from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, Query, HTTPException, status
from schema.products import ProductResponse
from db.db_manager import DatabaseManager, get_database
import logging
from app.utils.mongo import fix_mongo_types
from app.cache.redis_manager import get_redis

logger = logging.getLogger(__name__)
router = APIRouter()

def process_product_images(product):
    """Convert admin panel image objects to mobile app compatible URLs"""
    images = product.get("images", [])
    processed_images = []
    
    if isinstance(images, list):
        for img in images:
            if isinstance(img, dict):
                # Image object from admin panel/Cloudinary
                url = img.get("url") or img.get("secure_url") or img.get("original")
                if url:
                    processed_images.append(url)
            elif isinstance(img, str) and img.strip():
                # Direct URL string
                processed_images.append(img)
    elif isinstance(images, str) and images.strip():
        # Single image string (backward compatibility)
        processed_images.append(images)
    
    # Fallback: check for old single image field
    if not processed_images and product.get("image"):
        processed_images.append(product["image"])
    
    return processed_images

def serialize_product_for_mobile(product):
    """Serialize product specifically for mobile app with proper ID handling"""
    try:
        # First, fix MongoDB types
        fixed_product = fix_mongo_types(product)
        
        # Process images for mobile app
        fixed_product["images"] = process_product_images(fixed_product)
        
        # Ensure required fields exist
        fixed_product.setdefault("stock", 0)
        fixed_product.setdefault("status", "active")
        fixed_product.setdefault("keywords", [])
        fixed_product.setdefault("is_active", True)
        
        return fixed_product
        
    except Exception as e:
        logger.error(f"Error serializing product: {e}")
        return None

def generate_cache_key(**params):
    """Generate clean cache key from parameters, excluding None values"""
    key_parts = ["products", "v1"]
    for k, v in sorted(params.items()):
        if v is not None:
            key_parts.append(f"{k}:{v}")
    return ":".join(key_parts)

@router.get("")  # Handle both /products and /products/
@router.get("/")
async def get_products(
    category: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    in_stock: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: DatabaseManager = Depends(get_database) 
):
    """Get products with mobile app optimized response and caching"""
    try:
        logger.info(f"Product request: category={category}, brand={brand}, search={search}, page={page}")
        
        # Check Redis cache (only for non-search queries)
        redis = get_redis()
        cache_key = None
        
        if not search:
            cache_key = generate_cache_key(
                category=category,
                brand=brand,
                min_price=min_price,
                max_price=max_price,
                in_stock=in_stock,
                page=page,
                limit=limit
            )
            
            try:
                cached_result = await redis.get(cache_key)
                if cached_result:
                    logger.info(f"Cache HIT: {cache_key}")
                    return cached_result
            except Exception as cache_error:
                logger.warning(f"Cache read error: {cache_error}")
        
        # Build MongoDB query
        query = {"is_active": True}

        # Handle category filter
        if category:
            if ObjectId.is_valid(category):
                query["category"] = ObjectId(category)
            else:
                cat = await db.find_one("categories", {
                    "name": {"$regex": category, "$options": "i"},
                    "is_active": True
                })
                if cat:
                    query["category"] = cat["id"]
                else:
                    empty_response = {
                        "products": [], 
                        "pagination": {
                            "currentPage": page, 
                            "totalPages": 0, 
                            "totalProducts": 0,
                            "hasNextPage": False,
                            "hasPrevPage": False
                        }
                    }
                    # Cache empty results to prevent repeated queries
                    if cache_key:
                        try:
                            await redis.set(cache_key, empty_response, 300)
                        except:
                            pass
                    return empty_response
                    
        # Handle brand filter
        if brand:
            if ObjectId.is_valid(brand):
                query["brand"] = ObjectId(brand)
            else:
                brand_doc = await db.find_one("brands", {
                    "name": {"$regex": brand, "$options": "i"},
                    "is_active": True
                })
                if brand_doc:
                    query["brand"] = brand_doc["id"]
                else:
                    empty_response = {
                        "products": [],
                        "pagination": {
                            "currentPage": page,
                            "totalPages": 0,
                            "totalProducts": 0,
                            "hasNextPage": False,
                            "hasPrevPage": False
                        }
                    }
                    if cache_key:
                        try:
                            await redis.set(cache_key, empty_response, 300)
                        except:
                            pass
                    return empty_response
                    
        # Handle stock filter
        if in_stock:
            query["stock"] = {"$gt": 0}
            
        # Handle price range
        if min_price is not None or max_price is not None:
            query["price"] = {}
            if min_price is not None:
                query["price"]["$gte"] = min_price
            if max_price is not None:
                query["price"]["$lte"] = max_price
                
        # Handle search with better keyword matching
        if search:
            search_terms = search.strip()
            if search_terms:
                search_keywords = [kw.strip() for kw in search_terms.split(',') if kw.strip()]
                
                or_query = [
                    {"name": {"$regex": search_terms, "$options": "i"}},
                    {"description": {"$regex": search_terms, "$options": "i"}},
                ]
                
                # Add keyword searches
                for keyword in search_keywords:
                    or_query.extend([
                        {"keywords": {"$elemMatch": {"$regex": keyword, "$options": "i"}}},
                        {"tags": {"$elemMatch": {"$regex": keyword, "$options": "i"}}}
                    ])
                
                query["$or"] = or_query
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # Use aggregation pipeline for better performance
        pipeline = [
            {"$match": query},
            {
                "$lookup": {
                    "from": "categories",
                    "localField": "category",  # This is the custom ID string like "CATSNACKS"
                    "foreignField": "id",      # Match against category's custom id, not _id
                    "as": "category_data"
                }
            },
            {
                "$lookup": {
                    "from": "brands",
                    "localField": "brand",     # This is the custom ID string like "BRDLAYS"
                    "foreignField": "id",      # Match against brand's custom id, not _id
                    "as": "brand_data"
                }
            },
            {
                "$addFields": {
                    "category": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$category_data", 0]},
                            {"name": "Uncategorized", "id": None, "_id": None}
                        ]
                    },
                    "brand": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$brand_data", 0]},
                            {"name": "No Brand", "id": None, "_id": None}
                        ]
                    }
                }
            },
            {
                "$project": {
                    "category_data": 0,
                    "brand_data": 0
                }
            },
            {"$sort": {"created_at": -1}},
            {
                "$facet": {
                    "products": [
                        {"$skip": skip},
                        {"$limit": limit}
                    ],
                    "totalCount": [
                        {"$count": "count"}
                    ]
                }
            }
        ]
        
        result = await db.aggregate("products", pipeline)
        
        if not result:
            products = []
            total = 0
        else:
            products = result[0].get("products", [])
            total_count = result[0].get("totalCount", [])
            total = total_count[0]["count"] if total_count else 0
        
        # Process products for mobile app with proper ID handling
        processed_products = []
        for product in products:
            try:
                serialized_product = serialize_product_for_mobile(product)
                
                if serialized_product and serialized_product.get("id"):
                    processed_products.append(serialized_product)
                else:
                    logger.warning(f"Product {product.get('name')} missing id after serialization")
                
            except Exception as process_error:
                logger.error(f"Error processing product: {process_error}")
                continue

        logger.info(f"Returning {len(processed_products)} products")
        
        # Build response
        response_data = {
            "products": processed_products,
            "pagination": {
                "currentPage": page,
                "totalPages": (total + limit - 1) // limit if total > 0 else 0,
                "totalProducts": total,
                "hasNextPage": skip + len(products) < total,
                "hasPrevPage": page > 1
            }
        }
        
        # Cache the result (only non-search queries)
        if cache_key:
            try:
                # Dynamic TTL: 30min for first page, 10min for others
                ttl = 1800 if page == 1 else 600
                await redis.set(cache_key, response_data, ttl)
                logger.info(f"Cached: {cache_key} (TTL: {ttl}s)")
            except Exception as cache_error:
                logger.warning(f"Cache write error: {cache_error}")
        
        return response_data
        
    except Exception as e:
        logger.error(f"Get products error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get products: {str(e)}"
        )

@router.get("/{product_id}")
async def get_product(
    product_id: str,
    db: DatabaseManager = Depends(get_database)
):
    """Get a specific product by ID for mobile app"""
    # print(product_id)
    try:
        logger.info(f"Getting product by ID: {product_id}")
        
        if not product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid product ID format"
            )
        
        # Check cache first
        redis = get_redis()
        cache_key = f"product:{product_id}"
        
        try:
            cached_product = await redis.get(cache_key)
            if cached_product:
                logger.info(f"Cache HIT: {cache_key}")
                return cached_product
        except Exception as cache_error:
            logger.warning(f"Cache read error: {cache_error}")
        
        # Use aggregation to get product with populated fields
        pipeline = [
            {"$match": {"id": product_id, "is_active": True}},
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
                    "category": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$category_data", 0]},
                            {"name": "Uncategorized", "id": None}
                        ]
                    },
                    "brand": {
                        "$ifNull": [
                            {"$arrayElemAt": ["$brand_data", 0]},
                            {"name": "No Brand", "id": None}
                        ]
                    }
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
        
        if not products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Product not found"
            )
        
        # Use the enhanced serialization function
        product = serialize_product_for_mobile(products[0])
        
        if not product or not product.get("id"):
            logger.error(f"Product {product_id} missing _id after serialization")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Product data error"
            )
        
        # Cache the product for 1 hour
        try:
            await redis.set(cache_key, product, 3600)
            logger.info(f"Cached product: {cache_key}")
        except Exception as cache_error:
            logger.warning(f"Cache write error: {cache_error}")
        
        logger.info(f"Returning product {product.get('name')} with id: {product.get('id')}")
        return product
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get product error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_INTERNAL_SERVER_ERROR,
            detail="Failed to get product"
        )

@router.get("/debug/serialization")
async def debug_product_serialization(db: DatabaseManager = Depends(get_database)):
    """Debug endpoint to test product serialization"""
    try:
        # Get one product from database
        raw_product = await db.find_one("products", {})
        
        if not raw_product:
            return {"error": "No products found in database"}
        
        logger.info(f"Raw product from DB: {raw_product}")
        
        # Test serialization
        serialized = serialize_product_for_mobile(raw_product)
        
        return {
            "raw_product_id": str(raw_product.get("_id")),
            "raw_product_name": raw_product.get("name"),
            "serialized_product_id": serialized.get("_id") if serialized else None,
            "serialized_product_name": serialized.get("name") if serialized else None,
            "serialization_success": serialized is not None,
            "has_id_field": "_id" in (serialized or {}),
            "full_serialized": serialized
        }
    except Exception as e:
        logger.error(f"Debug serialization error: {e}")
        return {"error": str(e)}