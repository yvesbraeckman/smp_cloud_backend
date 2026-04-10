"""
Pytest Configuration
====================
Plugin and option setup for pytest.
"""

import os

# Set test mode BEFORE any imports in conftest module level
os.environ["IN_TEST_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_smartwall.db"
os.environ["SECRET_KEY"] = "super_geheime_sleutel_voor_smartwall"
# Set minimal environment variables to avoid mqtt errors
os.environ["MQTT_BROKER"] = "mock-broker"
os.environ["MQTT_PORT"] = "1883"
os.environ["SENDER_EMAIL"] = "test@smartwall.be"
os.environ["SENDER_PASSWORD"] = "test_password"
os.environ["SMTP_SERVER"] = "smtp.test.com"
os.environ["SMTP_PORT"] = "587"

import pytest
import os

def pytest_addoption(parser):
    """Add custom command-line options."""
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests"
    )
    parser.addoption(
        "--test-db",
        action="store",
        default="sqlite:///./test_smartwall.db",
        help="Database URL for testing"
    )
    parser.addoption(
        "--cov-module",
        action="store",
        default=".",
        help="Module to measure coverage for"
    )

def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
    config.addinivalue_line(
        "markers", "api: mark test as API endpoint test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )
    # Set test mode environment variable
    os.environ["IN_TEST_MODE"] = "true"
    os.environ["DATABASE_URL"] = "sqlite:///./test_smartwall.db"
    parser.addoption(
        "--test-db",
        action="store",
        default="sqlite:///./test_smartwall.db",
        help="Database URL for testing"
    )
    parser.addoption(
        "--cov-module",
        action="store",
        default=".",
        help="Module to measure coverage for"
    )

def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "unit: mark test as unit test"
    )
    config.addinivalue_line(
        "markers", "api: mark test as API endpoint test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as integration test"
    )

def pytest_collection_modifyitems(config, items):
    """Modify collected test items."""
    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="need --run-slow to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)


# ==========================================
# TEST FIXTURES
# ==========================================

import pytest_asyncio
import sys
import os

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlalchemy
import models
from sqlalchemy.pool import StaticPool


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create test database tables before all tests."""
    # Import database module and models separately
    import database
    models.Base.metadata.create_all(bind=database.engine)
    yield
    # Clean up test database file
    models.Base.metadata.drop_all(bind=database.engine)
    import os
    db_file = "test_smartwall.db"
    if os.path.exists(db_file):
        os.remove(db_file)


@pytest_asyncio.fixture(scope="function")
async def db_session():
    """Create a new database session for each test with rollback."""
    import database
    from sqlalchemy.orm import sessionmaker
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=database.engine)
    
    # Create tables for this session if they don't exist
    models.Base.metadata.create_all(bind=database.engine)
    
    session = TestingSessionLocal()
    
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        
        # Clean up all tables for next test
        models.Base.metadata.drop_all(bind=database.engine)
        models.Base.metadata.create_all(bind=database.engine)


# ==========================================
# TEST DATA FIXTURES
# ==========================================


@pytest.fixture
def location_a(db_session):
    """Create test location A."""
    location = models.Location(
        name="Locatie A",
        address="Teststraat 1",
        api_key="test_api_key_abc123",
        last_heartbeat=None
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture
def location_b(db_session):
    """Create test location B."""
    location = models.Location(
        name="Locatie B",
        address="Teststraat 2",
        api_key="test_api_key_def456",
        last_heartbeat=None
    )
    db_session.add(location)
    db_session.commit()
    db_session.refresh(location)
    return location


@pytest.fixture
def locker_available(db_session, location_a):
    """Create an available locker."""
    locker = models.Locker(
        location_id=location_a.id,
        door_number=1,
        size="M",
        status="Available",
        shadow_state={}
    )
    db_session.add(locker)
    db_session.commit()
    db_session.refresh(locker)
    return locker


@pytest.fixture
def locker_occupied(db_session, location_a):
    """Create an occupied locker."""
    locker = models.Locker(
        location_id=location_a.id,
        door_number=2,
        size="L",
        status="Occupied",
        shadow_state={"last_seen": "2026-04-07T10:00:00"}
    )
    db_session.add(locker)
    db_session.commit()
    db_session.refresh(locker)
    return locker


@pytest.fixture
def resident_1(db_session, location_a):
    """Create test resident 1."""
    user = models.User(
        location_id=location_a.id,
        name="Jan Jansen",
        email="jan.jansen@test.be",
        unit_number="Bus 12",
        phone="+32470123456"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def resident_2(db_session, location_a):
    """Create test resident 2."""
    user = models.User(
        location_id=location_a.id,
        name="Marie Jansen",
        email="marie.jansen@test.be",
        unit_number="Bus 15",
        phone="+32470987654"
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def parcel_delivered(db_session, locker_occupied, resident_1):
    """Create a delivered parcel."""
    parcel = models.Parcel(
        locker_id=locker_occupied.id,
        user_id=resident_1.id,
        tracking_code="3SBP123456789",
        courier="bpost",
        pincode="hashed_pin_hash",
        status="Delivered"
    )
    db_session.add(parcel)
    db_session.commit()
    db_session.refresh(parcel)
    return parcel


@pytest.fixture
def audit_log_info(db_session, location_a):
    """Create an INFO audit log."""
    log = models.AuditLog(
        location_id=location_a.id,
        event_type="LEVERING",
        severity="INFO",
        description="Test info log"
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


@pytest.fixture
def audit_log_critical(db_session, location_a):
    """Create a CRITICAL audit log."""
    log = models.AuditLog(
        location_id=location_a.id,
        event_type="ALARM",
        severity="CRITICAL",
        description="Test critical log"
    )
    db_session.add(log)
    db_session.commit()
    db_session.refresh(log)
    return log


@pytest.fixture
def auth_headers(db_session):
    """Generate basic auth headers for testing."""
    import jwt
    import datetime
    import os
    
    # Get first admin user from database to ensure correct ID in token
    admin = db_session.query(models.Admin).first()
    if not admin:
        # Create one if it doesn't exist
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
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


@pytest.fixture
def superadmin_auth_headers(db_session):
    """Generate auth headers for superadmin."""
    import jwt
    import datetime
    import os
    
    # Get first superadmin user from database to ensure correct ID in token
    admin = db_session.query(models.Admin).filter(models.Admin.role == "superadmin").first()
    if not admin:
        # Create one if it doesn't exist
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        admin = models.Admin(
            name="Super Admin",
            email="superadmin@smartwall.be",
            password_hash=pwd_context.hash("TestPassword123!"),
            phone="+32400987654",
            role="superadmin"
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


@pytest.fixture
def admin_user(db_session):
    """Create a test admin user."""
    import os
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
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
    return admin


@pytest.fixture
def superadmin_user(db_session):
    """Create a test superadmin user."""
    import os
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    
    admin = models.Admin(
        name="Super Admin",
        email="superadmin@smartwall.be",
        password_hash=pwd_context.hash("TestPassword123!"),
        phone="+32400987654",
        role="superadmin"
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin
