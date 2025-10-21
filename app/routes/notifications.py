from datetime import datetime
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


# Pydantic schemas
class NotificationCreate(BaseModel):
    title: str
    message: str
    type: str  # 'order', 'promotion', 'system'
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


# Helper function to create notifications
async def create_notification(
    db: DatabaseManager,
    user_id: str,
    title: str,
    message: str,
    notification_type: str,
    order_id: Optional[str] = None
):
    """
    Helper function to create notifications
    Used internally by other endpoints
    """
    try:
        current_time = get_ist_datetime_for_db()

        notification_data = {
            "user_id": user_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "order_id": order_id,
            "for":'specific_user',
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
    Get all notifications for the current user
    """
    try:
        notifications = await db.find_many(
            "notifications",
            {
                "$or": [
                    {"user_id": current_user.id, "for": "specific_user"},
                    {"for": "all_users"}
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
                    "read": notif.get("read", False) if notif.get("for") == "specific_user" else False,
                    "created_at": notif.get("created_at") or notif["created_at"].isoformat(),  # ✅ Use IST string
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

# Mark notification as read
@router.put('/{notification_id}/read')
async def mark_notification_as_read(
    notification_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Mark a specific notification as read
    """
    try:
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
        if notification['for'] == 'specific_user':
            current_time = get_ist_datetime_for_db()

            await db.update_one(
                "notifications",
                {"_id": ObjectId(notification_id)},
                {
                    "$set": {
                        "read": True,
                        "read_at":current_time['ist'],
                        "read_at_ist": current_time('ist_string')
                    }
                }
            )

        return {
            "message": "Notification marked as read",
            "id": notification_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notification as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark notification as read"
        )


# Mark all notifications as read
# @router.put('/read-all')
# async def mark_all_notifications_as_read(
#     current_user: UserinDB = Depends(current_active_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     """
#     Mark all notifications as read for the current user
#     """
#     try:
#         await db.update_many(
#             "notifications",
#             {"user_id": current_user.id, "read": False},
#             {
#                 "$set": {
#                     "read": True,
#                     "read_at": datetime.utcnow()
#                 }
#             }
#         )

#         return {
#             "message": "All notifications marked as read"
#         }
#     except Exception as e:
#         logger.error(f"Error marking all notifications as read: {str(e)}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to mark all notifications as read"
#         )


# Get unread count
@router.get('/unread-count')
async def get_unread_count(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get count of unread notifications for current user
    """
    try:
        count = await db.count_documents(
            "notifications",
            {
                "read": False,
                "$or": [
                        {"user_id": current_user.id, "for": "specific_user"},
                        {"for": "all_users"}
                    ]
            }
        )

        return {
            "count": count or 0
        }
    except Exception as e:
        logger.error(f"Error getting unread count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get unread count"
        )


# Delete notification
@router.delete('/{notification_id}')
async def delete_notification(
    notification_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Delete a specific notification
    """
    try:
        notification = await db.find_one(
            "notifications",
            {"id": notification_id, "user_id": current_user.id}
        )

        if not notification:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Notification not found"
            )

        await db.delete_one(
            "notifications",
            {"id": notification_id}
        )

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