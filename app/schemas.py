from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional

# --- USER SCHEMAS ---
class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None

class UserCreate(UserBase):
    auth_provider: str = "email"

class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True  # Pydantic v2 config (SQLAlchemy models ko JSON mein convert karne ke liye)

# --- WATCHLIST SCHEMAS ---
class WatchlistCreate(BaseModel):
    stock_symbol: str

class WatchlistResponse(BaseModel):
    id: UUID
    stock_symbol: str
    added_at: datetime

    class Config:
        from_attributes = True

# --- SUBSCRIPTION SCHEMAS ---
class SubscriptionResponse(BaseModel):
    id: UUID
    plan_type: str
    status: str
    current_period_end: Optional[datetime]

    class Config:
        from_attributes = True
