"""
MQTT Event Handlers
===================
Dit bestand bevat de logica voor het verwerken van binnenkomende MQTT-berichten.
Wanneer de kluiswand (Raspberry Pi) een gebeurtenis of sensordata doorstuurt, 
wordt de payload hier uitgepakt en in de PostgreSQL database verwerkt.
"""

import json
import random
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import Dict, Any
import paho.mqtt.client as mqtt

from passlib.context import CryptContext
from database import SessionLocal
import models
import qrcode
from io import BytesIO
from email.mime.image import MIMEImage

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def parse_mqtt_timestamp(ts_string: str | None) -> datetime:
    if not ts_string:
        return datetime.utcnow()
    try:
        return datetime.fromisoformat(ts_string.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


# ==========================================
# HELPER: E-MAIL VERZENDEN
# ==========================================
def send_delivery_email(recipient_email: str, recipient_name: str, raw_pin: str, barcode: str, carrier: str):
    """
    Stuurt een HTML e-mail naar de bewoner met de afhaal-PIN en een ingesloten QR-code.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT"))
    
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] E-mail instellingen ontbreken in .env!")
        return

    # 1. Genereer de QR code in het werkgeheugen (geen bestand op schijf nodig)
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(raw_pin) # We stoppen de ruwe PIN in de QR code
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    img_buffer = BytesIO()
    img.save(img_buffer, format="PNG")
    img_data = img_buffer.getvalue()

    # 2. Bouw de e-mail op
    msg = MIMEMultipart('related') # 'related' is belangrijk voor inline afbeeldingen
    msg['From'] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg['To'] = recipient_email
    msg['Subject'] = f"Je pakket van {carrier} is geleverd!"
    
    # 3. Maak een mooie HTML body
    html_body = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2 style="color: #1d1d1f;">Beste {recipient_name},</h2>
        <p>Er is zojuist een pakket voor je afgeleverd in de Smart Parcel Wall!</p>
        
        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px;">
            <p style="margin: 0 0 10px 0;"><strong>Koerier:</strong> {carrier}</p>
            <p style="margin: 0;"><strong>Barcode:</strong> {barcode}</p>
        </div>

        <p>Je kunt je pakket ophalen met de onderstaande pincode of door de QR-code te scannen bij de muur:</p>
        
        <h1 style="font-size: 32px; letter-spacing: 4px; color: #0071e3; margin: 10px 0;">{raw_pin}</h1>
        
        <img src="cid:qr_code" alt="QR Code" style="width: 200px; height: 200px; border-radius: 8px; border: 1px solid #d1d1d6;">
        
        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">
            Met vriendelijke groet,<br>
            Het Smart Parcel Wall Systeem
        </p>
      </body>
    </html>
    """
    
    # Voeg de HTML toe aan het bericht
    msg.attach(MIMEText(html_body, 'html'))
    
    # 4. Voeg de QR code afbeelding toe als "inline" bijlage
    image = MIMEImage(img_data, name="qrcode.png")
    image.add_header('Content-ID', '<qr_code>') # Zorg dat deze naam matcht met de cid in de HTML
    image.add_header('Content-Disposition', 'inline', filename="qrcode.png")
    msg.attach(image)
    
    # 5. Verstuur de e-mail (met het veilige 'with' blok!)
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)
            
        print(f"[EMAIL INFO] Succesvol HTML e-mail met QR verstuurd naar {recipient_email}")
        
    except Exception as e:
        print(f"[EMAIL ERROR] Fout bij verzenden van e-mail naar {recipient_email}: {e}")

# ==========================================
# EVENT HANDLERS
# ==========================================
import json
import random
# Zorg dat pwd_context en parse_mqtt_timestamp hierboven ergens geïmporteerd/gedefinieerd zijn!

def handle_delivery(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """
    Verwerkt een nieuw afgeleverd pakket en genereert de PIN.
    """
    locker_id = payload.get("locker_id")
    barcode = payload.get("barcode", "Onbekend")
    carrier = payload.get("carrier", "Onbekend")
    user_id = payload.get("user_id") # <-- BINGO! De bewoner die de koerier koos
    
    # Als je parse_mqtt_timestamp hebt, gebruik die. Anders fallback naar datetime.now()
    event_time = payload.get("timestamp") 
    
    db = SessionLocal()
    try:
        print(f"[MQTT] Delivery ontvangen voor kluis {locker_id}. Barcode: {barcode}")

        # 1. Check of het kluisje wel bestaat in de Cloud!
        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if not locker:
            print(f"[MQTT ERROR] 🚨 Kluis {locker_id} bestaat niet in de cloud database! Maak deze eerst aan.")
            return # We stoppen hier, anders crasht PostgreSQL weer op de Foreign Key!

        # 2. Genereer een ruwe PIN en hash deze
        raw_pin = str(random.randint(100000, 999999))
        hashed_pin = pwd_context.hash(raw_pin)
        
        # 3. Maak het pakket aan
        new_parcel = models.Parcel(
            tracking_code=barcode,
            locker_id=locker_id,
            courier=carrier,
            pincode=hashed_pin,
            status="Delivered",
            user_id=user_id  # <--- DEZE REGEL TOEVOEGEN! (Zonder het # teken)
        )
        # Optioneel: als je Parcel model een user_id heeft, koppel hem!
        # new_parcel.user_id = user_id 
        db.add(new_parcel)
        
        # 4. Zet kluis op bezet
        locker.status = "Occupied"
            
        # 5. Zoek de JUISTE bewoner op basis van de touch-screen keuze van de koerier!
        resident = db.query(models.User).filter(models.User.id == user_id).first()
        if resident:
            print(f"[MQTT EMAIL] ✉️ E-mail triggeren naar {resident.name} ({resident.email}) met PIN: {raw_pin}")
            send_delivery_email(resident.email, resident.name, raw_pin, barcode, carrier)
        else:
            print(f"[MQTT WARNING] ❓ Bewoner met ID {user_id} niet gevonden in de Cloud DB!")
            
        # 6. Schrijf weg in het Systeem Logboek
        new_log = models.AuditLog(
            location_id=int(location_id), 
            locker_id=locker_id,
            event_type="LEVERING",
            severity="INFO",
            description=f"Pakket voor bewoner {resident.name if resident else user_id} afgeleverd door {carrier}.",
            timestamp=event_time
        )
        db.add(new_log)
        
        # Sla alles in 1x veilig op in de database
        db.commit()
        print(f"[MQTT SUCCESS] Pakket opgeslagen in cloud database.")
        
        # 7. Stuur de GEHASHTE pincode terug naar de muur zodat de bewoner hem kan openen
        sync_payload = {
            "valid_codes": [
                {"hash": hashed_pin, "locker_ids": [locker_id]} 
            ]
        }
        client.publish(f"lockers/{location_id}/cmd/sync_whitelist", json.dumps(sync_payload), qos=1)
        print(f"[MQTT PUSH] Pincode hash gestuurd naar de kluiswand.")
        
    except Exception as e:
        print(f"[MQTT FATAL] Fout in handle_delivery: {e}")
        db.rollback() # Voorkom dat de database in een fout-staat blijft hangen
    finally:
        db.close()


def handle_pickup(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """
    Verwerkt de afhaling van een pakket door een bewoner.
    Topic: lockers/{location_id}/events/pickup
    
    Markeert het pakket als opgehaald, geeft de kluis weer vrij en logt de gebeurtenis.
    """
    locker_id = payload.get("locker_id")
    method = payload.get("method", "onbekend")  # Bv: 'PIN' of 'QR'
    duration = payload.get("duration_seconds")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))
    
    db = SessionLocal()
    try:
        print(f"[MQTT] Pickup: Kluis {locker_id} leeggemaakt via {method}.")
        
        # 1. Zoek het afgeleverde pakket in deze kluis
        parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.status == "Delivered"
        ).first()
        
        if parcel:
            parcel.status = "PickedUp"
            parcel.picked_up_at = datetime.utcnow()
        
        # 2. Update de kluis status naar beschikbaar
        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if locker:
            locker.status = "Available"
            
        # 3. Bouw een gedetailleerde log-beschrijving op
        desc = f"Pakket opgehaald. Authenticatie via {method}."
        if duration:
            desc += f" (Deur stond {duration}s open)"
            
        new_log = models.AuditLog(
            location_id=int(location_id),
            locker_id=locker_id,
            event_type="OPHALING",
            severity="INFO",
            description=desc,
            timestamp=event_time
        )
        db.add(new_log)
        db.commit()
        
    finally:
        db.close()


def handle_alarm(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """
    Verwerkt een alarm of foutmelding vanuit de hardware (bijv. deur te lang open).
    Topic: lockers/{location_id}/events/alarm
    """
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))
    severity = payload.get("severity", "WARNING")  # INFO, WARNING, of CRITICAL
    locker_id = payload.get("locker_id")
    msg = payload.get("msg", "Onbekend alarm")
    
    db = SessionLocal()
    try:
        print(f"[MQTT] ALARM op locatie {location_id}, kluis {locker_id}: {msg}")
        
        new_log = models.AuditLog(
            location_id=int(location_id),
            locker_id=locker_id,
            event_type="ALARM",
            severity=severity,
            description=msg,
            timestamp=event_time
        )
        db.add(new_log)
        db.commit()
        
    finally:
        db.close()


# ==========================================
# TELEMETRY HANDLERS (Digital Twin)
# ==========================================

def handle_telemetry(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """
    Verwerkt de periodieke hartslag (telemetry) van de kluiswand.
    Topic: lockers/{location_id}/telemetry
    
    Update de 'Digital Twin' (shadow_state) van de kluizen, zodat het dashboard
    real-time weet of deurtjes fysiek open of dicht zijn, en of de muur online is.
    """
    lockers_state = payload.get("lockers_state", {})
    
    db = SessionLocal()
    try:
        # Loop door de status van elk individueel deurtje heen
        for l_id, door_status in lockers_state.items():
            locker = db.query(models.Locker).filter(
                models.Locker.id == int(l_id),
                models.Locker.location_id == int(location_id)
            ).first()
            
            if locker:
                # Update de Digital Twin JSON
                locker.shadow_state = {
                    "door": door_status, 
                    "last_seen": str(datetime.utcnow())
                }
                
        db.commit()
    finally:
        db.close()


def handle_request_sync(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    print(f"[MQTT] Opstart-verzoek ontvangen van locatie {location_id}. Data verzamelen...")
    db = SessionLocal()
    try:
        # 1. Haal de bewoners op
        users = db.query(models.User).filter(models.User.location_id == int(location_id)).all()
        user_list = [{"id": u.id, "name": u.name, "email": u.email, "unit_number": u.unit_number} for u in users]
        
        # 2. NIEUW: Haal de kluisjes op voor deze muur (inclusief door_number!)
        lockers = db.query(models.Locker).filter(models.Locker.location_id == int(location_id)).all()
        locker_list = []
        
        for l in lockers:
            # Zoek of er momenteel een pakket in dit specifieke kluisje ligt
            active_parcel = db.query(models.Parcel).filter(
                models.Parcel.locker_id == l.id,
                models.Parcel.status == "Delivered"
            ).first()
            
            locker_list.append({
                "id": l.id, 
                "size": l.size, 
                "door_number": l.door_number,
                "status": l.status, # Stuur ook meteen de status mee (Occupied/Available)
                # Als er een pakket is, stuur de hash mee. Anders None.
                "current_code_hash": active_parcel.pincode if active_parcel else None 
            })
        
        # 3. Combineer alles in één dik sync-pakket
        sync_payload = {
            "users": user_list,
            "lockers": locker_list
        }
        
        client.publish(f"lockers/{location_id}/cmd/sync_users", json.dumps(sync_payload), qos=1)
        print(f"[MQTT] ⬇ Full sync verstuurd: {len(user_list)} bewoners & {len(locker_list)} kluisjes.")
    finally:
        db.close()

def push_user_to_edge(user: models.User):
    """ Verstuurt een enkele gebruiker naar de specifieke kluiswand via MQTT """
    payload = {
        "users": [{
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "unit_number": user.unit_number
        }]
    }
    topic = f"lockers/{user.location_id}/cmd/sync_users"
    
    # We sturen dit met QoS 1 zodat we zeker weten dat de Pi het ontvangt
    mqtt_client.publish(topic, json.dumps(payload), qos=1)
    print(f"[MQTT PUSH] Gebruiker {user.id} gepusht naar locatie {user.location_id}")