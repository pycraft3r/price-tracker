"""
API Routes
High-performance endpoints for price tracking operations
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import selectinload
from typing import List, Optional
from datetime import datetime, timedelta
from uuid import UUID
import jwt
import bcrypt
import os
from dotenv import load_dotenv

from database import get_db
from models import User, Product, PriceHistory, Alert, ProductStatus, AlertType
from .schemas import (
    UserCreate, UserResponse, UserLogin, TokenResponse,
    ProductCreate, ProductResponse, ProductListResponse,
    PriceHistoryResponse, PriceHistoryListResponse,
    AlertResponse, AlertListResponse,
    DashboardAnalytics, PriceAnalytics,
    BulkProductCreate, BulkOperationResponse,
    ErrorResponse
)

load_dotenv()

router = APIRouter()
security = HTTPBearer()

SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here")
ALGORITHM = "HS256"

# Utility functions
def create_access_token(user_id: str) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + timedelta(hours=24)
    payload = {
        "sub": user_id,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify JWT token and return user_id"""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

async def get_current_user(
    user_id: str = Depends(verify_token),
    db: AsyncSession = Depends(get_db)
) -> User:
    """Get current authenticated user"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Authentication endpoints
@router.post("/auth/register", response_model=UserResponse, status_code=201)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register new user"""
    # Check if user exists
    existing = await db.execute(
        select(User).where(or_(User.email == user_data.email, User.username == user_data.username))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="User already exists")
    
    # Hash password
    password_hash = bcrypt.hashpw(user_data.password.encode(), bcrypt.gensalt()).decode()
    
    # Create user
    user = User(
        email=user_data.email,
        username=user_data.username,
        password_hash=password_hash
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return user

@router.post("/auth/login", response_model=TokenResponse)
async def login(credentials: UserLogin, db: AsyncSession = Depends(get_db)):
    """User login"""
    result = await db.execute(select(User).where(User.username == credentials.username))
    user = result.scalar_one_or_none()
    
    if not user or not bcrypt.checkpw(credentials.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")
    
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)

# Product endpoints
@router.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(
    product_data: ProductCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create new product tracking"""
    # Check user limits
    if not current_user.is_premium:
        count = await db.execute(
            select(func.count(Product.id)).where(Product.user_id == current_user.id)
        )
        if count.scalar() >= 50:  # Free tier limit
            raise HTTPException(status_code=403, detail="Product limit reached")
    
    # Create product
    product = Product(
        user_id=current_user.id,
        marketplace=product_data.marketplace,
        url=str(product_data.url),
        target_price=product_data.target_price,
        check_interval_hours=product_data.check_interval_hours
    )
    
    db.add(product)
    await db.commit()
    await db.refresh(product)
    
    # Schedule initial scraping
    from scraper import scrape_product_task
    background_tasks.add_task(scrape_product_task, str(product.id))
    
    return product

@router.get("/products", response_model=ProductListResponse)
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[ProductStatus] = None,
    marketplace: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List user's tracked products"""
    query = select(Product).where(Product.user_id == current_user.id)
    
    # Apply filters
    if status:
        query = query.where(Product.status == status)
    if marketplace:
        query = query.where(Product.marketplace == marketplace)
    if search:
        query = query.where(Product.title.ilike(f"%{search}%"))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.execute(count_query)
    total_count = total.scalar()
    
    # Paginate
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(Product.created_at.desc())
    
    result = await db.execute(query)
    products = result.scalars().all()
    
    return ProductListResponse(
        items=products,
        total=total_count,
        page=page,
        page_size=page_size,
        pages=(total_count + page_size - 1) // page_size
    )

@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get product details"""
    result = await db.execute(
        select(Product).where(
            and_(Product.id == product_id, Product.user_id == current_user.id)
        )
    )
    product = result.scalar_one_or_none()
    
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return product

# Price history endpoints
@router.get("/products/{product_id}/prices", response_model=PriceHistoryListResponse)
async def get_price_history(
    product_id: UUID,
    days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get product price history"""
    # Verify product ownership
    product = await db.execute(
        select(Product).where(
            and_(Product.id == product_id, Product.user_id == current_user.id)
        )
    )
    if not product.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Product not found")
    
    # Get price history
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(PriceHistory)
        .where(and_(PriceHistory.product_id == product_id, PriceHistory.scraped_at >= since))
        .order_by(PriceHistory.scraped_at.desc())
    )
    history = result.scalars().all()
    
    # Get date range
    oldest = min([h.scraped_at for h in history]) if history else None
    newest = max([h.scraped_at for h in history]) if history else None
    
    return PriceHistoryListResponse(
        items=history,
        total=len(history),
        oldest=oldest,
        newest=newest
    )

# Alert endpoints
@router.get("/alerts", response_model=AlertListResponse)
async def list_alerts(
    unread_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """List user's alerts"""
    query = select(Alert).where(Alert.user_id == current_user.id)
    
    if unread_only:
        query = query.where(Alert.is_sent == False)
    
    query = query.order_by(Alert.triggered_at.desc()).limit(limit)
    
    result = await db.execute(query.options(selectinload(Alert.product)))
    alerts = result.scalars().all()
    
    # Count unread
    unread_count = await db.execute(
        select(func.count(Alert.id)).where(
            and_(Alert.user_id == current_user.id, Alert.is_sent == False)
        )
    )
    
    return AlertListResponse(
        items=alerts,
        total=len(alerts),
        unread_count=unread_count.scalar()
    )

# Analytics endpoints
@router.get("/analytics/dashboard", response_model=DashboardAnalytics)
async def get_dashboard_analytics(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get dashboard analytics"""
    # Product stats
    total_products = await db.execute(
        select(func.count(Product.id)).where(Product.user_id == current_user.id)
    )
    active_products = await db.execute(
        select(func.count(Product.id)).where(
            and_(Product.user_id == current_user.id, Product.status == ProductStatus.ACTIVE)
        )
    )
    
    # Alert stats
    total_alerts = await db.execute(
        select(func.count(Alert.id)).where(Alert.user_id == current_user.id)
    )
    today_alerts = await db.execute(
        select(func.count(Alert.id)).where(
            and_(
                Alert.user_id == current_user.id,
                Alert.triggered_at >= datetime.utcnow().date()
            )
        )
    )
    
    # Calculate average price drop
    price_drops = await db.execute(
        select(Alert.price_change_percent).where(
            and_(
                Alert.user_id == current_user.id,
                Alert.alert_type == AlertType.PRICE_DROP
            )
        )
    )
    drops = price_drops.scalars().all()
    avg_drop = sum(drops) / len(drops) if drops else 0
    
    # Total savings calculation
    savings_query = await db.execute(
        select(func.sum(Alert.old_price - Alert.new_price)).where(
            and_(
                Alert.user_id == current_user.id,
                Alert.alert_type == AlertType.PRICE_DROP
            )
        )
    )
    total_savings = savings_query.scalar() or 0
    
    # Most tracked categories
    categories = await db.execute(
        select(Product.category, func.count(Product.id).label('count'))
        .where(Product.user_id == current_user.id)
        .group_by(Product.category)
        .order_by(func.count(Product.id).desc())
        .limit(5)
    )
    
    # Recent price drops
    opportunities = await db.execute(
        select(Product)
        .join(Alert)
        .where(
            and_(
                Product.user_id == current_user.id,
                Alert.alert_type == AlertType.PRICE_DROP,
                Alert.triggered_at >= datetime.utcnow() - timedelta(days=7)
            )
        )
        .order_by(Alert.price_change_percent.desc())
        .limit(10)
    )
    
    return DashboardAnalytics(
        total_products=total_products.scalar(),
        active_products=active_products.scalar(),
        total_alerts=total_alerts.scalar(),
        alerts_today=today_alerts.scalar(),
        avg_price_drop_percent=abs(avg_drop),
        total_savings=total_savings,
        most_tracked_categories=[
            {"category": cat or "Uncategorized", "count": count}
            for cat, count in categories
        ],
        price_drop_opportunities=opportunities.scalars().all()
    )

@router.get("/analytics/product/{product_id}", response_model=PriceAnalytics)
async def get_product_analytics(
    product_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed product analytics"""
    # Implementation would include price prediction ML model
    # For now, returning mock data
    product = await db.execute(
        select(Product).where(
            and_(Product.id == product_id, Product.user_id == current_user.id)
        )
    )
    p = product.scalar_one_or_none()
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    
    return PriceAnalytics(
        product_id=product_id,
        current_price=p.current_price or 0,
        min_price=p.min_price or 0,
        max_price=p.max_price or 0,
        avg_price=p.avg_price or 0,
        price_volatility=0.15,  # Mock
        trend="stable",
        best_time_to_buy="Weekend mornings",
        price_predictions={"7_days": p.current_price * 0.98, "14_days": p.current_price * 0.97}
    )

# Bulk operations
@router.post("/products/bulk", response_model=BulkOperationResponse)
async def bulk_create_products(
    bulk_data: BulkProductCreate,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Bulk create products"""
    results = []
    errors = []
    
    for url in bulk_data.urls:
        try:
            product = Product(
                user_id=current_user.id,
                marketplace=bulk_data.marketplace,
                url=str(url),
                target_price=bulk_data.target_price,
                check_interval_hours=bulk_data.check_interval_hours
            )
            db.add(product)
            await db.flush()
            results.append({"url": str(url), "product_id": str(product.id), "status": "created"})
            
            from scraper import scrape_product_task
            background_tasks.add_task(scrape_product_task, str(product.id))
            
        except Exception as e:
            errors.append({"url": str(url), "error": str(e)})
    
    await db.commit()
    
    return BulkOperationResponse(
        success_count=len(results),
        failure_count=len(errors),
        results=results,
        errors=errors
    )