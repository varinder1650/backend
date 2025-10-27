# app/routes/porter.py - FIXED VERSION
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, validator
from typing import Optional
from datetime import datetime
from bson import ObjectId
from db.db_manager import get_database
from app.utils.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

class Address(BaseModel):
    address: str = Field(..., min_length=10, max_length=300)
    city: str = Field(..., min_length=2, max_length=50)
    pincode: str = Field(..., min_length=6, max_length=6)
    
    @validator('pincode')
    def validate_pincode(cls, v):
        if not v.isdigit():
            raise ValueError('Pincode must contain only digits')
        return v

class PorterRequestCreate(BaseModel):
    pickup_address: Address
    delivery_address: Address
    phone: str = Field(..., min_length=10, max_length=15)
    description: str = Field(..., min_length=10, max_length=500)
    estimated_distance: Optional[float] = Field(None, gt=0, le=100)
    package_size: str = Field(default="small")
    urgent: bool = Field(default=False)
    
    @validator('package_size')
    def validate_package_size(cls, v):
        if v not in ['small', 'medium', 'large']:
            raise ValueError('Package size must be small, medium, or large')
        return v
    
    @validator('phone')
    def validate_phone(cls, v):
        cleaned = v.replace(' ', '').replace('-', '')
        if not cleaned.replace('+', '').isdigit():
            raise ValueError('Phone number must contain only digits, spaces, dashes, or + symbol')
        return v

@router.post("/porter-requests")
async def create_porter_request(
    request_data: PorterRequestCreate,
    current_user = Depends(get_current_user)
):
    """Create a new porter delivery request"""
    try:
        db = get_database()
        
        # ✅ FIX: Access object attributes directly, not as dictionary
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        user_name = current_user.name if hasattr(current_user, 'name') else "Unknown"
        user_email = current_user.email if hasattr(current_user, 'email') else "Unknown"
        user_phone = current_user.phone if hasattr(current_user, 'phone') else "Not provided"
        
        # Prepare porter request document
        porter_request = {
            "_id": ObjectId(),
            "user_id": user_id if isinstance(user_id, str) else user_id,
            "user_name": user_name,
            "user_email": user_email,
            "user_phone": user_phone,
            "pickup_address": {
                "address": request_data.pickup_address.address,
                "city": request_data.pickup_address.city,
                "pincode": request_data.pickup_address.pincode,
            },
            "delivery_address": {
                "address": request_data.delivery_address.address,
                "city": request_data.delivery_address.city,
                "pincode": request_data.delivery_address.pincode,
            },
            "phone": request_data.phone,
            "description": request_data.description,
            "estimated_distance": request_data.estimated_distance,
            "package_size": request_data.package_size,
            "urgent": request_data.urgent,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
            "assigned_partner_id": None,
            "assigned_partner_name": None,
            "estimated_cost": None,
            "actual_cost": None,
            "admin_notes": None,
        }
        
        # Insert into database
        await db.insert_one("porter_requests", porter_request)
        
        logger.info(f"Porter request created: {porter_request['_id']} by user {user_email}")
        
        return {
            "message": "Porter request submitted successfully",
            "request_id": str(porter_request["_id"]),
            "status": "pending",
            "estimated_response_time": "15-30 minutes"
        }
        
    except ValueError as ve:
        logger.error(f"Validation error creating porter request: {ve}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Error creating porter request: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create porter request"
        )

@router.get("/porter-requests/my-requests")
async def get_my_porter_requests(
    current_user = Depends(get_current_user)
):
    """Get all porter requests for the current user"""
    try:
        db = get_database()
        
        # ✅ FIX: Access object attributes directly
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        user_id_obj = user_id if isinstance(user_id, str) else user_id
        
        # Find user's porter requests
        requests = await db.find_many(
            "porter_requests",
            {"user_id": user_id_obj},
            sort=[("created_at", -1)]
        )
        
        # Serialize requests
        serialized_requests = []
        for request in requests:
            serialized_request = {
                "_id": str(request["_id"]),
                "id": str(request["_id"]),
                "pickup_address": request.get("pickup_address", {}),
                "delivery_address": request.get("delivery_address", {}),
                "phone": request.get("phone"),
                "description": request.get("description"),
                "estimated_distance": request.get("estimated_distance"),
                "package_size": request.get("package_size"),
                "urgent": request.get("urgent", False),
                "status": request.get("status"),
                "assigned_partner_name": request.get("assigned_partner_name"),
                "estimated_cost": request.get("estimated_cost"),
                "actual_cost": request.get("actual_cost"),
                "created_at": request["created_at"].isoformat() if request.get("created_at") else None,
                "updated_at": request.get("updated_at").isoformat() if request.get("updated_at") else None,
            }
            serialized_requests.append(serialized_request)
        
        return {
            "requests": serialized_requests,
            "total_count": len(serialized_requests)
        }
        
    except Exception as e:
        logger.error(f"Error fetching user's porter requests: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
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
        
        # ✅ FIX: Access object attributes directly
        user_id = current_user.id if hasattr(current_user, 'id') else current_user.id
        user_id_obj = user_id if isinstance(user_id, str) else user_id
        
        # Find porter request
        request = await db.find_one(
            "porter_requests",
            {"_id": ObjectId(request_id), "user_id": user_id_obj}
        )
        
        if not request:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Porter request not found"
            )
        
        # Serialize request
        serialized_request = {
            "_id": str(request["_id"]),
            "id": str(request["_id"]),
            "pickup_address": request.get("pickup_address", {}),
            "delivery_address": request.get("delivery_address", {}),
            "phone": request.get("phone"),
            "description": request.get("description"),
            "estimated_distance": request.get("estimated_distance"),
            "package_size": request.get("package_size"),
            "urgent": request.get("urgent", False),
            "status": request.get("status"),
            "assigned_partner_name": request.get("assigned_partner_name"),
            "estimated_cost": request.get("estimated_cost"),
            "actual_cost": request.get("actual_cost"),
            "admin_notes": request.get("admin_notes"),
            "created_at": request["created_at"].isoformat() if request.get("created_at") else None,
            "updated_at": request.get("updated_at").isoformat() if request.get("updated_at") else None,
        }
        
        return serialized_request
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching porter request detail: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch porter request detail"
        )