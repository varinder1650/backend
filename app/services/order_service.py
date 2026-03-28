from datetime import datetime
from db.db_manager import DatabaseManager
from schema.order import OrderCreate
from app.utils.get_time import get_ist_datetime_for_db, now_utc
from app.cache.redis_manager import get_redis
from app.cache.cache_config import CacheKeys
import logging
from typing import List, Dict

logger = logging.getLogger(__name__)


class OrderService:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self.redis = get_redis()

    async def create_order(self, order_data: OrderCreate, current_user, id: str):
        """Create order with atomic stock validation and deduction."""
        order_dict = order_data.dict() if hasattr(order_data, 'dict') else order_data.model_dump()
        order_dict['user'] = current_user.id
        order_dict['id'] = id

        ist_time = get_ist_datetime_for_db()
        order_dict['created_at'] = ist_time['ist']
        order_dict['updated_at'] = ist_time['ist']
        order_dict['status_change_history'] = [{
            "status": "preparing",
            "changed_at": ist_time['ist'],
            "changed_at_ist": ist_time['ist_string'],
            "changed_by": current_user.name or "Customer",
            "message": "Order placed successfully"
        }]
        order_dict['estimated_delivery_time'] = 30
        order_dict['accepted_partners'] = []

        # --- Stock validation & deduction for product items ---
        product_items = [i for i in order_data.items if i.type == "product"]
        if product_items:
            await self._deduct_stock(product_items)

        # --- Process items into DB-friendly format ---
        processed_items = []
        for item in order_data.items:
            if item.type == "product":
                processed_items.append({
                    "type": "product",
                    "product": item.product,
                    "quantity": item.quantity,
                    "price": item.price,
                })
            elif item.type == "porter":
                service_data_dict = item.service_data.dict() if hasattr(item.service_data, 'dict') else item.service_data.model_dump()
                processed_items.append({"type": "porter", "service_data": service_data_dict})
            elif item.type == "printout":
                service_data_dict = item.service_data.dict() if hasattr(item.service_data, 'dict') else item.service_data.model_dump()
                processed_items.append({"type": "printout", "service_data": service_data_dict})
            else:
                raise ValueError(f"Unknown item type: {item.type}")

        order_dict["items"] = processed_items

        order_id = await self.db.insert_one("orders", order_dict)

        # Post-order cleanup (non-blocking)
        try:
            if order_data.promo_code:
                await self._update_coupon_usage(order_data.promo_code)
            await self._clear_user_cart(current_user.id)
            await self._invalidate_order_caches(current_user.id)
        except Exception as cleanup_error:
            logger.warning(f"Cleanup error (non-critical): {cleanup_error}")

        logger.info(f"Order {id} created successfully")
        return order_id

    async def _deduct_stock(self, product_items):
        """Atomically validate and deduct stock for all product items.

        Aggregates quantities per product, performs atomic $inc with $gte guard,
        and rolls back all successful deductions if any single product fails.
        """
        # Aggregate quantities by product id
        product_quantities: Dict[str, int] = {}
        for item in product_items:
            pid = item.product
            product_quantities[pid] = product_quantities.get(pid, 0) + item.quantity

        successful_deductions: List[Dict] = []

        for product_id, total_qty in product_quantities.items():
            result = await self.db.update_one(
                "products",
                {
                    "id": product_id,
                    "stock": {"$gte": total_qty},
                    "is_active": True,
                },
                {"$inc": {"stock": -total_qty}},
            )

            if result.matched_count == 0:
                # Insufficient stock — roll back everything we already deducted
                await self._rollback_stock(successful_deductions)
                # Get current stock for error message
                product = await self.db.find_one("products", {"id": product_id})
                available = product.get("stock", 0) if product else 0
                name = product.get("name", product_id) if product else product_id
                raise ValueError(
                    f"Insufficient stock for {name}: "
                    f"requested {total_qty}, available {available}"
                )

            successful_deductions.append({"product_id": product_id, "quantity": total_qty})
            logger.info(f"Stock deducted: {product_id} x{total_qty}")

    async def _rollback_stock(self, deductions: List[Dict]):
        """Roll back stock deductions on failure."""
        for d in deductions:
            try:
                await self.db.update_one(
                    "products",
                    {"id": d["product_id"]},
                    {"$inc": {"stock": d["quantity"]}},
                )
                logger.info(f"Rolled back {d['quantity']} units for {d['product_id']}")
            except Exception as e:
                logger.error(f"CRITICAL: Stock rollback failed for {d['product_id']}: {e}")

    async def _update_coupon_usage(self, promo_code: str):
        """Update coupon usage count atomically."""
        try:
            result = await self.db.update_one(
                'discount_coupons',
                {"code": promo_code, "usage_limit": {"$gt": 0}},
                {"$inc": {"usage_limit": -1}},
            )
            if result.matched_count > 0:
                logger.info(f"Updated coupon usage: {promo_code}")
        except Exception as e:
            logger.error(f"Coupon update failed: {e}")

    async def _clear_user_cart(self, user_id: str):
        """Clear user's cart after order."""
        try:
            cart = await self.db.find_one("carts", {"user": user_id})
            if cart:
                await self.db.update_one(
                    "carts",
                    {"_id": cart["_id"]},
                    {"$set": {"items": [], "updated_at": now_utc()}},
                )
                logger.info(f"Cleared cart for user {user_id}")
        except Exception as e:
            logger.error(f"Cart clear failed: {e}")

    async def _invalidate_order_caches(self, user_id: str):
        """Invalidate order and cart caches."""
        try:
            cart_key = CacheKeys.user_cart(user_id)
            await self.redis.delete(cart_key)
            await self.redis.delete_pattern(f"{CacheKeys.ORDER}:{user_id}:*")
            await self.redis.delete(f"active_order:{user_id}")
            logger.info(f"Invalidated caches for user {user_id}")
        except Exception as e:
            logger.error(f"Cache invalidation failed: {e}")
