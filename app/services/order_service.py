from db.db_manager import DatabaseManager
from schema.order import DeliveryAddress, OrderCreate
from app.utils.get_time import get_ist_datetime_for_db, now_utc, now_ist
import logging

logger = logging.getLogger(__name__)

class OrderService:
    def __init__(self, db: DatabaseManager):
        self.db = db
    
    async def create_order(self, order_data: dict, current_user, id: str):
        if not order_data.get('items'):
            raise ValueError("Order items are required")

        if not order_data.get('delivery_address'):
            raise ValueError("Address not found")
        
        if not order_data.get('total_amount') or order_data['total_amount'] <= 0:
            raise ValueError("Valid total amount is required")
        
        order_data['user'] = current_user.id
        order_data['accepted_partners'] = []
        
        try:
            validated_order = OrderCreate(**order_data)
        except Exception as validation_error:
            raise ValueError(f"Invalid order data: {str(validation_error)}")
        
        # ✅ STEP 1: Validate products and stock availability
        for item in validated_order.items:
            product = await self.db.find_one("products", {"id": item.product, "is_active": True})
            
            if not product:
                raise ValueError(f"Product not found: {item.product}")
            
            if product.get("stock", 0) < item.quantity:
                raise ValueError(f"Insufficient stock for product: {product['name']}. Available: {product.get('stock', 0)}, Requested: {item.quantity}")
        
        # ✅ STEP 2: Atomically decrement stock (prevents negative stock)
        stock_update_errors = []
        updated_products = []
        
        for item in validated_order.items:
            try:
                logger.info(f"🔄 Attempting to update stock for product {item.product}, quantity: {item.quantity}")
                
                # Use atomic update with condition to prevent negative stock
                result = await self.db.update_one(
                    "products",
                    {
                        "id": item.product,
                        "stock": {"$gte": item.quantity},  # ✅ Only update if stock >= quantity
                        "is_active": True
                    },
                    {
                        "$inc": {"stock": -item.quantity}
                    }
                )
                
                logger.info(f"📊 Update result for {item.product}: {result}")
                
                # ✅ Handle both Motor (UpdateResult) and PyMongo (bool) responses
                update_successful = False
                
                if isinstance(result, bool):
                    # PyMongo returns bool - True means success
                    update_successful = result
                    logger.info(f"✅ PyMongo result (bool): {result}")
                elif hasattr(result, 'matched_count'):
                    # Motor returns UpdateResult object
                    update_successful = result.matched_count > 0
                    logger.info(f"✅ Motor result - matched: {result.matched_count}, modified: {result.modified_count}")
                else:
                    logger.error(f"❌ Unexpected result type: {type(result)}")
                    update_successful = False
                
                if not update_successful:
                    # Stock insufficient or product not found
                    product = await self.db.find_one("products", {"id": item.product})
                    if product:
                        stock_update_errors.append({
                            "product_id": item.product,
                            "product_name": product.get("name", "Unknown"),
                            "requested": item.quantity,
                            "available": product.get("stock", 0)
                        })
                        logger.warning(f"⚠️ Stock insufficient for {product.get('name')}: Available={product.get('stock', 0)}, Requested={item.quantity}")
                    else:
                        stock_update_errors.append({
                            "product_id": item.product,
                            "error": "Product not found or inactive"
                        })
                        logger.error(f"❌ Product not found: {item.product}")
                else:
                    updated_products.append(item.product)
                    logger.info(f"✅ Successfully updated stock for {item.product}")
                    
            except Exception as stock_error:
                logger.error(f"❌ Stock update error for product {item.product}: {str(stock_error)}")
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                stock_update_errors.append({
                    "product_id": item.product,
                    "error": str(stock_error)
                })
        
        # ✅ STEP 3: If any stock update failed, rollback and raise error
        if stock_update_errors:
            logger.error(f"❌ Stock update failed for {len(stock_update_errors)} products, rolling back...")
            
            # Rollback stock for successfully updated products
            for product_id in updated_products:
                for item in validated_order.items:
                    if item.product == product_id:
                        try:
                            await self.db.update_one(
                                "products",
                                {"id": product_id},
                                {"$inc": {"stock": item.quantity}}  # Add back the stock
                            )
                            logger.info(f"🔄 Rolled back stock for {product_id}")
                        except Exception as rollback_error:
                            logger.error(f"❌ Rollback error for {product_id}: {rollback_error}")
            
            # Format error message
            error_messages = []
            for error in stock_update_errors:
                if "available" in error:
                    error_messages.append(
                        f"{error['product_name']}: Only {error['available']} available, you requested {error['requested']}"
                    )
                else:
                    error_messages.append(f"{error.get('product_id', 'Unknown')}: {error.get('error', 'Unknown error')}")
            
            raise ValueError(f"Stock unavailable: {'; '.join(error_messages)}")
        
        # ✅ STEP 4: Create order with IST timestamps
        order_dict = validated_order.dict()
        order_dict["user"] = current_user.id
        
        # ✅ Get IST time for status change history
        ist_time_data = get_ist_datetime_for_db()
        
        order_dict["status_change_history"] = [{
            "status": "preparing",
            "changed_at": ist_time_data['ist'],  # Store UTC in DB
            "changed_at_ist": ist_time_data['ist_string'],  # Store IST string for display
            "changed_by": current_user.name or "Customer"
        }]
        
        order_dict['id'] = id
        
        # ✅ Set created_at and updated_at with IST
        order_dict["created_at"] = ist_time_data['ist']
        order_dict["created_at_ist"] = ist_time_data['ist_string']
        order_dict["updated_at"] = ist_time_data['ist']
        order_dict["updated_at_ist"] = ist_time_data['ist_string']
        
        order_dict["promo_code"] = order_data.get('promo_code')
        order_dict["promo_discount"] = order_data.get('promo_discount', 0)
        order_dict["estimated_delivery_time"] = 30
        
        logger.info(f"📅 Creating order at IST: {ist_time_data['ist_string']}")
        # logger.info(f"📅 Storing in DB as UTC: {ist_time_data['utc']}")
        
        order_id = await self.db.insert_one("orders", order_dict)
        
        # Update coupon usage
        if order_data.get('promo_code'):
            try:
                update_coupon = await self.db.find_one(
                    "discount_coupons", 
                    {"code": order_data['promo_code']}
                )
                
                if update_coupon and update_coupon.get('usage_limit', 0) > 0:
                    await self.db.update_one(
                        'discount_coupons',
                        {
                            "code": order_data['promo_code'],
                            "usage_limit": {"$gt": 0}  # ✅ Only decrement if > 0
                        },
                        {
                            "$inc": {"usage_limit": -1}
                        }
                    )
                    logger.info(f"✅ Updated coupon usage for {order_data['promo_code']}")
            except Exception as coupon_error:
                logger.error(f"❌ Coupon update error: {coupon_error}")
        
        # Clear user's cart
        try:
            cart = await self.db.find_one("carts", {"user": current_user.id})
            if cart:
                await self.db.update_one(
                    "carts",
                    {"_id": cart["_id"]},
                    {"$set": {"items": [], "updated_at": now_utc()}}
                )
                logger.info(f"✅ Cleared cart for user {current_user.id}")
        except Exception as cart_error:
            logger.error(f"❌ Cart clear error: {cart_error}")
        
        logger.info(f"✅ Order {id} created successfully for user {current_user.id}")
        return order_id