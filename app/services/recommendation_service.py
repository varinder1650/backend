# app/services/recommendation_service.py
"""
ML-powered recommendation service for SmartBag
Handles personalized product recommendations and collaborative filtering
"""

import asyncio
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict, Counter
import logging
from bson import ObjectId

from app.cache.redis_manager import get_redis
from db.db_manager import DatabaseManager, get_database

logger = logging.getLogger(__name__)

class RecommendationService:
    def __init__(self):
        self.redis = get_redis()
        # Recommendation types
        self.RECOMMENDATION_TYPES = {
            "trending": "trending_products",
            "personalized": "personalized_for_user",
            "collaborative": "users_also_bought",
            "similar": "similar_products",
            "category_based": "category_recommendations",
            "price_based": "price_similar"
        }
    
    async def get_recommendations(
        self,
        user_id: str,
        recommendation_type: str = "personalized",
        limit: int = 10,
        category_id: str = None,
        product_id: str = None
    ) -> List[Dict[str, Any]]:
        """Get recommendations based on type"""
        
        # Try cache first
        cache_key = f"recommendations:{recommendation_type}:{user_id}:{category_id}:{product_id}:{limit}"
        cached_recommendations = await self.redis.get(cache_key)
        
        if cached_recommendations:
            logger.info(f"Recommendation cache HIT for {cache_key}")
            return cached_recommendations
        
        # Generate recommendations based on type
        if recommendation_type == "trending":
            recommendations = await self.get_trending_products(limit)
        elif recommendation_type == "personalized":
            recommendations = await self.get_personalized_recommendations(user_id, limit)
        elif recommendation_type == "collaborative":
            recommendations = await self.get_collaborative_filtering_recommendations(user_id, limit)
        elif recommendation_type == "similar" and product_id:
            recommendations = await self.get_similar_products(product_id, limit)
        elif recommendation_type == "category_based" and category_id:
            recommendations = await self.get_category_based_recommendations(category_id, user_id, limit)
        else:
            recommendations = await self.get_trending_products(limit)
        
        # Cache recommendations with different TTLs based on type
        ttl_mapping = {
            "trending": 3600,      # 1 hour for trending
            "personalized": 7200,  # 2 hours for personalized
            "collaborative": 14400, # 4 hours for collaborative
            "similar": 86400,      # 24 hours for similar products
            "category_based": 7200  # 2 hours for category-based
        }
        
        ttl = ttl_mapping.get(recommendation_type, 3600)
        await self.redis.set(cache_key, recommendations, ttl)
        
        return recommendations
    
    async def get_trending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get trending products based on recent orders and views"""
        try:
            db = get_database()
            
            # Get products ordered in last 7 days
            week_ago = datetime.utcnow() - timedelta(days=7)
            
            pipeline = [
                {
                    "$match": {
                        "created_at": {"$gte": week_ago},
                        "order_status": {"$nin": ["cancelled", "refunded"]}
                    }
                },
                {"$unwind": "$items"},
                {
                    "$group": {
                        "_id": "$items.product",
                        "order_count": {"$sum": "$items.quantity"},
                        "total_revenue": {"$sum": {"$multiply": ["$items.quantity", "$items.price"]}},
                        "unique_customers": {"$addToSet": "$user"}
                    }
                },
                {
                    "$addFields": {
                        "customer_count": {"$size": "$unique_customers"},
                        "trend_score": {
                            "$multiply": [
                                "$order_count",
                                {"$divide": ["$customer_count", "$order_count"]}  # Diversity factor
                            ]
                        }
                    }
                },
                {"$sort": {"trend_score": -1}},
                {"$limit": limit * 2},  # Get more to filter active products
                {
                    "$lookup": {
                        "from": "products",
                        "localField": "_id",
                        "foreignField": "_id",
                        "as": "product"
                    }
                },
                {"$unwind": "$product"},
                {"$match": {"product.is_active": True, "product.stock": {"$gt": 0}}},
                {"$limit": limit}
            ]
            
            trending_data = await db.aggregate("orders", pipeline)
            
            recommendations = []
            for item in trending_data:
                product = item["product"]
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "trend_score": item["trend_score"],
                    "order_count": item["order_count"],
                    "reason": "Trending now"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting trending products: {e}")
            return await self.get_fallback_recommendations(limit)
    
    async def get_personalized_recommendations(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get personalized recommendations based on user history"""
        try:
            db = get_database()
            
            # Get user's order history
            user_orders = await db.find_many(
                "orders",
                {"user": ObjectId(user_id), "order_status": {"$nin": ["cancelled", "refunded"]}},
                sort=[("created_at", -1)]
            )
            
            if not user_orders:
                return await self.get_trending_products(limit)
            
            # Extract user preferences
            category_scores = defaultdict(float)
            brand_scores = defaultdict(float)
            price_ranges = []
            purchased_products = set()
            
            for order in user_orders:
                order_weight = 1.0  # Could decay based on age
                
                for item in order.get("items", []):
                    product_id = str(item["product"])
                    purchased_products.add(product_id)
                    price_ranges.append(item["price"])
                    
                    # Get product details for category/brand
                    product = await db.find_one("products", {"_id": ObjectId(product_id)})
                    if product:
                        if product.get("category"):
                            category_scores[str(product["category"])] += order_weight * item["quantity"]
                        if product.get("brand"):
                            brand_scores[str(product["brand"])] += order_weight * item["quantity"]
            
            # Calculate price preference range
            if price_ranges:
                avg_price = np.mean(price_ranges)
                price_std = np.std(price_ranges)
                min_price = max(0, avg_price - price_std)
                max_price = avg_price + price_std
            else:
                min_price, max_price = 0, 1000
            
            # Find recommendations based on preferences
            top_categories = sorted(category_scores.items(), key=lambda x: x[1], reverse=True)[:3]
            top_brands = sorted(brand_scores.items(), key=lambda x: x[1], reverse=True)[:3]
            
            # Build recommendation query
            match_conditions = []
            
            if top_categories:
                match_conditions.append({
                    "category": {"$in": [ObjectId(cat[0]) for cat in top_categories]}
                })
            
            if top_brands:
                match_conditions.append({
                    "brand": {"$in": [ObjectId(brand[0]) for brand in top_brands]}
                })
            
            # Price range condition
            match_conditions.append({
                "price": {"$gte": min_price, "$lte": max_price}
            })
            
            # Exclude already purchased products
            if purchased_products:
                match_conditions.append({
                    "_id": {"$nin": [ObjectId(pid) for pid in purchased_products]}
                })
            
            pipeline = [
                {
                    "$match": {
                        "$and": [
                            {"is_active": True, "stock": {"$gt": 0}},
                            {"$or": match_conditions[:2]} if len(match_conditions) > 1 else match_conditions[0]
                        ] + match_conditions[2:]  # Add price and exclusion filters
                    }
                },
                {
                    "$addFields": {
                        "recommendation_score": {
                            "$add": [
                                {"$multiply": [{"$ifNull": ["$rating", 0]}, 2]},
                                {"$divide": [{"$ifNull": ["$review_count", 0]}, 10]},
                                {"$subtract": [100, {"$divide": ["$price", 10]}]}  # Price factor
                            ]
                        }
                    }
                },
                {"$sort": {"recommendation_score": -1}},
                {"$limit": limit}
            ]
            
            recommended_products = await db.aggregate("products", pipeline)
            
            recommendations = []
            for product in recommended_products:
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "recommendation_score": product["recommendation_score"],
                    "reason": "Recommended for you"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting personalized recommendations: {e}")
            return await self.get_trending_products(limit)
    
    async def get_collaborative_filtering_recommendations(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recommendations based on similar users' purchases"""
        try:
            db = get_database()
            
            # Get user's purchased products
            user_products = await self.get_user_product_set(user_id, db)
            
            if not user_products:
                return await self.get_trending_products(limit)
            
            # Find users with similar purchase patterns
            pipeline = [
                {"$match": {"order_status": {"$nin": ["cancelled", "refunded"]}}},
                {"$unwind": "$items"},
                {
                    "$group": {
                        "_id": "$user",
                        "products": {"$addToSet": "$items.product"}
                    }
                },
                {"$match": {"_id": {"$ne": ObjectId(user_id)}}},
                {
                    "$addFields": {
                        "common_products": {
                            "$size": {
                                "$setIntersection": [
                                    "$products",
                                    [ObjectId(pid) for pid in user_products]
                                ]
                            }
                        },
                        "total_products": {"$size": "$products"}
                    }
                },
                {"$match": {"common_products": {"$gte": 2}}},  # At least 2 common products
                {
                    "$addFields": {
                        "similarity_score": {
                            "$divide": ["$common_products", {"$add": ["$total_products", len(user_products)]}]
                        }
                    }
                },
                {"$sort": {"similarity_score": -1}},
                {"$limit": 50}  # Top 50 similar users
            ]
            
            similar_users = await db.aggregate("orders", pipeline)
            
            if not similar_users:
                return await self.get_trending_products(limit)
            
            # Get products bought by similar users but not by current user
            similar_user_ids = [user["_id"] for user in similar_users]
            
            recommendation_pipeline = [
                {
                    "$match": {
                        "user": {"$in": similar_user_ids},
                        "order_status": {"$nin": ["cancelled", "refunded"]}
                    }
                },
                {"$unwind": "$items"},
                {
                    "$match": {
                        "items.product": {"$nin": [ObjectId(pid) for pid in user_products]}
                    }
                },
                {
                    "$group": {
                        "_id": "$items.product",
                        "recommendation_count": {"$sum": 1},
                        "avg_price": {"$avg": "$items.price"},
                        "buyers": {"$addToSet": "$user"}
                    }
                },
                {
                    "$addFields": {
                        "buyer_count": {"$size": "$buyers"},
                        "popularity_score": {"$multiply": ["$recommendation_count", "$buyer_count"]}
                    }
                },
                {"$sort": {"popularity_score": -1}},
                {"$limit": limit * 2},
                {
                    "$lookup": {
                        "from": "products",
                        "localField": "_id",
                        "foreignField": "_id",
                        "as": "product"
                    }
                },
                {"$unwind": "$product"},
                {"$match": {"product.is_active": True, "product.stock": {"$gt": 0}}},
                {"$limit": limit}
            ]
            
            recommended_products = await db.aggregate("orders", recommendation_pipeline)
            
            recommendations = []
            for item in recommended_products:
                product = item["product"]
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "recommendation_count": item["recommendation_count"],
                    "buyer_count": item["buyer_count"],
                    "reason": f"Customers who bought similar items also bought this"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting collaborative recommendations: {e}")
            return await self.get_trending_products(limit)
    
    async def get_similar_products(self, product_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get products similar to given product"""
        try:
            db = get_database()
            
            # Get the reference product
            reference_product = await db.find_one("products", {"_id": ObjectId(product_id)})
            
            if not reference_product:
                return await self.get_trending_products(limit)
            
            # Find similar products based on category, brand, price range
            price = reference_product["price"]
            price_range_min = price * 0.7  # 30% lower
            price_range_max = price * 1.3  # 30% higher
            
            pipeline = [
                {
                    "$match": {
                        "_id": {"$ne": ObjectId(product_id)},
                        "is_active": True,
                        "stock": {"$gt": 0},
                        "$or": [
                            {"category": reference_product.get("category")},
                            {"brand": reference_product.get("brand")},
                            {"price": {"$gte": price_range_min, "$lte": price_range_max}}
                        ]
                    }
                },
                {
                    "$addFields": {
                        "similarity_score": {
                            "$add": [
                                {"$cond": [{"$eq": ["$category", reference_product.get("category")]}, 3, 0]},
                                {"$cond": [{"$eq": ["$brand", reference_product.get("brand")]}, 2, 0]},
                                {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {"$gte": ["$price", price_range_min]},
                                                {"$lte": ["$price", price_range_max]}
                                            ]
                                        },
                                        1,
                                        0
                                    ]
                                },
                                {"$divide": [{"$ifNull": ["$rating", 0]}, 2]}
                            ]
                        }
                    }
                },
                {"$sort": {"similarity_score": -1, "rating": -1}},
                {"$limit": limit}
            ]
            
            similar_products = await db.aggregate("products", pipeline)
            
            recommendations = []
            for product in similar_products:
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "similarity_score": product["similarity_score"],
                    "reason": "Similar to what you viewed"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting similar products: {e}")
            return await self.get_fallback_recommendations(limit)
    
    async def get_category_based_recommendations(self, category_id: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recommendations from specific category based on user preferences"""
        try:
            db = get_database()
            
            # Get user's price preferences in this category
            user_category_orders = await db.find_many(
                "orders",
                {
                    "user": ObjectId(user_id),
                    "order_status": {"$nin": ["cancelled", "refunded"]}
                }
            )
            
            category_prices = []
            for order in user_category_orders:
                for item in order.get("items", []):
                    # Check if item belongs to this category
                    product = await db.find_one("products", {
                        "_id": ObjectId(str(item["product"])),
                        "category": ObjectId(category_id)
                    })
                    if product:
                        category_prices.append(item["price"])
            
            # Calculate preferred price range
            if category_prices:
                avg_price = np.mean(category_prices)
                price_preference_weight = 2.0
            else:
                avg_price = None
                price_preference_weight = 1.0
            
            pipeline = [
                {
                    "$match": {
                        "category": ObjectId(category_id),
                        "is_active": True,
                        "stock": {"$gt": 0}
                    }
                },
                {
                    "$addFields": {
                        "category_score": {
                            "$add": [
                                {"$multiply": [{"$ifNull": ["$rating", 0]}, 3]},
                                {"$divide": [{"$ifNull": ["$review_count", 0]}, 5]},
                                {
                                    "$cond": [
                                        {"$ne": [avg_price, None]},
                                        {
                                            "$multiply": [
                                                price_preference_weight,
                                                {"$subtract": [10, {"$abs": {"$subtract": ["$price", avg_price]}}]}
                                            ]
                                        },
                                        {"$subtract": [50, {"$divide": ["$price", 10]}]}
                                    ]
                                }
                            ]
                        }
                    }
                },
                {"$sort": {"category_score": -1}},
                {"$limit": limit}
            ]
            
            category_products = await db.aggregate("products", pipeline)
            
            recommendations = []
            for product in category_products:
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "category_score": product["category_score"],
                    "reason": "Popular in this category"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting category recommendations: {e}")
            return await self.get_fallback_recommendations(limit)
    
    async def get_user_product_set(self, user_id: str, db: DatabaseManager) -> set:
        """Get set of products purchased by user"""
        try:
            user_orders = await db.find_many(
                "orders",
                {"user": ObjectId(user_id), "order_status": {"$nin": ["cancelled", "refunded"]}}
            )
            
            products = set()
            for order in user_orders:
                for item in order.get("items", []):
                    products.add(str(item["product"]))
            
            return products
            
        except Exception as e:
            logger.error(f"Error getting user products: {e}")
            return set()
    
    async def get_fallback_recommendations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fallback recommendations when other methods fail"""
        try:
            db = get_database()
            
            # Get highest rated, most reviewed products
            pipeline = [
                {
                    "$match": {
                        "is_active": True,
                        "stock": {"$gt": 0},
                        "rating": {"$gte": 4.0}
                    }
                },
                {
                    "$addFields": {
                        "fallback_score": {
                            "$add": [
                                {"$multiply": ["$rating", 10]},
                                {"$divide": [{"$ifNull": ["$review_count", 0]}, 5]}
                            ]
                        }
                    }
                },
                {"$sort": {"fallback_score": -1}},
                {"$limit": limit}
            ]
            
            products = await db.aggregate("products", pipeline)
            
            recommendations = []
            for product in products:
                recommendations.append({
                    "product_id": str(product["_id"]),
                    "name": product["name"],
                    "price": product["price"],
                    "images": product.get("images", []),
                    "rating": product.get("rating", 0),
                    "reason": "Highly rated"
                })
            
            return recommendations
            
        except Exception as e:
            logger.error(f"Error getting fallback recommendations: {e}")
            return []
    
    async def track_user_interaction(self, user_id: str, interaction_type: str, product_id: str, metadata: Dict = None):
        """Track user interactions for improving recommendations"""
        try:
            interaction_data = {
                "user_id": user_id,
                "product_id": product_id,
                "interaction_type": interaction_type,  # view, click, add_to_cart, purchase
                "timestamp": datetime.utcnow().isoformat(),
                "metadata": metadata or {}
            }
            
            # Store in Redis with expiry
            interaction_key = f"interaction:{user_id}:{product_id}:{int(datetime.utcnow().timestamp())}"
            await self.redis.set(interaction_key, interaction_data, 86400 * 30)  # 30 days
            
            # Update user interaction counters
            counter_key = f"user_interactions:{user_id}"
            await self.redis.increment(f"{counter_key}:{interaction_type}")
            
        except Exception as e:
            logger.error(f"Error tracking interaction: {e}")

# Global recommendation service
recommendation_service = RecommendationService()

def get_recommendation_service() -> RecommendationService:
    return recommendation_service

# Usage examples for your routes:
"""
# Add to your products.py or create recommendations.py

from app.services.recommendation_service import get_recommendation_service

@router.get("/recommendations/{recommendation_type}")
async def get_product_recommendations(
    recommendation_type: str,
    limit: int = Query(10, ge=1, le=50),
    category_id: Optional[str] = Query(None),
    product_id: Optional[str] = Query(None),
    current_user: UserinDB = Depends(current_active_user)
):
    recommendation_service = get_recommendation_service()
    
    recommendations = await recommendation_service.get_recommendations(
        user_id=current_user.id,
        recommendation_type=recommendation_type,
        limit=limit,
        category_id=category_id,
        product_id=product_id
    )
    
    return {
        "recommendations": recommendations,
        "type": recommendation_type,
        "count": len(recommendations)
    }

@router.post("/track-interaction")
async def track_product_interaction(
    interaction_data: dict,
    current_user: UserinDB = Depends(current_active_user)
):
    recommendation_service = get_recommendation_service()
    
    await recommendation_service.track_user_interaction(
        user_id=current_user.id,
        interaction_type=interaction_data.get("type", "view"),
        product_id=interaction_data["product_id"],
        metadata=interaction_data.get("metadata", {})
    )
    
    return {"message": "Interaction tracked"}
"""