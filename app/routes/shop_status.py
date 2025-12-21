from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import logging
from db.db_manager import DatabaseManager, get_database

logger = logging.getLogger(__name__)
router = APIRouter()

class ShopStatusUpdate(BaseModel):
    is_open: bool
    reopen_time: Optional[str] = None
    reason: Optional[str] = None

class ShopStatusResponse(BaseModel):
    is_open: bool
    reopen_time: Optional[str] = None
    reason: Optional[str] = None
    updated_at: str
    updated_by: str

@router.get("/status")
async def get_shop_status(db: DatabaseManager = Depends(get_database)):
    """Get current shop status (public endpoint) - NO CACHE, DIRECT FROM DB"""
    try:
        logger.info("📡 Fetching shop status directly from database")
        
        # ✅ REMOVED: All caching logic - get directly from database
        status_doc = await db.find_one("shop_status", {})
        
        if not status_doc:
            logger.info("⚠️ No shop status found, creating default (open)")
            # Default to open if no status set
            default_status = {
                "is_open": True,
                "reopen_time": None,
                "reason": None,
                "updated_at": datetime.utcnow(),
                "updated_by": "system"
            }
            await db.insert_one("shop_status", default_status)
            
            response = {
                "is_open": True,
                "reopen_time": None,
                "reason": None,
                "updated_at": datetime.utcnow().isoformat(),
                "updated_by": "system"
            }
            
            logger.info(f"✅ Returning default shop status: {response}")
            return response
        
        # Format response
        response = {
            "is_open": status_doc.get("is_open", True),
            "reopen_time": status_doc.get("reopen_time"),
            "reason": status_doc.get("reason"),
            "updated_at": status_doc.get("updated_at", datetime.utcnow()).isoformat() if hasattr(status_doc.get("updated_at"), 'isoformat') else str(status_doc.get("updated_at", datetime.utcnow().isoformat())),
            "updated_by": status_doc.get("updated_by", "admin")
        }
        
        logger.info(f"✅ Shop status from DB: is_open={response['is_open']}, reason={response.get('reason')}")
        
        # ✅ REMOVED: No caching - return fresh data every time
        return response
        
    except Exception as e:
        logger.error(f"❌ Get shop status error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        
        # Return default open status on error
        return {
            "is_open": True,
            "reopen_time": None,
            "reason": None,
            "updated_at": datetime.utcnow().isoformat(),
            "updated_by": "system"
        }