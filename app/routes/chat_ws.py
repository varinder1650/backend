# app/routes/chat_ws.py
"""
WebSocket endpoint for real-time support chat
"""
import json
import asyncio
import logging
from datetime import datetime
from bson import ObjectId
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.websocket_service import connection_manager, realtime_service
from db.db_manager import get_database

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/support/chat/ws")
async def chat_websocket(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token")
):
    """
    WebSocket endpoint for real-time support chat.

    Client sends:
      {"type": "chat_message", "ticket_id": "...", "message": "..."}
      {"type": "typing", "ticket_id": "..."}
      {"type": "ping"}

    Server pushes:
      {"type": "chat_message", "ticket_id": "...", "message": {...}}
      {"type": "typing", "ticket_id": "...", "user_name": "..."}
      {"type": "pong"}
    """
    # Authenticate
    auth_data = await realtime_service.authenticate_websocket(websocket, token)
    if not auth_data:
        return

    user_id = auth_data["user_id"]
    user_role = auth_data["user_role"]
    user_name = auth_data.get("name", "User")

    # Register connection
    await connection_manager.connect(
        websocket, user_id, user_role,
        {"type": "chat", "name": user_name}
    )

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "ping":
                    await connection_manager.send_personal_message(
                        {"type": "pong", "timestamp": datetime.utcnow().isoformat() + "Z"},
                        websocket
                    )

                elif msg_type == "chat_message":
                    await _handle_chat_message(data, user_id, user_name, user_role)

                elif msg_type == "typing":
                    await _handle_typing(data, user_id, user_name, user_role)

            except asyncio.TimeoutError:
                # Send keepalive ping
                await connection_manager.send_personal_message(
                    {"type": "ping", "timestamp": datetime.utcnow().isoformat() + "Z"},
                    websocket
                )
            except json.JSONDecodeError:
                await connection_manager.send_personal_message(
                    {"type": "error", "message": "Invalid JSON"},
                    websocket
                )

    except WebSocketDisconnect:
        connection_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"Chat WebSocket error for user {user_id}: {e}")
        connection_manager.disconnect(websocket)


async def _handle_chat_message(data: dict, user_id: str, user_name: str, user_role: str):
    """Save chat message to DB and push to the other party"""
    ticket_id = data.get("ticket_id")
    message_text = data.get("message", "").strip()

    if not ticket_id or not message_text or not ObjectId.is_valid(ticket_id):
        return

    db = get_database()

    # Verify ticket exists and user has access
    ticket = await db.find_one("support_tickets", {"_id": ObjectId(ticket_id)})
    if not ticket:
        return

    # Users can only send on their own tickets; admins can send on any
    if user_role != "admin" and str(ticket["user_id"]) != user_id:
        return

    if ticket.get("status") == "closed":
        return

    sender_type = "admin" if user_role == "admin" else "user"

    new_message = {
        "_id": ObjectId(),
        "message": message_text,
        "sender_type": sender_type,
        "sender_name": user_name,
        "sender_id": user_id,
        "created_at": datetime.utcnow(),
    }

    # Save to DB
    update_fields = {"updated_at": datetime.utcnow()}
    if sender_type == "user" and ticket["status"] == "resolved":
        update_fields["status"] = "open"

    await db.update_one(
        "support_tickets",
        {"_id": ObjectId(ticket_id)},
        {
            "$push": {"messages": new_message},
            "$set": update_fields
        }
    )

    # Build payload for WebSocket push
    message_payload = {
        "type": "chat_message",
        "ticket_id": ticket_id,
        "message": {
            "_id": str(new_message["_id"]),
            "message": new_message["message"],
            "sender_type": sender_type,
            "sender_name": user_name,
            "sender_id": user_id,
            "created_at": new_message["created_at"].isoformat(),
        }
    }

    # Push to the other party
    if sender_type == "user":
        # User sent → push to all admins
        await connection_manager.send_to_role(message_payload, "admin")
    else:
        # Admin sent → push to the ticket owner
        ticket_user_id = str(ticket["user_id"])
        await connection_manager.send_to_user(message_payload, ticket_user_id)

        # If user is offline, create a notification
        if not connection_manager.get_user_connections_count(ticket_user_id):
            try:
                from app.routes.notifications import create_notification
                await create_notification(
                    db, ticket_user_id,
                    "New message from support",
                    message_text[:100],
                    "support_chat"
                )
            except Exception as e:
                logger.warning(f"Failed to create offline notification: {e}")


async def _handle_typing(data: dict, user_id: str, user_name: str, user_role: str):
    """Forward typing indicator to the other party"""
    ticket_id = data.get("ticket_id")
    if not ticket_id:
        return

    payload = {
        "type": "typing",
        "ticket_id": ticket_id,
        "user_id": user_id,
        "user_name": user_name,
    }

    if user_role == "admin":
        # Admin typing → push to ticket owner
        db = get_database()
        ticket = await db.find_one("support_tickets", {"_id": ObjectId(ticket_id)})
        if ticket:
            await connection_manager.send_to_user(payload, str(ticket["user_id"]))
    else:
        # User typing → push to admins
        await connection_manager.send_to_role(payload, "admin")
