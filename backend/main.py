"""
Main FastAPI Application
Handles 50K+ products daily with enterprise-grade performance
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from contextlib import asynccontextmanager
import uvicorn
import logging
from datetime import datetime
import os
from dotenv import load_dotenv
import redis.asyncio as redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import socketio
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from fastapi.responses import Response

from api.routes import router as api_router
from database import init_db, get_db_session
from scraper import ScraperManager
from utils.alerts import AlertManager

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Metrics
request_count = Counter('price_tracker_requests_total', 'Total requests')
request_duration = Histogram('price_tracker_request_duration_seconds', 'Request duration')
scrape_count = Counter('price_tracker_scrapes_total', 'Total scrapes', ['site', 'status'])

# Create logs directory
os.makedirs('logs', exist_ok=True)

# Initialize scheduler
scheduler = AsyncIOScheduler()

# Socket.IO for real-time updates
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=os.getenv("CORS_ORIGINS", "*").split(",")
)
socket_app = socketio.ASGIApp(sio)

# Global instances
redis_client = None
scraper_manager = None
alert_manager = None

async def scrape_products_job():
    """Scheduled job to scrape products"""
    global scraper_manager
    try:
        logger.info("Starting scheduled product scraping...")
        await scraper_manager.scrape_all_products()
        scrape_count.labels(site='all', status='success').inc()
    except Exception as e:
        logger.error(f"Scheduled scraping failed: {e}")
        scrape_count.labels(site='all', status='failure').inc()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle"""
    global redis_client, scraper_manager, alert_manager
    
    # Startup
    logger.info("Starting Price Tracker API...")
    
    # Initialize database
    await init_db()
    
    # Initialize Redis
    redis_client = await redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379"),
        encoding="utf-8",
        decode_responses=True
    )
    
    # Initialize managers
    scraper_manager = ScraperManager(redis_client)
    alert_manager = AlertManager(redis_client)
    
    # Configure scheduler
    scheduler.add_job(
        scrape_products_job,
        IntervalTrigger(hours=int(os.getenv("SCRAPE_INTERVAL_HOURS", "4"))),
        id='product_scraping',
        replace_existing=True
    )
    scheduler.start()
    
    logger.info("Price Tracker API started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Price Tracker API...")
    scheduler.shutdown()
    await redis_client.close()
    logger.info("Shutdown complete")

# Create FastAPI app
app = FastAPI(
    title="Price Tracker API",
    description="Enterprise-grade e-commerce price monitoring system handling 50K+ products daily",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# Configure middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("ALLOWED_HOSTS", "*").split(",")
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")

# Mount Socket.IO app
app.mount("/ws", socket_app)

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0",
        "redis": "connected" if redis_client else "disconnected"
    }

# Metrics endpoint
@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint"""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

# Socket.IO events
@sio.event
async def connect(sid, environ):
    """Handle WebSocket connection"""
    logger.info(f"Client connected: {sid}")
    await sio.emit('connected', {'message': 'Welcome to Price Tracker'}, room=sid)

@sio.event
async def disconnect(sid):
    """Handle WebSocket disconnection"""
    logger.info(f"Client disconnected: {sid}")

@sio.event
async def subscribe_product(sid, data):
    """Subscribe to real-time updates for a product"""
    product_id = data.get('product_id')
    if product_id:
        await sio.enter_room(sid, f"product_{product_id}")
        await sio.emit('subscribed', {'product_id': product_id}, room=sid)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("ENV", "development") == "development",
        log_level=os.getenv("LOG_LEVEL", "info").lower()
    )