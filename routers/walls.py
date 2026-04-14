"""
Router: Walls & Lockers
========================

Endpoints for reading wall and locker hardware status, occupancy,
online/offline detection based on heartbeat timestamps, and full
CRUD for wall (location) management.
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional, Any
from datetime import datetime, timedelta, timezone

import models
import schemas
from database import get_db
from routers.auth import get_current_user

router = APIRouter(
    prefix="/api",
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/walls",
    response_model=List[schemas.WallListResponse],
    summary="List all walls",
    response_description="List of walls with occupancy and live status.",
)
def get_walls(
    search: Optional[str] = Query(None, description="Search by wall name"),
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by ONLINE or OFFLINE"),
    db: Session = Depends(get_db),
) -> Any:
    """Return all walls with occupancy stats and online/offline status.

    A wall is considered **offline** when its ``last_heartbeat`` is older
    than 5 minutes from the current UTC time.

    Args:
        search: Optional name search.
        status_filter: Filter by ``ONLINE`` or ``OFFLINE``.
        db: SQLAlchemy session.

    Returns:
        List of wall summary dicts.
    """
    locations = db.query(models.Location)
    if search:
        locations = locations.filter(models.Location.name.ilike(f"%{search}%"))
    locations = locations.all()

    response_data = []

    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

    for loc in locations:
        lockers = db.query(models.Locker).filter(models.Locker.location_id == loc.id).all()
        total_lockers = len(lockers)
        occupied_lockers = sum(1 for l in lockers if l.status == "Occupied")

        alarms = db.query(models.AuditLog).filter(
            models.AuditLog.locker_id.in_([l.id for l in lockers]),
            models.AuditLog.severity == "CRITICAL",
        ).count()

        last_sync = loc.last_heartbeat
        if last_sync and last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)

        is_online = last_sync and last_sync > offline_threshold
        wall_status = "ONLINE" if is_online else "OFFLINE"

        if status_filter and status_filter.upper() != "ALL":
            if status_filter.upper() != wall_status:
                continue

        response_data.append({
            "id": loc.id,
            "name": loc.name,
            "status": wall_status,
            "occupancy": f"{occupied_lockers}/{total_lockers}",
            "active_alarms": alarms,
            "last_sync": last_sync,
        })

    return response_data


@router.get("/walls/{wall_id}", response_model=schemas.WallDetailResponse)
def get_wall_detail(wall_id: int, db: Session = Depends(get_db)) -> Any:
    """Return detailed information for a single wall.

    Lockers that are ``Occupied`` but hold an ``AwaitingCourier`` parcel are
    overridden to show ``Return`` status for frontend display purposes.

    Args:
        wall_id: ID of the wall (location).
        db: SQLAlchemy session.

    Returns:
        Wall detail dict with nested locker list.

    Raises:
        HTTPException 404: If the wall is not found.
    """
    loc = db.query(models.Location).filter(models.Location.id == wall_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Wall not found")

    lockers = db.query(models.Locker).filter(models.Locker.location_id == wall_id).all()

    # Override status for display: an Occupied locker holding a return
    # parcel should appear as "Return" in the frontend
    for locker in lockers:
        if locker.status == "Occupied":
            parcel = db.query(models.Parcel).filter(
                models.Parcel.locker_id == locker.id,
                models.Parcel.status == "AwaitingCourier",
            ).first()
            if parcel:
                locker.status = "Return"

    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

    last_sync = loc.last_heartbeat
    if last_sync and last_sync.tzinfo is None:
        last_sync = last_sync.replace(tzinfo=timezone.utc)

    is_online = last_sync and last_sync > offline_threshold
    wall_status = "ONLINE" if is_online else "OFFLINE"

    return {
        "location_id": loc.id,
        "name": loc.name,
        "status": wall_status,
        "last_sync": last_sync,
        "lockers": lockers,
    }


@router.get(
    "/lockers/{locker_id}",
    response_model=schemas.LockerDetailResponse,
    summary="Get locker details",
    response_description="Full locker information including linked parcel and resident.",
)
def get_locker_detail(locker_id: int, db: Session = Depends(get_db)) -> Any:
    """Return all details for a single locker.

    If the locker is occupied, includes the active parcel and the linked
    resident's name and unit number.

    Args:
        locker_id: ID of the locker.
        db: SQLAlchemy session.

    Returns:
        Locker detail dict.

    Raises:
        HTTPException 404: If the locker is not found.
    """
    locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
    if not locker:
        raise HTTPException(status_code=404, detail="Locker not found")

    parcel = db.query(models.Parcel).filter(
        models.Parcel.locker_id == locker_id,
        models.Parcel.status.in_(["Delivered", "AwaitingCourier"]),
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
        "resident_unit": None,
    }

    if parcel:
        response["parcel_id"] = parcel.id
        response["parcel_status"] = parcel.status
        response["courier"] = parcel.courier
        response["delivery_time"] = parcel.created_at

        if parcel.user_id:
            user = db.query(models.User).filter(models.User.id == parcel.user_id).first()
            if user:
                response["resident_name"] = user.name
                response["resident_unit"] = user.unit_number

    return response


@router.post(
    "/walls",
    response_model=schemas.WallDetailResponse,
    summary="Create a new wall (with locker configuration)",
    response_description="The created wall including all nested lockers.",
)
def create_wall(wall_data: schemas.WallCreateRequest, db: Session = Depends(get_db)) -> Any:
    """Create a new wall (location) with its lockers.

    Generates a random 32-byte API key for the Raspberry Pi and bulk-inserts
    all lockers with their sizes and door numbers.

    Args:
        wall_data: Wall name, address, and locker configuration.
        db: SQLAlchemy session.

    Returns:
        The created wall with ``status: OFFLINE`` until the Pi boots.
    """
    import secrets

    new_location = models.Location(
        name=wall_data.name,
        address=wall_data.address,
        api_key=secrets.token_urlsafe(32),
    )
    db.add(new_location)
    db.commit()
    db.refresh(new_location)

    new_lockers = []
    for locker_in in wall_data.lockers:
        new_locker = models.Locker(
            location_id=new_location.id,
            door_number=locker_in.door_number,
            size=locker_in.size,
            status="Available",
            shadow_state={},
        )
        new_lockers.append(new_locker)

    db.bulk_save_objects(new_lockers)
    db.commit()

    saved_lockers = db.query(models.Locker).filter(models.Locker.location_id == new_location.id).all()

    return {
        "location_id": new_location.id,
        "name": new_location.name,
        "status": "OFFLINE",
        "last_sync": None,
        "lockers": saved_lockers,
    }


@router.delete(
    "/walls/{wall_id}",
    summary="Delete a wall",
    response_description="Deletion confirmation.",
)
def delete_wall(wall_id: int, db: Session = Depends(get_db)) -> Any:
    """Delete a wall and all its lockers.

    Safety check: deletion is blocked if any locker is currently occupied.

    Args:
        wall_id: ID of the wall to delete.
        db: SQLAlchemy session.

    Returns:
        Success message.

    Raises:
        HTTPException 400: If any locker is still occupied.
        HTTPException 404: If the wall is not found.
    """
    loc = db.query(models.Location).filter(models.Location.id == wall_id).first()
    if not loc:
        raise HTTPException(status_code=404, detail="Wall not found")

    lockers = db.query(models.Locker).filter(models.Locker.location_id == wall_id).all()
    for locker in lockers:
        if locker.status == "Occupied":
            raise HTTPException(
                status_code=400,
                detail=f"Cannot delete wall: locker {locker.id} still contains a parcel.",
            )

    for locker in lockers:
        db.delete(locker)

    db.delete(loc)
    db.commit()

    return {"message": f"Wall '{loc.name}' deleted successfully."}