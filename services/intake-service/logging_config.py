"""Logging setup for intake-service (copy-pasted per service — see ADR 0001).

Note: this service writes a per-registration line to a repo-level file handler
(logs/intake-service.log) so the front desk has a record of every registration.
As of 2026-07 new writes log only an allowlisted, non-PHI metadata shape
(schemas.log_metadata) — the request body is never logged (D1 fix). Redacting
the body was insufficient: pattern redaction misses names/DOBs in free-text
fields. The file's historical entries still contain plaintext PHI — purge/
gitignore is an open ops item (docs/phi-logging-policy.md).
"""
import logging
import os


def configure(service_name: str) -> logging.Logger:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, level, logging.INFO)

    logger = logging.getLogger(service_name)
    logger.setLevel(log_level)

    # Don't stack duplicate handlers if configure() is called more than once.
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s %(levelname)s [" + service_name + "] %(message)s")

    # Console handler.
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    logger.addHandler(stream)

    # File handler — repo-level logs/<service>.log. Create the directory robustly
    # so the container does not crash at startup on a fresh volume.
    logs_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
    os.makedirs(logs_dir, exist_ok=True)
    file_handler = logging.FileHandler(os.path.join(logs_dir, service_name + ".log"))
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    return logger
