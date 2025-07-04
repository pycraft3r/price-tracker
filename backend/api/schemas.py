"""
Pydantic schemas for API validation
Type-safe request/response models
"""

from pydantic import BaseModel, EmailStr, HttpUrl, Field, ConfigDict, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
import enum

class MarketplaceType(str, enum.Enum):
    """Supported marketplaces"""
    AMAZON = "amazon"
    EBAY = "ebay"
    ALIEXPRESS = "aliexpress"

class ProductStatus(str, enum.Enum):
    """Product tracking status"""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISCONTINUED = "discontinued"

class AlertType(str, enum.Enum):
    """Alert types"""
    PRICE_DROP = "price_drop"
    PRICE_INCREASE = "price_increase"
    BACK_IN_STOCK = "back_in_stock"
    NEW_LOW = "new_low"

# User schemas
class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)

class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=100)
    notification_settings: Optional[Dict[str, Any]] = None

class UserResponse(UserBase):
    id: UUID
    is_active: bool
    is_premium: bool
    created_at: datetime
    notification_settings: Dict[str, Any]
    api_calls_today: int
    
    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 3600

# Product schemas
class ProductBase(BaseModel):
    marketplace: MarketplaceType
    url: HttpUrl
    target_price: Optional[float] = Field(None, gt=0)
    check_interval_hours: int = Field(6, ge=1, le=168)

class ProductCreate(ProductBase):
    pass

class ProductUpdate(BaseModel):
    target_price: Optional[float] = Field(None, gt=0)
    check_interval_hours: Optional[int] = Field(None, ge=1, le=168)
    status: Optional[ProductStatus] = None

class ProductResponse(ProductBase):
    id: UUID
    marketplace_id: str
    title: str
    description: Optional[str]
    image_url: Optional[str]
    brand: Optional[str]
    category: Optional[str]
    status: ProductStatus
    current_price: Optional[float]
    currency: str
    in_stock: bool
    last_checked: Optional[datetime]
    min_price: Optional[float]
    max_price: Optional[float]
    avg_price: Optional[float]
    price_checks_count: int
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class ProductListResponse(BaseModel):
    items: List[ProductResponse]
    total: int
    page: int
    page_size: int
    pages: int

# Price history schemas
class PriceHistoryResponse(BaseModel):
    id: UUID
    price: float
    currency: str
    in_stock: bool
    shipping_cost: Optional[float]
    seller_name: Optional[str]
    seller_rating: Optional[float]
    reviews_count: Optional[int]
    scraped_at: datetime
    
    model_config = ConfigDict(from_attributes=True)

class PriceHistoryListResponse(BaseModel):
    items: List[PriceHistoryResponse]
    total: int
    oldest: Optional[datetime]
    newest: Optional[datetime]

# Alert schemas
class AlertCreate(BaseModel):
    product_id: UUID
    alert_type: AlertType
    threshold_value: Optional[float] = Field(None, description="Price or percentage threshold")

class AlertResponse(BaseModel):
    id: UUID
    product_id: UUID
    alert_type: AlertType
    threshold_value: Optional[float]
    triggered_at: datetime
    old_price: float
    new_price: float
    price_change_percent: float
    is_sent: bool
    sent_at: Optional[datetime]
    
    model_config = ConfigDict(from_attributes=True)

class AlertListResponse(BaseModel):
    items: List[AlertResponse]
    total: int
    unread_count: int

# Analytics schemas
class PriceAnalytics(BaseModel):
    product_id: UUID
    current_price: float
    min_price: float
    max_price: float
    avg_price: float
    price_volatility: float
    trend: str  # "increasing", "decreasing", "stable"
    best_time_to_buy: str
    price_predictions: Dict[str, float]  # Next 7, 14, 30 days

class DashboardAnalytics(BaseModel):
    total_products: int
    active_products: int
    total_alerts: int
    alerts_today: int
    avg_price_drop_percent: float
    total_savings: float
    most_tracked_categories: List[Dict[str, Any]]
    price_drop_opportunities: List[ProductResponse]

# WebSocket schemas
class WSMessage(BaseModel):
    event: str
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)

class WSPriceUpdate(BaseModel):
    product_id: UUID
    old_price: float
    new_price: float
    currency: str
    change_percent: float
    timestamp: datetime

# Error schemas
class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    request_id: Optional[str] = None

# Bulk operation schemas
class BulkProductCreate(BaseModel):
    urls: List[HttpUrl] = Field(..., max_length=100)
    marketplace: MarketplaceType
    target_price: Optional[float] = Field(None, gt=0)
    check_interval_hours: int = Field(6, ge=1, le=168)

class BulkOperationResponse(BaseModel):
    success_count: int
    failure_count: int
    results: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]