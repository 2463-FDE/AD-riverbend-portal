"""SQLAlchemy engine/session for roi-service.

The engine is created lazily on first use so importing this module (and app.py)
never opens a connection — the CI import smoke test (`python -c "import app"`)
relies on that, and there is no DB during image build.
"""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import settings

Base = declarative_base()

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def get_engine() -> Engine:
    """Create the engine on first call. create_engine itself does not connect,
    but we defer it anyway so module import is fully side-effect free."""
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
    db: Session = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
