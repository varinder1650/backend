from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
import logging
from typing import List
from app.utils.get_time import add_ist_timestamps, now_utc  # ✅ Import timezone utility
from app.utils.auth import get_current_user
from db.db_manager import DatabaseManager, get_database
from schema.address import AddressCreate, AddressUpdate, AddressResponse, GeocodeRequest, ReverseGeocodeRequest, AddressSearchRequest
from app.utils.mongo import fix_mongo_types
from typing import List, Optional
import os
from dotenv import load_dotenv
import httpx

logger = logging.getLogger(__name__)
router = APIRouter()

MAX_ADDRESSES_PER_USER = 5

load_dotenv()

OLA_API_KEY = os.getenv('OLA_KRUTRIM_API_KEY')
OLA_BASE_URL = os.getenv('OLA_BASE_URL')

# ✅ Helper function to geocode address and get coordinates
async def get_coordinates_from_address(street: str, city: str, state: str, pincode: str) -> tuple[Optional[float], Optional[float]]:
    """
    Geocode an address to get latitude and longitude
    Returns: (latitude, longitude) or (None, None) if failed
    """
    try:
        # Build full address string
        full_address = f"{street}, {city}"
        if state:
            full_address += f", {state}"
        if pincode:
            full_address += f", {pincode}"
        full_address += ", India"
        
        logger.info(f"🗺️ Geocoding address: {full_address}")
        
        url = f"{OLA_BASE_URL}/geocode"
        params = {
            'address': full_address,
            'api_key': OLA_API_KEY
        }
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('geocodingResults') and len(data['geocodingResults']) > 0:
                    result = data['geocodingResults'][0]
                    location = result.get('geometry', {}).get('location', {})
                    
                    lat = location.get('lat')
                    lng = location.get('lng')
                    
                    if lat and lng:
                        logger.info(f"✅ Coordinates found: {lat}, {lng}")
                        return (lat, lng)
                    
        logger.warning(f"⚠️ Could not geocode address: {full_address}")
        return (None, None)
        
    except Exception as e:
        logger.error(f"❌ Geocoding error: {e}")
        return (None, None)


@router.post("/", response_model=AddressResponse)
async def create_address(
    address_data: AddressCreate,
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Create a new address for the user with automatic geocoding"""
    try:
        # Validate mobile number format
        if not address_data.mobile_number.isdigit() or len(address_data.mobile_number) != 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Mobile number must be exactly 10 digits"
            )
        
        # Check address limit
        user_addresses_count = await db.count_documents("user_addresses", {
            "user_id": current_user.id
        })
        
        if user_addresses_count >= MAX_ADDRESSES_PER_USER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Maximum {MAX_ADDRESSES_PER_USER} addresses allowed. Please delete an existing address first."
            )
        
        # Check if this is the first address for the user
        is_default = user_addresses_count == 0  # First address becomes default
        
        address_doc = address_data.dict()
        address_doc["user_id"] = current_user.id
        address_doc["is_default"] = is_default
        
        # ✅ If coordinates are not provided or are (0, 0), geocode the address automatically
        lat = address_data.latitude
        lng = address_data.longitude
        
        if not lat or not lng or (lat == 0 and lng == 0):
            logger.info("🔍 No coordinates provided, attempting to geocode address...")
            lat, lng = await get_coordinates_from_address(
                address_data.street,
                address_data.city,
                address_data.state or "",
                address_data.pincode
            )
            
            if lat and lng:
                address_doc["latitude"] = lat
                address_doc["longitude"] = lng
                logger.info(f"✅ Address geocoded successfully: {lat}, {lng}")
            else:
                # Set to None if geocoding failed
                address_doc["latitude"] = None
                address_doc["longitude"] = None
                logger.warning("⚠️ Geocoding failed, saving address without coordinates")
        else:
            address_doc["latitude"] = lat
            address_doc["longitude"] = lng
            logger.info(f"📍 Using provided coordinates: {lat}, {lng}")
        
        # ✅ Add IST timestamps
        add_ist_timestamps(address_doc, created=True, updated=True)
        
        address_id = await db.insert_one("user_addresses", address_doc)
        
        # Get the created address
        created_address = await db.find_one("user_addresses", {"_id": ObjectId(address_id)})
        fixed_address = fix_mongo_types(created_address)
        
        logger.info(f"✅ Address created successfully for user {current_user.email}")
        return AddressResponse(**fixed_address)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create address error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create address"
        )


@router.get("/my", response_model=List[AddressResponse])
async def get_user_addresses(
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Get all addresses for the user"""
    try:
        addresses = await db.find_many(
            "user_addresses",
            {"user_id": current_user.id},
            sort=[("is_default", -1), ("created_at", -1)]  # Default first, then by creation date
        )
        
        fixed_addresses = [fix_mongo_types(address) for address in addresses]
        return [AddressResponse(**address) for address in fixed_addresses]
        
    except Exception as e:
        logger.error(f"Get addresses error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get addresses"
        )


@router.post("/{address_id}/set-default")
async def set_default_address(
    address_id: str,
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Set an address as the default"""
    try:
        if not ObjectId.is_valid(address_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid address ID"
            )
        
        # Check if address belongs to user
        existing_address = await db.find_one("user_addresses", {
            "_id": ObjectId(address_id),
            "user_id": current_user.id
        })
        
        if not existing_address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )
        
        # Remove default from all user addresses
        await db.update_many(
            "user_addresses",
            {"user_id": current_user.id},
            {"$set": {"is_default": False, "updated_at": now_utc()}}  # ✅ Use timezone utility
        )
        
        # Set this address as default
        await db.update_one(
            "user_addresses",
            {"_id": ObjectId(address_id)},
            {"$set": {"is_default": True, "updated_at": now_utc()}}  # ✅ Use timezone utility
        )
        
        logger.info(f"Address {address_id} set as default")
        return {"message": "Default address updated successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set default address error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to set default address"
        )


@router.put("/{address_id}", response_model=AddressResponse)
async def update_address(
    address_id: str,
    address_data: AddressUpdate,
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Update an address with automatic geocoding if address changed"""
    try:
        if not ObjectId.is_valid(address_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid address ID"
            )
        
        # Check if address belongs to user
        existing_address = await db.find_one("user_addresses", {
            "_id": ObjectId(address_id),
            "user_id": current_user.id
        })
        
        if not existing_address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )
        
        # Validate mobile number format if provided
        if address_data.mobile_number is not None:
            if not address_data.mobile_number.isdigit() or len(address_data.mobile_number) != 10:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Mobile number must be exactly 10 digits"
                )
        
        # Prepare update data
        update_data = {}
        for field, value in address_data.dict(exclude_unset=True).items():
            if value is not None:
                update_data[field] = value
        
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update"
            )
        
        # ✅ Check if address fields changed - if so, re-geocode
        address_changed = any(
            field in update_data 
            for field in ['street', 'city', 'state', 'pincode']
        )
        
        if address_changed:
            logger.info("📍 Address changed, re-geocoding...")
            
            # Get updated address components
            street = update_data.get('street', existing_address.get('street'))
            city = update_data.get('city', existing_address.get('city'))
            state = update_data.get('state', existing_address.get('state', ''))
            pincode = update_data.get('pincode', existing_address.get('pincode'))
            
            # Re-geocode
            lat, lng = await get_coordinates_from_address(street, city, state, pincode)
            
            if lat and lng:
                update_data["latitude"] = lat
                update_data["longitude"] = lng
                logger.info(f"✅ Address re-geocoded: {lat}, {lng}")
            else:
                logger.warning("⚠️ Re-geocoding failed, keeping existing coordinates")
        
        update_data["updated_at"] = now_utc()  # ✅ Use timezone utility
        
        # Update the address
        await db.update_one(
            "user_addresses",
            {"_id": ObjectId(address_id)},
            {"$set": update_data}
        )
        
        # Get the updated address
        updated_address = await db.find_one("user_addresses", {"_id": ObjectId(address_id)})
        fixed_address = fix_mongo_types(updated_address)
        
        logger.info(f"Address {address_id} updated successfully for user {current_user.email}")
        return AddressResponse(**fixed_address)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Update address error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update address"
        )


@router.delete("/{address_id}")
async def delete_address(
    address_id: str,
    current_user=Depends(get_current_user),
    db: DatabaseManager = Depends(get_database)
):
    """Delete an address"""
    try:
        if not ObjectId.is_valid(address_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid address ID"
            )
        
        # Check if address belongs to user
        existing_address = await db.find_one("user_addresses", {
            "_id": ObjectId(address_id),
            "user_id": current_user.id
        })
        
        if not existing_address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )
        
        # If deleting default address, make another address default
        if existing_address.get("is_default"):
            other_address = await db.find_one("user_addresses", {
                "user_id": current_user.id,
                "_id": {"$ne": ObjectId(address_id)}
            })
            
            if other_address:
                await db.update_one(
                    "user_addresses",
                    {"_id": other_address["_id"]},
                    {"$set": {"is_default": True, "updated_at": now_utc()}}  # ✅ Use timezone utility
                )

        await db.delete_one("user_addresses", {"_id": ObjectId(address_id)})
        
        logger.info(f"Address {address_id} deleted successfully")
        return {"message": "Address deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete address error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete address"
        )


@router.post("/search-addresses")
async def search_addresses_proxy(request: AddressSearchRequest):
    """Proxy for Ola Maps address search"""
    try:
        if not request.query or len(request.query.strip()) < 3:
            return {"predictions": []}
        
        url = f"{OLA_BASE_URL}/autocomplete"
        params = {
            'input': request.query.strip(),
            'api_key': OLA_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                return {"predictions": data.get("predictions", [])}
            else:
                logger.error(f"Ola Maps search error: {response.status_code}")
                return {"predictions": []}
                
    except Exception as e:
        logger.error(f"Address search proxy error: {e}")
        return {"predictions": []}


@router.post("/geocode")
async def geocode_address(request: GeocodeRequest):
    """Proxy for Ola Maps geocoding"""
    try:
        url = f"{OLA_BASE_URL}/geocode"
        params = {
            'address': request.address,
            'api_key': OLA_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                
                if data.get('geocodingResults') and len(data['geocodingResults']) > 0:
                    result = data['geocodingResults'][0]
                    location = result.get('geometry', {}).get('location', {})
                    
                    return {
                        'latitude': location.get('lat'),
                        'longitude': location.get('lng'),
                        'formatted_address': result.get('formatted_address'),
                        'place_id': result.get('place_id')
                    }
        
        raise HTTPException(status_code=404, detail="Address not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Geocode proxy error: {e}")
        raise HTTPException(status_code=500, detail="Geocoding failed")


@router.post("/reverse-geocode")
async def reverse_geocode_proxy(request: ReverseGeocodeRequest):
    """Proxy for Ola Maps reverse geocoding"""
    try:
        url = f"{OLA_BASE_URL}/reverse-geocode"
        params = {
            'latlng': f"{request.latitude},{request.longitude}",
            'api_key': OLA_API_KEY
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('results') and len(data['results']) > 0:
                    address_result = data['results'][0]
                    
                    return {
                        'formatted_address': address_result.get('formatted_address'),
                        'address_components': address_result.get('address_components', []),
                        'latitude': request.latitude,
                        'longitude': request.longitude
                    }
        
        raise HTTPException(status_code=404, detail="Address not found")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reverse geocode proxy error: {e}")
        raise HTTPException(status_code=500, detail="Reverse geocoding failed")