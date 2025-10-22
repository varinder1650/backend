# app/routes/metrics.py
"""
Metrics and monitoring endpoints
Provides insights into application performance
"""
from fastapi import APIRouter, Depends, HTTPException
from app.utils.auth import get_current_admin
from app.cache.redis_manager import get_redis
from db.db_manager import get_database, DatabaseManager
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/")
async def get_metrics(
    current_user = Depends(get_current_admin),  # ✅ Admin only
    db: DatabaseManager = Depends(get_database)
):
    """
    Get application metrics and statistics
    Requires admin authentication
    """
    try:
        redis = get_redis()
        
        # Redis metrics
        redis_info = await redis.redis.info()
        redis_stats = await redis.get_stats()
        
        # Database metrics
        db_stats = await db.db.command("dbStats")
        
        # Collection counts
        users_count = await db.count_documents("users", {})
        products_count = await db.count_documents("products", {"is_active": True})
        orders_count = await db.count_documents("orders", {})
        carts_count = await db.count_documents("carts", {})
        
        # Today's orders
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_orders = await db.count_documents("orders", {
            "created_at": {"$gte": today_start}
        })
        
        # Revenue today
        today_revenue_pipeline = [
            {"$match": {
                "created_at": {"$gte": today_start},
                "order_status": {"$nin": ["cancelled", "refunded"]}
            }},
            {"$group": {
                "_id": None,
                "total": {"$sum": "$total_amount"}
            }}
        ]
        
        revenue_result = await db.aggregate("orders", today_revenue_pipeline)
        today_revenue = revenue_result[0]["total"] if revenue_result else 0
        
        # Get slow requests from today
        slow_requests_key = f"slow_requests:{datetime.utcnow().strftime('%Y-%m-%d')}"
        try:
            slow_requests_raw = await redis.redis.zrevrange(
                slow_requests_key, 0, 9, withscores=True
            )
            slow_requests = [
                {
                    "endpoint": req[0].decode() if isinstance(req[0], bytes) else req[0],
                    "duration": round(req[1], 3)
                }
                for req in slow_requests_raw
            ]
        except:
            slow_requests = []
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": "calculated_uptime",
            "redis": {
                "l1_cache_size": redis_stats.get("l1_cache_size", 0),
                "l2_connected": redis_stats.get("l2_connected", False),
                "l2_used_memory": redis_stats.get("l2_used_memory", "N/A"),
                "l2_connected_clients": redis_stats.get("l2_connected_clients", 0),
                "l2_hit_rate": redis_stats.get("l2_hit_rate", 0),
                "total_commands": redis_info.get('total_commands_processed', 0)
            },
            "database": {
                "collections": db_stats.get('collections', 0),
                "objects": db_stats.get('objects', 0),
                "data_size_mb": round(db_stats.get('dataSize', 0) / (1024 * 1024), 2),
                "storage_size_mb": round(db_stats.get('storageSize', 0) / (1024 * 1024), 2),
                "indexes": db_stats.get('indexes', 0),
                "index_size_mb": round(db_stats.get('indexSize', 0) / (1024 * 1024), 2)
            },
            "application": {
                "users_total": users_count,
                "products_active": products_count,
                "orders_total": orders_count,
                "active_carts": carts_count,
                "orders_today": today_orders,
                "revenue_today": round(today_revenue, 2)
            },
            "performance": {
                "slow_requests_today": len(slow_requests),
                "top_slow_endpoints": slow_requests[:5]
            }
        }
    except Exception as e:
        logger.error(f"❌ Metrics error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch metrics"
        )

@router.get("/cache-stats")
async def get_cache_stats(
    current_user = Depends(get_current_admin)
):
    """Get detailed cache statistics"""
    try:
        redis = get_redis()
        stats = await redis.get_stats()
        
        # Additional cache insights
        info = await redis.redis.info()
        
        return {
            **stats,
            "keyspace": info.get('db0', {}),
            "memory": {
                "used": info.get('used_memory_human', 'N/A'),
                "peak": info.get('used_memory_peak_human', 'N/A'),
                "fragmentation_ratio": info.get('mem_fragmentation_ratio', 0)
            },
            "stats": {
                "evicted_keys": info.get('evicted_keys', 0),
                "expired_keys": info.get('expired_keys', 0)
            }
        }
    except Exception as e:
        logger.error(f"❌ Cache stats error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch cache stats"
        )