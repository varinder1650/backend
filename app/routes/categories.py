from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
import logging
from db.db_manager import DatabaseManager, get_database
from schema.category import CategoryResponse
from app.utils.mongo import fix_mongo_types
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

# @router.get("/", response_model=List[CategoryResponse])
# async def get_categories(db: DatabaseManager = Depends(get_database)):
#     """Get all active categories"""
#     try:
#         # Add better error handling and filters
#         categories = await db.find_many(
#             "categories", 
#             {"is_active": True},  # Only get active categories
#             sort=[("name", 1)]
#         )

#         processed_categories = []
#         for category in categories:
#             if category:
#                 # Use the mongo fix utility
#                 fixed_category = fix_mongo_types(category)
#                 processed_categories.append(fixed_category)
 
#         return processed_categories

#     except Exception as e:
#         logger.error(f"Get categories error: {e}")
#         # Log the full traceback for debugging
#         import traceback
#         logger.error(f"Full traceback: {traceback.format_exc()}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to get categories"    
#         )

@router.get("/", response_model=List[CategoryResponse])
async def get_categories(db: DatabaseManager = Depends(get_database)):
    """Get all active categories with caching"""
    try:
        redis = get_redis()
        cache_key = "categories:all"
        
        # ✅ Check cache first
        cached_categories = await redis.get(cache_key, use_l1=True)
        if cached_categories:
            logger.info("⚡ Categories cache HIT")
            return cached_categories
        
        logger.info("💾 Categories cache MISS")
        
        # Fetch from database
        categories = await db.find_many(
            "categories", 
            {"is_active": True},
            sort=[("name", 1)]
        )

        processed_categories = []
        for category in categories:
            if category:
                fixed_category = fix_mongo_types(category)
                processed_categories.append(fixed_category)
        
        # ✅ Cache for 2 hours
        await redis.set(cache_key, processed_categories, 7200, use_l1=True)
        logger.info("💾 Cached categories")
        
        return processed_categories

    except Exception as e:
        logger.error(f"Get categories error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get categories"    
        )