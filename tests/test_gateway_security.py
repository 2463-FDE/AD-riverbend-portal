"""Unit tests for gateway password hashing/verification (no DB, no Redis I/O)."""
from conftest import load_module

security = load_module("services/gateway/security.py", "gateway_security")


def test_hash_then_verify_roundtrip():
    encoded = security.hash_password("portal123")
    assert encoded.startswith("pbkdf2_sha256$")
    assert security.verify_password("portal123", encoded) is True


def test_verify_rejects_wrong_password():
    encoded = security.hash_password("portal123")
    assert security.verify_password("nope", encoded) is False


def test_verify_rejects_malformed_hash():
    assert security.verify_password("x", "not-a-valid-hash") is False
    assert security.verify_password("x", "") is False


def test_salt_is_random_per_hash():
    a = security.hash_password("same")
    b = security.hash_password("same")
    assert a != b  # different salts
    assert security.verify_password("same", a)
    assert security.verify_password("same", b)


def test_verifies_seeded_fixture_hash():
    # The exact hash the seed generator produces for the demo accounts.
    salt = "riverbend02saltval0"
    encoded = security.hash_password("portal123", salt=salt)
    assert security.verify_password("portal123", encoded)
