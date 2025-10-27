from fastapi import FastAPI
from app.middleware.setup import setup_middleware
from app.routes import (
    categories, products, orders, auth, cart, brands, 
    settings as settings_route, address, support, delivery, 
    coupons, shop_status, notifications, porter, metrics
)
from datetime import datetime
import os

def create_customer_app() -> FastAPI:
    """
    Create customer-facing application
    Includes all routes and middleware
    """
    app = FastAPI(
        title="SmartBag Customer API",
        version='2.1.0',
        description="Optimized e-commerce API for mobile and web",
        docs_url="/docs" if os.getenv('ENVIRONMENT') != 'Production' else None
    )

    # ✅ Setup all middleware (security, monitoring, rate limiting, etc.)
    setup_middleware(app)

    # ✅ Include all routes with proper prefixes
    app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    app.include_router(products.router, prefix="/products", tags=["Products"])
    app.include_router(categories.router, prefix="/categories", tags=["Categories"])
    app.include_router(brands.router, prefix="/brands", tags=["Brands"]) 
    app.include_router(orders.router, prefix="/orders", tags=["Orders"])
    app.include_router(cart.router, prefix="/cart", tags=["Cart"])
    app.include_router(settings_route.router, prefix="/settings", tags=["Settings"])  
    app.include_router(address.router, prefix="/address", tags=["Address"])
    app.include_router(support.router, prefix="/support", tags=["Support"])
    app.include_router(delivery.router, prefix="/delivery", tags=["Delivery"])
    app.include_router(coupons.router, prefix="/promocodes", tags=["Coupons"])
    app.include_router(shop_status.router, prefix="/shop", tags=["Shop Status"])
    app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
    app.include_router(metrics.router, prefix="/metrics", tags=["Metrics"])
    app.include_router(porter.router, prefix="/porter", tags=["Porter"])
    
    @app.get("/")
    async def root():
        return {
            "message": "SmartBag Customer API", 
            "status": "healthy",
            "version": "2.1.0"
        }
    
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.1.0"
        }

    return app