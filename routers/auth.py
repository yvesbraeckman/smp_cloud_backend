"""
Router: Authentication & Security
==================================

Handles admin login, JWT token validation, and password-reset flows
(including email delivery of reset links).
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

router = APIRouter(prefix="/api")

# ==========================================
# Security configuration
# ==========================================

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_current_user(
    authorization: Optional[str] = Header(None, description="Bearer token"),
    db: Session = Depends(get_db),
) -> models.Admin:
    """FastAPI dependency that validates the Bearer JWT token.

    Decodes the token, looks up the admin in the database, and returns the
    Admin model instance. Used across all protected routes.

    Args:
        authorization: The ``Authorization`` header value (``Bearer <token>``).
        db: SQLAlchemy session.

    Returns:
        The authenticated Admin model.

    Raises:
        HTTPException 401: If the token is missing, expired, or invalid.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.split(" ")[1]

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        admin_id = payload.get("sub")
        admin = db.query(models.Admin).filter(models.Admin.id == int(admin_id)).first()

        if not admin:
            raise HTTPException(status_code=401, detail="User not found")
        return admin

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post(
    "/auth/login",
    response_model=schemas.TokenResponse,
    summary="Admin login",
    response_description="The JWT access token and profile information.",
)
def login(request: schemas.LoginRequest, db: Session = Depends(get_db)) -> Any:
    """Authenticate an admin by email and password.

    On success, returns a JWT valid for 24 hours.

    Args:
        request: Login credentials (email + password).
        db: SQLAlchemy session.

    Returns:
        Dict with ``access_token`` and ``user`` profile.
    """
    admin = db.query(models.Admin).filter(models.Admin.email == request.email).first()

    if not admin or not pwd_context.verify(request.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    token_data = {"sub": str(admin.id), "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)

    return {
        "access_token": token,
        "user": {"id": admin.id, "name": admin.name, "email": admin.email},
    }


@router.post(
    "/auth/logout",
    summary="Admin logout",
    response_description="Success message.",
)
def logout() -> dict:
    """Confirm logout.

    In a stateless JWT architecture the actual token discard happens
    client-side (removing it from localStorage). This endpoint merely
    acknowledges the action.
    """
    return {"success": True, "message": "Successfully logged out"}


@router.post(
    "/auth/forgot-password",
    summary="Request password reset",
    response_description="Confirmation that the flow started (always returns success to prevent email enumeration).",
)
def forgot_password(request: schemas.ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """Start the password-reset flow.

    If the email address exists in the database, a JWT reset link (valid for
    15 minutes) is sent to the admin. The response is always positive
    regardless of whether the email exists, to prevent enumeration attacks.

    Args:
        request: The email address to send the reset link to.
        db: SQLAlchemy session.

    Returns:
        Generic success message.
    """
    admin = db.query(models.Admin).filter(models.Admin.email == request.email).first()

    if admin:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
        reset_token_data = {"sub": str(admin.id), "exp": expire, "type": "reset"}
        reset_token = jwt.encode(reset_token_data, SECRET_KEY, algorithm=ALGORITHM)

        frontend_url = os.getenv("FRONTEND_URL", "http://localhost:4200")
        reset_link = f"{frontend_url}/reset-password?token={reset_token}"

        SENDER_EMAIL = os.getenv("SENDER_EMAIL")
        SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
        SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.resend.com")
        SMTP_PORT = int(os.getenv("SMTP_PORT", 587))

        msg = MIMEMultipart()
        msg["From"] = f"Smart Parcel Wall <{SENDER_EMAIL}>"
        msg["To"] = admin.email
        msg["Subject"] = "Password Reset Request"

        body = f"""Dear {admin.name},

You requested a password reset for your Smart Parcel Wall account.
Click the link below to set a new password:

{reset_link}

This link expires in 15 minutes. If you did not make this request, you can safely ignore this email.

Kind regards,
The Smart Parcel Wall System
"""
        msg.attach(MIMEText(body, "plain"))

        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.starttls()
            server.login("resend", SENDER_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception as e:
            print(f"Failed to send reset email to {admin.email}: {e}")

    # Always return success to avoid revealing whether the email exists
    return {
        "success": True,
        "message": f"If {request.email} is registered, a reset link has been sent.",
    }


@router.post(
    "/auth/reset-password",
    summary="Set new password",
    response_description="Confirmation that the password was changed.",
)
def reset_password(request: schemas.ResetPasswordRequest, db: Session = Depends(get_db)) -> dict:
    """Verify the reset token and store the new password.

    The token must carry ``type: "reset"`` to distinguish it from a regular
    login token. This prevents a stolen login token from being reused to
    change the password.

    Args:
        request: The reset token and the new password.
        db: SQLAlchemy session.

    Returns:
        Success message.

    Raises:
        HTTPException 400: If the token is expired, invalid, or wrong type.
    """
    try:
        payload = jwt.decode(request.token, SECRET_KEY, algorithms=[ALGORITHM])

        # Ensure this is a reset token, not a reused login token
        if payload.get("type") != "reset":
            raise HTTPException(status_code=400, detail="Invalid token type.")

        admin_id = payload.get("sub")
        admin = db.query(models.Admin).filter(models.Admin.id == int(admin_id)).first()

        if not admin:
            raise HTTPException(status_code=404, detail="Admin not found.")

        admin.password_hash = pwd_context.hash(request.new_password)
        db.commit()

        return {"success": True, "message": "Password changed successfully."}

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Reset link expired. Request a new one.")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=400, detail="Invalid or corrupted reset link.")


@router.get(
    "/user/me",
    summary="Get current profile",
    response_description="Profile data of the authenticated admin.",
)
def get_me(current_user: models.Admin = Depends(get_current_user)) -> dict:
    """Return the profile of the currently authenticated admin.

    Requires a valid Bearer token in the Authorization header.
    """
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "avatar": f"https://ui-avatars.com/api/?name={current_user.name.replace(' ', '+')}&background=random",
    }