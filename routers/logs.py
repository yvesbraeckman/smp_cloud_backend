"""
Router: Audit Logs
==================

Provides endpoints to create, list, filter, and CSV-export system audit
logs. Both hardware-generated events (MQTT) and manual admin actions are
recorded here.
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc, cast, Date
from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import date, datetime
import io
import csv

import models
import schemas
from database import get_db

from routers.auth import get_current_user

router = APIRouter(
    prefix="/api/logs",
    dependencies=[Depends(get_current_user)],
)


class LogCreateRequest(BaseModel):
    """Schema for manually writing a log entry from the dashboard."""

    location_id: Optional[int] = Field(None, description="Wall location ID (if location-specific)")
    locker_id: Optional[int] = Field(None, description="Locker ID")
    event_type: str = Field(..., description="Event type (e.g. ADMIN_ACTION or ALARM)", examples=["ADMIN_ACTION"])
    severity: str = Field(..., description="Severity level (INFO, WARNING, CRITICAL)", examples=["WARNING"])
    description: str = Field(..., description="Details of the event", examples=["Locker put into maintenance by admin."])


def get_filtered_logs_query(
    db: Session,
    log_date: Optional[date] = None,
    location_id: Optional[int] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
) -> Any:
    """Build the filtered SQLAlchemy query shared by the list and export endpoints.

    Centralising the filter logic here ensures both endpoints apply the exact
    same criteria.

    Args:
        db: SQLAlchemy session.
        log_date: Filter by calendar date (ignores time-of-day).
        location_id: Filter by wall location.
        severity: Filter by severity (case-insensitive).
        search: Free-text search across description and event_type.

    Returns:
        A SQLAlchemy query ordered by timestamp descending.
    """
    query = db.query(models.AuditLog)

    if location_id:
        query = query.filter(models.AuditLog.location_id == location_id)

    if log_date:
        query = query.filter(cast(models.AuditLog.timestamp, Date) == log_date)

    if severity:
        query = query.filter(models.AuditLog.severity.ilike(severity))

    if search:
        query = query.filter(
            models.AuditLog.description.ilike(f"%{search}%")
            | models.AuditLog.event_type.ilike(f"%{search}%")
        )

    return query.order_by(desc(models.AuditLog.timestamp))


@router.post(
    "",
    response_model=schemas.LogResponse,
    summary="Create a new log entry",
    response_description="The saved log entry.",
)
def create_log(request: LogCreateRequest, db: Session = Depends(get_db)) -> Any:
    """Write a manual audit log entry.

    Primarily used by the dashboard to record admin actions such as
    remotely unlocking a door.

    Args:
        request: Log entry details.
        db: SQLAlchemy session.

    Returns:
        The created AuditLog model.
    """
    new_log = models.AuditLog(
        location_id=request.location_id,
        locker_id=request.locker_id,
        event_type=request.event_type,
        severity=request.severity,
        description=request.description,
        timestamp=datetime.utcnow(),
    )

    db.add(new_log)
    db.commit()
    db.refresh(new_log)

    return new_log


@router.get(
    "",
    response_model=List[schemas.LogResponse],
    summary="List and filter logs",
    response_description="A list of log entries matching the filters.",
)
def get_logs(
    log_date: Optional[date] = Query(None, alias="date", description="Filter by date (YYYY-MM-DD)"),
    location_id: Optional[int] = Query(None, description="Filter by wall ID"),
    severity: Optional[str] = Query(None, alias="type", description="Filter by severity (INFO, WARNING, CRITICAL)"),
    search: Optional[str] = Query(None, description="Search in description"),
    limit: int = Query(50, ge=1, le=500, description="Number of results (max 500)"),
    db: Session = Depends(get_db),
) -> List[dict]:
    """Return a paginated list of audit logs.

    Uses a single dict lookup for location names (1 query instead of N+1)
    to avoid querying the database per row.

    Args:
        log_date: Filter by date.
        location_id: Filter by wall.
        severity: Filter by severity.
        search: Free-text search term.
        limit: Maximum number of rows.
        db: SQLAlchemy session.

    Returns:
        List of dicts with log data and resolved location names.
    """
    query = get_filtered_logs_query(db, log_date, location_id, severity, search)
    logs = query.limit(limit).all()

    # Eager-load all location names in one query
    locations = {loc.id: loc.name for loc in db.query(models.Location).all()}

    result = []
    for log in logs:
        loc_name = locations.get(log.location_id) if log.location_id else None

        result.append({
            "id": log.id,
            "locker_id": log.locker_id,
            "location_name": loc_name,
            "event_type": log.event_type,
            "severity": log.severity,
            "description": log.description,
            "timestamp": log.timestamp,
        })

    return result


@router.get(
    "/export",
    summary="Export logs to CSV",
    response_description="A downloadable CSV file with the log data.",
)
def export_logs(
    log_date: Optional[date] = Query(None, alias="date"),
    location_id: Optional[int] = None,
    severity: Optional[str] = Query(None, alias="type"),
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Stream a semicolon-delimited CSV based on the same filters as the list endpoint.

    Returns a StreamingResponse so the browser prompts a file download instead
    of rendering the content.

    Args:
        log_date: Filter by date.
        location_id: Filter by wall.
        severity: Filter by severity.
        search: Free-text search term.
        db: SQLAlchemy session.

    Returns:
        StreamingResponse with ``text/csv`` content type.
    """
    query = get_filtered_logs_query(db, log_date, location_id, severity, search)
    logs = query.all()

    locations = {loc.id: loc.name for loc in db.query(models.Location).all()}

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow(["ID", "Timestamp", "Location & Locker", "Type", "Severity", "Description"])

    for log in logs:
        loc_name = "System"
        if log.location_id:
            base_name = locations.get(log.location_id, "Unknown Wall")
            if log.locker_id:
                loc_name = f"{base_name} (Locker {log.locker_id})"
            else:
                loc_name = base_name

        writer.writerow([
            log.id,
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            loc_name,
            log.event_type,
            log.severity,
            log.description,
        ])

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=smartwall_logs_export.csv"},
    )