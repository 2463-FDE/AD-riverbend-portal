"""SQLAlchemy engine/session for scheduling-service.

The engine is created lazily: ``create_engine`` does not open a connection
until first use, so importing this module is safe without a live database
(the CI import smoke test relies on that). We additionally defer the actual
``create_engine`` call behind ``get_engine()`` so even engine construction is
not done at import time.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

Base = declarative_base()

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    """Build (once) and return the process-wide engine. No connection is opened
    here — psycopg2 connects on first query via the pool."""
    global _engine
    if _engine is None:
        _engine = create_engine(settings.db_url, pool_pre_ping=True, future=True)
    return _engine


def get_sessionmaker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, future=True
        )
    return _SessionLocal


def get_db():
    """FastAPI dependency — yields a session and always closes it."""
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
