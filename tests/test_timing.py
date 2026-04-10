"""
Tests for API Endpoint Timing
==============================
Tests that all API endpoints respond within 1000ms with correct status codes.
"""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from fastapi import FastAPI
import models
from database import get_db
from passlib.context import CryptContext


# Setup app with all routers
from routers import auth, admins, residents, walls, logs, dashboard, maintenance

app = FastAPI()
app.include_router(auth.router)
app.include_router(admins.router)
app.include_router(residents.router)
app.include_router(walls.router)
app.include_router(logs.router)
app.include_router(dashboard.router)
app.include_router(maintenance.router)

# Add system status endpoint (from main.py)
@app.get("/api/system/status", tags=["Systeem & Logs"])
async def get_status():
    return {
        "online": True,
        "active_alarms": False,
        "message": "FastAPI backend is succesvol gekoppeld!"
    }


@pytest.fixture
def client(db_session):
    """Create test client with overridden get_db dependency."""
    def override_get_db():
        yield db_session
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(db_session):
    """Generate auth headers for testing with a valid admin."""
    import jwt
    import datetime
    import os
    
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    # Check if admin exists, if not create one
    admin = db_session.query(models.Admin).first()
    if not admin:
        admin = models.Admin(
            name="Test Admin",
            email="test@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"),
            phone="+32400123456",
            role="admin"
        )
        db_session.add(admin)
        db_session.commit()
        db_session.refresh(admin)
    
    SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
    ALGORITHM = "HS256"
    
    expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
    token_data = {"sub": str(admin.id), "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"Authorization": f"Bearer {token}"}


# ==========================================
# AUTH ROUTER TESTS (6 endpoints)
# ==========================================
class TestAuthEndpoints:
    
    def test_login_successful(self, client, db_session):
        """POST /api/auth/login - expect 200 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = models.Admin(
            name="Test Admin", email="test@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"),
            phone="+32400123456", role="admin"
        )
        db_session.add(admin)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/auth/login", json={"email": "test@smartwall.be", "password": "TestPassword123!"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert "access_token" in response.json()
    
    def test_login_invalid_credentials(self, client, db_session):
        """POST /api/auth/login - expect 401 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = models.Admin(
            name="Test Admin", email="test@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"),
            phone="+32400123456", role="admin"
        )
        db_session.add(admin)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/auth/login", json={"email": "test@smartwall.be", "password": "WrongPass"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 401
        assert elapsed < 1000
    
    def test_logout_successful(self, client):
        """POST /api/auth/logout - expect 200 within 1000ms."""
        start = time.time()
        response = client.post("/api/auth/logout")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert response.json()["success"] is True
    
    def test_forgot_password_successful(self, client):
        """POST /api/auth/forgot-password - expect 200 within 1000ms."""
        start = time.time()
        response = client.post("/api/auth/forgot-password", json={"email": "test@smartwall.be"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert response.json()["success"] is True
    
    def test_forgot_password_invalid_email(self, client):
        """POST /api/auth/forgot-password - expect 422 within 1000ms."""
        start = time.time()
        response = client.post("/api/auth/forgot-password", json={"email": "invalid-email"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 422
        assert elapsed < 1000
    
    def test_reset_password_successful(self, client, db_session):
        """POST /api/auth/reset-password - expect 200 within 1000ms."""
        import jwt
        import datetime
        import os
        
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = models.Admin(
            name="Test Admin", email="test@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"),
            phone="+32400123456", role="admin"
        )
        db_session.add(admin)
        db_session.commit()
        
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=15)
        reset_token_data = {"sub": str(admin.id), "exp": expire, "type": "reset"}
        reset_token = jwt.encode(reset_token_data, SECRET_KEY, algorithm=ALGORITHM)
        
        start = time.time()
        response = client.post("/api/auth/reset-password", json={"token": reset_token, "new_password": "NewSecure123!"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert response.json()["success"] is True
    
    def test_get_me_successful(self, client, auth_headers):
        """GET /api/user/me - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/user/me", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert "id" in response.json()
    
    def test_get_me_unauthorized(self, client):
        """GET /api/user/me - expect 401 within 1000ms."""
        start = time.time()
        response = client.get("/api/user/me")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 401
        assert elapsed < 1000


# ==========================================
# ADMINS ROUTER TESTS (6 endpoints)
# ==========================================
class TestAdminsEndpoints:
    
    def test_get_my_profile_successful(self, client, auth_headers):
        """GET /api/admins/me - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/admins/me", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_update_my_profile_successful(self, client, auth_headers, db_session):
        """PUT /api/admins/me - expect 200 within 1000ms."""
        start = time.time()
        response = client.put("/api/admins/me", headers=auth_headers, json={
            "name": "Updated", "email": "updated@smartwall.be", "phone": "+32470999888"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_update_my_profile_email_exists(self, client, auth_headers, db_session):
        """PUT /api/admins/me with duplicate email - expect 400 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin2 = models.Admin(
            name="Admin 2", email="admin2@smartwall.be",
            password_hash=pwd_context.hash("Password123!"), phone="+32400333444", role="admin"
        )
        db_session.add(admin2)
        db_session.commit()
        
        start = time.time()
        response = client.put("/api/admins/me", headers=auth_headers, json={"email": "admin2@smartwall.be"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code in [400, 422]
        assert elapsed < 1000
    
    def test_update_my_password_successful(self, client, auth_headers, db_session):
        """PUT /api/admins/me/password - expect 200 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = db_session.query(models.Admin).first()
        admin.password_hash = pwd_context.hash("TestPassword123!")
        db_session.commit()
        
        start = time.time()
        response = client.put("/api/admins/me/password", headers=auth_headers, json={
            "current_password": "TestPassword123!", "new_password": "NewSecure123!"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_list_admins_successful(self, client, auth_headers):
        """GET /api/admins - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/admins", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert isinstance(response.json(), list)
    
    def test_list_admins_unauthorized(self, client):
        """GET /api/admins - expect 401 within 1000ms."""
        start = time.time()
        response = client.get("/api/admins")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 401
        assert elapsed < 1000
    
    def test_create_admin_successful(self, client, db_session):
        """POST /api/admins - expect 201 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        superadmin = models.Admin(
            name="Super Admin", email="superadmin@smartwall.be",
            password_hash=pwd_context.hash("SuperPassword123!"), phone="+32400987654", role="superadmin"
        )
        db_session.add(superadmin)
        db_session.commit()
        
        import jwt
        import datetime
        import os
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
        token_data = {"sub": str(superadmin.id), "exp": expire}
        token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
        auth_headers = {"Authorization": f"Bearer {token}"}
        
        start = time.time()
        response = client.post("/api/admins", headers=auth_headers, json={
            "name": "New Admin", "email": "newadmin@test.be", "phone": "+32470111222",
            "password": "NewAdminPassword123!", "role": "admin"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 201
        assert elapsed < 1000
    
    def test_create_admin_duplicate_email(self, client, auth_headers, db_session):
        """POST /api/admins with duplicate email - expect 400 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin1 = models.Admin(
            name="Admin 1", email="existing@smartwall.be",
            password_hash=pwd_context.hash("Password123!"), phone="+32400111222", role="admin"
        )
        db_session.add(admin1)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/admins", headers=auth_headers, json={
            "name": "Duplicate", "email": "existing@smartwall.be", "phone": "+32470111222",
            "password": "SomePassword123!", "role": "admin"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code in [400, 422]
        assert elapsed < 1000
    
    def test_delete_admin_successful(self, client, db_session):
        """DELETE /api/admins/{id} - expect 204 within 1000ms."""
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        superadmin = models.Admin(
            name="Super Admin", email="superadmin2@smartwall.be",
            password_hash=pwd_context.hash("SuperPassword123!"), phone="+32400987654", role="superadmin"
        )
        db_session.add(superadmin)
        db_session.commit()
        
        admin_to_delete = models.Admin(
            name="To Delete", email="todelete@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"), phone="+32400999888", role="admin"
        )
        db_session.add(admin_to_delete)
        db_session.commit()
        
        import jwt
        import datetime
        import os
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
        token_data = {"sub": str(superadmin.id), "exp": expire}
        token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
        auth_headers = {"Authorization": f"Bearer {token}"}
        
        start = time.time()
        response = client.delete(f"/api/admins/{admin_to_delete.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 204
        assert elapsed < 1000
    
    def test_delete_admin_not_found(self, client, db_session):
        """DELETE /api/admins/{id} not found - expect 404 within 1000ms."""
        import jwt
        import datetime
        import os
        from passlib.context import CryptContext
        
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        superadmin = models.Admin(
            name="Super Admin", email="superadmin4@smartwall.be",
            password_hash=pwd_context.hash("SuperPassword123!"), phone="+32400987654", role="superadmin"
        )
        db_session.add(superadmin)
        db_session.commit()
        
        SECRET_KEY = os.getenv("SECRET_KEY", "super_geheime_sleutel_voor_smartwall")
        ALGORITHM = "HS256"
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=24)
        token_data = {"sub": str(superadmin.id), "exp": expire}
        token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
        auth_headers = {"Authorization": f"Bearer {token}"}
        
        start = time.time()
        response = client.delete("/api/admins/99999", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000


# ==========================================
# RESIDENTS ROUTER TESTS (6 endpoints)
# ==========================================
class TestResidentsEndpoints:
    
    def test_get_residents_successful(self, client, auth_headers, db_session):
        """GET /api/residents - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/residents", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert "items" in response.json()
    
    def test_create_resident_successful(self, client, auth_headers, db_session):
        """POST /api/residents - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key")
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/residents", headers=auth_headers, json={
            "name": "Test Resident", "email": "test.resident@test.be", "unit_number": "Bus 99",
            "phone": "+32470123456", "location_id": location.id
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_update_resident_successful(self, client, auth_headers, db_session):
        """PUT /api/residents/{id} - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key")
        db_session.add(location)
        db_session.commit()
        
        resident = models.User(
            location_id=location.id, name="Test Resident", email="test@resident.be",
            unit_number="Bus 1", phone="+32470123456"
        )
        db_session.add(resident)
        db_session.commit()
        
        start = time.time()
        response = client.put(f"/api/residents/{resident.id}", headers=auth_headers, json={
            "name": "Updated Name", "email": "updated.resident@test.be", "phone": "+32470999888"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_update_resident_not_found(self, client, auth_headers):
        """PUT /api/residents/{id} not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.put("/api/residents/99999", headers=auth_headers, json={"name": "Updated"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000
    
    def test_delete_resident_successful(self, client, auth_headers, db_session):
        """DELETE /api/residents/{id} - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key")
        db_session.add(location)
        db_session.commit()
        
        resident = models.User(
            location_id=location.id, name="To Delete", email="todelete@test.be",
            unit_number="Bus 99", phone="+32470123456"
        )
        db_session.add(resident)
        db_session.commit()
        
        start = time.time()
        response = client.delete(f"/api/residents/{resident.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_generate_credentials_successful(self, client, auth_headers, db_session):
        """POST /api/residents/{id}/credentials/generate - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key")
        db_session.add(location)
        db_session.commit()
        
        resident = models.User(
            location_id=location.id, name="Test Resident", email="test@resident.be",
            unit_number="Bus 1", phone="+32470123456"
        )
        db_session.add(resident)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Occupied", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        parcel = models.Parcel(
            locker_id=locker.id, user_id=resident.id, tracking_code="3SBP123456789",
            courier="bpost", pincode="hashed_pin", status="Delivered"
        )
        db_session.add(parcel)
        db_session.commit()
        
        start = time.time()
        response = client.post(f"/api/residents/{resident.id}/credentials/generate", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert response.json()["success"] is True
    
    def test_generate_credentials_no_parcels(self, client, auth_headers, db_session):
        """POST /api/residents/{id}/credentials/generate - no parcels - expect 400 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key")
        db_session.add(location)
        db_session.commit()
        
        resident = models.User(
            location_id=location.id, name="Test Resident", email="test@resident.be",
            unit_number="Bus 1", phone="+32470123456"
        )
        db_session.add(resident)
        db_session.commit()
        
        start = time.time()
        response = client.post(f"/api/residents/{resident.id}/credentials/generate", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 400
        assert elapsed < 1000
    
    def test_generate_credentials_not_found(self, client, auth_headers):
        """POST /api/residents/{id}/credentials/generate - not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.post("/api/residents/99999/credentials/generate", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000


# ==========================================
# WALLS ROUTER TESTS (6 endpoints)
# ==========================================
class TestWallsEndpoints:
    
    def test_get_walls_successful(self, client, auth_headers, db_session):
        """GET /api/walls - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/walls", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert isinstance(response.json(), list)
    
    def test_get_walls_with_search(self, client, auth_headers, db_session):
        """GET /api/walls with search - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/walls", headers=auth_headers, params={"search": "Test"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_walls_status_filter(self, client, auth_headers, db_session):
        """GET /api/walls with status filter - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/walls", headers=auth_headers, params={"status": "OFFLINE"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_wall_detail_successful(self, client, auth_headers, db_session):
        """GET /api/walls/{id} - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.get(f"/api/walls/{location.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_wall_detail_not_found(self, client, auth_headers):
        """GET /api/walls/{id} not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.get("/api/walls/99999", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000
    
    def test_get_locker_detail_successful(self, client, auth_headers, db_session):
        """GET /api/lockers/{id} - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Available", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        start = time.time()
        response = client.get(f"/api/lockers/{locker.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_locker_detail_occupied(self, client, auth_headers, db_session):
        """GET /api/lockers/{id} occupied - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Occupied", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        resident = models.User(location_id=location.id, name="Resident", email="res@test.be", unit_number="Bus 1", phone="+32470123456")
        db_session.add(resident)
        db_session.commit()
        
        parcel = models.Parcel(locker_id=locker.id, user_id=resident.id, tracking_code="3SBP123456789",
                               courier="bpost", pincode="hash", status="Delivered")
        db_session.add(parcel)
        db_session.commit()
        
        start = time.time()
        response = client.get(f"/api/lockers/{locker.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_locker_detail_not_found(self, client, auth_headers):
        """GET /api/lockers/{id} not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.get("/api/lockers/99999", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000
    
    def test_create_wall_successful(self, client, auth_headers):
        """POST /api/walls - expect 200 within 1000ms."""
        start = time.time()
        response = client.post("/api/walls", headers=auth_headers, json={
            "name": "New Test Location", "address": "Test Street 99",
            "lockers": [{"door_number": 1, "size": "S"}, {"door_number": 2, "size": "M"}, {"door_number": 3, "size": "L"}]
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert len(response.json()["lockers"]) == 3
    
    def test_create_wall_empty_lockers(self, client, auth_headers):
        """POST /api/walls with empty lockers - expect 200 within 1000ms."""
        start = time.time()
        response = client.post("/api/walls", headers=auth_headers, json={
            "name": "Test Location", "address": "Test Street", "lockers": []
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_create_wall_missing_fields(self, client, auth_headers):
        """POST /api/walls with missing fields - expect 422 within 1000ms."""
        start = time.time()
        response = client.post("/api/walls", headers=auth_headers, json={"name": "Test Location"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 422
        assert elapsed < 1000
    
    def test_delete_wall_successful(self, client, auth_headers, db_session):
        """DELETE /api/walls/{id} - expect 200 within 1000ms."""
        location = models.Location(name="To Delete", address="Test Street", api_key="test_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Available", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        start = time.time()
        response = client.delete(f"/api/walls/{location.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_delete_wall_with_occupied_locker(self, client, auth_headers, db_session):
        """DELETE /api/walls with occupied locker - expect 400 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Occupied", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        start = time.time()
        response = client.delete(f"/api/walls/{location.id}", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 400
        assert elapsed < 1000
    
    def test_delete_wall_not_found(self, client, auth_headers):
        """DELETE /api/walls/{id} not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.delete("/api/walls/99999", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000


# ==========================================
# LOGS ROUTER TESTS (4 endpoints)
# ==========================================
class TestLogsEndpoints:
    
    def test_create_log_successful(self, client, auth_headers, db_session):
        """POST /api/logs - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/logs", headers=auth_headers, json={
            "location_id": location.id, "event_type": "LEVERING", "severity": "INFO", "description": "Test log entry"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_create_log_missing_fields(self, client, auth_headers):
        """POST /api/logs missing fields - expect 422 within 1000ms."""
        start = time.time()
        response = client.post("/api/logs", headers=auth_headers, json={"event_type": "LEVERING"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 422
        assert elapsed < 1000
    
    def test_get_logs_successful(self, client, auth_headers, db_session):
        """GET /api/logs - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/logs", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert isinstance(response.json(), list)
    
    def test_get_logs_with_filters(self, client, auth_headers, db_session):
        """GET /api/logs with filters - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        log = models.AuditLog(location_id=location.id, event_type="LEVERING", severity="INFO", description="Test log")
        db_session.add(log)
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/logs", headers=auth_headers, params={"type": "INFO"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_get_logs_with_search(self, client, auth_headers, db_session):
        """GET /api/logs with search - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        log = models.AuditLog(location_id=location.id, event_type="LEVERING", severity="INFO", description="Test specific log")
        db_session.add(log)
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/logs", headers=auth_headers, params={"search": "specific"})
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_export_logs_successful(self, client, auth_headers, db_session):
        """GET /api/logs/export - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        log = models.AuditLog(location_id=location.id, event_type="LEVERING", severity="INFO", description="Test log")
        db_session.add(log)
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/logs/export", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert "text/csv" in response.headers["content-type"]
    
    def test_export_logs_empty(self, client, auth_headers, db_session):
        """GET /api/logs/export when empty - expect 200 within 1000ms."""
        import models
        db_session.query(models.AuditLog).delete()
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/logs/export", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000


# ==========================================
# DASHBOARD ROUTER TESTS (1 endpoint)
# ==========================================
class TestDashboardEndpoints:
    
    def test_get_kpis_successful(self, client, auth_headers, db_session):
        """GET /api/dashboard/kpis - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        data = response.json()
        assert "parcels_today" in data
        assert "total_walls" in data
    
    def test_get_kpis_empty_database(self, client, auth_headers, db_session):
        """GET /api/dashboard/kpis with empty database - expect 200 within 1000ms."""
        import models
        db_session.query(models.Parcel).delete()
        db_session.query(models.AuditLog).delete()
        db_session.query(models.Location).delete()
        db_session.commit()
        
        start = time.time()
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000


# ==========================================
# MAINTENANCE ROUTER TESTS (2 endpoints)
# ==========================================
class TestMaintenanceEndpoints:
    
    def test_remote_unlock_successful(self, client, auth_headers, db_session):
        """POST /api/maintenance/remote-unlock - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Available", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/maintenance/remote-unlock", headers=auth_headers, json={
            "location_id": location.id, "locker_id": locker.id, "reason": "Test unlock"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_remote_unlock_locker_not_found(self, client, auth_headers, db_session):
        """POST /api/maintenance/remote-unlock locker not found - expect 404 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/maintenance/remote-unlock", headers=auth_headers, json={
            "location_id": location.id, "locker_id": 99999, "reason": "Test"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000
    
    def test_service_mode_successful(self, client, auth_headers, db_session):
        """POST /api/maintenance/service-mode - expect 200 within 1000ms."""
        location = models.Location(name="Test Location", address="Teststraat 1", api_key="test_api_key", last_heartbeat=None)
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(location_id=location.id, door_number=1, size="M", status="Available", shadow_state={})
        db_session.add(locker)
        db_session.commit()
        
        start = time.time()
        response = client.post("/api/maintenance/service-mode", headers=auth_headers, json={
            "locker_id": locker.id, "status": "Maintenance"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
    
    def test_service_mode_locker_not_found(self, client, auth_headers):
        """POST /api/maintenance/service-mode locker not found - expect 404 within 1000ms."""
        start = time.time()
        response = client.post("/api/maintenance/service-mode", headers=auth_headers, json={
            "locker_id": 99999, "status": "Maintenance"
        })
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 404
        assert elapsed < 1000


# ==========================================
# SYSTEM ENDPOINT TESTS (1 endpoint)
# ==========================================
class TestSystemEndpoints:
    
    def test_get_system_status_successful(self, client):
        """GET /api/system/status - expect 200 within 1000ms."""
        start = time.time()
        response = client.get("/api/system/status")
        elapsed = (time.time() - start) * 1000
        
        assert response.status_code == 200
        assert elapsed < 1000
        assert response.json()["online"] is True
