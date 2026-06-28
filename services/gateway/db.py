"""SQLAlchemy engine/session for the gateway (reads the users table for login)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# create_engine does not connect until first use, so importing this module is
# safe without a live database (CI import smoke test relies on that).
engine = create_engine(settings.db_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
