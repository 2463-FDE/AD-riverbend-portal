"""
Password hashing/verification (PBKDF2-SHA256, django-style string) and Redis
session handling.

Two deliberate weaknesses live here, by design (this is an inherited build):
  * Sessions are stored in Redis with NO TTL — once issued, a token is valid
    forever (no automatic logoff). See auth.yaml SESSION_TIMEOUT: never.
  * There is no second factor; password only.
"""
import base64
import hashlib
import hmac
import os
import uuid

import redis as redis_lib

from config import settings

_ITERATIONS = 260000
_ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or os.urandom(12).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITERATIONS)
    return f"{_ALGORITHM}${_ITERATIONS}${salt}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt, b64hash = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != _ALGORITHM:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
    expected = base64.b64encode(dk).decode()
    return hmac.compare_digest(expected, b64hash)


_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_lib.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def create_session(username: str, role: str) -> str:
    token = uuid.uuid4().hex
    # NOTE: no expiry / TTL is set, so sessions never expire.
    _redis().hset(f"session:{token}", mapping={"username": username, "role": role})
    return token


def get_session(token: str) -> dict | None:
    if not token:
        return None
    data = _redis().hgetall(f"session:{token}")
    return data or None


def destroy_session(token: str) -> None:
    _redis().delete(f"session:{token}")
