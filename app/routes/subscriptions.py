import os
import hmac
import hashlib
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timedelta

import razorpay

from app.auth import verify_user_token

from .. import models, schemas
from ..database import get_db

logger = logging.getLogger("subscriptions")

router = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])

razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

# ---------------------------------------------------------------------------
# PLAN CONFIG
# ---------------------------------------------------------------------------
# report_limit: None = unlimited
PLAN_CONFIG = {
    "STARTER": {"amount": 14900, "report_limit": 15, "razorpay_plan_id": os.getenv("RAZORPAY_PLAN_STARTER")},
    "PRO":     {"amount": 34900, "report_limit": None, "razorpay_plan_id": os.getenv("RAZORPAY_PLAN_PRO")},
}
FREE_PLAN_REPORT_LIMIT = 2

# NOTE: RAZORPAY_PLAN_STARTER / RAZORPAY_PLAN_PRO must be created once in the
# Razorpay Dashboard (Subscriptions > Plans) or via razorpay_client.plan.create(...).
# A Plan defines the recurring amount + billing interval; a Subscription is an
# instance of a customer subscribing to that plan with an auto-debit mandate.


# ---------------------------------------------------------------------------
# 1. CREATE SUBSCRIPTION (replaces one-time order — this is what enables
#    auto-renewal, since it registers a recurring mandate with the customer)
# ---------------------------------------------------------------------------
@router.post("/create-order")
def create_subscription_order(user_id: UUID, plan_type: str, db: Session = Depends(get_db), auth_payload: dict = Depends(verify_user_token)):
    if plan_type not in PLAN_CONFIG:
        raise HTTPException(status_code=400, detail="Invalid Plan Type")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    plan_cfg = PLAN_CONFIG[plan_type]
    if not plan_cfg["razorpay_plan_id"]:
        # Fails loudly instead of silently creating a one-time order that
        # would never auto-renew.
        raise HTTPException(
            status_code=500,
            detail=f"No Razorpay plan configured for {plan_type}. Set RAZORPAY_PLAN_{plan_type} env var."
        )

    try:
        subscription = razorpay_client.subscription.create({
            "plan_id": plan_cfg["razorpay_plan_id"],
            "customer_notify": 1,       # Razorpay sends the customer payment + renewal notices, including pre-debit notice for e-mandate/UPI Autopay
            "total_count": 120,         # e.g. up to 10 years of monthly cycles; required by the API
            "notes": {
                "user_id": str(user_id),
                "plan_type": plan_type
            }
        })
        return {
            "subscription_id": subscription["id"],
            "razorpay_key_id": os.getenv("RAZORPAY_KEY_ID"),
            "plan_type": plan_type
        }
    except Exception as e:
        logger.error(f"Failed to create subscription for {user_id}: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# 2. WEBHOOK
# ---------------------------------------------------------------------------
@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db), auth_payload: dict = Depends(verify_user_token)):
    payload = await request.body()
    razorpay_signature = request.headers.get("x-razorpay-signature")
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    if not razorpay_signature or not webhook_secret:
        raise HTTPException(status_code=400, detail="Missing signature or webhook secret")

    expected_signature = hmac.new(
        bytes(webhook_secret, "utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()

    # constant-time comparison — plain `!=` leaks timing info that can be
    # used to brute-force a valid signature
    if not hmac.compare_digest(expected_signature, razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid Signature")

    event = await request.json()
    event_type = event.get("event")
    logger.info(f"Razorpay webhook received: {event_type}")

    # --- subscription.charged: fires on every successful renewal AND the first payment ---
    if event_type == "subscription.charged":
        payload_data = event["payload"]
        payment_entity = payload_data["payment"]["entity"]
        subscription_entity = payload_data["subscription"]["entity"]

        razorpay_sub_id = subscription_entity["id"]
        payment_id = payment_entity["id"]
        notes = subscription_entity.get("notes", {})
        user_id_str = notes.get("user_id")
        plan_type = notes.get("plan_type")

        if not user_id_str or plan_type not in PLAN_CONFIG:
            logger.warning(f"subscription.charged missing/invalid notes: {notes}")
            return {"status": "ignored", "message": "Missing plan/user info in notes"}

        # Idempotency guard: Razorpay retries webhooks on timeout/non-2xx.
        # If we've already applied this exact payment, skip re-processing.
        existing = db.query(models.Subscription).filter(
            models.Subscription.razorpay_subscription_id == razorpay_sub_id
        ).first()
        if existing and getattr(existing, "last_payment_id", None) == payment_id:
            return {"status": "ignored", "message": "Already processed"}

        report_limit = PLAN_CONFIG[plan_type]["report_limit"]
        valid_till = datetime.now() + timedelta(days=30)

        if existing:
            existing.plan_type = plan_type
            existing.status = "active"
            existing.current_period_start = datetime.now()
            existing.current_period_end = valid_till
            existing.reports_used = 0            # reset quota on each renewal
            existing.reports_limit = report_limit
            existing.last_payment_id = payment_id
        else:
            db.add(models.Subscription(
                user_id=user_id_str,
                razorpay_subscription_id=razorpay_sub_id,
                plan_type=plan_type,
                status="active",
                current_period_start=datetime.now(),
                current_period_end=valid_till,
                reports_used=0,
                reports_limit=report_limit,
                last_payment_id=payment_id
            ))

        db.commit()
        return {"status": "success", "message": "Subscription activated/renewed"}

    # --- subscription.cancelled / completed / halted: stop granting paid access ---
    if event_type in ("subscription.cancelled", "subscription.completed", "subscription.halted"):
        subscription_entity = event["payload"]["subscription"]["entity"]
        razorpay_sub_id = subscription_entity["id"]

        sub = db.query(models.Subscription).filter(
            models.Subscription.razorpay_subscription_id == razorpay_sub_id
        ).first()
        if sub:
            sub.status = "cancelled" if event_type != "subscription.halted" else "halted"
            db.commit()
        return {"status": "success", "message": f"Subscription marked {event_type}"}

    return {"status": "ignored", "message": "Unhandled event type"}


# ---------------------------------------------------------------------------
# 3. GET CURRENT PLAN (for the pricing page + gating checks)
# ---------------------------------------------------------------------------
FREE_PLAN_RESPONSE = {
    "plan_type": "FREE",
    "status": "active",
    "reports_used": 0,          # TODO: wire to your actual free-tier usage tracking
    "reports_limit": FREE_PLAN_REPORT_LIMIT,
    "current_period_end": None,
}


@router.get("/me")
def get_my_subscription(
    email: str | None = None,
    phone_number: str | None = None,
    db: Session = Depends(get_db),
    auth_payload: dict = Depends(verify_user_token)
):
    if not email and not phone_number:
        raise HTTPException(status_code=400, detail="Provide at least email or phone number")

    conditions = []
    if email:
        conditions.append(models.User.email == email)
    if phone_number:
        conditions.append(models.User.phone_number == phone_number)

    from sqlalchemy import or_
    user = db.query(models.User).filter(or_(*conditions)).first()

    if not user:
        # No account yet in our DB — treat as free tier rather than error,
        # since this endpoint is used to render the pricing page.
        return FREE_PLAN_RESPONSE

    subscription = db.query(models.Subscription).filter(
        models.Subscription.user_id == user.id,
        models.Subscription.status == "active"
    ).first()

    if not subscription:
        return FREE_PLAN_RESPONSE

    # A subscription past its current_period_end shouldn't still grant paid access
    # (covers the case where a renewal charge failed and no webhook update landed yet)
    if subscription.current_period_end and subscription.current_period_end < datetime.now():
        return FREE_PLAN_RESPONSE

    return {
        "plan_type": subscription.plan_type,
        "status": subscription.status,
        "reports_used": subscription.reports_used,
        "reports_limit": subscription.reports_limit,
        "current_period_end": subscription.current_period_end,
    }