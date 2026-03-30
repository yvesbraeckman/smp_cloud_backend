"""
API Schema's (Pydantic Modellen)
================================
Dit bestand bevat de datastructuren voor inkomende en uitgaande API-verzoeken.
Deze modellen zorgen voor automatische data-validatie en genereren de OpenAPI documentatie.
"""

from pydantic import BaseModel, ConfigDict, Field, EmailStr
from typing import Optional, List, Dict, Any
from datetime import datetime


# ==========================================
# STANDAARD TABELLEN (Kluizen & Pakketten)
# ==========================================

class LockerBase(BaseModel):
    """Basis eigenschappen van een kluis."""
    door_number: int = Field(..., description="Fysieke poort op de Pi")
    size: str = Field(..., description="Formaat van de kluis", examples=["S", "M", "L"])
    status: str = Field(..., description="Huidige status van de kluis", examples=["Available", "Occupied", "Maintenance"])
    shadow_state: Optional[Dict[str, Any]] = Field(None, description="Huidige fysieke vs gewenste status (IoT Twin)")

class LockerResponse(LockerBase):
    """Volledige data van een kluis zoals teruggestuurd door de API."""
    id: int = Field(..., description="Uniek kluis ID", examples=[12])
    location_id: int = Field(..., description="ID van de muur/locatie waar deze in zit", examples=[1])
    
    model_config = ConfigDict(from_attributes=True)

class ParcelResponse(BaseModel):
    """Data van een afgeleverd pakket."""
    id: int
    tracking_code: str = Field(..., description="Unieke tracking code van de koerier", examples=["3SBP123456789"])
    courier: str = Field(..., description="Naam van de koerier", examples=["bpost", "PostNL", "DHL"])
    status: str = Field(..., description="Status van het pakket", examples=["Delivered", "PickedUp"])
    pincode: Optional[str] = Field(None, description="De geheime afhaalcode voor de bewoner")
    created_at: datetime
    picked_up_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# DASHBOARD: WALLS & LOCATIONS
# ==========================================

class WallListResponse(BaseModel):
    """Beknopt overzicht van een kluiswand voor de dashboard lijst."""
    id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["Residentie De Zwaan"])
    status: str = Field(..., description="Huidige connectiviteit", examples=["ONLINE", "OFFLINE"])
    occupancy: str = Field(..., description="Bezetting als breuk", examples=["9/20"])
    active_alarms: int = Field(..., description="Aantal onopgeloste waarschuwingen", examples=[0])
    last_sync: Optional[datetime] = Field(None, description="Laatste heartbeat van de RPi")

class WallDetailResponse(BaseModel):
    """Uitgebreide data van een kluiswand inclusief alle onderliggende kluizen."""
    location_id: int
    name: str
    status: str
    last_sync: Optional[datetime] = None
    lockers: List[LockerResponse] = Field(..., description="Lijst van alle kluizen in deze muur")

class LockerDetailResponse(BaseModel):
    """Gedetailleerde weergave van één specifieke kluis (zijpaneel in dashboard)."""
    id: int
    status: str
    size: str
    shadow_state: Optional[Dict[str, Any]] = None
    
    # Gekoppeld pakket info
    parcel_id: Optional[int] = Field(None, description="ID van het pakket indien bezet")
    parcel_status: Optional[str] = None
    courier: Optional[str] = None
    delivery_time: Optional[datetime] = None
    
    # Gekoppelde bewoner info
    resident_name: Optional[str] = Field(None, examples=["Yves Braeckman"])
    resident_unit: Optional[str] = Field(None, examples=["Bus 12A"])


# ==========================================
# ACTIES & REQUESTS (Hardware & Status)
# ==========================================

class RemoteUnlockRequest(BaseModel):
    """Data nodig om een kluis op afstand te forceren/openen."""
    location_id: int = Field(..., description="ID van de kluiswand", examples=[1])
    locker_id: int = Field(..., description="ID van het specifieke deurtje", examples=[5])
    reason: str = Field(..., description="Reden voor het openen", examples=["Admin Override"])

class ServiceModeRequest(BaseModel):
    """Data nodig om een kluis in of uit onderhoud te halen."""
    locker_id: int = Field(..., examples=[5])
    status: str = Field(..., description="De nieuwe status", examples=["Maintenance", "Available"])


# ==========================================
# DASHBOARD: BEWONERS (RESIDENTS)
# ==========================================

class ResidentBase(BaseModel):
    """Basis data voor een bewoner."""
    name: str = Field(..., description="Volledige naam", examples=["Jan Peeters"])
    email: EmailStr = Field(..., description="E-mail voor notificaties", examples=["jan@voorbeeld.be"])
    unit_number: str = Field(..., description="Appartementsnummer/Bus", examples=["101", "Bus 3"])
    phone: str = Field(..., description="Telefoonnummer", examples=["+32400123456"])
    location_id: int = Field(..., description="Aan welke kluiswand is deze persoon gekoppeld?", examples=[1])

class ResidentCreate(ResidentBase):
    """Schema voor het aanmaken van een nieuwe bewoner (POST)."""
    pass

class ResidentUpdate(BaseModel):
    """Schema voor het bewerken van een bewoner (PUT). Alles is optioneel."""
    name: Optional[str] = Field(None, examples=["Jan Peeters"])
    email: Optional[EmailStr] = Field(None, examples=["jan.nieuw@voorbeeld.be"])
    unit_number: Optional[str] = Field(None, examples=["101B"])
    phone: Optional[str] = Field(None, examples=["+32400123456"])
    location_id: Optional[int] = Field(None, examples=[1])

class ResidentResponse(ResidentBase):
    """Bewoner data inclusief database ID (GET)."""
    id: int
    model_config = ConfigDict(from_attributes=True)

class ResidentPaginatedResponse(BaseModel):
    """Gepagineerde lijst van bewoners voor de datatable."""
    items: List[ResidentResponse]
    total: int = Field(..., description="Totaal aantal bewoners in de database")
    page: int = Field(..., description="Huidige pagina", examples=[1])
    limit: int = Field(..., description="Aantal items per pagina", examples=[10])


# ==========================================
# DASHBOARD: LOGS & AUDIT
# ==========================================

class LogResponse(BaseModel):
    """Een enkele regel in het systeem logboek."""
    id: int
    locker_id: Optional[int] = Field(None, description="Gekoppelde kluis indien van toepassing")
    location_name: Optional[str] = Field(None, description="Naam van de muur", examples=["Residentie De Zwaan"])
    event_type: str = Field(..., description="Type gebeurtenis", examples=["ADMIN_ACTION", "ALARM"])
    severity: str = Field(..., description="Ernst van de melding", examples=["INFO", "WARNING", "CRITICAL"])
    description: str = Field(..., description="Menselijke beschrijving van het event", examples=["Kluis geforceerd geopend."])
    timestamp: datetime
    
    model_config = ConfigDict(from_attributes=True)


# ==========================================
# DASHBOARD: KPIS
# ==========================================

class DashboardKPIs(BaseModel):
    """De kerncijfers voor de blokken bovenaan het dashboard."""
    parcels_today: int = Field(..., description="Aantal geleverde pakketten vandaag", examples=[42])
    active_walls: int = Field(..., description="Aantal online muren", examples=[3])
    total_walls: int = Field(..., description="Totaal aantal muren", examples=[3])
    offline_locations: int = Field(..., description="Aantal muren dat geen verbinding heeft", examples=[0])
    open_errors: int = Field(..., description="Aantal onopgeloste technische fouten", examples=[1])


# ==========================================
# AUTHENTICATIE & VEILIGHEID
# ==========================================

class LoginRequest(BaseModel):
    """Data verwacht bij het inloggen."""
    email: EmailStr = Field(..., examples=["admin@smartparcelwall.be"])
    password: str = Field(..., examples=["JouwGeheimeWachtwoord123!"])

class TokenResponse(BaseModel):
    """De JWT token die wordt teruggegeven na succesvol inloggen."""
    access_token: str = Field(..., description="De Bearer token voor verdere API calls")
    token_type: str = Field("bearer")
    user: Dict[str, Any] = Field(..., description="Beknopte profiel-info van de ingelogde admin")

class ForgotPasswordRequest(BaseModel):
    """Data nodig voor het aanvragen van een wachtwoord-reset."""
    email: EmailStr = Field(..., examples=["admin@smartparcelwall.be"])

class ResetPasswordRequest(BaseModel):
    """Data nodig voor het instellen van een nieuw wachtwoord."""
    token: str = Field(..., description="De JWT token uit de reset-link in de e-mail")
    new_password: str = Field(..., description="Het nieuwe, veilige wachtwoord", examples=["NieuwWachtwoord456!"])


# ==========================================
# DASHBOARD: ADMINS & SETTINGS
# ==========================================

class AdminResponse(BaseModel):
    """Data van een beheerder zoals teruggestuurd door de API."""
    id: int = Field(..., examples=[1])
    name: str = Field(..., examples=["Yves Braeckman"])
    email: EmailStr = Field(..., examples=["admin@smartparcelwall.be"])
    phone: Optional[str] = Field(None, examples=["+32400123456"])
    role: str = Field(..., examples=["admin", "superadmin"])

    model_config = ConfigDict(from_attributes=True)

class AdminUpdate(BaseModel):
    """Data om een bestaand beheerder-profiel bij te werken."""
    name: str = Field(..., examples=["Yves Braeckman"])
    email: EmailStr = Field(..., examples=["admin@smartparcelwall.be"])
    phone: Optional[str] = Field(None, examples=["+32400123456"])

class PasswordUpdate(BaseModel):
    """Data voor het wijzigen van een wachtwoord via het profiel."""
    current_password: str = Field(..., examples=["OudeWachtwoord123!"])
    new_password: str = Field(..., examples=["NieuweVeiligeWachtwoord456!"])

class AdminCreate(BaseModel):
    """Data voor het aanmaken van een nieuwe beheerder."""
    name: str = Field(..., examples=["Nieuwe Beheerder"])
    email: EmailStr = Field(..., examples=["nieuw@voorbeeld.be"])
    phone: Optional[str] = Field(None, examples=["+32400123456"])
    password: str = Field(..., description="Tijdelijk wachtwoord voor de nieuwe admin")
    role: str = Field("admin", description="Rol in het systeem (admin of superadmin)")

class LockerCreate(BaseModel):
    """Configuratie voor een individueel kluisje bij het aanmaken van een nieuwe muur."""
    door_number: int = Field(..., description="Het fysieke relais-nummer op de hardware (1, 2, 3...)")
    size: str = Field(..., description="Grootte van het kluisje", examples=["S", "M", "L"])

class WallCreateRequest(BaseModel):
    """De complete payload die Angular stuurt bij het aanmaken van een nieuwe kluiswand."""
    name: str = Field(..., description="Naam van de nieuwe locatie", examples=["Residentie De Zwaan"])
    address: str = Field(..., description="Adres van de locatie", examples=["Dorpsstraat 1, Kontich"])
    lockers: List[LockerCreate] = Field(..., description="De lijst met kluisjes en hun fysieke formaten")