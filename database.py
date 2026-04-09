"""
Database Configuratie
=====================
Dit bestand regelt de verbinding met de PostgreSQL database.
Het definieert de connectie-engine, de sessie-fabriek en levert de basisklasse
waar alle SQLAlchemy modellen (tabellen) van overerven.
"""

import os

# Check for test mode BEFORE loading anything from .env file
IN_TEST_MODE = os.getenv("IN_TEST_MODE", "false").lower() == "true"

# Only load .env if not in test mode
if not IN_TEST_MODE:
    from dotenv import load_dotenv
    load_dotenv()

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Get database URL from environment (PostgreSQL for production)
# Override to SQLite for testing
if IN_TEST_MODE:
    SQLALCHEMY_DATABASE_URL = "sqlite:///./test_smartwall.db"
else:
    SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL") or "sqlite:///./test_smartwall.db"

# Maak de engine aan: de daadwerkelijke motor die met Postgres of SQLite praat.
if SQLALCHEMY_DATABASE_URL:
    if "sqlite" in SQLALCHEMY_DATABASE_URL:
        # For SQLite, use explicit connection args
        engine = create_engine(
            SQLALCHEMY_DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
    else:
        engine = create_engine(SQLALCHEMY_DATABASE_URL)
else:
    # Fallback to SQLite for testing when PostgreSQL is not available
    engine = create_engine(
        "sqlite:///./test_smartwall.db",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )

# Maak een sessie-fabriek aan voor database-transacties.
# autocommit=False: We moeten handmatig db.commit() aanroepen (veiliger).
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# De basisklasse waar al onze databasemodellen in models.py van overerven.
Base = declarative_base()

def get_db() -> Generator[Session, None, None]:
    """
    Dependency functie om een database-sessie te openen en veilig te sluiten.
    Wordt gebruikt in FastAPI routes via `Depends(get_db)`.
    
    Yields:
        Session: Een actieve SQLAlchemy database sessie.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
