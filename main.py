from fastapi import FastAPI
from app.app import create_customer_app
from contextlib import asynccontextmanager
# import logging
import structlog
from db.db_manager import get_database
from app.cache.redis_manager import redis_manager
from app.services.search_service import search_service
from app.services.inventory_service import inventory_service
import os
from dotenv import load_dotenv
from datetime import datetime

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
        
        # Initialize Elasticsearch
        try:
            await search_service.init_elasticsearch()
            app.state.search = search_service
            logger.info("✅ Elasticsearch connected successfully")
        except Exception as e:
            logger.warning(f"⚠️ Elasticsearch connection failed, search will use fallback: {e}")
        
        # Initialize inventory cache
        try:
            await inventory_service.sync_inventory_to_cache(db)
            logger.info("✅ Inventory cache synchronized")
        except Exception as e:
            logger.warning(f"⚠️ Inventory sync failed: {e}")
        
        # Create database indexes
        await create_indexes(db)
        logger.info("✅ Database indexes created")
        
        logger.info("🎉 SmartBag application started successfully")

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
    """Create optimized database indexes"""
    try:
        # Enhanced indexes for better performance
        
        # User indexes
        await db.db['users'].create_index("email", unique=True)
        await db.db['users'].create_index([("role", 1), ("is_active", 1)])
        await db.db['users'].create_index("provider")
        
        # Product indexes (optimized for search and filtering)
        await db.db['products'].create_index([
            ("is_active", 1), ("category", 1), ("brand", 1), ("price", 1)
        ])
        await db.db['products'].create_index([("name", "text"), ("description", "text"), ("keywords", "text")])
        await db.db['products'].create_index([("created_at", -1)])
        await db.db['products'].create_index([("rating", -1), ("review_count", -1)])
        await db.db['products'].create_index("stock")
        
        # Order indexes (optimized for history and analytics)
        await db.db['orders'].create_index([("user", 1), ("created_at", -1)])
        await db.db['orders'].create_index([("order_status", 1), ("created_at", -1)])
        await db.db['orders'].create_index([("delivery_partner", 1), ("order_status", 1)])
        await db.db['orders'].create_index("created_at")
        
        # Cart indexes
        await db.db['carts'].create_index("user", unique=True)
        await db.db['carts'].create_index("updated_at")
        
        # Address indexes
        await db.db['user_addresses'].create_index([("user_id", 1), ("is_default", -1)])
        
        # Support ticket indexes
        await db.db['support_tickets'].create_index([("user_id", 1), ("created_at", -1)])
        await db.db['support_tickets'].create_index([("status", 1), ("created_at", -1)])
        
        # Session and token indexes
        await db.db['refresh_tokens'].create_index("expire", expireAfterSeconds=0)
        await db.db['password_reset_tokens'].create_index("expires_at", expireAfterSeconds=0)
        
        # Delivery-specific indexes
        await db.db['orders'].create_index([("delivery_partner", 1), ("order_status", 1)])
        
        logger.info("✅ All optimized indexes created successfully")
        
    except Exception as e:
        logger.error(f"❌ Error creating indexes: {str(e)}")

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
                "uptime": "calculated_uptime",  # Implement uptime calculation
                "version": "2.0.0"
            }
        }
    except Exception as e:
        return {"error": str(e)}

ENV = os.getenv('ENVIRONMENT', 'Production')

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
    
    if ENV == 'Development':
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    else:
        uvicorn.run(
            "main:app",
            host="0.0.0.0", 
            port=int(os.getenv('PORT', 8000)),
            reload=False,
            log_level="warning",
            workers=1  # Use 1 worker for now, increase based on server capacity
        )