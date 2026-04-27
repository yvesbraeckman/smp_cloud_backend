"""
MQTT Event Handlers
====================

Processes incoming MQTT messages from the locker walls (Raspberry Pi).
When the edge device publishes an event or sensor data, the payload is
unpacked here and persisted to PostgreSQL.
"""

import json
import random
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from datetime import datetime, timezone
from typing import Dict, Any
from io import BytesIO

import paho.mqtt.client as mqtt
import qrcode
from passlib.context import CryptContext

from database import SessionLocal
import models

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def parse_mqtt_timestamp(ts_string: str | None) -> datetime:
    """Parse an ISO-8601 timestamp string from an MQTT payload.

    Strips timezone info so the result is compatible with SQLite (which does
    not store timezone metadata). Falls back to the current UTC time on any
    parse failure.

    Args:
        ts_string: ISO-8601 timestamp, or None.

    Returns:
        A naive ``datetime`` representing the parsed time, or UTC now.
    """
    if not ts_string:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(ts_string.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


# ==========================================
# Email helpers
# ==========================================

def send_return_email(recipient_email: str, recipient_name: str, barcode: str, carrier: str):
    """Send an HTML confirmation email for a return shipment.

    Args:
        recipient_email: Resident's email address.
        recipient_name: Resident's display name.
        barcode: Tracking / reference barcode of the return parcel.
        carrier: Courier service handling the return.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] Email credentials missing in environment.")
        return

    msg = MIMEMultipart("alternative")
    msg["From"] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg["To"] = recipient_email
    msg["Subject"] = f"Your return via {carrier} has been registered"

    html_body = f"""
    <html>
      <body style="font-family: -apple-system, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2>Dear {recipient_name},</h2>
        <p>Your return parcel has been secured in the Smart Parcel Wall.</p>

        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px;">
            <p style="margin: 0 0 10px 0;"><strong>Carrier:</strong> {carrier}</p>
            <p style="margin: 0;"><strong>Tracking / Reference:</strong> {barcode}</p>
        </div>

        <p>The courier will pick it up as soon as possible. No further action needed on your part!</p>
        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">Kind regards,<br>The Smart Parcel Wall System</p>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)
        print(f"[EMAIL INFO] Return email sent successfully to {recipient_email}")
    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send return email to {recipient_email}: {e}")


def send_delivery_email(recipient_email: str, recipient_name: str, raw_pin: str, barcode: str, carrier: str):
    """Send an HTML email to the resident with the pickup PIN and an inline QR code.

    Args:
        recipient_email: Resident's email address.
        recipient_name: Resident's display name.
        raw_pin: The raw (plaintext) pickup PIN.
        barcode: Tracking barcode of the parcel.
        carrier: Courier that delivered the parcel.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] Email credentials missing in environment.")
        return

    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(raw_pin)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = BytesIO()
    img.save(img_buffer, format="PNG")
    img_data = img_buffer.getvalue()

    msg = MIMEMultipart("related")
    msg["From"] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg["To"] = recipient_email
    msg["Subject"] = f"A parcel from {carrier} has been delivered!"

    html_body = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2 style="color: #1d1d1f;">Dear {recipient_name},</h2>
        <p>A parcel has just been delivered to the Smart Parcel Wall for you!</p>

        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px;">
            <p style="margin: 0 0 10px 0;"><strong>Courier:</strong> {carrier}</p>
            <p style="margin: 0;"><strong>Barcode:</strong> {barcode}</p>
        </div>

        <p>You can collect your parcel using the PIN below, or by scanning the QR code at the wall:</p>

        <h1 style="font-size: 32px; letter-spacing: 4px; color: #0071e3; margin: 10px 0;">{raw_pin}</h1>

        <img src="cid:qr_code" alt="QR Code" style="width: 200px; height: 200px; border-radius: 8px; border: 1px solid #d1d1d6;">

        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">
            Kind regards,<br>
            The Smart Parcel Wall System
        </p>
      </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    image = MIMEImage(img_data, name="qrcode.png")
    image.add_header("Content-ID", "<qr_code>")
    image.add_header("Content-Disposition", "inline", filename="qrcode.png")
    msg.attach(image)

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)

        print(f"[EMAIL INFO] Delivery email with QR sent successfully to {recipient_email}")

    except Exception as e:
        print(f"[EMAIL ERROR] Failed to send delivery email to {recipient_email}: {e}")


# ==========================================
# Event handlers
# ==========================================

def handle_delivery(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """Process a new parcel delivery.

    Validates the locker, checks for duplicate events (idempotency), generates a
    random PIN, persists the parcel, marks the locker as occupied, emails the
    resident, writes an audit log, and pushes the full whitelist of valid codes
    back to the locker wall so the edge device can authorise door openings.

    Topic: ``lockers/{location_id}/events/delivery``

    Args:
        client: MQTT client (used to publish the whitelist back).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with keys ``locker_id``, ``barcode``, ``carrier``,
                 ``user_id``, and optionally ``timestamp``.
    """
    locker_id = payload.get("locker_id")
    barcode = payload.get("barcode", "Unknown")
    carrier = payload.get("carrier", "Unknown")
    user_id = payload.get("user_id")
    event_time = payload.get("timestamp")

    db = SessionLocal()
    try:
        print(f"[MQTT] Delivery received for locker {locker_id}. Barcode: {barcode}")

        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if not locker:
            print(f"[MQTT ERROR] Locker {locker_id} does not exist in cloud database.")
            return

        # Idempotency check — prevent duplicate emails and double-creation
        existing_parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.tracking_code == barcode,
            models.Parcel.status == "Delivered",
        ).first()

        if existing_parcel:
            print(f"[MQTT] Duplicate event ignored: parcel {barcode} already in locker {locker_id}.")
            return

        # Generate a random 6-digit PIN and store the bcrypt hash
        raw_pin = str(random.randint(100000, 999999))
        hashed_pin = pwd_context.hash(raw_pin)

        new_parcel = models.Parcel(
            tracking_code=barcode,
            locker_id=locker_id,
            courier=carrier,
            pincode=hashed_pin,
            status="Delivered",
            user_id=user_id,
        )
        db.add(new_parcel)

        locker.status = "Occupied"

        # Look up the resident who was selected at the touch screen
        resident = db.query(models.User).filter(models.User.id == user_id).first()
        if resident:
            print(f"[MQTT EMAIL] Sending email to {resident.name} ({resident.email}) with PIN: {raw_pin}")
            send_delivery_email(resident.email, resident.name, raw_pin, barcode, carrier)
        else:
            print(f"[MQTT WARNING] Resident with ID {user_id} not found in cloud database.")

        # Parse the event timestamp (strip TZ for SQLite), fallback to UTC now
        import re
        if event_time:
            try:
                if "+" in str(event_time) or "Z" in str(event_time):
                    ts_str = re.sub(r"[+-][0-9]{2}:[0-9]{2}$|Z$", "", str(event_time))
                    timestamp = datetime.fromisoformat(ts_str)
                else:
                    timestamp = datetime.fromisoformat(str(event_time))
            except (ValueError, TypeError):
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        new_log = models.AuditLog(
            location_id=int(location_id),
            locker_id=locker_id,
            event_type="LEVERING",
            severity="INFO",
            description=f"Parcel for resident {resident.name if resident else user_id} delivered by {carrier}.",
            timestamp=timestamp,
        )
        db.add(new_log)

        db.commit()
        print("[MQTT SUCCESS] Parcel saved in cloud database.")

        # Push the full whitelist back to the locker wall so the edge device
        # can verify door-opening codes locally without round-trips.
        all_active_parcels = (
            db.query(models.Parcel)
            .join(models.Locker)
            .filter(
                models.Locker.location_id == int(location_id),
                models.Parcel.status == "Delivered",
            )
            .all()
        )

        valid_codes_dict = {}
        for p in all_active_parcels:
            if p.pincode:
                if p.pincode not in valid_codes_dict:
                    valid_codes_dict[p.pincode] = []
                valid_codes_dict[p.pincode].append(p.locker_id)

        valid_codes_list = [
            {"hash": h, "locker_ids": ids} for h, ids in valid_codes_dict.items()
        ]

        sync_payload = {"valid_codes": valid_codes_list}
        client.publish(f"lockers/{location_id}/cmd/sync_whitelist", json.dumps(sync_payload), qos=1)

        print(f"[MQTT PUSH] Full whitelist ({len(valid_codes_list)} codes) pushed to wall {location_id}.")

    except Exception as e:
        print(f"[MQTT FATAL] Error in handle_delivery: {e}")
        db.rollback()
    finally:
        db.close()


def handle_pickup(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """Process a parcel pickup by a resident.

    Marks the parcel as picked up, frees the locker, and writes an audit log
    including the resident's name and the authentication method used.

    Topic: ``lockers/{location_id}/events/pickup``

    Args:
        client: MQTT client (unused but kept for handler interface consistency).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with keys ``locker_id``, ``method``, and optionally
                 ``duration_seconds`` and ``timestamp``.
    """
    locker_id = payload.get("locker_id")
    method = payload.get("method", "unknown")
    duration = payload.get("duration_seconds")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))

    db = SessionLocal()
    try:
        print(f"[MQTT] Pickup: locker {locker_id} emptied via {method}.")

        # NIEUWE CODE IN DE CLOUD (handle_pickup):
        parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.status.in_(["Delivered", "AwaitingCourier"]) # Checkt ze nu allebei!
        ).first()
        
        user_name = "Unknown resident"

        if parcel:
            parcel.status = "PickedUp"
            parcel.picked_up_at = datetime.utcnow()

            if parcel.user_id:
                resident = db.query(models.User).filter(models.User.id == parcel.user_id).first()
                if resident:
                    user_name = resident.name
        else:
            # Duplicate pickup event — parcel was already picked up
            print(f"[MQTT] Duplicate pickup event ignored for locker {locker_id}.")

        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if locker:
            locker.status = "Available"

        if parcel:
            desc = f"Parcel picked up by {user_name}. Authentication via {method}."
            if duration:
                desc += f" (Door open for {duration}s)"

            new_log = models.AuditLog(
                location_id=int(location_id),
                locker_id=locker_id,
                event_type="OPHALING",
                severity="INFO",
                description=desc,
                timestamp=event_time,
            )
            db.add(new_log)

        db.commit()

    except Exception as e:
        print(f"[MQTT FATAL] Error in handle_pickup: {e}")
        db.rollback()
    finally:
        db.close()


def handle_alarm(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """Process a hardware alarm or error (e.g. door left open too long).

    Topic: ``lockers/{location_id}/events/alarm``

    Args:
        client: MQTT client (unused).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with keys ``severity``, ``locker_id``,
                 ``msg``, and optionally ``timestamp``.
    """
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))
    severity = payload.get("severity", "WARNING")
    locker_id = payload.get("locker_id")
    msg = payload.get("msg", "Unknown alarm")

    db = SessionLocal()
    try:
        print(f"[MQTT] ALARM at location {location_id}, locker {locker_id}: {msg}")

        new_log = models.AuditLog(
            location_id=int(location_id),
            locker_id=locker_id,
            event_type="ALARM",
            severity=severity,
            description=msg,
            timestamp=event_time,
        )
        db.add(new_log)
        db.commit()

    finally:
        db.close()


def handle_return(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """Process a return parcel placed by a resident.

    Validates the locker, idempotency check against duplicate events, creates
    the parcel with status ``AwaitingCourier``, sets the locker to Return,
    emails the resident, and writes an audit log.

    Topic: ``lockers/{location_id}/events/return``

    Args:
        client: MQTT client (unused).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with keys ``locker_id``, ``barcode``,
                 ``carrier``, ``user_id``, and optionally ``timestamp``.
    """
    locker_id = payload.get("locker_id")
    barcode = payload.get("barcode", "Unknown")
    carrier = payload.get("carrier", "Unknown")
    user_id = payload.get("user_id")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))

    db = SessionLocal()
    try:
        print(f"[MQTT] Return received for locker {locker_id}. Barcode: {barcode}")

        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if not locker:
            print(f"[MQTT ERROR] Locker {locker_id} does not exist.")
            return

        # Idempotency check — avoid duplicate emails and duplicate parcels
        existing_return = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.tracking_code == barcode,
            models.Parcel.status == "AwaitingCourier",
        ).first()

        if existing_return:
            print(f"[MQTT] Duplicate event ignored: return {barcode} already in locker {locker_id}.")
            return

        new_parcel = models.Parcel(
            tracking_code=barcode,
            locker_id=locker_id,
            courier=carrier,
            status="AwaitingCourier",
            user_id=user_id,
            pincode=None,
        )
        db.add(new_parcel)

        locker.status = "Return"

        resident = db.query(models.User).filter(models.User.id == user_id).first()
        if resident:
            send_return_email(resident.email, resident.name, barcode, carrier)

        new_log = models.AuditLog(
            location_id=int(location_id),
            locker_id=locker_id,
            event_type="RETOUR_AANGEMELD",
            severity="INFO",
            description=f"Return for {carrier} placed by {resident.name if resident else user_id}.",
            timestamp=event_time,
        )
        db.add(new_log)

        db.commit()
        print("[MQTT SUCCESS] Return saved in cloud database.")

    except Exception as e:
        print(f"[MQTT FATAL] Error in handle_return: {e}")
        db.rollback()
    finally:
        db.close()


def handle_collect(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """Process a courier collecting a return parcel.

    Marks the parcel as picked up, frees the locker, and writes an audit log.

    Topic: ``lockers/{location_id}/events/collect``

    Args:
        client: MQTT client (unused).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with keys ``locker_id``, ``carrier``, and
                 optionally ``timestamp``.
    """
    locker_id = payload.get("locker_id")
    carrier = payload.get("carrier", "Unknown")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))

    db = SessionLocal()
    try:
        print(f"[MQTT] Courier {carrier} collected return from locker {locker_id}.")

        parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.status == "AwaitingCourier",
        ).first()

        if parcel:
            parcel.status = "PickedUp"
            parcel.picked_up_at = event_time
        else:
            # Duplicate collect — already picked up
            print(f"[MQTT] Duplicate collect event ignored for locker {locker_id}.")

        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if locker:
            locker.status = "Available"

        if parcel:
            new_log = models.AuditLog(
                location_id=int(location_id),
                locker_id=locker_id,
                event_type="RETOUR_OPGEHAALD",
                severity="INFO",
                description=f"Return parcel collected by courier ({carrier}).",
                timestamp=event_time,
            )
            db.add(new_log)

        db.commit()

    finally:
        db.close()


# ==========================================
# Telemetry & sync handlers
# ==========================================

def handle_telemetry(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """Process a periodic heartbeat / telemetry message from a locker wall.

    Updates the location's ``last_heartbeat`` timestamp and each locker's
    ``shadow_state`` (door status + last-seen time) to maintain a digital twin
    of the physical wall state.

    Topic: ``lockers/{location_id}/telemetry``

    Args:
        client: MQTT client (unused).
        location_id: Identifier of the locker wall location.
        payload: JSON payload with key ``lockers_state`` — a dict mapping
                 locker IDs to door status strings.
    """
    lockers_state = payload.get("lockers_state", {})

    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)

        location = db.query(models.Location).filter(models.Location.id == int(location_id)).first()
        if location:
            location.last_heartbeat = now_utc

        for l_id, door_status in lockers_state.items():
            locker = db.query(models.Locker).filter(
                models.Locker.id == int(l_id),
                models.Locker.location_id == int(location_id),
            ).first()

            if locker:
                locker.shadow_state = {
                    "door": door_status,
                    "last_seen": str(now_utc),
                }

        db.commit()
    finally:
        db.close()


def handle_request_sync(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """Handle a full-sync request from a locker wall (typically on startup).

    Gathers all users and lockers for the location, recomputes each locker's
    authoritative status, corrects the cloud database if it has drifted, and
    publishes the complete sync payload back to the wall.

    Topic: ``lockers/{location_id}/events/request_sync``

    Args:
        client: MQTT client (used to publish the sync payload back).
        location_id: Identifier of the locker wall location.
        payload: JSON payload (typically empty or minimal on request).
    """
    print(f"[MQTT] Sync request received from location {location_id}. Gathering data...")
    db = SessionLocal()
    try:
        users = db.query(models.User).filter(models.User.location_id == int(location_id)).all()
        user_list = [{"id": u.id, "name": u.name, "email": u.email, "unit_number": u.unit_number} for u in users]

        lockers = db.query(models.Locker).filter(models.Locker.location_id == int(location_id)).all()
        locker_list = []

        for l in lockers:
            active_parcel = (
                db.query(models.Parcel)
                .filter(
                    models.Parcel.locker_id == l.id,
                    models.Parcel.status.in_(["Delivered", "AwaitingCourier"]),
                )
                .order_by(models.Parcel.id.desc())
                .first()
            )

            # Derive the authoritative locker status from the active parcel
            if active_parcel:
                if active_parcel.status == "AwaitingCourier":
                    sync_status = "Return"
                else:
                    sync_status = "Occupied"
            else:
                sync_status = "Available"

            # Correct cloud DB if it has drifted from the computed status
            if l.status != sync_status:
                l.status = sync_status

            locker_list.append({
                "id": l.id,
                "size": l.size,
                "door_number": l.door_number,
                "status": sync_status,
                "current_code_hash": active_parcel.pincode if active_parcel else None,
                "carrier": active_parcel.courier if active_parcel else None,
                "current_barcode": active_parcel.tracking_code if active_parcel else None,
            })

        # Persist any status corrections to the cloud DB
        db.commit()

        sync_payload = {
            "users": user_list,
            "lockers": locker_list,
        }

        client.publish(f"lockers/{location_id}/cmd/sync_users", json.dumps(sync_payload), qos=1)
        print("[MQTT] Full sync sent and cloud DB corrected.")
    finally:
        db.close()


def push_user_to_edge(user: models.User):
    """Push a single user record to their locker wall over MQTT.

    Used when a user is created or updated in the cloud so the edge device
    stays in sync without waiting for a full sync cycle. Published with QoS 1
    for guaranteed delivery.

    Args:
        user: The User model instance to push.
    """
    payload = {
        "users": [{
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "unit_number": user.unit_number,
        }]
    }
    topic = f"lockers/{user.location_id}/cmd/sync_users"

    mqtt_client.publish(topic, json.dumps(payload), qos=1)
    print(f"[MQTT PUSH] User {user.id} pushed to location {user.location_id}")


def handle_flush_complete(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """Handle the signal that a locker wall has flushed its offline buffer.

    After an internet outage the edge device replays buffered events. Once all
    are replayed it publishes a ``flush_complete`` event. This handler responds
    with a ``sync_ready`` ACK so the wall knows it can resume normal operation.

    Topic: ``lockers/{location_id}/events/flush_complete``
    Response: ``lockers/{location_id}/cmd/sync_ready``

    Args:
        client: MQTT client (used to publish the ACK).
        location_id: Identifier of the locker wall location.
        payload: JSON payload (typically empty).
    """
    print(f"[MQTT] 'Flush complete' received from location {location_id}. Offline queue is empty.")

    ack_topic = f"lockers/{location_id}/cmd/sync_ready"
    ack_payload = {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    client.publish(ack_topic, payload=json.dumps(ack_payload), qos=1)
    print(f"[MQTT] 'sync_ready' ACK sent to wall {location_id}")