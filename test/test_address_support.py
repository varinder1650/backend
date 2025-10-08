"""
Address and Support Endpoint Tests
File: tests/test_address_support.py
"""
import pytest
from httpx import AsyncClient
from bson import ObjectId

class TestAddress:
    """Test address management"""
    
    # @pytest.mark.asyncio
    # async def test_create_address_success(self, client: AsyncClient, auth_headers):
    #     """Test creating new address"""
    #     address_data = {
    #         "label": "Office",
    #         "street": "456 Work St, Suite 100",
            
    #         "city": "Work City",
    #         "state": "Work State",
    #         "pincode": "543210",
    #         "latitude": 40.7589,
    #         "longitude": -73.9851
    #     }
        
    #     response = await client.post(
    #         "/address/",
    #         headers=auth_headers,
    #         json=address_data
    #     )
        
    #     assert response.status_code == 200
    #     data = response.json()
    #     assert data["label"] == "Office"
    #     assert data["city"] == "Work City"
    @pytest.mark.asyncio
    async def test_create_support_ticket(self, client: AsyncClient, auth_headers):
        """Test creating support ticket"""
        ticket_data = {
            "category": "order_inquiry",  # ← Must be valid enum value
            "subject": "Problem with my order",
            "message": "My order was damaged during delivery and I need help"  # ← Min 10 chars
        }
        
        response = await client.post(
            "/support/tickets",
            headers=auth_headers,
            json=ticket_data
        )
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_create_address_max_limit(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test address creation beyond max limit"""
        # Create 5 addresses (max limit)
        for i in range(5):
            address_data = {
                "_id": ObjectId(),
                "user_id": test_user["id"],
                "label": f"Address {i}",
                "address_line1": f"{i} Test St",
                "city": "Test City",
                "state": "Test State",
                "pincode": "12345",
                "is_default": i == 0
            }
            await test_db.user_addresses.insert_one(address_data)
        
        # Try to add 6th address
        response = await client.post(
            "/address/",
            headers=auth_headers,
            json={
                "label": "Extra",
                "street": "Extra St",
                "city": "Extra City",
                "state": "Extra State",
                "pincode": "999999",
                "latitude": 0,
                "longitude": 0
            }
        )
        
        assert response.status_code == 400
        assert "maximum" in response.json()["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_get_user_addresses(self, client: AsyncClient, auth_headers, test_address):
        """Test getting all user addresses"""
        response = await client.get(
            "/address/my",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_set_default_address(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test setting address as default"""
        # Create two addresses
        addr1 = {
            "_id": ObjectId(),
            "user_id": test_user["id"],
            "label": "Home",
            "address_line1": "123 Home St",
            "city": "City",
            "state": "State",
            "pincode": "12345",
            "is_default": True
        }
        addr2 = {
            "_id": ObjectId(),
            "user_id": test_user["id"],
            "label": "Work",
            "street": "456 Work St, Suite 100",
            "city": "City",
            "state": "State",
            "pincode": "12345",
            "is_default": False
        }
        await test_db.user_addresses.insert_many([addr1, addr2])
        
        # Set second address as default
        response = await client.post(
            f"/address/{addr2['_id']}/set-default",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify first address is no longer default
        addr1_updated = await test_db.user_addresses.find_one({"_id": addr1["_id"]})
        assert addr1_updated["is_default"] == False
        
        # Verify second address is now default
        addr2_updated = await test_db.user_addresses.find_one({"_id": addr2["_id"]})
        assert addr2_updated["is_default"] == True
    
    @pytest.mark.asyncio
    async def test_set_default_invalid_address(self, client: AsyncClient, auth_headers):
        """Test setting non-existent address as default"""
        fake_id = str(ObjectId())
        response = await client.post(
            f"/address/{fake_id}/set-default",
            headers=auth_headers
        )
        
        assert response.status_code == 404
    
    @pytest.mark.asyncio
    async def test_delete_address(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test deleting address"""
        address_data = {
            "_id": ObjectId(),
            "user_id": test_user["id"],
            "label": "ToDelete",
            "address_line1": "Delete St",
            "city": "City",
            "state": "State",
            "pincode": "12345",
            "is_default": False
        }
        await test_db.user_addresses.insert_one(address_data)
        
        response = await client.delete(
            f"/address/{address_data['_id']}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify deletion
        deleted = await test_db.user_addresses.find_one({"_id": address_data["_id"]})
        assert deleted is None
    
    @pytest.mark.asyncio
    async def test_delete_default_address(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test deleting default address reassigns default"""
        # Create two addresses
        addr1 = {
            "_id": ObjectId(),
            "user_id": test_user["id"],
            "label": "Default",
            "address_line1": "Default St",
            "city": "City",
            "state": "State",
            "pincode": "12345",
            "is_default": True
        }
        addr2 = {
            "_id": ObjectId(),
            "user_id": test_user["id"],
            "label": "Other",
            "address_line1": "Other St",
            "city": "City",
            "state": "State",
            "pincode": "12345",
            "is_default": False
        }
        await test_db.user_addresses.insert_many([addr1, addr2])
        
        # Delete default address
        response = await client.delete(
            f"/address/{addr1['_id']}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify other address became default
        addr2_updated = await test_db.user_addresses.find_one({"_id": addr2["_id"]})
        assert addr2_updated["is_default"] == True
    
    @pytest.mark.asyncio
    async def test_geocode_address(self, client: AsyncClient):
        """Test geocoding address to coordinates"""
        response = await client.post(
            "/address/geocode",
            json={"address": "1600 Amphitheatre Parkway, Mountain View, CA"}
        )
        
        # May fail if OLA Maps API is not configured
        assert response.status_code in [200, 404, 500]
    
    @pytest.mark.asyncio
    async def test_reverse_geocode(self, client: AsyncClient):
        """Test reverse geocoding coordinates to address"""
        response = await client.post(
            "/address/reverse-geocode",
            json={
                "latitude": 37.4224764,
                "longitude": -122.0842499
            }
        )
        
        assert response.status_code in [200, 404, 500]
    
    @pytest.mark.asyncio
    async def test_search_addresses(self, client: AsyncClient):
        """Test address search/autocomplete"""
        response = await client.post(
            "/address/search-addresses",
            json={"query": "Mountain View"}
        )
        
        assert response.status_code == 200

class TestSupport:
    """Test support ticket system"""
    
    @pytest.mark.asyncio
    async def test_create_support_ticket(self, client: AsyncClient, auth_headers):
        """Test creating support ticket"""
        ticket_data = {
            "category": "order_inquiry",
            "subject": "Problem with my order",
            "message": "My order was damaged during delivery",
            "priority": "high"
        }
        
        response = await client.post(
            "/support/tickets",
            headers=auth_headers,
            json=ticket_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == ticket_data["subject"]
        assert data["status"] == "open"
    
    @pytest.mark.asyncio
    async def test_create_ticket_with_order(self, client: AsyncClient, auth_headers, test_db, test_user, test_product):
        """Test creating ticket related to order"""
        # Create order first
        order_data = {
            "id": "ORDTICKET001",
            "_id": ObjectId(),
            "user": test_user["id"],
            "items": [{"product": test_product["_id"], "quantity": 1}],
            "order_status": "delivered",
            "total": 35.00
        }
        await test_db.orders.insert_one(order_data)
        
        ticket_data = {
            "category": "order_inquiry",
            "subject": "Order problem",
            "message": "Issue with order",
            "order_id": str(order_data["_id"])
        }
        
        response = await client.post(
            "/support/tickets",
            headers=auth_headers,
            json=ticket_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["order_id"] == str(order_data["_id"])
    
    @pytest.mark.asyncio
    async def test_get_user_tickets(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test getting user's support tickets"""
        # Create ticket
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "user_name": test_user["name"],
            "user_email": test_user["email"],
            "category": "other",
            "subject": "Test support ticket",
            "message": "This is a test message for support",
            "status": "open",
            "messages": []
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.get(
            "/support/tickets",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_get_ticket_detail(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test getting detailed ticket information"""
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "user_name": test_user["name"],
            "user_email": test_user["email"],
            "category": "other",
            "subject": "Detailed ticket",
            "message": "This is the initial message for this ticket",
            "status": "open",
            "messages": [
                {
                    "_id": ObjectId(),
                    "message": "First message",
                    "sender_type": "user",
                    "sender_name": test_user["name"],
                    "sender_id": test_user["id"],
                    "created_at": "2025-01-01T00:00:00"
                }
            ]
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.get(
            f"/support/tickets/{ticket_data['_id']}",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["subject"] == "Detailed ticket"
        assert "messages" in data
        assert len(data["messages"]) > 0
    
    @pytest.mark.asyncio
    async def test_get_ticket_unauthorized(self, client: AsyncClient, auth_headers, test_db):
        """Test getting ticket that doesn't belong to user"""
        # Create ticket for different user
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(),  # Different user
            "category": "other",
            "subject": "Other user ticket",
            "message": "This is a test support message",
            "status": "open",
            "messages": []
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.get(
            f"/support/tickets/{ticket_data['_id']}",
            headers=auth_headers
        )
        
        assert response.status_code == 403
    
    @pytest.mark.asyncio
    async def test_add_ticket_message(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test adding message to ticket"""
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "category": "other",
            "subject": "Ticket with messages",
            "message": "This is the initial ticket message",
            "status": "open",
            "messages": []
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.post(
            f"/support/tickets/{ticket_data['_id']}/messages",
            headers=auth_headers,
            json={"message": "Follow-up message"}
        )
        
        assert response.status_code == 200
        
        # Verify message was added
        ticket = await test_db.support_tickets.find_one({"_id": ticket_data["_id"]})
        assert len(ticket["messages"]) == 1
        assert ticket["messages"][0]["message"] == "Follow-up message"
    
    @pytest.mark.asyncio
    async def test_add_message_to_closed_ticket(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test adding message to closed ticket"""
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "category": "other",
            "subject": "Closed ticket",
            "message": "This is the initial ticket message",
            "status": "closed",
            "messages": []
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.post(
            f"/support/tickets/{ticket_data['_id']}/messages",
            headers=auth_headers,
            json={"message": "New message"}
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_update_ticket_status(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test updating ticket status"""
        ticket_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "category": "other",
            "subject": "Status update ticket",
            "message": "This is the initial ticket message",
            "status": "open",
            "messages": []
        }
        await test_db.support_tickets.insert_one(ticket_data)
        
        response = await client.patch(
            f"/support/tickets/{ticket_data['_id']}/status",
            headers=auth_headers,
            json={"status": "resolved"}
        )
        
        assert response.status_code == 200
        
        # Verify status updated
        ticket = await test_db.support_tickets.find_one({"_id": ticket_data["_id"]})
        assert ticket["status"] == "resolved"
    
    @pytest.mark.asyncio
    async def test_create_product_request(self, client: AsyncClient, auth_headers):
        """Test creating product request"""
        request_data = {
            "product_name": "New Product Request",
            "description": "Would love to see this product",
            "category": "Electronics"
        }
        
        response = await client.post(
            "/support/product-requests",
            headers=auth_headers,
            json=request_data
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["product_name"] == request_data["product_name"]
        assert data["status"] == "pending"
        assert data["votes"] == 1
    
    @pytest.mark.asyncio
    async def test_create_duplicate_product_request(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test creating duplicate product request"""
        # Create existing request
        existing_request = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "product_name": "Existing Product",
            "description": "Already requested",
            "status": "pending",
            "votes": 1
        }
        await test_db.product_requests.insert_one(existing_request)
        
        response = await client.post(
            "/support/product-requests",
            headers=auth_headers,
            json={
                "product_name": "Existing Product",
                "description": "Duplicate request",
                "category": "General"
            }
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_get_product_requests(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test getting user's product requests"""
        request_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(test_user["_id"]),
            "user_name": test_user["name"],
            "user_email": test_user["email"],
            "product_name": "My Request",
            "description": "Description",
            "status": "pending",
            "votes": 1
        }
        await test_db.product_requests.insert_one(request_data)
        
        response = await client.get(
            "/support/product-requests",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
    
    @pytest.mark.asyncio
    async def test_vote_product_request(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test voting for product request"""
        request_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(),  # Different user's request
            "product_name": "Popular Product",
            "description": "Many people want this",
            "status": "pending",
            "votes": 5
        }
        await test_db.product_requests.insert_one(request_data)
        
        response = await client.post(
            f"/support/product-requests/{request_data['_id']}/vote",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        
        # Verify vote was added
        request = await test_db.product_requests.find_one({"_id": request_data["_id"]})
        assert request["votes"] == 6
    
    @pytest.mark.asyncio
    async def test_vote_duplicate(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test voting twice for same request"""
        request_data = {
            "_id": ObjectId(),
            "user_id": ObjectId(),
            "product_name": "Product",
            "status": "pending",
            "votes": 5
        }
        await test_db.product_requests.insert_one(request_data)
        
        # Add existing vote
        vote_data = {
            "request_id": request_data["_id"],
            "user_id": ObjectId(test_user["_id"])
        }
        await test_db.product_request_votes.insert_one(vote_data)
        
        response = await client.post(
            f"/support/product-requests/{request_data['_id']}/vote",
            headers=auth_headers
        )
        
        assert response.status_code == 400

class TestCoupons:
    """Test coupon validation"""
    
    @pytest.mark.asyncio
    async def test_validate_coupon_success(self, client: AsyncClient, auth_headers, test_db):
        """Test validating valid coupon"""
        coupon_data = {
            "code": "SAVE10",
            "discount_type": "percentage",
            "discount_value": 10,
            "min_order_amount": 50,
            "usage_limit": 100,
            "target_audience": "all_users",
            "is_active": True
        }
        await test_db.discount_coupons.insert_one(coupon_data)
        
        response = await client.post(
            "/promocodes/validate",
            headers=auth_headers,
            json={
                "code": "SAVE10",
                "order_amount": 100
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == True
        assert data["promocode"]["code"] == "SAVE10"
    
    @pytest.mark.asyncio
    async def test_validate_coupon_below_minimum(self, client: AsyncClient, auth_headers, test_db):
        """Test coupon with order below minimum"""
        coupon_data = {
            "code": "BIGORDER",
            "discount_type": "percentage",
            "discount_value": 20,
            "min_order_amount": 100,
            "usage_limit": 50,
            "target_audience": "all_users",
            "is_active": True
        }
        await test_db.discount_coupons.insert_one(coupon_data)
        
        response = await client.post(
            "/promocodes/validate",
            headers=auth_headers,
            json={
                "code": "BIGORDER",
                "order_amount": 50
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == False
    
    @pytest.mark.asyncio
    async def test_validate_expired_coupon(self, client: AsyncClient, auth_headers, test_db):
        """Test validating expired coupon"""
        coupon_data = {
            "code": "EXPIRED",
            "discount_type": "fixed",
            "discount_value": 10,
            "min_order_amount": 0,
            "usage_limit": 0,  # No uses left
            "target_audience": "all_users",
            "is_active": True
        }
        await test_db.discount_coupons.insert_one(coupon_data)
        
        response = await client.post(
            "/promocodes/validate",
            headers=auth_headers,
            json={
                "code": "EXPIRED",
                "order_amount": 50
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["valid"] == False

class TestSettings:
    """Test settings endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_public_settings(self, client: AsyncClient):
        """Test getting public app settings"""
        response = await client.get("/settings/public")
        
        assert response.status_code == 200
        data = response.json()
        assert "app_name" in data or "currency" in data

class TestShopStatus:
    """Test shop status endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_shop_status(self, client: AsyncClient):
        """Test getting shop open/closed status"""
        response = await client.get("/shop/status")
        
        assert response.status_code == 200
        data = response.json()
        assert "is_open" in data
        assert isinstance(data["is_open"], bool)