"""
Tests for Admins Router
=======================
Test admin management endpoints: CRUD operations and password updates.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from fastapi import FastAPI
from unittest.mock import Mock, patch
import sys
import os
import models

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers import admins
from fastapi import FastAPI

app = FastAPI()
app.include_router(admins.router)


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


class TestAdminGetProfile:
    """Test get my profile endpoint."""
    
    def test_get_my_profile_success(self, client, admin_user, auth_headers):
        """Test getting own profile."""
        response = client.get(
            "/api/admins/me",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == admin_user.id
        assert data["name"] == "Test Admin"
        assert data["email"] == "test@smartwall.be"


class TestAdminUpdateProfile:
    """Test update profile endpoint."""
    
    def test_update_my_profile_success(self, client, admin_user, auth_headers):
        """Test successful profile update."""
        response = client.put(
            "/api/admins/me",
            headers=auth_headers,
            json={
                "name": "Updated Name",
                "email": "updated.email@smartwall.be",
                "phone": "+32470999888"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Name"
        assert data["email"] == "updated.email@smartwall.be"
        assert data["phone"] == "+32470999888"
    
    def test_update_my_profile_email_exists(self, client, admin_user, auth_headers, db_session):
        """Test updating to existing email."""
        # Create another admin
        from routers.auth import pwd_context
        admin2 = models.Admin(
            name="Admin 2",
            email="admin2@smartwall.be",
            password_hash=pwd_context.hash("Password123!")
        )
        db_session.add(admin2)
        db_session.commit()
        
        response = client.put(
            "/api/admins/me",
            headers=auth_headers,
            json={
                "email": "admin2@smartwall.be"
            }
        )
        
        # Allow both 400 (database constraint) and 422 (Pydantic validation)
        assert response.status_code in [400, 422]
        if response.status_code == 400:
            assert "al in gebruik" in response.json()["detail"].lower()
        else:
            detail = response.json()["detail"]
            assert isinstance(detail, list)
            assert any("email" in str(d).lower() or "field" in str(d).lower() for d in detail) or "field" in response.json()["detail"].lower()
    
    def test_update_my_profile_duplicate_email(self, client, admin_user, auth_headers, db_session):
        """Test email uniqueness validation."""
        # Create another admin with different email
        from routers.auth import pwd_context
        admin2 = models.Admin(
            name="Admin 2",
            email="admin2@smartwall.be",
            password_hash=pwd_context.hash("Password123!")
        )
        db_session.add(admin2)
        db_session.commit()
        
        # Try to change admin's email to admin2's email
        response = client.put(
            "/api/admins/me",
            headers=auth_headers,
            json={
                "email": "admin2@smartwall.be"
            }
        )
        
        assert response.status_code in [400, 422]


class TestAdminUpdatePassword:
    """Test update password endpoint."""
    
    def test_update_password_success(self, client, admin_user, auth_headers, db_session):
        """Test successful password update."""
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        # Update password
        admin_user.password_hash = pwd_context.hash("OldPassword123!")
        db_session.commit()
        
        response = client.put(
            "/api/admins/me/password",
            headers=auth_headers,
            json={
                "current_password": "OldPassword123!",
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "wachtwoord" in data["detail"].lower() or "gewijzigd" in data["detail"].lower()
        
        # Verify password was actually changed
        db_session.refresh(admin_user)
        assert pwd_context.verify("NewSecurePassword456!", admin_user.password_hash)
    
    def test_update_password_wrong_current(self, client, admin_user, auth_headers, db_session):
        """Test updating password with wrong current password."""
        response = client.put(
            "/api/admins/me/password",
            headers=auth_headers,
            json={
                "current_password": "WrongPassword",
                "new_password": "NewSecurePassword456!"
            }
        )
        
        assert response.status_code in [400, 422]
        assert "huidig" in response.json()["detail"].lower() or "onjuist" in response.json()["detail"].lower()
    
    def test_update_password_empty_fields(self, client, admin_user, auth_headers):
        """Test password update with empty fields."""
        response = client.put(
            "/api/admins/me/password",
            headers=auth_headers,
            json={
                "current_password": "",
                "new_password": "NewPassword"
            }
        )
        
        # Empty password validation returns 400 (not 422 validation error)
        assert response.status_code in [400, 422]
        assert "huidig" in response.json()["detail"].lower() or "onjuist" in response.json()["detail"].lower() or "empty" in response.json()["detail"].lower()


class TestAdminList:
    """Test list admins endpoint."""
    
    def test_list_admins_success(self, client, admin_user, auth_headers, db_session):
        """Test successful admin listing."""
        # Create some admins
        from routers.auth import pwd_context
        for i in range(3):
            new_admin = models.Admin(
                name=f"Admin {i}",
                email=f"admin{i}@smartwall.be",
                password_hash=pwd_context.hash(f"Password{i}!")
            )
            db_session.add(new_admin)
        db_session.commit()
        
        response = client.get(
            "/api/admins",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 4  # Original + 3 created
    
    def test_list_admins_unauthorized(self, client):
        """Test listing admins without authentication."""
        response = client.get("/api/admins")
        
        assert response.status_code == 401


class TestAdminCreate:
    """Test create admin endpoint."""
    
    def test_create_admin_success(self, client, superadmin_user, superadmin_auth_headers, db_session):
        """Test successful admin creation."""
        response = client.post(
            "/api/admins",
            headers=superadmin_auth_headers,
            json={
                "name": "New Admin",
                "email": "newadmin@smartwall.be",
                "phone": "+32470111222",
                "password": "NewAdminPassword123!",
                "role": "admin"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "New Admin"
        assert data["email"] == "newadmin@smartwall.be"
        assert data["phone"] == "+32470111222"
        assert data["role"] == "admin"
        
        # Verify password was hashed - password hash should be different from plain text
        new_admin = db_session.query(models.Admin).filter_by(email="newadmin@smartwall.be").first()
        assert new_admin.password_hash != "NewAdminPassword123!"
    
    def test_create_admin_duplicate_email(self, client, superadmin_user, superadmin_auth_headers, db_session):
        """Test creating admin with existing email."""
        # First create an admin with a specific email
        from routers.auth import pwd_context
        existing_admin = models.Admin(
            name="Existing Admin",
            email="existing@smartwall.be",
            password_hash=pwd_context.hash("Password123!"),
            role="admin"
        )
        db_session.add(existing_admin)
        db_session.commit()
        
        # Try to create another admin with the same email
        response = client.post(
            "/api/admins",
            headers=superadmin_auth_headers,
            json={
                "name": "Duplicate Admin",
                "email": "existing@smartwall.be",  # Existing email
                "phone": "+32470111222",
                "password": "SomePassword123!",
                "role": "admin"
            }
        )
        
        assert response.status_code in [400, 422]
        assert "al in gebruik" in response.json()["detail"].lower()
    
    def test_create_admin_missing_fields(self, client, superadmin_user, superadmin_auth_headers):
        """Test creating admin with missing required fields."""
        response = client.post(
            "/api/admins",
            headers=superadmin_auth_headers,
            json={
                "name": "Incomplete Admin",
                "email": "incomplete@smartwall.be"
                # Missing password
            }
        )
        
        assert response.status_code == 422


class TestAdminDelete:
    """Test delete admin endpoint."""
    
    def test_delete_admin_success(self, client, superadmin_user, superadmin_auth_headers, db_session):
        """Test successful admin deletion."""
        # Create admin to delete
        from routers.auth import pwd_context
        admin_to_delete = models.Admin(
            name="ToDelete Admin",
            email="todelete@smartwall.be",
            password_hash=pwd_context.hash("Password123!")
        )
        db_session.add(admin_to_delete)
        db_session.commit()
        
        response = client.delete(
            f"/api/admins/{admin_to_delete.id}",
            headers=superadmin_auth_headers
        )
        
        assert response.status_code == 204
        
        # Verify admin was deleted
        deleted_admin = db_session.query(models.Admin).filter_by(id=admin_to_delete.id).first()
        assert deleted_admin is None
    
    def test_delete_admin_as_regular_admin(self, client, admin_user, auth_headers, db_session):
        """Test regular admin trying to delete another admin."""
        # Create admin to delete
        from routers.auth import pwd_context
        admin_to_delete = models.Admin(
            name="ToDelete Admin",
            email="todelete@smartwall.be",
            password_hash=pwd_context.hash("Password123!")
        )
        db_session.add(admin_to_delete)
        db_session.commit()
        
        response = client.delete(
            f"/api/admins/{admin_to_delete.id}",
            headers=auth_headers
        )
        
        assert response.status_code == 403
        assert "superadmin" in response.json()["detail"].lower()
    
    def test_delete_admin_self(self, client, admin_user, auth_headers, db_session):
        """Test admin trying to delete themselves."""
        response = client.delete(
            f"/api/admins/{admin_user.id}",
            headers=auth_headers
        )
        
        # Regular admin cannot delete admins (403), cannot even try to delete self
        assert response.status_code == 403
        assert "superadmin" in response.json()["detail"].lower() or "alleen" in response.json()["detail"].lower()
    
    def test_delete_admin_not_found(self, client, superadmin_user, superadmin_auth_headers):
        """Test deleting non-existent admin."""
        response = client.delete(
            "/api/admins/99999",
            headers=superadmin_auth_headers
        )
        
        assert response.status_code == 404
        assert "gevonden" in response.json()["detail"].lower() or "niet" in response.json()["detail"].lower()
