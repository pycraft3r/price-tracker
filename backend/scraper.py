"""
Web Scraper Module
Handles concurrent scraping for 50K+ products daily with proxy rotation
"""

import asyncio
import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, WebDriverException
import random
import logging
from typing import Dict, Optional, List, Tuple
from datetime import datetime
import re
from urllib.parse import urlparse, parse_qs
import json
import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
import time

from database import get_db_session
from models import Product, PriceHistory, Alert, ProductStatus, AlertType, MarketplaceType
from utils.proxy_manager import ProxyManager
from utils.alerts import send_alert

logger = logging.getLogger(__name__)

class ScraperManager:
    """Manages scraping operations with rate limiting and proxy rotation"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis_client = redis_client
        self.proxy_manager = ProxyManager()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
        ]
        self.semaphore = asyncio.Semaphore(50)  # Concurrent scraping limit
        
    async def scrape_all_products(self):
        """Scrape all active products"""
        async with get_db_session() as db:
            # Get products that need scraping
            result = await db.execute(
                select(Product).where(
                    Product.status == ProductStatus.ACTIVE,
                    Product.last_checked < datetime.utcnow() - timedelta(hours=Product.check_interval_hours)
                ).limit(5000)  # Batch size
            )
            products = result.scalars().all()
            
            logger.info(f"Starting scraping for {len(products)} products")
            
            # Scrape products concurrently
            tasks = [self._scrape_with_limit(product) for product in products]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            logger.info(f"Scraping completed: {success_count}/{len(products)} successful")
    
    async def _scrape_with_limit(self, product: Product):
        """Scrape with semaphore limit"""
        async with self.semaphore:
            return await self.scrape_product(product)
    
    async def scrape_product(self, product: Product) -> Optional[Dict]:
        """Scrape a single product"""
        start_time = time.time()
        
        try:
            # Choose scraper based on marketplace
            if product.marketplace == MarketplaceType.AMAZON:
                data = await self._scrape_amazon(product.url)
            elif product.marketplace == MarketplaceType.EBAY:
                data = await self._scrape_ebay(product.url)
            elif product.marketplace == MarketplaceType.ALIEXPRESS:
                data = await self._scrape_aliexpress(product.url)
            else:
                raise ValueError(f"Unsupported marketplace: {product.marketplace}")
            
            if data:
                # Update product and save history
                await self._update_product_data(product, data, time.time() - start_time)
                
                # Check for price alerts
                await self._check_alerts(product, data)
                
                # Emit real-time update
                await self._emit_price_update(product, data)
                
            return data
            
        except Exception as e:
            logger.error(f"Error scraping product {product.id}: {e}")
            await self._handle_scraping_error(product, str(e))
            return None
    
    async def _scrape_amazon(self, url: str) -> Optional[Dict]:
        """Scrape Amazon product"""
        proxy = await self.proxy_manager.get_proxy()
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection': 'keep-alive',
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, proxy=proxy, timeout=30) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract ASIN
                    asin_match = re.search(r'/dp/([A-Z0-9]{10})', url)
                    asin = asin_match.group(1) if asin_match else None
                    
                    # Extract price
                    price_element = soup.select_one('.a-price-whole, .a-price.a-text-price.a-size-medium.apexPriceToPay, .a-price-range')
                    price = None
                    if price_element:
                        price_text = price_element.text.strip()
                        price_match = re.search(r'[\d,]+\.?\d*', price_text)
                        if price_match:
                            price = float(price_match.group().replace(',', ''))
                    
                    # Extract title
                    title = soup.select_one('#productTitle')
                    title_text = title.text.strip() if title else "Unknown Product"
                    
                    # Extract availability
                    availability = soup.select_one('#availability span')
                    in_stock = "in stock" in availability.text.lower() if availability else True
                    
                    # Extract additional data
                    brand = soup.select_one('a#bylineInfo')
                    brand_text = brand.text.strip().replace('Brand: ', '') if brand else None
                    
                    rating = soup.select_one('span.a-icon-alt')
                    rating_value = None
                    if rating:
                        rating_match = re.search(r'([\d.]+) out of', rating.text)
                        if rating_match:
                            rating_value = float(rating_match.group(1))
                    
                    reviews = soup.select_one('#acrCustomerReviewText')
                    reviews_count = None
                    if reviews:
                        reviews_match = re.search(r'([\d,]+)', reviews.text)
                        if reviews_match:
                            reviews_count = int(reviews_match.group(1).replace(',', ''))
                    
                    image = soup.select_one('#landingImage, #imgBlkFront')
                    image_url = image.get('src') if image else None
                    
                    return {
                        'marketplace_id': asin,
                        'title': title_text,
                        'price': price,
                        'currency': 'USD',
                        'in_stock': in_stock,
                        'brand': brand_text,
                        'image_url': image_url,
                        'seller_rating': rating_value,
                        'reviews_count': reviews_count,
                        'category': self._extract_amazon_category(soup),
                    }
                    
            except Exception as e:
                logger.error(f"Amazon scraping error: {e}")
                await self.proxy_manager.mark_proxy_failed(proxy)
                return None
    
    async def _scrape_ebay(self, url: str) -> Optional[Dict]:
        """Scrape eBay product"""
        proxy = await self.proxy_manager.get_proxy()
        headers = {'User-Agent': random.choice(self.user_agents)}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, headers=headers, proxy=proxy, timeout=30) as response:
                    html = await response.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    
                    # Extract item ID
                    item_id_match = re.search(r'/itm/(\d+)', url)
                    item_id = item_id_match.group(1) if item_id_match else None
                    
                    # Extract price
                    price_element = soup.select_one('.x-price-primary span.ux-textspans')
                    price = None
                    if price_element:
                        price_text = price_element.text.strip()
                        price_match = re.search(r'[\d,]+\.?\d*', price_text)
                        if price_match:
                            price = float(price_match.group().replace(',', ''))
                    
                    # Extract title
                    title = soup.select_one('h1.it-ttl')
                    title_text = title.text.strip() if title else "Unknown Product"
                    
                    # Extract seller info
                    seller = soup.select_one('.si-inner .mbg-nw')
                    seller_name = seller.text.strip() if seller else None
                    
                    seller_rating = soup.select_one('.si-inner .perCnt')
                    rating_value = None
                    if seller_rating:
                        rating_match = re.search(r'([\d.]+)%', seller_rating.text)
                        if rating_match:
                            rating_value = float(rating_match.group(1)) / 20  # Convert to 5-star
                    
                    # Extract shipping
                    shipping = soup.select_one('.vi-acc-del-range b')
                    shipping_cost = 0
                    if shipping and 'free' not in shipping.text.lower():
                        ship_match = re.search(r'[\d.]+', shipping.text)
                        if ship_match:
                            shipping_cost = float(ship_match.group())
                    
                    return {
                        'marketplace_id': item_id,
                        'title': title_text,
                        'price': price,
                        'currency': 'USD',
                        'in_stock': True,  # eBay items are usually available
                        'seller_name': seller_name,
                        'seller_rating': rating_value,
                        'shipping_cost': shipping_cost,
                    }
                    
            except Exception as e:
                logger.error(f"eBay scraping error: {e}")
                return None
    
    async def _scrape_aliexpress(self, url: str) -> Optional[Dict]:
        """Scrape AliExpress product using Selenium for dynamic content"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument(f'user-agent={random.choice(self.user_agents)}')
        
        # Add proxy if available
        proxy = await self.proxy_manager.get_proxy()
        if proxy:
            chrome_options.add_argument(f'--proxy-server={proxy}')
        
        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.get(url)
            
            # Wait for price to load
            wait = WebDriverWait(driver, 10)
            price_element = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, '.product-price-value'))
            )
            
            # Extract data
            price_text = price_element.text
            price_match = re.search(r'[\d,]+\.?\d*', price_text)
            price = float(price_match.group().replace(',', '')) if price_match else None
            
            title = driver.find_element(By.CSS_SELECTOR, '.product-title-text').text
            
            # Extract product ID
            product_id_match = re.search(r'/item/(\d+)\.html', url)
            product_id = product_id_match.group(1) if product_id_match else None
            
            # Check stock
            try:
                stock_element = driver.find_element(By.CSS_SELECTOR, '.product-quantity-tip')
                in_stock = 'out of stock' not in stock_element.text.lower()
            except:
                in_stock = True
            
            return {
                'marketplace_id': product_id,
                'title': title,
                'price': price,
                'currency': 'USD',
                'in_stock': in_stock,
            }
            
        except Exception as e:
            logger.error(f"AliExpress scraping error: {e}")
            return None
        finally:
            if driver:
                driver.quit()
    
    def _extract_amazon_category(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract category from Amazon page"""
        breadcrumb = soup.select_one('#wayfinding-breadcrumbs_feature_div')
        if breadcrumb:
            categories = breadcrumb.select('a.a-link-normal')
            if categories:
                return categories[-1].text.strip()
        return None
    
    async def _update_product_data(self, product: Product, data: Dict, response_time: float):
        """Update product with scraped data"""
        async with get_db_session() as db:
            # Update product
            product.marketplace_id = data.get('marketplace_id', product.marketplace_id)
            product.title = data.get('title', product.title)
            product.current_price = data.get('price')
            product.in_stock = data.get('in_stock', True)
            product.last_checked = datetime.utcnow()
            product.error_count = 0
            product.last_error = None
            
            if data.get('image_url'):
                product.image_url = data['image_url']
            if data.get('brand'):
                product.brand = data['brand']
            if data.get('category'):
                product.category = data['category']
            
            # Update price statistics
            if data.get('price'):
                product.price_checks_count += 1
                
                if not product.min_price or data['price'] < product.min_price:
                    product.min_price = data['price']
                if not product.max_price or data['price'] > product.max_price:
                    product.max_price = data['price']
                
                # Calculate running average
                if product.avg_price:
                    product.avg_price = (
                        (product.avg_price * (product.price_checks_count - 1) + data['price']) /
                        product.price_checks_count
                    )
                else:
                    product.avg_price = data['price']
            
            # Save price history
            history = PriceHistory(
                product_id=product.id,
                price=data.get('price', 0),
                currency=data.get('currency', 'USD'),
                in_stock=data.get('in_stock', True),
                shipping_cost=data.get('shipping_cost'),
                seller_name=data.get('seller_name'),
                seller_rating=data.get('seller_rating'),
                reviews_count=data.get('reviews_count'),
                response_time_ms=int(response_time * 1000)
            )
            
            db.add(product)
            db.add(history)
            await db.commit()
    
    async def _check_alerts(self, product: Product, data: Dict):
        """Check and trigger price alerts"""
        if not data.get('price') or not product.current_price:
            return
        
        new_price = data['price']
        old_price = product.current_price
        
        if old_price == new_price:
            return
        
        price_change_percent = ((new_price - old_price) / old_price) * 100
        
        async with get_db_session() as db:
            # Check for price drop alert
            if price_change_percent <= -10:  # 10% drop
                alert = Alert(
                    user_id=product.user_id,
                    product_id=product.id,
                    alert_type=AlertType.PRICE_DROP,
                    old_price=old_price,
                    new_price=new_price,
                    price_change_percent=price_change_percent
                )
                db.add(alert)
                await db.commit()
                
                # Send notification
                await send_alert(alert, product)
            
            # Check for target price alert
            if product.target_price and new_price <= product.target_price:
                alert = Alert(
                    user_id=product.user_id,
                    product_id=product.id,
                    alert_type=AlertType.PRICE_DROP,
                    threshold_value=product.target_price,
                    old_price=old_price,
                    new_price=new_price,
                    price_change_percent=price_change_percent
                )
                db.add(alert)
                await db.commit()
                
                await send_alert(alert, product)
            
            # Check for new low price
            if product.min_price and new_price < product.min_price:
                alert = Alert(
                    user_id=product.user_id,
                    product_id=product.id,
                    alert_type=AlertType.NEW_LOW,
                    old_price=old_price,
                    new_price=new_price,
                    price_change_percent=price_change_percent
                )
                db.add(alert)
                await db.commit()
                
                await send_alert(alert, product)
    
    async def _emit_price_update(self, product: Product, data: Dict):
        """Emit real-time price update via WebSocket"""
        if not data.get('price'):
            return
        
        try:
            # Publish to Redis pub/sub
            update_data = {
                'product_id': str(product.id),
                'old_price': product.current_price,
                'new_price': data['price'],
                'currency': data.get('currency', 'USD'),
                'change_percent': (
                    ((data['price'] - product.current_price) / product.current_price * 100)
                    if product.current_price else 0
                ),
                'timestamp': datetime.utcnow().isoformat()
            }
            
            await self.redis_client.publish(
                f"price_update:{product.id}",
                json.dumps(update_data)
            )
            
        except Exception as e:
            logger.error(f"Error emitting price update: {e}")
    
    async def _handle_scraping_error(self, product: Product, error: str):
        """Handle scraping errors"""
        async with get_db_session() as db:
            product.last_error = error
            product.error_count += 1
            product.last_checked = datetime.utcnow()
            
            # Disable product after too many errors
            if product.error_count >= 10:
                product.status = ProductStatus.ERROR
                logger.warning(f"Product {product.id} disabled after 10 errors")
            
            db.add(product)
            await db.commit()

# Background task for FastAPI
async def scrape_product_task(product_id: str):
    """Background task to scrape a single product"""
    try:
        redis_client = await redis.from_url("redis://localhost:6379")
        scraper = ScraperManager(redis_client)
        
        async with get_db_session() as db:
            result = await db.execute(select(Product).where(Product.id == product_id))
            product = result.scalar_one_or_none()
            
            if product:
                await scraper.scrape_product(product)
                
        await redis_client.close()
        
    except Exception as e:
        logger.error(f"Error in scrape task for {product_id}: {e}")