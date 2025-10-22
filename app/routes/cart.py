# app/routes/cart.py - COMPLETE REPLACEMENT
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
import logging
from app.utils.auth import current_active_user
from app.utils.mongo import fix_mongo_types
from db.db_manager import DatabaseManager, get_database
from schema.cart import CartRequest, UpdateCartItemRequest
from schema.user import UserinDB
import uuid
from datetime import datetime
from app.cache.redis_manager import get_redis
from app.cache.cache_config import CacheTTL, CacheKeys
from app.services.inventory_service import get_inventory_service
from app.utils.validators import InputValidator
import os

logger = logging.getLogger(__name__)
router = APIRouter()

def process_product_images_for_cart(product):
    """Convert admin panel image objects to mobile app compatible URLs"""
    images = product.get("images", [])
    processed_images = []
    
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                url = img.get("url") or img.get("secure_url") or img.get("original")
                if url:
                    processed_images.append(url)
            elif isinstance(img, str) and img.strip():
                processed_images.append(img)
    elif isinstance(images, str) and images.strip():
        processed_images.append(images)
    
    return processed_images

async def invalidate_cart_cache(user_id: str):
    """Helper to invalidate cart cache"""
    try:
        redis = get_redis()
        cache_key = CacheKeys.user_cart(user_id)
        await redis.delete(cache_key)
        logger.info(f"🗑️ Invalidated cart cache: {user_id}")
    except Exception as e:
        logger.warning(f"⚠️ Cart cache invalidation error: {e}")

@router.post("/add")
async def add_to_cart(
    req: CartRequest,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)    
):
    """
    Add item to cart with atomic stock validation
    Prevents overselling with real-time inventory checks
    """
    product_id = req.productId
    quantity = req.quantity
    
    try:
        logger.info(f"🛒 Adding to cart: product={product_id}, quantity={quantity}, user={current_user.email}")
        
        # ✅ Validate inputs
        if not product_id or not InputValidator.validate_custom_id(product_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid product ID"
            )
        
        max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
        if not InputValidator.validate_quantity(quantity, max_qty):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Quantity must be between 1 and {max_qty}"
            )
        
        # ✅ Real-time stock check with atomic query
        product = await db.find_one("products", {
            "id": product_id,
            "is_active": True,
            "stock": {"$gte": quantity}
        })
        
        if not product:
            # Check why product not found
            product_check = await db.find_one("products", {"id": product_id})
            
            if not product_check:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Product not found"
                )
            
            if not product_check.get("is_active", False):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Product is not available"
                )
            
            # Stock insufficient
            current_stock = product_check.get('stock', 0)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only {current_stock} item{'s' if current_stock != 1 else ''} available"
            )
        
        # Find or create cart
        cart = await db.find_one("carts", {"user": current_user.id})

        if not cart:
            # ✅ Create new cart
            item_id = str(uuid.uuid4())
            cart_data = {
                "user": current_user.id,
                "items": [{
                    "_id": item_id,
                    "product": product_id, 
                    "quantity": quantity,
                    "added_at": datetime.utcnow()
                }],
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await db.insert_one("carts", cart_data)
            logger.info(f"✅ Created new cart for user {current_user.email}")
        else:
            # ✅ Update existing cart
            existing_item = None
            for item in cart["items"]:
                if item["product"] == product_id:
                    existing_item = item
                    break
            
            if existing_item:
                # Check if new total exceeds stock
                new_quantity = existing_item["quantity"] + quantity
                
                if product.get("stock", 0) < new_quantity:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot add {quantity} more. Only {product.get('stock', 0)} available (you have {existing_item['quantity']} in cart)"
                    )
                
                existing_item["quantity"] = new_quantity
                existing_item["updated_at"] = datetime.utcnow()
            else:
                # Add new item
                item_id = str(uuid.uuid4())
                cart["items"].append({
                    "_id": item_id,
                    "product": product_id, 
                    "quantity": quantity,
                    "added_at": datetime.utcnow()
                })

            cart["updated_at"] = datetime.utcnow()
            await db.update_one(
                "carts", 
                {"_id": cart["_id"]},
                {
                    "$set": {
                        "items": cart["items"],
                        "updated_at": cart["updated_at"]
                    }
                }
            )
            logger.info(f"✅ Updated cart for user {current_user.email}")
        
        # ✅ Invalidate cart cache
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        # ✅ Track interaction for recommendations
        background_tasks.add_task(
            track_cart_interaction,
            current_user.id,
            product_id,
            "add_to_cart"
        )
            
        return {
            "message": "Product added to cart successfully",
            "product_id": product_id,
            "quantity": quantity
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to add to cart: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add to cart"
        )

@router.post("/batch-add")
async def batch_add_to_cart(
    items: list[CartRequest],
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Add multiple items to cart in single request
    Reduces API calls from mobile apps
    """
    try:
        # ✅ Validate batch size
        if len(items) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 10 items per batch"
            )
        
        if not items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No items provided"
            )
        
        logger.info(f"🛒 Batch add to cart: {len(items)} items, user={current_user.email}")
        
        # ✅ Validate all products exist and have stock
        product_ids = [item.productId for item in items]
        products = await db.find_many("products", {
            "id": {"$in": product_ids},
            "is_active": True
        })
        
        # Create product lookup
        product_map = {p["id"]: p for p in products}
        
        # Validate stock for all items
        stock_errors = []
        for item in items:
            product = product_map.get(item.productId)
            
            if not product:
                stock_errors.append(f"Product {item.productId} not found")
                continue
            
            if product.get("stock", 0) < item.quantity:
                stock_errors.append(
                    f"{product['name']}: only {product.get('stock', 0)} available"
                )
        
        if stock_errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"errors": stock_errors}
            )
        
        # ✅ Get or create cart
        cart = await db.find_one("carts", {"user": current_user.id})
        
        if not cart:
            # Create new cart with all items
            cart_items = []
            for item in items:
                cart_items.append({
                    "_id": str(uuid.uuid4()),
                    "product": item.productId,
                    "quantity": item.quantity,
                    "added_at": datetime.utcnow()
                })
            
            cart_data = {
                "user": current_user.id,
                "items": cart_items,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await db.insert_one("carts", cart_data)
        else:
            # Update existing cart
            for item in items:
                existing_item = None
                for cart_item in cart["items"]:
                    if cart_item["product"] == item.productId:
                        existing_item = cart_item
                        break
                
                if existing_item:
                    # Update quantity
                    existing_item["quantity"] += item.quantity
                    existing_item["updated_at"] = datetime.utcnow()
                else:
                    # Add new item
                    cart["items"].append({
                        "_id": str(uuid.uuid4()),
                        "product": item.productId,
                        "quantity": item.quantity,
                        "added_at": datetime.utcnow()
                    })
            
            cart["updated_at"] = datetime.utcnow()
            await db.update_one(
                "carts",
                {"_id": cart["_id"]},
                {"$set": {"items": cart["items"], "updated_at": cart["updated_at"]}}
            )
        
        # ✅ Invalidate cache
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        logger.info(f"✅ Batch added {len(items)} items to cart")
        
        return {
            "message": f"Added {len(items)} items to cart successfully",
            "item_count": len(items)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Batch add to cart error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to add items to cart"
        )
        
@router.get("/")
async def get_cart(
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """
    Get user's cart with multi-layer caching
    - L1 (Memory) + L2 (Redis) caching
    - Real-time stock validation
    - Optimized product population
    """
    try:
        logger.info(f"🛒 Getting cart for user {current_user.email}")
        
        redis = get_redis()
        inventory_service = get_inventory_service()
        
        cache_key = CacheKeys.user_cart(current_user.id)
        
        # ✅ Multi-layer cache check
        try:
            cached_cart = await redis.get(cache_key, use_l1=True)
            
            if cached_cart:
                # Verify stock for cached items (quick check)
                for item in cached_cart.get('items', []):
                    try:
                        available_stock = await inventory_service.get_available_stock(
                            item['product']['id']
                        )
                        item['available_stock'] = available_stock
                        item['stock_sufficient'] = available_stock >= item['quantity']
                    except Exception as stock_error:
                        logger.warning(f"⚠️ Stock check error: {stock_error}")
                        item['available_stock'] = item['product'].get('stock', 0)
                        item['stock_sufficient'] = item['product'].get('stock', 0) >= item['quantity']
                
                logger.info(f"⚡ Cart cache HIT for user {current_user.id}")
                return cached_cart
        except Exception as cache_error:
            logger.warning(f"⚠️ Cache read error: {cache_error}")
        
        logger.info(f"💾 Cart cache MISS for user {current_user.id}")
        
        # ✅ Fetch from database
        cart = await db.find_one("carts", {"user": current_user.id})
        
        if not cart:
            empty_cart = {"items": [], "total_items": 0, "total_price": 0.0}
            # Cache empty cart briefly
            await redis.set(cache_key, empty_cart, 300, use_l1=True)
            return empty_cart
        
        # ✅ Optimized product population with single aggregation
        if not cart.get('items'):
            empty_cart = {"items": [], "total_items": 0, "total_price": 0.0}
            await redis.set(cache_key, empty_cart, 300, use_l1=True)
            return empty_cart
        
        product_ids = [item["product"] for item in cart.get('items', [])]
        
        # Fetch all products in one query with populated references
        pipeline = [
            {"$match": {"id": {"$in": product_ids}, "is_active": True}},
            {
                "$lookup": {
                    "from": "categories",
                    "localField": "category",
                    "foreignField": "id",
                    "as": "category_data"
                }
            },
            {
                "$lookup": {
                    "from": "brands",
                    "localField": "brand",
                    "foreignField": "id",
                    "as": "brand_data"
                }
            },
            {
                "$addFields": {
                    "category": {"$arrayElemAt": ["$category_data", 0]},
                    "brand": {"$arrayElemAt": ["$brand_data", 0]}
                }
            },
            {
                "$project": {
                    "category_data": 0,
                    "brand_data": 0
                }
            }
        ]
        
        products = await db.aggregate("products", pipeline)
        product_map = {p["id"]: p for p in products}
        
        # ✅ Build cart response with stock validation
        items_with_products = []
        total_price = 0.0
        total_items = 0
        
        for item in cart.get('items', []):
            try:
                product_id = item["product"]
                product = product_map.get(product_id)
                
                if not product:
                    logger.warning(f"⚠️ Product {product_id} not found or inactive")
                    continue
                
                product_fixed = fix_mongo_types(product)
                product_fixed["images"] = process_product_images_for_cart(product_fixed)
                
                # Real-time stock check
                try:
                    available_stock = await inventory_service.get_available_stock(product_id)
                except Exception:
                    available_stock = product.get('stock', 0)
                
                item_price = product_fixed.get('price', 0) * item.get("quantity", 0)
                total_price += item_price
                total_items += item.get("quantity", 0)
                
                items_with_products.append({
                    "_id": str(item.get("_id")),
                    "product": product_fixed,
                    "quantity": item.get("quantity", 0),
                    "available_stock": available_stock,
                    "stock_sufficient": available_stock >= item.get("quantity", 0),
                    "item_total": item_price,
                    "added_at": item.get("added_at"),
                    "updated_at": item.get("updated_at")
                })
                    
            except Exception as item_error:
                logger.error(f"❌ Error processing cart item: {item_error}")
                continue
        
        cart_response = {
            "items": items_with_products,
            "total_items": total_items,
            "total_price": round(total_price, 2)
        }
        
        # ✅ Cache the processed cart (L1 + L2)
        try:
            await redis.set(cache_key, cart_response, CacheTTL.CART, use_l1=True)
            logger.info(f"💾 Cached cart for user {current_user.id} (L1 + L2)")
        except Exception as cache_error:
            logger.warning(f"⚠️ Cache write error: {cache_error}")
        
        logger.info(f"✅ Returning cart with {len(items_with_products)} items")
        return cart_response
        
    except Exception as e:
        logger.error(f"❌ Get cart error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get cart"
        )

@router.put("/update")
async def update_cart_item(
    req: UpdateCartItemRequest,
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Update cart item quantity with stock validation"""
    item_id = req.itemId
    quantity = req.quantity
    
    try:
        logger.info(f"🔄 Updating cart item: {item_id}, quantity={quantity}, user={current_user.email}")
        
        # ✅ Validate quantity
        max_qty = int(os.getenv('MAX_CART_ITEMS_PER_PRODUCT', 100))
        if not InputValidator.validate_quantity(quantity, max_qty):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Quantity must be between 1 and {max_qty}"
            )
        
        redis = get_redis()
        inventory_service = get_inventory_service()
            
        cart = await db.find_one("carts", {"user": current_user.id})
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart not found"
            )
        
        # Find and update item
        item_found = False
        for item in cart["items"]:
            if str(item.get("_id", "")) == item_id:
                # ✅ Real-time stock check
                try:
                    available_stock = await inventory_service.get_available_stock(
                        str(item["product"])
                    )
                    if available_stock < quantity:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Only {available_stock} items available"
                        )
                except Exception as stock_error:
                    logger.warning(f"⚠️ Inventory service error: {stock_error}")
                    # Fallback to DB
                    product = await db.find_one("products", {
                        "id": item["product"], 
                        "is_active": True
                    })
                    if not product:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="Product not found or inactive"
                        )
                    if product["stock"] < quantity:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Only {product['stock']} items available"
                        )
                
                item["quantity"] = quantity
                item["updated_at"] = datetime.utcnow()
                item_found = True
                break
                
        if not item_found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found in cart"
            )
        
        # Update cart
        await db.update_one(
            "carts",
            {"_id": cart["_id"]},
            {
                "$set": {
                    "items": cart["items"],
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # ✅ Invalidate cache
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        logger.info(f"✅ Cart item {item_id} updated successfully")
        return {
            "message": "Cart item updated successfully",
            "item_id": item_id,
            "quantity": quantity
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Update cart error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update cart"
        )

@router.delete("/remove")
async def remove_from_cart(
    background_tasks: BackgroundTasks,
    item_id: str = Query(..., description="Cart item ID to remove"),
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Remove item from cart"""
    try:
        logger.info(f"🗑️ Removing cart item: {item_id}, user={current_user.email}")
        
        cart = await db.find_one("carts", {"user": current_user.id})
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart not found"
            )
        
        # Find and remove item
        original_count = len(cart["items"])
        cart["items"] = [
            item for item in cart["items"] 
            if str(item.get("_id", "")) != item_id
        ]
        
        if len(cart["items"]) == original_count:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Item not found in cart"
            )
        
        # Update cart
        await db.update_one(
            "carts",
            {"_id": cart["_id"]},
            {
                "$set": {
                    "items": cart["items"],
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # ✅ Invalidate cache
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        logger.info(f"✅ Cart item {item_id} removed successfully")
        return {
            "message": "Item removed from cart",
            "item_id": item_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Remove from cart error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove from cart"
        )

@router.delete("/clear")
async def clear_cart(
    background_tasks: BackgroundTasks,
    current_user: UserinDB = Depends(current_active_user),
    db: DatabaseManager = Depends(get_database)
):
    """Clear user's entire cart"""
    try:
        logger.info(f"🗑️ Clearing cart for user {current_user.email}")
        
        cart = await db.find_one("carts", {"user": current_user.id})
        if not cart:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Cart not found"
            )
        
        # Clear cart items
        await db.update_one(
            "carts",
            {"_id": cart["_id"]},
            {
                "$set": {
                    "items": [],
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        # ✅ Invalidate cache
        background_tasks.add_task(invalidate_cart_cache, current_user.id)
        
        logger.info(f"✅ Cart cleared for user {current_user.email}")
        return {"message": "Cart cleared successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Clear cart error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear cart"
        )

# Background task helper
async def track_cart_interaction(user_id: str, product_id: str, interaction_type: str):
    """Track cart interactions for recommendations"""
    try:
        from app.services.recommendation_service import get_recommendation_service
        recommendation_service = get_recommendation_service()
        
        await recommendation_service.track_user_interaction(
            user_id=user_id,
            interaction_type=interaction_type,
            product_id=product_id,
            metadata={"source": "cart"}
        )
    except Exception as e:
        logger.error(f"❌ Interaction tracking error: {e}")