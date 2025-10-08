"""
Orders and Delivery Endpoint Tests
File: tests/test_orders_delivery.py
"""
import pytest
from httpx import AsyncClient
from bson import ObjectId
from datetime import datetime

class TestOrders:
    """Test order creation and management"""
    
    @pytest.mark.asyncio
    async def test_create_order_success(self, client: AsyncClient, auth_headers, test_product, test_address, create_test_order_data):
        """Test successful order creation"""
        order_data = create_test_order_data()
        
        response = await client.post(
            "/orders/",
            headers=auth_headers,
            json=order_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "id" in data or "_id" in data
        assert data["order_status"] == "pending"
    
    @pytest.mark.asyncio
    async def test_create_order_insufficient_stock(self, client: AsyncClient, auth_headers, test_db, test_category, test_brand, test_address):
        """Test order creation with insufficient stock"""
        # Create low stock product
        low_stock = {
            "id": "PRDLOW002",
            "_id": ObjectId(),
            "name": "Low Stock Product",
            "price": 10.00,
            "stock": 1,
            "category": test_category["id"],
            "brand": test_brand["id"],
            "is_active": True
        }
        await test_db.products.insert_one(low_stock)
        
        order_data = {
            "items": [{
                "product_id": str(low_stock["_id"]),
                "quantity": 5,
                "price": 10.00
            }],
            "payment_method": "card",
            "delivery_address_id": str(test_address["_id"]),
            "subtotal": 50.00,
            "tax": 4.00,
            "delivery_fee": 5.00,
            "total": 59.00
        }
        
        response = await client.post(
            "/orders/",
            headers=auth_headers,
            json=order_data
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_create_order_invalid_address(self, client: AsyncClient, auth_headers, test_product):
        """Test order creation with invalid address"""
        order_data = {
            "items": [{
                "product_id": str(test_product["_id"]),
                "quantity": 1,
                "price": test_product["price"]
            }],
            "payment_method": "card",
            "delivery_address_id": str(ObjectId()),  # Non-existent address
            "subtotal": test_product["price"],
            "tax": 2.40,
            "delivery_fee": 5.00,
            "total": 37.39
        }
        
        response = await client.post(
            "/orders/",
            headers=auth_headers,
            json=order_data
        )
        
        assert response.status_code in [400, 404]
    
    @pytest.mark.asyncio
    async def test_create_order_unauthorized(self, client: AsyncClient, test_product, test_address):
        """Test order creation without authentication"""
        order_data = {
            "items": [{
                "product_id": str(test_product["_id"]),
                "quantity": 1,
                "price": test_product["price"]
            }],
            "payment_method": "card",
            "delivery_address_id": str(test_address["_id"]),
            "subtotal": test_product["price"],
            "total": 37.39
        }
        
        response = await client.post("/orders/", json=order_data)
        
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_get_my_orders(self, client: AsyncClient, auth_headers, test_db, test_user, test_product):
        """Test getting user's order history"""
        # Create test order
        order_data = {
            "id": "ORDTEST001",
            "_id": ObjectId(),
            "user": test_user["id"],
            "items": [{
                "product": test_product["_id"],
                "quantity": 2,
                "price": test_product["price"]
            }],
            "order_status": "delivered",
            "total": 59.98,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.get("/orders/my", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "orders" in data
        assert len(data["orders"]) > 0
        assert "pagination" in data
    
    @pytest.mark.asyncio
    async def test_get_my_orders_pagination(self, client: AsyncClient, auth_headers, test_db, test_user, test_product):
        """Test order history pagination"""
        # Create multiple orders
        for i in range(15):
            order_data = {
                "id": f"ORDTEST{i:03d}",
                "_id": ObjectId(),
                "user": test_user["id"],
                "items": [{
                    "product": test_product["_id"],
                    "quantity": 1,
                    "price": test_product["price"]
                }],
                "order_status": "delivered",
                "total": 35.00,
                "created_at": datetime.utcnow()
            }
            await test_db.orders.insert_one(order_data)
        
        # Test first page
        response = await client.get("/orders/my?page=1&limit=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["orders"]) == 10
        
        # Test second page
        response = await client.get("/orders/my?page=2&limit=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["orders"]) == 5
    
    @pytest.mark.asyncio
    async def test_get_active_order(self, client: AsyncClient, auth_headers, test_db, test_user, test_product):
        """Test getting active order"""
        # Create active order
        order_data = {
            "id": "ORDACTIVE001",
            "_id": ObjectId(),
            "user": test_user["id"],
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "confirmed",
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.get("/orders/active", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert data["order_status"] == "confirmed"
    
    @pytest.mark.asyncio
    async def test_get_active_order_none(self, client: AsyncClient, auth_headers):
        """Test getting active order when none exists"""
        response = await client.get("/orders/active", headers=auth_headers)
        
        assert response.status_code == 404

class TestDelivery:
    """Test delivery partner endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_available_orders(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product):
        """Test getting available orders for delivery"""
        # Create confirmed order
        order_data = {
            "id": "ORDAVAIL001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "confirmed",
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.get(
            "/delivery/available",
            headers=delivery_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_get_available_orders_unauthorized(self, client: AsyncClient, auth_headers):
        """Test getting available orders as non-delivery user"""
        response = await client.get(
            "/delivery/available",
            headers=auth_headers
        )
        
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_accept_order(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product, test_delivery_partner):
        """Test accepting order for delivery"""
        # Create confirmed order
        order_data = {
            "id": "ORDACCEPT001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "confirmed",
            "total": 35.00,
            "accepted_partners": [],
            "created_at": datetime.utcnow()
        }
        order_id = await test_db.orders.insert_one(order_data)
        
        response = await client.post(
            f"/delivery/{order_data['_id']}/accept",
            headers=delivery_headers
        )
        
        assert response.status_code == 200
        
        # Verify order was accepted
        order = await test_db.orders.find_one({"_id": order_data["_id"]})
        assert order["order_status"] == "accepted"
    
    @pytest.mark.asyncio
    async def test_accept_already_assigned_order(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product):
        """Test accepting already assigned order"""
        # Create order with delivery partner
        order_data = {
            "id": "ORDASSIGNED001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "assigned",
            "delivery_partner": ObjectId(),  # Already assigned
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.post(
            f"/delivery/{order_data['_id']}/accept",
            headers=delivery_headers
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_get_assigned_orders(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product, test_delivery_partner):
        """Test getting assigned orders"""
        # Create assigned order
        order_data = {
            "id": "ORDMYASSIGN001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "assigned",
            "delivery_partner": ObjectId(test_delivery_partner["_id"]),
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.get(
            "/delivery/assigned",
            headers=delivery_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_mark_order_delivered(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product, test_delivery_partner):
        """Test marking order as delivered"""
        # Create assigned order
        order_data = {
            "id": "ORDDELIVER001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "out_for_delivery",
            "delivery_partner": ObjectId(test_delivery_partner["_id"]),
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.post(
            f"/delivery/{order_data['_id']}/mark-delivered",
            headers=delivery_headers
        )
        
        assert response.status_code == 200
        
        # Verify order status
        order = await test_db.orders.find_one({"_id": order_data["_id"]})
        assert order["order_status"] == "delivered"
    
    @pytest.mark.asyncio
    async def test_mark_delivered_wrong_partner(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product):
        """Test marking order delivered by wrong partner"""
        # Create order assigned to different partner
        order_data = {
            "id": "ORDWRONG001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "out_for_delivery",
            "delivery_partner": ObjectId(),  # Different partner
            "total": 35.00,
            "created_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.post(
            f"/delivery/{order_data['_id']}/mark-delivered",
            headers=delivery_headers
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_get_delivered_orders(self, client: AsyncClient, delivery_headers, test_db, test_user, test_product, test_delivery_partner):
        """Test getting delivered order history"""
        # Create delivered order
        order_data = {
            "id": "ORDHISTORY001",
            "_id": ObjectId(),
            "user": ObjectId(test_user["_id"]),
            "items": [{
                "product": test_product["_id"],
                "quantity": 1,
                "price": test_product["price"]
            }],
            "order_status": "delivered",
            "delivery_partner": ObjectId(test_delivery_partner["_id"]),
            "total": 35.00,
            "created_at": datetime.utcnow(),
            "delivered_at": datetime.utcnow()
        }
        await test_db.orders.insert_one(order_data)
        
        response = await client.get(
            "/delivery/delivered",
            headers=delivery_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0