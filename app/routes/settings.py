from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import logging
import os
import httpx
import cloudinary
import cloudinary.uploader
from db.db_manager import DatabaseManager, get_database
from app.utils.auth import current_active_user
from app.utils.verify_pricing import getPricing
from schema.user import UserinDB

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
)

MAX_PRINTOUT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

ALLOWED_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
}

logger = logging.getLogger(__name__)
router = APIRouter()

OLA_API_KEY = os.getenv('OLA_KRUTRIM_API_KEY')


class DistanceRequest(BaseModel):
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float


@router.post("/estimate-distance")
async def estimate_distance(req: DistanceRequest):
    """Calculate driving distance between two coordinates using Ola Maps Directions API"""
    if not OLA_API_KEY:
        raise HTTPException(status_code=500, detail="Ola Maps API key not configured")

    try:
        url = (
            f"https://api.olamaps.io/routing/v1/directions"
            f"?origin={req.origin_lat},{req.origin_lng}"
            f"&destination={req.dest_lat},{req.dest_lng}"
            f"&api_key={OLA_API_KEY}"
        )

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(url)

        if response.status_code != 200:
            logger.error(f"Ola Maps Directions API error: {response.status_code} {response.text}")
            raise HTTPException(status_code=502, detail="Failed to calculate distance")

        data = response.json()
        routes = data.get("routes", [])
        if not routes:
            raise HTTPException(status_code=404, detail="No route found between these locations")

        # Distance in meters → km, duration in seconds → minutes
        leg = routes[0].get("legs", [{}])[0]
        distance_km = round(leg.get("distance", 0) / 1000, 1)
        duration_min = round(leg.get("duration", 0) / 60)

        return {
            "distance_km": distance_km,
            "duration_min": duration_min,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Distance estimation error: {e}")
        raise HTTPException(status_code=500, detail="Failed to estimate distance")


class PorterPriceRequest(BaseModel):
    distance: float
    length: str = "<10"
    width: str = "<10"
    height: str = "<10"
    is_urgent: bool = False


class PrintoutPriceRequest(BaseModel):
    print_type: str = "document"
    copies: int = 1
    pages: int = 1
    color: bool = False
    paper_size: str = "A4"


@router.post("/estimate-porter-price")
async def estimate_porter_price(req: PorterPriceRequest, db: DatabaseManager = Depends(get_database)):
    """Calculate porter price using backend pricing config — single source of truth"""
    pricing = await getPricing(db)
    porter_rate = pricing.get("porterFee", 100) if pricing else 100

    dim_map = {"<10": 10, "10-20": 20, "20-50": 50, "50+": 60}
    l = dim_map.get(req.length, 10)
    w = dim_map.get(req.width, 10)
    h = dim_map.get(req.height, 10)

    volume = l * w * h
    volumetric_weight = volume / 5000
    price = round(volumetric_weight * req.distance * porter_rate)

    if req.is_urgent:
        price += 20

    return {"price": price}


@router.post("/estimate-printout-price")
async def estimate_printout_price(req: PrintoutPriceRequest, db: DatabaseManager = Depends(get_database)):
    """Calculate printout price using backend pricing config — single source of truth"""
    pricing = await getPricing(db)
    printout_config = pricing.get("printoutFee", {}) if pricing else {}

    if req.print_type == "photo":
        photo_config = printout_config.get("photo", {})
        price_per = photo_config.get("passport", 10) if req.paper_size == "Passport" else photo_config.get("other", 15)
        return {"price": round(price_per * req.copies, 2)}

    doc_config = printout_config.get("doc", {})
    if req.paper_size == "A4":
        price_per_page = doc_config.get("A4_color" if req.color else "A4_black", 5 if req.color else 2)
    elif req.paper_size == "A3":
        price_per_page = doc_config.get("A3_color" if req.color else "A3_black", 10 if req.color else 4)
    elif req.paper_size == "Legal":
        price_per_page = doc_config.get("legal_color" if req.color else "legal_black", 7.5 if req.color else 3)
    else:
        price_per_page = doc_config.get("A4_color" if req.color else "A4_black", 5 if req.color else 2)

    return {"price": round(req.pages * req.copies * price_per_page, 2)}

@router.get("/public")
async def get_public_settings(db: DatabaseManager = Depends(get_database)):
    """Get public app settings"""
    try:
        # Get app settings from database
        settings = await db.find_one("pricing_config", {})
        # print(settings)
        if not settings:
            # Return default settings if none exist
            default_settings = {
                "app_name": "SmartBag",
                "app_version": "1.0.0",
                "currency": "USD",
                "tax_rate": 0.08,
                "shipping_fee": 5.00,
                "free_shipping_threshold": 50.00,
                "contact_email": "support@smartbag.com",
                "contact_phone": "+1234567890",
                "social_media": {
                    "facebook": "",
                    "instagram": "",
                    "twitter": ""
                },
                "payment_methods": ["card", "paypal", "apple_pay"],
                "delivery_areas": ["City Center", "Suburbs", "Downtown"]
            }
            return default_settings
        
        settings.pop("_id", None)
        return settings

    except Exception as e:
        logger.error(f"Get public settings error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get app settings"
        )


@router.post("/upload-printout-file")
async def upload_printout_file(
    file: UploadFile = File(...),
    current_user: UserinDB = Depends(current_active_user),
):
    """Upload a document or image for the printout service. Max file size: 10 MB."""
    allowed_types = ALLOWED_DOCUMENT_TYPES | ALLOWED_IMAGE_TYPES
    content_type = file.content_type or ""

    if content_type not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{content_type}'. Allowed: PDF, DOC, DOCX, JPEG, PNG, WEBP.",
        )

    contents = await file.read()

    if len(contents) > MAX_PRINTOUT_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File exceeds the 10 MB size limit.",
        )

    is_photo = content_type in ALLOWED_IMAGE_TYPES
    folder = "smartbag/printouts/photos" if is_photo else "smartbag/printouts/documents"
    resource_type = "image" if is_photo else "raw"

    try:
        result = cloudinary.uploader.upload(
            contents,
            folder=folder,
            resource_type=resource_type,
            use_filename=True,
            unique_filename=True,
        )
    except Exception as e:
        logger.error(f"Cloudinary upload error: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="File upload failed. Please try again.",
        )

    return {
        "url": result.get("secure_url"),
        "type": "photo" if is_photo else "document",
    }