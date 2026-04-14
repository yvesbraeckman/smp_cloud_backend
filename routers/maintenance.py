"""
Router: Hardware & Maintenance
==============================

Cloud-to-device (C2D) communication. Translates dashboard API requests
into MQTT commands that are executed by the Raspberry Pi inside the
locker wall (e.g. remote unlock, service-mode toggle).
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any
import json
import uuid

import models
import schemas
from database import get_db
from mqtt.client import client as mqtt_client

from routers.auth import get_current_user

router = APIRouter(
    prefix="/api/maintenance",
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "/remote-unlock",
    summary="Remote unlock a locker",
    response_description="Confirmation that the MQTT open command was sent.",
)
def remote_unlock(request: schemas.RemoteUnlockRequest, db: Session = Depends(get_db)) -> dict:
    """Force a locker door open remotely from the dashboard.

    Validates the locker exists, publishes an ``cmd/open`` MQTT command
    (QoS 1 for guaranteed delivery) with a unique transaction ID, and
    logs the action as CRITICAL in the audit log for traceability.

    Args:
        request: Locker and location IDs plus the reason for unlocking.
        db: SQLAlchemy session.

    Returns:
        Success confirmation.

    Raises:
        HTTPException 404: If the locker or location is not found.
    """
    locker = db.query(models.Locker).filter(
        models.Locker.id == request.locker_id,
        models.Locker.location_id == request.location_id,
    ).first()

    if not locker:
        raise HTTPException(status_code=404, detail="Locker or location not found")

    cmd_payload = {
        "transaction_id": str(uuid.uuid4()),
        "locker_id": request.locker_id,
        "reason": request.reason,
    }
    topic = f"lockers/{request.location_id}/cmd/open"

    mqtt_client.publish(topic, json.dumps(cmd_payload), qos=1)

    new_log = models.AuditLog(
        location_id=request.location_id,
        locker_id=locker.id,
        event_type="REMOTE_OPEN",
        severity="CRITICAL",
        description=f"Remote unlock via dashboard. Reason: {request.reason}",
    )
    db.add(new_log)
    db.commit()

    return {"success": True, "message": f"Open command sent via MQTT to locker {request.locker_id}."}


@router.post(
    "/service-mode",
    summary="Toggle maintenance mode",
    response_description="Confirmation of the status change.",
)
def set_service_mode(request: schemas.ServiceModeRequest, db: Session = Depends(get_db)) -> dict:
    """Toggle a locker between maintenance and available status.

    The status change is persisted in the cloud database **and** propagated
    to the edge device via MQTT so the wall's touch screen reflects the
    updated state (e.g. marks the door as out of service).

    Args:
        request: Locker ID and the target status (``Maintenance`` or ``Available``).
        db: SQLAlchemy session.

    Returns:
        Success confirmation.

    Raises:
        HTTPException 404: If the locker is not found.
    """
    locker = db.query(models.Locker).filter(models.Locker.id == request.locker_id).first()

    if not locker:
        raise HTTPException(status_code=404, detail="Locker not found")

    locker.status = request.status
    db.commit()

    status_payload = {
        "locker_id": request.locker_id,
        "status": request.status,
    }
    topic = f"lockers/{locker.location_id}/cmd/status"
    mqtt_client.publish(topic, json.dumps(status_payload), qos=1)

    return {"success": True, "message": f"Locker {request.locker_id} status updated and edge device notified."}