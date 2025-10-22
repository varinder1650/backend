# app/cache/cache_config.py
"""
Centralized cache TTL configuration
Prevents magic numbers scattered throughout codebase
"""
import os

class CacheTTL:
    """Cache Time-To-Live constants (in seconds)"""
    
    # Product caching
    PRODUCT_DETAIL = int(os.getenv('CACHE_TTL_PRODUCT_DETAIL', 3600))      # 1 hour
    PRODUCT_LIST = int(os.getenv('CACHE_TTL_PRODUCT_LIST', 600))           # 10 minutes
    PRODUCT_SEARCH = 300                                                     # 5 minutes
    
    # Cart caching
    CART = int(os.getenv('CACHE_TTL_CART', 1800))                          # 30 minutes
    CART_COUNT = 600                                                         # 10 minutes
    
    # Category & Brand caching
    CATEGORIES = int(os.getenv('CACHE_TTL_CATEGORIES', 7200))              # 2 hours
    BRANDS = int(os.getenv('CACHE_TTL_BRANDS', 7200))                      # 2 hours
    CATEGORY_STATS = 1800                                                    # 30 minutes
    
    # Order caching
    USER_ORDERS = int(os.getenv('CACHE_TTL_USER_ORDERS', 900))             # 15 minutes
    ORDER_DETAIL = 1800                                                      # 30 minutes
    ACTIVE_ORDER = 60                                                        # 1 minute (real-time)
    
    # Shop & Settings
    SHOP_STATUS = int(os.getenv('CACHE_TTL_SHOP_STATUS', 300))             # 5 minutes
    APP_SETTINGS = 3600                                                      # 1 hour
    
    # Inventory
    INVENTORY = int(os.getenv('CACHE_TTL_INVENTORY', 60))                  # 1 minute
    STOCK_LEVEL = 30                                                         # 30 seconds
    
    # User & Auth
    USER_PROFILE = 1800                                                      # 30 minutes
    USER_ADDRESSES = 3600                                                    # 1 hour
    
    # Recommendations & Analytics
    TRENDING_PRODUCTS = 900                                                  # 15 minutes
    RECOMMENDATIONS = 1800                                                   # 30 minutes
    
    # Search
    SEARCH_SUGGESTIONS = 3600                                                # 1 hour
    
    # Notifications
    NOTIFICATIONS = 300                                                      # 5 minutes
    
    # Rate Limiting
    RATE_LIMIT_WINDOW = 60                                                   # 1 minute
    
    # Session
    SESSION = 86400                                                          # 24 hours
    
    # Materialized Views
    MATERIALIZED_VIEW = 900                                                  # 15 minutes

class CacheKeys:
    """Standardized cache key prefixes"""
    
    PRODUCT = "product"
    PRODUCTS_LIST = "products_list"
    CART = "cart"
    CATEGORY = "category"
    BRAND = "brand"
    ORDER = "order"
    USER = "user"
    INVENTORY = "inventory"
    TRENDING = "trending"
    RECOMMENDATIONS = "recommendations"
    SHOP_STATUS = "shop_status"
    SESSION = "session"
    RATE_LIMIT = "rate_limit"
    MATERIALIZED = "materialized"
    
    @staticmethod
    def product_detail(product_id: str) -> str:
        return f"{CacheKeys.PRODUCT}:{product_id}"
    
    @staticmethod
    def product_list(**filters) -> str:
        """Generate cache key for product listing with filters"""
        import hashlib
        import json
        filter_str = json.dumps(filters, sort_keys=True)
        filter_hash = hashlib.md5(filter_str.encode()).hexdigest()[:8]
        return f"{CacheKeys.PRODUCTS_LIST}:{filter_hash}"
    
    @staticmethod
    def user_cart(user_id: str) -> str:
        return f"{CacheKeys.CART}:{user_id}"
    
    @staticmethod
    def user_orders(user_id: str, page: int = 1) -> str:
        return f"{CacheKeys.ORDER}:{user_id}:page{page}"
    
    @staticmethod
    def category_list() -> str:
        return f"{CacheKeys.CATEGORY}:all"
    
    @staticmethod
    def brand_list() -> str:
        return f"{CacheKeys.BRAND}:all"
    
    @staticmethod
    def stock_level(product_id: str) -> str:
        return f"{CacheKeys.INVENTORY}:stock:{product_id}"
    
    @staticmethod
    def reserved_stock(product_id: str) -> str:
        return f"{CacheKeys.INVENTORY}:reserved:{product_id}"