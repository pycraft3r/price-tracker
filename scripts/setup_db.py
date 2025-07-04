#!/usr/bin/env python3
"""
Database Setup Script
Creates all tables and initial data
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from sqlalchemy import text
from backend.database import engine, init_db
from backend.models import Base, User, Product, MarketplaceType, ProductStatus
import bcrypt
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def create_extensions(conn):
    """Create PostgreSQL extensions"""
    try:
        # Create UUID extension
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        logger.info("Created UUID extension")
        
        # Create pg_trgm for fuzzy text search
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))
        logger.info("Created pg_trgm extension")
        
    except Exception as e:
        logger.warning(f"Extension creation warning: {e}")

async def create_indexes(conn):
    """Create additional indexes for performance"""
    indexes = [
        # Product indexes
        "CREATE INDEX IF NOT EXISTS idx_product_user_status ON products(user_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_product_marketplace_id ON products(marketplace, marketplace_id)",
        "CREATE INDEX IF NOT EXISTS idx_product_last_checked ON products(last_checked)",
        "CREATE INDEX IF NOT EXISTS idx_product_title_trgm ON products USING gin(title gin_trgm_ops)",
        
        # Price history indexes
        "CREATE INDEX IF NOT EXISTS idx_price_history_product_date ON price_history(product_id, scraped_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(scraped_at DESC)",
        
        # Alert indexes
        "CREATE INDEX IF NOT EXISTS idx_alert_user_sent ON alerts(user_id, is_sent)",
        "CREATE INDEX IF NOT EXISTS idx_alert_triggered ON alerts(triggered_at DESC)",
        
        # User indexes
        "CREATE INDEX IF NOT EXISTS idx_user_active ON users(is_active) WHERE is_active = true",
    ]
    
    for index in indexes:
        try:
            await conn.execute(text(index))
            logger.info(f"Created index: {index.split(' ')[5]}")
        except Exception as e:
            logger.warning(f"Index creation warning: {e}")

async def create_demo_user(conn):
    """Create a demo user for testing"""
    try:
        # Check if demo user exists
        result = await conn.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": "demo@pricetracker.com"}
        )
        if result.scalar():
            logger.info("Demo user already exists")
            return
        
        # Create demo user
        password_hash = bcrypt.hashpw("demo123".encode(), bcrypt.gensalt()).decode()
        await conn.execute(
            text("""
                INSERT INTO users (id, email, username, password_hash, is_active, is_premium, created_at)
                VALUES (gen_random_uuid(), :email, :username, :password_hash, true, true, :created_at)
            """),
            {
                "email": "demo@pricetracker.com",
                "username": "demo",
                "password_hash": password_hash,
                "created_at": datetime.utcnow()
            }
        )
        logger.info("Created demo user (email: demo@pricetracker.com, password: demo123)")
        
    except Exception as e:
        logger.error(f"Error creating demo user: {e}")

async def setup_database():
    """Main database setup function"""
    logger.info("Starting database setup...")
    
    try:
        # Initialize database (create tables)
        await init_db()
        logger.info("Database tables created successfully")
        
        # Create extensions and indexes
        async with engine.begin() as conn:
            await create_extensions(conn)
            await create_indexes(conn)
            await create_demo_user(conn)
        
        logger.info("Database setup completed successfully!")
        
    except Exception as e:
        logger.error(f"Database setup failed: {e}")
        raise
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(setup_database())