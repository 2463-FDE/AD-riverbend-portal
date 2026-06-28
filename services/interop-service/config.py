"""interop-service configuration. Environment-driven; sensible compose defaults.

This service has no database — it parses inbound HL7 v2 messages into our
internal record shape and returns them. No db.py / models here by design.
"""
import os


class Settings:
    service_name = "interop-service"
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # guardrail for inbound message size (bytes of the raw HL7 string)
    max_message_bytes = int(os.getenv("MAX_MESSAGE_BYTES", "262144"))


settings = Settings()
