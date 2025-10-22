# tests/test_products.py
"""
Unit tests for product endpoints
"""
import pytest
from httpx import AsyncClient
from main import app

@pytest.mark.asyncio
async def test_get_products():
    """Test getting products list"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/products/")
        
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert "pagination" in data
        assert isinstance(data["products"], list)

@pytest.mark.asyncio
async def test_get_products_with_filters():
    """Test product filtering"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/products/?category=electronics&in_stock=true")
        
        assert response.status_code == 200
        data = response.json()
        assert "products" in data

@pytest.mark.asyncio
async def test_get_product_by_id():
    """Test getting single product"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        # First get products to get a valid ID
        products_response = await client.get("/api/products/")
        products = products_response.json()["products"]
        
        if products:
            product_id = products[0]["id"]
            response = await client.get(f"/api/products/{product_id}")
            
            assert response.status_code == 200
            data = response.json()
            assert data["id"] == product_id

@pytest.mark.asyncio
async def test_product_not_found():
    """Test 404 for non-existent product"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/api/products/INVALID_ID")
        
        assert response.status_code == 404