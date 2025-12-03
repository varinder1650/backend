from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
import logging
from typing import Optional
from app.cache.redis_manager import get_redis
from app.services.order_service import OrderService
from app.services.email_service import email_service
from app.routes.notifications import create_notification
from app.utils.auth import current_active_user, get_current_user
from db.db_manager import DatabaseManager, get_database
from schema.order import OrderResponse, OrderResponseEnhanced, OrderRating
from schema.user import UserinDB
from app.utils.mongo import fix_mongo_types
from app.utils.id_generator import get_id_generator
from pydantic import BaseModel, Field
from app.utils.get_time import get_ist_datetime_for_db,utc_to_ist

id_generator = get_id_generator()

logger = logging.getLogger(__name__)
router = APIRouter()

# @router.post("/")
# async def create_order(
#     order_data: dict,
#     background_tasks: BackgroundTasks,
#     current_user: UserinDB = Depends(current_active_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     try:
#         logger.info(f"Order creation request from user: {current_user.email}")
#         logger.info(f"Order data received: {order_data}")
        
#         order_service = OrderService(db)
#         custom_id = await id_generator.generate_order_id(current_user.id)
        
#         # ✅ This already handles stock deduction atomically
#         order_id = await order_service.create_order(order_data, current_user, custom_id)

#         logger.info(f"Order created successfully with ID: {order_id}")
        
#         # Get the created order details
#         created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
        
#         # Create notification for order confirmation
#         try:
#             await create_notification(
#                 db=db,
#                 user_id=current_user.id,
#                 title="Order Placed Successfully! ✓",
#                 message=f"Your order #{created_order.get('id', order_id)} has been placed and will be confirmed shortly.",
#                 notification_type="order",
#                 order_id=str(created_order.get('id', order_id))
#             )
#         except Exception as notif_error:
#             logger.error(f"Failed to create notification: {notif_error}")
        
#         # Invalidate user's cart and order caches
#         redis = get_redis()
#         try:
#             await redis.delete(f"cart:{current_user.id}")
#             await redis.delete(f"recent_orders:{current_user.id}")
#         except Exception as cache_error:
#             logger.warning(f"Cache invalidation error: {cache_error}")
        
#         # Add background tasks for order processing
#         background_tasks.add_task(
#             send_order_confirmation_email, 
#             created_order, 
#             current_user.email,
#             current_user.name
#         )
        
#         # ❌ REMOVE THIS - Stock is already deducted in order_service.create_order()
#         # background_tasks.add_task(update_inventory_after_order, order_data.get('items', []), db)
        
#         # Format response
#         created_order['id'] = str(created_order["id"])
#         created_order["user"] = str(created_order['user'])
#         for item in created_order.get("items", []):
#             if isinstance(item.get("product"), ObjectId):
#                 item["product"] = str(item["product"])

#         return OrderResponse(**created_order)
        
#     except ValueError as e:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail=str(e)
#         )
#     except Exception as e:
#         logger.error(f"Create order error: {e}")
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Failed to create order"
#         )

@router.post("/")
async def create_order(
    order_data: dict,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        logger.info(f"Order creation request from user: {current_user.email}")
        logger.info(f"Order data received: {order_data}")
        
        order_service = OrderService(db)
        custom_id = await id_generator.generate_order_id(current_user.id)
        
        order_id = await order_service.create_order(order_data, current_user, custom_id)

        logger.info(f"Order created successfully with ID: {order_id}")
        
        # Get the created order details
        created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
        
        # ✅ Create notification with push
        try:
            from app.routes.notifications import create_notification
            
            order_type = order_data.get('order_type', 'product')
            if order_type == 'printout':
                notification_title = "Printout Order Placed! 🖨️"
                notification_message = f"Your printout order #{created_order.get('id', order_id)} has been received and will be ready soon."
            else:
                notification_title = "Order Placed Successfully! ✅"
                notification_message = f"Your order #{created_order.get('id', order_id)} has been placed and will be confirmed shortly."
            
            await create_notification(
                db=db,
                user_id=current_user.id,
                title=notification_title,
                message=notification_message,
                notification_type="order",
                order_id=str(created_order.get('id', order_id))
            )
            logger.info(f"✅ Notification with push sent for order {order_id}")
        except Exception as notif_error:
            logger.error(f"Failed to create notification: {notif_error}")
        
        # Invalidate user's cart and order caches
        redis = get_redis()
        try:
            await redis.delete(f"cart:{current_user.id}")
            await redis.delete(f"recent_orders:{current_user.id}")
        except Exception as cache_error:
            logger.warning(f"Cache invalidation error: {cache_error}")
        
        # Add background tasks for order processing
        background_tasks.add_task(
            send_order_confirmation_email, 
            created_order, 
            current_user.email,
            current_user.name
        )
        
        # Format response
        created_order['id'] = str(created_order["id"])
        created_order["user"] = str(created_order['user'])
        for item in created_order.get("items", []):
            if isinstance(item.get("product"), ObjectId):
                item["product"] = str(item["product"])

        return OrderResponse(**created_order)
        
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Create order error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create order"
        )
        
@router.get("/my")
async def get_my_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get user's order history - NO CACHING for real-time status updates"""
    try:
        logger.info(f"Fetching orders for user {current_user.id}")
        
        skip = (page - 1) * limit
        total_orders = await db.count_documents("orders", {"user": current_user.id})
        total_pages = (total_orders + limit - 1) // limit if total_orders > 0 else 0
        
        orders = await db.find_many(
            "orders", 
            {"user": current_user.id},
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit
        )
        
        # Process orders
        enhanced_orders = []
        for order in orders:
            try:
                # Process items
                if "items" in order and isinstance(order["items"], list):
                    for item in order["items"]:
                        try:
                            if isinstance(item.get('product'), str):
                                product_id = item['product']
                            elif isinstance(item.get('product'), ObjectId):
                                product_id = item['product']
                                item['product'] = str(item['product'])
                            else:
                                continue

                            product = await db.find_one("products", {"id": product_id})
                            if product:
                                item["product_name"] = product["name"]
                                item["product_image"] = product.get("images", [])
                            else:
                                item["product_name"] = "Product not found"
                                item["product_image"] = []
                                
                        except Exception as item_error:
                            logger.error(f"Error processing item: {item_error}")
                            item["product_name"] = "Error loading product"
                            item["product_image"] = []
                
                # Fix MongoDB types
                fixed_order = fix_mongo_types(order)

                try:
                    validated_order = OrderResponseEnhanced(**fixed_order)
                    order_dict = validated_order.model_dump(by_alias=True)
                    enhanced_orders.append(order_dict)
                except Exception as validation_error:
                    logger.error(f"Validation error: {validation_error}")
                    enhanced_orders.append(fixed_order)
                    
            except Exception as order_error:
                logger.error(f"Error processing order: {order_error}")
                continue

        result = {
            "orders": enhanced_orders,
            "pagination": {
                "currentPage": page,
                "totalPages": total_pages,
                "totalOrders": total_orders,
                "hasNextPage": page < total_pages,
                "hasPrevPage": page > 1
            }
        }
        
        logger.info(f"✅ Returning {len(enhanced_orders)} fresh orders for page {page}")
        return result
        
    except Exception as e:
        logger.error(f"Get my orders error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get orders"
        )


@router.get("/active")
async def get_active_order(
    current_user = Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
) -> Optional[dict]:
    """Get user's most recent active order - NO CACHING for real-time status"""
    try:
        if not current_user:
            logger.info("No authenticated user found")
            return None
            
        logger.info(f"Fetching active order for user: {current_user.email}")
        
        # ✅ REMOVED CACHING - Always fetch fresh for active orders
        
        # ✅ Optimized aggregation - populate products in single query
        pipeline = [
            {
                "$match": {
                    "user": current_user.id,
                    "order_status": {
                        "$in": ["confirmed", "assigning", "preparing", "assigned", "out_for_delivery", "arrived"]
                    }
                }
            },
            {"$sort": {"created_at": -1}},
            {"$limit": 1},
            {
                "$lookup": {
                    "from": "products",
                    "let": {"item_products": "$items.product"},
                    "pipeline": [
                        {"$match": {"$expr": {"$in": ["$id", "$$item_products"]}}}
                    ],
                    "as": "product_details"
                }
            }
        ]
        
        orders = await db.aggregate("orders", pipeline)
        
        if not orders or len(orders) == 0:
            logger.info(f"No active order found for user {current_user.email}")
            return None
        
        order = orders[0]
        
        # ✅ Map products to items efficiently
        if "product_details" in order:
            product_map = {p["id"]: p for p in order["product_details"]}
            
            for item in order.get("items", []):
                product_id = item.get('product')
                product = product_map.get(product_id)
                
                if product:
                    item["product_name"] = product.get("name", "Unknown Product")
                    item["product_image"] = product.get("images", [])
                else:
                    item["product_name"] = "Product not found"
                    item["product_image"] = []
            
            # Remove product_details from response
            del order["product_details"]
        
        # Get delivery partner info if assigned
        if order.get('delivery_partner'):
            try:
                partner = await db.find_one(
                    "users",
                    {"id": order["delivery_partner"]},
                    projection={"name": 1, "phone": 1, "rating": 1, "total_deliveries": 1}
                )
                if partner:
                    order["delivery_partner"] = {
                        "name": partner.get("name"),
                        "phone": partner.get("phone"),
                        "rating": partner.get("rating", 4.5),
                        "deliveries": partner.get("total_deliveries", 0)
                    }
            except Exception as partner_error:
                logger.warning(f"Error fetching delivery partner: {partner_error}")
        
        # Add status message
        if not order.get("status_message"):
            status_messages = {
                "confirmed": "Your order has been confirmed and will be prepared soon.",
                "preparing": "We are preparing your order",
                "assigned": "Delivery Partner Assigned",
                "out_for_delivery": "Your order is on its way to you.",
                "arrived": "Delivery partner has arrived at your location!"
            }
            order["status_message"] = status_messages.get(
                order["order_status"], 
                "Your order is being processed."
            )
        
        # Serialize
        serialized_order = fix_mongo_types(order)
        
        logger.info(f"✅ Returning active order {serialized_order.get('id')} ({len(order.get('items', []))} items)")
        
        return serialized_order
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active order: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, 
            detail="Failed to fetch active order"
        )

# Background task helpers
async def send_order_confirmation_email(order: dict, email: str, customer_name: str):
    """Send order confirmation email"""
    try:
        # Prepare order data for email
        order_data = {
            'order_id': str(order.get('id', 'N/A')),
            'customer_name': customer_name,
            'items': [
                {
                    'name': item.get('product_name', 'Product'),
                    'quantity': item.get('quantity', 1),
                    'price': item.get('price', 0)
                }
                for item in order.get('items', [])
            ],
            'total_amount': order.get('total_amount', 0),
            'estimated_delivery': order.get('estimated_delivery_time', '30 minutes'),
            'restaurant_name': order.get('restaurant_name', 'Restaurant'),
            'delivery_address': order.get('delivery_address', {}).get('address', 'N/A')
        }
        
        await email_service.send_order_confirmation(email, order_data)
        logger.info(f"Order confirmation email sent for order {order_data['order_id']} to {email}")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

async def update_inventory_after_order(items: list, db: DatabaseManager):
    """
    LOG inventory changes after order completion
    NOTE: Stock is already deducted in order_service.create_order()
    This function is now only for logging/analytics
    """
    try:
        logger.info(f"📊 Inventory update summary for {len(items)} items:")
        for item in items:
            product_id = item.get('product_id') or item.get('product')
            quantity = item.get('quantity', 0)
            
            if product_id and quantity > 0:
                # ❌ DON'T DEDUCT - Already done in order_service
                # await db.update_one(
                #     "products",
                #     {"id": product_id},
                #     {"$inc": {"stock": -quantity}}
                # )
                
                # ✅ Just log for analytics
                product = await db.find_one("products", {"id": product_id})
                if product:
                    logger.info(f"   - {product.get('name')}: -{quantity} (current: {product.get('stock', 0)})")
        
    except Exception as e:
        logger.error(f"Inventory logging failed: {e}")

# @router.get("/active")
# async def get_active_order(
#     current_user = Depends(get_current_user),
#     db: DatabaseManager = Depends(get_database)
# ) -> Optional[dict]:
#     """Get user's most recent active order with caching"""
#     try:
#         if not current_user:
#             logger.info("No authenticated user found")
#             return None
            
#         logger.info(f"Fetching active order for user: {current_user.email}")
        
#         # ✅ Add Redis caching for active orders
#         from app.cache.redis_manager import get_redis
#         redis = get_redis()
#         cache_key = f"active_order:{current_user.id}"
        
#         # Check cache first
#         try:
#             cached_order = await redis.get(cache_key, use_l1=True)
#             if cached_order:
#                 logger.info(f"⚡ Active order cache HIT for {current_user.id}")
#                 return cached_order
#         except Exception as cache_error:
#             logger.warning(f"Cache read error: {cache_error}")
        
#         # ✅ Optimized aggregation - populate products in single query
#         pipeline = [
#             {
#                 "$match": {
#                     "user": current_user.id,
#                     "order_status": {
#                         "$in": ["confirmed", "assigning", "preparing", "assigned", "out_for_delivery", "arrived"]
#                     }
#                 }
#             },
#             {"$sort": {"created_at": -1}},
#             {"$limit": 1},
#             {
#                 "$lookup": {
#                     "from": "products",
#                     "let": {"item_products": "$items.product"},
#                     "pipeline": [
#                         {"$match": {"$expr": {"$in": ["$id", "$$item_products"]}}}
#                     ],
#                     "as": "product_details"
#                 }
#             }
#         ]
        
#         orders = await db.aggregate("orders", pipeline)
        
#         if not orders or len(orders) == 0:
#             logger.info(f"No active order found for user {current_user.email}")
#             # Cache the null result briefly
#             await redis.set(cache_key, None, 30)
#             return None
        
#         order = orders[0]
        
#         # ✅ Map products to items efficiently
#         if "product_details" in order:
#             product_map = {p["id"]: p for p in order["product_details"]}
            
#             for item in order.get("items", []):
#                 product_id = item.get('product')
#                 product = product_map.get(product_id)
                
#                 if product:
#                     item["product_name"] = product.get("name", "Unknown Product")
#                     item["product_image"] = product.get("images", [])
#                 else:
#                     item["product_name"] = "Product not found"
#                     item["product_image"] = []
            
#             # Remove product_details from response
#             del order["product_details"]
        
#         # Get delivery partner info if assigned
#         if order.get('delivery_partner'):
#             try:
#                 partner = await db.find_one(
#                     "users",
#                     {"id": order["delivery_partner"]},
#                     projection={"name": 1, "phone": 1, "rating": 1, "total_deliveries": 1}  # ✅ Only get needed fields
#                 )
#                 if partner:
#                     order["delivery_partner"] = {
#                         "name": partner.get("name"),
#                         "phone": partner.get("phone"),
#                         "rating": partner.get("rating", 4.5),
#                         "deliveries": partner.get("total_deliveries", 0)
#                     }
#             except Exception as partner_error:
#                 logger.warning(f"Error fetching delivery partner: {partner_error}")
        
#         # Add status message
#         if not order.get("status_message"):
#             status_messages = {
#                 "confirmed": "Your order has been confirmed and will be prepared soon.",
#                 "preparing": "We are preparing your order",
#                 "assigned": "Delivery Partner Assigned",
#                 "out_for_delivery": "Your order is on its way to you.",
#                 "arrived": "Delivery partner has arrived at your location!"
#             }
#             order["status_message"] = status_messages.get(
#                 order["order_status"], 
#                 "Your order is being processed."
#             )
        
#         # Serialize
#         serialized_order = fix_mongo_types(order)
        
#         # ✅ Cache for 30 seconds (active orders change frequently)
#         try:
#             await redis.set(cache_key, serialized_order, 30, use_l1=True)
#             logger.info(f"💾 Cached active order for {current_user.id}")
#         except Exception as cache_error:
#             logger.warning(f"Cache write error: {cache_error}")
        
#         logger.info(f"✅ Returning active order {serialized_order.get('id')} ({len(order.get('items', []))} items)")
        
#         return serialized_order
        
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"Error fetching active order: {e}")
#         import traceback
#         logger.error(traceback.format_exc())
#         raise HTTPException(
#             status_code=500, 
#             detail="Failed to fetch active order"
#         )

@router.post('/{order_id}/rate')
async def rate_order(
    order_id: str,
    rating_data: OrderRating,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Submit rating for a delivered order
    """
    try:
        # Find the order
        order = await db.find_one(
            "orders",
            {"id": order_id, "user": current_user.id}
        )

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        if order.get("order_status") != 'delivered':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only rate delivered orders"
            )

        # Check if already rated
        if order.get("rating"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order has already been rated"
            )
        current_time = get_ist_datetime_for_db()
        # Update order rating
        await db.update_one(
            "orders",
            {"id": order_id},
            {
                "$set": {
                    "rating": rating_data.rating,
                    "review": rating_data.review,
                    "rated_at": current_time['ist_string']
                }
            }
        )

        # Update delivery partner's average rating if applicable
        if order.get("delivery_partner"):
            await update_delivery_partner_rating(
                db=db,
                partner_id=order["delivery_partner"],
                new_rating=rating_data.rating
            )

        logger.info(f"Order {order_id} rated {rating_data.rating} stars by user {current_user.id}")

        return {
            "message": "Rating submitted successfully",
            "rating": rating_data.rating,
            "order_id": order_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting rating: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to submit rating"
        )


async def update_delivery_partner_rating(
    db: DatabaseManager,
    partner_id: str,
    new_rating: int
):
    """Helper function to update delivery partner's average rating"""
    try:
        # Get all completed orders for this partner
        orders = await db.find_many(
            "orders",
            {
                "delivery_partner": partner_id,
                "rating": {"$exists": True, "$ne": None}
            }
        )

        if orders:
            total_rating = sum(order.get("rating", 0) for order in orders)
            avg_rating = total_rating / len(orders)

            # Update partner's rating in users collection
            await db.update_one(
                "users",
                {"id": partner_id},
                {
                    "$set": {
                        "rating": round(avg_rating, 2),
                        "total_deliveries": len(orders)
                    }
                }
            )
    except Exception as e:
        logger.error(f"Error updating delivery partner rating: {str(e)}")

class AddTip(BaseModel):
    tip_amount: int = Field(..., ge=1, le=500)
    order_id: str

@router.post('/{order_id}/add-tip')
async def add_tip_to_order(
    order_id: str,
    tip_data: AddTip,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Add tip for delivery partner"""
    try:
        # Find the order
        order = await db.find_one(
            "orders",
            {"id": order_id, "user": current_user.id}
        )

        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )

        # Check if order is in valid state for tip
        if order.get("order_status") not in ['assigning', 'assigned', 'out_for_delivery']:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only add tip to active orders"
            )

        # Check if tip already added
        if order.get("tip_amount"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tip already added to this order"
            )

        current_time = get_ist_datetime_for_db()
        # Update order with tip
        await db.update_one(
            "orders",
            {"id": order_id},
            {
                "$set": {
                    "tip_amount": tip_data.tip_amount,
                    "tip_added_at": current_time['ist_string']
                }
            }
        )

        logger.info(f"Tip of ₹{tip_data.tip_amount} added to order {order_id}")

        return {
            "message": "Tip added successfully",
            "tip_amount": tip_data.tip_amount,
            "order_id": order_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding tip: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add tip"
        )

@router.get("/{order_id}")
async def get_order_by_id(
    order_id: str,
    current_user = Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get a specific order by ID
    User can only access their own orders
    """
    try:
        logger.info(f"📦 Fetching order {order_id} for user {current_user.email}")
        
        # Validate order_id format
        if not order_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order ID is required"
            )
        
        # Get user_id
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        # user_id_str = str(user_id) if isinstance(user_id, ObjectId) else user_id
        
        # Find order by ID and ensure it belongs to the user
        order = await db.find_one(
            "orders",
            {
                "id": order_id,
                "user": user_id
            }
        )
        
        if not order:
            logger.warning(f"❌ Order {order_id} not found for user {current_user.email}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        logger.info(f"✅ Order {order_id} found, status: {order.get('order_status')}")
        
        # Get user information
        user_info = await db.find_one("users", {"id": user_id})
        
        # Get delivery partner information if assigned
        delivery_partner_info = None
        if order.get("delivery_partner_id"):
            delivery_partner_info = await db.find_one(
                "users",
                {"id": order["delivery_partner_id"]}
            )
        
        # Serialize order data
        serialized_order = {
            "_id": str(order["_id"]),
            "id": order.get("id"),
            "order_status": order.get("order_status", "pending"),
            "items": order.get("items", []),
            "total_amount": order.get("total_amount", 0),
            "subtotal": order.get("subtotal", 0),
            "tax": order.get("tax", 0),
            "delivery_charge": order.get("delivery_charge", 0),
            "app_fee": order.get("app_fee", 0),
            "promo_discount": order.get("promo_discount", 0),
            "tip_amount": order.get("tip_amount", 0),
            "payment_method": order.get("payment_method"),
            "payment_status": order.get("payment_status"),
            "delivery_address": order.get("delivery_address"),
            "estimated_delivery_time": order.get("estimated_delivery_time", 30),
            "actual_delivery": order.get("actual_delivery"),
            "status_message": order.get("status_message"),
            "created_at": order["created_at"].isoformat() if order.get("created_at") else None,
            "updated_at": order.get("updated_at").isoformat() if order.get("updated_at") else None,
            "assigned_at": order.get("assigned_at").isoformat() if order.get("assigned_at") else None,
            "out_for_delivery_at": order.get("out_for_delivery_at").isoformat() if order.get("out_for_delivery_at") else None,
            "delivered_at": order.get("delivered_at").isoformat() if order.get("delivered_at") else None,
        }
        
        # Add delivery partner info if available
        if delivery_partner_info:
            serialized_order["delivery_partner"] = {
                "name": delivery_partner_info.get("name", "Delivery Partner"),
                "phone": delivery_partner_info.get("phone", ""),
                "rating": delivery_partner_info.get("rating"),
                "deliveries": delivery_partner_info.get("total_deliveries"),
            }
        
        # Add status change history if available
        if order.get("status_change_history"):
            serialized_order["status_change_history"] = [
                {
                    "status": item["status"],
                    "changed_at": item["changed_at"].isoformat() if hasattr(item.get("changed_at"), 'isoformat') else str(item.get("changed_at")),
                    "changed_by": item.get("changed_by", "system")
                }
                for item in order.get("status_change_history", [])
            ]
        
        logger.info(f"✅ Returning order {order_id} to user {current_user.email}")
        
        return serialized_order
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching order by ID: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch order"
        )