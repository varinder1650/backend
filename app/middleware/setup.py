# app/middleware/setup.py - COMPLETE REPLACEMENT
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from app.middleware.rate_limiter import GlobalRateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.monitoring import (
    PerformanceMonitoringMiddleware,
    RequestLoggingMiddleware,
    ErrorTrackingMiddleware
)
import os
import logging

logger = logging.getLogger(__name__)

def setup_middleware(app: FastAPI):
    """
    Setup all middleware in correct order
    Order matters! Apply from outermost to innermost
    """
    
    # ✅ 1. Security Headers (first, applies to all responses)
    app.add_middleware(SecurityHeadersMiddleware)
    logger.info("✅ Security headers middleware added")
    
    # ✅ 2. CORS (must be early for OPTIONS requests)
    allowed_origins = os.getenv('ALLOWED_ORIGINS', 'http://localhost:3000').split(',')
    allowed_origins = [origin.strip() for origin in allowed_origins]
    
    # Note: allow_origins=["*"] with allow_credentials=True violates the CORS spec
    # and will be rejected by browsers. Always use explicit origins.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["*"],
        max_age=3600
    )
    logger.info(f"✅ CORS middleware added (origins: {len(allowed_origins)})")
    
    # ✅ 3. Trusted Host (security)
    if os.getenv('ENVIRONMENT') == 'Production':
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"]  # Configure properly for production
        )
        logger.info("✅ Trusted host middleware added")
    
    # ✅ 4. Error Tracking (catch all errors)
    app.add_middleware(ErrorTrackingMiddleware)
    logger.info("✅ Error tracking middleware added")
    
    # ✅ 5. Performance Monitoring
    app.add_middleware(
        PerformanceMonitoringMiddleware,
        slow_threshold=float(os.getenv('SLOW_QUERY_THRESHOLD', 2.0))
    )
    logger.info("✅ Performance monitoring middleware added")
    
    # ✅ 6. Request Logging
    app.add_middleware(RequestLoggingMiddleware)
    logger.info("✅ Request logging middleware added")
    
    # ✅ 7. Global Rate Limiting
    if os.getenv('ENABLE_RATE_LIMITING', 'true').lower() == 'true':
        app.add_middleware(
            GlobalRateLimitMiddleware,
            max_requests=int(os.getenv('API_RATE_LIMIT_PER_MINUTE', 1000)),
            window_seconds=60,
            exclude_paths=["/health", "/docs", "/openapi.json", "/redoc", "/metrics"]
        )
        logger.info("✅ Global rate limiting middleware added")
    
    # ✅ 8. Response Compression (last, compresses final response)
    app.add_middleware(
        GZipMiddleware,
        minimum_size=2000  # Only compress responses > 2KB
    )
    logger.info("✅ GZIP compression middleware added")
    
    logger.info("🎉 All middleware configured successfully")