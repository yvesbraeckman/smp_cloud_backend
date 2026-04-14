# Smart Parcel Wall — Backend

IoT-based parcel locker management system for residential buildings. Physical locker walls equipped with Raspberry Pi edge nodes are installed at residential locations. Couriers deliver packages into lockers; residents pick them up using PIN or QR codes received via email. This backend bridges an Angular admin dashboard with the hardware through MQTT messaging.

## Core Flows

1. **Delivery** — Courier scans barcode at wall → RPi publishes MQTT `events/delivery` → backend creates parcel with hashed PIN, marks locker occupied, emails resident PIN+QR, pushes whitelist to RPi.
2. **Pickup** — Resident enters PIN or scans QR at wall → RPi publishes MQTT `events/pickup` → backend marks parcel picked up, frees locker, writes audit log.
3. **Return** — Resident places return parcel in locker → RPi publishes MQTT `events/return` → backend creates parcel with status AwaitingCourier, emails resident confirmation.
4. **Collect** — Courier collects return → RPi publishes MQTT `events/collect` → backend marks parcel picked up, frees locker.
5. **Alarm** — Hardware detects issue → RPi publishes MQTT `events/alarm` → backend writes CRITICAL audit log.
6. **Telemetry** — RPi sends periodic heartbeat → backend updates wall's last heartbeat and locker shadow state (digital twin).
7. **Sync** — On RPi startup or after outage, it requests full sync → backend pushes all users, lockers, and valid codes to the RPi.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.11 |
| Framework | FastAPI + Uvicorn (ASGI) |
| Database | PostgreSQL (SQLAlchemy ORM), SQLite for testing |
| IoT Protocol | MQTT v5 (paho-mqtt) with TLS |
| Authentication | JWT (HS256, 24h expiry) + bcrypt |
| Email | SMTP with STARTTLS (qrcode + Pillow for QR codes) |
| Testing | pytest, httpx, pytest-cov, freezegun |
| Dev Tools | black, flake8, mypy, pylint |
| Containerization | Docker (python:3.11-slim) |

## Prerequisites

- **Python 3.11**
- **PostgreSQL** database server
- **Mosquitto MQTT Broker** (TLS on port 8883)
- **SMTP server** (e.g., Resend) for email delivery
- **Docker** (optional, for containerised deployment)

## Getting Started

### 1. Configure environment

Copy the example environment file and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://user:pass@localhost:5432/smartwall_db` |
| `SECRET_KEY` | JWT signing key | `your-secret-key` |
| `FRONTEND_URL` | Angular dashboard origin | `http://localhost:4200` |
| `SMTP_SERVER` | SMTP hostname | `smtp.resend.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SENDER_EMAIL` | Sender email address | `noreply@example.com` |
| `SENDER_PASSWORD` | SMTP auth password | `re_xxx` |
| `MQTT_BROKER` | MQTT broker hostname | `localhost` |
| `MQTT_PORT` | MQTT broker port (TLS) | `8883` |
| `MQTT_USER` | MQTT username | `rpi_client` |
| `MQTT_PASS` | MQTT password | `secret` |

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Run the server

**Locally:**

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

**With Docker:**

```bash
docker build -t smartwall-backend .
docker run -p 8000:8000 --env-file .env smartwall-backend
```

The API is available at `http://localhost:8000`. Interactive docs at `/docs` (Swagger) and `/redoc`.

## API Overview

All endpoints require JWT Bearer authentication except login and health check.

| Group | Prefix | Endpoints |
|-------|--------|-----------|
| Health | `/api/system` | `GET /status` |
| Auth | `/api/auth` | login, logout, forgot-password, reset-password |
| Profile | `/api/user` | get current user |
| Admins | `/api/admins` | CRUD, profile update, role-based delete |
| Dashboard | `/api/dashboard` | KPIs (parcels today, wall status, errors) |
| Walls | `/api/walls` | list, detail, create, delete; locker detail |
| Residents | `/api/residents` | CRUD, search/pagination, PIN generation |
| Maintenance | `/api/maintenance` | remote unlock, service mode |
| Logs | `/api/logs` | create, list/filter, CSV export |

## MQTT Topics

**Subscribed** (RPi → Cloud):

| Topic | Event |
|-------|-------|
| `lockers/{id}/events/delivery` | Parcel delivered |
| `lockers/{id}/events/pickup` | Parcel picked up |
| `lockers/{id}/events/return` | Return placed |
| `lockers/{id}/events/collect` | Courier collected return |
| `lockers/{id}/events/alarm` | Hardware alarm |
| `lockers/{id}/events/request_sync` | Full sync request |
| `lockers/{id}/events/flush_complete` | Offline buffer replay done |
| `lockers/{id}/telemetry` | Periodic heartbeat |

**Published** (Cloud → RPi):

| Topic | Command |
|-------|---------|
| `lockers/{id}/cmd/open` | Remote unlock |
| `lockers/{id}/cmd/status` | Status change |
| `lockers/{id}/cmd/sync_users` | User list sync |
| `lockers/{id}/cmd/sync_whitelist` | Valid codes whitelist |
| `lockers/{id}/cmd/delete_user` | User deletion |
| `lockers/{id}/cmd/sync_ready` | ACK after flush |

## Project Structure

```
backend/
├── main.py                # FastAPI app, router registration, MQTT lifecycle
├── database.py             # SQLAlchemy engine, session factory
├── models.py               # 6 ORM models (Location, Locker, User, Parcel, AuditLog, Admin)
├── schemas.py              # Pydantic request/response schemas
├── routers/                # API endpoint handlers
│   ├── auth.py             # Login, JWT, password reset
│   ├── admins.py           # Admin CRUD, role-based access
│   ├── dashboard.py        # KPIs
│   ├── walls.py            # Walls & lockers
│   ├── maintenance.py      # Remote unlock, service mode
│   ├── residents.py        # Resident management, PIN generation
│   └── logs.py             # Audit log CRUD, CSV export
├── mqtt/                   # MQTT communication layer
│   ├── client.py           # Paho-MQTT client, TLS, lifecycle
│   └── handlers.py         # 8 event handlers + email helpers
├── tests/                  # Test suite (171 tests, 91% coverage)
├── Dockerfile              # Python 3.11-slim container
├── requirements.txt        # Python dependencies
└── TESTING.md              # Full testing documentation
```

## Testing

The test suite contains **171 tests** with **91% code coverage**. See [TESTING.md](TESTING.md) for full details.

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=80

# Run via Docker
docker-compose run --rm backend-api pytest tests/ -v
```