# from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
# from typing import List
# from datetime import datetime
# import uuid
# import logging
# import os

# from pydantic import BaseModel
# from starlette.background import BackgroundTask

# from db.db_manager import DatabaseManager, get_database
# from app.utils.auth import current_active_user
# from app.cache.redis_manager import get_redis
# from app.cache.cache_config import CacheTTL, CacheKeys
# from app.services.inventory_service import get_inventory_service
# from app.utils.validators import InputValidator
# from schema.cart import CartRequest, UpdateCartItemRequest
# from schema.user import UserinDB

# logger = logging.getLogger(__name__)
# router = APIRouter()

# # ----------------- Helpers -----------------

# async def invalidate_cart_cache(user_id: str):
#     try:
#         redis = get_redis()
#         cache_key = CacheKeys.user_cart(user_id)
#         await redis.delete(cache_key)
#         logger.info(f"🗑️ Invalidated cart cache for user {user_id}")
#     except Exception as e:
#         logger.warning(f"⚠️ Cart cache invalidation error: {e}")

# def process_product_images(product: dict) -> List[str]:
#     images = product.get("images", [])
#     processed = []
#     if isinstance(images, list):
#         for img in images:
#             if isinstance(img, dict):
#                 url = img.get("url") or img.get("secure_url") or img.get("original")
#                 if url: processed.append(url)
#             elif isinstance(img, str) and img.strip():
#                 processed.append(img)
#     elif isinstance(images, str) and images.strip():
#         processed.append(images)
#     return processed

# async def get_cart_or_create(db: DatabaseManager, user_id: str):
#     cart = await db.find_one("carts", {"user": user_id})
#     if not cart:
#         cart_data = {
#             "user": user_id,
#             "items": [],
#             "created_at": datetime.utcnow(),
#             "updated_at": datetime.utcnow()
#         }
#         await db.insert_one("carts", cart_data)
#         return cart_data
#     return cart

# # ----------------- Routes -----------------

# @router.post("/add", status_code=201)
# async def add_to_cart(
#     req: CartRequest,
#     background_tasks: BackgroundTasks,
#     current_user: UserinDB = Depends(current_active_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     print(req)
#     if not req.productId or not InputValidator.validate_custom_id(req.productId):
#         raise HTTPException(status_code=400, detail="Invalid product ID")
#     max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
#     if not InputValidator.validate_quantity(req.quantity, max_qty):
#         raise HTTPException(status_code=400, detail=f"Quantity must be between 1 and {max_qty}")

#     try:
#         # Real-time stock check
#         product = await db.find_one("products", {"id": req.productId, "is_active": True})
#         if not product:
#             raise HTTPException(status_code=404, detail="Product not found or inactive")
#         if product.get("stock", 0) < req.quantity:
#             raise HTTPException(status_code=400, detail=f"Only {product.get('stock',0)} available")

#         cart = await get_cart_or_create(db, current_user.id)

#         existing_item = next((i for i in cart["items"] if i["product"] == req.productId), None)
#         if existing_item:
#             new_qty = existing_item["quantity"] + req.quantity
#             if product.get("stock", 0) < new_qty:
#                 raise HTTPException(status_code=400, detail=f"Cannot add {req.quantity}. Only {product.get('stock',0)-existing_item['quantity']} more available")
#             existing_item["quantity"] = new_qty
#             existing_item["updated_at"] = datetime.utcnow()
#         else:
#             cart["items"].append({
#                 "_id": str(uuid.uuid4()),
#                 "product": req.productId,
#                 "quantity": req.quantity,
#                 "added_at": datetime.utcnow(),
#                 "updated_at": datetime.utcnow()
#             })

#         cart["updated_at"] = datetime.utcnow()
#         # print("add cart: ",cart)
#         await db.update_one("carts", {"user": current_user.id}, {"$set": cart})

#         background_tasks.add_task(invalidate_cart_cache, current_user.id)

#         return {"message": "Product added to cart", "cart_item": cart["items"][-1] if not existing_item else existing_item}

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ Add to cart error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to add to cart")


# @router.post("/batch-add")
# async def batch_add_to_cart(
#     items: List[CartRequest],
#     background_tasks: BackgroundTasks,
#     current_user: UserinDB = Depends(current_active_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     if not items:
#         raise HTTPException(status_code=400, detail="No items provided")
#     if len(items) > 10:
#         raise HTTPException(status_code=400, detail="Maximum 10 items per batch")

#     try:
#         product_ids = [i.productId for i in items]
#         products = await db.find_many("products", {"id": {"$in": product_ids}, "is_active": True})
#         product_map = {p["id"]: p for p in products}

#         stock_errors = []
#         for i in items:
#             product = product_map.get(i.productId)
#             if not product: stock_errors.append(f"Product {i.productId} not found")
#             elif product.get("stock",0) < i.quantity: stock_errors.append(f"{product['name']}: only {product.get('stock',0)} available")
#         if stock_errors: raise HTTPException(status_code=400, detail={"errors": stock_errors})

#         cart = await get_cart_or_create(db, current_user.id)

#         for i in items:
#             existing_item = next((it for it in cart["items"] if it["product"]==i.productId), None)
#             if existing_item:
#                 existing_item["quantity"] += i.quantity
#                 existing_item["updated_at"] = datetime.utcnow()
#             else:
#                 cart["items"].append({
#                     "_id": str(uuid.uuid4()),
#                     "product": i.productId,
#                     "quantity": i.quantity,
#                     "added_at": datetime.utcnow(),
#                     "updated_at": datetime.utcnow()
#                 })
#         cart["updated_at"] = datetime.utcnow()
#         await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
#         background_tasks.add_task(invalidate_cart_cache, current_user.id)

#         return {"message": f"{len(items)} items added", "items": cart["items"]}

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ Batch add error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to add items to cart")


# @router.get("/")
# async def get_cart(current_user: UserinDB = Depends(current_active_user), db: DatabaseManager = Depends(get_database)):
#     try:
#         redis = get_redis()
#         cache_key = CacheKeys.user_cart(current_user.id)
#         cached = await redis.get(cache_key)
#         if cached: return cached

#         cart = await get_cart_or_create(db, current_user.id)

#         product_ids = [item["product"] for item in cart["items"]]
#         products = await db.find_many("products", {"id": {"$in": product_ids}, "is_active": True})
#         product_map = {p["id"]: p for p in products}

#         items_with_product = []
#         total_price = 0
#         total_items = 0
#         inventory_service = get_inventory_service()

#         for item in cart["items"]:
#             product = product_map.get(item["product"])
#             if not product: continue
#             try:
#                 stock = await inventory_service.get_available_stock(product["id"])
#             except Exception:
#                 stock = product.get("stock",0)
#             item_total = product.get("price",0) * item["quantity"]
#             total_price += item_total
#             total_items += item["quantity"]
#             items_with_product.append({
#                 "id": item["_id"],
#                 "product": {**product, "images": process_product_images(product)},
#                 "quantity": item["quantity"],
#                 "available_stock": stock,
#                 "stock_sufficient": stock >= item["quantity"],
#                 "item_total": item_total,
#                 "added_at": item.get("added_at"),
#                 "updated_at": item.get("updated_at")
#             })

#         response = {"items": items_with_product, "total_items": total_items, "total_price": total_price}
#         await redis.set(cache_key, response, CacheTTL.CART)
#         print(response)
#         return response

#     except Exception as e:
#         logger.error(f"❌ Get cart error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to fetch cart")


# @router.put("/update")
# async def update_cart_item(req: UpdateCartItemRequest, background_tasks: BackgroundTasks, current_user: UserinDB = Depends(current_active_user), db: DatabaseManager = Depends(get_database)):
#     try:
#         max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
#         if not InputValidator.validate_quantity(req.quantity, max_qty):
#             raise HTTPException(status_code=400, detail=f"Quantity must be between 1 and {max_qty}")

#         cart = await get_cart_or_create(db, current_user.id)
#         item = next((i for i in cart["items"] if i["product"]==req.itemId), None)
#         if not item: raise HTTPException(status_code=404, detail="Item not found in cart")

#         product = await db.find_one("products", {"id": item["product"], "is_active": True})
#         if not product: raise HTTPException(status_code=404, detail="Product not found or inactive")
#         if product.get("stock",0) < req.quantity: raise HTTPException(status_code=400, detail=f"Only {product['stock']} items available")

#         item["quantity"] = req.quantity
#         item["updated_at"] = datetime.utcnow()
#         cart["updated_at"] = datetime.utcnow()
#         await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
#         background_tasks.add_task(invalidate_cart_cache, current_user.id)
#         return {"message": "Cart item updated", "item_id": item["_id"], "quantity": item["quantity"]}

#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ Update cart error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to update cart")


# class RemoveItem(BaseModel):
#     itemId: str

# @router.delete("/remove")
# async def remove_cart_item(
#     background_tasks: BackgroundTasks,
#     payload: RemoveItem,
#     current_user: UserinDB = Depends(current_active_user),
#     db: DatabaseManager = Depends(get_database)
# ):
#     try:
#         cart = await get_cart_or_create(db, current_user.id)
#         original_len = len(cart["items"])
#         cart["items"] = [i for i in cart["items"] if i["product"] != payload.itemId]
#         if len(cart["items"]) == original_len: raise HTTPException(status_code=404, detail="Item not found")
#         cart["updated_at"] = datetime.utcnow()
#         await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
#         background_tasks.add_task(invalidate_cart_cache, current_user.id)
#         return {"message": "Item removed", "item_id": payload.itemId}
#     except HTTPException:
#         raise
#     except Exception as e:
#         logger.error(f"❌ Remove item error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to remove item")


# @router.delete("/clear")
# async def clear_cart(background_tasks: BackgroundTasks, current_user: UserinDB = Depends(current_active_user), db: DatabaseManager = Depends(get_database)):
#     try:
#         cart = await get_cart_or_create(db, current_user.id)
#         cart["items"] = []
#         cart["updated_at"] = datetime.utcnow()
#         await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
#         background_tasks.add_task(invalidate_cart_cache, current_user.id)
#         return {"message": "Cart cleared successfully"}
#     except Exception as e:
#         logger.error(f"❌ Clear cart error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to clear cart")

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from typing import List
from datetime import datetime
import uuid
import logging
import os

from pydantic import BaseModel
from starlette.background import BackgroundTask

from db.db_manager import DatabaseManager, get_database
from app.utils.auth import current_active_user
from app.cache.redis_manager import get_redis
from app.cache.cache_config import CacheTTL, CacheKeys
from app.services.inventory_service import get_inventory_service
from app.utils.validators import InputValidator
from schema.cart import CartRequest, UpdateCartItemRequest
from schema.user import UserinDB

logger = logging.getLogger(__name__)
router = APIRouter()

# ----------------- Helpers -----------------
from bson import ObjectId

# Add this helper function
def serialize_doc(doc):
    """Convert MongoDB document to JSON-serializable dict"""
    if doc is None:
        return None
    if isinstance(doc, list):
        return [serialize_doc(item) for item in doc]
    if isinstance(doc, dict):
        result = {}
        for key, value in doc.items():
            if isinstance(value, ObjectId):
                result[key] = str(value)
            elif isinstance(value, dict):
                result[key] = serialize_doc(value)
            elif isinstance(value, list):
                result[key] = [serialize_doc(item) for item in value]
            elif isinstance(value, datetime):
                result[key] = value.isoformat()
            else:
                result[key] = value
        return result
    return doc
    
async def invalidate_cart_cache(user_id: str):
    try:
        redis = get_redis()
        cache_key = CacheKeys.user_cart(user_id)
        await redis.delete(cache_key)
        logger.info(f"🗑️ Invalidated cart cache for user {user_id}")
    except Exception as e:
        logger.warning(f"⚠️ Cart cache invalidation error: {e}")

def process_product_images(product: dict) -> List[str]:
    images = product.get("images", [])
    processed = []
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                url = img.get("url") or img.get("secure_url") or img.get("original")
                if url: processed.append(url)
            elif isinstance(img, str) and img.strip():
                processed.append(img)
    elif isinstance(images, str) and images.strip():
        processed.append(images)
    return processed

async def get_cart_or_create(db: DatabaseManager, user_id: str):
    cart = await db.find_one("carts", {"user": user_id})
    if not cart:
        cart_data = {
            "user": user_id,
            "items": [],
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        await db.insert_one("carts", cart_data)
        return cart_data
    return cart

# ----------------- Routes -----------------

@router.post("/add", status_code=201)
async def add_to_cart(
    req: CartRequest,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Add product or service to cart.
    For products: requires productId, handles stock
    For services: requires serviceType, serviceName, servicePrice, serviceDetails
    """
    try:
        cart = await get_cart_or_create(db, current_user.id)
        
        # Handle SERVICES (porter, printout)
        if req.serviceType in ['porter', 'printout']:
            if not req.serviceName or req.servicePrice is None:
                raise HTTPException(status_code=400, detail="Service name and price required")
            
            # Check if porter service already exists (only 1 allowed)
            if req.serviceType == 'porter':
                has_porter = any(i.get("serviceType") == "porter" for i in cart["items"])
                if has_porter:
                    raise HTTPException(
                        status_code=400, 
                        detail="Only one porter service allowed per cart. Remove existing one first."
                    )
            
            # Add service to cart
            service_item = {
                "_id": str(uuid.uuid4()),
                "serviceType": req.serviceType,
                "serviceName": req.serviceName,
                "servicePrice": req.servicePrice,
                "serviceDetails": req.serviceDetails or {},
                "quantity": 1,  # Services always have quantity 1
                "added_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            cart["items"].append(service_item)
            cart["updated_at"] = datetime.utcnow()
            await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
            background_tasks.add_task(invalidate_cart_cache, current_user.id)
            
            return {
                "message": f"{req.serviceName} added to cart",
                "cart_item": service_item
            }
        
        # Handle PRODUCTS (existing logic)
        else:
            if not req.productId or not InputValidator.validate_custom_id(req.productId):
                raise HTTPException(status_code=400, detail="Invalid product ID")
            
            max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
            if not InputValidator.validate_quantity(req.quantity, max_qty):
                raise HTTPException(
                    status_code=400, 
                    detail=f"Quantity must be between 1 and {max_qty}"
                )

            # Real-time stock check
            product = await db.find_one("products", {"id": req.productId, "is_active": True})
            if not product:
                raise HTTPException(status_code=404, detail="Product not found or inactive")
            if product.get("stock", 0) < req.quantity:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Only {product.get('stock',0)} available"
                )

            # Check for existing product
            existing_item = next(
                (i for i in cart["items"] 
                 if i.get("product") == req.productId and i.get("serviceType") != "porter" and i.get("serviceType") != "printout"), 
                None
            )
            
            if existing_item:
                new_qty = existing_item["quantity"] + req.quantity
                if product.get("stock", 0) < new_qty:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Cannot add {req.quantity}. Only {product.get('stock',0)-existing_item['quantity']} more available"
                    )
                existing_item["quantity"] = new_qty
                existing_item["updated_at"] = datetime.utcnow()
            else:
                cart["items"].append({
                    "_id": str(uuid.uuid4()),
                    "product": req.productId,
                    "serviceType": "product",
                    "quantity": req.quantity,
                    "added_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })

            cart["updated_at"] = datetime.utcnow()
            await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
            background_tasks.add_task(invalidate_cart_cache, current_user.id)

            return {
                "message": "Product added to cart", 
                "cart_item": cart["items"][-1] if not existing_item else existing_item
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Add to cart error: {e}")
        raise HTTPException(status_code=500, detail="Failed to add to cart")


@router.post("/batch-add")
async def batch_add_to_cart(
    items: List[CartRequest],
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Batch add products to cart (services not supported in batch)"""
    if not items:
        raise HTTPException(status_code=400, detail="No items provided")
    if len(items) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 items per batch")

    # Filter out services from batch add
    product_items = [i for i in items if i.serviceType == 'product' and i.productId]
    if not product_items:
        raise HTTPException(status_code=400, detail="No valid products to add")

    try:
        product_ids = [i.productId for i in product_items]
        products = await db.find_many("products", {"id": {"$in": product_ids}, "is_active": True})
        product_map = {p["id"]: p for p in products}

        stock_errors = []
        for i in product_items:
            product = product_map.get(i.productId)
            if not product: 
                stock_errors.append(f"Product {i.productId} not found")
            elif product.get("stock",0) < i.quantity: 
                stock_errors.append(f"{product['name']}: only {product.get('stock',0)} available")
        
        if stock_errors: 
            raise HTTPException(status_code=400, detail={"errors": stock_errors})

        cart = await get_cart_or_create(db, current_user.id)

        for i in product_items:
            existing_item = next(
                (it for it in cart["items"] 
                 if it.get("product") == i.productId and it.get("serviceType") == "product"), 
                None
            )
            if existing_item:
                existing_item["quantity"] += i.quantity
                existing_item["updated_at"] = datetime.utcnow()
            else:
                cart["items"].append({
                    "_id": str(uuid.uuid4()),
                    "product": i.productId,
                    "serviceType": "product",
                    "quantity": i.quantity,
                    "added_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })
        
        cart["updated_at"] = datetime.utcnow()
        await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
        background_tasks.add_task(invalidate_cart_cache, current_user.id)

        return {"message": f"{len(product_items)} items added", "items": cart["items"]}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Batch add error: {e}")
        raise HTTPException(status_code=500, detail="Failed to add items to cart")


# @router.get("/")
# async def get_cart(
#     current_user: UserinDB = Depends(current_active_user), 
#     db: DatabaseManager = Depends(get_database)
# ):
#     """Get cart with both products and services"""
#     try:
#         redis = get_redis()
#         cache_key = CacheKeys.user_cart(current_user.id)
#         cached = await redis.get(cache_key)
#         if cached: 
#             return cached

#         cart = await get_cart_or_create(db, current_user.id)

#         # Separate products and services
#         product_items = [i for i in cart["items"] if i.get("serviceType") == "product"]
#         service_items = [i for i in cart["items"] if i.get("serviceType") in ["porter", "printout"]]

#         # Process products
#         product_ids = [item["product"] for item in product_items]
#         products = await db.find_many("products", {"id": {"$in": product_ids}, "is_active": True})
#         product_map = {p["id"]: p for p in products}

#         items_with_details = []
#         total_price = 0
#         total_items = 0
#         inventory_service = get_inventory_service()

#         # Add products to response
#         for item in product_items:
#             product = product_map.get(item["product"])
#             if not product: 
#                 continue
            
#             try:
#                 stock = await inventory_service.get_available_stock(product["id"])
#             except Exception:
#                 stock = product.get("stock", 0)
            
#             item_total = product.get("price", 0) * item["quantity"]
#             total_price += item_total
#             total_items += item["quantity"]
            
#             items_with_details.append({
#                 "_id": item["_id"],
#                 "productId": product["id"],
#                 "product": {**product, "images": process_product_images(product)},
#                 "serviceType": "product",
#                 "quantity": item["quantity"],
#                 "available_stock": stock,
#                 "stock_sufficient": stock >= item["quantity"],
#                 "item_total": item_total,
#                 "added_at": item.get("added_at"),
#                 "updated_at": item.get("updated_at")
#             })

#         # Add services to response
#         for item in service_items:
#             service_total = item.get("servicePrice", 0)
#             total_price += service_total
#             total_items += 1
            
#             items_with_details.append({
#                 "_id": item["_id"],
#                 "serviceType": item["serviceType"],
#                 "serviceName": item.get("serviceName"),
#                 "servicePrice": item.get("servicePrice"),
#                 "serviceDetails": item.get("serviceDetails"),
#                 "quantity": 1,  # Services always 1
#                 "item_total": service_total,
#                 "added_at": item.get("added_at"),
#                 "updated_at": item.get("updated_at")
#             })

#         response = {
#             "items": items_with_details, 
#             "total_items": total_items, 
#             "total_price": total_price
#         }
        
#         await redis.set(cache_key, response, CacheTTL.CART)
#         return response

#     except Exception as e:
#         logger.error(f"❌ Get cart error: {e}")
#         raise HTTPException(status_code=500, detail="Failed to fetch cart")

@router.get("/")
async def get_cart(
    current_user: UserinDB = Depends(current_active_user), 
    db: DatabaseManager = Depends(get_database)
):
    try:
        redis = get_redis()
        cache_key = CacheKeys.user_cart(current_user.id)
        cached = await redis.get(cache_key)
        if cached: 
            return cached

        cart = await get_cart_or_create(db, current_user.id)

        product_ids = [item["product"] for item in cart["items"] if item.get("product")]
        products = await db.find_many("products", {"id": {"$in": product_ids}, "is_active": True})
        product_map = {p["id"]: p for p in products}

        items_with_product = []
        total_price = 0
        total_items = 0
        inventory_service = get_inventory_service()

        for item in cart["items"]:
            # Handle products
            if item.get("serviceType") == "product" or item.get("product"):
                product = product_map.get(item.get("product"))
                if not product: 
                    continue
                    
                try:
                    stock = await inventory_service.get_available_stock(product["id"])
                except Exception:
                    stock = product.get("stock", 0)
                    
                item_total = product.get("price", 0) * item["quantity"]
                total_price += item_total
                total_items += item["quantity"]
                
                items_with_product.append({
                    "_id": str(item.get("_id", "")),  # Convert ObjectId to string
                    "productId": product["id"],
                    "product": {**product, "images": process_product_images(product)},
                    "serviceType": "product",
                    "quantity": item["quantity"],
                    "available_stock": stock,
                    "stock_sufficient": stock >= item["quantity"],
                    "item_total": item_total,
                    "added_at": item.get("added_at"),
                    "updated_at": item.get("updated_at")
                })
            
            # Handle services
            elif item.get("serviceType") in ["porter", "printout"]:
                service_total = item.get("servicePrice", 0)
                total_price += service_total
                total_items += 1
                
                items_with_product.append({
                    "_id": str(item.get("_id", "")),  # Convert ObjectId to string
                    "serviceType": item["serviceType"],
                    "serviceName": item.get("serviceName"),
                    "servicePrice": item.get("servicePrice"),
                    "serviceDetails": item.get("serviceDetails"),
                    "quantity": 1,
                    "item_total": service_total,
                    "added_at": item.get("added_at"),
                    "updated_at": item.get("updated_at")
                })

        response = {
            "items": items_with_product, 
            "total_items": total_items, 
            "total_price": total_price
        }
        
        # ✅ Serialize the response
        serialized_response = serialize_doc(response)
        
        await redis.set(cache_key, serialized_response, CacheTTL.CART)
        return serialized_response

    except Exception as e:
        logger.error(f"❌ Get cart error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch cart")
        
@router.put("/update")
async def update_cart_item(
    req: UpdateCartItemRequest, 
    background_tasks: BackgroundTasks, 
    current_user: UserinDB = Depends(current_active_user), 
    db: DatabaseManager = Depends(get_database)
):
    """Update cart item quantity (products only, services can't change quantity)"""
    try:
        max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
        if not InputValidator.validate_quantity(req.quantity, max_qty):
            raise HTTPException(
                status_code=400, 
                detail=f"Quantity must be between 1 and {max_qty}"
            )

        cart = await get_cart_or_create(db, current_user.id)
        item = next((i for i in cart["items"] if i.get("product") == req.itemId), None)
        
        if not item: 
            raise HTTPException(status_code=404, detail="Item not found in cart")
        
        # Prevent updating service quantities
        if item.get("serviceType") in ["porter", "printout"]:
            raise HTTPException(
                status_code=400, 
                detail="Cannot update service quantity. Remove and re-add with new details."
            )

        # Check product stock
        product = await db.find_one("products", {"id": item["product"], "is_active": True})
        if not product: 
            raise HTTPException(status_code=404, detail="Product not found or inactive")
        if product.get("stock", 0) < req.quantity: 
            raise HTTPException(
                status_code=400, 
                detail=f"Only {product['stock']} items available"
            )

        item["quantity"] = req.quantity
        item["updated_at"] = datetime.utcnow()
        cart["updated_at"] = datetime.utcnow()
        
        await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        return {
            "message": "Cart item updated", 
            "item_id": item["_id"], 
            "quantity": item["quantity"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Update cart error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update cart")


class RemoveItem(BaseModel):
    itemId: str

@router.delete("/remove")
async def remove_cart_item(
    background_tasks: BackgroundTasks,
    payload: RemoveItem,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Remove item from cart (works for both products and services)"""
    try:
        cart = await get_cart_or_create(db, current_user.id)
        original_len = len(cart["items"])
        
        # Remove by _id (works for both products and services)
        cart["items"] = [i for i in cart["items"] if i.get("_id") != payload.itemId]
        
        # Also try removing by product ID (for backward compatibility)
        if len(cart["items"]) == original_len:
            cart["items"] = [i for i in cart["items"] if i.get("product") != payload.itemId]
        
        if len(cart["items"]) == original_len: 
            raise HTTPException(status_code=404, detail="Item not found")
        
        cart["updated_at"] = datetime.utcnow()
        await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        return {"message": "Item removed", "itemId": payload.itemId}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Remove item error: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove item")


@router.delete("/clear")
async def clear_cart(
    background_tasks: BackgroundTasks, 
    current_user: UserinDB = Depends(current_active_user), 
    db: DatabaseManager = Depends(get_database)
):
    """Clear entire cart (removes all products and services)"""
    try:
        cart = await get_cart_or_create(db, current_user.id)
        cart["items"] = []
        cart["updated_at"] = datetime.utcnow()
        await db.update_one("carts", {"user": current_user.id}, {"$set": cart})
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        return {"message": "Cart cleared successfully"}
    except Exception as e:
        logger.error(f"❌ Clear cart error: {e}")
        raise HTTPException(status_code=500, detail="Failed to clear cart")