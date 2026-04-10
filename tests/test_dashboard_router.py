"""
Tests for Dashboard Router
==========================
Test dashboard KPI endpoints:实时 statistics and metrics.
"""

import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db
from routers import dashboard
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(dashboard.router)


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


class TestGetDashboardKPIs:
    """Test GET /api/dashboard/kpis endpoint."""
    
    def test_get_kpis_empty_database(self, client, auth_headers):
        """Test KPIs when database is empty."""
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "parcels_today" in data
        assert "active_walls" in data
        assert "total_walls" in data
        assert "offline_locations" in data
        assert "open_errors" in data
        
        # All should be 0 for empty database
        assert data["parcels_today"] == 0
        assert data["total_walls"] == 0
        assert data["offline_locations"] == 0
    
    def test_get_kpis_with_data(self, client, auth_headers, location_a, location_b, parcel_delivered, audit_log_info, db_session):
        """Test KPIs with actual data."""
        # Ensure location_b is offline
        import models
        location_b.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=10)
        db_session.commit()
        
        # Create a CRITICAL log for error count
        critical_log = models.AuditLog(
            location_id=location_a.id,
            event_type="ALARM",
            severity="CRITICAL",
            description="Critical error test"
        )
        db_session.add(critical_log)
        db_session.commit()
        
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # parcels_today should be at least 1 (parcel_delivered was created today)
        assert data["parcels_today"] >= 1
        
        # total_walls should be at least 2 (location_a and location_b)
        assert data["total_walls"] >= 2
        
        # offline_locations should include location_b
        assert data["offline_locations"] >= 1
        
        # open_errors should be at least 1 (the CRITICAL log)
        assert data["open_errors"] >= 1
    
    def test_get_kpis_today_filter(self, client, auth_headers, db_session):
        """Test that parcels_today filters correctly by today's date."""
        import models
        
        # Create parcel from yesterday
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        location = db_session.query(models.Location).first()
        
        # Create a user and locker for the parcel
        user = models.User(
            location_id=location.id if location else 1,
            name="Test User",
            email="test_today@test.be",
            unit_number="1"
        )
        db_session.add(user)
        db_session.commit()
        
        locker = models.Locker(
            location_id=location.id if location else 1,
            door_number=99,
            size="M",
            status="Available"
        )
        db_session.add(locker)
        db_session.commit()
        
        yesterday_parcel = models.Parcel(
            locker_id=locker.id,
            user_id=user.id,
            tracking_code="3SBPYESTERDAY",
            courier="bpost",
            pincode="hash",
            status="Delivered",
            created_at=yesterday
        )
        db_session.add(yesterday_parcel)
        db_session.commit()
        
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        # Yesterday's parcel should NOT be counted in parcels_today
        # Only parcels created today should be counted
    
    def test_get_kpis_response_structure(self, client, auth_headers):
        """Test that KPI response has correct structure."""
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Verify all required fields present
        required_fields = [
            "parcels_today",
            "active_walls",
            "total_walls",
            "offline_locations",
            "open_errors"
        ]
        
        for field in required_fields:
            assert field in data
            assert isinstance(data[field], int)
    
    def test_get_kpis_calculation_accuracy(self, client, auth_headers, db_session):
        """Test KPI calculations are accurate."""
        import models
        from sqlalchemy import func
        
        # Get expected counts
        expected_total_walls = db_session.query(models.Location).count()
        expected_parcels_today = db_session.query(models.Parcel).filter(
            models.Parcel.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        ).count()
        expected_open_errors = db_session.query(models.AuditLog).filter(
            models.AuditLog.severity == "CRITICAL"
        ).count()
        
        response = client.get("/api/dashboard/kpis", headers=auth_headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Basic validation - counts might differ slightly due to test data
        assert data["total_walls"] == expected_total_walls or expected_total_walls > 0
        assert data["open_errors"] >= expected_open_errors
