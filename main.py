"""
Hoofdapplicatie (Main)
======================
Dit is het startpunt van de FastAPI backend voor de Smart Parcel Wall.
Hier configureren we de API, koppelen we de database, en laden we alle 
verschillende modules (routers) in.
"""

import os
from dotenv import load_dotenv
load_dotenv()

from contextlib import asynccontextmanager
from fastapi import FastAPI
from database import engine, Base
import models
from routers import maintenance, walls, residents, logs, auth, dashboard, admins
from mqtt.client import start_mqtt, stop_mqtt
from mqtt.handlers import send_delivery_email

# 1. Creëer de database tabellen als ze nog niet bestaan
# Skip table creation during imports (e.g., for testing)
IN_TEST_MODE = os.getenv("IN_TEST_MODE", "false").lower() == "true"
if not IN_TEST_MODE:
    Base.metadata.create_all(bind=engine)


# 2. De Lifespan (Startup & Shutdown logica)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # DIT GEBEURT BIJ OPSTARTEN:
    print("[SYSTEM] FastAPI is aan het opstarten, MQTT client wordt geladen...")
    start_mqtt()
    
    yield  # Hier draait je applicatie...
    
    # DIT GEBEURT BIJ AFSLUITEN:
    print("[SYSTEM] FastAPI sluit af, MQTT verbinding verbreken...")
    stop_mqtt()

# 3. Uitgebreide beschrijving voor de Swagger documentatie (/docs)
api_description = """
Welkom bij de **Smart Parcel Wall API**. 

Deze API vormt de brug tussen het Angular beheerders-dashboard en de fysieke kluiswanden.
Hier vind je alle endpoints voor:
* **Authenticatie:** Inloggen en wachtwoordbeheer voor beheerders.
* **Dashboard:** KPI's en live-statistieken.
* **Hardware:** Fysieke kluizen openen en in onderhoud zetten.
* **Bewoners:** Gebruikers beheren die pakketten mogen ontvangen.
"""

# 4. Tags metadata zorgt ervoor dat je /docs pagina mooi gegroepeerd wordt
tags_metadata = [
    {"name": "Authenticatie", "description": "Login, tokens en admin profielen."},
    {"name": "Dashboard", "description": "Statistieken en KPI's voor het thuisscherm."},
    {"name": "Kluiswanden", "description": "Locaties, kluismuren en deurtjes bedienen."},
    {"name": "Bewoners", "description": "CRUD operaties voor bewoners (toevoegen/wijzigen/verwijderen)."},
    {"name": "Systeem & Logs", "description": "Audit trails en algemene server status."},
]

# 4. Initialiseer de FastAPI applicatie met alle metadata
app = FastAPI(
    title="Smart Parcel Wall API", 
    description=api_description,
    version="1.0.0",
    openapi_tags=tags_metadata,
    lifespan=lifespan, 
    contact={
        "name": "SmartWall Support",
        "email": "support@smartparcelwall.be",
    }
)

# 5. Koppel alle losse route-bestanden (de 'controllers') aan de hoofd-app
# Door de 'tags' parameter te gebruiken, vallen ze direct in de juiste categorie in /docs
app.include_router(auth.router, tags=["Authenticatie"])
app.include_router(admins.router, tags=["Authenticatie"])
app.include_router(dashboard.router, tags=["Dashboard"]) 
app.include_router(walls.router, tags=["Kluiswanden"])
app.include_router(maintenance.router, tags=["Kluiswanden"])
app.include_router(residents.router, tags=["Bewoners"])
app.include_router(logs.router, tags=["Systeem & Logs"])


# 6. De Health-Check Endpoint
@app.get(
    "/api/system/status", 
    tags=["Systeem & Logs"], 
    summary="Check de server status",
    response_description="Een simpel JSON object dat aantoont dat de server draait."
)
async def get_status() -> dict:
    """
    Simpele health-check route om te controleren of de FastAPI server bereikbaar is.
    Wordt in de achtergrond gebruikt door het dashboard of load-balancers.
    """
    return {
        "online": True,
        "active_alarms": False,
        "message": "FastAPI backend is succesvol gekoppeld!"
    }
