"""eligibility-service configuration. Environment-driven; sensible compose defaults."""
import os


class Settings:
    service_name = "eligibility-service"
    port = int(os.getenv("PORT", "8072"))
    environment = os.getenv("ENVIRONMENT", "development")
    log_level = os.getenv("LOG_LEVEL", "INFO")

    # Clearinghouse / payer REST shim that fronts the X12 270/271 exchange.
    payer_api_url = os.getenv("PAYER_API_URL", "https://edi.example.com/v1/eligibility")
    payer_api_key = os.getenv("PAYER_API_KEY", "")
    payer_name = os.getenv("PAYER_NAME", "edi.example.com")


settings = Settings()
