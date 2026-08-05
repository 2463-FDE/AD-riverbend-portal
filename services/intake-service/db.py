"""SQLAlchemy engine/session for intake-service (writes patients/coverage/consents)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# create_engine does not connect until first use, so importing this module is
# safe without a live database (CI import smoke test relies on that).
# hide_parameters strips SQLAlchemy's [SQL: ...] [parameters: (...)] from
# DBAPIError text ONLY — the driver's own message can still embed values
# (e.g. Postgres "Failing row contains ..."), so rule 3's class-name log
# idiom stays the primary control; this is blast-radius narrowing.
engine = create_engine(
    settings.db_url, pool_pre_ping=True, future=True, hide_parameters=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
