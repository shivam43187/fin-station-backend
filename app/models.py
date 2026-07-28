import uuid
from sqlalchemy import Column, String, Float, Boolean, Integer, DateTime, ForeignKey, Enum, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from .database import Base

# --- Enums for specific fields ---
class PlanType(enum.Enum):
    FREE = "FREE"
    STARTER = "STARTER"
    PRO = "PRO"

class ReportType(enum.Enum):
    EQUITY = "EQUITY"
    FUNDAMENTAL = "FUNDAMENTAL"
    DCF = "DCF"
    CONCALL = "CONCALL"

# --- Database Tables ---

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, unique=True, nullable=True)
    full_name = Column(String)
    auth_provider = Column(String, default="email")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships (Cascade ensure karta hai ki user delete ho toh uska saara data delete ho jaye)
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    usage = relationship("UserUsage", back_populates="user", cascade="all, delete-orphan")
    watchlists = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    reports_history = relationship("AIReportHistory", back_populates="user", cascade="all, delete-orphan")
    price_alerts = relationship("PriceAlert", back_populates="user", cascade="all, delete-orphan") # Added mapping


class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_type = Column(Enum(PlanType), default=PlanType.FREE)
    razorpay_customer_id = Column(String, nullable=True)
    razorpay_subscription_id = Column(String, nullable=True)
    status = Column(String, default="active")
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="subscriptions")


class UserUsage(Base):
    __tablename__ = "user_usage"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    billing_month = Column(String, nullable=False) # e.g., '2023-11'
    ai_reports_generated = Column(Integer, default=0)
    last_generated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="usage")


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False) 
    stock_symbol = Column(String, nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="watchlists")
    
    # Ensures a user can't add the same stock twice
    __table_args__ = (UniqueConstraint('user_id', 'stock_symbol', name='_user_stock_uc'),)


class PriceAlert(Base):
    __tablename__ = "price_alerts"

    # Fixed: Updated to UUID and user_id to match system architecture
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    symbol = Column(String, nullable=False)
    target_price = Column(Float, nullable=False)
    condition = Column(String, nullable=False) # "ABOVE" or "BELOW"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="price_alerts") # Relationship Added


class AIReportHistory(Base):
    __tablename__ = "ai_reports_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    stock_symbol = Column(String, nullable=False)
    report_type = Column(String, nullable=False) 
    report_s3_url = Column(String, nullable=True)
    content = Column(Text, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reports_history")