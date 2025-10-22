# app/middleware/rate_limiter.py - COMPLETE REPLACEMENT
import time
import logging
import hashlib
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import HTTPException, Request, status
from functools import wraps
import asyncio
import os
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    Advanced rate limiter with Redis backend
    Supports distributed rate limiting across multiple servers
    """
    
    def __init__(self, use_redis: bool = True):
        self.use_redis = use_redis and os.getenv('ENABLE_RATE_LIMITING', 'true').lower() == 'true'
        
        if not self.use_redis:
            # Fallback to in-memory for development
            self.requests = defaultdict(lambda: defaultdict(list))
            self._last_cleanup = time.time()
            self.cleanup_interval = 300
        else:
            self.redis = get_redis()
    
    def _get_client_identifier(self, request: Request) -> str:
        """
        Generate unique client identifier
        Uses IP + User-Agent to prevent simple bypasses
        """
        # Check for proxy headers
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            client_ip = request.client.host if request.client else "unknown"
        
        # Add user agent for fingerprinting
        user_agent = request.headers.get("User-Agent", "")
        
        # Create hash for privacy
        identifier = f"{client_ip}:{user_agent}"
        return hashlib.sha256(identifier.encode()).hexdigest()[:16]
    
    async def is_rate_limited_redis(
        self,
        client_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Redis-based rate limiting using sliding window
        More accurate and scalable than fixed window
        """
        try:
            current_time = int(time.time())
            window_start = current_time - window_seconds
            
            # Redis key for this client+endpoint
            key = f"rate_limit:{client_id}:{endpoint}"
            
            # Use Redis sorted set for sliding window
            pipe = self.redis.redis.pipeline()
            
            # Remove old entries outside window
            pipe.zremrangebyscore(key, 0, window_start)
            
            # Count requests in current window
            pipe.zcard(key)
            
            # Add current request
            pipe.zadd(key, {str(current_time): current_time})
            
            # Set expiry on key
            pipe.expire(key, window_seconds)
            
            # Execute pipeline
            results = await pipe.execute()
            
            request_count = results[1]  # Count before adding current request
            
            is_limited = request_count >= max_requests
            
            # Calculate retry_after
            if is_limited:
                # Get oldest request timestamp
                oldest = await self.redis.redis.zrange(key, 0, 0, withscores=True)
                if oldest:
                    oldest_time = int(oldest[0][1])
                    retry_after = window_seconds - (current_time - oldest_time)
                else:
                    retry_after = window_seconds
            else:
                retry_after = 0
            
            rate_info = {
                "limit": max_requests,
                "remaining": max(0, max_requests - request_count - 1),
                "reset": current_time + window_seconds,
                "retry_after": max(0, retry_after)
            }
            
            return is_limited, rate_info
            
        except Exception as e:
            logger.error(f"Redis rate limiting error: {e}")
            # Fail open - allow request if rate limiting fails
            return False, {
                "limit": max_requests,
                "remaining": max_requests,
                "reset": int(time.time() + window_seconds),
                "retry_after": 0
            }
    
    def is_rate_limited_memory(
        self,
        client_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        In-memory rate limiting (fallback for development)
        """
        # Testing environment bypass
        if os.getenv('ENVIRONMENT') == 'Testing':
            return False, {
                "limit": max_requests,
                "remaining": max_requests,
                "reset": int(time.time() + window_seconds),
                "retry_after": 0
            }
        
        self._cleanup_old_entries()
        
        current_time = time.time()
        window_start = current_time - window_seconds
        
        # Get requests within window
        endpoint_requests = self.requests[client_id][endpoint]
        
        # Remove old requests
        valid_requests = [
            (ts, count) for ts, count in endpoint_requests
            if ts > window_start
        ]
        self.requests[client_id][endpoint] = valid_requests
        
        # Calculate total requests
        total_requests = sum(count for _, count in valid_requests)
        
        # Check if limited
        is_limited = total_requests >= max_requests
        
        if not is_limited:
            # Add current request
            self.requests[client_id][endpoint].append((current_time, 1))
            total_requests += 1
        
        # Calculate retry_after
        if valid_requests:
            oldest_request_time = valid_requests[0][0]
            retry_after = int(window_seconds - (current_time - oldest_request_time))
        else:
            retry_after = window_seconds
        
        rate_info = {
            "limit": max_requests,
            "remaining": max(0, max_requests - total_requests),
            "reset": int(current_time + retry_after),
            "retry_after": retry_after if is_limited else 0
        }
        
        return is_limited, rate_info
    
    async def is_rate_limited(
        self,
        client_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check rate limit using Redis or memory backend
        """
        if self.use_redis:
            return await self.is_rate_limited_redis(
                client_id, endpoint, max_requests, window_seconds
            )
        else:
            return self.is_rate_limited_memory(
                client_id, endpoint, max_requests, window_seconds
            )
    
    def _cleanup_old_entries(self):
        """Clean up old in-memory entries"""
        current_time = time.time()
        if current_time - self._last_cleanup < self.cleanup_interval:
            return
        
        cutoff_time = current_time - 3600
        for client_id in list(self.requests.keys()):
            for endpoint in list(self.requests[client_id].keys()):
                self.requests[client_id][endpoint] = [
                    (ts, count) for ts, count in self.requests[client_id][endpoint]
                    if ts > cutoff_time
                ]
                if not self.requests[client_id][endpoint]:
                    del self.requests[client_id][endpoint]
            if not self.requests[client_id]:
                del self.requests[client_id]
        
        self._last_cleanup = current_time
        logger.info(f"✅ Rate limiter cleanup completed. Active clients: {len(self.requests)}")

# Global rate limiter instance
_rate_limiter = RateLimiter(use_redis=True)

def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """
    Decorator for endpoint-specific rate limiting
    
    Usage:
        @router.post("/login")
        @rate_limit(max_requests=5, window_seconds=300)
        async def login(request: Request, ...):
            ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request from args/kwargs
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get('request')
            
            if not request:
                logger.warning(f"⚠️ Rate limiting skipped for {func.__name__}: No Request object")
                return await func(*args, **kwargs)
            
            # Get client identifier
            client_id = _rate_limiter._get_client_identifier(request)
            
            # Get endpoint identifier
            endpoint = f"{request.method}:{request.url.path}"
            
            # Check rate limit
            is_limited, rate_info = await _rate_limiter.is_rate_limited(
                client_id,
                endpoint,
                max_requests,
                window_seconds
            )
            
            if is_limited:
                logger.warning(
                    f"⚠️ Rate limit exceeded: {client_id[:8]}... on {endpoint} "
                    f"({max_requests}/{window_seconds}s)"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "error": "Rate limit exceeded",
                        "message": f"Too many requests. Please try again in {rate_info['retry_after']} seconds.",
                        "retry_after": rate_info['retry_after'],
                        "limit": rate_info['limit'],
                        "window_seconds": window_seconds
                    },
                    headers={
                        "X-RateLimit-Limit": str(rate_info['limit']),
                        "X-RateLimit-Remaining": str(rate_info['remaining']),
                        "X-RateLimit-Reset": str(rate_info['reset']),
                        "Retry-After": str(rate_info['retry_after'])
                    }
                )
            
            # Execute endpoint
            response = await func(*args, **kwargs)
            
            # Add rate limit headers to response if possible
            if hasattr(response, 'headers'):
                response.headers["X-RateLimit-Limit"] = str(rate_info['limit'])
                response.headers["X-RateLimit-Remaining"] = str(rate_info['remaining'])
                response.headers["X-RateLimit-Reset"] = str(rate_info['reset'])
            
            return response
        
        return wrapper
    return decorator


class GlobalRateLimitMiddleware:
    """
    Global rate limiting middleware for all endpoints
    Protects against DDoS and abuse
    """
    
    def __init__(
        self,
        app,
        max_requests: int = 10000,
        window_seconds: int = 60,
        exclude_paths: list = None
    ):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exclude_paths = exclude_paths or [
            "/health", "/docs", "/openapi.json", "/redoc", "/metrics"
        ]
        self.rate_limiter = RateLimiter(use_redis=True)
    
    async def __call__(self, scope, receive, send):
        """ASGI3 middleware interface"""
        # Bypass in testing
        if os.getenv('ENVIRONMENT') == 'Development':
            await self.app(scope, receive, send)
            return
        
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Create request object
        from starlette.requests import Request
        request = Request(scope, receive)
        
        # Skip excluded paths
        if request.url.path in self.exclude_paths:
            await self.app(scope, receive, send)
            return
        
        # Get client identifier
        client_id = self.rate_limiter._get_client_identifier(request)
        
        # Global rate limit key
        endpoint = f"GLOBAL:{client_id}"
        
        # Check rate limit
        is_limited, rate_info = await self.rate_limiter.is_rate_limited(
            client_id,
            endpoint,
            self.max_requests,
            self.window_seconds
        )
        
        if is_limited:
            logger.warning(
                f"⚠️ Global rate limit exceeded: {client_id[:8]}... "
                f"({self.max_requests}/{self.window_seconds}s)"
            )
            
            from starlette.responses import JSONResponse
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": "Global rate limit exceeded",
                    "message": f"Too many requests. Please try again in {rate_info['retry_after']} seconds.",
                    "retry_after": rate_info['retry_after']
                },
                headers={
                    "X-RateLimit-Limit": str(rate_info['limit']),
                    "X-RateLimit-Remaining": str(rate_info['remaining']),
                    "X-RateLimit-Reset": str(rate_info['reset']),
                    "Retry-After": str(rate_info['retry_after'])
                }
            )
            await response(scope, receive, send)
            return
        
        # Add rate limit headers to response
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-ratelimit-limit", str(rate_info['limit']).encode()),
                    (b"x-ratelimit-remaining", str(rate_info['remaining']).encode()),
                    (b"x-ratelimit-reset", str(rate_info['reset']).encode()),
                ])
                message["headers"] = headers
            await send(message)
        
        await self.app(scope, receive, send_wrapper)