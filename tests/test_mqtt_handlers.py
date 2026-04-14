"""
Tests for MQTT Handlers
=======================
Test all MQTT event handlers: delivery, pickup, alarm, return, collect, telemetry, and sync.
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch
from datetime import datetime, timezone
import json

from mqtt.handlers import (
    handle_delivery, handle_pickup, handle_alarm, handle_return,
    handle_collect, handle_telemetry, handle_request_sync, send_delivery_email, send_return_email,
    parse_mqtt_timestamp
)
import models


class TestMQTTTimestampParsing:
    """Test timestamp parsing functionality."""
    
    def test_parse_valid_timestamp(self):
        """Test parsing a valid ISO timestamp."""
        ts_string = "2026-04-07T10:30:00Z"
        result = parse_mqtt_timestamp(ts_string)
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 7
        assert result.hour == 10
    
    def test_parse_valid_timestamp_with_timezone(self):
        """Test parsing timestamp with timezone offset."""
        ts_string = "2026-04-07T10:30:00+02:00"
        result = parse_mqtt_timestamp(ts_string)
        assert result.year == 2026
        assert result.month == 4
        assert result.day == 7
    
    def test_parse_none_timestamp(self):
        """Test parsing None timestamp returns current time."""
        result = parse_mqtt_timestamp(None)
        assert result is not None
        # Should be close to current time
        now = datetime.utcnow()
        diff = abs((now - result).total_seconds())
        assert diff < 1  # Within 1 second
    
    def test_parse_invalid_timestamp(self):
        """Test parsing invalid timestamp returns current time."""
        result = parse_mqtt_timestamp("not-a-date")
        assert result is not None
        now = datetime.utcnow()
        diff = abs((now - result).total_seconds())
        assert diff < 1


class TestMQTTEmailSenders:
    """Test email sending functions."""
    
    @pytest.fixture
    def env_with_email_config(self, monkeypatch):
        """Set up environment variables for email testing."""
        monkeypatch.setenv("SENDER_EMAIL", "test@example.com")
        monkeypatch.setenv("SENDER_PASSWORD", "test_password")
        monkeypatch.setenv("SMTP_SERVER", "smtp.test.com")
        monkeypatch.setenv("SMTP_PORT", "587")
    
    def test_send_return_email_no_config(self, monkeypatch):
        """Test send_return_email when config is missing."""
        monkeypatch.delenv("SENDER_EMAIL", raising=False)
        result = send_return_email("recipient@example.com", "John Doe", "BAR123", "bpost")
        # Should return without error when config is missing
        assert result is None
    
    def test_send_delivery_email_no_config(self, monkeypatch):
        """Test send_delivery_email when config is missing."""
        monkeypatch.delenv("SENDER_EMAIL", raising=False)
        result = send_delivery_email("recipient@example.com", "John Doe", "123456", "BAR123", "bpost")
        # Should return without error when config is missing
        assert result is None


class TestMQTTDeliveryHandler:
    """Test the handle_delivery handler."""
    
    @pytest_asyncio.fixture
    async def setup_database(self, db_session):
        """Set up database with location and locker."""
        import models
        
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create locker
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Available"
        )
        db_session.add(locker)
        db_session.commit()
        
        # Create user
        user = models.User(
            location_id=location.id,
            name="Test User",
            email="test@example.com",
            unit_number="Bus 1"
        )
        db_session.add(user)
        db_session.commit()
        
        return {
            "location": location,
            "locker": locker,
            "user": user
        }
    
    def test_handle_delivery_success(self, db_session, setup_database):
        """Test successful delivery handling."""
        location = setup_database["location"]
        locker = setup_database["locker"]
        user = setup_database["user"]
        
        # Commit to make data available in SQLite in-memory database
        db_session.commit()
        
        # Mock MQTT client
        mock_client = Mock()
        mock_client.publish = Mock(return_value={"mid": 1, "rc": 0})
        
        # Create delivery payload
        payload = {
            "locker_id": locker.id,
            "user_id": user.id,
            "barcode": "3SBP123456789",
            "carrier": "bpost",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Call handler
        handle_delivery(mock_client, str(location.id), payload)
        
        # Refresh to get latest data from the handler's session
        db_session.expire_all()
        
        # Verify parcel was created
        parcel = db_session.query(models.Parcel).filter_by(
            tracking_code="3SBP123456789"
        ).first()
        assert parcel is not None
        assert parcel.status == "Delivered"
        assert parcel.locker_id == locker.id
        assert parcel.user_id == user.id
        
        # Verify locker status updated
        locker = db_session.query(models.Locker).filter_by(id=locker.id).first()
        assert locker.status == "Occupied"
        
        # Verify audit log was created
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="LEVERING"
        ).first()
        assert audit_log is not None
    
    def test_handle_delivery_locker_not_found(self, db_session, setup_database):
        """Test delivery handling when locker doesn't exist."""
        location = setup_database["location"]
        
        # Mock MQTT client
        mock_client = Mock()
        mock_client.publish = Mock(return_value={"mid": 1, "rc": 0})
        
        # Create payload with non-existent locker
        payload = {
            "locker_id": 99999,  # Non-existent
            "user_id": 1,
            "barcode": "3SBP123456789",
            "carrier": "bpost"
        }
        
        # Should return early without creating parcel
        with patch('mqtt.handlers.print') as mock_print:
            handle_delivery(mock_client, str(location.id), payload)
            mock_print.assert_any_call(
                "[MQTT ERROR] Locker 99999 does not exist in cloud database."
            )
        
        # Verify no parcel was created
        parcel = db_session.query(models.Parcel).filter_by(tracking_code="3SBP123456789").first()
        assert parcel is None
    
    def test_handle_delivery_user_not_found(self, db_session, setup_database):
        """Test delivery handling when user doesn't exist but locker does."""
        location = setup_database["location"]
        locker = setup_database["locker"]
        
        # Mock MQTT client
        mock_client = Mock()
        mock_client.publish = Mock(return_value={"mid": 1, "rc": 0})
        
        # Create payload with non-existent user
        payload = {
            "locker_id": locker.id,
            "user_id": 99999,  # Non-existent
            "barcode": "3SBP123456789",
            "carrier": "bpost"
        }
        
        handle_delivery(mock_client, str(location.id), payload)
        
        # Verify parcel was created
        parcel = db_session.query(models.Parcel).filter_by(tracking_code="3SBP123456789").first()
        assert parcel is not None
        
        # Should log warning about missing user
        with patch('mqtt.handlers.print') as mock_print:
            handle_delivery(mock_client, str(location.id), payload)
            # The function should handle the missing user gracefully


class TestMQTTPickupHandler:
    """Test the handle_pickup handler."""
    
    @pytest_asyncio.fixture
    async def setup_delivery(self, db_session):
        """Set up a delivery scenario."""
        import models
        
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create locker
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Occupied"
        )
        db_session.add(locker)
        db_session.commit()
        
        # Create user
        user = models.User(
            location_id=location.id,
            name="John Doe",
            email="john@example.com",
            unit_number="Bus 1"
        )
        db_session.add(user)
        db_session.commit()
        
        # Create parcel
        parcel = models.Parcel(
            locker_id=locker.id,
            user_id=user.id,
            tracking_code="3SBP123456789",
            courier="bpost",
            pincode="hashed_pin",
            status="Delivered"
        )
        db_session.add(parcel)
        db_session.commit()
        
        return {
            "location": location,
            "locker": locker,
            "user": user,
            "parcel": parcel
        }
    
    def test_handle_pickup_success(self, db_session, setup_delivery):
        """Test successful pickup handling."""
        location = setup_delivery["location"]
        locker = setup_delivery["locker"]
        user = setup_delivery["user"]
        parcel = setup_delivery["parcel"]
        
        # Mock MQTT client
        mock_client = Mock()
        
        # Create pickup payload
        payload = {
            "locker_id": locker.id,
            "method": "PIN",
            "duration_seconds": 30,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Call handler
        handle_pickup(mock_client, str(location.id), payload)
        
        # Verify parcel status updated
        db_session.refresh(parcel)
        assert parcel.status == "PickedUp"
        assert parcel.picked_up_at is not None
        
        # Verify locker status updated
        db_session.refresh(locker)
        assert locker.status == "Available"
        
        # Verify audit log was created with user name
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="OPHALING"
        ).first()
        assert audit_log is not None
        assert "John Doe" in audit_log.description
        assert "PIN" in audit_log.description
        assert "30" in audit_log.description


class TestMQTTAlarmHandler:
    """Test the handle_alarm handler."""
    
    def test_handle_alarm_creates_audit_log(self, db_session):
        """Test alarm handling creates audit log."""
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create locker
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Available"
        )
        db_session.add(locker)
        db_session.commit()
        
        # Mock MQTT client
        mock_client = Mock()
        
        # Create alarm payload
        payload = {
            "locker_id": locker.id,
            "msg": "Door open too long",
            "severity": "WARNING",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Call handler
        handle_alarm(mock_client, str(location.id), payload)
        
        # Verify audit log was created
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="ALARM"
        ).first()
        assert audit_log is not None
        assert audit_log.description == "Door open too long"
        assert audit_log.severity == "WARNING"
    
    def test_handle_alarm_critical_severity(self, db_session):
        """Test alarm with CRITICAL severity."""
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Available"
        )
        db_session.add(locker)
        db_session.commit()
        
        mock_client = Mock()
        
        payload = {
            "locker_id": locker.id,
            "msg": "Security breach detected",
            "severity": "CRITICAL",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        handle_alarm(mock_client, str(location.id), payload)
        
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="ALARM",
            severity="CRITICAL"
        ).first()
        assert audit_log is not None


class TestMQTTReturnHandler:
    """Test the handle_return handler."""
    
    def test_handle_return_success(self, db_session):
        """Test successful return handling."""
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create locker
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Available"
        )
        db_session.add(locker)
        db_session.commit()
        
        # Create user
        user = models.User(
            location_id=location.id,
            name="John Doe",
            email="john@example.com",
            unit_number="Bus 1"
        )
        db_session.add(user)
        db_session.commit()
        
        mock_client = Mock()
        
        payload = {
            "locker_id": locker.id,
            "user_id": user.id,
            "barcode": "3SRET987654321",
            "carrier": "PostNL",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        handle_return(mock_client, str(location.id), payload)
        
        # Verify parcel was created with return status
        parcel = db_session.query(models.Parcel).filter_by(
            tracking_code="3SRET987654321"
        ).first()
        assert parcel is not None
        assert parcel.status == "AwaitingCourier"
        assert parcel.user_id == user.id
        
        # Verify locker status (for returns, status is "Return" not "Occupied")
        db_session.refresh(locker)
        assert locker.status == "Return"
        
        # Verify audit log was created
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="RETOUR_AANGEMELD"
        ).first()
        assert audit_log is not None


class TestMQTTCollectHandler:
    """Test the handle_collect handler."""
    
    def test_handle_collect_success(self, db_session):
        """Test successful collect handling."""
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create locker
        locker = models.Locker(
            location_id=location.id,
            door_number=1,
            size="M",
            status="Occupied"
        )
        db_session.add(locker)
        db_session.commit()
        
        # Create return parcel
        parcel = models.Parcel(
            locker_id=locker.id,
            user_id=1,
            tracking_code="3SRET987654321",
            courier="PostNL",
            status="AwaitingCourier"
        )
        db_session.add(parcel)
        db_session.commit()
        
        mock_client = Mock()
        
        payload = {
            "locker_id": locker.id,
            "carrier": "PostNL",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        handle_collect(mock_client, str(location.id), payload)
        
        # Verify parcel status updated
        db_session.refresh(parcel)
        assert parcel.status == "PickedUp"
        
        # Verify locker is available
        db_session.refresh(locker)
        assert locker.status == "Available"
        
        # Verify audit log was created
        audit_log = db_session.query(models.AuditLog).filter_by(
            event_type="RETOUR_OPGEHAALD"
        ).first()
        assert audit_log is not None


class TestMQTTTelemetryHandler:
    """Test the handle_telemetry handler."""
    
    def test_handle_telemetry_success(self, db_session):
        """Test successful telemetry handling."""
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create lockers
        lockers = []
        for i in range(3):
            locker = models.Locker(
                location_id=location.id,
                door_number=i+1,
                size="M",
                status="Available"
            )
            db_session.add(locker)
            lockers.append(locker)
        db_session.commit()
        
        mock_client = Mock()
        
        # Create telemetry payload
        lockers_state = {
            str(lockers[0].id): "closed",
            str(lockers[1].id): "open",
            str(lockers[2].id): "closed"
        }
        
        payload = {
            "lockers_state": lockers_state
        }
        
        handle_telemetry(mock_client, str(location.id), payload)
        
        # Verify location heartbeat updated
        db_session.refresh(location)
        assert location.last_heartbeat is not None
        
        # Verify locker shadow state updated
        for locker in lockers:
            db_session.refresh(locker)
            assert locker.shadow_state is not None
            assert "last_seen" in locker.shadow_state
            assert "door" in locker.shadow_state


class TestMQTTRequestSyncHandler:
    """Test the handle_request_sync handler."""
    
    def test_handle_request_sync_success(self, db_session):
        """Test successful request sync handling."""
        # Create location
        location = models.Location(
            name="Test Location",
            address="Test Street 1",
            api_key="test_api_key"
        )
        db_session.add(location)
        db_session.commit()
        
        # Create lockers
        lockers = []
        for i in range(3):
            locker = models.Locker(
                location_id=location.id,
                door_number=i+1,
                size="M",
                status="Available"
            )
            db_session.add(locker)
            lockers.append(locker)
        db_session.commit()
        
        # Create user
        user = models.User(
            location_id=location.id,
            name="John Doe",
            email="john@example.com",
            unit_number="Bus 1"
        )
        db_session.add(user)
        db_session.commit()
        
        mock_client = Mock()
        mock_client.publish = Mock(return_value={"mid": 1, "rc": 0})
        
        payload = {}
        
        handle_request_sync(mock_client, str(location.id), payload)
        
        # Verify sync command was published
        assert len(mock_client.publish.call_args_list) >= 1
        publish_call = mock_client.publish.call_args_list[0]
        topic = publish_call[0][0]
        assert "cmd/sync_users" in topic
        
        # Parse payload and verify structure
        sync_payload = json.loads(publish_call[0][1])
        assert "lockers" in sync_payload
        assert "users" in sync_payload
        assert len(sync_payload["users"]) == 1
        assert len(sync_payload["lockers"]) == 3
