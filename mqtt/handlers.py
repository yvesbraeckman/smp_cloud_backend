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

def send_return_email(recipient_email: str, recipient_name: str, barcode: str, carrier: str):
    """
    Stuurt een HTML e-mail ter bevestiging van een retourzending.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] E-mail instellingen ontbreken in .env!")
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg['To'] = recipient_email
    msg['Subject'] = f"Je retour via {carrier} is geregistreerd"
    
    html_body = f"""
    <html>
      <body style="font-family: -apple-system, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2>Beste {recipient_name},</h2>
        <p>Je retourpakket is succesvol veiliggesteld in de Smart Parcel Wall.</p>
        
        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px;">
            <p style="margin: 0 0 10px 0;"><strong>Vervoerder:</strong> {carrier}</p>
            <p style="margin: 0;"><strong>Tracking/Referentie:</strong> {barcode}</p>
        </div>

        <p>De koerier pikt het pakket zo snel mogelijk op. Je hoeft verder niets te doen!</p>
        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">Met vriendelijke groet,<br>Het Smart Parcel Wall Systeem</p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)
        print(f"[EMAIL INFO] Succesvol retour e-mail verstuurd naar {recipient_email}")
    except Exception as e:
        print(f"[EMAIL ERROR] Fout bij verzenden van e-mail naar {recipient_email}: {e}")


def send_delivery_email(recipient_email: str, recipient_name: str, raw_pin: str, barcode: str, carrier: str):
    """
    Stuurt een HTML e-mail naar de bewoner met de afhaal-PIN en een ingesloten QR-code.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    
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
            return

        # ==========================================
        # NIEUW: IDEMPOTENTIE CHECK (Voorkom dubbele mails)
        # ==========================================
        existing_parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.tracking_code == barcode,
            models.Parcel.status == "Delivered"
        ).first()

        if existing_parcel:
            print(f"[MQTT] ⚠️ Duplicaat event genegeerd: Pakket {barcode} ligt al in kluis {locker_id}.")
            return
        # ==========================================
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
        # Parse the timestamp if provided, otherwise use current UTC time
        from datetime import datetime as dt_type, timezone
        import re
        
        if event_time:
            # Try to parse ISO format timestamp string
            try:
                # Remove timezone info for SQLite support (SQLite doesn't store timezone)
                if '+' in str(event_time) or 'Z' in str(event_time):
                    # Remove timezone suffix
                    ts_str = re.sub(r'[+-][0-9]{2}:[0-9]{2}$|Z$', '', str(event_time))
                    timestamp = dt_type.fromisoformat(ts_str)
                else:
                    timestamp = dt_type.fromisoformat(str(event_time))
            except (ValueError, TypeError):
                # Fallback to current time
                timestamp = dt_type.now(timezone.utc)
        else:
            timestamp = dt_type.now(timezone.utc)
            
        new_log = models.AuditLog(
            location_id=int(location_id), 
            locker_id=locker_id,
            event_type="LEVERING",
            severity="INFO",
            description=f"Pakket voor bewoner {resident.name if resident else user_id} afgeleverd door {carrier}.",
            timestamp=timestamp
        )
        db.add(new_log)
        
        # Sla alles in 1x veilig op in de database
        db.commit()
        print(f"[MQTT SUCCESS] Pakket opgeslagen in cloud database.")
        
        # 7. Stuur de GEHASHTE pincode terug naar de muur zodat de bewoner hem kan openen
        # 7. Haal de VOLLEDIGE whitelist op voor deze muur en stuur die door
        # We zoeken alle pakketten op deze locatie die de status 'Delivered' hebben
        all_active_parcels = db.query(models.Parcel).join(models.Locker).filter(
            models.Locker.location_id == int(location_id),
            models.Parcel.status == "Delivered"
        ).all()

        # Groepeer de kluisjes per hash-code
        valid_codes_dict = {}
        for p in all_active_parcels:
            if p.pincode: # Alleen pakketjes met een actieve code
                if p.pincode not in valid_codes_dict:
                    valid_codes_dict[p.pincode] = []
                valid_codes_dict[p.pincode].append(p.locker_id)

        # Maak de lijst voor de Edge
        valid_codes_list = [
            {"hash": h, "locker_ids": ids} for h, ids in valid_codes_dict.items()
        ]

        sync_payload = {"valid_codes": valid_codes_list}
        client.publish(f"lockers/{location_id}/cmd/sync_whitelist", json.dumps(sync_payload), qos=1)
        
        print(f"[MQTT PUSH] Volledige whitelist ({len(valid_codes_list)} codes) gestuurd naar kluiswand {location_id}.")
        
    except Exception as e:
        print(f"[MQTT FATAL] Fout in handle_delivery: {e}")
        db.rollback() # Voorkom dat de database in een fout-staat blijft hangen
    finally:
        db.close()


def handle_pickup(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """
    Verwerkt de afhaling van een pakket door een bewoner.
    Topic: lockers/{location_id}/events/pickup
    
    Markeert het pakket als opgehaald, geeft de kluis weer vrij en logt de gebeurtenis inclusief naam.
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
        
        user_name = "Onbekende bewoner"
        
        if parcel:
            parcel.status = "PickedUp"
            parcel.picked_up_at = datetime.utcnow()
            
            # Zoek de bijbehorende bewoner op via de user_id van het pakket
            if parcel.user_id:
                resident = db.query(models.User).filter(models.User.id == parcel.user_id).first()
                if resident:
                    user_name = resident.name
        # ==========================================
        # NIEUW: Breek af als het pakket al is opgehaald!
        # ==========================================
        else:
            print(f"[MQTT] ⚠️ Duplicaat pickup event genegeerd voor kluis {locker_id}. Pakket is al weg.")
        # ==========================================
        
        # 2. Update de kluis status naar beschikbaar
        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if locker:
            locker.status = "Available"
            
        # 3. Bouw een gedetailleerde log-beschrijving op met de naam van de bewoner
        if parcel:
            desc = f"Pakket opgehaald door {user_name}. Authenticatie via {method}."
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
        
    except Exception as e:
        print(f"[MQTT FATAL] Fout in handle_pickup: {e}")
        db.rollback()
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


def handle_return(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """
    Verwerkt een nieuw retourpakket dat door een bewoner in de kluis is gelegd.
    """
    locker_id = payload.get("locker_id")
    barcode = payload.get("barcode", "Onbekend")
    carrier = payload.get("carrier", "Onbekend")
    user_id = payload.get("user_id")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))
    
    db = SessionLocal()
    try:
        print(f"[MQTT] Retour ontvangen voor kluis {locker_id}. Barcode: {barcode}")

        # 1. Check of kluis bestaat
        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if not locker:
            print(f"[MQTT ERROR] Kluis {locker_id} bestaat niet.")
            return

        # ==========================================
        # NIEUW: IDEMPOTENTIE CHECK (Voorkom dubbele mails)
        # ==========================================
        existing_return = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.tracking_code == barcode,
            models.Parcel.status == "AwaitingCourier"
        ).first()

        if existing_return:
            print(f"[MQTT] ⚠️ Duplicaat event genegeerd: Retour {barcode} wacht al in kluis {locker_id}.")
            return
        # ==========================================

        # 2. Maak het pakket aan met status 'AwaitingCourier' (of 'Return')
        new_parcel = models.Parcel(
            tracking_code=barcode,
            locker_id=locker_id,
            courier=carrier,
            status="AwaitingCourier", # Speciale status zodat we weten dat de koerier dit nog moet halen
            user_id=user_id,
            pincode=None # Geen PIN nodig voor de bewoner
        )
        db.add(new_parcel)
        
        # 3. Zet kluis op bezet
        locker.status = "Return"
            
        # 4. Zoek de bewoner en stuur mail
        resident = db.query(models.User).filter(models.User.id == user_id).first()
        if resident:
            send_return_email(resident.email, resident.name, barcode, carrier)
            
        # 5. Schrijf weg in het Systeem Logboek
        new_log = models.AuditLog(
            location_id=int(location_id), 
            locker_id=locker_id,
            event_type="RETOUR_AANGEMELD",
            severity="INFO",
            description=f"Retour voor {carrier} geplaatst door {resident.name if resident else user_id}.",
            timestamp=event_time
        )
        db.add(new_log)
        
        db.commit()
        print(f"[MQTT SUCCESS] Retour succesvol opgeslagen in cloud database.")
        
    except Exception as e:
        print(f"[MQTT FATAL] Fout in handle_return: {e}")
        db.rollback()
    finally:
        db.close()


def handle_collect(client: mqtt.Client, location_id: str, payload: dict) -> None:
    """
    Verwerkt de afhaling van een retourpakket door een koerierdienst.
    """
    locker_id = payload.get("locker_id")
    carrier = payload.get("carrier", "Onbekend")
    event_time = parse_mqtt_timestamp(payload.get("timestamp"))
    
    db = SessionLocal()
    try:
        print(f"[MQTT] Koerier {carrier} heeft retour in kluis {locker_id} opgehaald.")
        
        # 1. Zoek het retourpakket
        parcel = db.query(models.Parcel).filter(
            models.Parcel.locker_id == locker_id,
            models.Parcel.status == "AwaitingCourier"
        ).first()
        
        if parcel:
            parcel.status = "PickedUp" # Het pakket is nu definitief weg
            parcel.picked_up_at = event_time
        # ==========================================
        # NIEUW: Breek af als het pakket al is opgehaald!
        # ==========================================
        else:
            print(f"[MQTT] ⚠️ Duplicaat collect event genegeerd voor kluis {locker_id}.")
        # ==========================================
        
        # 2. Zet de kluis weer op beschikbaar voor de volgende!
        locker = db.query(models.Locker).filter(models.Locker.id == locker_id).first()
        if locker:
            locker.status = "Available"
            
        # 3. Logboek
        if parcel:
            new_log = models.AuditLog(
                location_id=int(location_id),
                locker_id=locker_id,
                event_type="RETOUR_OPGEHAALD",
                severity="INFO",
                description=f"Retourpakket succesvol opgehaald door koerier ({carrier}).",
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
    """
    lockers_state = payload.get("lockers_state", {})
    
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)

        # 1. NIEUW: Update de muur DIRECT zodat deze online is
        location = db.query(models.Location).filter(models.Location.id == int(location_id)).first()
        if location:
            location.last_heartbeat = now_utc
            
        # 2. Update de status van elk individueel deurtje (zoals je al deed)
        for l_id, door_status in lockers_state.items():
            locker = db.query(models.Locker).filter(
                models.Locker.id == int(l_id),
                models.Locker.location_id == int(location_id)
            ).first()
            
            if locker:
                locker.shadow_state = {
                    "door": door_status, 
                    "last_seen": str(now_utc)
                }
                
        db.commit()
    finally:
        db.close()


def handle_request_sync(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    print(f"[MQTT] Opstart-verzoek ontvangen van locatie {location_id}. Data verzamelen...")
    db = SessionLocal()
    try:
        users = db.query(models.User).filter(models.User.location_id == int(location_id)).all()
        user_list = [{"id": u.id, "name": u.name, "email": u.email, "unit_number": u.unit_number} for u in users]
        
        lockers = db.query(models.Locker).filter(models.Locker.location_id == int(location_id)).all()
        locker_list = []
        
        for l in lockers:
            active_parcel = db.query(models.Parcel).filter(
                models.Parcel.locker_id == l.id,
                models.Parcel.status.in_(["Delivered", "AwaitingCourier"])            
            ).order_by(models.Parcel.id.desc()).first()
            
            # --- SLIMME STATUS LOGICA ---
            if active_parcel:
                if active_parcel.status == "AwaitingCourier":
                    sync_status = "Return"
                else:
                    sync_status = "Occupied"
            else:
                sync_status = "Available"
            
            # 🚨 CRITIAL FIX: Sla de berekende status daadwerkelijk op in de Cloud DB!
            if l.status != sync_status:
                l.status = sync_status
                
            locker_list.append({
                "id": l.id, 
                "size": l.size, 
                "door_number": l.door_number,
                "status": sync_status, 
                "current_code_hash": active_parcel.pincode if active_parcel else None,
                "carrier": active_parcel.courier if active_parcel else None,
                "current_barcode": active_parcel.tracking_code if active_parcel else None
            })
            
        # 🚨 CRITICAL FIX: Commit de wijzigingen aan de lockers tabel!
        db.commit() 
        
        sync_payload = {
            "users": user_list,
            "lockers": locker_list
        }
        
        client.publish(f"lockers/{location_id}/cmd/sync_users", json.dumps(sync_payload), qos=1)
        print(f"[MQTT] ⬇ Full sync verstuurd en Cloud DB hersteld.")
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


def handle_flush_complete(client: mqtt.Client, location_id: str, payload: Dict[str, Any]) -> None:
    """
    Wordt aangeroepen wanneer de kluiswand (Edge) na een internetstoring 
    al zijn offline gebufferde events heeft doorgestuurd. 
    De Cloud bevestigt dat alles is verwerkt met een 'sync_ready' ACK.
    """
    print(f"[MQTT] ✅ 'Flush complete' ontvangen van locatie {location_id}. Wachtrij is leeg!")
    
    # Stuur de ACK terug naar de specifieke kluiswand
    ack_topic = f"lockers/{location_id}/cmd/sync_ready"
    ack_payload = {
        "status": "ready",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    client.publish(ack_topic, payload=json.dumps(ack_payload), qos=1)
    print(f"[MQTT] ⬆ 'sync_ready' (ACK) commando verzonden naar kluiswand {location_id}")