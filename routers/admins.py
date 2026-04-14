"""
Router: Admins & Settings
========================

Manages dashboard admin accounts. Admins can view and update their own
profile and password. Superadmins can also create new admins and delete
existing ones.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Any

from database import get_db
import models
import schemas

from routers.auth import get_current_user, pwd_context

router = APIRouter(
    prefix="/api/admins",
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/me",
    response_model=schemas.AdminResponse,
    summary="Get my profile",
    response_description="The authenticated admin's profile data.",
)
def get_my_profile(current_admin: models.Admin = Depends(get_current_user)) -> Any:
    """Return the profile of the currently authenticated admin."""
    return current_admin


@router.put(
    "/me",
    response_model=schemas.AdminResponse,
    summary="Update my profile",
    response_description="The updated profile data.",
)
def update_my_profile(
    profile_data: schemas.AdminUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_user),
) -> Any:
    """Update the authenticated admin's name, email, and phone.

    Enforces email uniqueness — the new email cannot already be in use by
    another admin.

    Args:
        profile_data: Updated profile fields.
        db: SQLAlchemy session.
        current_admin: The authenticated admin (injected by dependency).

    Returns:
        The refreshed admin model.
    """
    if profile_data.email != current_admin.email:
        existing_admin = db.query(models.Admin).filter(models.Admin.email == profile_data.email).first()
        if existing_admin:
            raise HTTPException(status_code=400, detail="Email address already in use by another admin.")

    current_admin.name = profile_data.name
    current_admin.email = profile_data.email
    current_admin.phone = profile_data.phone

    db.commit()
    db.refresh(current_admin)
    return current_admin


@router.put(
    "/me/password",
    summary="Change my password",
    response_description="Confirmation of the password change.",
)
def update_my_password(
    passwords: schemas.PasswordUpdate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_user),
) -> dict:
    """Change the authenticated admin's password.

    Requires the current password for verification before the new one is
    stored.

    Args:
        passwords: Current and new password values.
        db: SQLAlchemy session.
        current_admin: The authenticated admin.

    Returns:
        Success message.
    """
    if not pwd_context.verify(passwords.current_password, current_admin.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")

    current_admin.password_hash = pwd_context.hash(passwords.new_password)
    db.commit()

    return {"detail": "Password changed successfully."}


@router.get(
    "",
    response_model=List[schemas.AdminResponse],
    summary="List all admins",
    response_description="List of all admins in the system.",
)
def get_all_admins(
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_user),
) -> Any:
    """Return a list of all admin accounts.

    Used in the dashboard for managing colleague accounts.
    """
    return db.query(models.Admin).all()


@router.post(
    "",
    response_model=schemas.AdminResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create new admin",
    response_description="The newly created admin.",
)
def create_admin(
    admin_data: schemas.AdminCreate,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_user),
) -> Any:
    """Add a new admin account.

    Enforces email uniqueness and hashes the password with bcrypt before
    storing.

    Args:
        admin_data: New admin details including plaintext password.
        db: SQLAlchemy session.
        current_admin: The authenticated admin.

    Returns:
        The created admin model.
    """
    existing_admin = db.query(models.Admin).filter(models.Admin.email == admin_data.email).first()
    if existing_admin:
        raise HTTPException(status_code=400, detail="Email address already in use.")

    hashed_pw = pwd_context.hash(admin_data.password)

    new_admin = models.Admin(
        name=admin_data.name,
        email=admin_data.email,
        phone=admin_data.phone,
        password_hash=hashed_pw,
        role=admin_data.role,
    )

    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    return new_admin


@router.delete(
    "/{admin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete admin (superadmin only)",
    response_description="No content (204) on success.",
)
def delete_admin(
    admin_id: int,
    db: Session = Depends(get_db),
    current_admin: models.Admin = Depends(get_current_user),
) -> None:
    """Delete an admin account.

    Only superadmins can delete other admins. An admin cannot delete
    themselves.

    Args:
        admin_id: ID of the admin to delete.
        db: SQLAlchemy session.
        current_admin: The authenticated admin (must be superadmin).

    Raises:
        HTTPException 403: If the caller is not a superadmin.
        HTTPException 400: If the caller tries to delete themselves.
        HTTPException 404: If the target admin does not exist.
    """
    if current_admin.role != "superadmin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: only superadmins can delete admin accounts.",
        )

    if current_admin.id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account.",
        )

    admin_to_delete = db.query(models.Admin).filter(models.Admin.id == admin_id).first()
    if not admin_to_delete:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin not found.")

    db.delete(admin_to_delete)
    db.commit()
    return None