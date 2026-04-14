"""
Tests for Auth Router
=====================
Test authentication endpoints: login, logout, forgot-password, reset-password.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, patch
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers import auth
from fastapi import FastAPI

app = FastAPI()
app.include_router(auth.router)


@pytest.fixture
def client(db_session):
    """Create test client with overridden get_db dependency."""
    from database import get_db
    
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestAuthLogin:
    """Test login endpoint."""
    
    def test_login_success(self, client, admin_user, db_session):
        """Test successful login."""
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        # Update password hash to match test password
        admin_user.password_hash = pwd_context.hash("TestPassword123!")
        db_session.commit()
        
        response = client.post(
            "/api/auth/login",
            json={
                "email": "test@smartwall.be",
                "password": "TestPassword123!"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "user" in data
        assert data["user"]["id"] == admin_user.id
        assert data["user"]["name"] == "Test Admin"
    
    def test_login_invalid_credentials(self, client, admin_user):
        """Test login with invalid credentials."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "test@smartwall.be",
                "password": "WrongPassword"
            }
        )
        
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    
    def test_login_user_not_found(self, client):
        """Test login with non-existent user."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "nonexistent@test.be",
                "password": "SomePassword"
            }
        )
        
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid email or password"
    
    def test_login_empty_password(self, client):
        """Test login with empty password."""
        response = client.post(
            "/api/auth/login",
            json={
                "email": "test@smartwall.be",
                "password": ""
            }
        )
        
        assert response.status_code == 401  # Returns 401 for invalid credentials (empty password)
        assert "invalid" in response.json()["detail"].lower()


class TestAuthLogout:
    """Test logout endpoint."""
    
    def test_logout_success(self, client):
        """Test successful logout."""
        response = client.post("/api/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "message" in data
        assert "logged out" in data["message"].lower()


class TestAuthForgotPassword:
    """Test forgot-password endpoint."""
    
    def test_forgot_password_success(self, client, admin_user):
        """Test successful forgot password request."""
        response = client.post(
            "/api/auth/forgot-password",
            json={
                "email": "test@smartwall.be"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Security: Should not reveal if email exists
        assert "reset link" in data["message"].lower() or "registered" in data["message"].lower()
    
    def test_forgot_password_nonexistent_email(self, client):
        """Test forgot password with non-existent email."""
        response = client.post(
            "/api/auth/forgot-password",
            json={
                "email": "nonexistent@test.be"
            }
        )
        
        assert response.status_code == 200
        # Security: Should return same response for non-existent email
        data = response.json()
        assert data["success"] is True
    
    def test_forgot_password_invalid_email(self, client):
        """Test forgot password with invalid email format."""
        response = client.post(
            "/api/auth/forgot-password",
            json={
                "email": "not-an-email"
            }
        )
        
        assert response.status_code == 422  # Validation error


class TestAuthResetPassword:
    """Test reset-password endpoint."""
    
    def test_reset_password_success(self, client, admin_user):
        """Test successful password reset."""
        import jwt
        import datetime
        import os
        
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        
        # Create valid reset token
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
        reset_token_data = {"sub": str(admin_user.id), "exp": expire, "type": "reset"}
        reset_token = jwt.encode(reset_token_data, SECRET_KEY, algorithm=ALGORITHM)
        
        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": reset_token,
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "password" in data["message"].lower() or "changed" in data["message"].lower()
    
    def test_reset_password_expired_token(self, client, admin_user):
        """Test password reset with expired token."""
        import jwt
        import datetime
        import os
        
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        
        # Create expired reset token
        expire = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
        reset_token_data = {"sub": str(admin_user.id), "exp": expire, "type": "reset"}
        reset_token = jwt.encode(reset_token_data, SECRET_KEY, algorithm=ALGORITHM)
        
        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": reset_token,
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "expired" in data["detail"].lower()
    
    def test_reset_password_invalid_type(self, client, admin_user):
        """Test password reset with wrong token type."""
        import jwt
        import datetime
        import os
        
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        
        # Create login token (not reset token)
        expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        token_data = {"sub": str(admin_user.id), "exp": expire}
        token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
        
        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": token,
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "invalid token type" in data["detail"].lower()
    
    def test_reset_password_invalid_token(self, client):
        """Test password reset with invalid token."""
        response = client.post(
            "/api/auth/reset-password",
            json={
                "token": "invalid.token.here",
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "invalid" in data["detail"].lower() or "corrupted" in data["detail"].lower()


class TestAuthGetMe:
    """Test get current user endpoint."""
    
    def test_get_me_success(self, client, admin_user, auth_headers):
        """Test getting current user profile."""
        response = client.get(
            "/api/user/me",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == admin_user.id
        assert data["name"] == "Test Admin"
        assert data["email"] == "test@smartwall.be"
        assert "avatar" in data
    
    def test_get_me_no_token(self, client):
        """Test getting user profile without token."""
        response = client.get("/api/user/me")
        
        assert response.status_code == 401
        data = response.json()
        assert "not authenticated" in data["detail"].lower() or "invalid token" in data["detail"].lower()
    
    def test_get_me_invalid_token(self, client):
        """Test getting user profile with invalid token."""
        response = client.get(
            "/api/user/me",
            headers={"Authorization": "Bearer invalid_token"}
        )
        
        assert response.status_code == 401
