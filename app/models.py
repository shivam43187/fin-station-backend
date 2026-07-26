import uuid
from sqlalchemy import Column, String, Boolean, Integer, DateTime, ForeignKey, Enum, UniqueConstraint
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

    # [cite: 61]
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    phone_number = Column(String, unique=True, nullable=True)
    full_name = Column(String)
    auth_provider = Column(String, default="email")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True)

    # Relationships
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    usage = relationship("UserUsage", back_populates="user", cascade="all, delete-orphan")
    watchlists = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")
    reports_history = relationship("AIReportHistory", back_populates="user", cascade="all, delete-orphan")


class Subscription(Base):
    __tablename__ = "subscriptions"

    # [cite: 62]
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    plan_type = Column(Enum(PlanType), default=PlanType.FREE)
    razorpay_customer_id = Column(String, nullable=True)
    razorpay_subscription_id = Column(String, nullable=True)
    status = Column(String, default="active")
    current_period_start = Column(DateTime(timezone=True))
    current_period_end = Column(DateTime(timezone=True))

    user = relationship("User", back_populates="subscriptions")


class UserUsage(Base):
    __tablename__ = "user_usage"

    # [cite: 63]
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    billing_month = Column(String, nullable=False) # e.g., '2023-11'
    ai_reports_generated = Column(Integer, default=0)
    last_generated_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="usage")


class Watchlist(Base):
    __tablename__ = "watchlists"

    # [cite: 64]
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")) 
    stock_symbol = Column(String, nullable=False)
    added_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="watchlists")
    
    # Ensures a user can't add the same stock twice [cite: 64]
    __table_args__ = (UniqueConstraint('user_id', 'stock_symbol', name='_user_stock_uc'),)

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True)
    symbol = Column(String)
    target_price = Column(Float)
    condition = Column(String) # "ABOVE" or "BELOW"
    is_active = Column(Boolean, default=True)

class AIReportHistory(Base):
    __tablename__ = "ai_reports_history"

    # [cite: 66]
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    stock_symbol = Column(String, nullable=False)
    report_type = Column(Enum(ReportType), nullable=False)
    report_s3_url = Column(String, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="reports_history")