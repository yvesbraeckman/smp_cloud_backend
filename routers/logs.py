"""
Router: Systeem Logboek (Audit Logs)
====================================
Dit bestand handelt alle interacties met het systeemlogboek af.
Hier kunnen gebeurtenissen worden opgeslagen (door de admin of de hardware),
en kunnen beheerders de logs inzien, filteren of exporteren naar CSV.
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

# Prefix voor alle log-routes
router = APIRouter(prefix="/api/logs")

# ==========================================
# LOKALE SCHEMA'S
# ==========================================
class LogCreateRequest(BaseModel):
    """Schema voor het handmatig wegschrijven van een log-regel vanuit het dashboard."""
    location_id: Optional[int] = Field(None, description="ID van de muur (indien locatiespecifiek)")
    locker_id: Optional[int] = Field(None, description="ID van de specifieke kluis")
    event_type: str = Field(..., description="Type event (bv. ADMIN_ACTION of ALARM)", examples=["ADMIN_ACTION"])
    severity: str = Field(..., description="Ernst van de melding (INFO, WARNING, CRITICAL)", examples=["WARNING"])
    description: str = Field(..., description="Details van wat er is gebeurd", examples=["Kluis in onderhoud gezet door admin."])

# ==========================================
# HULPFUNCTIES
# ==========================================
def get_filtered_logs_query(
    db: Session,
    log_date: Optional[date] = None,
    location_id: Optional[int] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None
) -> Any:
    """
    Bouwt dynamisch de SQLAlchemy query op voor het filteren van logs.
    Door dit centraal te doen, hebben de 'lijst' en 'export' endpoints altijd
    exact dezelfde filter-logica.
    """
    query = db.query(models.AuditLog)

    # Filter op specifieke locatie
    if location_id:
        query = query.filter(models.AuditLog.location_id == location_id)

    # Filter op een specifieke datum (negeert de tijdstippen)
    if log_date:
        query = query.filter(cast(models.AuditLog.timestamp, Date) == log_date)

    # Filter op de ernst van het event (INFO, WARNING, CRITICAL)
    if severity:
        query = query.filter(models.AuditLog.severity.ilike(severity))

    # Zoekbalk: check of de term voorkomt in de beschrijving of het type
    if search:
        query = query.filter(
            models.AuditLog.description.ilike(f"%{search}%") |
            models.AuditLog.event_type.ilike(f"%{search}%")
        )

    # Sorteer altijd nieuwste eerst
    return query.order_by(desc(models.AuditLog.timestamp))

# ==========================================
# ENDPOINTS
# ==========================================

@router.post(
    "", 
    response_model=schemas.LogResponse,
    summary="Nieuwe log toevoegen",
    response_description="De zojuist opgeslagen log-regel."
)
def create_log(request: LogCreateRequest, db: Session = Depends(get_db)) -> Any:
    """
    Schrijft direct een nieuwe gebeurtenis weg in het systeemlogboek.
    Wordt voornamelijk gebruikt door het dashboard om beheerders-acties te loggen
    (zoals het geforceerd openen van een deur).
    """
    new_log = models.AuditLog(
        location_id=request.location_id,
        locker_id=request.locker_id,
        event_type=request.event_type,
        severity=request.severity,
        description=request.description,
        timestamp=datetime.utcnow()  # Tijdstip van opslaan
    )
    
    db.add(new_log)
    db.commit()
    db.refresh(new_log)
    
    return new_log


@router.get(
    "", 
    response_model=List[schemas.LogResponse],
    summary="Logs ophalen en filteren",
    response_description="Een lijst met log-regels gebaseerd op de filters."
)
def get_logs(
    log_date: Optional[date] = Query(None, alias="date", description="Filter op specifieke datum (YYYY-MM-DD)"),
    location_id: Optional[int] = Query(None, description="Filter op kluiswand ID"),
    severity: Optional[str] = Query(None, alias="type", description="Filter op ernst (INFO, WARNING, CRITICAL)"),
    search: Optional[str] = Query(None, description="Zoek in de beschrijving"),
    limit: int = Query(50, ge=1, le=500, description="Aantal resultaten (max 500)"),
    db: Session = Depends(get_db)
) -> List[dict]:
    """
    Haalt het logboek op. Gebruikt een efficiënte dictionary-lookup voor locatienamen
    om te voorkomen dat de database per log-regel apart bevraagd moet worden.
    """
    query = get_filtered_logs_query(db, log_date, location_id, severity, search)
    logs = query.limit(limit).all()
    
    # Haal alle locaties in één keer op (Optimalisatie: 1 query i.p.v. N query's)
    locations = {loc.id: loc.name for loc in db.query(models.Location).all()}
    
    result = []
    for log in logs:
        # Koppel de locatienaam razendsnel via de dictionary in het geheugen
        loc_name = locations.get(log.location_id) if log.location_id else None
                    
        result.append({
            "id": log.id,
            "locker_id": log.locker_id,
            "location_name": loc_name,
            "event_type": log.event_type,
            "severity": log.severity,
            "description": log.description,
            "timestamp": log.timestamp
        })
        
    return result


@router.get(
    "/export",
    summary="Exporteer logs naar CSV",
    response_description="Een downloadbaar CSV-bestand met de log-gegevens."
)
def export_logs(
    log_date: Optional[date] = Query(None, alias="date"),
    location_id: Optional[int] = None,
    severity: Optional[str] = Query(None, alias="type"),
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """
    Genereert een dynamisch CSV-bestand op basis van de huidige filter-instellingen.
    In plaats van JSON terug te geven, streamt deze route een tekstbestand rechtstreeks
    naar de browser van de beheerder.
    """
    query = get_filtered_logs_query(db, log_date, location_id, severity, search)
    logs = query.all()
    
    # Haal ook hier alle locaties efficiënt op voor de export
    locations = {loc.id: loc.name for loc in db.query(models.Location).all()}

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    
    # Schrijf de header-rij van de CSV
    writer.writerow(["ID", "Tijdstip", "Locatie & Kluis", "Type", "Ernst", "Beschrijving"])
    
    for log in logs:
        # Bepaal format voor de weergavekolom (Bv: "Residentie De Zwaan (Kluis 12)" of "Systeem")
        loc_name = "Systeem"
        if log.location_id:
            base_name = locations.get(log.location_id, "Onbekende Muur")
            if log.locker_id:
                loc_name = f"{base_name} (Kluis {log.locker_id})"
            else:
                loc_name = base_name

        # Schrijf de rij weg
        writer.writerow([
            log.id,
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            loc_name,
            log.event_type,
            log.severity,
            log.description
        ])

    output.seek(0)
    
    # StreamingResponse vertelt de browser dat er een bestand aankomt (download-prompt)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=smartwall_logs_export.csv"}
    )