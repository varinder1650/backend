# main.py - COMPLETE WORKING VERSION
from fastapi import FastAPI
from app.app import create_customer_app
from contextlib import asynccontextmanager
import structlog
from db.db_manager import get_database
from app.cache.redis_manager import redis_manager
from app.services.search_service import search_service
from app.services.inventory_service import inventory_service
import os
from dotenv import load_dotenv
from datetime import datetime
import logging

load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="ISO"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer()
    ],
    cache_logger_on_first_use=True
)

logger = structlog.get_logger(__name__)

# Configure standard logging
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("🚀 Starting SmartBag application...")
        
        # Initialize database
        db = get_database()
        app.state.db = db
        db.client.admin.command('ping')
        logger.info("✅ Database connected successfully")
        
        # Initialize Redis
        await redis_manager.init_redis_pool(os.getenv('REDIS_URL', 'redis://localhost:6379'))
        app.state.redis = redis_manager
        logger.info("✅ Redis connected successfully")
        
        # Initialize Elasticsearch (optional)
        if os.getenv('ENABLE_ELASTICSEARCH', 'false').lower() == 'true':
            try:
                await search_service.init_elasticsearch()
                app.state.search = search_service
                logger.info("✅ Elasticsearch connected successfully")
            except Exception as e:
                logger.warning(f"⚠️ Elasticsearch connection failed: {e}")
        
        # Initialize inventory cache
        try:
            await inventory_service.sync_inventory_to_cache(db)
            logger.info("✅ Inventory cache synchronized")
        except Exception as e:
            logger.warning(f"⚠️ Inventory sync failed: {e}")
        
        # Create database indexes
        await create_indexes(db)
        logger.info("✅ Database indexes verified")
        
        logger.info("🎉 SmartBag application started successfully")
        logger.info(f"📍 Environment: {os.getenv('ENVIRONMENT', 'Development')}")

    except Exception as e:
        logger.error(f"💥 Failed to initialize application: {str(e)}")
        raise e

    yield
    
    # Cleanup on shutdown
    logger.info("🔄 Shutting down SmartBag application...")
    
    if hasattr(app.state, 'db'):
        app.state.db.client.close()
        logger.info("✅ Database connection closed")
    
    if hasattr(app.state, 'redis'):
        await app.state.redis.close()
        logger.info("✅ Redis connection closed")
    
    if hasattr(app.state, 'search'):
        await app.state.search.close()
        logger.info("✅ Elasticsearch connection closed")
    
    logger.info("👋 SmartBag application shutdown complete")

async def create_indexes(db):
    """Create optimized database indexes (skip if already exist)"""
    try:
        # Helper to create index safely
        async def safe_create_index(collection, spec, **kwargs):
            try:
                await db.db[collection].create_index(spec, **kwargs)
            except Exception as e:
                if "already exists" not in str(e).lower():
                    logger.debug(f"Index note for {collection}: {e}")
        
        # User indexes
        await safe_create_index('users', "email", unique=True)
        await safe_create_index('users', [("role", 1), ("is_active", 1)])
        await safe_create_index('users', "provider")
        
        # Product indexes
        await safe_create_index('products', [
            ("is_active", 1), ("category", 1), ("brand", 1), ("price", 1)
        ])
        await safe_create_index('products', [
            ("name", "text"), ("description", "text"), ("keywords", "text")
        ])
        await safe_create_index('products', [("created_at", -1)])
        await safe_create_index('products', [("rating", -1), ("review_count", -1)])
        await safe_create_index('products', "stock")
        
        # Order indexes
        await safe_create_index('orders', [("user", 1), ("created_at", -1)])
        await safe_create_index('orders', [("order_status", 1), ("created_at", -1)])
        await safe_create_index('orders', [("delivery_partner", 1), ("order_status", 1)])
        await safe_create_index('orders', "created_at")
        
        # Cart indexes
        await safe_create_index('carts', "user", unique=True)
        await safe_create_index('carts', "updated_at")
        
        # Address indexes
        await safe_create_index('user_addresses', [("user_id", 1), ("is_default", -1)])
        
        # Support ticket indexes
        await safe_create_index('support_tickets', [("user_id", 1), ("created_at", -1)])
        await safe_create_index('support_tickets', [("status", 1), ("created_at", -1)])
        
        # Session and token indexes
        await safe_create_index('refresh_tokens', "expire", expireAfterSeconds=0)
        await safe_create_index('password_reset_tokens', "expires_at", expireAfterSeconds=0)
        
        # Delivery-specific indexes
        await safe_create_index('orders', [("delivery_partner", 1), ("order_status", 1)])
        
        logger.info("✅ All database indexes verified")
        
    except Exception as e:
        logger.error(f"❌ Error with indexes: {str(e)}")

# Create main application
app = FastAPI(
    title="SmartBag Production Server",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs" if os.getenv('ENVIRONMENT') == 'Development' else None,
    redoc_url="/redoc" if os.getenv('ENVIRONMENT') == 'Development' else None
)

# Create sub-applications
customer_app = create_customer_app()

app.state.customer_app = customer_app

# Mount applications
app.mount("/api", customer_app)

# Health check endpoints
@app.get("/health")
async def health_check():
    """Comprehensive health check"""
    health_status = {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0.0",
        "services": {}
    }
    
    # Check database
    try:
        await app.state.db.client.admin.command('ping')
        health_status["services"]["database"] = "healthy"
    except Exception as e:
        health_status["services"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Redis
    try:
        await app.state.redis.redis.ping()
        health_status["services"]["redis"] = "healthy"
    except Exception as e:
        health_status["services"]["redis"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check Elasticsearch (optional)
    if hasattr(app.state, 'search'):
        try:
            await app.state.search.client.ping()
            health_status["services"]["elasticsearch"] = "healthy"
        except Exception as e:
            health_status["services"]["elasticsearch"] = f"unhealthy: {str(e)}"
    
    return health_status

@app.get("/metrics")
async def get_metrics():
    """Application metrics for monitoring"""
    try:
        # Redis metrics
        redis_info = await app.state.redis.redis.info()
        
        # Database metrics (basic)
        db_stats = await app.state.db.db.command("dbStats")
        
        return {
            "redis": {
                "connected_clients": redis_info.get('connected_clients', 0),
                "used_memory_human": redis_info.get('used_memory_human', '0B'),
                "hit_rate": redis_info.get('keyspace_hits', 0) / max(redis_info.get('keyspace_hits', 0) + redis_info.get('keyspace_misses', 1), 1),
                "total_commands": redis_info.get('total_commands_processed', 0)
            },
            "database": {
                "collections": db_stats.get('collections', 0),
                "objects": db_stats.get('objects', 0),
                "data_size": db_stats.get('dataSize', 0),
                "storage_size": db_stats.get('storageSize', 0)
            },
            "app": {
                "version": "2.0.0",
                "environment": os.getenv('ENVIRONMENT', 'Development')
            }
        }
    except Exception as e:
        return {"error": str(e)}

ENV = os.getenv('ENVIRONMENT', 'Development')

@app.get("/")
async def root():
    return {
        "message": "SmartBag Production API",
        "environment": ENV,
        "version": "2.0.0",
        "status": "running"
    }

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv('PORT', 8000))
    
    if ENV == 'Development':
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            log_level="info"
        )
    else:
        uvicorn.run(
            "main:app",
            host="0.0.0.0", 
            port=port,
            reload=False,
            log_level="warning",
            workers=1
        )