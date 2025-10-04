# app/services/search_service.py
"""
Elasticsearch integration for advanced product search
Install: pip install elasticsearch[async] aiofiles
"""

from elasticsearch import AsyncElasticsearch
from typing import List, Dict, Any, Optional
import logging
import json
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class SearchService:
    def __init__(self):
        self.client = None
        self.index_name = "smartbag_products"
    
    async def init_elasticsearch(self):
        """Initialize Elasticsearch connection"""
        try:
            # self.client = AsyncElasticsearch([
            #     {'host': os.getenv('ELASTICSEARCH_HOST', 'localhost'), 'port': 9200}
            # ])
            
            self.client = AsyncElasticsearch(
                hosts=[f"http://{os.getenv('ELASTICSEARCH_HOST', 'localhost')}:9200"]
            )
            # Test connection
            await self.client.ping()
            
            # Create index if it doesn't exist
            await self.create_product_index()
            
            logger.info("Elasticsearch initialized successfully")
        except Exception as e:
            logger.error(f"Elasticsearch initialization failed: {e}")
            raise
    
    async def create_product_index(self):
        """Create product index with proper mappings"""
        mapping = {
            "mappings": {
                "properties": {
                    "name": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "keyword": {"type": "keyword"},
                            "suggest": {
                                "type": "search_as_you_type"
                            }
                        }
                    },
                    "description": {
                        "type": "text",
                        "analyzer": "standard"
                    },
                    "category": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "keyword"},
                            "name": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}}
                            }
                        }
                    },
                    "brand": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "keyword"},
                            "name": {
                                "type": "text",
                                "fields": {"keyword": {"type": "keyword"}}
                            }
                        }
                    },
                    "price": {"type": "double"},
                    "stock": {"type": "integer"},
                    "keywords": {
                        "type": "text",
                        "analyzer": "keyword"
                    },
                    "images": {"type": "text"},
                    "is_active": {"type": "boolean"},
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                    "rating": {"type": "float"},
                    "review_count": {"type": "integer"}
                }
            }
        }
        
        try:
            # Check if index exists
            if not await self.client.indices.exists(index=self.index_name):
                await self.client.indices.create(
                    index=self.index_name,
                    body=mapping
                )
                logger.info(f"Created Elasticsearch index: {self.index_name}")
        except Exception as e:
            logger.error(f"Error creating index: {e}")
    
    async def index_product(self, product: Dict[str, Any]):
        """Index a single product"""
        try:
            # Transform MongoDB document for Elasticsearch
            es_doc = {
                "name": product.get("name", ""),
                "description": product.get("description", ""),
                "category": {
                    "id": str(product.get("category", {}).get("_id", "")),
                    "name": product.get("category", {}).get("name", "")
                },
                "brand": {
                    "id": str(product.get("brand", {}).get("_id", "")),
                    "name": product.get("brand", {}).get("name", "")
                },
                "price": float(product.get("price", 0)),
                "stock": int(product.get("stock", 0)),
                "keywords": product.get("keywords", []),
                "images": product.get("images", []),
                "is_active": product.get("is_active", True),
                "created_at": product.get("created_at", datetime.utcnow()),
                "updated_at": product.get("updated_at", datetime.utcnow()),
                "rating": float(product.get("rating", 0)),
                "review_count": int(product.get("review_count", 0))
            }
            
            await self.client.index(
                index=self.index_name,
                id=str(product["_id"]),
                body=es_doc
            )
            
        except Exception as e:
            logger.error(f"Error indexing product {product.get('_id')}: {e}")
    
    async def bulk_index_products(self, products: List[Dict[str, Any]]):
        """Bulk index multiple products"""
        try:
            actions = []
            for product in products:
                es_doc = {
                    "name": product.get("name", ""),
                    "description": product.get("description", ""),
                    "category": {
                        "id": str(product.get("category", {}).get("_id", "")),
                        "name": product.get("category", {}).get("name", "")
                    },
                    "brand": {
                        "id": str(product.get("brand", {}).get("_id", "")),
                        "name": product.get("brand", {}).get("name", "")
                    },
                    "price": float(product.get("price", 0)),
                    "stock": int(product.get("stock", 0)),
                    "keywords": product.get("keywords", []),
                    "images": product.get("images", []),
                    "is_active": product.get("is_active", True),
                    "created_at": product.get("created_at", datetime.utcnow()),
                    "updated_at": product.get("updated_at", datetime.utcnow()),
                    "rating": float(product.get("rating", 0)),
                    "review_count": int(product.get("review_count", 0))
                }
                
                actions.extend([
                    {"index": {"_index": self.index_name, "_id": str(product["_id"])}},
                    es_doc
                ])
            
            if actions:
                response = await self.client.bulk(body=actions)
                if response.get("errors"):
                    logger.error(f"Bulk indexing errors: {response['errors']}")
                else:
                    logger.info(f"Successfully indexed {len(products)} products")
                    
        except Exception as e:
            logger.error(f"Bulk indexing error: {e}")
    
    async def search_products(
        self,
        query: str = "",
        category: str = None,
        brand: str = None,
        min_price: float = None,
        max_price: float = None,
        in_stock: bool = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """Advanced product search with filters"""
        try:
            # Build Elasticsearch query
            search_body = {
                "size": limit,
                "from": (page - 1) * limit,
                "query": {
                    "bool": {
                        "must": [],
                        "filter": [
                            {"term": {"is_active": True}}
                        ]
                    }
                },
                "sort": [
                    {"_score": {"order": "desc"}},
                    {"rating": {"order": "desc"}},
                    {"created_at": {"order": "desc"}}
                ],
                "aggs": {
                    "categories": {
                        "terms": {"field": "category.name.keyword", "size": 20}
                    },
                    "brands": {
                        "terms": {"field": "brand.name.keyword", "size": 20}
                    },
                    "price_ranges": {
                        "range": {
                            "field": "price",
                            "ranges": [
                                {"to": 25, "key": "Under $25"},
                                {"from": 25, "to": 50, "key": "$25 - $50"},
                                {"from": 50, "to": 100, "key": "$50 - $100"},
                                {"from": 100, "key": "Over $100"}
                            ]
                        }
                    }
                }
            }
            
            # Add text search
            if query:
                search_body["query"]["bool"]["must"].append({
                    "multi_match": {
                        "query": query,
                        "fields": [
                            "name^3",
                            "name.suggest^2",
                            "description^1",
                            "keywords^2",
                            "category.name^1.5",
                            "brand.name^1.5"
                        ],
                        "type": "best_fields",
                        "fuzziness": "AUTO"
                    }
                })
            else:
                search_body["query"]["bool"]["must"].append({
                    "match_all": {}
                })
            
            # Add filters
            if category:
                search_body["query"]["bool"]["filter"].append({
                    "term": {"category.name.keyword": category}
                })
            
            if brand:
                search_body["query"]["bool"]["filter"].append({
                    "term": {"brand.name.keyword": brand}
                })
            
            if min_price is not None or max_price is not None:
                price_range = {}
                if min_price is not None:
                    price_range["gte"] = min_price
                if max_price is not None:
                    price_range["lte"] = max_price
                
                search_body["query"]["bool"]["filter"].append({
                    "range": {"price": price_range}
                })
            
            if in_stock:
                search_body["query"]["bool"]["filter"].append({
                    "range": {"stock": {"gt": 0}}
                })
            
            # Execute search
            response = await self.client.search(
                index=self.index_name,
                body=search_body
            )
            
            # Process results
            hits = response["hits"]["hits"]
            total = response["hits"]["total"]["value"]
            
            products = []
            for hit in hits:
                product = hit["_source"]
                product["_id"] = hit["_id"]
                product["_score"] = hit["_score"]
                products.append(product)
            
            # Process aggregations
            facets = {}
            if "aggregations" in response:
                aggs = response["aggregations"]
                facets = {
                    "categories": [
                        {"name": bucket["key"], "count": bucket["doc_count"]}
                        for bucket in aggs["categories"]["buckets"]
                    ],
                    "brands": [
                        {"name": bucket["key"], "count": bucket["doc_count"]}
                        for bucket in aggs["brands"]["buckets"]
                    ],
                    "price_ranges": [
                        {"range": bucket["key"], "count": bucket["doc_count"]}
                        for bucket in aggs["price_ranges"]["buckets"]
                    ]
                }
            
            return {
                "products": products,
                "total": total,
                "page": page,
                "limit": limit,
                "total_pages": (total + limit - 1) // limit,
                "facets": facets,
                "query_time": response["took"]
            }
            
        except Exception as e:
            logger.error(f"Search error: {e}")
            return {
                "products": [],
                "total": 0,
                "page": page,
                "limit": limit,
                "total_pages": 0,
                "facets": {},
                "error": str(e)
            }
    
    async def suggest_products(self, query: str, size: int = 10) -> List[str]:
        """Get search suggestions"""
        try:
            search_body = {
                "suggest": {
                    "product_suggest": {
                        "prefix": query,
                        "completion": {
                            "field": "name.suggest",
                            "size": size
                        }
                    }
                }
            }
            
            response = await self.client.search(
                index=self.index_name,
                body=search_body
            )
            
            suggestions = []
            if "suggest" in response:
                for suggestion in response["suggest"]["product_suggest"]:
                    for option in suggestion["options"]:
                        suggestions.append(option["text"])
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Suggestion error: {e}")
            return []
    
    async def close(self):
        """Close Elasticsearch connection"""
        if self.client:
            await self.client.close()

# Global search service instance
search_service = SearchService()

def get_search_service() -> SearchService:
    return search_service