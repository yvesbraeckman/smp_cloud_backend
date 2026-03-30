"""
Router: Authenticatie & Beveiliging
===================================
Dit bestand handelt alle login-processen, JWT-token validatie en
wachtwoord-reset flows (inclusief e-mail) af voor de beheerders.
"""

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import jwt
import datetime
from typing import Optional, Any
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

import models
import schemas
from database import get_db

# Prefix voor alle routes in dit bestand
router = APIRouter(prefix="/api")

# ==========================================
# SECURITY CONFIGURATIE
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token"), 
    db: Session = Depends(get_db)
) -> models.Admin:
    """
    FastAPI Dependency die controleert of het meegestuurde JWT-token geldig is.
    Wordt gebruikt in andere routes om te garanderen dat de bezoeker is ingelogd.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Niet ingelogd")
    
    token = authorization.split(" ")[1]
    
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id = payload.get("sub")
        admin = db.query(models.Admin).filter(models.Admin.id == int(admin_id)).first()
        
        if not admin:
            raise HTTPException(status_code=401, detail="Gebruiker niet gevonden")
        return admin
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Sessie is verlopen")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Ongeldig token")


@router.post(
    "/auth/login", 
    response_model=schemas.TokenResponse,
    summary="Beheerder inloggen",
    response_description="De JWT access-token en profielinformatie."
)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)) -> Any:
    """
    Controleert de e-mail en het wachtwoord van een beheerder.
    Bij succes wordt er een JWT-token gegenereerd dat 24 uur geldig is.
    """
    admin = db.query(models.Admin).filter(models.Admin.email == request.email).first()
    
    # Check of admin bestaat EN of wachtwoord klopt (via bcrypt hash)
    if not admin or not pwd_context.verify(request.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="E-mail of wachtwoord onjuist")
    
    # Maak de JWT Token (Geldig voor 24 uur)
    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    token_data = {"sub": str(admin.id), "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "access_token": token,
        "user": {"id": admin.id, "name": admin.name, "email": admin.email}
    }


@router.post(
    "/auth/logout",
    summary="Beheerder uitloggen",
    response_description="Succesmelding."
)
def logout() -> dict:
    """
    Uitloggen in een stateless (JWT) applicatie gebeurt voornamelijk aan de frontend
    (het wissen van de token uit de localStorage). Deze route bevestigt enkel de actie.
    """
    return {"success": True, "message": "Succesvol uitgelogd"}


@router.post(
    "/auth/forgot-password",
    summary="Wachtwoord reset aanvragen",
    response_description="Bevestiging dat de flow gestart is (geeft altijd succes terug om datalekken te voorkomen)."
)
def forgot_password(request: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """
    Start de wachtwoord-reset flow. Als het e-mailadres bestaat, wordt er
    een unieke en tijdelijke JWT link gemaild naar de beheerder.
    """
    admin = db.query(models.Admin).filter(models.Admin.email == request.email).first()
    
    # We sturen alleen een mail als de admin echt bestaat
    if admin:
        # 1. Maak een speciaal 'Reset Token' (Geldig voor 15 minuten)
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
        reset_token_data = {"sub": str(admin.id), "exp": expire, "type": "reset"}
        reset_token = jwt.encode(reset_token_data, SECRET_KEY, algorithm=ALGORITHM)
        
        # 2. Bepaal de link naar je frontend
        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:4200")
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"
        
       # ==========================================
        # 3. E-MAIL INSTELLINGEN (Nu via .env)
        # ==========================================
        SENDER_EMAIL = os.getenv("SENDER_EMAIL")
        SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
        SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.resend.com")
        SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
        
        msg = MIMEMultipart()
        msg['From'] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
        msg['To'] = admin.email
        msg['Subject'] = "Wachtwoord Reset Aanvraag"
        
        body = f"""Beste {admin.name},

Je hebt aangegeven dat je je wachtwoord bent vergeten.
Klik op de onderstaande link om een nieuw wachtwoord in te stellen:

{reset_link}

Let op: Deze link is slechts 15 minuten geldig. Heb je dit niet aangevraagd? Dan kun je deze e-mail veilig negeren.

Met vriendelijke groet,
Het Smart Parcel Wall Systeem
"""
        msg.attach(MIMEText(body, 'plain'))
        
        # 4. Verstuur de e-mail via SMTP
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT) 
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception as e:
            # Print de error in de terminal, maar crash de app niet
            print(f"Fout bij verzenden van e-mail naar {admin.email}: {e}")
            
    # Veiligheidsmaatregel: Zeg niet of de mail bestond of niet.
    return {"success": True, "message": f"Als {request.email} bij ons bekend is, is er een reset-link verstuurd."}


@router.post(
    "/auth/reset-password",
    summary="Nieuw wachtwoord instellen",
    response_description="Succesmelding dat het wachtwoord is aangepast."
)
def reset_password(request: schemas.ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """
    Verifieert het reset-token en slaat het nieuwe, gehashte wachtwoord op in de database.
    """
    try:
        # 1. Ontsleutel het token
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])
        
        # 2. Check of het écht een reset-token is (en geen gestolen login-token)
        if payload.get("type") != "reset":
            raise HTTPException(status_code=400, detail="Ongeldig type token.")
            
        admin_id = payload.get("sub")
        admin = db.query(models.Admin).filter(models.Admin.id == int(admin_id)).first()
        
        if not admin:
            raise HTTPException(status_code=404, detail="Beheerder niet gevonden.")
            
        # 3. Hash het nieuwe wachtwoord en sla op
        admin.password_hash = pwd_context.hash(request.new_password)
        db.commit()
        
        return {"success": True, "message": "Wachtwoord succesvol gewijzigd."}
        
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Deze reset-link is verlopen. Vraag een nieuwe aan.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Ongeldige of corrupte reset-link.")


@router.get(
    "/user/me",
    summary="Huidig profiel ophalen",
    response_description="Profielgegevens van de ingelogde admin."
)
def get_me(current_user: models.Admin = Depends(get_current_user)) -> dict:
    """
    Haalt de gegevens op van de beheerder die op dit moment is ingelogd.
    Deze route is beveiligd: je moet een geldige Bearer token meesturen.
    """
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "avatar": f"https://ui-avatars.com/api/?name={current_user.name.replace(' ', '+')}&background=random"
    }