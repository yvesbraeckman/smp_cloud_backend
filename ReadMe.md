# Smart Parcel Wall - Cloud Backend 

Welkom bij de Cloud Backend van het **Smart Parcel Wall** project. Dit systeem fungeert als de centrale "Source of Truth" voor slimme pakketmuren en maakt gebruik van een **Digital Twin architectuur**.

De backend is gebouwd in FastAPI en communiceert asynchroon via MQTT met fysieke Edge Nodes (Raspberry Pi's) om hardware-deuren aan te sturen, statussen uit te lezen en pakketleveringen te beheren.

## Architectuur

Het project is opgedeeld in twee hoofdcomponenten:
1. **Cloud Backend (Dit project):** Draait in Docker, beheert de PostgreSQL database (gebruikers, kluizen, logboeken) en levert een REST API voor het Angular Admin Dashboard.
2. **Edge Node (Raspberry Pi):** De fysieke controller. Ontvangt commando's via MQTT, draait een lokale offline-database voor veerkracht en stuurt de sloten aan.

### Kernfuncties
* **Digital Twin:** De backend houdt een `shadow_state` bij van elke kluis op basis van MQTT telemetry heartbeats (elke minuut).
* **Zero-Touch Provisioning:** Zodra een nieuwe muur online komt, synchroniseert de backend automatisch de volledige configuratie (hardware-pinnen, bewoners, statussen) naar de Edge Node.
* **Dynamische QR-codes:** Genereert unieke afhaal-QR-codes volledig in het RAM-geheugen (`BytesIO`) en verstuurt deze als inline HTML-afbeelding via e-mail.
* **Veilige Authenticatie:** Gebruikt ruwe `bcrypt` voor pincodes (geen dependency hell met passlib) en beveiligde routes voor het dashboard.

## Tech Stack

* **Framework:** Python 3.11+ / FastAPI
* **Database:** PostgreSQL (via SQLAlchemy ORM)
* **IoT / Messaging:** Paho-MQTT
* **E-mail:** Resend SMTP (Port 587)
* **Deployment:** Docker

## Bestandsstructuur

```text
.
├── main.py              # FastAPI entrypoint & app configuratie
├── database.py          # PostgreSQL database connectie
├── models.py            # SQLAlchemy ORM modellen
├── schemas.py           # Pydantic validatie schema's
├── requirements.txt     # Python dependencies
├── Dockerfile           # Docker image configuratie
├── mqtt/                # MQTT Logica
│   ├── client.py        # MQTT connectie setup
│   └── handlers.py      # Verwerking van inkomende events (telemetry, levering, alarm)
└── routers/             # API Endpoints (REST)
    ├── walls.py         # Hardware statussen & kluis-configuratie
    ├── dashboard.py     # KPI's voor Angular frontend
    ├── residents.py     # Bewonersbeheer
    ├── maintenance.py   # Remote unlock & onderhoudsmodus
    ├── logs.py          # Audit trails
    ├── admins.py        # Dashboard beheerders
    └── auth.py          # Login & security