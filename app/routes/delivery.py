from bson import ObjectId
from fastapi import HTTPException,APIRouter, Depends, status,BackgroundTasks
from app.utils.auth import current_active_user
from app.utils.mongo import fix_mongo_types
from db.db_manager import DatabaseManager, get_database
from schema.user import UserinDB
import logging
from app.routes.notifications import create_notification
from app.services.email_service import email_service
from app.utils.get_time import get_ist_datetime_for_db

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/available")
async def get_available_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get orders that are available for delivery assignment"""
    try:
        # Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can access this endpoint."
            )
        
        # Find orders that are confirmed but not yet assigned to any delivery partner
        orders = await db.find_many(
            "orders",
            {
                "order_status": {"$in" : ["assigning"]}
            },
            sort=[("created_at", -1)]
        )
        
        enhanced_orders = []
        for order in orders:
            try:
                # Get user info for each order
                user_info = await db.find_one("users", {"id": order["user"]})
                if user_info:
                    order["user_info"] = {
                        "name": user_info.get("name", "N/A"),
                        "phone": user_info.get("phone", "N/A"),
                        "email": user_info.get("email", "N/A")
                    }
                    
                # Process items to add product details
                if "items" in order and isinstance(order["items"], list):
                    for item in order["items"]:
                        try:
                            if isinstance(item.get('product'), (str, ObjectId)):
                                product_id = item['product']
                                product = await db.find_one("products", {"id": product_id})
                                if product:
                                    item["product_name"] = product["name"]
                                    item["product_image"] = product.get("images", [])
                                item['product'] = str(item['product'])  # Convert to string
                        except Exception as item_error:
                            logger.error(f"Error processing item: {item_error}")
                            item["product_name"] = "Error loading product"
                            item["product_image"] = []
                
                fixed_order = fix_mongo_types(order)
                enhanced_orders.append(fixed_order)
                    
            except Exception as order_error:
                logger.error(f"Error processing order {order.get('id')}: {order_error}")
                continue
        
        logger.info(f"Returning {len(enhanced_orders)} available orders for delivery")
        return enhanced_orders
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get available delivery orders error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get available orders"
        )

@router.get("/assigned")
async def get_assigned_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get orders assigned to the current delivery partner"""
    try:
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can access this endpoint."
            )
        
        # Find orders assigned to this delivery partner
        orders = await db.find_many(
            "orders",
            {
                "delivery_partner": current_user.id,
                "order_status": {"$in":["assigned","out_for_delivery"]}
            },
            sort=[("created_at", -1)]
        )
        
        enhanced_orders = []
        for order in orders:
            try:
                # Get user info for each order
                user_info = await db.find_one("users", {"id": order["user"]})
                if user_info:
                    order["user_info"] = {
                        "name": user_info.get("name", "N/A"),
                        "phone": user_info.get("phone", "N/A"),
                        "email": user_info.get("email", "N/A")
                    }
                
                # Process items to add product details
                if "items" in order and isinstance(order["items"], list):
                    for item in order["items"]:
                        try:
                            if isinstance(item.get('product'), (str, ObjectId)):
                                product_id = item['product']
                                product = await db.find_one("products", {"id": product_id})
                                if product:
                                    item["product_name"] = product["name"]
                                    item["product_image"] = product.get("images", [])
                                item['product'] = str(item['product'])  # Convert to string
                        except Exception as item_error:
                            logger.error(f"Error processing item: {item_error}")
                            item["product_name"] = "Error loading product"
                            item["product_image"] = []
                
                fixed_order = fix_mongo_types(order)
                enhanced_orders.append(fixed_order)
                
            except Exception as order_error:
                logger.error(f"Error processing order {order.get('id')}: {order_error}")
                continue
            # print(enhanced_orders)
        logger.info(f"Returning {len(enhanced_orders)} assigned orders for delivery partner {current_user.id}")
        return enhanced_orders
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get assigned delivery orders error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get assigned orders"
        )

@router.get("/delivered")
async def get_delivered_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get orders that have been delivered by the current delivery partner"""
    try:
        # Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can access this endpoint."
            )
        
        # Find delivered orders by this delivery partner
        orders = await db.find_many(
            "orders",
            {
                "delivery_partner": current_user.id,
                "order_status": "delivered"
            },
            sort=[("updated_at", -1)]  # Sort by delivery date
        )
        
        enhanced_orders = []
        for order in orders:
            try:
                # Get user info for each order
                user_info = await db.find_one("users", {"id": order["user"]})
                if user_info:
                    order["user_info"] = {
                        "name": user_info.get("name", "N/A"),
                        "phone": user_info.get("phone", "N/A"),
                        "email": user_info.get("email", "N/A")
                    }
                
                # Process items to add product details
                if "items" in order and isinstance(order["items"], list):
                    for item in order["items"]:
                        try:
                            if isinstance(item.get('product'), (str, ObjectId)):
                                product_id = item['product']
                                product = await db.find_one("products", {"id": product_id})
                                if product:
                                    item["product_name"] = product["name"]
                                    item["product_image"] = product.get("images", [])
                                item['product'] = str(item['product'])  # Convert to string
                        except Exception as item_error:
                            logger.error(f"Error processing item: {item_error}")
                            item["product_name"] = "Error loading product"
                            item["product_image"] = []
                
                fixed_order = fix_mongo_types(order)
                enhanced_orders.append(fixed_order)
                
            except Exception as order_error:
                logger.error(f"Error processing order {order.get('id')}: {order_error}")
                continue
        
        logger.info(f"Returning {len(enhanced_orders)} delivered orders for delivery partner {current_user.id}")
        return enhanced_orders
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get delivered orders error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get delivered orders"
        )

@router.post("/{order_id}/accept")
async def accept_delivery_order(
    order_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Accept an order for delivery"""
    try:
        # Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can accept orders."
            )
        
        # Validate order_id
        try:
            order_object_id = str(order_id)
        except Exception:
            logger.error("Invalid order ID")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid order ID format"
            )
        
        # Check if order exists and is available for assignment
        order = await db.find_one("orders", {"id": order_object_id})
        if not order:
            logger.error("Order not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Check if order is already assigned
        if order.get("delivery_partner"):
            logger.info("Order already assigned to other agent")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is already assigned to another delivery partner"
            )
        
        # Check if order status allows assignment
        if order.get("order_status") not in ["preparing","assigning"]:
            logger.error("can't be assigned")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order with status '{order.get('order_status')}' cannot be assigned for delivery"
            )

        accepted_partners = order.get("accepted_partners",[])
        if current_user.id in accepted_partners:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already accepted this order"
            )
        accepted_partners.append(current_user.id)
        
        current_time = get_ist_datetime_for_db()
        status_history_entry = {
            "status": "assigning",
            "changed_at": current_time['ist'],
            "changed_at_ist": current_time['ist_string'],
            "changed_by": current_user.name,
            "partner_id": current_user.id,
            "message": f"{current_user.name} accepted the order"
        }
        # print(status_history_entry)
        update_data = {
            "$set": {
                "accepted_partners": accepted_partners,
                "order_status": "assigning",
                "accepted_at": current_time['ist'],
                "accepted_at_ist": current_time['ist_string'],
                "updated_at": current_time['ist'],
                "updated_at_ist": current_time['ist_string'],
                "status_message": f"Order accepted by {current_user.name}"
            },
            "$push": {
                "status_change_history": status_history_entry
            }
        }

        await db.update_one(
            "orders",
            {"id": order_id},
            update_data
        )
        
        # Create notification for user
        await create_notification(
            db=db,
            user_id=order.get("user"),
            title="Delivery Partner Found",
            message=f"A delivery partner is reviewing your order from {order.get('restaurant_name', 'the restaurant')}.",
            notification_type="order",
            order_id=order_id
        )
        
        logger.info(f"Order {order_id} assigned to delivery partner {current_user.id}")
        
        return {"message": "Order accepted successfully", "order_id": order_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Accept delivery order error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept order"
        )


@router.post("/{order_id}/mark-delivered")
async def mark_order_as_delivered(
    order_id: str,
    background_tasks: BackgroundTasks,  # Add this
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Mark an assigned order as delivered"""
    try:
        #    Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can mark orders as delivered."
            )
        order = await db.find_one("orders", {
            "id": order_id,
            "delivery_partner": current_user.id
        })
      
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or not assigned to you"
            )
        
        # Check if order status allows marking as delivered
        if order.get("order_status") not in ["out_for_delivery"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order with status '{order.get('order_status')}' cannot be marked as delivered"
            )
        
        current_time = get_ist_datetime_for_db()
        
        # Mark the order as delivered with proper timeline
        await db.update_one(
            "orders",
            {"id": order_id},
            {
                "$set": {
                    "order_status": "delivered",
                    "delivered_at":current_time['ist'],
                    "delivered_at_ist": current_time['ist_string'],
                    "payment_status": "completed" if order.get("payment_method") == "cod" else order.get("payment_status"),
                    "updated_at": current_time['ist'],
                    "updated_at_ist": current_time['ist_string'],
                    "status_message": "Order delivered successfully!"
                },
                "$push": {
                    "status_change_history": {
                        "status": "delivered",
                        "changed_at": current_time['ist'],
                        "changed_at_ist": current_time['ist_string'],
                        "changed_by": current_user.name,
                        "message": f"Order delivered by {current_user.name}"
                    }
                }
            }
        )
        
        # Get user info for email
        user_info = await db.find_one("users", {"id": order.get("user")})
        
        # Create notification for user
        await create_notification(
            db=db,
            user_id=order.get("user"),
            title="Order Delivered! 🎉",
            message=f"Your order from {order.get('restaurant_name', 'the restaurant')} has been delivered. Enjoy your meal!",
            notification_type="order",
            order_id=order_id
        )
        
        # Send email notification in background
        if user_info and user_info.get("email"):
            background_tasks.add_task(
                email_service.send_order_status_update,
                user_info.get("email"),
                order_id,
                "delivered",
                user_info.get("name", "Customer")
            )
        
        logger.info(f"Order {order_id} marked as delivered by delivery partner {current_user.id}")
        
        return {"message": "Order marked as delivered successfully", "order_id": order_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mark order as delivered error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark order as delivered"
        )