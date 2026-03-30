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
from mqtt.client import client as mqtt_client # Of hoe jouw import pad ook heet

# Prefix voor alle routes in dit bestand. 
router = APIRouter(prefix="/api/residents")

@router.get(
    "", 
    response_model=schemas.ResidentPaginatedResponse,
    summary="Bewoners ophalen (met zoekfunctie & paginering)",
    response_description="Geeft een lijst met bewoners en paginatie-metadata terug."
)
def get_residents(
    search: Optional[str] = Query(None, description="Zoek op naam, e-mail, busnummer of locatie"),
    page: int = Query(1, ge=1, description="Huidige pagina (start bij 1)"),
    limit: int = Query(10, ge=1, le=100, description="Aantal bewoners per pagina (max 100)"),
    db: Session = Depends(get_db)
) -> Any:
    """
    Haalt een lijst met bewoners op uit de database.
    
    - **Zoeken**: Filtert resultaten dynamisch op basis van een zoekterm (`search`).
    - **Paginering**: Beperkt de output met `page` en `limit` om de laadtijd van het Angular dashboard kort te houden.
    """
    # NIEUW: We koppelen de Location tabel eraan vast met een outerjoin
    query = db.query(models.User).outerjoin(
        models.Location, models.User.location_id == models.Location.id
    )
    
    # Zoekfunctie: kijk of de zoekterm in de naam, email, busnummer óf locatienaam zit
    if search:
        query = query.filter(
            models.User.name.ilike(f"%{search}%") | 
            models.User.email.ilike(f"%{search}%") |
            models.User.unit_number.ilike(f"%{search}%") |
            models.Location.name.ilike(f"%{search}%") # NIEUW: Zoek in locatienaam
        )
    
    # Paginering berekenen
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
    summary="Nieuwe bewoner aanmaken",
    response_description="De aangemaakte bewoner inclusief database ID."
)
def create_resident(resident: schemas.ResidentCreate, db: Session = Depends(get_db)) -> Any:
    """
    Voegt een nieuwe bewoner toe aan het systeem.
    Controleert vooraf of het e-mailadres niet al door een andere bewoner in gebruik is.
    """
    # Check of email al bestaat
    if db.query(models.User).filter(models.User.email == resident.email).first():
        raise HTTPException(status_code=400, detail="E-mailadres is al in gebruik")
        
    # FIX: We noemen deze nu new_user in plaats van db_user
    new_user = models.User(**resident.model_dump())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Nu kan hij de location_id en andere gegevens perfect uitlezen!
    if new_user.location_id:
        # We sturen een lijstje met maar 1 persoon erin. De Edge gebruikt UPSERT, dus voegt hem netjes toe!
        sync_payload = {
            "users": [{
                "id": new_user.id, 
                "name": new_user.name, 
                "email": new_user.email, 
                "unit_number": new_user.unit_number
            }]
        }
        
        # Publish naar de specifieke muur
        topic = f"lockers/{new_user.location_id}/cmd/sync_users"
        mqtt_client.publish(topic, json.dumps(sync_payload), qos=1)
        print(f"[API] Nieuwe bewoner (ID: {new_user.id}) direct gepusht naar muur {new_user.location_id}")
        
    return new_user


@router.put(
    "/{resident_id}", 
    response_model=schemas.ResidentResponse,
    summary="Bewoner bewerken",
    response_description="De bijgewerkte bewoner data."
)
def update_resident(
    resident_id: int, 
    resident: schemas.ResidentUpdate, 
    db: Session = Depends(get_db)
) -> Any:
    """
    Bewerkt een bestaande bewoner.
    Alleen de velden die worden meegestuurd in de request-body worden aangepast.
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")
    
    # Pas alleen de velden aan die expliciet zijn meegestuurd (exclude_unset=True)
    update_data = resident.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_user, key, value)
        
    db.commit()
    db.refresh(db_user)

    # 2. De "inline" push naar de Edge
    if db_user.location_id:
        # We sturen de nieuwe gegevens door. De Edge doet een UPSERT en overschrijft de oude data.
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
    summary="Bewoner verwijderen",
    response_description="Succesmelding van verwijdering."
)
def delete_resident(resident_id: int, db: Session = Depends(get_db)) -> dict:
    """
    Verwijdert een bewoner permanent uit de database.
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")

    # 1. BELANGRIJK: Gegevens onthouden voor MQTT voordat we hem wissen
    location_id = db_user.location_id
    res_name = db_user.name
    
    db.delete(db_user)
    db.commit()
    # 3. Direct het verwijder-commando pushen naar de juiste muur
    if location_id:
        # We sturen alleen het ID door, de Pi doet de rest
        delete_payload = {
            "resident_id": resident_id
        }
        
        topic = f"lockers/{location_id}/cmd/delete_user"
        mqtt_client.publish(topic, json.dumps(delete_payload), qos=1)
        print(f"[API] Delete-commando voor bewoner {res_name} (ID: {resident_id}) gepusht naar muur {location_id}")
    
    return {"success": True, "message": f"Bewoner {db_user.name} is succesvol verwijderd."}


@router.post(
    "/{resident_id}/credentials/generate",
    summary="Toegangscode genereren",
    response_description="Bevestiging dat de code is verstuurd (inclusief debug pin)."
)
def generate_credentials(resident_id: int, db: Session = Depends(get_db)) -> dict:
    """
    Genereert een eenmalige toegangscode (PIN) voor de bewoner.
    *(In de toekomst zal deze functie gekoppeld worden aan Resend/SendGrid om de code daadwerkelijk te mailen).*
    """
    db_user = db.query(models.User).filter(models.User.id == resident_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="Bewoner niet gevonden")
    
    # Genereer een veilige 6-cijferige pincode
    new_pin = str(random.randint(100000, 999999))
    
    # TODO: Integreer e-mail service (bv. via Resend of SMTP)
    # email_service.send_code(db_user.email, new_pin)

    return {
        "success": True, 
        "message": f"Nieuwe code succesvol gemaild naar {db_user.email}",
        "debug_pin": new_pin  # Let op: verwijder debug_pin in productie!
    }