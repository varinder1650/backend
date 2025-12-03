# app/routes/payment.py - PhonePe Payment Routes
import hashlib
import base64
import json
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
import httpx
from db.db_manager import DatabaseManager, get_database
from app.utils.auth import current_active_user
from schema.user import UserinDB
from app.utils.get_time import get_ist_datetime_for_db
from bson import ObjectId

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payment", tags=["payment"])

# PhonePe Configuration
PHONEPE_MERCHANT_ID = "YOUR_MERCHANT_ID"  # Replace with your PhonePe merchant ID
PHONEPE_SALT_KEY = "YOUR_SALT_KEY"  # Replace with your PhonePe salt key
PHONEPE_SALT_INDEX = "1"  # Usually 1 for production
PHONEPE_API_URL = "https://api.phonepe.com/apis/hermes"  # Production URL
# For testing use: "https://api-preprod.phonepe.com/apis/pg-sandbox"

class PaymentInitiateRequest(BaseModel):
    order_id: str
    amount: float
    callback_url: Optional[str] = None

class PaymentStatusRequest(BaseModel):
    merchant_transaction_id: str

def generate_phonepe_checksum(payload: str, endpoint: str) -> str:
    """Generate X-VERIFY checksum for PhonePe API"""
    checksum_string = f"{payload}{endpoint}{PHONEPE_SALT_KEY}"
    checksum = hashlib.sha256(checksum_string.encode()).hexdigest()
    return f"{checksum}###{PHONEPE_SALT_INDEX}"

@router.post("/phonepe/initiate")
async def initiate_phonepe_payment(
    payment_request: PaymentInitiateRequest,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Initiate PhonePe payment for an order
    """
    try:
        logger.info(f"📱 Initiating PhonePe payment for order {payment_request.order_id}")
        
        # Verify order exists and belongs to user
        order = await db.find_one(
            "orders",
            {"id": payment_request.order_id, "user": current_user.id}
        )
        
        if not order:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found"
            )
        
        if order.get("payment_status") == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment already completed for this order"
            )
        
        # Generate unique merchant transaction ID
        merchant_transaction_id = f"MT{payment_request.order_id}{int(get_ist_datetime_for_db()['ist'].timestamp())}"
        
        # Convert amount to paise (PhonePe requires amount in paise)
        amount_in_paise = int(payment_request.amount * 100)
        
        # Prepare PhonePe payment request
        payment_payload = {
            "merchantId": PHONEPE_MERCHANT_ID,
            "merchantTransactionId": merchant_transaction_id,
            "merchantUserId": str(current_user.id),
            "amount": amount_in_paise,
            "redirectUrl": payment_request.callback_url or f"https://yourapp.com/payment/callback",
            "redirectMode": "POST",
            "callbackUrl": f"https://yourapi.com/payment/phonepe/callback",
            "mobileNumber": current_user.phone or order.get("delivery_address", {}).get("phone", ""),
            "paymentInstrument": {
                "type": "PAY_PAGE"
            }
        }
        
        # Encode payload to base64
        payload_json = json.dumps(payment_payload)
        payload_base64 = base64.b64encode(payload_json.encode()).decode()
        
        # Generate checksum
        endpoint = "/pg/v1/pay"
        checksum = generate_phonepe_checksum(payload_base64, endpoint)
        
        # Make API request to PhonePe
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": checksum
        }
        
        request_body = {
            "request": payload_base64
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{PHONEPE_API_URL}{endpoint}",
                json=request_body,
                headers=headers
            )
        
        response_data = response.json()
        logger.info(f"PhonePe Response: {response_data}")
        
        if response.status_code == 200 and response_data.get("success"):
            # Store payment transaction details
            payment_record = {
                "order_id": payment_request.order_id,
                "user_id": current_user.id,
                "merchant_transaction_id": merchant_transaction_id,
                "phonepe_transaction_id": response_data.get("data", {}).get("transactionId"),
                "amount": payment_request.amount,
                "status": "pending",
                "payment_method": "phonepe",
                "created_at": get_ist_datetime_for_db()['ist'],
                "payment_url": response_data.get("data", {}).get("instrumentResponse", {}).get("redirectInfo", {}).get("url")
            }
            
            await db.insert_one("payment_transactions", payment_record)
            
            # Update order with payment details
            await db.update_one(
                "orders",
                {"id": payment_request.order_id},
                {
                    "$set": {
                        "payment_transaction_id": merchant_transaction_id,
                        "payment_status": "pending",
                        "updated_at": get_ist_datetime_for_db()['ist']
                    }
                }
            )
            
            logger.info(f"✅ PhonePe payment initiated: {merchant_transaction_id}")
            
            return {
                "success": True,
                "payment_url": response_data.get("data", {}).get("instrumentResponse", {}).get("redirectInfo", {}).get("url"),
                "merchant_transaction_id": merchant_transaction_id,
                "message": "Payment initiated successfully"
            }
        else:
            error_message = response_data.get("message", "Payment initiation failed")
            logger.error(f"❌ PhonePe payment initiation failed: {error_message}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error initiating PhonePe payment: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate payment"
        )

@router.post("/phonepe/callback")
async def phonepe_payment_callback(
    request: Request,
    db: DatabaseManager = Depends(get_database)
):
    """
    Handle PhonePe payment callback
    This endpoint is called by PhonePe after payment completion
    """
    try:
        # Get the callback data
        body = await request.body()
        callback_data = await request.json()
        
        logger.info(f"📱 PhonePe callback received: {callback_data}")
        
        # Verify the callback checksum
        x_verify = request.headers.get("X-VERIFY")
        
        if not x_verify:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing X-VERIFY header"
            )
        
        # Extract base64 encoded response
        response_base64 = callback_data.get("response")
        
        if not response_base64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing response data"
            )
        
        # Verify checksum
        expected_checksum = hashlib.sha256(
            f"{response_base64}/pg/v1/pay{PHONEPE_SALT_KEY}".encode()
        ).hexdigest() + f"###{PHONEPE_SALT_INDEX}"
        
        if x_verify != expected_checksum:
            logger.error("❌ Invalid callback checksum")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid checksum"
            )
        
        # Decode response
        response_json = base64.b64decode(response_base64).decode()
        response_data = json.loads(response_json)
        
        merchant_transaction_id = response_data.get("data", {}).get("merchantTransactionId")
        payment_status = response_data.get("code")
        
        # Find the payment transaction
        payment_transaction = await db.find_one(
            "payment_transactions",
            {"merchant_transaction_id": merchant_transaction_id}
        )
        
        if not payment_transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment transaction not found"
            )
        
        order_id = payment_transaction["order_id"]
        
        # Update payment transaction status
        current_time = get_ist_datetime_for_db()
        
        if payment_status == "PAYMENT_SUCCESS":
            # Payment successful
            await db.update_one(
                "payment_transactions",
                {"merchant_transaction_id": merchant_transaction_id},
                {
                    "$set": {
                        "status": "completed",
                        "phonepe_response": response_data,
                        "completed_at": current_time['ist'],
                        "updated_at": current_time['ist']
                    }
                }
            )
            
            # Update order payment status
            await db.update_one(
                "orders",
                {"id": order_id},
                {
                    "$set": {
                        "payment_status": "completed",
                        "updated_at": current_time['ist']
                    }
                }
            )
            
            logger.info(f"✅ Payment completed for order {order_id}")
            
            return {
                "success": True,
                "message": "Payment completed successfully",
                "order_id": order_id
            }
        
        elif payment_status in ["PAYMENT_ERROR", "PAYMENT_DECLINED"]:
            # Payment failed
            await db.update_one(
                "payment_transactions",
                {"merchant_transaction_id": merchant_transaction_id},
                {
                    "$set": {
                        "status": "failed",
                        "phonepe_response": response_data,
                        "failed_at": current_time['ist'],
                        "updated_at": current_time['ist']
                    }
                }
            )
            
            # Update order payment status
            await db.update_one(
                "orders",
                {"id": order_id},
                {
                    "$set": {
                        "payment_status": "failed",
                        "updated_at": current_time['ist']
                    }
                }
            )
            
            logger.warning(f"⚠️ Payment failed for order {order_id}")
            
            return {
                "success": False,
                "message": "Payment failed",
                "order_id": order_id
            }
        
        else:
            # Payment pending or other status
            await db.update_one(
                "payment_transactions",
                {"merchant_transaction_id": merchant_transaction_id},
                {
                    "$set": {
                        "status": "pending",
                        "phonepe_response": response_data,
                        "updated_at": current_time['ist']
                    }
                }
            )
            
            return {
                "success": False,
                "message": "Payment pending",
                "order_id": order_id
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error processing PhonePe callback: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process payment callback"
        )

@router.post("/phonepe/status")
async def check_phonepe_payment_status(
    status_request: PaymentStatusRequest,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Check PhonePe payment status manually
    """
    try:
        logger.info(f"🔍 Checking payment status: {status_request.merchant_transaction_id}")
        
        # Find payment transaction
        payment_transaction = await db.find_one(
            "payment_transactions",
            {
                "merchant_transaction_id": status_request.merchant_transaction_id,
                "user_id": current_user.id
            }
        )
        
        if not payment_transaction:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Payment transaction not found"
            )
        
        # Prepare status check request
        endpoint = f"/pg/v1/status/{PHONEPE_MERCHANT_ID}/{status_request.merchant_transaction_id}"
        
        # Generate checksum
        checksum_string = f"{endpoint}{PHONEPE_SALT_KEY}"
        checksum = hashlib.sha256(checksum_string.encode()).hexdigest() + f"###{PHONEPE_SALT_INDEX}"
        
        headers = {
            "Content-Type": "application/json",
            "X-VERIFY": checksum,
            "X-MERCHANT-ID": PHONEPE_MERCHANT_ID
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{PHONEPE_API_URL}{endpoint}",
                headers=headers
            )
        
        response_data = response.json()
        logger.info(f"PhonePe Status Response: {response_data}")
        
        if response.status_code == 200 and response_data.get("success"):
            payment_status = response_data.get("code")
            
            # Update transaction status based on response
            current_time = get_ist_datetime_for_db()
            
            if payment_status == "PAYMENT_SUCCESS":
                await db.update_one(
                    "payment_transactions",
                    {"merchant_transaction_id": status_request.merchant_transaction_id},
                    {
                        "$set": {
                            "status": "completed",
                            "phonepe_response": response_data,
                            "completed_at": current_time['ist'],
                            "updated_at": current_time['ist']
                        }
                    }
                )
                
                await db.update_one(
                    "orders",
                    {"id": payment_transaction["order_id"]},
                    {
                        "$set": {
                            "payment_status": "completed",
                            "updated_at": current_time['ist']
                        }
                    }
                )
            
            return {
                "success": True,
                "status": payment_status,
                "data": response_data.get("data", {}),
                "order_id": payment_transaction["order_id"]
            }
        else:
            return {
                "success": False,
                "message": response_data.get("message", "Failed to fetch payment status"),
                "order_id": payment_transaction["order_id"]
            }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error checking payment status: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check payment status"
        )

@router.get("/transactions/my")
async def get_my_payment_transactions(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get user's payment transaction history
    """
    try:
        transactions = await db.find_many(
            "payment_transactions",
            {"user_id": current_user.id},
            sort=[("created_at", -1)],
            limit=50
        )
        
        # Serialize transactions
        serialized_transactions = []
        for txn in transactions:
            serialized_txn = {
                "_id": str(txn["_id"]),
                "order_id": txn.get("order_id"),
                "merchant_transaction_id": txn.get("merchant_transaction_id"),
                "amount": txn.get("amount"),
                "status": txn.get("status"),
                "payment_method": txn.get("payment_method"),
                "created_at": txn.get("created_at").isoformat() if txn.get("created_at") else None,
                "completed_at": txn.get("completed_at").isoformat() if txn.get("completed_at") else None,
            }
            serialized_transactions.append(serialized_txn)
        
        return {
            "transactions": serialized_transactions,
            "total": len(serialized_transactions)
        }
    
    except Exception as e:
        logger.error(f"❌ Error fetching payment transactions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch payment transactions"
        )

# Add this helper function for internal payment initiation
async def initiate_phonepe_payment_internal(
    order_id: str,
    amount: float,
    user,
    db: DatabaseManager
):
    """Internal function to initiate PhonePe payment (used by order creation)"""
    from app.routes.payment import (
        PHONEPE_MERCHANT_ID,
        PHONEPE_SALT_KEY,
        PHONEPE_SALT_INDEX,
        PHONEPE_API_URL,
        generate_phonepe_checksum
    )
    import httpx
    import json
    import base64
    
    # Generate unique merchant transaction ID
    merchant_transaction_id = f"MT{order_id}{int(get_ist_datetime_for_db()['ist'].timestamp())}"
    
    # Convert amount to paise
    amount_in_paise = int(amount * 100)
    
    # Get order details for phone number
    order = await db.find_one("orders", {"id": order_id})
    phone_number = ""
    if order:
        phone_number = order.get("delivery_address", {}).get("phone", "")
    
    # Prepare PhonePe payment request
    payment_payload = {
        "merchantId": PHONEPE_MERCHANT_ID,
        "merchantTransactionId": merchant_transaction_id,
        "merchantUserId": str(user.id),
        "amount": amount_in_paise,
        "redirectUrl": f"https://yourapp.com/payment/callback",
        "redirectMode": "POST",
        "callbackUrl": f"https://yourapi.com/payment/phonepe/callback",
        "mobileNumber": phone_number or user.phone or "",
        "paymentInstrument": {
            "type": "PAY_PAGE"
        }
    }
    
    # Encode payload to base64
    payload_json = json.dumps(payment_payload)
    payload_base64 = base64.b64encode(payload_json.encode()).decode()
    
    # Generate checksum
    endpoint = "/pg/v1/pay"
    checksum = generate_phonepe_checksum(payload_base64, endpoint)
    
    # Make API request to PhonePe
    headers = {
        "Content-Type": "application/json",
        "X-VERIFY": checksum
    }
    
    request_body = {
        "request": payload_base64
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{PHONEPE_API_URL}{endpoint}",
            json=request_body,
            headers=headers
        )
    
    response_data = response.json()
    
    if response.status_code == 200 and response_data.get("success"):
        # Store payment transaction details
        payment_record = {
            "order_id": order_id,
            "user_id": user.id,
            "merchant_transaction_id": merchant_transaction_id,
            "phonepe_transaction_id": response_data.get("data", {}).get("transactionId"),
            "amount": amount,
            "status": "pending",
            "payment_method": "phonepe",
            "created_at": get_ist_datetime_for_db()['ist'],
            "payment_url": response_data.get("data", {}).get("instrumentResponse", {}).get("redirectInfo", {}).get("url")
        }
        
        await db.insert_one("payment_transactions", payment_record)
        
        # Update order with payment details
        await db.update_one(
            "orders",
            {"id": order_id},
            {
                "$set": {
                    "payment_transaction_id": merchant_transaction_id,
                    "payment_status": "pending",
                    "updated_at": get_ist_datetime_for_db()['ist']
                }
            }
        )
        
        return {
            "success": True,
            "payment_url": response_data.get("data", {}).get("instrumentResponse", {}).get("redirectInfo", {}).get("url"),
            "merchant_transaction_id": merchant_transaction_id
        }
    else:
        raise Exception(response_data.get("message", "Payment initiation failed"))

# Update the porter payment callback

@router.post("/phonepe/callback/porter")
async def phonepe_porter_payment_callback(
    request: Request,
    db: DatabaseManager = Depends(get_database)
):
    """Handle PhonePe payment callback for porter requests"""
    try:
        callback_data = await request.json()
        logger.info(f"📱 PhonePe Porter callback: {callback_data}")
        
        # Verify checksum
        x_verify = request.headers.get("X-VERIFY")
        if not x_verify:
            raise HTTPException(status_code=400, detail="Missing X-VERIFY")
        
        response_base64 = callback_data.get("response")
        if not response_base64:
            raise HTTPException(status_code=400, detail="Missing response")
        
        # Decode response
        import base64
        import json
        response_json = base64.b64decode(response_base64).decode()
        response_data = json.loads(response_json)
        
        merchant_transaction_id = response_data.get("data", {}).get("merchantTransactionId")
        payment_status = response_data.get("code")
        
        # Find payment transaction
        payment_transaction = await db.find_one(
            "payment_transactions",
            {"merchant_transaction_id": merchant_transaction_id}
        )
        
        if not payment_transaction:
            raise HTTPException(status_code=404, detail="Payment transaction not found")
        
        request_id = payment_transaction["request_id"]
        
        from app.utils.get_time import get_ist_datetime_for_db
        current_time = get_ist_datetime_for_db()
        
        if payment_status == "PAYMENT_SUCCESS":
            # Update payment transaction
            await db.update_one(
                "payment_transactions",
                {"merchant_transaction_id": merchant_transaction_id},
                {
                    "$set": {
                        "status": "completed",
                        "phonepe_response": response_data,
                        "completed_at": current_time['ist'],
                    }
                }
            )
            
            # Update porter request payment status
            await db.update_one(
                "porter_requests",
                {"id": request_id},
                {
                    "$set": {
                        "payment_status": "completed",
                        "paid_at": current_time['ist'],
                        "updated_at": current_time['ist'],
                    }
                }
            )
            
            # ✅ Create notification with push
            try:
                from app.routes.notifications import create_notification
                porter_request = await db.find_one("porter_requests", {"id": request_id})
                if porter_request:
                    await create_notification(
                        db=db,
                        user_id=porter_request["user_id"],
                        title="Payment Successful! ✅",
                        message=f"Payment of ₹{payment_transaction['amount']} completed. Your porter request is now confirmed.",
                        notification_type="porter_payment",
                        order_id=request_id
                    )
            except Exception as notif_error:
                logger.error(f"Failed to create notification: {notif_error}")
            
            logger.info(f"✅ Porter payment completed for request {request_id}")
            
            return {
                "success": True,
                "message": "Payment completed",
                "request_id": request_id
            }
        
        elif payment_status in ["PAYMENT_ERROR", "PAYMENT_DECLINED"]:
            # Payment failed
            await db.update_one(
                "payment_transactions",
                {"merchant_transaction_id": merchant_transaction_id},
                {"$set": {"status": "failed", "failed_at": current_time['ist']}}
            )
            
            await db.update_one(
                "porter_requests",
                {"id": request_id},
                {"$set": {"payment_status": "failed", "updated_at": current_time['ist']}}
            )
            
            # ✅ Send failure notification
            try:
                from app.routes.notifications import create_notification
                porter_request = await db.find_one("porter_requests", {"id": request_id})
                if porter_request:
                    await create_notification(
                        db=db,
                        user_id=porter_request["user_id"],
                        title="Payment Failed ❌",
                        message=f"Payment of ₹{payment_transaction['amount']} failed. Please try again.",
                        notification_type="porter_payment_failed",
                        order_id=request_id
                    )
            except Exception as notif_error:
                logger.error(f"Failed to create notification: {notif_error}")
            
            logger.warning(f"⚠️ Porter payment failed for request {request_id}")
            return {"success": False, "message": "Payment failed"}
        
    except Exception as e:
        logger.error(f"Error processing porter payment callback: {e}")
        raise HTTPException(status_code=500, detail="Failed to process callback")


# Similarly update the regular order payment callback
@router.post("/phonepe/callback")
async def phonepe_payment_callback(
    request: Request,
    db: DatabaseManager = Depends(get_database)
):
    """Handle PhonePe payment callback"""
    try:
        # ... existing verification code ...
        
        if payment_status == "PAYMENT_SUCCESS":
            # ... existing update code ...
            
            # ✅ Add notification
            try:
                from app.routes.notifications import create_notification
                order = await db.find_one("orders", {"id": order_id})
                if order:
                    await create_notification(
                        db=db,
                        user_id=order["user"],
                        title="Payment Successful! ✅",
                        message=f"Payment completed for order #{order_id}. Your order is being processed.",
                        notification_type="order_payment",
                        order_id=order_id
                    )
            except Exception as notif_error:
                logger.error(f"Failed to create notification: {notif_error}")
            
            return {
                "success": True,
                "message": "Payment completed successfully",
                "order_id": order_id
            }
        
        # ... rest of the code ...
        
    except Exception as e:
        logger.error(f"Error processing payment callback: {e}")
        raise HTTPException(status_code=500, detail="Failed to process callback")