"""
Tests for Maintenance Router
============================
Test remote hardware control endpoints: unlock and service mode.
"""

import pytest
import sys
import os
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers import maintenance
from fastapi.testclient import TestClient
from fastapi import status

app = FastAPI()
app.include_router(maintenance.router)


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


class TestRemoteUnlock:
    """Test POST /api/maintenance/remote-unlock endpoint."""
    
    def test_remote_unlock_success(self, client, location_a, locker_available):
        """Test successful remote unlock command."""
        unlock_data = {
            "location_id": location_a.id,
            "locker_id": locker_available.id,
            "reason": "Admin override test"
        }
        
        response = client.post("/api/maintenance/remote-unlock", json=unlock_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "verzonden" in data["message"].lower() or "MQTT" in data["message"]
    
    def test_remote_unlock_locker_not_found(self, client, location_a):
        """Test remote unlock with non-existent locker."""
        unlock_data = {
            "location_id": location_a.id,
            "locker_id": 99999,
            "reason": "Test"
        }
        
        response = client.post("/api/maintenance/remote-unlock", json=unlock_data)
        
        assert response.status_code == 404
    
    def test_remote_unlock_location_not_found(self, client):
        """Test remote unlock with non-existent location."""
        unlock_data = {
            "location_id": 99999,
            "locker_id": 1,
            "reason": "Test"
        }
        
        response = client.post("/api/maintenance/remote-unlock", json=unlock_data)
        
        assert response.status_code == 404


class TestSetServiceMode:
    """Test POST /api/maintenance/service-mode endpoint."""
    
    def test_set_service_mode_to_maintenance(self, client, locker_available):
        """Test setting locker to maintenance mode."""
        service_data = {
            "locker_id": locker_available.id,
            "status": "Maintenance"
        }
        
        response = client.post("/api/maintenance/service-mode", json=service_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "status" in data["message"].lower() or "geüpdatet" in data["message"].lower()
    
    def test_set_service_mode_to_available(self, client, locker_available, db_session):
        """Test setting locker back to available mode."""
        import models
        # First set to maintenance
        locker_available.status = "Maintenance"
        db_session.commit()
        
        service_data = {
            "locker_id": locker_available.id,
            "status": "Available"
        }
        
        response = client.post("/api/maintenance/service-mode", json=service_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        
        # Verify status updated
        db_session.refresh(locker_available)
        assert locker_available.status == "Available"
    
    def test_set_service_mode_locker_not_found(self, client):
        """Test service mode with non-existent locker."""
        service_data = {
            "locker_id": 99999,
            "status": "Maintenance"
        }
        
        response = client.post("/api/maintenance/service-mode", json=service_data)
        
        assert response.status_code == 404
