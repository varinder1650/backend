"""
Rate Limiting Middleware for SmartBag API
Protects against brute force attacks and API abuse
"""

import time
import logging
from datetime import datetime, timedelta
from collections import defaultdict
from fastapi import HTTPException, Request, status
from functools import wraps
import asyncio

logger = logging.getLogger(__name__)

class RateLimiter:
    """
    In-memory rate limiter with sliding window algorithm
    For production, consider using Redis for distributed rate limiting
    """
    
    def __init__(self):
        # Store: {client_ip: {endpoint: [(timestamp, count)]}}
        self.requests = defaultdict(lambda: defaultdict(list))
        self.cleanup_interval = 300  # Clean old entries every 5 minutes
        self._last_cleanup = time.time()
    
    def _cleanup_old_entries(self):
        """Remove expired entries to prevent memory leak"""
        current_time = time.time()
        if current_time - self._last_cleanup < self.cleanup_interval:
            return
        
        cutoff_time = current_time - 3600  # Keep last hour only
        for ip in list(self.requests.keys()):
            for endpoint in list(self.requests[ip].keys()):
                self.requests[ip][endpoint] = [
                    (ts, count) for ts, count in self.requests[ip][endpoint]
                    if ts > cutoff_time
                ]
                if not self.requests[ip][endpoint]:
                    del self.requests[ip][endpoint]
            if not self.requests[ip]:
                del self.requests[ip]
        
        self._last_cleanup = current_time
        logger.info(f"Rate limiter cleanup completed. Active IPs: {len(self.requests)}")
    
    def is_rate_limited(
        self, 
        client_ip: str, 
        endpoint: str, 
        max_requests: int, 
        window_seconds: int
    ) -> tuple[bool, dict]:
        """
        Check if client has exceeded rate limit
        Returns: (is_limited, rate_info)
        """
        self._cleanup_old_entries()
        
        current_time = time.time()
        window_start = current_time - window_seconds
        
        # Get requests within the time window
        endpoint_requests = self.requests[client_ip][endpoint]
        
        # Remove old requests outside the window
        valid_requests = [
            (ts, count) for ts, count in endpoint_requests
            if ts > window_start
        ]
        self.requests[client_ip][endpoint] = valid_requests
        
        # Calculate total requests in window
        total_requests = sum(count for _, count in valid_requests)
        
        # Check if limit exceeded
        is_limited = total_requests >= max_requests
        
        if not is_limited:
            # Add current request
            self.requests[client_ip][endpoint].append((current_time, 1))
            total_requests += 1
        
        # Calculate retry after time
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

# Global rate limiter instance
_rate_limiter = RateLimiter()

def rate_limit(max_requests: int = 100, window_seconds: int = 60):
    """
    Decorator for rate limiting endpoints
    
    Args:
        max_requests: Maximum number of requests allowed
        window_seconds: Time window in seconds
    
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
                # If no request object, skip rate limiting
                logger.warning(f"Rate limiting skipped for {func.__name__}: No Request object found")
                return await func(*args, **kwargs)
            
            # Get client IP
            client_ip = request.client.host if request.client else "unknown"
            
            # Get endpoint path
            endpoint = f"{request.method}:{request.url.path}"
            
            # Check rate limit
            is_limited, rate_info = _rate_limiter.is_rate_limited(
                client_ip, 
                endpoint, 
                max_requests, 
                window_seconds
            )
            
            if is_limited:
                logger.warning(
                    f"Rate limit exceeded for {client_ip} on {endpoint}. "
                    f"Limit: {max_requests}/{window_seconds}s"
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
            
            # Add rate limit headers to response
            response = await func(*args, **kwargs)
            
            # If response has headers attribute (JSONResponse, etc.)
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
    Use this in addition to endpoint-specific rate limiting
    """
    
    def __init__(
        self,
        app,  # ✅ REQUIRED: FastAPI passes app as first argument
        max_requests: int = 1000,
        window_seconds: int = 60,
        exclude_paths: list = None
    ):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.exclude_paths = exclude_paths or ["/health", "/docs", "/openapi.json", "/redoc"]
        self.rate_limiter = RateLimiter()
    
    async def __call__(self, scope, receive, send):
        """ASGI3 middleware interface"""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        # Create request object to access path and client
        from starlette.requests import Request
        request = Request(scope, receive)
        
        # Skip rate limiting for excluded paths
        if request.url.path in self.exclude_paths:
            await self.app(scope, receive, send)
            return
        
        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        
        # Global rate limit key
        endpoint = f"GLOBAL:{client_ip}"
        
        # Check rate limit
        is_limited, rate_info = self.rate_limiter.is_rate_limited(
            client_ip,
            endpoint,
            self.max_requests,
            self.window_seconds
        )
        
        if is_limited:
            logger.warning(
                f"Global rate limit exceeded for {client_ip}. "
                f"Limit: {self.max_requests}/{self.window_seconds}s"
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
        
        # Continue with request processing
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                # Add rate limit headers
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-ratelimit-limit", str(rate_info['limit']).encode()),
                    (b"x-ratelimit-remaining", str(rate_info['remaining']).encode()),
                    (b"x-ratelimit-reset", str(rate_info['reset']).encode()),
                ])
                message["headers"] = headers
            await send(message)
        
        await self.app(scope, receive, send_wrapper)


# Redis-based rate limiter for production (optional)
class RedisRateLimiter:
    """
    Redis-based rate limiter for distributed systems
    Requires: redis, aioredis
    
    Usage in setup.py:
        from redis import asyncio as aioredis
        redis_client = await aioredis.from_url("redis://localhost")
        rate_limiter = RedisRateLimiter(redis_client)
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    async def is_rate_limited(
        self, 
        client_ip: str, 
        endpoint: str, 
        max_requests: int, 
        window_seconds: int
    ) -> tuple[bool, dict]:
        """Check rate limit using Redis"""
        key = f"rate_limit:{client_ip}:{endpoint}"
        current_time = int(time.time())
        window_start = current_time - window_seconds
        
        # Use Redis sorted set for sliding window
        pipe = self.redis.pipeline()
        
        # Remove old entries
        pipe.zremrangebyscore(key, 0, window_start)
        
        # Count requests in window
        pipe.zcard(key)
        
        # Add current request
        pipe.zadd(key, {str(current_time): current_time})
        
        # Set expiry
        pipe.expire(key, window_seconds)
        
        results = await pipe.execute()
        request_count = results[1]
        
        is_limited = request_count >= max_requests
        
        rate_info = {
            "limit": max_requests,
            "remaining": max(0, max_requests - request_count),
            "reset": current_time + window_seconds,
            "retry_after": window_seconds if is_limited else 0
        }
        
        return is_limited, rate_info