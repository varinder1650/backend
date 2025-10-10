from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
import logging
from app.cache.redis_manager import get_redis
from app.services.order_service import OrderService
from app.utils.auth import current_active_user, get_current_user
from db.db_manager import DatabaseManager, get_database
from schema.order import OrderResponse, OrderResponseEnhanced
from schema.user import UserinDB
from app.utils.mongo import fix_mongo_types
from app.utils.id_generator import get_id_generator

id_generator = get_id_generator()

logger = logging.getLogger(__name__)
router = APIRouter()

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
        order_id = await order_service.create_order(order_data, current_user,custom_id)

        logger.info(f"Order created successfully with ID: {order_id}")
        
        # Invalidate user's cart and order caches
        redis = get_redis()
        try:
            await redis.delete(f"cart:{current_user.id}")
            await redis.delete(f"recent_orders:{current_user.id}")
        except Exception as cache_error:
            logger.warning(f"Cache invalidation error: {cache_error}")
        
        # Add background tasks for order processing
        background_tasks.add_task(send_order_confirmation_email, order_id, current_user.email)
        background_tasks.add_task(update_inventory_after_order, order_data.get('items', []), db)
        
        created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
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
    """Get user's order history with caching and pagination"""
    try:
        redis = get_redis()
        cache_key = f"recent_orders:{current_user.id}:page{page}"
        
        if page == 1:
            cached_orders = await redis.get(cache_key)
            if cached_orders:
                logger.info(f"✅ Order cache HIT for user {current_user.id}")
                return cached_orders
        
        logger.info(f"❌ Order cache MISS for user {current_user.id}")
        
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
                    # ✅ Convert to dict with by_alias to ensure 'id' field
                    order_dict = validated_order.model_dump(by_alias=True)
                    enhanced_orders.append(order_dict)
                except Exception as validation_error:
                    logger.error(f"Validation error: {validation_error}")
                    # Fallback: use fixed_order as dict
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
        
        # Cache first page
        if page == 1:
            await redis.set(cache_key, result, 900)
            logger.info(f"💾 Cached orders: {cache_key}")
        
        logger.info(f"Returning {len(enhanced_orders)} orders for page {page}")
        return result
        
    except Exception as e:
        logger.error(f"Get my orders error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get orders"
        )

# Background task helpers
async def send_order_confirmation_email(order_id: str, email: str):
    """Send order confirmation email"""
    try:
        # Implement email sending logic
        logger.info(f"Order confirmation email sent for order {order_id} to {email}")
    except Exception as e:
        logger.error(f"Email sending failed: {e}")

async def update_inventory_after_order(items: list, db: DatabaseManager):
    """Update inventory after order completion"""
    try:
        for item in items:
            product_id = item.get('product_id') or item.get('product')
            quantity = item.get('quantity', 0)
            
            if product_id and quantity > 0:
                # Update database stock
                await db.update_one(
                    "products",
                    {"id": product_id},
                    {"$inc": {"stock": -quantity}}
                )
        
        logger.info(f"Inventory updated for {len(items)} items")
    except Exception as e:
        logger.error(f"Inventory update failed: {e}")

@router.get("/active")
async def get_active_order(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get user's most recent active order (single order)
    Returns only the most recent order that's actively being processed
    """
    try:
        logger.info(f"Fetching active order for user: {current_user.email}")
        # print(current_user)
        orders = await db.find_many(
            "orders",
            {
                "user": current_user.id,
                "order_status": {
                    "$in": ["confirmed", "assigning","preparing", "assigned", "out_for_delivery", "arrived"]
                }
            },
            sort=[("created_at", -1)],
            limit=1  # ✅ Only get the most recent one
        )
        # print(orders)
        if not orders or len(orders) == 0:
            logger.info(f"No active order found for user {current_user.email}")
            raise HTTPException(
                status_code=404, 
                detail="No active order found"
            )
        
        # Get the first (most recent) order
        order = orders[0]
        
        # Get delivery partner info if assigned
        if order.get('delivery_partner'):
            try:
                partner = await db.find_one(
                    "users",
                    {"id": order["delivery_partner"]}
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
        
        # Add status message based on current status
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
        
        for item in order.get('items'):
            product = await db.find_one('products', {"id": item['product']})

            item['product_name'] = product['name']
        
        # Serialize and return single order
        serialized_order = fix_mongo_types(order)
        logger.info(f"Returning active order {serialized_order.get('id')} with status: {order['order_status']}")
        
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
