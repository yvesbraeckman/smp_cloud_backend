"""
Tests for Walls Router
======================
Test walls and lockers endpoints: CRUD operations and hardware status.
"""

import pytest
import sys
import os
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers import walls
from fastapi.testclient import TestClient
from fastapi import status

app = FastAPI()
app.include_router(walls.router)


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


class TestGetWalls:
    """Test GET /api/walls endpoint."""
    
    def test_get_walls_empty(self, client):
        """Test retrieving walls when none exist."""
        response = client.get("/api/walls")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_get_walls_success(self, client, location_a, location_b, db_session):
        """Test successful wall listing."""
        response = client.get("/api/walls")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2
        assert data[0]["id"] == location_a.id
        assert "name" in data[0]
        assert "status" in data[0]
        assert "occupancy" in data[0]
    
    def test_get_walls_with_search(self, client, location_a, db_session):
        """Test filtering walls by search term."""
        response = client.get("/api/walls", params={"search": "Locatie"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
    
    def test_get_walls_status_filter(self, client, location_a, location_b, db_session):
        """Test filtering walls by online/offline status."""
        # Make location_b offline
        import models
        from datetime import datetime, timezone, timedelta
        
        location_b.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        db_session.commit()
        
        response = client.get("/api/walls", params={"status": "OFFLINE"})
        
        assert response.status_code == 200
        data = response.json()
        # Should return location_b (offline)
        assert len(data) >= 1


class TestGetWallDetail:
    """Test GET /api/walls/{wall_id} endpoint."""
    
    def test_get_wall_detail_success(self, client, location_a, locker_available, db_session):
        """Test successful wall detail retrieval."""
        response = client.get(f"/api/walls/{location_a.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["location_id"] == location_a.id
        assert "name" in data
        assert "lockers" in data
        assert isinstance(data["lockers"], list)
    
    def test_get_wall_detail_not_found(self, client):
        """Test getting wall detail for non-existent wall."""
        response = client.get("/api/walls/99999")
        
        assert response.status_code == 404
        assert "niet gevonden" in response.json()["detail"].lower() or "muur" in response.json()["detail"].lower()


class TestGetLockerDetail:
    """Test GET /api/lockers/{locker_id} endpoint."""
    
    def test_get_locker_detail_available(self, client, locker_available):
        """Test getting detail for available locker."""
        response = client.get(f"/api/lockers/{locker_available.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == locker_available.id
        assert data["status"] == "Available"
        assert "resident_name" in data
        assert data["parcel_id"] is None
    
    def test_get_locker_detail_occupied(self, client, locker_occupied, parcel_delivered):
        """Test getting detail for occupied locker."""
        response = client.get(f"/api/lockers/{locker_occupied.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "Occupied"
        assert data["parcel_id"] == parcel_delivered.id
        assert data["courier"] is not None
        assert "resident_name" in data
    
    def test_get_locker_detail_not_found(self, client):
        """Test getting detail for non-existent locker."""
        response = client.get("/api/lockers/99999")
        
        assert response.status_code == 404


class TestCreateWall:
    """Test POST /api/walls endpoint."""
    
    def test_create_wall_success(self, client, db_session):
        """Test successful wall creation."""
        wall_data = {
            "name": "New Test Location",
            "address": "Test Street 99",
            "lockers": [
                {"door_number": 1, "size": "S"},
                {"door_number": 2, "size": "M"},
                {"door_number": 3, "size": "L"}
            ]
        }
        
        response = client.post("/api/walls", json=wall_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "New Test Location"
        assert data["status"] == "OFFLINE"
        assert len(data["lockers"]) == 3
    
    def test_create_wall_empty_lockers(self, client):
        """Test creating wall with empty lockers array."""
        wall_data = {
            "name": "Test Location",
            "address": "Test Street",
            "lockers": []
        }
        
        response = client.post("/api/walls", json=wall_data)
        
        assert response.status_code == 200
        data = response.json()
        assert len(data["lockers"]) == 0
    
    def test_create_wall_missing_fields(self, client):
        """Test creating wall with missing required fields."""
        wall_data = {
            "name": "Test Location"
            # Missing address and lockers
        }
        
        response = client.post("/api/walls", json=wall_data)
        
        assert response.status_code == 422


class TestDeleteWall:
    """Test DELETE /api/walls/{wall_id} endpoint."""
    
    def test_delete_wall_success(self, client, db_session):
        """Test successful wall deletion."""
        # Create a new location
        import models
        loc = models.Location(
            name="To Delete",
            address="Test Street",
            api_key="test_key"
        )
        db_session.add(loc)
        db_session.commit()
        
        # Create empty lockers
        for i in range(2):
            locker = models.Locker(
                location_id=loc.id,
                door_number=i+1,
                size="M",
                status="Available"
            )
            db_session.add(locker)
        db_session.commit()
        
        response = client.delete(f"/api/walls/{loc.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "succesvol" in data["message"].lower() or "verwijderd" in data["message"].lower()
        
        # Verify wall was deleted
        deleted = db_session.query(models.Location).filter_by(id=loc.id).first()
        assert deleted is None
    
    def test_delete_wall_with_occupied_lockers(self, client, location_a, locker_occupied, db_session):
        """Test attempting to delete wall with occupied lockers."""
        response = client.delete(f"/api/walls/{location_a.id}")
        
        assert response.status_code == 400
        assert "bevat nog een" in response.json()["detail"].lower() or "bezette" in response.json()["detail"].lower()
    
    def test_delete_wall_not_found(self, client):
        """Test deleting non-existent wall."""
        response = client.delete("/api/walls/99999")
        
        assert response.status_code == 404
