"""
Router: Dashboard KPIs
=====================

Provides live statistics for the admin dashboard home screen: parcels
delivered today, critical error count, and wall online/offline status
based on IoT heartbeat timestamps.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from typing import Any

import models
import schemas
from database import get_db

from routers.auth import get_current_user

router = APIRouter(
    prefix="/api/dashboard",
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/kpis",
    response_model=schemas.DashboardKPIs,
    summary="Get dashboard KPIs",
    response_description="Calculated statistics for the dashboard top cards.",
)
def get_dashboard_kpis(db: Session = Depends(get_db)) -> Any:
    """Compute live dashboard statistics.

    - **Parcels today**: All parcels registered since midnight UTC.
    - **Critical errors**: Audit logs with severity ``CRITICAL``.
    - **Online/offline walls**: A wall is **offline** when its most recent
      heartbeat across any of its lockers is older than 5 minutes.

    Args:
        db: SQLAlchemy session.

    Returns:
        Dict with ``parcels_today``, ``active_walls``, ``total_walls``,
        ``offline_locations``, and ``open_errors``.
    """
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    parcels_today = db.query(models.Parcel).filter(models.Parcel.created_at >= today).count()

    open_errors = db.query(models.AuditLog).filter(models.AuditLog.severity == "CRITICAL").count()

    locations = db.query(models.Location).all()
    total_walls = len(locations)
    offline_locations = 0

    offline_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)

    for loc in locations:
        lockers = db.query(models.Locker).filter(models.Locker.location_id == loc.id).all()
        last_sync = None

        # Find the most recent heartbeat across all lockers in this wall
        for locker in lockers:
            if locker.shadow_state and "last_seen" in locker.shadow_state:
                try:
                    seen_time = datetime.fromisoformat(locker.shadow_state["last_seen"])

                    # Ensure timezone-aware comparison
                    if seen_time.tzinfo is None:
                        seen_time = seen_time.replace(tzinfo=timezone.utc)

                    if not last_sync or seen_time > last_sync:
                        last_sync = seen_time
                except Exception:
                    pass

        if not last_sync or last_sync < offline_threshold:
            offline_locations += 1

    active_walls = total_walls - offline_locations

    return {
        "parcels_today": parcels_today,
        "active_walls": active_walls,
        "total_walls": total_walls,
        "offline_locations": offline_locations,
        "open_errors": open_errors,
    }