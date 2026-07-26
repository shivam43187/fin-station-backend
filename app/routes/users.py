from sqlalchemy import or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, HTTPException, Query, Depends
from .. import models, schemas
from ..database import get_db

# Router setup
router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# 1. Create User Endpoint (Tumhara existing code)
@router.post("/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
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
 