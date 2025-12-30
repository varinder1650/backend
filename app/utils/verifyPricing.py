from datetime import datetime
from fastapi import HTTPException

async def getPricing(db):
    return await db.find_one("pricing_config", {})
    
def calculate_porter_price_backend(distance: float, dimensions: dict,weight,is_urgent) -> float:
    """Calculate porter service price on backend"""
    base_price = 30
    per_km = 10
    
    size_multiplier = 1.0
    if dimensions:
        size_multiplier = 1.2
    
    try:
        weight_value = float(weight)
    except (ValueError, TypeError):
        weight_value = 1.0

    price = base_price + (distance * per_km * size_multiplier * weight_value)
    if is_urgent:
        price = price+20
    return round(price, 2)

def calculate_printout_price_backend(service_data: dict) -> float:
    copies = service_data['copies']
    pages = service_data['pages']
    color = service_data['color']
    paper_size = service_data['paper_size']    
    
    base_price = 2 if not color else 5
    
    if paper_size == "A3":
        base_price *= 2
    elif paper_size == "Legal":
        base_price *= 1.5
    
    total = base_price * copies * pages
    return round(total, 2)

async def calculateDeliveryFee(db, subtotal):
    pricing = await getPricing(db)
    
    if not pricing:
        return 20
    
    delivery_config = pricing.get("delivery_fee", {})
    
    if subtotal >= delivery_config.get("free_delivery_threshold", 50):
        return 0
    else:
        return max(
            delivery_config.get("base_fee", 20),
            delivery_config.get("min_fee", 10)
        )

async def calculateDiscount(db, promocode, subtotal):
    if not promocode:
        return 0
    
    promo = await db.find_one("discount_coupons", {
        "code": promocode,
        "is_active": True
    })
    
    if not promo:
        return 0
    
    # Check expiry
    if promo.get("expiry_date") and datetime.now() > promo["expiry_date"]:
        raise HTTPException(400, "Promo code expired")
    
    # Check min order
    if promo.get("min_order_amount", 0) > subtotal:
        raise HTTPException(400, f"Minimum order of ₹{promo['min_order_amount']} required")
    
    # Calculate discount
    if promo.get("discount_type") == "percentage":
        discount = (subtotal * promo.get("discount_value", 0)) / 100
    else:
        discount = promo.get("discount_value", 0)
    
    # Apply max discount
    if promo.get("max_discount"):
        discount = min(discount, promo["max_discount"])
    
    return round(discount, 2)