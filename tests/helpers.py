# Test utilities and helpers
import json
from datetime import datetime, timezone, timedelta

def generate_tracking_code():
    """Generate a fake tracking code."""
    import random
    import string
    return "3S" + "".join(random.choices(string.digits, k=13))

def generate_pincode():
    """Generate a 6-digit PIN code."""
    import random
    return "".join(random.choices(string.digits, k=6))

def create_test_parcel_data(locker_id, user_id, courier="bpost"):
    """Create test parcel data for API requests."""
    return {
        "tracking_code": generate_tracking_code(),
        "locker_id": locker_id,
        "user_id": user_id,
        "courier": courier,
        "status": "Delivered"
    }

def create_test_resident_data(location_id, idx=1):
    """Create test resident data."""
    return {
        "name": f"Test Bewoner {idx}",
        "email": f"test{idx}@smartwall.be",
        "unit_number": f"Bus {idx}",
        "phone": f"+32470{idx*10000+1234}",
        "location_id": location_id
    }

def create_test_locker_data(location_id, door_number=1, size="M"):
    """Create test locker data."""
    return {
        "location_id": location_id,
        "door_number": door_number,
        "size": size,
        "status": "Available",
        "shadow_state": {}
    }

def create_test_wall_data(name, address, lockers_config):
    """Create test wall data."""
    return {
        "name": name,
        "address": address,
        "lockers": lockers_config
    }

# Mock MQTT client for testing
class MockMQTTClient:
    """Mock MQTT client for testing without real broker."""
    
    def __init__(self):
        self.published_messages = []
        self.subscribed_topics = []
    
    def publish(self, topic, payload, qos=0):
        """Mock publish method."""
        self.published_messages.append({
            "topic": topic,
            "payload": payload,
            "qos": qos
        })
        return {"mid": len(self.published_messages), "rc": 0}
    
    def subscribe(self, topic, qos=0):
        """Mock subscribe method."""
        self.subscribed_topics.append({"topic": topic, "qos": qos})
    
    def clear_messages(self):
        """Clear published messages for testing."""
        self.published_messages = []

# Test data generators
def generate_delivery_payload(locker_id, user_id, barcode=None, carrier="bpost"):
    """Generate MQTT delivery payload."""
    return {
        "locker_id": locker_id,
        "user_id": user_id,
        "barcode": barcode or generate_tracking_code(),
        "carrier": carrier,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def generate_pickup_payload(locker_id, method="PIN", duration=None):
    """Generate MQTT pickup payload."""
    payload = {
        "locker_id": locker_id,
        "method": method,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if duration:
        payload["duration_seconds"] = duration
    return payload

def generate_alarm_payload(locker_id, msg="Test alarm", severity="WARNING"):
    """Generate MQTT alarm payload."""
    return {
        "locker_id": locker_id,
        "msg": msg,
        "severity": severity,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def generate_return_payload(locker_id, user_id, barcode=None, carrier="PostNL"):
    """Generate MQTT return payload."""
    return {
        "locker_id": locker_id,
        "user_id": user_id,
        "barcode": barcode or generate_tracking_code(),
        "carrier": carrier,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

def generate_telemetry_payload(locker_ids, location_id):
    """Generate MQTT telemetry payload."""
    lockers_state = {str(lid): "closed" for lid in locker_ids}
    return {
        "lockers_state": lockers_state,
        "location_id": location_id
    }

def generate_sync_payload():
    """Generate MQTT request sync payload."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# Date utilities
def get_today_midnight():
    """Get today's midnight in UTC."""
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

def get_past_datetime(days=0, hours=0, minutes=0):
    """Get a datetime in the past."""
    return datetime.now(timezone.utc) - timedelta(days=days, hours=hours, minutes=minutes)
