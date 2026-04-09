"""
Tests for Logs Router
=====================
Test audit log endpoints: creation, filtering, and export.
"""

import pytest
import sys
import os
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routers import logs
from fastapi.testclient import TestClient

app = FastAPI()
app.include_router(logs.router)


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


class TestCreateLog:
    """Test POST /api/logs endpoint."""
    
    def test_create_log_success_info(self, client, location_a):
        """Test creating INFO log."""
        log_data = {
            "location_id": location_a.id,
            "event_type": "LEVERING",
            "severity": "INFO",
            "description": "Test log entry INFO"
        }
        
        response = client.post("/api/logs", json=log_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "LEVERING"
        assert data["severity"] == "INFO"
        # Note: Response includes location_name, not location_id
        assert "location_name" in data or data.get("location_name") is not None
    
    def test_create_log_success_warning(self, client, location_a):
        """Test creating WARNING log."""
        log_data = {
            "location_id": location_a.id,
            "event_type": "ALARM",
            "severity": "WARNING",
            "description": "Test log entry WARNING"
        }
        
        response = client.post("/api/logs", json=log_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["severity"] == "WARNING"
    
    def test_create_log_success_critical(self, client, location_a):
        """Test creating CRITICAL log."""
        log_data = {
            "location_id": location_a.id,
            "event_type": "ALARM",
            "severity": "CRITICAL",
            "description": "Test log entry CRITICAL"
        }
        
        response = client.post("/api/logs", json=log_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["severity"] == "CRITICAL"
    
    def test_create_log_missing_fields(self, client):
        """Test creating log with missing required fields."""
        log_data = {
            "event_type": "LEVERING"
            # Missing severity, description
        }
        
        response = client.post("/api/logs", json=log_data)
        
        assert response.status_code == 422


class TestGetLogs:
    """Test GET /api/logs endpoint."""
    
    def test_get_logs_empty(self, client):
        """Test retrieving logs when none exist."""
        response = client.get("/api/logs")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0
    
    def test_get_logs_success(self, client, audit_log_info, audit_log_critical):
        """Test successful log retrieval."""
        response = client.get("/api/logs")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2
    
    @pytest.mark.skip(reason="Ticket-SW-101: Date filtering with SQLite requires proper date casting")
    def test_get_logs_with_date_filter(self, client, audit_log_info):
        """Test filtering logs by date."""
        # Use today's date in ISO format
        today = audit_log_info.timestamp.date()
        response = client.get("/api/logs", params={"date": today.isoformat()})
        
        assert response.status_code == 200
        data = response.json()
        # At least one log should be returned (audit_log_info should have today's date)
        assert len(data) >= 1
    
    def test_get_logs_with_location_filter(self, client, audit_log_info):
        """Test filtering logs by location."""
        response = client.get("/api/logs", params={"location_id": audit_log_info.location_id})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
    
    def test_get_logs_with_severity_filter(self, client, audit_log_info, audit_log_critical):
        """Test filtering logs by severity."""
        response = client.get("/api/logs", params={"type": "CRITICAL"})
        
        assert response.status_code == 200
        data = response.json()
        # Should only return critical logs
        for log in data:
            assert log["severity"] == "CRITICAL"
    
    def test_get_logs_with_search(self, client, audit_log_info):
        """Test searching logs by description."""
        # The fixture description is "Test info log", so search for that or a partial match
        response = client.get("/api/logs", params={"search": "Test info log"})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
    
    def test_get_logs_with_limit(self, client, db_session):
        """Test limiting number of logs returned."""
        import models
        # Create more logs
        for i in range(10):
            log = models.AuditLog(
                location_id=1,
                event_type="LEVERING",
                severity="INFO",
                description=f"Log {i}"
            )
            db_session.add(log)
        db_session.commit()
        
        response = client.get("/api/logs", params={"limit": 5})
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 5


class TestExportLogs:
    """Test GET /api/logs/export endpoint."""
    
    def test_export_logs_csv(self, client, audit_log_info):
        """Test exporting logs to CSV."""
        response = client.get("/api/logs/export")
        
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/csv; charset=utf-8"
        assert "attachment" in response.headers["content-disposition"]
        assert "log" in response.headers["content-disposition"]
        
        # Check CSV content
        content = response.text
        lines = content.strip().split("\n")
        assert len(lines) >= 2  # Header + at least one log
        assert "ID" in lines[0]
        assert "Tijdstip" in lines[0]
        assert "Locatie" in lines[0]
    
    def test_export_logs_with_filters(self, client, audit_log_info):
        """Test exporting logs with filters applied."""
        response = client.get("/api/logs/export", params={"type": "INFO"})
        
        assert response.status_code == 200
        content = response.text
        lines = content.strip().split("\n")
        assert len(lines) >= 2
    
    def test_export_logs_empty(self, client, db_session):
        """Test exporting when no logs exist."""
        # Delete all logs first using db_session
        import models
        db_session.query(models.AuditLog).delete()
        db_session.commit()
        
        response = client.get("/api/logs/export")
        
        assert response.status_code == 200
        content = response.text
        lines = content.strip().split("\n")
        assert len(lines) == 1  # Just header
