from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from .. import models, schemas
from ..database import get_db

# Router setup
router = APIRouter(
    prefix="/users",
    tags=["Users"]
)

# Create User Endpoint
@router.post("/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # 1. Check karo ki email pehle se exist toh nahi karta
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # 2. Agar naya user hai, toh database model banao
    new_user = models.User(
        email=user.email, 
        full_name=user.full_name, 
        auth_provider=user.auth_provider
    )
    
    # 3. Database mein save karo
    db.add(new_user)
    db.commit()
    db.refresh(new_user) # ID aur created_at fetch karne ke liye
    
    # 4. Return new user (FastAPI automatically isko JSON mein convert kar dega)
    return new_user