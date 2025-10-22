# app/middleware/monitoring.py
"""
Advanced monitoring and profiling middleware
Tracks performance, detects bottlenecks, logs slow requests
"""
import time
import logging
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable
import os
from datetime import datetime
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)

class PerformanceMonitoringMiddleware(BaseHTTPMiddleware):
    """
    Monitor request performance and log slow requests
    Helps identify bottlenecks in production
    """
    
    def __init__(self, app, slow_threshold: float = 2.0):
        super().__init__(app)
        self.slow_threshold = float(os.getenv('SLOW_QUERY_THRESHOLD', slow_threshold))
        self.redis = None
        try:
            self.redis = get_redis()
        except:
            logger.warning("⚠️ Redis not available for metrics")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip monitoring for health checks
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)
        
        start_time = time.time()
        
        # Execute request
        response = await call_next(request)
        
        # Calculate duration
        duration = time.time() - start_time
        
        # Add performance header
        response.headers["X-Process-Time"] = f"{duration:.3f}"
        
        # Log slow requests
        if duration > self.slow_threshold:
            logger.warning(
                f"🐌 SLOW REQUEST: {request.method} {request.url.path} took {duration:.2f}s"
            )
            
            # Track slow request in Redis (for metrics dashboard)
            if self.redis:
                try:
                    await self._track_slow_request(
                        request.method,
                        request.url.path,
                        duration
                    )
                except Exception as e:
                    logger.error(f"❌ Metrics tracking error: {e}")
        
        # Track request metrics
        if self.redis:
            try:
                await self._track_request_metrics(
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration
                )
            except Exception as e:
                logger.debug(f"Metrics tracking error: {e}")
        
        return response
    
    async def _track_slow_request(self, method: str, path: str, duration: float):
        """Track slow requests for analysis"""
        try:
            key = f"slow_requests:{datetime.utcnow().strftime('%Y-%m-%d')}"
            value = {
                "method": method,
                "path": path,
                "duration": round(duration, 3),
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Store in Redis sorted set
            await self.redis.redis.zadd(
                key,
                {f"{method}:{path}:{time.time()}": duration}
            )
            
            # Expire after 7 days
            await self.redis.redis.expire(key, 604800)
        except Exception as e:
            logger.debug(f"Slow request tracking error: {e}")
    
    async def _track_request_metrics(
        self, 
        method: str, 
        path: str, 
        status_code: int,
        duration: float
    ):
        """Track general request metrics"""
        try:
            # Increment request counter
            counter_key = f"metrics:requests:{method}:{path}"
            await self.redis.increment(counter_key)
            await self.redis.expire(counter_key, 86400)  # 24 hours
            
            # Track response times (for percentiles)
            timing_key = f"metrics:timing:{method}:{path}"
            await self.redis.redis.lpush(timing_key, duration)
            await self.redis.redis.ltrim(timing_key, 0, 999)  # Keep last 1000
            await self.redis.expire(timing_key, 86400)
            
            # Track status codes
            status_key = f"metrics:status:{status_code}"
            await self.redis.increment(status_key)
            await self.redis.expire(status_key, 86400)
            
        except Exception as e:
            logger.debug(f"Metrics tracking error: {e}")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Enhanced request/response logging
    Logs all API calls with context
    """
    
    def __init__(self, app):
        super().__init__(app)
        self.log_bodies = os.getenv('LOG_REQUEST_BODIES', 'false').lower() == 'true'
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Generate request ID if not present
        request_id = request.headers.get("X-Request-ID", str(time.time())[:16])
        
        # Get client info
        client_ip = request.client.host if request.client else "unknown"
        
        # Log request
        logger.info(
            f"[{request_id}] ➡️  {request.method} {request.url.path} from {client_ip}"
        )
        
        # Optionally log body for debugging
        if self.log_bodies and request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                if body and len(body) < 1000:  # Only log small bodies
                    logger.debug(f"[{request_id}] Body: {body.decode()[:500]}")
            except:
                pass
        
        # Execute request
        start_time = time.time()
        response = await call_next(request)
        duration = time.time() - start_time
        
        # Log response
        status_emoji = "✅" if response.status_code < 400 else "❌"
        logger.info(
            f"[{request_id}] {status_emoji} {response.status_code} "
            f"in {duration:.3f}s"
        )
        
        # Add request ID to response
        response.headers["X-Request-ID"] = request_id
        
        return response


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """
    Track and log errors for monitoring
    Integrates with error tracking services (Sentry, etc.)
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            # Log error with full context
            logger.error(
                f"❌ UNHANDLED ERROR: {type(e).__name__} in {request.url.path}",
                exc_info=True,
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client": request.client.host if request.client else "unknown",
                    "error_type": type(e).__name__
                }
            )
            
            # Re-raise to let FastAPI handle
            raise