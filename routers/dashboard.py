"""
Router: Dashboard KPI's
=======================
Dit bestand levert de kerncijfers voor het hoofdscherm van het beheerders-dashboard.
Het berekent live-statistieken zoals het aantal pakketten van vandaag en
welke kluiswanden momenteel offline zijn (op basis van hun laatste heartbeat).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import Any

import models
import schemas
from database import get_db

# Prefix voor de routes
router = APIRouter(prefix="/api/dashboard")


@router.get(
    "/kpis", 
    response_model=schemas.DashboardKPIs,
    summary="Dashboard KPI's ophalen",
    response_description="De berekende statistieken voor de top-cards in het Angular dashboard."
)
def get_dashboard_kpis(db: Session = Depends(get_db)) -> Any:
    """
    Berekent de live-statistieken voor het thuisscherm van het dashboard.
    
    - **Pakketten vandaag**: Telt alle parcels die sinds middernacht (UTC) zijn geregistreerd.
    - **Fouten**: Telt het aantal CRITICAL audit logs.
    - **Online status**: Controleert de `last_seen` timestamp in de shadow_state van de kluizen. 
      Als de recentste heartbeat van een muur ouder is dan 5 minuten, wordt de muur als 'offline' beschouwd.
    """
    # 1. Pakketten vandaag (vanaf middernacht UTC)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    parcels_today = db.query(models.Parcel).filter(models.Parcel.created_at >= today).count()

    # 2. Openstaande errors (Telt alle logs met severity CRITICAL)
    open_errors = db.query(models.AuditLog).filter(models.AuditLog.severity == "CRITICAL").count()

    # 3. Muren & Offline status berekenen
    locations = db.query(models.Location).all()
    total_walls = len(locations)
    offline_locations = 0
    
    # Een kluiswand is offline als we al 5 minuten niks gehoord hebben van de Raspberry Pi
    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

    for loc in locations:
        lockers = db.query(models.Locker).filter(models.Locker.location_id == loc.id).all()
        last_sync = None
        
        # Zoek de meest recente heartbeat ('last_seen') over alle kluizen in deze muur
        for locker in lockers:
            if locker.shadow_state and "last_seen" in locker.shadow_state:
                try:
                    seen_time = datetime.fromisoformat(locker.shadow_state["last_seen"])
                    
                    # Zorg dat de tijd timezone-aware is (UTC) voor een correcte vergelijking
                    if seen_time.tzinfo is None:
                        seen_time = seen_time.replace(tzinfo=timezone.utc)
                        
                    if not last_sync or seen_time > last_sync:
                        last_sync = seen_time
                except Exception:
                    # Negeren als er een corrupte datum string in de JSON zit
                    pass
        
        # Als er geen heartbeat is gevonden, óf hij is te oud, dan telt de locatie als offline
        if not last_sync or last_sync < offline_threshold:
            offline_locations += 1

    active_walls = total_walls - offline_locations

    return {
        "parcels_today": parcels_today,
        "active_walls": active_walls,
        "total_walls": total_walls,
        "offline_locations": offline_locations,
        "open_errors": open_errors
    }