import pytest
from httpx import AsyncClient
import json


@pytest.mark.integration
@pytest.mark.asyncio
class TestHealthEndpoint:
    """Test health check endpoint"""

    async def test_healthz_returns_ok(self, client: AsyncClient):
        """Test that health endpoint returns ok"""
        response = await client.get("/healthz")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


@pytest.mark.integration
@pytest.mark.asyncio
class TestAuthEndpoints:
    """Test authentication endpoints"""

    async def test_signup_creates_user(self, client: AsyncClient, sample_user_data):
        """Test that signup creates a new user"""
        response = await client.post("/api/auth/signup", json=sample_user_data)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] is not None
        assert data["email"] == sample_user_data["email"]

    async def test_signup_missing_fields(self, client: AsyncClient):
        """Test signup with missing fields"""
        response = await client.post(
            "/api/auth/signup",
            json={"first_name": "John"},  # Missing required fields
        )
        assert response.status_code == 400

    async def test_signup_invalid_email(self, client: AsyncClient):
        """Test signup with invalid email"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "first_name": "John",
                "last_name": "Doe",
                "phone": "+1234567890",
                "email": "invalid-email",
                "password": "TestPassword123!",
            },
        )
        assert response.status_code == 400

    async def test_signup_short_password(self, client: AsyncClient):
        """Test signup with password too short"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "first_name": "John",
                "last_name": "Doe",
                "phone": "+1234567890",
                "email": "john@example.com",
                "password": "short",
            },
        )
        assert response.status_code == 400

    async def test_signup_duplicate_email(self, client: AsyncClient, sample_user_data):
        """Test signup with duplicate email"""
        # First signup
        response1 = await client.post("/api/auth/signup", json=sample_user_data)
        assert response1.status_code == 200

        # Second signup with same email
        response2 = await client.post("/api/auth/signup", json=sample_user_data)
        assert response2.status_code == 409

    async def test_login_with_correct_credentials(self, client: AsyncClient, sample_user_data):
        """Test login with correct credentials"""
        # First create user
        await client.post("/api/auth/signup", json=sample_user_data)

        # Then login
        response = await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == sample_user_data["email"]

    async def test_login_with_incorrect_password(self, client: AsyncClient, sample_user_data):
        """Test login with incorrect password"""
        # Create user
        await client.post("/api/auth/signup", json=sample_user_data)

        # Try login with wrong password
        response = await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": "WrongPassword123!",
            },
        )
        assert response.status_code == 401

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent user"""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 401

    async def test_logout(self, client: AsyncClient, sample_user_data):
        """Test logout endpoint"""
        # Create and login user
        await client.post("/api/auth/signup", json=sample_user_data)
        response = await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )

        # Logout
        response = await client.post("/api/auth/logout")
        assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
class TestConversationEndpoints:
    """Test conversation endpoints"""

    async def test_get_conversations_requires_auth(self, client: AsyncClient):
        """Test that conversations endpoint requires authentication"""
        response = await client.get("/api/conversations")
        assert response.status_code == 401

    async def test_get_conversations_authenticated(self, client: AsyncClient, sample_user_data):
        """Test getting conversations when authenticated"""
        # Create and login user
        await client.post("/api/auth/signup", json=sample_user_data)
        await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )

        # Get conversations
        response = await client.get("/api/conversations")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


@pytest.mark.integration
@pytest.mark.asyncio
class TestStatsEndpoints:
    """Test statistics endpoints"""

    async def test_get_stats_requires_auth(self, client: AsyncClient):
        """Test that stats endpoint requires authentication"""
        response = await client.get("/api/stats")
        assert response.status_code == 401

    async def test_get_stats_authenticated(self, client: AsyncClient, sample_user_data):
        """Test getting stats when authenticated"""
        # Create and login user
        await client.post("/api/auth/signup", json=sample_user_data)
        await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )

        # Get stats
        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert "order_count" in data
        assert "order_by_category" in data


@pytest.mark.integration
@pytest.mark.asyncio
class TestDashboardEndpoint:
    """Test dashboard endpoint"""

    async def test_dashboard_requires_auth(self, client: AsyncClient):
        """Test that dashboard requires authentication"""
        response = await client.get("/dashboard")
        # Should redirect to login or return 401
        assert response.status_code in [301, 302, 401]

    async def test_dashboard_authenticated(self, client: AsyncClient, sample_user_data):
        """Test accessing dashboard when authenticated"""
        # Create and login user
        await client.post("/api/auth/signup", json=sample_user_data)
        await client.post(
            "/api/auth/login",
            json={
                "email": sample_user_data["email"],
                "password": sample_user_data["password"],
            },
        )

        # Get dashboard
        response = await client.get("/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


@pytest.mark.integration
@pytest.mark.asyncio
class TestRateLimiting:
    """Test rate limiting on endpoints"""

    async def test_signup_rate_limiting(self, client: AsyncClient):
        """Test that signup has rate limiting"""
        base_data = {
            "first_name": "Test",
            "last_name": "User",
            "phone": "+1234567890",
            "password": "TestPassword123!",
        }

        # Make multiple requests
        for i in range(6):
            data = base_data.copy()
            data["email"] = f"user{i}@example.com"
            response = await client.post("/api/auth/signup", json=data)

            if i < 5:
                # First 5 should succeed
                assert response.status_code in [200, 409]  # 409 for duplicates
            else:
                # 6th should be rate limited
                assert response.status_code == 429

    async def test_login_rate_limiting(self, client: AsyncClient):
        """Test that login has rate limiting"""
        # Make multiple failed login attempts
        for i in range(6):
            response = await client.post(
                "/api/auth/login",
                json={
                    "email": "user@example.com",
                    "password": f"password{i}",
                },
            )

            if i < 5:
                # First 5 should get 401
                assert response.status_code == 401
            else:
                # 6th should be rate limited
                assert response.status_code == 429
