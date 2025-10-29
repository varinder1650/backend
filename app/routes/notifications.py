from datetime import datetime, timedelta
from bson.objectid import ObjectId
from fastapi import HTTPException, APIRouter, Depends, status
from typing import Optional, List
import logging

from app.utils.auth import current_active_user
from app.utils.mongo import fix_mongo_types
from db.db_manager import DatabaseManager, get_database
from schema.user import UserinDB
from pydantic import BaseModel, Field
from app.utils.get_time import get_ist_datetime_for_db

router = APIRouter()
logger = logging.getLogger(__name__)

class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str
    order_id: Optional[str] = None
    user_id: str

class NotificationResponse(BaseModel):
    id: str
    title: str
    message: str
    type: str
    read: bool
    created_at: datetime
    order_id: Optional[str] = None

async def create_notification(
    db: DatabaseManager,
    user_id: str,
    title: str,
    message: str,
    notification_type: str,
    order_id: Optional[str] = None
):
    """Helper function to create notifications"""
    try:
        current_time = get_ist_datetime_for_db()

        notification_data = {
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "order_id": order_id,
            "for": 'specific_user',
            "read": False,
            "read_at": None,
            "created_at": current_time['ist'],
            "created_at_ist": current_time['ist_string']
        }
        
        result = await db.insert_one("notifications", notification_data)
        logger.info(f"Notification created for user {user_id}: {title}")
        return result
    except Exception as e:
        logger.error(f"Error creating notification: {str(e)}")
        raise


@router.get('/')
async def get_notifications(
    skip: int = 0,
    limit: int = 50,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get all notifications for the current user from the last 3 days
    """
    try:
        # ✅ Calculate 3 days ago timestamp
        three_days_ago = datetime.utcnow() - timedelta(days=3)
        
        logger.info(f"Fetching notifications for user {current_user.id} from last 3 days (since {three_days_ago})")
        
        # ✅ Query with 3-day filter
        notifications = await db.find_many(
            "notifications",
            {
                "$or": [
                    {
                        "user_id": current_user.id, 
                        "for": "specific_user",
                        "created_at": {"$gte": three_days_ago}
                    },
                    {
                        "for": "all_users",
                        "created_at": {"$gte": three_days_ago}
                    }
                ]
            },
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit
        )

        fixed_notifications = [fix_mongo_types(notif) for notif in notifications]

        return {
            "notifications": [
                {
                    "id": str(notif["_id"]),
                    "title": notif["title"],
                    "message": notif["message"],
                    "type": notif["type"],
                    "for": notif.get("for", "specific_user"),
                    "read": (
                        notif.get("read", False) if notif.get("for") == "specific_user"
                        else current_user.id in notif.get("read_by", [])
                    ),
                    "created_at": notif.get("created_at") or notif["created_at"].isoformat(),
                    "order_id": notif.get("order_id")
                }
                for notif in fixed_notifications
            ]
        }
    except Exception as e:
        logger.error(f"Error fetching notifications: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch notifications"
        )

@router.put('/{notification_id}/read')
async def mark_notification_as_read(
    notification_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Mark a specific notification as read"""
    try:
        if not ObjectId.is_valid(notification_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid notification ID format"
            )

        notification = await db.find_one(
            "notifications",
            {
                "_id": ObjectId(notification_id),
                "$or": [
                    {"user_id": current_user.id, "for": "specific_user"},
                    {"for": "all_users"}
                ]
            },
        )

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )

        # Handle based on notification type
        if notification.get('for') == 'specific_user':
            # Check if already read
            if notification.get('read', False):
                logger.info(f"Notification {notification_id} already marked as read for user {current_user.id}")
                return {
                    "message": "Notification already marked as read",
                    "id": notification_id,
                    "already_read": True
                }
            
            # For specific user notifications, mark as read
            current_time = get_ist_datetime_for_db()
            await db.update_one(
                "notifications",
                {"_id": ObjectId(notification_id)},
                {
                    "$set": {
                        "read": True,
                        "read_at": current_time['ist'],
                        "read_at_ist": current_time['ist_string']
                    }
                }
            )
            logger.info(f"Marked specific notification {notification_id} as read for user {current_user.id}")
        else:
            # For broadcast notifications - check if user already in read_by list
            read_by_list = notification.get("read_by", [])
            if current_user.id in read_by_list:
                logger.info(f"User {current_user.id} already read broadcast notification {notification_id}")
                return {
                    "message": "Notification already marked as read",
                    "id": notification_id,
                    "already_read": True
                }
            
            # Add user to read_by list
            current_time = get_ist_datetime_for_db()
            await db.update_one(
                "notifications",
                {"_id": ObjectId(notification_id)},
                {
                    "$addToSet": {  # Prevents duplicate user IDs
                        "read_by": current_user.id
                    },
                    "$set": {
                        f"read_by_details.{current_user.id}": {
                            "read_at": current_time['ist'],
                            "read_at_ist": current_time['ist_string']
                        }
                    }
                }
            )
            logger.info(f"Added user {current_user.id} to read_by list for broadcast notification {notification_id}")

        return {
            "message": "Notification marked as read",
            "id": notification_id,
            "already_read": False
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )

@router.get('/unread-count')
async def get_unread_count(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get count of unread notifications for current user from the last 3 days"""
    try:
        # ✅ Calculate 3 days ago timestamp
        three_days_ago = datetime.utcnow() - timedelta(days=3)
        
        # ✅ Count specific user notifications that are unread (last 3 days)
        specific_count = await db.count_documents(
            "notifications",
            {
                "user_id": current_user.id,
                "for": "specific_user",
                "read": False,
                "created_at": {"$gte": three_days_ago}
            }
        )

        # ✅ Count broadcast notifications where user hasn't read yet (last 3 days)
        broadcast_notifications = await db.find_many(
            "notifications",
            {
                "for": "all_users",
                "created_at": {"$gte": three_days_ago}
            }
        )

        # Count broadcasts where current user is NOT in read_by list
        broadcast_unread_count = sum(
            1 for notif in broadcast_notifications
            if current_user.id not in notif.get("read_by", [])
        )

        total_unread = specific_count + broadcast_unread_count

        logger.info(f"Unread count (last 3 days) for {current_user.id}: {total_unread} (specific: {specific_count}, broadcast: {broadcast_unread_count})")

        return {
            "count": total_unread
        }
    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get unread count"
        )

@router.delete('/{notification_id}')
async def delete_notification(
    notification_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Delete a specific notification (only for specific_user notifications)"""
    try:
        if not ObjectId.is_valid(notification_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid notification ID format"
            )

        notification = await db.find_one(
            "notifications",
            {
                "_id": ObjectId(notification_id),
                "user_id": current_user.id,
                "for": "specific_user"
            }
        )

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found or cannot be deleted"
            )

        await db.delete_one(
            "notifications",
            {"_id": ObjectId(notification_id)}
        )

        logger.info(f"Notification {notification_id} deleted by user {current_user.id}")

        return {
            "message": "Notification deleted successfully",
            "id": notification_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting notification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete notification"
        )


# ✅ OPTIONAL: Background job to clean old notifications
async def cleanup_old_notifications(db: DatabaseManager):
    """
    Background job to delete notifications older than 3 days
    Run this daily via cron job or scheduler
    """
    try:
        three_days_ago = datetime.utcnow() - timedelta(days=3)
        
        result = await db.delete_many(
            "notifications",
            {"created_at": {"$lt": three_days_ago}}
        )
        
        deleted_count = result.deleted_count if hasattr(result, 'deleted_count') else 0
        logger.info(f"Cleaned up {deleted_count} old notifications (older than 3 days)")
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up old notifications: {e}")
        return 0