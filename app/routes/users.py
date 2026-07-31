from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends
import logging

from .. import models, schemas
from ..database import get_db
from ..auth import verify_user_token

logger = logging.getLogger("users")

router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


# 1. Create User Endpoint
@router.post("/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        existing_user = db.query(models.User).filter(
            (models.User.email == user.email) | (models.User.phone_number == user.phone_number)
        ).first()

        if existing_user:
            raise HTTPException(status_code=400, detail="Account with this Email or Phone Number already exists")

        new_user = models.User(
            email=user.email,
            full_name=user.full_name,
            auth_provider=user.auth_provider,
            phone_number=user.phone_number
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error while creating user account")

@router.post("/sync", response_model=schemas.UserResponse)
def sync_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        conditions = [models.User.email == user.email]
        if user.phone_number:  # only match on phone if a real value was sent
            conditions.append(models.User.phone_number == user.phone_number)

        existing_user = db.query(models.User).filter(or_(*conditions)).first()

        if existing_user:
            return existing_user

        new_user = models.User(
            email=user.email,
            full_name=user.full_name,
            auth_provider=user.auth_provider,
            phone_number=user.phone_number
        )

        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return new_user

    except Exception as e:
        db.rollback()
        logger.error(f"Error syncing user: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error while syncing user account")


# 2. Get User Profile Endpoint
@router.get("/profile", response_model=schemas.UserResponse)
def get_user_profile(
    email: str | None = Query(None),
    db: Session = Depends(get_db),
    auth_payload: dict = Depends(verify_user_token)
):
    try:
        token_email = auth_payload.get("email")

        if not email:
            raise HTTPException(
                status_code=400,
                detail="Email is required."
            )

        if token_email and email != token_email:
            raise HTTPException(
                status_code=403,
                detail="Access denied. You can only fetch your own profile."
            )

        user = (
            db.query(models.User)
            .filter(models.User.email == email)
            .first()
        )

        if not user:
            raise HTTPException(
                status_code=404,
                detail="User not found"
            )

        return user

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )