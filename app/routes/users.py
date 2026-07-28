from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends
from .. import models, schemas
from ..database import get_db
import logging

logger = logging.getLogger("users")

# Router setup
router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# 1. Create User Endpoint (Tumhara existing code)
@router.post("/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    try:
        # 1. Check karo ki email/phone pehle se exist toh nahi karta
        existing_user = db.query(models.User).filter(
            (models.User.email == user.email) | (models.User.phone_number == user.phone_number)
        ).first()

        if existing_user:
            raise HTTPException(status_code=400, detail="Account with this Email or Phone Number already exists")

        # 2. Agar naya user hai, toh database model banao
        new_user = models.User(
            email=user.email, 
            full_name=user.full_name, 
            auth_provider=user.auth_provider,
            phone_number=user.phone_number
        )
        
        # 3. Database mein save karo
        db.add(new_user)
        db.commit()
        db.refresh(new_user) # ID aur created_at fetch karne ke liye
        
        # 4. Return new user (FastAPI automatically isko JSON mein convert kar dega)
        return new_user

    except HTTPException:
        # Custom HTTP exceptions (jaise 400 wala) ko as-is throw hone do
        raise
    except Exception as e:
        # Agar Database commit fail ho jaye (jaise DB down ho ya constraint error ho)
        db.rollback() 
        logger.error(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error while creating user account")

# 2. NAYA: Get User Profile Endpoint
@router.get("/profile", response_model=schemas.UserResponse)
def get_user_profile(
    email: str | None = Query(None),
    phone_number: str | None = Query(None),
    db: Session = Depends(get_db)
):
    if not email and not phone_number:
        raise HTTPException(status_code=400, detail="Provide at least email or phone number to fetch user")
 
    # Match on EITHER field, not just email-first. This matters because a
    # user's auth session can carry both email and phone even if the DB
    # record was originally created with only one of them — an email-only
    # filter would miss the match and wrongly return 404.
    conditions = []
    if email:
        conditions.append(models.User.email == email)
    if phone_number:
        conditions.append(models.User.phone_number == phone_number)
 
    user = db.query(models.User).filter(or_(*conditions)).first()
 
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
 
    return user
 