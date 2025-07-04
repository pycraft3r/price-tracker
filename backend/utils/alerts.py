"""
Alert System
Handles notifications for price drops and other events
"""

import asyncio
import aiohttp
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Dict, List
from datetime import datetime
import json
import os
from jinja2 import Template
from dotenv import load_dotenv

from database import get_db_session
from models import Alert, Product, User, AlertType

load_dotenv()

logger = logging.getLogger(__name__)

class AlertManager:
    """Manages alert notifications across multiple channels"""
    
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_password = os.getenv("SMTP_PASSWORD")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@pricetracker.com")
        self.webhook_timeout = 30
        
        # Email templates
        self.email_templates = {
            AlertType.PRICE_DROP: """
            <html>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f4;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                    <h1 style="color: #2ecc71; text-align: center;">🎉 Price Drop Alert!</h1>
                    <h2 style="color: #333;">{{ product.title }}</h2>
                    
                    <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0;">
                        <table width="100%">
                            <tr>
                                <td style="font-size: 18px; color: #666;">Previous Price:</td>
                                <td style="font-size: 18px; color: #666; text-align: right;">
                                    <del>${{ "%.2f"|format(alert.old_price) }}</del>
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 24px; color: #2ecc71; font-weight: bold;">New Price:</td>
                                <td style="font-size: 24px; color: #2ecc71; font-weight: bold; text-align: right;">
                                    ${{ "%.2f"|format(alert.new_price) }}
                                </td>
                            </tr>
                            <tr>
                                <td style="font-size: 18px; color: #e74c3c;">You Save:</td>
                                <td style="font-size: 18px; color: #e74c3c; text-align: right;">
                                    ${{ "%.2f"|format(alert.old_price - alert.new_price) }} ({{ "%.1f"|format(abs(alert.price_change_percent)) }}%)
                                </td>
                            </tr>
                        </table>
                    </div>
                    
                    <a href="{{ product.url }}" style="display: inline-block; background-color: #3498db; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; font-size: 18px;">
                        View Product
                    </a>
                    
                    <p style="color: #666; font-size: 14px;">
                        This is the lowest price we've tracked for this product!
                    </p>
                    
                    <hr style="border: 1px solid #eee; margin: 20px 0;">
                    
                    <p style="color: #999; font-size: 12px; text-align: center;">
                        You're receiving this because you're tracking this product on Price Tracker.
                        <br>
                        <a href="{{ unsubscribe_url }}" style="color: #3498db;">Unsubscribe</a> | 
                        <a href="{{ settings_url }}" style="color: #3498db;">Update Settings</a>
                    </p>
                </div>
            </body>
            </html>
            """,
            
            AlertType.NEW_LOW: """
            <html>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f4;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 10px;">
                    <h1 style="color: #e74c3c; text-align: center;">🔥 New All-Time Low Price!</h1>
                    <h2 style="color: #333;">{{ product.title }}</h2>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <span style="font-size: 48px; color: #e74c3c; font-weight: bold;">
                            ${{ "%.2f"|format(alert.new_price) }}
                        </span>
                        <p style="color: #666;">Previous lowest: ${{ "%.2f"|format(product.min_price) }}</p>
                    </div>
                    
                    <a href="{{ product.url }}" style="display: block; background-color: #e74c3c; color: white; padding: 15px; text-align: center; text-decoration: none; border-radius: 5px; font-size: 18px;">
                        Buy Now - Lowest Price Ever!
                    </a>
                </div>
            </body>
            </html>
            """,
            
            AlertType.BACK_IN_STOCK: """
            <html>
            <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f4f4f4;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 10px;">
                    <h1 style="color: #3498db; text-align: center;">📦 Back in Stock!</h1>
                    <h2 style="color: #333;">{{ product.title }}</h2>
                    
                    <p style="font-size: 18px; color: #666; text-align: center;">
                        Great news! This product is available again.
                    </p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <span style="font-size: 36px; color: #2ecc71; font-weight: bold;">
                            ${{ "%.2f"|format(product.current_price) }}
                        </span>
                    </div>
                    
                    <a href="{{ product.url }}" style="display: block; background-color: #3498db; color: white; padding: 15px; text-align: center; text-decoration: none; border-radius: 5px; font-size: 18px;">
                        Shop Now
                    </a>
                </div>
            </body>
            </html>
            """
        }
    
    async def send_alert(self, alert: Alert, product: Product):
        """Send alert through configured channels"""
        try:
            async with get_db_session() as db:
                # Get user settings
                result = await db.execute(
                    db.query(User).filter(User.id == alert.user_id)
                )
                user = result.scalar_one_or_none()
                
                if not user:
                    logger.error(f"User not found for alert {alert.id}")
                    return
                
                notification_settings = user.notification_settings
                
                # Send through enabled channels
                tasks = []
                
                if notification_settings.get('email', True):
                    tasks.append(self._send_email_alert(alert, product, user))
                
                if notification_settings.get('webhook') and notification_settings.get('webhook_url'):
                    tasks.append(self._send_webhook_alert(
                        alert, product, notification_settings['webhook_url']
                    ))
                
                # Execute all notification tasks
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Check if any succeeded
                success = any(not isinstance(r, Exception) for r in results)
                
                if success:
                    alert.is_sent = True
                    alert.sent_at = datetime.utcnow()
                    db.add(alert)
                    await db.commit()
                    
                    # Track in Redis
                    await self._track_alert_sent(alert)
                else:
                    # Log all errors
                    for i, result in enumerate(results):
                        if isinstance(result, Exception):
                            logger.error(f"Notification error: {result}")
                    
                    alert.error_message = "All notification methods failed"
                    db.add(alert)
                    await db.commit()
                    
        except Exception as e:
            logger.error(f"Error sending alert {alert.id}: {e}")
    
    async def _send_email_alert(self, alert: Alert, product: Product, user: User):
        """Send email notification"""
        try:
            # Select template
            template_str = self.email_templates.get(
                alert.alert_type,
                self.email_templates[AlertType.PRICE_DROP]
            )
            
            # Render template
            template = Template(template_str)
            html_content = template.render(
                alert=alert,
                product=product,
                user=user,
                unsubscribe_url=f"{os.getenv('FRONTEND_URL')}/unsubscribe/{user.id}",
                settings_url=f"{os.getenv('FRONTEND_URL')}/settings"
            )
            
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = self._get_email_subject(alert, product)
            msg['From'] = self.from_email
            msg['To'] = user.email
            
            # Add HTML content
            msg.attach(MIMEText(html_content, 'html'))
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent for alert {alert.id} to {user.email}")
            
        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            raise
    
    async def _send_webhook_alert(self, alert: Alert, product: Product, webhook_url: str):
        """Send webhook notification"""
        payload = {
            'event': 'price_alert',
            'alert_type': alert.alert_type.value,
            'product': {
                'id': str(product.id),
                'title': product.title,
                'url': product.url,
                'marketplace': product.marketplace.value,
                'current_price': product.current_price,
                'currency': product.currency
            },
            'price_change': {
                'old_price': alert.old_price,
                'new_price': alert.new_price,
                'change_percent': alert.price_change_percent,
                'savings': alert.old_price - alert.new_price
            },
            'timestamp': alert.triggered_at.isoformat()
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    webhook_url,
                    json=payload,
                    timeout=self.webhook_timeout,
                    headers={'Content-Type': 'application/json'}
                ) as response:
                    if response.status >= 400:
                        raise Exception(f"Webhook returned {response.status}")
                    
                logger.info(f"Webhook sent for alert {alert.id}")
                
            except asyncio.TimeoutError:
                logger.error(f"Webhook timeout for alert {alert.id}")
                raise
            except Exception as e:
                logger.error(f"Webhook failed: {e}")
                raise
    
    def _get_email_subject(self, alert: Alert, product: Product) -> str:
        """Generate email subject based on alert type"""
        if alert.alert_type == AlertType.PRICE_DROP:
            percent = abs(alert.price_change_percent)
            return f"💰 {percent:.1f}% Price Drop: {product.title[:50]}..."
        elif alert.alert_type == AlertType.NEW_LOW:
            return f"🔥 All-Time Low Price: {product.title[:50]}..."
        elif alert.alert_type == AlertType.BACK_IN_STOCK:
            return f"📦 Back in Stock: {product.title[:50]}..."
        else:
            return f"Price Alert: {product.title[:50]}..."
    
    async def _track_alert_sent(self, alert: Alert):
        """Track alert metrics in Redis"""
        try:
            # Daily counter
            today = datetime.utcnow().date().isoformat()
            await self.redis_client.hincrby(f"alerts:sent:{today}", alert.alert_type.value, 1)
            
            # User counter
            await self.redis_client.hincrby(f"user:alerts:{alert.user_id}", "total", 1)
            
            # Set expiry on daily counter
            await self.redis_client.expire(f"alerts:sent:{today}", 86400 * 7)  # 7 days
            
        except Exception as e:
            logger.error(f"Error tracking alert metrics: {e}")
    
    async def get_alert_stats(self, user_id: Optional[str] = None) -> Dict:
        """Get alert statistics"""
        try:
            if user_id:
                # User-specific stats
                total = await self.redis_client.hget(f"user:alerts:{user_id}", "total") or 0
                return {"user_total_alerts": int(total)}
            else:
                # System-wide stats
                today = datetime.utcnow().date().isoformat()
                daily_stats = await self.redis_client.hgetall(f"alerts:sent:{today}")
                
                return {
                    "today": {
                        alert_type: int(count)
                        for alert_type, count in daily_stats.items()
                    },
                    "total_today": sum(int(v) for v in daily_stats.values())
                }
                
        except Exception as e:
            logger.error(f"Error getting alert stats: {e}")
            return {}
    
    async def send_bulk_alerts(self, alerts: List[Alert]):
        """Send multiple alerts efficiently"""
        tasks = []
        
        # Group by user for batching
        user_alerts = {}
        for alert in alerts:
            if alert.user_id not in user_alerts:
                user_alerts[alert.user_id] = []
            user_alerts[alert.user_id].append(alert)
        
        # Send alerts
        for user_id, user_alert_list in user_alerts.items():
            if len(user_alert_list) == 1:
                # Single alert
                tasks.append(self.send_alert(user_alert_list[0]))
            else:
                # Multiple alerts - send digest
                tasks.append(self._send_alert_digest(user_id, user_alert_list))
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _send_alert_digest(self, user_id: str, alerts: List[Alert]):
        """Send digest email for multiple alerts"""
        # Implementation for digest emails
        pass

# Helper function for direct usage
async def send_alert(alert: Alert, product: Product):
    """Send an alert notification"""
    import redis.asyncio as redis
    redis_client = await redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
    manager = AlertManager(redis_client)
    await manager.send_alert(alert, product)
    await redis_client.close()