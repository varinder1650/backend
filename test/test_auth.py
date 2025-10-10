"""
Authentication Endpoint Tests
File: tests/test_auth.py
"""
import pytest
from httpx import AsyncClient

class TestRegistration:
    """Test user registration endpoint"""
    
    @pytest.mark.asyncio
    async def test_register_success(self, client: AsyncClient):
        """Test successful user registration"""
        response = await client.post(
            "/auth/register",
            json={
                "name": "New User",
                "email": "newuser@example.com",
                "password": "securepass123",
                "phone": "+1234567893"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == "newuser@example.com"
    
    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client: AsyncClient, test_user):
        """Test registration with duplicate email"""
        response = await client.post(
            "/auth/register",
            json={
                "name": "Duplicate User",
                "email": test_user["email"],
                "password": "password123",
                "phone": "+1234567894"
            }
        )
        
        assert response.status_code == 400
        assert "already exists" in response.json()["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registration with invalid email format"""
        response = await client.post(
            "/auth/register",
            json={
                "name": "Invalid Email",
                "email": "notanemail",
                "password": "password123",
                "phone": "+1234567895"
            }
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_register_short_password(self, client: AsyncClient):
        """Test registration with password too short"""
        response = await client.post(
            "/auth/register",
            json={
                "name": "Short Pass",
                "email": "shortpass@example.com",
                "password": "123",
                "phone": "+1234567896"
            }
        )
        
        assert response.status_code == 422
    
    @pytest.mark.asyncio
    async def test_register_missing_fields(self, client: AsyncClient):
        """Test registration with missing required fields"""
        response = await client.post(
            "/auth/register",
            json={
                "name": "Incomplete User",
                "email": "incomplete@example.com"
            }
        )
        
        assert response.status_code == 422

class TestLogin:
    """Test user login endpoint"""
    
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient, test_user):
        """Test successful login"""
        response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["user"]["email"] == test_user["email"]
    
    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Test login with wrong password"""
        response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "wrongpassword"
            }
        )
        
        assert response.status_code == 401
        assert "invalid" in response.json()["detail"].lower()
    
    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent email"""
        response = await client.post(
            "/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123"
            }
        )
        
        assert response.status_code == 401
    
    @pytest.mark.asyncio
    async def test_login_inactive_user(self, client: AsyncClient, test_db, test_user):
        """Test login with inactive user account"""
        # Deactivate user
        await test_db.users.update_one(
            {"id": test_user["id"]},
            {"$set": {"is_active": False}}
        )
        
        response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        
        assert response.status_code == 401

class TestGoogleLogin:
    """Test Google OAuth login"""
    
    @pytest.mark.asyncio
    async def test_google_login_new_user(self, client: AsyncClient):
        """Test Google login with new user"""
        response = await client.post(
            "/auth/google",
            json={
                "googleToken":"googletoken",
                "user": {
                    "email": "googleuser@example.com",
                    "name": "Google User",
                    "googleId": "google123"
                }
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["requires_phone"] == True
        assert data["user"]["provider"] == "google"
    
    @pytest.mark.asyncio
    async def test_google_login_existing_user(self, client: AsyncClient, test_db):
        """Test Google login with existing user"""
        # Create Google user
        from app.utils.auth import create_pasword_hash
        from bson import ObjectId
        from datetime import datetime
        
        google_user = {
            "id": "CUSGOOGLE001",
            "_id": ObjectId(),
            "name": "Existing Google User",
            "email": "existing@gmail.com",
            "phone": "TEMP_google123",
            "phone_is_temporary": True,
            # "hashed_password": create_pasword_hash("dummy"),
            "role": "customer",
            "is_active": True,
            "provider": "google",
            "google_id": "google123",
            "created_at": datetime.utcnow()
        }
        
        await test_db.users.insert_one(google_user)
        
        response = await client.post(
            "/auth/google",
            json={
                "googleToken":"googletoken",
                "user": {
                    "email": "existing@gmail.com",
                    "name": "Existing Google User",
                    "googleId": "google123"
                }
            }
        )
        
        assert response.status_code == 200
        assert response.json()["requires_phone"] == True
    
    @pytest.mark.asyncio
    async def test_google_login_missing_data(self, client: AsyncClient):
        """Test Google login with missing required data"""
        response = await client.post(
            "/auth/google",
            json={
                "googleToken":"googletoken",
                "user": {
                    "email": "incomplete@gmail.com"
                }
            }
        )
        
        assert response.status_code == 400

class TestPhoneUpdate:
    """Test phone number update endpoint"""
    
    @pytest.mark.asyncio
    async def test_update_phone_success(self, client: AsyncClient, auth_headers):
        """Test successful phone update"""
        response = await client.post(
            "/auth/phone",
            headers=auth_headers,
            json={"phone": "+9876543210"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] == True
        assert data["user"]["phone"] == "+9876543210"
    
    @pytest.mark.asyncio
    async def test_update_phone_duplicate(self, client: AsyncClient, auth_headers, test_db, test_user):
        """Test phone update with duplicate number"""
        # Create another user with phone
        from bson import ObjectId
        from app.utils.auth import create_pasword_hash
        from datetime import datetime
        
        other_user = {
            "id": "CUSOTHER001",
            "_id": ObjectId(),
            "name": "Other User",
            "email": "other@example.com",
            "phone": "+1111111111",
            "hashed_password": create_pasword_hash("pass123"),
            "role": "customer",
            "is_active": True,
            "created_at": datetime.utcnow()
        }
        await test_db.users.insert_one(other_user)
        
        response = await client.post(
            "/auth/phone",
            headers=auth_headers,
            json={"phone": "+1111111111"}
        )
        
        assert response.status_code == 400
    
    @pytest.mark.asyncio
    async def test_update_phone_unauthorized(self, client: AsyncClient):
        """Test phone update without authentication"""
        response = await client.post(
            "/auth/phone",
            json={"phone": "+9876543210"}
        )
        
        assert response.status_code == 401

class TestProfile:
    """Test profile endpoints"""
    
    @pytest.mark.asyncio
    async def test_get_profile_success(self, client: AsyncClient, auth_headers, test_user):
        """Test getting user profile"""
        response = await client.get(
            "/auth/profile",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user["email"]
    
    @pytest.mark.asyncio
    async def test_update_profile_success(self, client: AsyncClient, auth_headers):
        """Test updating user profile"""
        response = await client.put(
            "/auth/profile",
            headers=auth_headers,
            json={"name": "Updated Name"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["name"] == "Updated Name"
    
    @pytest.mark.asyncio
    async def test_profile_unauthorized(self, client: AsyncClient):
        """Test profile access without authentication"""
        response = await client.get("/auth/profile")
        assert response.status_code == 401

class TestPasswordReset:
    """Test password reset flow"""
    
    @pytest.mark.asyncio
    async def test_forgot_password_success(self, client: AsyncClient, test_user):
        """Test forgot password request"""
        response = await client.post(
            "/auth/forgot-password",
            json={"email": test_user["email"]}
        )
        
        assert response.status_code == 200
        assert "success" in response.json()
    
    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent(self, client: AsyncClient):
        """Test forgot password with non-existent email"""
        response = await client.post(
            "/auth/forgot-password",
            json={"email": "nonexistent@example.com"}
        )
        
        # Should still return success to prevent email enumeration
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_reset_password_success(self, client: AsyncClient, test_db, test_user):
        """Test password reset with valid token"""
        from datetime import datetime, timedelta
        import secrets
        
        # Create reset token
        token = secrets.token_urlsafe(32)
        reset_doc = {
            "user_id": test_user["id"],
            "token": token,
            "expires_at": datetime.utcnow() + timedelta(hours=1),
            "used": False,
            "created_at": datetime.utcnow()
        }
        await test_db.password_reset_tokens.insert_one(reset_doc)
        
        response = await client.post(
            "/auth/reset-password",
            json={
                "token": token,
                "new_password": "newsecurepass123"
            }
        )
        
        assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_reset_password_invalid_token(self, client: AsyncClient):
        """Test password reset with invalid token"""
        response = await client.post(
            "/auth/reset-password",
            json={
                "token": "invalidtoken",
                "new_password": "newsecurepass123"
            }
        )
        
        assert response.status_code == 400

class TestTokenRefresh:
    """Test token refresh endpoint"""
    
    @pytest.mark.asyncio
    async def test_refresh_token_success(self, client: AsyncClient, test_user):
        """Test successful token refresh"""
        # First login to get refresh token
        login_response = await client.post(
            "/auth/login",
            json={
                "email": test_user["email"],
                "password": "testpass123"
            }
        )
        
        refresh_token = login_response.json()["refresh_token"]
        
        # Refresh the token
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": refresh_token}
        )
        
        assert response.status_code == 200
        assert "access_token" in response.json()
    
    @pytest.mark.asyncio
    async def test_refresh_token_invalid(self, client: AsyncClient):
        """Test token refresh with invalid token"""
        response = await client.post(
            "/auth/refresh",
            json={"refresh_token": "invalid_token"}
        )
        
        assert response.status_code == 401