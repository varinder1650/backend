# app/services/websocket_service.py
"""
WebSocket service for real-time order tracking and notifications
"""

from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict, List, Set, Optional
import json
import asyncio
import logging
from datetime import datetime
from app.cache.redis_manager import get_redis
from app.utils.auth import decode_token
from db.db_manager import get_database

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Store active connections by user_id
        self.active_connections: Dict[str, List[WebSocket]] = {}
        # Store connection metadata
        self.connection_metadata: Dict[WebSocket, Dict] = {}
        # Track connections by role
        self.role_connections: Dict[str, Set[WebSocket]] = {
            "customer": set(),
            "delivery_partner": set(),
            "restaurant": set(),
            "admin": set()
        }
    
    async def connect(self, websocket: WebSocket, user_id: str, user_role: str, metadata: Dict = None):
        """Accept and register new WebSocket connection"""
        await websocket.accept()
        
        # Add to user connections
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        
        self.active_connections[user_id].append(websocket)
        
        # Store metadata
        self.connection_metadata[websocket] = {
            "user_id": user_id,
            "user_role": user_role,
            "connected_at": datetime.utcnow(),
            "last_ping": datetime.utcnow(),
            **(metadata or {})
        }
        
        # Add to role-based tracking
        if user_role in self.role_connections:
            self.role_connections[user_role].add(websocket)
        
        logger.info(f"WebSocket connected: user={user_id}, role={user_role}")
        
        # Send welcome message
        await self.send_personal_message({
            "type": "connection_established",
            "message": "Connected to SmartBag real-time service",
            "timestamp": datetime.utcnow().isoformat()
        }, websocket)
    
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection"""
        if websocket in self.connection_metadata:
            metadata = self.connection_metadata[websocket]
            user_id = metadata["user_id"]
            user_role = metadata["user_role"]
            
            # Remove from user connections
            if user_id in self.active_connections:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
            
            # Remove from role connections
            if user_role in self.role_connections:
                self.role_connections[user_role].discard(websocket)
            
            # Remove metadata
            del self.connection_metadata[websocket]
            
            logger.info(f"WebSocket disconnected: user={user_id}, role={user_role}")
    
    async def send_personal_message(self, message: Dict, websocket: WebSocket):
        """Send message to specific WebSocket"""
        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to WebSocket: {e}")
            self.disconnect(websocket)
    
    async def send_to_user(self, message: Dict, user_id: str):
        """Send message to all connections of a specific user"""
        if user_id in self.active_connections:
            disconnected_connections = []
            
            for websocket in self.active_connections[user_id]:
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Failed to send message to user {user_id}: {e}")
                    disconnected_connections.append(websocket)
            
            # Clean up disconnected connections
            for websocket in disconnected_connections:
                self.disconnect(websocket)
    
    async def send_to_role(self, message: Dict, role: str):
        """Send message to all users with specific role"""
        if role in self.role_connections:
            disconnected_connections = []
            
            for websocket in self.role_connections[role].copy():
                try:
                    await websocket.send_text(json.dumps(message))
                except Exception as e:
                    logger.error(f"Failed to send message to role {role}: {e}")
                    disconnected_connections.append(websocket)
            
            # Clean up disconnected connections
            for websocket in disconnected_connections:
                self.disconnect(websocket)
    
    async def broadcast(self, message: Dict):
        """Broadcast message to all connected clients"""
        all_connections = []
        for user_connections in self.active_connections.values():
            all_connections.extend(user_connections)
        
        disconnected_connections = []
        
        for websocket in all_connections:
            try:
                await websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Failed to broadcast message: {e}")
                disconnected_connections.append(websocket)
        
        # Clean up disconnected connections
        for websocket in disconnected_connections:
            self.disconnect(websocket)
    
    def get_user_connections_count(self, user_id: str) -> int:
        """Get number of active connections for user"""
        return len(self.active_connections.get(user_id, []))
    
    def get_role_connections_count(self, role: str) -> int:
        """Get number of active connections for role"""
        return len(self.role_connections.get(role, set()))
    
    def get_total_connections(self) -> int:
        """Get total number of active connections"""
        return sum(len(connections) for connections in self.active_connections.values())

# Global connection manager
connection_manager = ConnectionManager()

class RealtimeService:
    def __init__(self):
        self.redis = get_redis()
        self.manager = connection_manager
    
    async def authenticate_websocket(self, websocket: WebSocket, token: str) -> Optional[Dict]:
        """Authenticate WebSocket connection"""
        try:
            if not token:
                await websocket.close(code=4001, reason="Authentication required")
                return None
            
            db = get_database()
            # Use your existing token decode function
            user_data = await decode_token(token, db)
            
            if not user_data:
                await websocket.close(code=4001, reason="Invalid token")
                return None
            
            return {
                "user_id": user_data.id,
                "user_role": user_data.role,
                "email": user_data.email,
                "name": user_data.name
            }
        
        except Exception as e:
            logger.error(f"WebSocket authentication error: {e}")
            await websocket.close(code=4001, reason="Authentication failed")
            return None
    
    async def send_order_update(self, order_id: str, update_data: Dict):
        """Send order update to relevant users"""
        try:
            # Get order details from database
            db = get_database()
            order = await db.find_one("orders", {"_id": ObjectId(order_id)})
            
            if not order:
                logger.error(f"Order {order_id} not found for update")
                return
            
            customer_id = str(order["user"])
            delivery_partner_id = str(order.get("delivery_partner")) if order.get("delivery_partner") else None
            
            # Prepare update message
            message = {
                "type": "order_update",
                "order_id": order_id,
                "status": update_data.get("status", order.get("order_status")),
                "timestamp": datetime.utcnow().isoformat(),
                "message": update_data.get("message", "Your order has been updated"),
                "data": update_data
            }
            
            # Send to customer
            await self.manager.send_to_user(message, customer_id)
            
            # Send to delivery partner if assigned
            if delivery_partner_id:
                delivery_message = {
                    **message,
                    "type": "delivery_update",
                    "message": update_data.get("delivery_message", "Delivery status updated")
                }
                await self.manager.send_to_user(delivery_message, delivery_partner_id)
            
            # Cache update in Redis for offline users
            await self.cache_notification(customer_id, message)
            if delivery_partner_id:
                await self.cache_notification(delivery_partner_id, delivery_message)
            
            logger.info(f"Order update sent for order {order_id}")
            
        except Exception as e:
            logger.error(f"Error sending order update: {e}")
    
    async def send_delivery_location_update(self, delivery_partner_id: str, location_data: Dict):
        """Send delivery partner location to customers"""
        try:
            # Get active orders for this delivery partner
            db = get_database()
            active_orders = await db.find_many(
                "orders",
                {
                    "delivery_partner": ObjectId(delivery_partner_id),
                    "order_status": {"$in": ["out_for_delivery", "assigned"]}
                }
            )
            
            for order in active_orders:
                customer_id = str(order["user"])
                
                message = {
                    "type": "delivery_location_update",
                    "order_id": str(order["_id"]),
                    "location": {
                        "latitude": location_data["latitude"],
                        "longitude": location_data["longitude"],
                        "accuracy": location_data.get("accuracy"),
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    "estimated_arrival": location_data.get("estimated_arrival")
                }
                
                await self.manager.send_to_user(message, customer_id)
            
        except Exception as e:
            logger.error(f"Error sending location update: {e}")
    
    async def send_new_order_notification(self, order_id: str):
        """Notify available delivery partners of new order"""
        try:
            # Send to all online delivery partners
            message = {
                "type": "new_order_available",
                "order_id": order_id,
                "timestamp": datetime.utcnow().isoformat(),
                "message": "New delivery order available"
            }
            
            await self.manager.send_to_role(message, "delivery_partner")
            
        except Exception as e:
            logger.error(f"Error sending new order notification: {e}")
    
    async def cache_notification(self, user_id: str, notification: Dict):
        """Cache notification for offline users"""
        try:
            cache_key = f"notifications:{user_id}"
            
            # Get existing notifications
            existing = await self.redis.get(cache_key) or []
            if not isinstance(existing, list):
                existing = []
            
            # Add new notification
            existing.append({
                **notification,
                "cached_at": datetime.utcnow().isoformat()
            })
            
            # Keep only last 10 notifications
            existing = existing[-10:]
            
            # Cache for 24 hours
            await self.redis.set(cache_key, existing, 86400)
            
        except Exception as e:
            logger.error(f"Error caching notification: {e}")
    
    async def get_cached_notifications(self, user_id: str) -> List[Dict]:
        """Get cached notifications for user"""
        try:
            cache_key = f"notifications:{user_id}"
            notifications = await self.redis.get(cache_key)
            
            if notifications and isinstance(notifications, list):
                return notifications
            
            return []
            
        except Exception as e:
            logger.error(f"Error getting cached notifications: {e}")
            return []
    
    async def clear_cached_notifications(self, user_id: str):
        """Clear cached notifications for user"""
        try:
            cache_key = f"notifications:{user_id}"
            await self.redis.delete(cache_key)
        except Exception as e:
            logger.error(f"Error clearing notifications: {e}")

# Global realtime service
realtime_service = RealtimeService()

def get_realtime_service() -> RealtimeService:
    return realtime_service

# WebSocket endpoint for orders.py
"""
Add this to your orders.py or create a separate websocket.py file:

from app.services.websocket_service import connection_manager, get_realtime_service
from fastapi import WebSocket, Query, HTTPException

@router.websocket("/ws/orders")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="Authentication token")
):
    realtime_service = get_realtime_service()
    
    # Authenticate connection
    auth_data = await realtime_service.authenticate_websocket(websocket, token)
    
    if not auth_data:
        return  # Connection closed by authentication
    
    # Connect user
    await connection_manager.connect(
        websocket,
        auth_data["user_id"],
        auth_data["user_role"],
        {"email": auth_data["email"], "name": auth_data["name"]}
    )
    
    # Send cached notifications
    cached_notifications = await realtime_service.get_cached_notifications(auth_data["user_id"])
    if cached_notifications:
        for notification in cached_notifications:
            await connection_manager.send_personal_message(notification, websocket)
        
        # Clear cache after sending
        await realtime_service.clear_cached_notifications(auth_data["user_id"])
    
    try:
        # Keep connection alive with ping/pong
        while True:
            try:
                # Wait for client message or timeout after 30 seconds
                message = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                
                # Handle client messages
                try:
                    data = json.loads(message)
                    
                    if data.get("type") == "ping":
                        await connection_manager.send_personal_message(
                            {"type": "pong", "timestamp": datetime.utcnow().isoformat()},
                            websocket
                        )
                    
                    elif data.get("type") == "location_update" and auth_data["user_role"] == "delivery_partner":
                        # Handle location updates from delivery partners
                        await realtime_service.send_delivery_location_update(
                            auth_data["user_id"],
                            data.get("location", {})
                        )
                    
                except json.JSONDecodeError:
                    logger.error("Invalid JSON received from WebSocket")
            
            except asyncio.TimeoutError:
                # Send ping to check connection
                await connection_manager.send_personal_message(
                    {"type": "ping", "timestamp": datetime.utcnow().isoformat()},
                    websocket
                )
    
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        connection_manager.disconnect(websocket)
"""