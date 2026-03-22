from datetime import datetime, timedelta
import json
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
import logging
from typing import Optional, List
from app.cache.redis_manager import get_redis
from app.services.order_service import OrderService
from app.services.email_service import email_service
from app.routes.notifications import create_notification
from app.utils.auth import current_active_user, get_current_user
from app.utils.orderItemGeneration import validatePorterItems, validateProductsItems, validatePrintItems
from app.utils.orderVerification import generate_order_signature, verify_order_signature
from app.utils.verifyPricing import calculateDeliveryFee, calculateDiscount
from db.db_manager import DatabaseManager, get_database
from schema.order import ConfirmOrderRequest, DeliveryAddress, DraftOrderRequest, DraftOrderResponse, OrderCreate, OrderResponse, OrderResponseEnhanced, OrderRating
from schema.user import UserinDB
from app.utils.mongo import fix_mongo_types
from app.utils.id_generator import get_id_generator
from pydantic import BaseModel, Field
from app.utils.get_time import get_ist_datetime_for_db, utc_to_ist, utc_isoformat

id_generator = get_id_generator()

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/draft", response_model=DraftOrderResponse)
async def create_draft_order(
    draft_data: DraftOrderRequest,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        logger.info(f"Draft order request from user: {current_user.email}")
        
        subtotal=0
        porterPrice=0
        validated_items = []
        
        for item in draft_data.items:
            if item['type'] == "product":
                validated_item, item_price = await validateProductsItems(item, db)
                validated_items.append(validated_item)
                subtotal += item_price
            
            elif item['type'] == "porter":
                validated_item, item_price = await validatePorterItems(item, db)
                validated_items.append(validated_item)
                porterPrice += item_price
            
            elif item['type'] == "printout":
                validated_item, item_price = await validatePrintItems(item, db)
                validated_items.append(validated_item)
                subtotal += item_price
        
        logger.info(f"Calculated subtotal: {subtotal}")

        has_porter_only = all(item['type'] == 'porter' for item in draft_data.items)
        deliveryFee = 0 if has_porter_only else await calculateDeliveryFee(db, subtotal)
        
        # Apply promo code if provided
        discount = 0
        if draft_data.promo_code:
            discount = await calculateDiscount(db, draft_data.promo_code, subtotal)

        appFee = 5
        # Calculate total
        total_amount = subtotal + porterPrice + deliveryFee + appFee + draft_data.tip_amount - discount
        total_amount = round(total_amount, 2)
        
        # Generate draft order ID
        draft_order_id = f"DRAFT_{current_user.id}_{int(datetime.now().timestamp())}"
        
        # Create signature
        signature = generate_order_signature(draft_order_id, total_amount, current_user.id)
        
        # Store draft order (expires in 10 minutes)
        expires_at = datetime.now() + timedelta(minutes=10)
        
        delivery_address_dict = None
        if draft_data.delivery_address:
            if hasattr(draft_data.delivery_address, 'dict'):
                # It's a Pydantic model
                delivery_address_dict = draft_data.delivery_address.dict()
            elif hasattr(draft_data.delivery_address, 'model_dump'):
                # Pydantic v2
                delivery_address_dict = draft_data.delivery_address.model_dump()
            elif isinstance(draft_data.delivery_address, dict):
                # Already a dict
                delivery_address_dict = draft_data.delivery_address
            else:
                # Try to convert to dict
                delivery_address_dict = dict(draft_data.delivery_address)

        draft_order = {
            "draft_order_id": draft_order_id,
            "user_id": current_user.id,
            "items": validated_items,
            "delivery_address": delivery_address_dict,
            "subtotal": subtotal,
            "delivery_fee": deliveryFee,
            "app_fee": appFee,
            "tip_amount": draft_data.tip_amount,
            "promo_code": draft_data.promo_code,
            "discount": discount,
            "total_amount": total_amount,
            "signature": signature,
            "created_at": datetime.now(),
            "expires_at": expires_at,
        }

        try:
            redis = get_redis()
            await redis.setex(
                f"draft_order:{draft_order_id}",
                600,  # 10 minutes TTL
                json.dumps(draft_order, default=str)
            )
        except:
            # Fallback: store in DB
            await db.insert_one("draft_orders", draft_order)
        
        logger.info(f"Draft order created: {draft_order}, total: {total_amount}")
        
        return DraftOrderResponse(
            draft_order_id=draft_order_id,
            signature=signature,
            total_amount=total_amount,
            subtotal=subtotal,
            delivery_fee=deliveryFee,
            app_fee=appFee,
            tip_amount=draft_data.tip_amount,
            discount=discount,
            expires_at=utc_isoformat(expires_at)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Draft order error: {e}")
        raise HTTPException(500, "Failed to create draft order")

@router.post("/confirm")
async def confirm_order(
    confirm_data: ConfirmOrderRequest,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        # Retrieve draft order
        draft_order_id = confirm_data.draft_order_id
        
        try:
            redis = get_redis()
            draft_json = await redis.get(f"draft_order:{draft_order_id}")
            if draft_json:
                draft_order = json.loads(draft_json)
            else:
                draft_order = await db.find_one("draft_orders", {"draft_order_id": draft_order_id})
        except:
            draft_order = await db.find_one("draft_orders", {"draft_order_id": draft_order_id})
        
        print("fetched order: ",draft_order)
        
        if not draft_order:
            raise HTTPException(404, "Draft order not found or expired")
        
        # Verify signature
        expected_signature = generate_order_signature(
            draft_order_id,
            draft_order["total_amount"],
            current_user.id
        )
        
        if confirm_data.signature != expected_signature:
            raise HTTPException(400, "Invalid order signature")
        
        # Verify user
        if draft_order["user_id"] != current_user.id:
            raise HTTPException(403, "Unauthorized")
        
        # Generate permanent order ID
        order_id = await id_generator.generate_order_id(current_user.id)
        
        transformed_items = []
        
        for item in draft_order["items"]:
            if item["type"] == "product":
                # Get full product details
                product = await db.find_one("products", {"id": item["product_id"]})
                if not product:
                    raise HTTPException(400, f"Product {item['product_id']} not found")
                
                transformed_items.append({
                    "type": "product",
                    "product": product["id"],
                    "quantity": item["quantity"],
                    "price": item["price"]
                })
            
            elif item["type"] == "printout":
                file_urls = []
                if item["service_data"].get("document_urls"):
                    file_urls = item["service_data"].get("document_urls")
                else:
                    file_urls = item["service_data"].get("photo_urls")
                transformed_items.append({
                    "type": "printout",
                    "service_data": {
                        **item["service_data"],
                        
                        "file_urls": file_urls,
                        "price": item["price"]
                    }
                })
            
            elif item["type"] == "porter":
                service_data = item["service_data"]
                
                weight_map = {
                    "0.5-1": 1,
                    "1-5": 2,
                    "5-10": 3,
                    "10-20": 4,
                    "20+": 5
                }
                weight_category_int = weight_map.get(service_data.get("weight_category", "1-5"), 2)
                
                transformed_items.append({
                    "type": "porter",
                    "service_data": {
                        "pickup_address": service_data.get("pickup_address"),
                        "delivery_address": service_data.get("delivery_address"),
                        "dimensions": service_data.get("dimensions"),
                        "weight_category": weight_category_int,
                        "phone": service_data.get("phone", ""),
                        "estimated_distance": service_data.get("estimated_distance", 0),
                        "estimated_cost": item["price"],
                        "notes": service_data.get("notes", ""),
                        "is_urgent": service_data.get("is_urgent",False)
                    }
                })
        
        order_create = OrderCreate(
            items=transformed_items,
            delivery_address=draft_order['delivery_address'],
            payment_method=confirm_data.payment_method,
            delivery=draft_order["delivery_fee"],
            app_fee=draft_order["app_fee"],
            tip_amount=draft_order["tip_amount"],
            total_amount=draft_order["total_amount"],
            promo_code=draft_order.get("promo_code"),
            promo_discount=draft_order.get("discount", 0),
            payment_status="pending" if confirm_data.payment_method == "online" else "pending"
        )
        
        # Create order in DB
        order_manager = OrderService(db)
        order_id = await order_manager.create_order(order_create, current_user, order_id)
        
        # Delete draft order
        try:
            redis = get_redis()
            await redis.delete(f"draft_order:{draft_order_id}")
        except:
            pass
        
        await db.delete_one("draft_orders", {"draft_order_id": draft_order_id})
        
        logger.info(f"Order {order_id} confirmed from draft {draft_order_id}")
        
        created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
         
        try:
            notification_title = "Order Placed Successfully! ✅"
            notification_message = f"Your order #{created_order.get('id', order_id)} has been placed and will be Delivered shortly."
            
            await create_notification(
                db=db,
                user_id=current_user.id,
                title=notification_title,
                message=notification_message,
                notification_type="order",
                order_id=str(created_order['id'])
            )
            logger.info(f"✅ Notification sent for order {order_id}")
        except Exception as notif_error:
            logger.error(f"Failed to create notification: {notif_error}")
        
        try:
            redis = get_redis()
            await redis.delete(f"cart:{current_user.id}")
            await redis.delete(f"recent_orders:{current_user.id}")
        except Exception as cache_error:
            logger.warning(f"Cache invalidation error: {cache_error}")
        
        # Add background tasks for order processing
        try:
            background_tasks.add_task(
                send_order_confirmation_email, 
                created_order, 
                current_user.email,
                current_user.name
            )
        except:
            logger.warning("email generation failed!!")
        return {
            "success": True,
            "order_id": order_id,
            "message": "Order placed successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Order confirmation error: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to confirm order: {str(e)}")

@router.post("/")
async def create_order(
    order_data: OrderCreate,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        logger.info(f"Order creation request from user: {current_user.email}")

        order_service = OrderService(db)
        custom_id = await id_generator.generate_order_id(current_user.id)
        order_id = await order_service.create_order(order_data, current_user, custom_id)

        logger.info(f"Order created successfully with ID: {order_id}")
        
        # Get the created order details
        created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
        
        #Create notification
        try:
            from app.routes.notifications import create_notification
            
            order_type = order_data.order_type
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
                order_id=str(created_order['id'])
            )
            logger.info(f"✅ Notification sent for order {order_id}")
        except Exception as notif_error:
            logger.error(f"Failed to create notification: {notif_error}")
        
        try:
            redis = get_redis()
            await redis.delete(f"cart:{current_user.id}")
            await redis.delete(f"recent_orders:{current_user.id}")
        except Exception as cache_error:
            logger.warning(f"Cache invalidation error: {cache_error}")
        
        # Add background tasks for order processing
        try:
            background_tasks.add_task(
                send_order_confirmation_email, 
                created_order, 
                current_user.email,
                current_user.name
            )
        except:
            logger.warning("email generation failed!!")
        
        # Format response
        # created_order['id'] = str(created_order["id"])
        # created_order["user"] = str(created_order['user'])
        # for item in created_order.get("items", []):
        #     if isinstance(item.get("product"), ObjectId):
        #         item["product"] = str(item["product"])

        # return OrderResponse(**created_order)
        return True
        
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
    """
    Get user's order history - optimized minimal data for fast response.
    Returns order_id, created_at, delivered_at, total_amount, order_type, and order_status.
    """
    try:
        logger.info(f"Fetching orders for user {current_user.id}")

        skip = (page - 1) * limit
        total_orders = await db.count_documents("orders", {"user": current_user.id})
        total_pages = (total_orders + limit - 1) // limit if total_orders > 0 else 0

        # Fetch only the necessary fields
        orders = await db.find_many(
            "orders",
            {"user": current_user.id},
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit,
        )

        optimized_orders = []
        for order in orders:
            try:
                fixed_order = fix_mongo_types(order)

                optimized_orders.append({
                    "order_id": fixed_order.get("id"),
                    "created_at": fixed_order.get("created_at"),
                    "delivered_at": fixed_order.get("delivered_at"),  # may be None
                    "total_amount": fixed_order.get("total_amount", 0),
                    "order_type": fixed_order.get("order_type"),
                    "order_status": fixed_order.get("order_status"),
                })

            except Exception as e:
                logger.error(f"Error processing order {order.get('id')}: {e}")
                continue

        result = {
            "orders": optimized_orders,
            "pagination": {
                "currentPage": page,
                "totalPages": total_pages,
                "totalOrders": total_orders,
                "hasNextPage": page < total_pages,
                "hasPrevPage": page > 1
            }
        }

        logger.info(f"✅ Returning {len(optimized_orders)} orders for page {page}")
        return result

    except Exception as e:
        logger.error(f"Get my orders error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get orders"
        )


@router.get("/active")
async def get_active_orders(
    current_user = Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
) -> List[dict]:
    """Get all user's active orders - NO CACHING for real-time status"""
    try:
        if not current_user:
            logger.info("No authenticated user found")
            return []
            
        logger.info(f"Fetching active orders for user: {current_user.email}")

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
        
        if not orders:
            logger.info(f"No active orders found for user {current_user.email}")
            return []
            
        active_orders = []

        for order in orders:
            # ✅ Map products to items efficiently
            if "product_details" in order:
                product_map = {p["id"]: p for p in order["product_details"]}
                
                for item in order.get("items", []):
                    # Only map product details if it's a product type item or has a product field
                    if item.get("type") == "product" or item.get("product"):
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
            active_orders.append(serialized_order)
        
        logger.info(f"✅ Returning {len(active_orders)} active orders")
        
        return active_orders
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching active orders: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500, 
            detail="Failed to fetch active orders"
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
                    'name': 'product',
                    'quantity': item.get('quantity', 1),
                    'price': item.get('price', 0)
                }
                for item in order.get('items', [])
            ],
            'total_amount': order.get('total_amount', 0),
            'estimated_delivery': order.get('estimated_delivery_time', '30 minutes'),
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
                product = await db.find_one("products", {"id": product_id})
                if product:
                    logger.info(f"   - {product.get('name')}: -{quantity} (current: {product.get('stock', 0)})")
        
    except Exception as e:
        logger.error(f"Inventory logging failed: {e}")

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
        if order.get("delivery_partner"):
            delivery_partner_info = await db.find_one(
                "users",
                {"id": order["delivery_partner"]}
            )
            
        # Fetch product names and images for the order items
        product_ids = [item.get("product") for item in order.get("items", []) if item.get("type") == "product" or item.get("product")]
        if product_ids:
            products = await db.find_many("products", {"id": {"$in": product_ids}})
            product_map = {p["id"]: p for p in products}
            
            for item in order.get("items", []):
                if item.get("type") == "product" or item.get("product"):
                    product_id = item.get('product')
                    product = product_map.get(product_id)
                    if product:
                        item["product_name"] = product.get("name", "Unknown Product")
                        item["product_image"] = product.get("images", [])
                    else:
                        item["product_name"] = "Product not found"
                        item["product_image"] = []
        
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
            "created_at": utc_isoformat(order.get("created_at")),
            "updated_at": utc_isoformat(order.get("updated_at")),
            "assigned_at": utc_isoformat(order.get("assigned_at")),
            "out_for_delivery_at": utc_isoformat(order.get("out_for_delivery_at")),
            "delivered_at": utc_isoformat(order.get("delivered_at")),
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
                    "changed_at": utc_isoformat(item.get("changed_at")) if hasattr(item.get("changed_at"), 'isoformat') else str(item.get("changed_at")),
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
