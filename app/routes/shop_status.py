from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import logging
# from app.utils.auth import get_current_user
from db.db_manager import DatabaseManager, get_database
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

class ShopStatusUpdate(BaseModel):
    is_open: bool
    reopen_time: Optional[str] = None  # ISO format datetime string
    reason: Optional[str] = None

class ShopStatusResponse(BaseModel):
    is_open: bool
    reopen_time: Optional[str] = None
    reason: Optional[str] = None
    updated_at: str
    updated_by: str

@router.get("/status")
async def get_shop_status(db: DatabaseManager = Depends(get_database)):
    """Get current shop status (public endpoint)"""
    try:
        redis = get_redis()
        
        # Try cache first
        cached_status = await redis.get("shop_status")
        if cached_status:
            return cached_status
        
        # Get from database
        status_doc = await db.find_one("shop_status", {})
        
        if not status_doc:
            # Default to open if no status set
            default_status = {
                "is_open": True,
                "reopen_time": None,
                "reason": None,
                "updated_at": datetime.utcnow().isoformat(),
                "updated_by": "system"
            }
            await db.insert_one("shop_status", default_status)
            await redis.set("shop_status", default_status, 300)  # 5 min cache
            return default_status
        
        # Format response
        response = {
            "is_open": status_doc.get("is_open", True),
            "reopen_time": status_doc.get("reopen_time"),
            "reason": status_doc.get("reason"),
            "updated_at": status_doc.get("updated_at", datetime.utcnow()).isoformat(),
            "updated_by": status_doc.get("updated_by", "admin")
        }
        
        # Cache for 5 minutes
        await redis.set("shop_status", response, 300)
        
        return response
        
    except Exception as e:
        logger.error(f"Get shop status error: {e}")
        # Return default open status on error
        return {
            "is_open": True,
            "reopen_time": None,
            "reason": None,
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": "system"
        }

# @router.post("/status", response_model=ShopStatusResponse)
# async def update_shop_status(
#     status_update: ShopStatusUpdate,
#     current_user = Depends(get_current_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     """Update shop status (admin only)"""
#     try:
#         # Check if user is admin
#         if current_user.role != "admin":
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Only admins can update shop status"
#             )
        
#         # Validate reopen_time if shop is being closed
#         if not status_update.is_open and status_update.reopen_time:
#             try:
#                 reopen_datetime = datetime.fromisoformat(status_update.reopen_time.replace('Z', '+00:00'))
#                 if reopen_datetime <= datetime.utcnow():
#                     raise HTTPException(
#                         status_code=status.HTTP_400_BAD_REQUEST,
#                         detail="Reopen time must be in the future"
#                     )
#             except ValueError as e:
#                 raise HTTPException(
#                     status_code=status.HTTP_400_BAD_REQUEST,
#                     detail="Invalid datetime format"
#                 )
        
#         status_doc = {
#             "is_open": status_update.is_open,
#             "reopen_time": status_update.reopen_time,
#             "reason": status_update.reason,
#             "updated_at": datetime.utcnow(),
#             "updated_by": current_user.email
#         }
        
#         # Update or insert
#         existing = await db.find_one("shop_status", {})
        
#         if existing:
#             await db.update_one(
#                 "shop_status",
#                 {"_id": existing["_id"]},
#                 {"$set": status_doc}
#             )
#         else:
#             await db.insert_one("shop_status", status_doc)
        
#         # Invalidate cache
#         redis = get_redis()
#         await redis.delete("shop_status")
        
#         # Broadcast to all connected users via WebSocket (if implemented)
#         try:
#             from app.services.websocket_service import realtime_service
#             await realtime_service.manager.broadcast({
#                 "type": "shop_status_changed",
#                 "is_open": status_update.is_open,
#                 "reopen_time": status_update.reopen_time,
#                 "reason": status_update.reason,
#                 "message": "Shop availability has been updated"
#             })
#         except Exception as ws_error:
#             logger.warning(f"WebSocket broadcast failed: {ws_error}")
        
#         logger.info(f"Shop status updated by {current_user.email}: is_open={status_update.is_open}")
        
#         return ShopStatusResponse(
#             is_open=status_update.is_open,
#             reopen_time=status_update.reopen_time,
#             reason=status_update.reason,
#             updated_at=status_doc["updated_at"].isoformat(),
#             updated_by=current_user.email
#         )
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Update shop status error: {e}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to update shop status"
#         )

# @router.post("/status/auto-open")
# async def schedule_auto_reopen(db: DatabaseManager = Depends(get_database)):
#     """Background task to automatically reopen shop at scheduled time"""
#     try:
#         status_doc = await db.find_one("shop_status", {})
        
#         if not status_doc or status_doc.get("is_open"):
#             return  # Already open or no status set
        
#         reopen_time_str = status_doc.get("reopen_time")
#         if not reopen_time_str:
#             return  # No scheduled reopen time
        
#         reopen_time = datetime.fromisoformat(reopen_time_str.replace('Z', '+00:00'))
        
#         # Check if it's time to reopen
#         if datetime.utcnow() >= reopen_time:
#             await db.update_one(
#                 "shop_status",
#                 {"_id": status_doc["_id"]},
#                 {
#                     "$set": {
#                         "is_open": True,
#                         "reopen_time": None,
#                         "reason": None,
#                         "updated_at": datetime.utcnow(),
#                         "updated_by": "system_auto_reopen"
#                     }
#                 }
#             )
            
#             # Invalidate cache
#             redis = get_redis()
#             await redis.delete("shop_status")
            
#             # Broadcast reopening
#             try:
#                 from app.services.websocket_service import realtime_service
#                 await realtime_service.manager.broadcast({
#                     "type": "shop_reopened",
#                     "message": "Shop is now open for orders!"
#                 })
#             except:
#                 pass
            
#             logger.info("Shop automatically reopened")
        
#     except Exception as e:
#         logger.error(f"Auto-reopen error: {e}")

# Add this route to your app.py
"""
# Also add a background task runner for auto-reopen
# In main.py lifespan:

from apscheduler.schedulers.asyncio import AsyncIOScheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existing setup
    
    # Schedule auto-reopen check every minute
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        schedule_auto_reopen,
        'interval',
        minutes=1,
        args=[get_database()]
    )
    scheduler.start()
    app.state.scheduler = scheduler
    
    yield
    
    # Cleanup
    if hasattr(app.state, 'scheduler'):
        app.state.scheduler.shutdown()
"""