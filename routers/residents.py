"""
Router: Residents
=================

CRUD endpoints for managing residents. Every create, update, or delete
operation is immediately synced to the edge wall via MQTT so the touch
screen stays up to date.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, Any
import random
import models
import schemas
from database import get_db
import json
from mqtt.client import client as mqtt_client
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from routers.auth import get_current_user

router = APIRouter(
    prefix="/api/residents",
    dependencies=[Depends(get_current_user)],
)


# ==========================================
# Email helper
# ==========================================

def send_access_code_email(recipient_email: str, recipient_name: str, pin_code: str):
    """Send an HTML email to the resident with a newly generated access PIN.

    Args:
        recipient_email: Resident's email address.
        recipient_name: Resident's display name.
        pin_code: The plaintext PIN code.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] Email credentials missing in environment.")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg["To"] = recipient_email
    msg["Subject"] = "Your new access code for the Smart Parcel Wall"

    html_body = f"""
    <html>
      <body style="font-family: -apple-system, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2>Dear {recipient_name},</h2>
        <p>An administrator has just generated a new access code for you.</p>

        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px; text-align: center;">
            <p style="margin: 0; font-size: 14px; color: #86868b; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Your Pin Code</p>
            <p style="margin: 10px 0 0 0; font-size: 36px; font-weight: bold; color: #0a84ff; letter-spacing: 6px;">{pin_code}</p>
        </div>

        <p>You can use this code directly on the locker wall screen to pick up your parcels.</p>

        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">
            Kind regards,<br>
            The Smart Parcel Wall System
        </p>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)

        print(f"[EMAIL INFO] Access code email sent successfully to {recipient_email}")

    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send access code email to {recipient_email}: {e}")


# ==========================================
# Endpoints
# ==========================================

@router.get(
    "",
    response_model=schemas.ResidentPaginatedResponse,
    summary="List residents (with search & pagination)",
)
def get_residents(
    search: Optional[str] = Query(None, description="Search by name, email, unit, or location"),
    page: int = Query(1, ge=1, description="Current page (starts at 1)"),
    limit: int = Query(10, ge=1, le=100, description="Residents per page (max 100)"),
    db: Session = Depends(get_db),
) -> Any:
    """Return a paginated, searchable list of residents.

    Search is case-insensitive and matches against name, email, unit number,
    and location name.

    Args:
        search: Optional free-text search term.
        page: Page number (1-based).
        limit: Page size.
        db: SQLAlchemy session.

    Returns:
        Paginated response with ``items``, ``total``, ``page``, and ``limit``.
    """
    query = db.query(models.User).outerjoin(
        models.Location, models.User.location_id == models.Location.id
    )

    if search:
        query = query.filter(
            models.User.name.ilike(f"%{search}%")
            | models.User.email.ilike(f"%{search}%")
            | models.User.unit_number.ilike(f"%{search}%")
            | models.Location.name.ilike(f"%{search}%")
        )

    total_records = query.count()
    offset = (page - 1) * limit
    users = query.offset(offset).limit(limit).all()

    return {
        "items": users,
        "total": total_records,
        "page": page,
        "limit": limit,
    }


@router.post(
    "",
    response_model=schemas.ResidentResponse,
    summary="Create a new resident",
)
def create_resident(resident: schemas.ResidentCreate, db: Session = Depends(get_db)) -> Any:
    """Create a resident and immediately push the record to the edge wall.

    Args:
        resident: New resident details.
        db: SQLAlchemy session.

    Returns:
        The created User model.

    Raises:
        HTTPException 400: If the email is already in use.
    """
    if db.query(models.User).filter(models.User.email == resident.email).first():
        raise HTTPException(status_code=400, detail="Email address already in use")

    new_user = models.User(**resident.model_dump())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    if new_user.location_id:
        sync_payload = {
            "users": [{
                "id": new_user.id,
                "name": new_user.name,
                "email": new_user.email,
                "unit_number": new_user.unit_number,
            }]
        }

        topic = f"lockers/{new_user.location_id}/cmd/sync_users"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] New resident (ID: {new_user.id}) pushed to wall {new_user.location_id}")

    return new_user


@router.put(
    "/{resident_id}",
    response_model=schemas.ResidentResponse,
    summary="Update a resident",
)
def update_resident(
    resident_id: int,
    resident: schemas.ResidentUpdate,
    db: Session = Depends(get_db),
) -> Any:
    """Update a resident and push the changes to the edge wall.

    Args:
        resident_id: ID of the resident to update.
        resident: Updated fields (partial).
        db: SQLAlchemy session.

    Returns:
        The refreshed User model.

    Raises:
        HTTPException 404: If the resident is not found.
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Resident not found")

    update_data = resident.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)

    db.commit()
    db.refresh(db_user)

    if db_user.location_id:
        sync_payload = {
            "users": [{
                "id": db_user.id,
                "name": db_user.name,
                "email": db_user.email,
                "unit_number": db_user.unit_number,
            }]
        }

        topic = f"lockers/{db_user.location_id}/cmd/sync_users"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Resident (ID: {db_user.id}) update pushed to wall {db_user.location_id}")

    return db_user


@router.delete(
    "/{resident_id}",
    summary="Delete a resident",
)
def delete_resident(resident_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete a resident and send a delete command to the edge wall.

    Args:
        resident_id: ID of the resident to delete.
        db: SQLAlchemy session.

    Returns:
        Success confirmation.

    Raises:
        HTTPException 404: If the resident is not found.
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Resident not found")

    location_id = db_user.location_id
    res_name = db_user.name

    db.delete(db_user)
    db.commit()

    if location_id:
        delete_payload = {"resident_id": resident_id}
        topic = f"lockers/{location_id}/cmd/delete_user"
        mqtt_client.publish(topic, json.dumps(delete_payload), qos=1)
        print(f"[API] Delete command for resident {res_name} (ID: {resident_id}) pushed to wall {location_id}")

    return {"success": True, "message": f"Resident {res_name} deleted successfully."}


@router.post(
    "/{resident_id}/credentials/generate",
    summary="Generate access code",
)
def generate_credentials(resident_id: int, db: Session = Depends(get_db)) -> dict:
    """Generate a new access PIN for all of a resident's active parcels.

    When a resident has parcels currently in the wall (status ``Delivered``),
    this generates a single 6-digit PIN, hashes it with bcrypt, and assigns
    it to every active parcel. The full whitelist for the wall is then
    rebuilt and pushed to the edge device (because the Pi clears its memory
    on ``sync_whitelist``). Finally, the plaintext PIN is emailed to the
    resident.

    Args:
        resident_id: ID of the resident.
        db: SQLAlchemy session.

    Returns:
        Success message with the generated PIN (debug only).

    Raises:
        HTTPException 404: If the resident is not found.
        HTTPException 400: If the resident has no active parcels.
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Resident not found")

    active_user_parcels = db.query(models.Parcel).filter(
        models.Parcel.user_id == resident_id,
        models.Parcel.status == "Delivered",
    ).all()

    if not active_user_parcels:
        raise HTTPException(
            status_code=400,
            detail="This resident has no parcels currently in the wall.",
        )

    new_pin = str(random.randint(100000, 999999))
    hashed_pin = pwd_context.hash(new_pin)

    for parcel in active_user_parcels:
        parcel.pincode = hashed_pin

    db.commit()

    # Rebuild the full whitelist for the wall (the Pi replaces its entire
    # code store on each sync_whitelist command)
    wall_id = db_user.location_id
    if wall_id:
        all_active_parcels_on_wall = db.query(models.Parcel).join(models.Locker).filter(
            models.Locker.location_id == wall_id,
            models.Parcel.status == "Delivered",
        ).all()

        valid_codes_dict = {}
        for p in all_active_parcels_on_wall:
            if p.pincode not in valid_codes_dict:
                valid_codes_dict[p.pincode] = []
            valid_codes_dict[p.pincode].append(p.locker_id)

        valid_codes_list = [
            {"hash": code_hash, "locker_ids": l_ids}
            for code_hash, l_ids in valid_codes_dict.items()
        ]

        sync_payload = {"valid_codes": valid_codes_list}
        topic = f"lockers/{wall_id}/cmd/sync_whitelist"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Full whitelist ({len(valid_codes_list)} codes) synced to wall {wall_id}")

    send_access_code_email(db_user.email, db_user.name, new_pin)

    return {
        "success": True,
        "message": f"New code emailed to {db_user.email}",
        "debug_pin": new_pin,
    }