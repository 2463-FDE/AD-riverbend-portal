"""scheduling-service configuration. Environment-driven; sensible compose defaults."""
import os
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class Settings:
    service_name = "scheduling-service"
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    db_host = os.getenv("DB_HOST", "postgres")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "riverbend")
    db_user = os.getenv("DB_USER", "riverbend_app")
    db_password = os.getenv("DB_PASSWORD", "")

    # pagination guardrails for list endpoints
    default_page_limit = int(os.getenv("DEFAULT_PAGE_LIMIT", "50"))
    max_page_limit = int(os.getenv("MAX_PAGE_LIMIT", "200"))

    # The clinic's own timezone. /schedule resolves a calendar day in THIS zone,
    # not the server's and not the caller's: appointments are stored as
    # TIMESTAMPTZ, so "2026-08-01" is only a day once a zone is named. Matches
    # the rendering rule the portal is held to (frontend-rebuild FE-R8).
    clinic_timezone = os.getenv("CLINIC_TIMEZONE", "America/New_York")

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()


def _validate_clinic_timezone(name: str) -> None:
    """Fail the container at boot on an unresolvable CLINIC_TIMEZONE.

    Deferring this to the first request is the green-dashboard failure: /healthz
    does no timezone work, so it keeps answering 200 while every /schedule call
    raises ZoneInfoNotFoundError out of the handler and surfaces at the gateway
    as a transport-shaped 502. A typo (`America/New_york`) is the realistic
    trigger, and the difference between "this deploy is misconfigured" and "the
    scheduling service is flaky" is worth an import-time check.
    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise RuntimeError(
            f"CLINIC_TIMEZONE={name!r} is not a resolvable IANA timezone: {e}"
        ) from e


_validate_clinic_timezone(settings.clinic_timezone)
