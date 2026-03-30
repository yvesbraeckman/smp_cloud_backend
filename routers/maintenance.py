"""
Router: Hardware & Onderhoud (Maintenance)
==========================================
Dit bestand regelt de Cloud-to-Device (C2D) communicatie. 
Hier vangen we API-verzoeken van het Angular dashboard op en vertalen 
we deze naar fysieke MQTT commando's voor de Raspberry Pi in de kluiswand.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any
import json
import uuid

import models
import schemas
from database import get_db
from mqtt.client import client as mqtt_client  # Importeer de actieve MQTT client

# Prefix voor de routes 
router = APIRouter(prefix="/api/maintenance")


@router.post(
    "/remote-unlock",
    summary="Kluis op afstand forceren (Remote Unlock)",
    response_description="Bevestiging dat het MQTT open-commando is verstuurd."
)
def remote_unlock(request: schemas.RemoteUnlockRequest, db: Session = Depends(get_db)) -> dict:
    """
    Forceert een fysiek kluisdeurtje om open te springen via het dashboard.
    
    1. Controleert of de kluis bestaat in de database.
    2. Stuurt een MQTT bericht (`cmd/open`) naar de specifieke kluiswand.
    3. Logt de actie direct in de Audit Log voor traceerbaarheid.
    """
    # 1. Check of de locker bestaat in de database
    locker = db.query(models.Locker).filter(
        models.Locker.id == request.locker_id,
        models.Locker.location_id == request.location_id
    ).first()
    
    if not locker:
        raise HTTPException(status_code=404, detail="Locker of locatie niet gevonden")

    # 2. Downstream MQTT commando: Stuur het open-commando naar de RPi
    cmd_payload = {
        "transaction_id": str(uuid.uuid4()),  # Unieke ID om het commando te volgen
        "locker_id": request.locker_id,
        "reason": request.reason
    }
    topic = f"lockers/{request.location_id}/cmd/open"
    
    # qos=1 zorgt ervoor dat we zeker weten dat de broker het bericht ontvangt
    mqtt_client.publish(topic, json.dumps(cmd_payload), qos=1)
    
    # 3. Log de actie in de Audit Log
    new_log = models.AuditLog(
        location_id=request.location_id,
        locker_id=locker.id,
        event_type="REMOTE_OPEN",
        severity="CRITICAL",
        description=f"Remote unlock via dashboard. Reden: {request.reason}"
    )
    db.add(new_log)
    db.commit()

    return {"success": True, "message": f"Open commando verzonden via MQTT naar kluis {request.locker_id}."}


@router.post(
    "/service-mode",
    summary="Onderhoudsmodus in/uitschakelen",
    response_description="Bevestiging van de statuswijziging."
)
def set_service_mode(request: schemas.ServiceModeRequest, db: Session = Depends(get_db)) -> dict:
    """
    Zet een specifieke kluis in of uit onderhoud ('Maintenance' of 'Available').
    
    Deze status wordt direct opgeslagen in de cloud-database én gesynchroniseerd
    met de lokale hardware via MQTT, zodat het lokale scherm van de kluiswand 
    deze kluis ook als 'buiten gebruik' markeert.
    """
    # Haal de locker op (we hebben de location_id nodig voor het MQTT topic)
    locker = db.query(models.Locker).filter(models.Locker.id == request.locker_id).first()
    
    if not locker:
        raise HTTPException(status_code=404, detail="Locker niet gevonden")

    # 1. Update de status in de cloud database
    locker.status = request.status
    db.commit()

    # 2. Downstream MQTT commando: Laat de RPi weten dat deze locker offline/online is
    status_payload = {
        "locker_id": request.locker_id,
        "status": request.status
    }
    topic = f"lockers/{locker.location_id}/cmd/status"
    mqtt_client.publish(topic, json.dumps(status_payload), qos=1)

    return {"success": True, "message": f"Kluis {request.locker_id} status geüpdatet en Edge (RPi) is genotificeerd."}