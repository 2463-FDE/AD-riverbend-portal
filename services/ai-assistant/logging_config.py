"""Logging setup for ai-assistant (copy-pasted per service — see ADR 0001).

Contract for this service: prompt and completion bodies are NEVER logged, to
any handler. Log metadata only (model, token counts, cost, latency, request
id). Anything that must log payload-shaped data goes through
redaction.safe_log_payload. See docs/phi-logging-policy.md.
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
