from datetime import datetime
from app.cache.redis_manager import get_redis
from bson import ObjectId
import asyncio
from typing import Dict, List
import logging

from db.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

class InventoryService:
    def __init__(self):
        self.redis = get_redis()
    
    async def sync_inventory_to_cache(self, db: DatabaseManager):
        """Sync all product inventory from DB to Redis"""
        try:
            # Get all active products with stock info
            products = await db.find_many(
                "products", 
                {"is_active": True}
                # projection={"_id": 1, "stock": 1, "reserved_stock": 1}
            )
            
            # Batch update Redis
            pipeline = []
            for product in products:
                stock_key = f"stock:{product['id']}"
                reserved_key = f"reserved:{product['id']}"
                
                pipeline.append(
                    self.redis.set(stock_key, product.get('stock', 0), 3600)
                )
                pipeline.append(
                    self.redis.set(reserved_key, product.get('reserved_stock', 0), 3600)
                )
            
            # Execute all Redis operations
            await asyncio.gather(*pipeline)
            logger.info(f"Synced {len(products)} products to Redis inventory cache")
            
        except Exception as e:
            logger.error(f"Inventory sync error: {e}")
    
    async def get_available_stock(self, product_id: str) -> int:
        """Get real-time available stock"""
        try:
            stock_key = f"stock:{product_id}"
            reserved_key = f"reserved:{product_id}"
            
            stock_data = await self.redis.get_many([stock_key, reserved_key])
            
            total_stock = stock_data.get(stock_key, 0)
            reserved_stock = stock_data.get(reserved_key, 0)
            
            return max(0, total_stock - reserved_stock)
            
        except Exception as e:
            logger.error(f"Stock check error for {product_id}: {e}")
            # Fallback to database
            return await self._get_stock_from_db(product_id)
    
    async def reserve_stock(self, product_id: str, quantity: int, order_id: str) -> bool:
        """Reserve stock for order (atomic operation)"""
        try:
            available = await self.get_available_stock(product_id)
            
            if available < quantity:
                return False
            
            # Atomic reservation
            reserved_key = f"reserved:{product_id}"
            reservation_key = f"reservation:{order_id}:{product_id}"
            
            # Increment reserved stock
            await self.redis.increment(reserved_key, quantity)
            
            # Track reservation for this order
            await self.redis.set(
                reservation_key, 
                {"product_id": product_id, "quantity": quantity, "timestamp": datetime.utcnow().isoformat()}, 
                1800  # 30 minutes to complete order
            )
            
            logger.info(f"Reserved {quantity} units of {product_id} for order {order_id}")
            return True
            
        except Exception as e:
            logger.error(f"Stock reservation error: {e}")
            return False
    
    async def release_reservation(self, order_id: str):
        """Release stock reservations for cancelled order"""
        try:
            # Find all reservations for this order
            reservation_keys = await self.redis.keys(f"reservation:{order_id}:*")
            
            for key in reservation_keys:
                reservation = await self.redis.get(key)
                if reservation:
                    product_id = reservation['product_id']
                    quantity = reservation['quantity']
                    
                    # Decrease reserved stock
                    reserved_key = f"reserved:{product_id}"
                    await self.redis.increment(reserved_key, -quantity)
                    
                    # Remove reservation
                    await self.redis.delete(key)
            
            logger.info(f"Released reservations for order {order_id}")
            
        except Exception as e:
            logger.error(f"Reservation release error: {e}")

# Add to your dependency injection
inventory_service = InventoryService()

def get_inventory_service() -> InventoryService:
    return inventory_service