"""
Setup monitoring and logging infrastructure
"""

import logging
import structlog
from prometheus_client import Counter, Histogram, Gauge, start_http_server
import asyncio
import os

# Prometheus metrics
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP requests', ['method', 'endpoint', 'status'])
REQUEST_DURATION = Histogram('http_request_duration_seconds', 'HTTP request duration')
CACHE_HITS = Counter('cache_hits_total', 'Cache hits', ['cache_type'])
CACHE_MISSES = Counter('cache_misses_total', 'Cache misses', ['cache_type']) 
ACTIVE_USERS = Gauge('active_users', 'Number of active users')
DATABASE_CONNECTIONS = Gauge('database_connections', 'Number of database connections')

def setup_logging():
    """Configure structured logging"""
    
    logging.basicConfig(
        level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
        format='%(message)s'
    )
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="ISO"),
            structlog.dev.ConsoleRenderer() if os.getenv('ENVIRONMENT') == 'Development' 
            else structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

def start_metrics_server():
    """Start Prometheus metrics server"""
    port = int(os.getenv('PROMETHEUS_PORT', 8001))
    start_http_server(port)
    logger = structlog.get_logger()
    logger.info(f"📊 Metrics server started on port {port}")

# Middleware for tracking metrics
class MetricsMiddleware:
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            method = scope["method"]
            path = scope["path"]
            
            with REQUEST_DURATION.time():
                response = await self.app(scope, receive, send)
            
            # Track request
            status = getattr(response, 'status_code', 200)
            REQUEST_COUNT.labels(method=method, endpoint=path, status=status).inc()
            
            return response
        
        return await self.app(scope, receive, send)

if __name__ == "__main__":
    setup_logging()
    start_metrics_server()
    print("Monitoring setup complete")