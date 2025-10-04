from fastapi import BackgroundTasks
import asyncio
from typing import Dict, Any
import smtplib
from email.mime.text import MIMEText

class BackgroundTaskService:
    @staticmethod
    async def send_order_confirmation_email(order_data: Dict[str, Any]):
        """Send order confirmation email"""
        try:
            # Email sending logic
            await asyncio.sleep(0.1)  # Simulate email sending
            logger.info(f"Order confirmation sent for order {order_data.get('order_id')}")
        except Exception as e:
            logger.error(f"Email sending failed: {e}")
    
    @staticmethod
    async def update_inventory_after_order(order_items: List[Dict], db: DatabaseManager):
        """Update inventory in database after order completion"""
        try:
            inventory_service = get_inventory_service()
            
            for item in order_items:
                product_id = item['product_id']
                quantity = item['quantity']
                
                # Update database stock
                await db.update_one(
                    "products",
                    {"_id": ObjectId(product_id)},
                    {"$inc": {"stock": -quantity}}
                )
                
                # Update Redis cache
                stock_key = f"stock:{product_id}"
                await inventory_service.redis.increment(stock_key, -quantity)
            
            logger.info(f"Inventory updated for {len(order_items)} items")
            
        except Exception as e:
            logger.error(f"Inventory update failed: {e}")
    
    @staticmethod
    async def generate_order_invoice(order_id: str, order_data: Dict):
        """Generate and store order invoice"""
        try:
            # Invoice generation logic
            await asyncio.sleep(0.5)  # Simulate PDF generation
            logger.info(f"Invoice generated for order {order_id}")
        except Exception as e:
            logger.error(f"Invoice generation failed: {e}")

# Update your order creation to use background tasks
@router.post("/")
async def create_order(
    order_data: dict,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        # Your existing order creation logic...
        order_service = OrderService(db)
        order_id = await order_service.create_order(order_data, current_user)
        
        # Add background tasks for heavy operations
        background_tasks.add_task(
            BackgroundTaskService.send_order_confirmation_email,
            {"order_id": order_id, "user_email": current_user.email}
        )
        
        background_tasks.add_task(
            BackgroundTaskService.update_inventory_after_order,
            order_data.get('items', []),
            db
        )
        
        background_tasks.add_task(
            BackgroundTaskService.generate_order_invoice,
            order_id,
            order_data
        )
        
        # Invalidate relevant caches
        redis = get_redis()
        await redis.delete(f"cart:{current_user.id}")
        await redis.delete(f"recent_orders:{current_user.id}")
        
        logger.info(f"Order created successfully with ID: {order_id}")
        
        # Return immediate response
        created_order = await db.find_one("orders", {"_id": ObjectId(order_id)})
        created_order['_id'] = str(created_order["_id"])
        created_order["user"] = str(created_order['user'])
        
        return OrderResponse(**created_order)
        
    except Exception as e:
        logger.error(f"Create order error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create order"
        )