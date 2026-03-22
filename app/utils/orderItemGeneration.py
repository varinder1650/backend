from fastapi import HTTPException

from app.utils.verifyPricing import calculate_porter_price_backend, calculate_printout_price_backend

async def validateProductsItems(item: dict, db):
    product = await db.find_one("products", {"id": item['product_id']})
    if not product:
        raise HTTPException(400, f"Product {item['product_id']} not found")
    
    if product.get("stock", 0) < item['quantity']:
        raise HTTPException(400, f"Insufficient stock for {product['name']}")
    
    item_total = product["selling_price"] * item['quantity']
    
    validated_item = {
        "type": "product",
        "product_id": item['product_id'],
        "quantity": item['quantity'],
        "price": product["selling_price"],
        "subtotal": item_total
    }
    
    return validated_item, item_total

async def validatePorterItems(item: dict, db):
    service_data = item['service_data']
    distance = service_data['estimated_distance']
    porter_price = await calculate_porter_price_backend(
        distance,
        service_data['dimensions'],
        service_data['weight_category'],
        service_data['is_urgent'],
        db
    )

    validated_item = {
        "type": "porter",
        "service_data": service_data,
        "price": porter_price
    }

    return validated_item, porter_price

async def validatePrintItems(item: dict, db):
    service_data = item['service_data']
    printout_price = await calculate_printout_price_backend(service_data, db)

    validated_item = {
        "type": "printout",
        "service_data": service_data,
        "price": printout_price
    }

    return validated_item, printout_price