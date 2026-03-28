from datetime import datetime
from fastapi import HTTPException

async def getPricing(db):
    return await db.find_one("pricing_config", {})
    
async def calculate_porter_price_backend(distance: float, dimensions: dict, weight, is_urgent, db) -> float:
    """Calculate porter service price — matches frontend formula: volumetricWeight * distance * porterFee"""
    pricing = await getPricing(db)
    porter_rate = pricing.get("porterFee", 100) if pricing else 100

    dim_map = {"<10": 10, "10-20": 20, "20-50": 50, "50+": 60}
    if dimensions:
        l = dim_map.get(str(dimensions.get("length", "<10")), 10)
        w = dim_map.get(str(dimensions.get("width", "<10")), 10)
        h = dim_map.get(str(dimensions.get("height", "<10")), 10)
    else:
        l, w, h = 10, 10, 10

    volume = l * w * h
    volumetric_weight = volume / 5000
    price = round(volumetric_weight * distance * porter_rate)

    if is_urgent:
        price += 20

    return float(price)

async def calculate_printout_price_backend(service_data: dict, db) -> float:
    """Calculate printout price — matches frontend formula using DB pricing config"""
    pricing = await getPricing(db)
    printout_config = pricing.get("printoutFee", {}) if pricing else {}

    copies = service_data['copies']
    pages = service_data['pages']
    color = service_data['color']
    paper_size = service_data['paper_size']
    print_type = service_data.get('print_type', 'document')

    if print_type == 'photo':
        photo_config = printout_config.get("photo", {})
        if paper_size == 'Passport':
            price_per = photo_config.get("passport", 10)
        else:
            price_per = photo_config.get("other", 15)
        return round(price_per * copies, 2)

    # Document printing
    doc_config = printout_config.get("doc", {})
    if paper_size == "A4":
        price_per_page = doc_config.get("A4_color" if color else "A4_black", 5 if color else 2)
    elif paper_size == "A3":
        price_per_page = doc_config.get("A3_color" if color else "A3_black", 10 if color else 4)
    elif paper_size == "Legal":
        price_per_page = doc_config.get("legal_color" if color else "legal_black", 7.5 if color else 3)
    else:
        price_per_page = doc_config.get("A4_color" if color else "A4_black", 5 if color else 2)

    return round(pages * copies * price_per_page, 2)

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
    
    # Apply max discount (admin saves as max_discount_amount)
    max_discount = promo.get("max_discount") or promo.get("max_discount_amount")
    if max_discount:
        discount = min(discount, max_discount)
    
    return round(discount, 2)