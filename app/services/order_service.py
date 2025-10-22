# app/services/order_service.py - COMPLETE REPLACEMENT
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
        Create order with optimized stock management
        Uses atomic operations and background processing
        """
        # ✅ Validation
        if not order_data.get('items'):
            raise ValueError("Order items are required")

        if not order_data.get('delivery_address'):
            raise ValueError("Delivery address is required")
        
        if not order_data.get('total_amount') or order_data['total_amount'] <= 0:
            raise ValueError("Valid total amount is required")
        
        order_data['user'] = current_user.id
        order_data['accepted_partners'] = []
        
        try:
            validated_order = OrderCreate(**order_data)
        except Exception as validation_error:
            raise ValueError(f"Invalid order data: {str(validation_error)}")
        
        # ✅ STEP 1: Validate products and stock (batch query)
        product_ids = [item.product for item in validated_order.items]
        products = await self.db.find_many(
            "products",
            {"id": {"$in": product_ids}, "is_active": True}
        )
        
        # Create product lookup map
        product_map = {p["id"]: p for p in products}
        
        # Validate all products exist and have stock
        for item in validated_order.items:
            product = product_map.get(item.product)
            
            if not product:
                raise ValueError(f"Product not found: {item.product}")
            
            if product.get("stock", 0) < item.quantity:
                raise ValueError(
                    f"Insufficient stock for {product['name']}. "
                    f"Available: {product.get('stock', 0)}, Requested: {item.quantity}"
                )
        
        # ✅ STEP 2: Atomic stock updates with optimistic locking
        stock_update_errors = []
        updated_products = []
        
        for item in validated_order.items:
            try:
                logger.info(f"📦 Updating stock: product={item.product}, quantity={item.quantity}")
                
                # Atomic update with stock check
                result = await self.db.update_one(
                    "products",
                    {
                        "id": item.product,
                        "stock": {"$gte": item.quantity},
                        "is_active": True
                    },
                    {
                        "$inc": {"stock": -item.quantity}
                    }
                )
                
                # Check if update succeeded
                update_successful = False
                
                if isinstance(result, bool):
                    update_successful = result
                elif hasattr(result, 'matched_count'):
                    update_successful = result.matched_count > 0
                
                if not update_successful:
                    product = product_map.get(item.product)
                    if product:
                        stock_update_errors.append({
                            "product_id": item.product,
                            "product_name": product.get("name", "Unknown"),
                            "requested": item.quantity,
                            "available": product.get("stock", 0)
                        })
                    else:
                        stock_update_errors.append({
                            "product_id": item.product,
                            "error": "Product not found or inactive"
                        })
                else:
                    updated_products.append(item.product)
                    logger.info(f"✅ Stock updated for {item.product}")
                    
            except Exception as stock_error:
                logger.error(f"❌ Stock update error for {item.product}: {stock_error}")
                stock_update_errors.append({
                    "product_id": item.product,
                    "error": str(stock_error)
                })
        
        # ✅ STEP 3: Rollback on failure
        if stock_update_errors:
            logger.error(f"❌ Stock update failed, rolling back {len(updated_products)} products")
            
            # Rollback successful updates
            for product_id in updated_products:
                for item in validated_order.items:
                    if item.product == product_id:
                        try:
                            await self.db.update_one(
                                "products",
                                {"id": product_id},
                                {"$inc": {"stock": item.quantity}}
                            )
                            logger.info(f"🔄 Rolled back stock for {product_id}")
                        except Exception as rollback_error:
                            logger.error(f"❌ Rollback error for {product_id}: {rollback_error}")
            
            # Format error message
            error_messages = []
            for error in stock_update_errors:
                if "available" in error:
                    error_messages.append(
                        f"{error['product_name']}: only {error['available']} available (requested {error['requested']})"
                    )
                else:
                    error_messages.append(
                        f"{error.get('product_id', 'Unknown')}: {error.get('error', 'Unknown error')}"
                    )
            
            raise ValueError(f"Stock unavailable: {'; '.join(error_messages)}")
        
        # ✅ STEP 4: Create order with IST timestamps
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
        
        order_dict["promo_code"] = order_data.get('promo_code')
        order_dict["promo_discount"] = order_data.get('promo_discount', 0)
        order_dict["estimated_delivery_time"] = 30
        
        logger.info(f"📅 Creating order at IST: {ist_time_data['ist_string']}")
        
        order_id = await self.db.insert_one("orders", order_dict)
        
        # ✅ STEP 5: Update coupon usage (non-blocking)
        if order_data.get('promo_code'):
            try:
                await self._update_coupon_usage(order_data['promo_code'])
            except Exception as coupon_error:
                logger.error(f"❌ Coupon update error: {coupon_error}")
        
        # ✅ STEP 6: Clear cart (non-blocking)
        try:
            await self._clear_user_cart(current_user.id)
        except Exception as cart_error:
            logger.error(f"❌ Cart clear error: {cart_error}")
        
        # ✅ STEP 7: Invalidate caches
        try:
            await self._invalidate_order_caches(current_user.id)
        except Exception as cache_error:
            logger.warning(f"⚠️ Cache invalidation error: {cache_error}")
        
        logger.info(f"✅ Order {id} created successfully")
        return order_id
    
    async def _update_coupon_usage(self, promo_code: str):
        """Update coupon usage count"""
        try:
            coupon = await self.db.find_one(
                "discount_coupons", 
                {"code": promo_code}
            )
            
            if coupon and coupon.get('usage_limit', 0) > 0:
                await self.db.update_one(
                    'discount_coupons',
                    {
                        "code": promo_code,
                        "usage_limit": {"$gt": 0}
                    },
                    {"$inc": {"usage_limit": -1}}
                )
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
            # Invalidate cart cache
            cart_key = CacheKeys.user_cart(user_id)
            await self.redis.delete(cart_key)
            
            # Invalidate order list cache
            await self.redis.delete_pattern(f"{CacheKeys.ORDER}:{user_id}:*")
            
            logger.info(f"✅ Invalidated caches for user {user_id}")
        except Exception as e:
            logger.error(f"❌ Cache invalidation failed: {e}")