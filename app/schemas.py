from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime
from typing import Optional

# --- USER SCHEMAS ---
class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    auth_provider: str
    phone_number: str

class UserCreate(UserBase):
    auth_provider: str = "email"

class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    is_active: bool

    class Config:
        from_attributes = True  # (orm_mode in older Pydantic)

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
