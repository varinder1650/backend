"""
Products and Cart Endpoint Tests
File: tests/test_products_cart.py
"""
import pytest
from httpx import AsyncClient
from bson import ObjectId

class TestProducts:
    """Test product listing and retrieval"""
    
    @pytest.mark.asyncio
    async def test_get_products_success(self, client: AsyncClient, test_product):
        """Test getting product list"""
        response = await client.get("/products/")
        
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert "pagination" in data
        assert len(data["products"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_products_pagination(self, client: AsyncClient, test_db, test_category, test_brand):
        """Test product pagination"""
        # Create multiple products
        for i in range(25):
            product_data = {
                "id": f"PRDTEST{i:03d}",
                "_id": ObjectId(),
                "name": f"Test Product {i}",
                "description": f"Description {i}",
                "price": 10.00 + i,
                "stock": 50,
                "category": test_category["id"],
                "brand": test_brand["id"],
                "images": ["https://example.com/image.jpg"],
                "is_active": True,
                "keywords": ["test"]
            }
            await test_db.products.insert_one(product_data)
        
        # Test first page
        response = await client.get("/products/?page=1&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) == 10
        assert data["pagination"]["currentPage"] == 1
        assert data["pagination"]["hasNextPage"] == True
        
        # Test second page
        response = await client.get("/products/?page=2&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) == 10
        assert data["pagination"]["currentPage"] == 2
    
    @pytest.mark.asyncio
    async def test_get_products_by_category(self, client: AsyncClient, test_product, test_category):
        """Test filtering products by category"""
        response = await client.get(f"/products/?category={test_category['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) > 0
        assert data["products"][0]["category"]["id"] == test_category["id"]
    
    @pytest.mark.asyncio
    async def test_get_products_by_brand(self, client: AsyncClient, test_product, test_brand):
        """Test filtering products by brand"""
        response = await client.get(f"/products/?brand={test_brand['id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_products_price_range(self, client: AsyncClient, test_product):
        """Test filtering products by price range"""
        response = await client.get("/products/?min_price=20&max_price=40")
        
        assert response.status_code == 200
        data = response.json()
        for product in data["products"]:
            assert 20 <= product["price"] <= 40
    
    @pytest.mark.asyncio
    async def test_get_products_in_stock(self, client: AsyncClient, test_db, test_category, test_brand):
        """Test filtering in-stock products"""
        # Create out of stock product
        out_of_stock = {
            "id": "PRDOUT001",
            "_id": ObjectId(),
            "name": "Out of Stock",
            "price": 10.00,
            "stock": 0,
            "category": test_category["id"],
            "brand": test_brand["id"],
            "is_active": True
        }
        await test_db.products.insert_one(out_of_stock)
        
        response = await client.get("/products/?in_stock=true")
        
        assert response.status_code == 200
        data = response.json()
        for product in data["products"]:
            assert product["stock"] > 0
    
    @pytest.mark.asyncio
    async def test_search_products(self, client: AsyncClient, test_product):
        """Test product search"""
        response = await client.get(f"/products/?search={test_product['name']}")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["products"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_product_by_id(self, client: AsyncClient, test_product):
        """Test getting single product by ID"""
        response = await client.get(f"/products/{test_product['_id']}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == test_product["name"]
        assert "_id" in data
    
    @pytest.mark.asyncio
    async def test_get_product_invalid_id(self, client: AsyncClient):
        """Test getting product with invalid ID"""
        response = await client.get("/products/invalid_id")
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_get_product_not_found(self, client: AsyncClient):
        """Test getting non-existent product"""
        fake_id = str(ObjectId())
        response = await client.get(f"/products/{fake_id}")
        
        assert response.status_code == 404

class TestCart:
    """Test cart operations"""
    
    @pytest.mark.asyncio
    async def test_add_to_cart_success(self, client: AsyncClient, auth_headers, test_product):
        """Test adding product to cart"""
        response = await client.post(
            "/cart/add",
            headers=auth_headers,
            json={
                "productId": str(test_product["_id"]),
                "quantity": 2
            }
        )
        
        assert response.status_code == 200
        assert "successfully" in response.json()["message"].lower()
    
    @pytest.mark.asyncio
    async def test_add_to_cart_insufficient_stock(self, client: AsyncClient, auth_headers, test_db, test_category, test_brand):
        """Test adding product with insufficient stock"""
        # Create low stock product
        low_stock = {
            "id": "PRDLOW001",
            "_id": ObjectId(),
            "name": "Low Stock Product",
            "price": 10.00,
            "stock": 2,
            "category": test_category["id"],
            "brand": test_brand["id"],
            "is_active": True
        }
        await test_db.products.insert_one(low_stock)
        
        response = await client.post(
            "/cart/add",
            headers=auth_headers,
            json={
                "productId": str(low_stock["_id"]),
                "quantity": 5
            }
        )
        
        assert response.status_code == 400
        assert "stock" in response.json()["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_add_to_cart_invalid_product(self, client: AsyncClient, auth_headers):
        """Test adding non-existent product"""
        fake_id = str(ObjectId())
        response = await client.post(
            "/cart/add",
            headers=auth_headers,
            json={
                "productId": fake_id,
                "quantity": 1
            }
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_add_to_cart_unauthorized(self, client: AsyncClient, test_product):
        """Test adding to cart without authentication"""
        response = await client.post(
            "/cart/add",
            json={
                "productId": str(test_product["_id"]),
                "quantity": 1
            }
        )
        
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_cart_success(self, client: AsyncClient, auth_headers, test_product, test_db, test_user):
        """Test getting cart contents"""
        # Add product to cart first
        cart_data = {
            "user": test_user["id"],
            "items": [{
                "_id": str(ObjectId()),
                "product": test_product["_id"],
                "quantity": 2
            }]
        }
        await test_db.carts.insert_one(cart_data)
        
        response = await client.get("/cart/", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert len(data["items"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_cart_empty(self, client: AsyncClient, auth_headers):
        """Test getting empty cart"""
        response = await client.get("/cart/", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
    
    @pytest.mark.asyncio
    async def test_update_cart_item(self, client: AsyncClient, auth_headers, test_product, test_db, test_user):
        """Test updating cart item quantity"""
        # Create cart with item
        item_id = str(ObjectId())
        cart_data = {
            "user": test_user["id"],
            "items": [{
                "_id": item_id,
                "product": test_product["_id"],
                "quantity": 2
            }]
        }
        await test_db.carts.insert_one(cart_data)
        
        response = await client.put(
            "/cart/update",
            headers=auth_headers,
            json={
                "itemId": item_id,
                "quantity": 5
            }
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_update_cart_item_invalid_quantity(self, client: AsyncClient, auth_headers, test_product, test_db, test_user):
        """Test updating cart with invalid quantity"""
        item_id = str(ObjectId())
        cart_data = {
            "user": test_user["id"],
            "items": [{
                "_id": item_id,
                "product": test_product["_id"],
                "quantity": 2
            }]
        }
        await test_db.carts.insert_one(cart_data)
        
        response = await client.put(
            "/cart/update",
            headers=auth_headers,
            json={
                "itemId": item_id,
                "quantity": 0
            }
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_remove_from_cart(self, client: AsyncClient, auth_headers, test_product, test_db, test_user):
        """Test removing item from cart"""
        item_id = str(ObjectId())
        cart_data = {
            "user": test_user["id"],
            "items": [{
                "_id": item_id,
                "product": test_product["_id"],
                "quantity": 2
            }]
        }
        await test_db.carts.insert_one(cart_data)
        
        response = await client.delete(
            f"/cart/remove?item_id={item_id}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_remove_nonexistent_item(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test removing non-existent cart item"""
        # Create empty cart
        cart_data = {"user": test_user["id"], "items": []}
        await test_db.carts.insert_one(cart_data)
        
        fake_item_id = str(ObjectId())
        response = await client.delete(
            f"/cart/remove?item_id={fake_item_id}",
            headers=auth_headers
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_clear_cart(self, client: AsyncClient, auth_headers, test_product, test_db, test_user):
        """Test clearing entire cart"""
        cart_data = {
            "user": test_user["id"],
            "items": [{
                "_id": str(ObjectId()),
                "product": test_product["_id"],
                "quantity": 2
            }]
        }
        await test_db.carts.insert_one(cart_data)
        
        response = await client.delete("/cart/clear", headers=auth_headers)
        
        assert response.status_code == 200
        
        # Verify cart is empty
        get_response = await client.get("/cart/", headers=auth_headers)
        assert len(get_response.json()["items"]) == 0

class TestCategories:
    """Test category endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_categories(self, client: AsyncClient, test_category):
        """Test getting all categories"""
        response = await client.get("/categories/")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["name"] == test_category["name"]

class TestBrands:
    """Test brand endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_brands(self, client: AsyncClient, test_brand):
        """Test getting all brands"""
        response = await client.get("/brands/")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert data[0]["name"] == test_brand["name"]