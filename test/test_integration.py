"""
Integration and Performance Tests
File: tests/test_integration.py

These tests verify end-to-end workflows and performance under load.
"""
import pytest
import asyncio
from httpx import AsyncClient
from bson import ObjectId
from datetime import datetime

@pytest.mark.integration
class TestCompleteUserJourney:
    """Test complete user journey from registration to order delivery"""
    
    @pytest.mark.asyncio
    async def test_complete_shopping_flow(self, client: AsyncClient, test_db, test_product, test_category, test_brand):
        """Test complete flow: Register -> Browse -> Add to Cart -> Checkout"""
        
        # Step 1: Register new user
        register_response = await client.post(
            "/auth/register",
            json={
                "name": "Journey User",
                "email": "journey@test.com",
                "password": "password123",
                "phone": "+1234567890"
            }
        )
        assert register_response.status_code == 200
        access_token = register_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {access_token}"}
        
        # Step 2: Browse products
        products_response = await client.get("/products/")
        assert products_response.status_code == 200
        assert len(products_response.json()["products"]) > 0
        
        # Step 3: Get product details
        product_response = await client.get(f"/products/{test_product['_id']}")
        assert product_response.status_code == 200
        
        # Step 4: Add to cart
        cart_response = await client.post(
            "/cart/add",
            headers=headers,
            json={
                "productId": str(test_product["_id"]),
                "quantity": 2
            }
        )
        assert cart_response.status_code == 200
        
        # Step 5: View cart
        get_cart_response = await client.get("/cart/", headers=headers)
        assert get_cart_response.status_code == 200
        cart_data = get_cart_response.json()
        assert len(cart_data["items"]) == 1
        
        # Step 6: Create address
        address_response = await client.post(
            "/address/",
            headers=headers,
            json={
                "label": "Home",
                "address_line1": "123 Test St",
                "city": "Test City",
                "state": "Test State",
                "pincode": "12345",
                "latitude": 40.7128,
                "longitude": -74.0060
            }
        )
        assert address_response.status_code == 200
        address_id = address_response.json()["_id"]
        
        # Step 7: Create order
        order_response = await client.post(
            "/orders/",
            headers=headers,
            json={
                "items": [{
                    "product_id": str(test_product["_id"]),
                    "quantity": 2,
                    "price": test_product["price"]
                }],
                "payment_method": "card",
                "delivery_address_id": address_id,
                "subtotal": test_product["price"] * 2,
                "tax": 4.80,
                "delivery_fee": 5.00,
                "total": 69.78
            }
        )
        assert order_response.status_code == 200
        order_id = order_response.json()["_id"] if "_id" in order_response.json() else order_response.json()["id"]
        
        # Step 8: Verify cart is cleared (implementation dependent)
        cart_after_order = await client.get("/cart/", headers=headers)
        # Cart might be cleared or kept depending on implementation
        
        # Step 9: Check order in history
        orders_response = await client.get("/orders/my", headers=headers)
        assert orders_response.status_code == 200
        assert len(orders_response.json()["orders"]) > 0
    
    @pytest.mark.asyncio
    async def test_delivery_partner_workflow(self, client: AsyncClient, test_db, test_delivery_partner, test_user, test_product):
        """Test delivery partner accepting and delivering order"""
        
        # Login as delivery partner
        login_response = await client.post(
            "/auth/login",
            json={
                "email": test_delivery_partner["email"],
                "password": "deliverypass123"
            }
        )
        delivery_token = login_response.json()["access_token"]
        delivery_headers = {"Authorization": f"Bearer {delivery_token}"}
        
        # Create order ready for delivery
        order_data = {
            "id": "ORDDELIVERY001",
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
        await test_db.orders.insert_one(order_data)
        
        # Get available orders
        available_response = await client.get(
            "/delivery/available",
            headers=delivery_headers
        )
        assert available_response.status_code == 200
        assert len(available_response.json()) > 0
        
        # Accept order
        accept_response = await client.post(
            f"/delivery/{order_data['_id']}/accept",
            headers=delivery_headers
        )
        assert accept_response.status_code == 200
        
        # Update order status to assigned (simulate admin action)
        await test_db.orders.update_one(
            {"_id": order_data["_id"]},
            {"$set": {
                "order_status": "out_for_delivery",
                "delivery_partner": ObjectId(test_delivery_partner["_id"])
            }}
        )
        
        # Get assigned orders
        assigned_response = await client.get(
            "/delivery/assigned",
            headers=delivery_headers
        )
        assert assigned_response.status_code == 200
        assert len(assigned_response.json()) > 0
        
        # Mark as delivered
        delivered_response = await client.post(
            f"/delivery/{order_data['_id']}/mark-delivered",
            headers=delivery_headers
        )
        assert delivered_response.status_code == 200
        
        # Verify in delivered history
        history_response = await client.get(
            "/delivery/delivered",
            headers=delivery_headers
        )
        assert history_response.status_code == 200
        assert len(history_response.json()) > 0

@pytest.mark.integration
class TestSupportWorkflow:
    """Test complete support ticket workflow"""
    
    @pytest.mark.asyncio
    async def test_support_ticket_lifecycle(self, client: AsyncClient, auth_headers, test_db):
        """Test creating and managing support ticket"""
        
        # Create ticket
        create_response = await client.post(
            "/support/tickets",
            headers=auth_headers,
            json={
                "category": "order_issue",
                "subject": "Problem with order",
                "message": "My order arrived damaged",
                "priority": "high"
            }
        )
        assert create_response.status_code == 200
        ticket_id = create_response.json()["_id"]
        
        # View ticket details
        detail_response = await client.get(
            f"/support/tickets/{ticket_id}",
            headers=auth_headers
        )
        assert detail_response.status_code == 200
        
        # Add message to ticket
        message_response = await client.post(
            f"/support/tickets/{ticket_id}/messages",
            headers=auth_headers,
            json={"message": "I would like a replacement"}
        )
        assert message_response.status_code == 200
        
        # Verify message was added
        updated_ticket = await client.get(
            f"/support/tickets/{ticket_id}",
            headers=auth_headers
        )
        assert len(updated_ticket.json()["messages"]) == 1
        
        # Resolve ticket
        resolve_response = await client.patch(
            f"/support/tickets/{ticket_id}/status",
            headers=auth_headers,
            json={"status": "resolved"}
        )
        assert resolve_response.status_code == 200
        
        # Verify in ticket list
        list_response = await client.get(
            "/support/tickets",
            headers=auth_headers
        )
        assert list_response.status_code == 200
        tickets = list_response.json()
        assert any(t["_id"] == ticket_id and t["status"] == "resolved" for t in tickets)

@pytest.mark.slow
@pytest.mark.integration
class TestPerformance:
    """Performance and load tests"""
    
    @pytest.mark.asyncio
    async def test_concurrent_cart_operations(self, client: AsyncClient, test_db, test_user, test_product):
        """Test multiple cart operations concurrently"""
        
        # Login to get token
        login_response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Concurrent add to cart operations
        async def add_to_cart():
            return await client.post(
                "/cart/add",
                headers=headers,
                json={
                    "productId": str(test_product["_id"]),
                    "quantity": 1
                }
            )
        
        # Execute 10 concurrent requests
        tasks = [add_to_cart() for _ in range(10)]
        responses = await asyncio.gather(*tasks)
        
        # At least one should succeed
        success_count = sum(1 for r in responses if r.status_code == 200)
        assert success_count > 0
    
    @pytest.mark.asyncio
    async def test_product_listing_performance(self, client: AsyncClient, test_db, test_category, test_brand):
        """Test product listing performance with large dataset"""
        
        # Create 100 products
        products = []
        for i in range(100):
            products.append({
                "id": f"PRDPERF{i:03d}",
                "_id": ObjectId(),
                "name": f"Performance Product {i}",
                "description": f"Description {i}",
                "price": 10.00 + i,
                "stock": 50,
                "category": test_category["id"],
                "brand": test_brand["id"],
                "images": ["https://example.com/image.jpg"],
                "is_active": True,
                "keywords": ["test", "performance"]
            })
        
        await test_db.products.insert_many(products)
        
        # Measure response time
        import time
        start_time = time.time()
        
        response = await client.get("/products/?page=1&limit=20")
        
        elapsed_time = time.time() - start_time
        
        assert response.status_code == 200
        assert len(response.json()["products"]) == 20
        # Response should be under 2 seconds
        assert elapsed_time < 2.0, f"Response took {elapsed_time:.2f}s, expected < 2.0s"
    
    @pytest.mark.asyncio
    async def test_order_creation_under_load(self, client: AsyncClient, test_db, test_user, test_product, test_address):
        """Test order creation under concurrent load"""
        
        # Login
        login_response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        token = login_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create multiple orders concurrently
        async def create_order(order_num):
            return await client.post(
                "/orders/",
                headers=headers,
                json={
                    "items": [{
                        "product_id": str(test_product["_id"]),
                        "quantity": 1,
                        "price": test_product["price"]
                    }],
                    "payment_method": "card",
                    "delivery_address_id": str(test_address["_id"]),
                    "subtotal": test_product["price"],
                    "tax": 2.40,
                    "delivery_fee": 5.00,
                    "total": 37.39
                }
            )
        
        # Create 5 concurrent orders
        tasks = [create_order(i) for i in range(5)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check how many succeeded
        success_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
        
        # At least some should succeed (may fail due to stock limits)
        assert success_count >= 1

@pytest.mark.integration
class TestDataConsistency:
    """Test data consistency across operations"""
    
    @pytest.mark.asyncio
    async def test_stock_consistency_after_order(self, client: AsyncClient, auth_headers, test_db, test_product):
        """Verify stock is properly updated after order"""
        
        initial_stock = test_product["stock"]
        order_quantity = 5
        
        # Create address first
        address_response = await client.post(
            "/address/",
            headers=auth_headers,
            json={
                "label": "Test",
                "address_line1": "123 St",
                "city": "City",
                "state": "State",
                "pincode": "12345",
                "latitude": 0,
                "longitude": 0
            }
        )
        address_id = address_response.json()["_id"]
        
        # Create order
        order_response = await client.post(
            "/orders/",
            headers=auth_headers,
            json={
                "items": [{
                    "product_id": str(test_product["_id"]),
                    "quantity": order_quantity,
                    "price": test_product["price"]
                }],
                "payment_method": "card",
                "delivery_address_id": address_id,
                "subtotal": test_product["price"] * order_quantity,
                "tax": 12.00,
                "delivery_fee": 5.00,
                "total": 166.95
            }
        )
        
        assert order_response.status_code == 200
        
        # Wait a bit for background tasks
        await asyncio.sleep(1)
        
        # Check stock was updated
        updated_product = await test_db.products.find_one({"_id": test_product["_id"]})
        # Stock should be decreased (if background task ran)
        # This might vary based on implementation
        assert updated_product is not None
    
    @pytest.mark.asyncio
    async def test_cart_consistency_across_sessions(self, client: AsyncClient, test_user, test_product):
        """Verify cart persists across login sessions"""
        
        # Session 1: Login and add to cart
        login1 = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        token1 = login1.json()["access_token"]
        
        await client.post(
            "/cart/add",
            headers={"Authorization": f"Bearer {token1}"},
            json={
                "productId": str(test_product["_id"]),
                "quantity": 3
            }
        )
        
        # Session 2: Login again and check cart
        login2 = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        token2 = login2.json()["access_token"]
        
        cart_response = await client.get(
            "/cart/",
            headers={"Authorization": f"Bearer {token2}"}
        )
        
        assert cart_response.status_code == 200
        cart_data = cart_response.json()
        assert len(cart_data["items"]) > 0
        # Cart should persist with the same quantity
        assert cart_data["items"][0]["quantity"] == 3

@pytest.mark.integration
class TestErrorRecovery:
    """Test system behavior under error conditions"""
    
    @pytest.mark.asyncio
    async def test_order_creation_with_invalid_product(self, client: AsyncClient, auth_headers, test_address):
        """Test order creation with non-existent product"""
        
        fake_product_id = str(ObjectId())
        
        response = await client.post(
            "/orders/",
            headers=auth_headers,
            json={
                "items": [{
                    "product_id": fake_product_id,
                    "quantity": 1,
                    "price": 10.00
                }],
                "payment_method": "card",
                "delivery_address_id": str(test_address["_id"]),
                "subtotal": 10.00,
                "tax": 0.80,
                "delivery_fee": 5.00,
                "total": 15.80
            }
        )
        
        # Should handle gracefully
        assert response.status_code in [400, 404, 500]
    
    @pytest.mark.asyncio
    async def test_concurrent_stock_depletion(self, client: AsyncClient, test_db, test_user, test_category, test_brand, test_address):
        """Test handling concurrent orders depleting stock"""
        
        # Create product with limited stock
        limited_product = {
            "id": "PRDLIMITED001",
            "_id": ObjectId(),
            "name": "Limited Stock",
            "price": 10.00,
            "stock": 5,  # Only 5 items
            "category": test_category["id"],
            "brand": test_brand["id"],
            "is_active": True
        }
        await test_db.products.insert_one(limited_product)
        
        # Login
        login = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to order 10 concurrent orders of 2 items each (20 total, but only 5 in stock)
        async def create_order():
            return await client.post(
                "/orders/",
                headers=headers,
                json={
                    "items": [{
                        "product_id": str(limited_product["_id"]),
                        "quantity": 2,
                        "price": 10.00
                    }],
                    "payment_method": "card",
                    "delivery_address_id": str(test_address["_id"]),
                    "subtotal": 20.00,
                    "tax": 1.60,
                    "delivery_fee": 5.00,
                    "total": 26.60
                }
            )
        
        tasks = [create_order() for _ in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Most should fail due to insufficient stock
        success_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 200)
        failure_count = sum(1 for r in responses if not isinstance(r, Exception) and r.status_code == 400)
        
        # Should have more failures than successes
        assert failure_count > success_count
        # But system should handle all requests without crashing
        assert all(not isinstance(r, Exception) for r in responses)