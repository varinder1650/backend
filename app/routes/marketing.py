# backend/app/routes/marketing.py
from fastapi import APIRouter, Depends, HTTPException, status
import logging
from db.db_manager import DatabaseManager, get_database
from app.utils.mongo import fix_mongo_types
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_KEY = "marketing:active_banners"
CACHE_TTL = 300  # 5 minutes


@router.get("/banners")
async def get_active_banners(db: DatabaseManager = Depends(get_database)):
    """Return all active marketing banners sorted by order (public endpoint)"""
    try:
        redis = get_redis()
        # use_l1=False: skip in-memory cache — admin-backend can only invalidate Redis (L2),
        # not the main backend's in-process memory. L2-only ensures invalidation works instantly.
        cached = await redis.get(CACHE_KEY, use_l1=False)
        if cached:
            logger.info("⚡ Marketing banners cache HIT")
            return cached

        banners = await db.find_many(
            "marketing_banners",
            {"is_active": True},
            sort=[("order", 1)],
        )

        result = []
        for b in banners:
            fixed = fix_mongo_types(b)
            result.append(fixed)

        await redis.set(CACHE_KEY, result, CACHE_TTL, use_l1=False)
        logger.info("💾 Marketing banners cached")
        return result

    except Exception as e:
        logger.error(f"Get marketing banners error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get marketing banners",
        )
