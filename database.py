"""
Database Configuratie
=====================
Dit bestand regelt de verbinding met de PostgreSQL database.
Het definieert de connectie-engine, de sessie-fabriek en levert de basisklasse
waar alle SQLAlchemy modellen (tabellen) van overerven.
"""

import os
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# Haal de database URL uit de Docker environment variabelen
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# Maak de engine aan: de daadwerkelijke motor die met Postgres praat.
engine = create_engine(SQLALCHEMY_DATABASE_URL)

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