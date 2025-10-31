from db.db_manager import DatabaseManager
from schema.order import DeliveryAddress, OrderCreate
from app.utils.get_time import get_ist_datetime_for_db, now_utc, now_ist
from app.cache.redis_manager import get_redis
from app.cache.cache_config import CacheKeys
import logging
from typing import List, Dict
from bson import ObjectId

logger = logging.getLogger(__name__)

class OrderService:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.redis = get_redis()
    
    async def create_order(self, order_data: dict, current_user, id: str):
        """
        Create order with atomic stock management
        """
        # ✅ Validation
        if not order_data.get('items'):
            raise ValueError("Order items are required")

        if not order_data.get('delivery_address'):
            raise ValueError("Delivery address is required")
        
        if not order_data.get('total_amount') or order_data['total_amount'] <= 0:
            raise ValueError("Valid total amount is required")
        
        # ✅ Validate tip amount if provided
        tip_amount = order_data.get('tip_amount', 0)
        if tip_amount < 0:
            raise ValueError("Tip amount cannot be negative")
        if tip_amount > 500:
            raise ValueError("Tip amount cannot exceed ₹500")
        
        order_data['user'] = current_user.id
        order_data['accepted_partners'] = []
        
        try:
            validated_order = OrderCreate(**order_data)
        except Exception as validation_error:
            raise ValueError(f"Invalid order data: {str(validation_error)}")
        
        # ✅ STEP 0: Aggregate quantities by product (CRITICAL FIX!)
        product_quantities = {}
        for item in validated_order.items:
            if item.product in product_quantities:
                product_quantities[item.product] += item.quantity
                logger.info(f"🔄 Duplicate product detected: {item.product}, adding {item.quantity} to existing {product_quantities[item.product] - item.quantity}")
            else:
                product_quantities[item.product] = item.quantity
        
        logger.info(f"📊 Aggregated order quantities: {product_quantities}")
        
        # ✅ STEP 1: Validate products exist and are active
        product_ids = list(product_quantities.keys())
        products = await self.db.find_many(
            "products",
            {"id": {"$in": product_ids}, "is_active": True}
        )
        
        # Create product lookup map
        product_map = {p["id"]: p for p in products}
        
        # Validate all products exist
        for product_id in product_ids:
            if product_id not in product_map:
                raise ValueError(f"Product not found or inactive: {product_id}")
        
        # ✅ STEP 2: ATOMIC stock updates (one per unique product)
        stock_update_errors = []
        updated_products = []
        
        for product_id, total_quantity in product_quantities.items():
            product = product_map[product_id]
            
            logger.info(f"📦 Attempting atomic stock update for: {product['name']}")
            logger.info(f"   Product ID: {product_id}")
            logger.info(f"   Total requested quantity: {total_quantity}")
            logger.info(f"   Current stock: {product.get('stock', 0)}")
            
            try:
                # ✅ ATOMIC UPDATE: Check and decrement in ONE operation
                result = await self.db.update_one(
                    "products",
                    {
                        "id": product_id,
                        "stock": {"$gte": total_quantity},  # Condition: stock must be >= total quantity
                        "is_active": True
                    },
                    {
                        "$inc": {"stock": -total_quantity}  # Decrement by total quantity
                    }
                )
                
                # ✅ Check if the atomic condition was met
                if result.matched_count == 0:
                    # Condition failed - insufficient stock
                    fresh_product = await self.db.find_one("products", {"id": product_id})
                    current_stock = fresh_product.get("stock", 0) if fresh_product else 0
                    
                    logger.warning(f"❌ Insufficient stock for {product['name']}")
                    logger.warning(f"   Available: {current_stock}")
                    logger.warning(f"   Requested: {total_quantity}")
                    
                    stock_update_errors.append({
                        "product_id": product_id,
                        "product_name": product["name"],
                        "requested": total_quantity,
                        "available": current_stock
                    })
                elif result.modified_count == 0:
                    # Matched but not modified
                    logger.error(f"⚠️ Matched but not modified for {product['name']}")
                    stock_update_errors.append({
                        "product_id": product_id,
                        "product_name": product["name"],
                        "error": "Update matched but stock not modified"
                    })
                else:
                    # Success!
                    updated_products.append({
                        "product_id": product_id,
                        "quantity": total_quantity
                    })
                    
                    # Verify the update
                    verify_product = await self.db.find_one("products", {"id": product_id})
                    new_stock = verify_product.get("stock", 0) if verify_product else 0
                    
                    logger.info(f"✅ Stock updated successfully for {product['name']}")
                    logger.info(f"   Matched: {result.matched_count}, Modified: {result.modified_count}")
                    logger.info(f"   Stock: {product.get('stock', 0)} → {new_stock}")
                    
                    # ✅ CRITICAL: Verify stock didn't go negative
                    if new_stock < 0:
                        logger.error(f"🚨🚨🚨 CRITICAL: Stock went NEGATIVE for {product['name']}!")
                        logger.error(f"   Product ID: {product_id}")
                        logger.error(f"   Previous stock: {product.get('stock', 0)}")
                        logger.error(f"   Requested: {total_quantity}")
                        logger.error(f"   New stock: {new_stock}")
                        
                        # Emergency rollback
                        await self.db.update_one(
                            "products",
                            {"id": product_id},
                            {"$inc": {"stock": total_quantity}}
                        )
                        
                        raise ValueError(f"CRITICAL ERROR: Stock validation failed for {product['name']}")
                        
            except ValueError:
                raise  # Re-raise validation errors
            except Exception as stock_error:
                logger.error(f"❌ Exception during stock update for {product_id}: {stock_error}")
                import traceback
                logger.error(traceback.format_exc())
                
                stock_update_errors.append({
                    "product_id": product_id,
                    "product_name": product["name"],
                    "error": str(stock_error)
                })
        
        # ✅ STEP 3: Rollback if ANY update failed
        if stock_update_errors:
            logger.error(f"❌ Stock validation failed, rolling back {len(updated_products)} successful updates")
            
            # Rollback all successful updates
            for update_info in updated_products:
                try:
                    rollback_result = await self.db.update_one(
                        "products",
                        {"id": update_info["product_id"]},
                        {"$inc": {"stock": update_info["quantity"]}}  # Add back the quantity
                    )
                    
                    # Verify rollback
                    verify_product = await self.db.find_one("products", {"id": update_info["product_id"]})
                    logger.info(f"🔄 Rolled back {update_info['quantity']} units for product {update_info['product_id']}")
                    logger.info(f"   Rollback - Matched: {rollback_result.matched_count}, Modified: {rollback_result.modified_count}")
                    logger.info(f"   Stock after rollback: {verify_product.get('stock', 'N/A') if verify_product else 'N/A'}")
                except Exception as rollback_error:
                    logger.error(f"❌ CRITICAL: Rollback failed for {update_info['product_id']}: {rollback_error}")
            
            # Format error messages
            error_messages = []
            for error in stock_update_errors:
                if "available" in error:
                    error_messages.append(
                        f"{error['product_name']}: only {error['available']} in stock (you requested {error['requested']})"
                    )
                else:
                    error_messages.append(
                        f"{error['product_name']}: {error.get('error', 'Stock check failed')}"
                    )
            
            raise ValueError(f"Unable to complete order. {' | '.join(error_messages)}")
        
        # ✅ STEP 4: Create order
        order_dict = validated_order.dict()
        order_dict["user"] = current_user.id
        
        ist_time_data = get_ist_datetime_for_db()
        
        order_dict["status_change_history"] = [{
            "status": "preparing",
            "changed_at": ist_time_data['ist'],
            "changed_at_ist": ist_time_data['ist_string'],
            "changed_by": current_user.name or "Customer",
            "message": "Order placed successfully"
        }]
        
        order_dict['id'] = id
        order_dict["created_at"] = ist_time_data['ist']
        order_dict["created_at_ist"] = ist_time_data['ist_string']
        order_dict["updated_at"] = ist_time_data['ist']
        order_dict["updated_at_ist"] = ist_time_data['ist_string']
        
        order_dict["tip_amount"] = tip_amount
        order_dict["promo_code"] = order_data.get('promo_code')
        order_dict["promo_discount"] = order_data.get('promo_discount', 0)
        order_dict["estimated_delivery_time"] = 30
        order_dict["payment_method"] = order_data.get('payment_method', 'cod')
        order_dict["payment_status"] = order_data.get('payment_status', 'pending')
        
        logger.info(f"📅 Creating order {id} at IST: {ist_time_data['ist_string']}")
        logger.info(f"   Total unique products: {len(product_quantities)}")
        logger.info(f"   Total items in order: {sum(product_quantities.values())}")
        if tip_amount > 0:
            logger.info(f"💰 Order includes tip: ₹{tip_amount}")
        
        order_id = await self.db.insert_one("orders", order_dict)
        
        # ✅ STEP 5: Cleanup (non-blocking)
        try:
            if order_data.get('promo_code'):
                await self._update_coupon_usage(order_data['promo_code'])
            
            await self._clear_user_cart(current_user.id)
            await self._invalidate_order_caches(current_user.id)
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Cleanup error (non-critical): {cleanup_error}")
        
        logger.info(f"✅✅✅ Order {id} created successfully!")
        return order_id
        
    
    async def _update_coupon_usage(self, promo_code: str):
        """Update coupon usage count atomically"""
        try:
            result = await self.db.update_one(
                'discount_coupons',
                {
                    "code": promo_code,
                    "usage_limit": {"$gt": 0}
                },
                {"$inc": {"usage_limit": -1}}
            )
            if result.matched_count > 0:
                logger.info(f"✅ Updated coupon usage: {promo_code}")
        except Exception as e:
            logger.error(f"❌ Coupon update failed: {e}")
    
    async def _clear_user_cart(self, user_id: str):
        """Clear user's cart after order"""
        try:
            cart = await self.db.find_one("carts", {"user": user_id})
            if cart:
                await self.db.update_one(
                    "carts",
                    {"_id": cart["_id"]},
                    {"$set": {"items": [], "updated_at": now_utc()}}
                )
                logger.info(f"✅ Cleared cart for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Cart clear failed: {e}")
    
    async def _invalidate_order_caches(self, user_id: str):
        """Invalidate order and cart caches"""
        try:
            cart_key = CacheKeys.user_cart(user_id)
            await self.redis.delete(cart_key)
            await self.redis.delete_pattern(f"{CacheKeys.ORDER}:{user_id}:*")
            await self.redis.delete(f"active_order:{user_id}")
            
            logger.info(f"✅ Invalidated caches for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Cache invalidation failed: {e}")