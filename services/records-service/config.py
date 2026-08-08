"""records-service configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "records-service"
    port = int(os.getenv("PORT", "8073"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Serve-side bounds for the chart-open relevant-records helper. The client's
    # AI budget constrains the eval harness's embedding spend (RAG_MAX_CORPUS_DOCS);
    # these bound the SERVING path, which does no embedding at all — how many
    # records one chart open may read, and how many it may return. Without the
    # scan bound a large chart would cost one query per encounter with no ceiling
    # (D8's N+1 is deliberate and stays; unbounded is not the same as deliberate).
    relevant_records_max_items = int(os.getenv("RELEVANT_RECORDS_MAX_ITEMS", "10"))
    relevant_records_max_scan = int(os.getenv("RELEVANT_RECORDS_MAX_SCAN", "500"))

    db_host = os.getenv("DB_HOST", "postgres")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "riverbend")
    db_user = os.getenv("DB_USER", "riverbend_app")
    db_password = os.getenv("DB_PASSWORD", "")

    @property
    def db_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
