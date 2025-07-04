"""
SQLAlchemy Database Models
Optimized for high-volume price tracking operations
"""

from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Boolean, 
    ForeignKey, Index, Text, JSON, Enum as SQLEnum,
    UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from database import Base
import uuid
import enum
from datetime import datetime

class ProductStatus(enum.Enum):
    """Product tracking status"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISCONTINUED = "discontinued"

class AlertType(enum.Enum):
    """Alert trigger types"""
    PRICE_DROP = "price_drop"
    PRICE_INCREASE = "price_increase"
    BACK_IN_STOCK = "back_in_stock"
    NEW_LOW = "new_low"

class MarketplaceType(enum.Enum):
    """Supported marketplaces"""
    AMAZON = "amazon"
    EBAY = "ebay"
    ALIEXPRESS = "aliexpress"

class User(Base):
    """User model with authentication"""
    __tablename__ = "users"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    is_premium = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Settings
    notification_settings = Column(JSON, default={
        "email": True,
        "webhook": False,
        "webhook_url": None
    })
    
    # Rate limiting
    api_calls_today = Column(Integer, default=0, nullable=False)
    last_api_call = Column(DateTime(timezone=True))
    
    # Relationships
    products = relationship("Product", back_populates="user", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_user_email_active', 'email', 'is_active'),
    )

class Product(Base):
    """Product tracking model"""
    __tablename__ = "products"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    marketplace = Column(SQLEnum(MarketplaceType), nullable=False, index=True)
    marketplace_id = Column(String(255), nullable=False)  # ASIN, eBay ID, etc.
    url = Column(Text, nullable=False)
    
    # Product details
    title = Column(String(500), nullable=False)
    description = Column(Text)
    image_url = Column(Text)
    brand = Column(String(255))
    category = Column(String(255), index=True)
    
    # Tracking settings
    status = Column(SQLEnum(ProductStatus), default=ProductStatus.ACTIVE, nullable=False, index=True)
    target_price = Column(Float)  # Alert when price drops below this
    check_interval_hours = Column(Integer, default=6, nullable=False)
    
    # Current state
    current_price = Column(Float)
    currency = Column(String(3), default="USD", nullable=False)
    in_stock = Column(Boolean, default=True, nullable=False)
    last_checked = Column(DateTime(timezone=True))
    last_error = Column(Text)
    error_count = Column(Integer, default=0, nullable=False)
    
    # Statistics
    min_price = Column(Float)
    max_price = Column(Float)
    avg_price = Column(Float)
    price_checks_count = Column(Integer, default=0, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    # Relationships
    user = relationship("User", back_populates="products")
    price_history = relationship("PriceHistory", back_populates="product", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="product", cascade="all, delete-orphan")
    
    __table_args__ = (
        UniqueConstraint('user_id', 'marketplace', 'marketplace_id', name='uq_user_marketplace_product'),
        Index('idx_product_status_check', 'status', 'last_checked'),
        Index('idx_product_marketplace', 'marketplace', 'marketplace_id'),
        CheckConstraint('target_price > 0', name='check_positive_target_price'),
        CheckConstraint('check_interval_hours >= 1 AND check_interval_hours <= 168', name='check_interval_range'),
    )

class PriceHistory(Base):
    """Historical price tracking"""
    __tablename__ = "price_history"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    
    price = Column(Float, nullable=False)
    currency = Column(String(3), default="USD", nullable=False)
    in_stock = Column(Boolean, default=True, nullable=False)
    
    # Additional data
    shipping_cost = Column(Float, default=0)
    seller_name = Column(String(255))
    seller_rating = Column(Float)
    reviews_count = Column(Integer)
    
    # Metadata
    scraped_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    response_time_ms = Column(Integer)  # Track scraping performance
    
    # Relationships
    product = relationship("Product", back_populates="price_history")
    
    __table_args__ = (
        Index('idx_price_history_product_time', 'product_id', 'scraped_at'),
        Index('idx_price_history_time', 'scraped_at'),
        CheckConstraint('price >= 0', name='check_non_negative_price'),
    )

class Alert(Base):
    """Price alerts and notifications"""
    __tablename__ = "alerts"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    
    alert_type = Column(SQLEnum(AlertType), nullable=False, index=True)
    threshold_value = Column(Float)  # Price threshold or percentage
    
    # Alert details
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    old_price = Column(Float, nullable=False)
    new_price = Column(Float, nullable=False)
    price_change_percent = Column(Float, nullable=False)
    
    # Notification status
    is_sent = Column(Boolean, default=False, nullable=False, index=True)
    sent_at = Column(DateTime(timezone=True))
    notification_method = Column(String(50))  # email, webhook, etc.
    error_message = Column(Text)
    
    # Relationships
    user = relationship("User", back_populates="alerts")
    product = relationship("Product", back_populates="alerts")
    
    __table_args__ = (
        Index('idx_alert_user_sent', 'user_id', 'is_sent'),
        Index('idx_alert_triggered', 'triggered_at'),
    )