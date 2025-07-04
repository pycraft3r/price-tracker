"""
Proxy Manager
Handles proxy rotation for high-volume scraping (1M+ requests)
"""

import asyncio
import aiohttp
import random
import logging
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import json
import os
from collections import defaultdict
import redis.asyncio as redis
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Manages proxy rotation with health checking and rate limiting
    Supports 1M+ requests daily with intelligent proxy selection
    """
    
    def __init__(self):
        self.redis_client = None
        self.proxy_providers = [
            self._load_residential_proxies,
            self._load_datacenter_proxies,
            self._load_rotating_proxies
        ]
        self.proxy_stats = defaultdict(lambda: {
            'success': 0,
            'failure': 0,
            'total_requests': 0,
            'avg_response_time': 0,
            'last_used': None,
            'blocked_until': None
        })
        self.proxy_list: List[str] = []
        self.healthy_proxies: List[str] = []
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def initialize(self):
        """Initialize proxy manager with Redis connection"""
        if self._initialized:
            return
            
        self.redis_client = await redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            encoding="utf-8",
            decode_responses=True
        )
        
        # Load proxies from providers
        await self._load_all_proxies()
        
        # Start health check task
        asyncio.create_task(self._health_check_loop())
        
        self._initialized = True
        logger.info(f"Proxy manager initialized with {len(self.proxy_list)} proxies")
    
    async def _load_all_proxies(self):
        """Load proxies from all configured providers"""
        all_proxies = []
        
        for provider in self.proxy_providers:
            try:
                proxies = await provider()
                all_proxies.extend(proxies)
            except Exception as e:
                logger.error(f"Error loading proxies from provider: {e}")
        
        self.proxy_list = list(set(all_proxies))  # Remove duplicates
        self.healthy_proxies = self.proxy_list.copy()
        
        # Store in Redis for persistence
        if self.redis_client:
            await self.redis_client.set(
                "proxy:list",
                json.dumps(self.proxy_list),
                ex=86400  # 24 hours
            )
    
    async def _load_residential_proxies(self) -> List[str]:
        """Load residential proxies from provider"""
        # In production, integrate with providers like:
        # - Bright Data (Luminati)
        # - Oxylabs
        # - SmartProxy
        
        # Mock residential proxies for development
        if os.getenv("ENV") == "development":
            return [
                "http://user:pass@residential1.proxy.com:8080",
                "http://user:pass@residential2.proxy.com:8080",
                "http://user:pass@residential3.proxy.com:8080",
            ]
        
        # Production implementation would fetch from API
        api_key = os.getenv("RESIDENTIAL_PROXY_API_KEY")
        if not api_key:
            return []
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://proxy-provider.com/api/proxies",
                    headers={"Authorization": f"Bearer {api_key}"},
                    params={"type": "residential", "country": "US", "limit": 100}
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [p["url"] for p in data["proxies"]]
        except Exception as e:
            logger.error(f"Failed to load residential proxies: {e}")
            
        return []
    
    async def _load_datacenter_proxies(self) -> List[str]:
        """Load datacenter proxies"""
        # Mock datacenter proxies
        if os.getenv("ENV") == "development":
            return [
                "http://dc1.proxy.com:3128",
                "http://dc2.proxy.com:3128",
                "http://dc3.proxy.com:3128",
            ]
        
        # Production: Load from provider API or config
        return []
    
    async def _load_rotating_proxies(self) -> List[str]:
        """Load rotating proxy endpoints"""
        # These are endpoints that automatically rotate IPs
        rotating_endpoints = os.getenv("ROTATING_PROXY_ENDPOINTS", "").split(",")
        return [ep.strip() for ep in rotating_endpoints if ep.strip()]
    
    async def get_proxy(self, marketplace: Optional[str] = None) -> Optional[str]:
        """
        Get a healthy proxy for use
        Implements intelligent selection based on performance stats
        """
        if not self._initialized:
            await self.initialize()
        
        async with self._lock:
            if not self.healthy_proxies:
                logger.warning("No healthy proxies available")
                return None
            
            # Sort by performance score
            scored_proxies = []
            for proxy in self.healthy_proxies:
                stats = self.proxy_stats[proxy]
                
                # Skip if blocked
                if stats['blocked_until'] and datetime.utcnow() < stats['blocked_until']:
                    continue
                
                # Calculate performance score
                success_rate = (
                    stats['success'] / stats['total_requests']
                    if stats['total_requests'] > 0 else 0.5
                )
                
                # Prefer less used proxies
                usage_score = 1 / (stats['total_requests'] + 1)
                
                # Combine scores
                score = success_rate * 0.7 + usage_score * 0.3
                
                scored_proxies.append((score, proxy))
            
            if not scored_proxies:
                return None
            
            # Select proxy with weighted random (better proxies more likely)
            scored_proxies.sort(reverse=True)
            weights = [score for score, _ in scored_proxies]
            total_weight = sum(weights)
            
            if total_weight == 0:
                selected = random.choice(scored_proxies)[1]
            else:
                r = random.uniform(0, total_weight)
                cumsum = 0
                selected = scored_proxies[0][1]
                
                for score, proxy in scored_proxies:
                    cumsum += score
                    if r <= cumsum:
                        selected = proxy
                        break
            
            # Update stats
            self.proxy_stats[selected]['total_requests'] += 1
            self.proxy_stats[selected]['last_used'] = datetime.utcnow()
            
            return selected
    
    async def mark_proxy_success(self, proxy: str, response_time: float):
        """Mark a proxy request as successful"""
        async with self._lock:
            stats = self.proxy_stats[proxy]
            stats['success'] += 1
            
            # Update average response time
            if stats['avg_response_time'] == 0:
                stats['avg_response_time'] = response_time
            else:
                stats['avg_response_time'] = (
                    stats['avg_response_time'] * 0.9 + response_time * 0.1
                )
            
            # Clear any blocks
            stats['blocked_until'] = None
    
    async def mark_proxy_failed(self, proxy: str, error: Optional[str] = None):
        """Mark a proxy request as failed"""
        async with self._lock:
            stats = self.proxy_stats[proxy]
            stats['failure'] += 1
            
            # Calculate failure rate
            total = stats['success'] + stats['failure']
            failure_rate = stats['failure'] / total if total > 0 else 1
            
            # Block proxy temporarily if high failure rate
            if failure_rate > 0.5 and total > 10:
                stats['blocked_until'] = datetime.utcnow() + timedelta(minutes=30)
                logger.warning(f"Proxy {proxy} blocked for 30 minutes due to high failure rate")
                
                # Remove from healthy list
                if proxy in self.healthy_proxies:
                    self.healthy_proxies.remove(proxy)
    
    async def _health_check_loop(self):
        """Periodic health check for all proxies"""
        while True:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                await self._check_proxy_health()
            except Exception as e:
                logger.error(f"Error in health check loop: {e}")
    
    async def _check_proxy_health(self):
        """Check health of all proxies"""
        logger.info("Starting proxy health check")
        
        test_urls = [
            "http://httpbin.org/ip",
            "http://checkip.amazonaws.com",
            "http://icanhazip.com"
        ]
        
        healthy = []
        tasks = []
        
        for proxy in self.proxy_list:
            tasks.append(self._test_proxy(proxy, random.choice(test_urls)))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for proxy, result in zip(self.proxy_list, results):
            if isinstance(result, Exception):
                logger.debug(f"Proxy {proxy} failed health check: {result}")
            elif result:
                healthy.append(proxy)
                
                # Clear block if proxy is now healthy
                if self.proxy_stats[proxy]['blocked_until']:
                    self.proxy_stats[proxy]['blocked_until'] = None
        
        async with self._lock:
            self.healthy_proxies = healthy
            
        logger.info(f"Health check complete: {len(healthy)}/{len(self.proxy_list)} proxies healthy")
        
        # Store health status in Redis
        if self.redis_client:
            await self.redis_client.set(
                "proxy:healthy",
                json.dumps(healthy),
                ex=600  # 10 minutes
            )
    
    async def _test_proxy(self, proxy: str, test_url: str) -> bool:
        """Test if a proxy is working"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    test_url,
                    proxy=proxy,
                    timeout=10,
                    headers={'User-Agent': 'ProxyHealthCheck/1.0'}
                ) as response:
                    return response.status == 200
        except:
            return False
    
    async def get_proxy_stats(self) -> Dict:
        """Get current proxy statistics"""
        total_proxies = len(self.proxy_list)
        healthy_count = len(self.healthy_proxies)
        
        total_requests = sum(s['total_requests'] for s in self.proxy_stats.values())
        total_success = sum(s['success'] for s in self.proxy_stats.values())
        total_failures = sum(s['failure'] for s in self.proxy_stats.values())
        
        avg_response_time = 0
        if total_requests > 0:
            weighted_sum = sum(
                s['avg_response_time'] * s['total_requests']
                for s in self.proxy_stats.values()
                if s['total_requests'] > 0
            )
            avg_response_time = weighted_sum / total_requests
        
        return {
            'total_proxies': total_proxies,
            'healthy_proxies': healthy_count,
            'total_requests': total_requests,
            'success_count': total_success,
            'failure_count': total_failures,
            'success_rate': total_success / total_requests if total_requests > 0 else 0,
            'avg_response_time': avg_response_time,
            'blocked_proxies': sum(
                1 for s in self.proxy_stats.values()
                if s['blocked_until'] and datetime.utcnow() < s['blocked_until']
            )
        }
    
    async def add_proxy(self, proxy: str):
        """Dynamically add a new proxy"""
        async with self._lock:
            if proxy not in self.proxy_list:
                self.proxy_list.append(proxy)
                self.healthy_proxies.append(proxy)
                logger.info(f"Added new proxy: {proxy}")
    
    async def remove_proxy(self, proxy: str):
        """Remove a proxy from rotation"""
        async with self._lock:
            if proxy in self.proxy_list:
                self.proxy_list.remove(proxy)
            if proxy in self.healthy_proxies:
                self.healthy_proxies.remove(proxy)
            if proxy in self.proxy_stats:
                del self.proxy_stats[proxy]
            logger.info(f"Removed proxy: {proxy}")