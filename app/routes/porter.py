from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field, validator
from typing import Optional
from bson import ObjectId
from db.db_manager import get_database, DatabaseManager
from app.utils.auth import get_current_user, current_active_user
from app.utils.get_time import get_ist_datetime_for_db
from schema.user import UserinDB
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

class Address(BaseModel):
    address: str = Field(..., min_length=10, max_length=300)
    city: str = Field(..., min_length=2, max_length=50)
    pincode: str = Field(..., min_length=6, max_length=6)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    @validator('pincode')
    def validate_pincode(cls, v):
        if not v.isdigit():
            raise ValueError('Pincode must contain only digits')
        return v

class PackageDimensions(BaseModel):
    length: str = Field(..., description="Length category: '< 10 cm', '10-20 cm', '20-50 cm', '> 50 cm'")
    breadth: str = Field(..., description="Breadth category: '< 10 cm', '10-20 cm', '20-50 cm', '> 50 cm'")
    height: str = Field(..., description="Height category: '< 10 cm', '10-20 cm', '20-50 cm', '> 50 cm'")
    unit: str = Field(default="cm")
    
    @validator('length', 'breadth', 'height')
    def validate_dimension_category(cls, v):
        valid_categories = ['< 10 cm', '10-20 cm', '20-50 cm', '> 50 cm']
        if v not in valid_categories:
            raise ValueError(f'Dimension must be one of: {", ".join(valid_categories)}')
        return v
    
    @validator('unit')
    def validate_unit(cls, v):
        if v not in ['cm', 'inch']:
            raise ValueError('Unit must be cm or inch')
        return v
        
class PorterRequestCreate(BaseModel):
    pickup_address: Address
    delivery_address: Address
    phone: str = Field(..., min_length=10, max_length=15)
    description: str = Field(..., min_length=10, max_length=500)
    dimensions: PackageDimensions
    weight_category: str
    estimated_distance: Optional[float] = Field(None, gt=0, le=1000)
    urgent: bool = Field(default=False)
    estimated_cost: float = Field(..., gt=0)
    
    @validator('weight_category')
    def validate_weight(cls, v):
        valid_categories = ['< 0.5 kg', '0.5-1 kg', '1-2 kg', '> 2 kg']
        if v not in valid_categories:
            raise ValueError(f'Weight category must be one of {valid_categories}')
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        cleaned = v.replace(' ', '').replace('-', '')
        if not cleaned.replace('+', '').isdigit():
            raise ValueError('Phone number must contain only digits')
        return v

class EstimateCostUpdate(BaseModel):
    estimated_cost: float = Field(..., gt=0)
    admin_notes: Optional[str] = None

@router.post("/porter-requests")
async def create_porter_request(
    request_data: PorterRequestCreate,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user)
):
    """Create a new porter delivery request"""
    try:
        db = get_database()
        
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        user_name = current_user.name if hasattr(current_user, 'name') else "Unknown"
        user_email = current_user.email if hasattr(current_user, 'email') else "Unknown"
        user_phone = current_user.phone if hasattr(current_user, 'phone') else "Not provided"
        
        current_time = get_ist_datetime_for_db()
        request_id = str(ObjectId())
        print(request_data)
        # Prepare porter request document
        porter_request = {
            "_id": ObjectId(request_id),
            "id": request_id,
            "user_id": user_id if isinstance(user_id, str) else user_id,
            "user_name": user_name,
            "user_email": user_email,
            "user_phone": user_phone,
            "pickup_address": {
                "address": request_data.pickup_address.address,
                "city": request_data.pickup_address.city,
                "pincode": request_data.pickup_address.pincode,
                "latitude": request_data.pickup_address.latitude,
                "longitude": request_data.pickup_address.longitude,
            },
            "delivery_address": {
                "address": request_data.delivery_address.address,
                "city": request_data.delivery_address.city,
                "pincode": request_data.delivery_address.pincode,
                "latitude": request_data.delivery_address.latitude,  
                "longitude": request_data.delivery_address.longitude,
            },
            "phone": request_data.phone,
            "estimated_distance": request_data.estimated_distance,
            "description": request_data.description,
            "dimensions": {
                "length": request_data.dimensions.length,
                "breadth": request_data.dimensions.breadth,
                "height": request_data.dimensions.height,
                "unit": request_data.dimensions.unit,
            },
            "weight_category": request_data.weight_category,
            "urgent": request_data.urgent,
            "estimated_cost": request_data.estimated_cost,
            "status": "pending",
            "created_at": current_time['ist'],
            "created_at_ist": current_time['ist_string'],
            "updated_at": current_time['ist'],
            "updated_at_ist": current_time['ist_string'],
            "assigned_partner_id": None,
            "assigned_partner_name": None,
            "actual_cost": None,
            "payment_status": "not_required",
            "payment_transaction_id": None,
            "admin_notes": None,
        }
        
        # Insert into database
        await db.insert_one("porter_requests", porter_request)
        
        # Create notification for user
        try:
            from app.routes.notifications import create_notification
            await create_notification(
                db=db,
                user_id=user_id,
                title="Porter Request Submitted 📦",
                message=f"Your porter request has been received. We'll send you the estimated cost within 15-30 minutes.",
                notification_type="porter",
                order_id=request_id
            )
        except Exception as notif_error:
            logger.error(f"Failed to create notification: {notif_error}")
        
        logger.info(f"Porter request created: {request_id} by user {user_email}")
        
        return {
            "message": "Porter request submitted successfully",
            "request_id": request_id,
            "status": "pending",
            "estimated_response_time": "15-30 minutes"
        }
        
    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Error creating porter request: {e}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create porter request"
        )

@router.get("/porter-requests/my-requests")
async def get_my_porter_requests(
    current_user = Depends(get_current_user)
):
    """Get all porter requests for the current user - NO CACHING for real-time status"""
    try:
        db = get_database()
        
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        user_id_obj = user_id if isinstance(user_id, str) else user_id
        
        # ✅ Always fetch fresh data - no caching for status updates
        requests = await db.find_many(
            "porter_requests",
            {"user_id": user_id_obj},
            sort=[("created_at", -1)]
        )
        
        serialized_requests = []
        for request in requests:
            serialized_request = {
                "_id": str(request["_id"]),
                "id": request.get("id", str(request["_id"])),
                "pickup_address": request.get("pickup_address", {}),
                "delivery_address": request.get("delivery_address", {}),
                "phone": request.get("phone"),
                "description": request.get("description"),
                "dimensions": request.get("dimensions"),
                "weight_category": request.get("weight_category"),
                "urgent": request.get("urgent", False),
                "status": request.get("status"),  # ✅ Always fresh
                "assigned_partner_name": request.get("assigned_partner_name"),
                "estimated_cost": request.get("estimated_cost"),
                "actual_cost": request.get("actual_cost"),
                "payment_status": request.get("payment_status", "not_required"),  # ✅ Always fresh
                "can_pay": request.get("estimated_cost") and request.get("payment_status") == "pending",
                "created_at": request["created_at"].isoformat() if request.get("created_at") else None,
                "updated_at": request.get("updated_at").isoformat() if request.get("updated_at") else None,
            }
            serialized_requests.append(serialized_request)
        
        logger.info(f"✅ Fetched {len(serialized_requests)} fresh porter requests for user {user_id}")
        
        return {
            "requests": serialized_requests,
            "total_count": len(serialized_requests)
        }
        
    except Exception as e:
        logger.error(f"Error fetching porter requests: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch porter requests"
        )

@router.get("/porter-requests/{request_id}")
async def get_porter_request_detail(
    request_id: str,
    current_user = Depends(get_current_user)
):
    """Get detailed information about a specific porter request"""
    try:
        if not ObjectId.is_valid(request_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request ID format"
            )
        
        db = get_database()
        
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        
        request = await db.find_one(
            "porter_requests",
            {"_id": ObjectId(request_id), "user_id": user_id}
        )
        
        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Porter request not found"
            )
        
        serialized_request = {
            "_id": str(request["_id"]),
            "id": request.get("id", str(request["_id"])),
            "pickup_address": request.get("pickup_address", {}),
            "delivery_address": request.get("delivery_address", {}),
            "phone": request.get("phone"),
            "description": request.get("description"),
            "dimensions": request.get("dimensions"),
            "weight_category": request.get("weight_category"),
            "urgent": request.get("urgent", False),
            "status": request.get("status"),
            "assigned_partner_name": request.get("assigned_partner_name"),
            "estimated_cost": request.get("estimated_cost"),
            "actual_cost": request.get("actual_cost"),
            "payment_status": request.get("payment_status", "not_required"),
            "can_pay": request.get("estimated_cost") and request.get("payment_status") == "pending",
            "admin_notes": request.get("admin_notes"),
            "created_at": request["created_at"].isoformat() if request.get("created_at") else None,
            "updated_at": request.get("updated_at").isoformat() if request.get("updated_at") else None,
        }
        
        return serialized_request
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching porter request: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch porter request"
        )

# ADMIN ENDPOINT - Update estimated cost
@router.put("/porter-requests/{request_id}/estimate")
async def update_estimated_cost(
    request_id: str,
    estimate_data: EstimateCostUpdate,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Admin endpoint to update estimated cost"""
    try:
        # Verify admin access (implement your admin check)
        # if not current_user.is_admin:
        #     raise HTTPException(status_code=403, detail="Admin access required")
        
        if not ObjectId.is_valid(request_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request ID"
            )
        
        request = await db.find_one(
            "porter_requests",
            {"_id": ObjectId(request_id)}
        )
        
        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Porter request not found"
            )
        
        current_time = get_ist_datetime_for_db()
        
        # Update request with estimated cost
        await db.update_one(
            "porter_requests",
            {"_id": ObjectId(request_id)},
            {
                "$set": {
                    "estimated_cost": estimate_data.estimated_cost,
                    "payment_status": "pending",
                    "admin_notes": estimate_data.admin_notes,
                    "updated_at": current_time['ist'],
                    "updated_at_ist": current_time['ist_string'],
                }
            }
        )
        
        # Send notification to user
        try:
            from app.routes.notifications import create_notification
            await create_notification(
                db=db,
                user_id=request["user_id"],
                title="Porter Cost Estimated 💰",
                message=f"Estimated cost for your porter request: ₹{estimate_data.estimated_cost:.2f}. Tap to view details and proceed with payment.",
                notification_type="porter_estimate",
                order_id=request_id
            )
        except Exception as notif_error:
            logger.error(f"Failed to create notification: {notif_error}")
        
        logger.info(f"Estimated cost updated for request {request_id}: ₹{estimate_data.estimated_cost}")
        
        return {
            "message": "Estimated cost updated successfully",
            "request_id": request_id,
            "estimated_cost": estimate_data.estimated_cost
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating estimated cost: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update estimated cost"
        )

# Payment for porter request
@router.post("/porter-requests/{request_id}/pay")
async def pay_porter_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    current_user = Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Initiate payment for porter request"""
    try:
        if not ObjectId.is_valid(request_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid request ID"
            )
        
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        
        request = await db.find_one(
            "porter_requests",
            {"_id": ObjectId(request_id), "user_id": user_id}
        )
        
        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Porter request not found"
            )
        
        if not request.get("estimated_cost"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Estimated cost not yet available"
            )
        
        if request.get("payment_status") == "completed":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Payment already completed"
            )
        
        # Initiate PhonePe payment
        try:
            from app.routes.orders import initiate_phonepe_payment_internal
            
            payment_result = await initiate_phonepe_payment_internal(
                order_id=request_id,
                amount=request["estimated_cost"],
                user=current_user,
                db=db,
                order=request
            )
            
            # Update porter request with payment details
            current_time = get_ist_datetime_for_db()
            await db.update_one(
                "porter_requests",
                {"_id": ObjectId(request_id)},
                {
                    "$set": {
                        "payment_transaction_id": payment_result.get("merchant_transaction_id"),
                        "payment_status": "pending",
                        "updated_at": current_time['ist'],
                        "updated_at_ist": current_time['ist_string'],
                    }
                }
            )
            
            logger.info(f"Payment initiated for porter request {request_id}")
            
            return {
                "success": True,
                "payment_url": payment_result.get("payment_url"),
                "merchant_transaction_id": payment_result.get("merchant_transaction_id"),
                "request_id": request_id
            }
            
        except Exception as payment_error:
            logger.error(f"Payment initiation failed: {payment_error}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Payment initiation failed: {str(payment_error)}"
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initiating payment: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate payment"
        )