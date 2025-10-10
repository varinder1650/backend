"""
SmartBag Test Suite Configuration
"""
import pytest
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime, timedelta
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from bson import ObjectId

# Add parent directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

load_dotenv()

# CRITICAL: Set environment variables BEFORE any app imports
os.environ['MONGO_URI'] = 'mongodb://localhost:27017'
os.environ['DB_NAME'] = 'smartbag_test'
os.environ['REDIS_URL'] = 'redis://localhost:6379/1'
os.environ['ENVIRONMENT'] = 'Testing'

@pytest.fixture(scope="function")
async def test_db():
    """Create test database connection"""
    client = AsyncIOMotorClient('mongodb://localhost:27017')
    db = client['smartbag_test']
    
    # Clean before test
    collections = await db.list_collection_names()
    for collection in collections:
        if not collection.startswith('system.'):
            await db[collection].delete_many({})
    
    yield db
    
    client.close()

@pytest.fixture(scope="function")
def app():
    """Create simple test app without lifespan"""
    from fastapi import FastAPI
    from app.middleware.setup import setup_middleware
    from app.routes import categories, products, orders, auth, cart, brands, settings as settings_route, address, support, delivery, coupons, shop_status
    
    # Create simple app
    test_app = FastAPI(title="SmartBag Test")
    
    # Setup middleware
    setup_middleware(test_app)
    
    # Include routes
    test_app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
    test_app.include_router(products.router, prefix="/products", tags=["Products"])
    test_app.include_router(categories.router, prefix="/categories", tags=["Categories"])
    test_app.include_router(brands.router, prefix="/brands", tags=["Brands"]) 
    test_app.include_router(orders.router, prefix="/orders", tags=["Orders"])
    test_app.include_router(cart.router, prefix="/cart", tags=["Cart"])
    test_app.include_router(settings_route.router, prefix="/settings", tags=["Settings"])  
    test_app.include_router(address.router, prefix="/address", tags=["Address"])
    test_app.include_router(support.router, prefix="/support", tags=["Support"])
    test_app.include_router(delivery.router, prefix="/delivery", tags=["Delivery"])
    test_app.include_router(coupons.router, prefix="/promocodes", tags=["Coupons"])
    test_app.include_router(shop_status.router, prefix="/shop", tags=["Shop Status"])
    
    return test_app

@pytest.fixture
async def client(app):
    """Create async HTTP client"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
async def test_user(test_db):
    """Create test user"""
    from app.utils.auth import create_pasword_hash
    
    user_data = {
        "id": "CUSTEST001",
        "_id": ObjectId(),
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1234567890",
        "hashed_password": create_pasword_hash("testpass123"),
        "role": "customer",
        "is_active": True,
        "provider": "local",
        "created_at": datetime.utcnow()
    }
    
    await test_db.users.insert_one(user_data)
    return user_data

@pytest.fixture
async def test_admin(test_db):
    """Create test admin user"""
    from app.utils.auth import create_pasword_hash
    
    admin_data = {
        "id": "ADMTEST001",
        "_id": ObjectId(),
        "name": "Admin User",
        "email": "admin@example.com",
        "phone": "+1234567891",
        "hashed_password": create_pasword_hash("adminpass123"),
        "role": "admin",
        "is_active": True,
        "provider": "local",
        "created_at": datetime.utcnow()
    }
    
    await test_db.users.insert_one(admin_data)
    return admin_data

@pytest.fixture
async def test_delivery_partner(test_db):
    """Create test delivery partner"""
    from app.utils.auth import create_pasword_hash
    
    partner_data = {
        "id": "DELTEST001",
        "_id": ObjectId(),
        "name": "Delivery Partner",
        "email": "delivery@example.com",
        "phone": "+1234567892",
        "hashed_password": create_pasword_hash("deliverypass123"),
        "role": "delivery_partner",
        "is_active": True,
        "provider": "local",
        "created_at": datetime.utcnow()
    }
    
    await test_db.users.insert_one(partner_data)
    return partner_data

@pytest.fixture
async def auth_token(client, test_user):
    """Get authentication token for test user"""
    response = await client.post(
        "/auth/login",
        json={
            "email": test_user["email"],
            "password": "testpass123"
        }
    )
    if response.status_code != 200:
        print(f"Login response: {response.text}")
    assert response.status_code == 200, f"Login failed: {response.status_code} - {response.text}"
    return response.json()["access_token"]

@pytest.fixture
async def admin_token(client, test_admin):
    """Get authentication token for admin"""
    response = await client.post(
        "/auth/login",
        json={
            "email": test_admin["email"],
            "password": "adminpass123"
        }
    )
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    return response.json()["access_token"]

@pytest.fixture
async def delivery_token(client, test_delivery_partner):
    """Get authentication token for delivery partner"""
    response = await client.post(
        "/auth/login",
        json={
            "email": test_delivery_partner["email"],
            "password": "deliverypass123"
        }
    )
    assert response.status_code == 200, f"Delivery login failed: {response.text}"
    return response.json()["access_token"]

@pytest.fixture
async def test_category(test_db):
    """Create test category"""
    category_data = {
        "id": "CATTEST001",
        "_id": ObjectId(),
        "name": "Test Category",
        "description": "Test category description",
        "is_active": True,
        "created_at": datetime.utcnow()
    }
    
    await test_db.categories.insert_one(category_data)
    return category_data

@pytest.fixture
async def test_brand(test_db):
    """Create test brand"""
    brand_data = {
        "id": "BRDTEST001",
        "_id": ObjectId(),
        "name": "Test Brand",
        "description": "Test brand description",
        "is_active": True,
        "created_at": datetime.utcnow()
    }
    
    await test_db.brands.insert_one(brand_data)
    return brand_data

@pytest.fixture
async def test_product(test_db, test_category, test_brand):
    """Create test product"""
    product_data = {
        "id": "PRDTEST001",
        "_id": ObjectId(),
        "name": "Test Product",
        "description": "Test product description",
        "price": 29.99,
        "stock": 100,
        "category": test_category["id"],
        "brand": test_brand["id"],
        "images": ["https://example.com/image.jpg"],
        "is_active": True,
        "keywords": ["test", "product"],
        "created_at": datetime.utcnow()
    }
    
    await test_db.products.insert_one(product_data)
    return product_data

@pytest.fixture
async def test_address(test_db, test_user):
    """Create test address"""
    address_data = {
        "_id": ObjectId(),
        "user_id": test_user["id"],
        "label": "Home",
        "street": "123 Test St",  # ← ADD THIS
        "address_line1": "123 Test St",
        "address_line2": "Apt 4B",
        "city": "Test City",
        "state": "Test State",
        "pincode": "123456",  # ← Changed from "12345" to "123456"
        "latitude": 40.7128,
        "longitude": -74.0060,
        "is_default": True,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()  # ← ADD THIS
    }
    
    await test_db.user_addresses.insert_one(address_data)
    return address_data

@pytest.fixture
def auth_headers(auth_token):
    """Create authorization headers"""
    return {"Authorization": f"Bearer {auth_token}"}

@pytest.fixture
def admin_headers(admin_token):
    """Create admin authorization headers"""
    return {"Authorization": f"Bearer {admin_token}"}

@pytest.fixture
def delivery_headers(delivery_token):
    """Create delivery partner authorization headers"""
    return {"Authorization": f"Bearer {delivery_token}"}

@pytest.fixture
def create_test_order_data(test_product, test_address):
    """Helper to create order data"""
    def _create_order(items=None, payment_method="cod"):
        if items is None:
            items = [{
                "product_id": str(test_product["id"]),
                "quantity": 2,
                "price": test_product["price"]
            }]
        
        return {
            "items": items,
            "payment_method": payment_method,
            "delivery_address": {
                "address":"Prestige Jindal City, 560073, 560073",
                "city":"Prestige Jindal City",
                "state":"560073",
                "pincode":"560073"
                },
            "subtotal": sum(item["price"] * item["quantity"] for item in items),
            "tax": 2.40,
            "delivery_fee": 5.00,
            "total_amount": 67.38
        }
    
    return _create_order