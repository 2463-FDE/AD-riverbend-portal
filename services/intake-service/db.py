"""SQLAlchemy engine/session for intake-service (writes patients/coverage/consents)."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# create_engine does not connect until first use, so importing this module is
# safe without a live database (CI import smoke test relies on that).
# hide_parameters: a DBAPIError message must never embed the bound row (PHI) —
# engine-level backstop behind phi-logging-policy rule 3's log discipline.
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
