"""
Router: Bewoners (Residents)
============================
Dit bestand bevat alle API-endpoints voor het beheren van bewoners.
Hier vind je de CRUD-operaties die het 
Angular dashboard gebruikt om de bewonerslijst te beheren.
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

# --- NIEUWE IMPORTS VOOR E-MAIL ---
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
# ----------------------------------

from routers.auth import get_current_user

# Prefix voor alle routes in dit bestand
router = APIRouter(
    prefix="/api/residents",
    dependencies=[Depends(get_current_user)]
)
# ==========================================
# HELPER: E-MAIL VERZENDEN
# ==========================================
def send_access_code_email(recipient_email: str, recipient_name: str, pin_code: str):
    """
    Stuurt een HTML e-mail naar de bewoner met de nieuw gegenereerde toegangscode.
    """
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
    SMTP_SERVER = os.getenv("SMTP_SERVER")
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("[EMAIL ERROR] E-mail instellingen ontbreken in .env!")
        return

    msg = MIMEMultipart('alternative')
    msg['From'] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
    msg['To'] = recipient_email
    msg['Subject'] = "Je nieuwe toegangscode voor de Smart Parcel Wall"
    
    html_body = f"""
    <html>
      <body style="font-family: -apple-system, sans-serif; color: #1d1d1f; line-height: 1.6;">
        <h2>Beste {recipient_name},</h2>
        <p>De beheerder heeft zojuist een nieuwe toegangscode voor je gegenereerd.</p>
        
        <div style="background-color: #f5f5f7; padding: 20px; border-radius: 12px; margin: 20px 0; max-width: 400px; text-align: center;">
            <p style="margin: 0; font-size: 14px; color: #86868b; text-transform: uppercase; letter-spacing: 1px; font-weight: 600;">Jouw Pincode</p>
            <p style="margin: 10px 0 0 0; font-size: 36px; font-weight: bold; color: #0a84ff; letter-spacing: 6px;">{pin_code}</p>
        </div>

        <p>Je kunt deze code direct gebruiken op het scherm van de kluiswand om je pakketten op te halen.</p>
        
        <p style="color: #86868b; font-size: 14px; margin-top: 30px;">
            Met vriendelijke groet,<br>
            Het Smart Parcel Wall Systeem
        </p>
      </body>
    </html>
    """
    
    msg.attach(MIMEText(html_body, 'html'))
    
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login("resend", SENDER_PASSWORD) # Zelfde login als bij je andere mails
            server.send_message(msg)
            
        print(f"[EMAIL INFO] Succesvol toegangscode e-mail verstuurd naar {recipient_email}")
        
    except Exception as e:
        print(f"[EMAIL ERROR] Fout bij verzenden van e-mail naar {recipient_email}: {e}")

# ==========================================
# ENDPOINTS
# ==========================================

@router.get(
    "", 
    response_model=schemas.ResidentPaginatedResponse,
    summary="Bewoners ophalen (met zoekfunctie & paginering)"
)
def get_residents(
    search: Optional[str] = Query(None, description="Zoek op naam, e-mail, busnummer of locatie"),
    page: int = Query(1, ge=1, description="Huidige pagina (start bij 1)"),
    limit: int = Query(10, ge=1, le=100, description="Aantal bewoners per pagina (max 100)"),
    db: Session = Depends(get_db)
) -> Any:
    
    query = db.query(models.User).outerjoin(
        models.Location, models.User.location_id == models.Location.id
    )
    
    if search:
        query = query.filter(
            models.User.name.ilike(f"%{search}%") | 
            models.User.email.ilike(f"%{search}%") |
            models.User.unit_number.ilike(f"%{search}%") |
            models.Location.name.ilike(f"%{search}%")
        )
    
    total_records = query.count()
    offset = (page - 1) * limit
    users = query.offset(offset).limit(limit).all()
    
    return {
        "items": users,
        "total": total_records,
        "page": page,
        "limit": limit
    }


@router.post(
    "", 
    response_model=schemas.ResidentResponse,
    summary="Nieuwe bewoner aanmaken"
)
def create_resident(resident: schemas.ResidentCreate, db: Session = Depends(get_db)) -> Any:
    if db.query(models.User).filter(models.User.email == resident.email).first():
        raise HTTPException(status_code=400, detail="E-mailadres is al in gebruik")
        
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
                "unit_number": new_user.unit_number
            }]
        }
        
        topic = f"lockers/{new_user.location_id}/cmd/sync_users"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Nieuwe bewoner (ID: {new_user.id}) direct gepusht naar muur {new_user.location_id}")
        
    return new_user


@router.put(
    "/{resident_id}", 
    response_model=schemas.ResidentResponse,
    summary="Bewoner bewerken"
)
def update_resident(
    resident_id: int, 
    resident: schemas.ResidentUpdate, 
    db: Session = Depends(get_db)
) -> Any:
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")
    
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
                "unit_number": db_user.unit_number
            }]
        }
        
        topic = f"lockers/{db_user.location_id}/cmd/sync_users"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Bewoner (ID: {db_user.id}) update gepusht naar muur {db_user.location_id}")

    return db_user


@router.delete(
    "/{resident_id}",
    summary="Bewoner verwijderen"
)
def delete_resident(resident_id: int, db: Session = Depends(get_db)) -> dict:
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")

    location_id = db_user.location_id
    res_name = db_user.name
    
    db.delete(db_user)
    db.commit()
    
    if location_id:
        delete_payload = {
            "resident_id": resident_id
        }
        topic = f"lockers/{location_id}/cmd/delete_user"
        mqtt_client.publish(topic, json.dumps(delete_payload), qos=1)
        print(f"[API] Delete-commando voor bewoner {res_name} (ID: {resident_id}) gepusht naar muur {location_id}")
    
    return {"success": True, "message": f"Bewoner {db_user.name} is succesvol verwijderd."}


@router.post(
    "/{resident_id}/credentials/generate",
    summary="Toegangscode genereren"
)
def generate_credentials(resident_id: int, db: Session = Depends(get_db)) -> dict:
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")
        
    # 1. Zoek alle pakketjes die momenteel op DEZE bewoner wachten
    active_user_parcels = db.query(models.Parcel).filter(
        models.Parcel.user_id == resident_id,
        models.Parcel.status == "Delivered"
    ).all()

    if not active_user_parcels:
        raise HTTPException(
            status_code=400, 
            detail="Deze bewoner heeft momenteel geen pakketjes in de kluis liggen."
        )

    # 2. Genereer een nieuwe pincode en hash deze
    new_pin = str(random.randint(100000, 999999))
    hashed_pin = pwd_context.hash(new_pin)

    # 3. Koppel de nieuwe code aan de pakketten in de cloud database
    for parcel in active_user_parcels:
        parcel.pincode = hashed_pin
    
    db.commit()

    # 4. Haal NU alle actieve pakketten op voor de HELE MUUR om de whitelist te bouwen
    # (Omdat de Raspberry Pi zijn hele geheugen wist bij een sync_whitelist commando!)
    wall_id = db_user.location_id
    if wall_id:
        all_active_parcels_on_wall = db.query(models.Parcel).join(models.Locker).filter(
            models.Locker.location_id == wall_id,
            models.Parcel.status == "Delivered"
        ).all()

        # Groepeer de kluisjes per hash-code (want 1 code kan meerdere deurtjes openen)
        valid_codes_dict = {}
        for p in all_active_parcels_on_wall:
            if p.pincode not in valid_codes_dict:
                valid_codes_dict[p.pincode] = []
            valid_codes_dict[p.pincode].append(p.locker_id)

        # Zet het om in het formaat dat de Raspberry Pi verwacht
        valid_codes_list = [
            {"hash": code_hash, "locker_ids": l_ids} 
            for code_hash, l_ids in valid_codes_dict.items()
        ]

        # 5. Push de complete up-to-date whitelist naar de kluiswand
        sync_payload = {"valid_codes": valid_codes_list}
        topic = f"lockers/{wall_id}/cmd/sync_whitelist"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Complete whitelist ({len(valid_codes_list)} codes) gesynchroniseerd met muur {wall_id}")

    # 6. E-mail versturen naar de bewoner
    send_access_code_email(db_user.email, db_user.name, new_pin)

    return {
        "success": True, 
        "message": f"Nieuwe code succesvol gemaild naar {db_user.email}",
        "debug_pin": new_pin
    }