"""Shared-ish logging setup (copy-pasted per service — see ADR 0001)."""
import logging
import os


def configure(service_name: str) -> logging.Logger:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s [" + service_name + "] %(message)s",
    )
    return logging.getLogger(service_name)
