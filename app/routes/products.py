# app/routes/products.py - COMPLETE REPLACEMENT
from typing import Optional
from bson import ObjectId
from fastapi import APIRouter, Depends, Query, HTTPException, status
from schema.products import ProductResponse
from db.db_manager import DatabaseManager, get_database
import logging
from app.utils.mongo import fix_mongo_types
from app.cache.redis_manager import get_redis
from app.cache.cache_config import CacheTTL, CacheKeys
from app.utils.validators import InputValidator
from app.utils.auth import get_current_admin
import hashlib
import json

logger = logging.getLogger(__name__)
router = APIRouter()

def process_product_images(product):
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
    
    if not processed_images and product.get("image"):
        processed_images.append(product["image"])
    
    return processed_images

def serialize_product_for_mobile(product, include_full_details: bool = True):
    """
    Serialize product with optional field selection
    Reduces payload size for list views
    """
    try:
        fixed_product = fix_mongo_types(product)
        
        # Process images
        fixed_product["images"] = process_product_images(fixed_product)
        
        # For list view, only include essential fields
        if not include_full_details:
            essential_fields = [
                'id', '_id', 'name', 'price', 'images', 
                'stock', 'rating', 'category', 'brand'
            ]
            fixed_product = {
                k: v for k, v in fixed_product.items() 
                if k in essential_fields
            }
        
        # Ensure required fields
        fixed_product.setdefault("stock", 0)
        fixed_product.setdefault("status", "active")
        fixed_product.setdefault("is_active", True)
        
        return fixed_product
        
    except Exception as e:
        logger.error(f"Error serializing product: {e}")
        return None

def generate_cache_key(**filters) -> str:
    """Generate deterministic cache key from filters"""
    # Remove None values
    clean_filters = {k: v for k, v in filters.items() if v is not None}
    
    # Sort and hash
    filter_str = json.dumps(clean_filters, sort_keys=True)
    filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:12]
    
    return f"{CacheKeys.PRODUCTS_LIST}:{filter_hash}"

@router.get("")
@router.get("/")
async def get_products(
    category: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    in_stock: Optional[bool] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    fields: Optional[str] = Query(None, description="Comma-separated fields to return"),
    db: DatabaseManager = Depends(get_database) 
):
    """
    Get products with advanced caching and optimization
    - Multi-layer caching (L1 memory + L2 Redis)
    - Field selection for reduced payload
    - Optimized MongoDB aggregation
    """
    try:
        logger.info(f"📦 Product request: category={category}, search={search}, page={page}")
        
        redis = get_redis()
        
        # Generate cache key
        cache_key = generate_cache_key(
            category=category,
            brand=brand,
            search=search,
            min_price=min_price,
            max_price=max_price,
            in_stock=in_stock,
            page=page,
            limit=limit,
            fields=fields
        )
        
        # ✅ L1 + L2 Cache Check (skip cache for search queries to keep results fresh)
        if not search:
            try:
                cached_result = await redis.get(cache_key, use_l1=True)
                if cached_result:
                    logger.info(f"⚡ Cache HIT: {cache_key[:30]}...")
                    return cached_result
            except Exception as cache_error:
                logger.warning(f"⚠️ Cache read error: {cache_error}")
        
        logger.info(f"💾 Cache MISS: {cache_key[:30]}...")
        
        # Build MongoDB query
        query = {"is_active": True}

        # Category filter
        if category:
            if ObjectId.is_valid(category):
                query["category"] = ObjectId(category)
            else:
                # print("category: ",category)
                cat = await db.find_one("categories", {
                    # "name": {"$regex": category, "$options": "i"},
                    "is_active": True,
                    "id": category,
                })
                # print("cat: ",cat)
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
                    # Cache empty results
                    await redis.set(cache_key, empty_response, CacheTTL.PRODUCT_LIST)
                    return empty_response
                    
        # Brand filter
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
                    await redis.set(cache_key, empty_response, CacheTTL.PRODUCT_LIST)
                    return empty_response
                    
        # Stock filter
        if in_stock:
            query["stock"] = {"$gt": 0}
            
        # Price range filter
        if min_price is not None or max_price is not None:
            query["price"] = {}
            if min_price is not None:
                query["price"]["$gte"] = min_price
            if max_price is not None:
                query["price"]["$lte"] = max_price
                
        # ✅ Search with sanitization
        if search:
            search_terms = InputValidator.sanitize_search_query(search.strip())
            if search_terms:
                search_keywords = [kw.strip() for kw in search_terms.split(',') if kw.strip()]
                
                or_query = [
                    {"name": {"$regex": search_terms, "$options": "i"}},
                    {"description": {"$regex": search_terms, "$options": "i"}},
                ]
                
                # Add keyword searches
                for keyword in search_keywords[:5]:  # Limit to 5 keywords
                    or_query.extend([
                        {"keywords": {"$elemMatch": {"$regex": keyword, "$options": "i"}}},
                        {"tags": {"$elemMatch": {"$regex": keyword, "$options": "i"}}}
                    ])
                
                query["$or"] = or_query
        
        # Calculate pagination
        skip = (page - 1) * limit
        
        # ✅ Optimized aggregation pipeline with projections
        pipeline = [
            {"$match": query},
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
            }
        ]
        
        # ✅ Field projection for reduced payload
        if fields:
            field_list = [f.strip() for f in fields.split(',')]
            projection = {field: 1 for field in field_list}
            projection["_id"] = 1  # Always include ID
            pipeline.append({"$project": projection})
        else:
            # Remove lookup data
            pipeline.append({
                "$project": {
                    "category_data": 0,
                    "brand_data": 0
                }
            })
        
        # Sort and paginate
        pipeline.extend([
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
        ])
        
        # ✅ Execute aggregation
        result = await db.aggregate("products", pipeline)
        
        if not result:
            products = []
            total = 0
        else:
            products = result[0].get("products", [])
            total_count = result[0].get("totalCount", [])
            total = total_count[0]["count"] if total_count else 0
        
        # ✅ Process products with optimized serialization
        include_full = page == 1  # Full details only on first page
        processed_products = []
        
        for product in products:
            try:
                serialized_product = serialize_product_for_mobile(
                    product, 
                    include_full_details=include_full
                )
                
                if serialized_product and serialized_product.get("id"):
                    processed_products.append(serialized_product)
                else:
                    logger.warning(f"⚠️ Product missing id: {product.get('name')}")
                
            except Exception as process_error:
                logger.error(f"❌ Error processing product: {process_error}")
                continue

        logger.info(f"✅ Returning {len(processed_products)} products")
        
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
        
        # ✅ Cache the result (shorter TTL for search, longer for filters)
        if not search:
            ttl = CacheTTL.PRODUCT_LIST if page > 1 else CacheTTL.PRODUCT_LIST * 3
            try:
                await redis.set(cache_key, response_data, ttl, use_l1=(page == 1))
                logger.info(f"💾 Cached result: {cache_key[:30]}... (TTL: {ttl}s, L1: {page == 1})")
            except Exception as cache_error:
                logger.warning(f"⚠️ Cache write error: {cache_error}")
        print(response_data)
        return response_data
        
    except Exception as e:
        logger.error(f"❌ Get products error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get products"
        )

@router.get("/{product_id}")
async def get_product(
    product_id: str,
    db: DatabaseManager = Depends(get_database)
):
    """
    Get specific product by ID with caching
    """
    try:
        logger.info(f"🔍 Getting product: {product_id}")
        
        if not product_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid product ID"
            )
        
        redis = get_redis()
        cache_key = CacheKeys.product_detail(product_id)
        
        # ✅ Multi-layer cache check
        try:
            cached_product = await redis.get(cache_key, use_l1=True)
            if cached_product:
                logger.info(f"⚡ Cache HIT: {cache_key}")
                return cached_product
        except Exception as cache_error:
            logger.warning(f"⚠️ Cache read error: {cache_error}")
        
        logger.info(f"💾 Cache MISS: {cache_key}")
        
        # ✅ Optimized aggregation with single query
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
        
        # ✅ Serialize with full details
        product = serialize_product_for_mobile(products[0], include_full_details=True)
        
        if not product or not product.get("id"):
            logger.error(f"❌ Product {product_id} missing id after serialization")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Product data error"
            )
        
        # ✅ Cache for longer (1 hour) with L1
        try:
            await redis.set(cache_key, product, CacheTTL.PRODUCT_DETAIL, use_l1=True)
            logger.info(f"💾 Cached product: {cache_key} (L1 + L2)")
        except Exception as cache_error:
            logger.warning(f"⚠️ Cache write error: {cache_error}")
        
        logger.info(f"✅ Returning product: {product.get('name')}")
        return product
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get product error: {e}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get product"
        )

@router.post("/invalidate-cache")
async def invalidate_product_cache(
    product_ids: Optional[list[str]] = None,
    current_user = Depends(get_current_admin)
):
    """
    Admin endpoint to invalidate product caches
    Use after product updates
    """
    try:
        redis = get_redis()
        
        if product_ids:
            # Invalidate specific products
            for product_id in product_ids:
                cache_key = CacheKeys.product_detail(product_id)
                await redis.delete(cache_key)
            
            logger.info(f"✅ Invalidated {len(product_ids)} product caches")
            return {
                "message": f"Invalidated {len(product_ids)} product caches",
                "product_ids": product_ids
            }
        else:
            # Invalidate all product caches
            await redis.delete_pattern(f"{CacheKeys.PRODUCT}:*")
            await redis.delete_pattern(f"{CacheKeys.PRODUCTS_LIST}:*")
            
            logger.info("✅ Invalidated all product caches")
            return {"message": "Invalidated all product caches"}
        
    except Exception as e:
        logger.error(f"❌ Cache invalidation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to invalidate cache"
        )