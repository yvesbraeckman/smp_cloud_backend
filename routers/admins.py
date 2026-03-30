"""
Router: Beheerders (Admins) & Instellingen
==========================================
Dit bestand regelt het beheer van de dashboard-accounts.
Hier kan een admin zijn eigen profiel of wachtwoord aanpassen,
en kunnen (super)admins nieuwe collega's toevoegen of verwijderen.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Any

# Importeer de database en modellen
from database import get_db
import models
import schemas

# Belangrijk: Importeer de auth functies en hashing logic
from routers.auth import get_current_user, pwd_context 

# Prefix voor alle routes in dit bestand
router = APIRouter(prefix="/api/admins")


@router.get(
    "/me", 
    response_model=schemas.AdminResponse,
    summary="Mijn profiel ophalen",
    response_description="De gegevens van de ingelogde admin."
)
def get_my_profile(current_admin: models.Admin = Depends(get_current_user)) -> Any:
    """
    Haalt de profielgegevens op van de beheerder die de request uitvoert.
    Vereist een geldig JWT token.
    """
    return current_admin


@router.put(
    "/me", 
    response_model=schemas.AdminResponse,
    summary="Mijn profiel bijwerken",
    response_description="De bijgewerkte profielgegevens."
)
def update_my_profile(
    profile_data: schemas.AdminUpdate, 
    db: Session = Depends(get_db), 
    current_admin: models.Admin = Depends(get_current_user)
) -> Any:
    """
    Werkt de persoonlijke gegevens (naam, email, telefoon) van de ingelogde beheerder bij.
    Controleert of het nieuwe e-mailadres niet al door een andere beheerder in gebruik is.
    """
    # Check of het e-mailadres niet door een ándere admin in gebruik is
    if profile_data.email != current_admin.email:
        existing_admin = db.query(models.Admin).filter(models.Admin.email == profile_data.email).first()
        if existing_admin:
            raise HTTPException(status_code=400, detail="E-mailadres is al in gebruik door een andere beheerder.")
    
    current_admin.name = profile_data.name
    current_admin.email = profile_data.email
    current_admin.phone = profile_data.phone
    
    db.commit()
    db.refresh(current_admin)
    return current_admin


@router.put(
    "/me/password",
    summary="Mijn wachtwoord wijzigen",
    response_description="Succesmelding van de wachtwoordwijziging."
)
def update_my_password(
    passwords: schemas.PasswordUpdate, 
    db: Session = Depends(get_db), 
    current_admin: models.Admin = Depends(get_current_user)
) -> dict:
    """
    Wijzigt het wachtwoord van de ingelogde beheerder.
    Vereist dat het huidige wachtwoord correct wordt meegegeven ter verificatie.
    """
    # Gebruik pwd_context.verify uit auth.py
    if not pwd_context.verify(passwords.current_password, current_admin.password_hash):
        raise HTTPException(status_code=400, detail="Huidig wachtwoord is onjuist.")
    
    # Hash het nieuwe wachtwoord en sla op
    current_admin.password_hash = pwd_context.hash(passwords.new_password)
    db.commit()
    
    return {"detail": "Wachtwoord succesvol gewijzigd."}


@router.get(
    "", 
    response_model=List[schemas.AdminResponse],
    summary="Alle beheerders ophalen",
    response_description="Lijst met alle admins in het systeem."
)
def get_all_admins(
    db: Session = Depends(get_db), 
    current_admin: models.Admin = Depends(get_current_user)
) -> Any:
    """
    Haalt een lijst van alle beheerders op. 
    Wordt gebruikt in het dashboard voor het beheer van collega-accounts.
    """
    return db.query(models.Admin).all()


@router.post(
    "", 
    response_model=schemas.AdminResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Nieuwe beheerder aanmaken",
    response_description="De nieuw aangemaakte admin."
)
def create_admin(
    admin_data: schemas.AdminCreate, 
    db: Session = Depends(get_db), 
    current_admin: models.Admin = Depends(get_current_user)
) -> Any:
    """
    Voegt een nieuwe beheerder toe aan het systeem.
    """
    existing_admin = db.query(models.Admin).filter(models.Admin.email == admin_data.email).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="E-mailadres is al in gebruik.")

    # Hash het nieuwe wachtwoord
    hashed_pw = pwd_context.hash(admin_data.password)
    
    new_admin = models.Admin(
        name=admin_data.name,
        email=admin_data.email,
        phone=admin_data.phone,
        password_hash=hashed_pw,
        role=admin_data.role
    )
    
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    
    return new_admin


@router.delete(
    "/{admin_id}", 
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Beheerder verwijderen (Alleen Superadmin)",
    response_description="Geen content (204) bij succes."
)
def delete_admin(
    admin_id: int, 
    db: Session = Depends(get_db), 
    current_admin: models.Admin = Depends(get_current_user)
) -> None:
    """
    Verwijdert een beheerder uit de database.
    **Let op:** Dit is beveiligd. Alleen accounts met de rol `superadmin`
    mogen andere beheerders verwijderen.
    """
    
    # 1. Beveiliging: Check of de ingelogde admin een superadmin is
    if current_admin.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Actie geweigerd: Alleen een superadmin mag beheerders verwijderen."
        )
        
    # 2. Beveiliging: Je mag jezelf niet per ongeluk verwijderen
    if current_admin.id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Je kunt je eigen account niet verwijderen."
        )
        
    admin_to_delete = db.query(models.Admin).filter(models.Admin.id == admin_id).first()
    if not admin_to_delete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Beheerder niet gevonden.")
        
    db.delete(admin_to_delete)
    db.commit()
    return None