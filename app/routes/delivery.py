from bson import ObjectId
from fastapi import HTTPException,APIRouter, Depends, status,BackgroundTasks
from app.utils.auth import current_active_user
from app.utils.mongo import fix_mongo_types
from app.utils.get_time import utc_isoformat
from db.db_manager import DatabaseManager, get_database
from schema.user import UserinDB
import logging
from app.routes.notifications import create_notification
from app.services.email_service import email_service
from datetime import datetime

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/available")
async def get_available_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database),
    page: int = 1,
    limit: int = 10,
):
    if current_user.role != "delivery_partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only delivery partners allowed"
        )

    skip = (page - 1) * limit

    try:
        orders = await db.find_many(
            "orders",
            {"order_status": "assigning"},
            sort=[("created_at", -1)],
            skip=skip,
            limit=limit,
        )

        # ⚡ Lightweight response only
        response = []
        for order in orders:
            response.append({
                "id": order.get("id"),
                "created_at": utc_isoformat(order.get("created_at")),
                "order_status": order.get("order_status"),
            })

        return {
            "data": response,
            "page": page,
            "has_more": len(response) == limit,
        }

    except Exception as e:
        logger.error(f"Available orders error: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to fetch available orders"
        )

@router.get("/assigned")
async def get_assigned_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database),
    page: int = 1,
    limit: int = 10,
):
    if current_user.role != "delivery_partner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only delivery partners can access this"
        )

    skip = (page - 1) * limit

    orders = await db.find_many(
        "orders",
        {
            "delivery_partner": current_user.id,
            "order_status": {"$in": ["assigned", "out_for_delivery"]},
        },
        sort=[("created_at", -1)],
        skip=skip,
        limit=limit,
    )

    if not orders:
        return []

    user_ids = list({o["user"] for o in orders if o.get("user")})
    users = await db.find_many("users", {"id": {"$in": user_ids}})
    users_map = {u["id"]: u for u in users}

    response = []

    for order in orders:
        user = users_map.get(order.get("user"), {})

        summary = {
            "id": order.get("id"),
            "created_at": utc_isoformat(order.get("created_at")),
            "order_type": order.get("order_type", "product"),
            "order_status": order.get("order_status"),
            "payment_method": order.get("payment_method"),
            "payment_amount": order.get("total_amount", 0),

            "customer": {
                "name": order.get("delivery_address", {}).get("name") or user.get("name", "N/A"),
                "phone": order.get("delivery_address", {}).get("mobile_number") or user.get("phone", "N/A"),
            },

            "delivery": None,
            "porter": None,
        }

        if order.get("delivery_address"):
            da = order["delivery_address"]
            summary["delivery"] = {
                "address": f'{da.get("street")}, {da.get("city")}, {da.get("state")} - {da.get("pincode")}'
            }

        # 🚚 Porter service (pickup + drop)
        for item in order.get("items", []):
            if item.get("type") == "porter":
                s = item.get("service_data", {})
                summary["porter"] = {
                    "pickup": f'{s.get("pickup_address", {}).get("street")}, {s.get("pickup_address", {}).get("city")}',
                    "drop": f'{s.get("delivery_address", {}).get("street")}, {s.get("delivery_address", {}).get("city")}',
                    "recipient_name": s.get("recipient_name"),
                    "phone": s.get("phone"),
                    "distance": s.get("estimated_distance"),
                }
                break

        response.append(summary)

    return response

@router.get("/delivered")
async def get_delivered_orders_for_delivery(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    try:
        # Only delivery partners can access
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can access this endpoint."
            )
        
        # Fetch delivered orders for this partner
        orders = await db.find_many(
            "orders",
            {
                "delivery_partner": current_user.id,
                "order_status": "delivered"
            },
            sort=[("updated_at", -1)]
        )

        delivered_summary = []
        for order in orders:
            try:
                total_amount = order.get("total_amount", 0)
                tip = order.get("tip_amount", 0)
                earnings = round((total_amount * 0.1) + tip, 2)  # 10% commission + tip

                delivered_summary.append({
                    "id": order.get("id"),
                    "delivered_at": utc_isoformat(order.get("delivered_at")),
                    "tip_amount": tip,
                    "total_earnings": earnings
                })
            except Exception as e:
                logger.error(f"Error processing delivered order {order.get('id')}: {e}")
                continue

        logger.info(f"Returning {len(delivered_summary)} delivered orders for delivery partner {current_user.id}")
        return delivered_summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get delivered orders error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get delivered orders"
        )


@router.get("/order/{order_id}")
async def get_delivery_order_details(
    order_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database),
):
    if current_user.role != "delivery_partner":
        raise HTTPException(status_code=403, detail="Access denied")

    order = await db.find_one("orders", {"id": order_id})

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.get("delivery_partner") != current_user.id:
        raise HTTPException(status_code=403, detail="Not your order")

    user = await db.find_one("users", {"id": order["user"]})

    response = {
        "id": order["id"],
        "created_at": utc_isoformat(order["created_at"]),
        "order_status": order["order_status"],
        "order_type": order.get("order_type"),
        "payment_method": order.get("payment_method"),
        "payment_amount": order.get("total_amount")
        if order.get("payment_method") == "cod"
        else None,
        "customer": {
            "name": order.get("delivery_address", {}).get("name") or user.get("name"),
            "phone": order.get("delivery_address", {}).get("mobile_number") or user.get("phone"),
        },
        "delivery_address": order.get("delivery_address"),
        "porter": None,
        "items": [],
    }
    # Add items (minimal)
    for item in order.get("items", []):
        if item["type"] == "product":
            product = await db.find_one("products",{'id':item["product"]})
            if product:
                brand = product.get("brand", {})
                brand_name = brand.get("name") if isinstance(brand, dict) else None
                response["items"].append({
                    "type": "product",
                    "name": product.get("name"),
                    "quantity": item.get("quantity"),
                    "warehouse_name": brand_name,
                })
            else:
                response["items"].append({
                    "type": "product",
                    "name": "Not Available",
                    "quantity": item.get("quantity"),
                    "warehouse_name": None,
                })

        if item["type"] == "porter":
            s = item["service_data"]
            response["items"].append({
                "type": "porter",
                "pickup": s["pickup_address"],
                "drop": s["delivery_address"],
                "recipient_name": s.get("recipient_name"),
                "phone": s.get("phone"),
                "distance": s.get("estimated_distance"),
            })
            response["porter"] = {
                "pickup": f'{s.get("pickup_address", {}).get("street")}, {s.get("pickup_address", {}).get("city")}',
                "drop": f'{s.get("delivery_address", {}).get("street")}, {s.get("delivery_address", {}).get("city")}',
                "recipient_name": s.get("recipient_name"),
                "phone": s.get("phone"),
                "distance": s.get("estimated_distance"),
            }
        if item["type"] == "printout":
            s = item["service_data"]
            response["items"].append({
                "type": "printout",
            })
    return response

@router.post("/{order_id}/accept")
async def accept_delivery_order(
    order_id: str,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Accept an order for delivery"""
    try:
        # Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can accept orders."
            )
        
        # Validate order_id
        try:
            order_object_id = str(order_id)
        except Exception:
            logger.error("Invalid order ID")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid order ID format"
            )
        
        # Check if order exists and is available for assignment
        order = await db.find_one("orders", {"id": order_object_id})
        if not order:
            logger.error("Order not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        # Check if order is already assigned
        if order.get("delivery_partner"):
            logger.info("Order already assigned to other agent")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Order is already assigned to another delivery partner"
            )
        
        # Check if order status allows assignment
        if order.get("order_status") not in ["preparing","assigning"]:
            logger.error("can't be assigned")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order with status '{order.get('order_status')}' cannot be assigned for delivery"
            )

        accepted_partners = order.get("accepted_partners",[])
        if current_user.id in accepted_partners:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You have already accepted this order"
            )
        accepted_partners.append(current_user.id)
        
        current_time = datetime.utcnow()
        status_history_entry = {
            "status": "assigning",
            "changed_at": current_time,
            "changed_by": current_user.name,
            "partner_id": current_user.id,
            "message": f"{current_user.name} accepted the order"
        }
        update_data = {
            "$set": {
                "accepted_partners": accepted_partners,
                "order_status": "assigning",
                "accepted_at": current_time,
                "updated_at": current_time,
                "status_message": f"Order accepted by {current_user.name}"
            },
            "$push": {
                "status_change_history": status_history_entry
            }
        }

        await db.update_one(
            "orders",
            {"id": order_id},
            update_data
        )
        
        # Create notification for user
        await create_notification(
            db=db,
            user_id=order.get("user"),
            title="Delivery Partner Found",
            message=f"A delivery partner is reviewing your order from {order.get('restaurant_name', 'the restaurant')}.",
            notification_type="order",
            order_id=order_id
        )
        
        logger.info(f"Order {order_id} assigned to delivery partner {current_user.id}")
        
        return {"message": "Order accepted successfully", "order_id": order_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Accept delivery order error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to accept order"
        )


@router.post("/{order_id}/mark-delivered")
async def mark_order_as_delivered(
    order_id: str,
    background_tasks: BackgroundTasks,  # Add this
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Mark an assigned order as delivered"""
    try:
        #    Check if user is a delivery partner
        if current_user.role != "delivery_partner":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Only delivery partners can mark orders as delivered."
            )
        order = await db.find_one("orders", {
            "id": order_id,
            "delivery_partner": current_user.id
        })
      
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found or not assigned to you"
            )
        
        # Check if order status allows marking as delivered
        if order.get("order_status") not in ["out_for_delivery"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order with status '{order.get('order_status')}' cannot be marked as delivered"
            )
        
        current_time = datetime.utcnow()

        # Mark the order as delivered with proper timeline
        await db.update_one(
            "orders",
            {"id": order_id},
            {
                "$set": {
                    "order_status": "delivered",
                    "delivered_at": current_time,
                    "payment_status": "completed" if order.get("payment_method") == "cod" else order.get("payment_status"),
                    "updated_at": current_time,
                    "status_message": "Order delivered successfully!"
                },
                "$push": {
                    "status_change_history": {
                        "status": "delivered",
                        "changed_at": current_time,
                        "changed_by": current_user.name,
                        "message": f"Order delivered by {current_user.name}"
                    }
                }
            }
        )
        
        # Get user info for email
        user_info = await db.find_one("users", {"id": order.get("user")})
        
        # Create notification for user
        await create_notification(
            db=db,
            user_id=order.get("user"),
            title="Order Delivered! 🎉",
            message=f"Your order from {order.get('restaurant_name', 'the restaurant')} has been delivered. Enjoy your meal!",
            notification_type="order",
            order_id=order_id
        )
        
        # Send email notification in background
        if user_info and user_info.get("email"):
            background_tasks.add_task(
                email_service.send_order_status_update,
                user_info.get("email"),
                order_id,
                "delivered",
                user_info.get("name", "Customer")
            )
        
        logger.info(f"Order {order_id} marked as delivered by delivery partner {current_user.id}")
        
        return {"message": "Order marked as delivered successfully", "order_id": order_id}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Mark order as delivered error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark order as delivered"
        )