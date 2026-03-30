"""
Database Modellen
=================
Dit bestand bevat de SQLAlchemy ORM modellen.
Elke class representeert een tabel in de PostgreSQL database.
"""

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from database import Base

class Location(Base):
    """
    Representeert een fysieke locatie waar één of meerdere Smart Parcel Walls staan.
    Bv: 'Residentie de Zwaan'. Dient als het hoofdniveau (parent) voor kluisjes en bewoners.
    """
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, doc="De weergavenaam van de kluiswand op het dashboard.")
    address = Column(String, doc="Het fysieke adres waar de kluiswand is geïnstalleerd.")
    api_key = Column(String, doc="Beveiligingssleutel voor authenticatie/Zero-Touch Provisioning van de Edge Node (Raspberry Pi).")

    # Relaties (1-op-veel) met cascade
    # Cascade zorgt ervoor dat als een Location wordt verwijderd, de bijbehorende kluisjes en gebruikers ook verdwijnen.
    lockers = relationship("Locker", back_populates="location", cascade="all, delete-orphan")
    users = relationship("User", back_populates="location", cascade="all, delete-orphan")


class Locker(Base):
    """
    Representeert één individueel kluisje binnen een fysieke kluiswand (Location).
    Houdt zowel de configuratie als de digitale status (Digital Twin) bij.
    """
    __tablename__ = "lockers"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), doc="Verwijst naar de fysieke muur (Location.id).")
    door_number = Column(Integer, nullable=False, doc="De hardware pin/id op de Edge Node (bv. pin 1 voor deurtje 1).")
    size = Column(String, doc="Het formaat van het kluisje. Mogelijke waarden: 'S', 'M', 'L'.")
    shadow_state = Column(JSONB, doc="Digital Twin data gesynchroniseerd via MQTT: bevat zaken als {'door': 'closed', 'last_seen': '...'} .")
    status = Column(String, default="Available", doc="De logische status. Mogelijke waarden: 'Available', 'Occupied', 'Maintenance', 'Error'.")

    # Relaties
    location = relationship("Location", back_populates="lockers")
    parcels = relationship("Parcel", back_populates="locker", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="locker", cascade="all, delete-orphan")


class User(Base):
    """
    Representeert een Bewoner (Resident) van een gebouw die pakketten kan ontvangen in de kluiswand.
    Let op: Dit is géén dashboard-beheerder (zie het Admin model daarvoor).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), doc="De kluiswand waar deze bewoner aan gekoppeld is.")
    name = Column(String, doc="Volledige naam van de bewoner.")
    email = Column(String, unique=True, index=True, doc="E-mailadres voor ontvangst van afhaal-PIN en QR-code.")
    unit_number = Column(String, doc="Appartementsnummer, bv. 'Bus 12' of 'Apt 4B'.")
    phone = Column(String, nullable=True, doc="Optioneel telefoonnummer voor SMS notificaties.")

    # Relaties
    location = relationship("Location", back_populates="users")
    parcels = relationship("Parcel", back_populates="user")


class Parcel(Base):
    """
    Representeert een fysiek pakket dat is afgeleverd in een specifieke kluis.
    Koppelt een levering aan een Bewoner (User) en een Kluis (Locker).
    """
    __tablename__ = "parcels"

    id = Column(Integer, primary_key=True, index=True)
    tracking_code = Column(String, index=True, doc="De barcode gescand door de koerier.")
    user_id = Column(Integer, ForeignKey("users.id"), doc="Verwijzing naar de bewoner voor wie dit pakket is.")
    locker_id = Column(Integer, ForeignKey("lockers.id"), doc="Het specifieke kluisje waar het pakket in ligt.")
    courier = Column(String, doc="Naam van de bezorgdienst, bv: 'bpost', 'PostNL', 'DHL'.")
    pincode = Column(String, doc="De gehashte unieke afhaalcode voor dit pakket.")
    status = Column(String, default="Delivered", doc="Huidige status van het pakket. Mogelijke waarden: 'Delivered', 'PickedUp', 'Returned'.")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), doc="Tijdstip van levering door de koerier.")
    picked_up_at = Column(DateTime(timezone=True), nullable=True, doc="Tijdstip waarop de bewoner de kluis heeft geopend.")

    # Relaties
    user = relationship("User", back_populates="parcels")
    locker = relationship("Locker", back_populates="parcels")


class AuditLog(Base):
    """
    Systeem logboek (Telemetry & Events). Houdt een chronologische audittrail bij van alle 
    hardware-acties, waarschuwingen, en beheerdersacties via het Angular dashboard.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    location_id = Column(Integer, ForeignKey("locations.id"), nullable=True, doc="De locatie waar het event plaatsvond.")
    locker_id = Column(Integer, ForeignKey("lockers.id"), nullable=True, doc="Optionele specifieke kluis waar het event over gaat.")
    event_type = Column(String, doc="Categorie van het event, bv: 'ALARM', 'LEVERING', 'OPHALING', 'ADMIN_ACTION'.")
    severity = Column(String, default="INFO", doc="Ernst van de melding. Waarden: 'INFO', 'WARNING', 'CRITICAL'.")
    description = Column(String, doc="Menselijk leesbare beschrijving van de gebeurtenis.")
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), doc="Exact tijdstip van het event, geparst uit de MQTT payload.")

    # Relaties
    locker = relationship("Locker", back_populates="audit_logs")


class Admin(Base):
    """
    Representeert een Systeembeheerder die inlogt op het Angular Cloud Dashboard.
    Dit model handelt de eigenlijke authenticatie, rollen en beveiliging af.
    """
    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, doc="Naam van de beheerder.")
    email = Column(String(255), unique=True, index=True, nullable=False, doc="Login e-mailadres.")
    password_hash = Column(String(255), nullable=False, doc="Veilig gehashte wachtwoord string.")
    
    # Instellingen
    phone = Column(String(255), nullable=True, doc="Telefoonnummer voor eventuele 2FA of contact.")
    role = Column(String(50), default="admin", doc="Rechtenniveau in het dashboard. Waarden: 'admin', 'superadmin'.")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), doc="Datum waarop dit account is aangemaakt.")