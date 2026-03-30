"""
Router: Kluiswanden & Deurtjes (Walls & Lockers)
================================================
Dit bestand bevat de endpoints voor het ophalen van de hardware statussen.
Hier berekent de backend live of een kluiswand online is (via IoT heartbeats)
en wat de huidige bezettingsgraad van de kluisjes is.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional, Any
from datetime import datetime, timedelta, timezone

import models
import schemas
from database import get_db

# Prefix voor alle routes in dit bestand
router = APIRouter(prefix="/api")


@router.get(
    "/walls", 
    response_model=List[schemas.WallListResponse],
    summary="Overzicht kluiswanden ophalen",
    response_description="Lijst met alle kluiswanden inclusief bezetting en live status."
)
def get_walls(
    search: Optional[str] = Query(None, description="Zoek op naam van de kluiswand"), 
    status_filter: Optional[str] = Query(None, alias="status", description="Filter op ONLINE of OFFLINE"),
    db: Session = Depends(get_db)
) -> Any:
    """
    Haalt de lijst met alle Wall Cards op voor het dashboard.
    Berekent voor elke muur dynamisch de bezetting en de online/offline status 
    door te kijken naar de meest recente `last_seen` timestamp van de kluisjes.
    """
    locations = db.query(models.Location)
    if search:
        locations = locations.filter(models.Location.name.ilike(f"%{search}%"))
    locations = locations.all()

    response_data = []
    
    # 5 minuten grens voor offline status
    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

    for loc in locations:
        # Haal alle kluizen op voor deze muur
        lockers = db.query(models.Locker).filter(models.Locker.location_id == loc.id).all()
        total_lockers = len(lockers)
        occupied_lockers = sum(1 for l in lockers if l.status == "Occupied")
        
        # Check active alarms (Telt het aantal openstaande CRITICAL logs voor deze muur)
        alarms = db.query(models.AuditLog).filter(
            models.AuditLog.locker_id.in_([l.id for l in lockers]),
            models.AuditLog.severity == "CRITICAL"
        ).count()

        # Bepaal last_sync en online status op basis van de lockers shadow_state
        last_sync = None
        is_online = False
        
        for locker in lockers:
            if locker.shadow_state and "last_seen" in locker.shadow_state:
                try:
                    seen_time = datetime.fromisoformat(locker.shadow_state["last_seen"])
                    # Zorg dat seen_time timezone-aware is voor een correcte vergelijking
                    if seen_time.tzinfo is None:
                        seen_time = seen_time.replace(tzinfo=timezone.utc)
                    if not last_sync or seen_time > last_sync:
                        last_sync = seen_time
                except Exception:
                    pass
        
        if last_sync and last_sync > offline_threshold:
            is_online = True

        wall_status = "ONLINE" if is_online else "OFFLINE"

        # Pas status filter toe als deze is meegegeven in de URL (?status=online)
        if status_filter and status_filter.upper() != "ALL":
            if status_filter.upper() != wall_status:
                continue

        response_data.append({
            "id": loc.id,
            "name": loc.name,
            "status": wall_status,
            "occupancy": f"{occupied_lockers}/{total_lockers}",
            "active_alarms": alarms,
            "last_sync": last_sync
        })

    return response_data


@router.get(
    "/walls/{wall_id}", 
    response_model=schemas.WallDetailResponse,
    summary="Details kluiswand ophalen",
    response_description="De volledige configuratie van één kluiswand inclusief alle deurtjes."
)
def get_wall_detail(wall_id: int, db: Session = Depends(get_db)) -> Any:
    """
    Haalt de specifieke grid-layout en status op van één muur.
    Wordt gebruikt wanneer een beheerder op een Wall Card klikt.
    """
    loc = db.query(models.Location).filter(models.Location.id == wall_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Muur niet gevonden")

    lockers = db.query(models.Locker).filter(models.Locker.location_id == wall_id).all()
    
    # 1. Bereken de ECHTE status en last_sync, net als in het dashboard
    last_sync = None
    is_online = False
    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
    
    for locker in lockers:
        if locker.shadow_state and "last_seen" in locker.shadow_state:
            try:
                seen_time = datetime.fromisoformat(locker.shadow_state["last_seen"])
                if seen_time.tzinfo is None:
                    seen_time = seen_time.replace(tzinfo=timezone.utc)
                if not last_sync or seen_time > last_sync:
                    last_sync = seen_time
            except Exception:
                pass
    
    if last_sync and last_sync > offline_threshold:
        is_online = True
        
    wall_status = "ONLINE" if is_online else "OFFLINE"

    # 2. Stuur de berekende data terug
    return {
        "location_id": loc.id,
        "name": loc.name,
        "status": wall_status,
        "last_sync": last_sync,
        "lockers": lockers
    }


@router.get(
    "/lockers/{locker_id}", 
    response_model=schemas.LockerDetailResponse,
    summary="Details kluisje ophalen",
    response_description="Alle informatie van één kluisje, inclusief gekoppeld pakket."
)
def get_locker_detail(locker_id: int, db: Session = Depends(get_db)) -> Any:
    """
    Haalt alle details van één kluisje op. 
    Als de kluis de status 'Occupied' heeft, zoekt deze route ook op welk 
    specifiek pakket (en welke bewoner) aan deze kluis gekoppeld is.
    """
    locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
    if not locker:
        raise HTTPException(status_code=404, detail="Kluis niet gevonden")

    # Zoek of er een actief pakket in ligt
    parcel = db.query(models.Parcel).filter(
        models.Parcel.locker_id == locker_id,
        models.Parcel.status == "Delivered"
    ).first()

    response = {
        "id": locker.id,
        "status": locker.status,
        "size": locker.size,
        "shadow_state": locker.shadow_state,
        "parcel_id": None,
        "parcel_status": None,
        "courier": None,
        "delivery_time": None,
        "resident_name": None,
        "resident_unit": None
    }

    # Vul pakket- en bewoner-info aan als de kluis in gebruik is
    if parcel:
        response["parcel_id"] = parcel.id
        response["parcel_status"] = parcel.status
        response["courier"] = parcel.courier
        response["delivery_time"] = parcel.created_at
        
        # Als er een gebruiker (bewoner) aan gekoppeld is, haal die ook op
        if parcel.user_id:
            user = db.query(models.User).filter(models.User.id == parcel.user_id).first()
            if user:
                response["resident_name"] = user.name
                response["resident_unit"] = user.unit_number

    return response

@router.post(
    "/walls", 
    response_model=schemas.WallDetailResponse,
    summary="Nieuwe kluiswand aanmaken (inclusief configuratie)",
    response_description="De aangemaakte muur inclusief alle geneste kluisjes."
)
def create_wall(wall_data: schemas.WallCreateRequest, db: Session = Depends(get_db)) -> Any:
    """
    Maakt een nieuwe fysieke locatie (kluiswand) aan.
    Koppelt direct alle kluisjes met hun juiste formaten en hardware-pinnen (door_number)
    aan deze nieuwe muur.
    """
    import secrets
    
    # 1. Maak de nieuwe Locatie aan in de database
    new_location = models.Location(
        name=wall_data.name,
        address=wall_data.address,
        api_key=secrets.token_urlsafe(32) # Genereer direct een veilige sleutel voor de Pi
    )
    db.add(new_location)
    db.commit()
    db.refresh(new_location) # Haal het nieuwe ID op (bijv. ID 35)

    # 2. Loop door de lijst met kluisjes die Angular meestuurde en voeg ze toe
    new_lockers = []
    for locker_in in wall_data.lockers:
        new_locker = models.Locker(
            location_id=new_location.id,
            door_number=locker_in.door_number,
            size=locker_in.size,
            status="Available", # Een nieuwe muur is altijd leeg
            shadow_state={}
        )
        new_lockers.append(new_locker)
    
    db.bulk_save_objects(new_lockers)
    db.commit()

    # 3. Haal de kluisjes opnieuw op om ze terug te sturen in de response
    saved_lockers = db.query(models.Locker).filter(models.Locker.location_id == new_location.id).all()

    return {
        "location_id": new_location.id,
        "name": new_location.name,
        "status": "OFFLINE", # Een net aangemaakte muur is altijd offline tot de Pi opstart
        "last_sync": None,
        "lockers": saved_lockers
    }

@router.delete(
    "/walls/{wall_id}", 
    summary="Kluiswand verwijderen",
    response_description="Bevestiging van verwijdering."
)
def delete_wall(wall_id: int, db: Session = Depends(get_db)) -> Any:
    """
    Verwijdert een fysieke locatie (kluiswand).
    Veiligheidscheck: Kan alleen verwijderd worden als alle kluisjes leeg zijn.
    """
    # 1. Zoek de muur op
    loc = db.query(models.Location).filter(models.Location.id == wall_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Muur niet gevonden")

    # 2. Veiligheidscheck: check of er nog bezette kluisjes zijn
    lockers = db.query(models.Locker).filter(models.Locker.location_id == wall_id).all()
    for locker in lockers:
        if locker.status == "Occupied":
            raise HTTPException(
                status_code=400, 
                detail=f"Kan muur niet verwijderen: kluis {locker.id} bevat nog een pakket."
            )

    # 3. Verwijder de muur
    # Let op: dit vereist dat de relatie in models.py een cascade heeft, 
    # bv: lockers = relationship("Locker", back_populates="location", cascade="all, delete-orphan")
    # Mocht je dat niet hebben, dan kun je de kluisjes hier ook handmatig weggooien:
    for locker in lockers:
        db.delete(locker)

    db.delete(loc)
    db.commit()

    return {"message": f"Muur '{loc.name}' succesvol verwijderd."}