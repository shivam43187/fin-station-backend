import os
import razorpay
import hmac
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from uuid import UUID
from datetime import datetime, timedelta

from .. import models, schemas
from ..database import get_db

router = APIRouter(
    prefix="/subscriptions",
    tags=["Subscriptions"]
)

# Razorpay Client Setup
razorpay_client = razorpay.Client(
    auth=(os.getenv("RAZORPAY_KEY_ID"), os.getenv("RAZORPAY_KEY_SECRET"))
)

# Plan Pricing Mapping (In Paise - Razorpay accepts amount in paise)
PLAN_PRICES = {
    "STARTER": 14900,  # Rs. 149
    "PRO": 34900       # Rs. 349
}

# 1. CREATE ORDER ENDPOINT
@router.post("/create-order")
def create_subscription_order(user_id: UUID, plan_type: str, db: Session = Depends(get_db)):
    if plan_type not in PLAN_PRICES:
        raise HTTPException(status_code=400, detail="Invalid Plan Type")
    
    # Check if user exists
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    amount = PLAN_PRICES[plan_type]
    
    # Create order in Razorpay
    order_data = {
        "amount": amount,
        "currency": "INR",
        "receipt": f"receipt_{user_id}",
        "notes": {
            "user_id": str(user_id),
            "plan_type": plan_type
        }
    }
    
    try:
        order = razorpay_client.order.create(data=order_data)
        return {"order_id": order["id"], "amount": amount, "currency": "INR"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 2. WEBHOOK ENDPOINT (Razorpay calls this)
@router.post("/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    # 1. Get raw body and signature header
    payload = await request.body()
    razorpay_signature = request.headers.get("x-razorpay-signature")
    webhook_secret = os.getenv("RAZORPAY_WEBHOOK_SECRET")

    # 2. Verify Signature (Crucial for security)
    try:
        expected_signature = hmac.new(
            bytes(webhook_secret, 'utf-8'),
            msg=payload,
            digestmod=hashlib.sha256
        ).hexdigest()
        
        if expected_signature != razorpay_signature:
            raise HTTPException(status_code=400, detail="Invalid Signature")
    except Exception:
        raise HTTPException(status_code=400, detail="Signature Verification Failed")

    # 3. Parse JSON and update Database
    event = await request.json()
    
    if event['event'] == 'payment.captured':
        payment_entity = event['payload']['payment']['entity']
        notes = payment_entity.get('notes', {})
        
        user_id_str = notes.get('user_id')
        plan_type = notes.get('plan_type')
        
        if user_id_str and plan_type:
            # Update user's subscription in DB
            subscription = db.query(models.Subscription).filter(
                models.Subscription.user_id == user_id_str
            ).first()
            
            # 30 days validity logic
            valid_till = datetime.now() + timedelta(days=30)
            
            if subscription:
                subscription.plan_type = plan_type
                subscription.status = "active"
                subscription.current_period_end = valid_till
            else:
                new_sub = models.Subscription(
                    user_id=user_id_str,
                    plan_type=plan_type,
                    status="active",
                    current_period_start=datetime.now(),
                    current_period_end=valid_till
                )
                db.add(new_sub)
                
            db.commit()
            return {"status": "success", "message": "Subscription Updated"}
            
    return {"status": "ignored", "message": "Unhandled event type"}