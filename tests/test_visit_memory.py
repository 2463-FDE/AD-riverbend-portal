"""Tests for gateway visit-scoped chat memory (ADR 0011 §3).

Visit memory is the first place this system deliberately stores PHI-adjacent
state at rest (a payer member id + a structured coverage verdict), in a Redis
instance the deployment has not hardened (debt-log D3b). So the properties under
test here are containment properties, not feature properties:

  * the key is opaque and carries no identifier — the deliberate opposite of the
    walkable sequential patient_id behind debt D11;
  * every write carries a TTL, atomically, because the TTL IS the retention
    policy for that state;
  * the transcript is bounded at the store, not by caller good behaviour;
  * a visit that is not yours is indistinguishable from one that does not exist;
  * a backend fault fails CLOSED. A fault cannot tell "absent" from "someone
    else's", so "start fresh on error" would skip the ownership check during a
    Redis blip.
"""
import json
import sys

import pytest

from conftest import load_module

_PINNED = ("config", "logging_config", "db", "models")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "vm_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "vm_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "vm_db")
sys.modules["models"] = load_module("services/gateway/models.py", "vm_models")
security = load_module("services/gateway/security.py", "vm_security")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

OWNER = "frontdesk"
OTHER = "drnguyen"
MEMBER_ID = "AETN1224"
FACTS = {"insurance_id": MEMBER_ID, "last_eligibility": {"active": True, "status": "active"}}


class _FakeRedis:
    """GET/SET(+nx/ex)/DEL/EVAL, enough for the visit store and its lock.
    ``ttls`` records expiries so tests can prove no visit key is ever written
    without one. ``fail`` makes every operation raise, for the fault paths."""

    def __init__(self):
        self.store = {}
        self.ttls = {}
        self.fail = False

    def get(self, key):
        if self.fail:
            raise RuntimeError("redis down")
        return self.store.get(key)

    def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise RuntimeError("redis down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def delete(self, key):
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    def eval(self, script, numkeys, *keys_and_args):
        if self.fail:
            raise RuntimeError("redis down")
        key = keys_and_args[0]
        # Only the compare-and-delete script reaches this store.
        assert script == security._SINGLEFLIGHT_RELEASE_LUA
        token = keys_and_args[1]
        if self.store.get(key) == token:
            self.store.pop(key, None)
            self.ttls.pop(key, None)
            return 1
        return 0


@pytest.fixture
def redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(security, "_redis_client", fake)
    monkeypatch.setattr(security.time, "time", lambda: 1_000_000.0)
    return fake


# --- the key ----------------------------------------------------------------
def test_visit_ids_are_opaque_and_unique():
    ids = {security.new_visit_id() for _ in range(200)}
    assert len(ids) == 200
    for visit_id in ids:
        assert len(visit_id) == 32
        assert all(char in "0123456789abcdef" for char in visit_id)
        assert not visit_id.isdigit()  # not a walkable integer (contrast: D11)


def test_no_identifier_appears_in_the_key(redis):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)

    written = list(redis.store)
    assert written == [f"visit:{visit_id}"]
    assert MEMBER_ID not in written[0]
    assert OWNER not in written[0]


# --- round trip + TTL -------------------------------------------------------
def test_round_trip(redis):
    visit_id = security.new_visit_id()
    turns = [{"role": "user", "text": "hi"}]
    security.visit_memory_save(visit_id, OWNER, FACTS, turns, 1800, 12)

    record = security.visit_memory_get(visit_id, OWNER)

    assert record["facts"] == FACTS
    assert record["turns"] == turns
    assert record["owner"] == OWNER


def test_every_write_binds_a_ttl(redis):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)

    assert redis.ttls[f"visit:{visit_id}"] == 1800


def test_ttl_is_sliding_and_created_at_is_preserved(redis, monkeypatch):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)
    first = security.visit_memory_get(visit_id, OWNER)

    monkeypatch.setattr(security.time, "time", lambda: 1_000_600.0)
    security.visit_memory_save(
        visit_id, OWNER, FACTS, [], 1800, 12, created_at=first["created_at"]
    )
    second = security.visit_memory_get(visit_id, OWNER)

    assert second["created_at"] == first["created_at"]  # visit age is not reset
    assert second["updated_at"] > first["updated_at"]   # but the window slides
    assert redis.ttls[f"visit:{visit_id}"] == 1800


def test_zero_ttl_writes_nothing(redis):
    # A retention policy of "forever" must not be reachable by setting 0.
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 0, 12)

    assert redis.store == {}


# --- bounded transcript -----------------------------------------------------
def test_turns_are_truncated_at_the_store(redis):
    visit_id = security.new_visit_id()
    turns = [{"role": "user", "text": f"turn {i}"} for i in range(30)]

    security.visit_memory_save(visit_id, OWNER, FACTS, turns, 1800, 12)

    stored = security.visit_memory_get(visit_id, OWNER)["turns"]
    assert len(stored) == 12
    # The TAIL is kept — recent turns carry the context.
    assert stored[-1]["text"] == "turn 29"
    assert stored[0]["text"] == "turn 18"


def test_truncation_does_not_trust_the_caller(redis):
    # The bound is a PHI bound: a caller that forgets to window its turns must
    # not be able to grow the stored transcript without limit.
    visit_id = security.new_visit_id()
    huge = [{"role": "user", "text": "x" * 100} for _ in range(500)]

    security.visit_memory_save(visit_id, OWNER, FACTS, huge, 1800, 12)

    assert len(security.visit_memory_get(visit_id, OWNER)["turns"]) == 12


# --- ownership --------------------------------------------------------------
def test_another_users_visit_is_indistinguishable_from_a_missing_one(redis):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)

    assert security.visit_memory_get(visit_id, OTHER) is None
    assert security.visit_memory_get(security.new_visit_id(), OTHER) is None


def test_owner_mismatch_does_not_leak_the_record(redis):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)

    assert security.visit_memory_get(visit_id, OTHER) is None
    # ...and the real owner still has it (a mismatch is not destructive).
    assert security.visit_memory_get(visit_id, OWNER)["facts"] == FACTS


# --- faults fail closed -----------------------------------------------------
def test_backend_fault_on_read_raises_rather_than_starting_fresh(redis):
    visit_id = security.new_visit_id()
    security.visit_memory_save(visit_id, OWNER, FACTS, [], 1800, 12)
    redis.fail = True

    with pytest.raises(security.VisitMemoryUnavailable):
        security.visit_memory_get(visit_id, OWNER)


def test_corrupt_record_raises_rather_than_starting_fresh(redis):
    # "Start fresh" on a corrupt value would skip the ownership check — the same
    # hole as failing soft on a backend fault, reached a different way.
    visit_id = security.new_visit_id()
    redis.store[f"visit:{visit_id}"] = "{not json"

    with pytest.raises(security.VisitMemoryUnavailable):
        security.visit_memory_get(visit_id, OWNER)


def test_non_dict_record_is_not_a_visit(redis):
    visit_id = security.new_visit_id()
    redis.store[f"visit:{visit_id}"] = json.dumps(["not", "a", "record"])

    assert security.visit_memory_get(visit_id, OWNER) is None


def test_write_fault_is_swallowed(redis):
    # The turn has already been answered; losing continuity beats failing a
    # request the clerk already got value from.
    redis.fail = True
    security.visit_memory_save(security.new_visit_id(), OWNER, FACTS, [], 1800, 12)


# --- the per-visit lock -----------------------------------------------------
def test_lock_admits_one_holder(redis):
    visit_id = security.new_visit_id()

    first = security.visit_lock_acquire(visit_id, 75)
    second = security.visit_lock_acquire(visit_id, 75)

    assert first
    assert second is None


def test_lock_release_frees_the_visit(redis):
    visit_id = security.new_visit_id()
    token = security.visit_lock_acquire(visit_id, 75)

    security.visit_lock_release(visit_id, token)

    assert security.visit_lock_acquire(visit_id, 75)


def test_lock_carries_a_ttl_so_it_cannot_wedge(redis):
    visit_id = security.new_visit_id()
    security.visit_lock_acquire(visit_id, 75)

    assert redis.ttls[f"visitlock:{visit_id}"] == 75


def test_a_stale_holder_cannot_release_a_newer_lock(redis):
    # Codex PR #7 round 13, one resource over: A's lock expired, B acquired the
    # same visit, and a blind DEL from A would hand C a concurrent turn.
    visit_id = security.new_visit_id()
    stale_token = security.visit_lock_acquire(visit_id, 75)
    redis.delete(f"visitlock:{visit_id}")  # A's lock expires
    fresh_token = security.visit_lock_acquire(visit_id, 75)  # B acquires

    security.visit_lock_release(visit_id, stale_token)  # A's late release

    assert security.visit_lock_acquire(visit_id, 75) is None  # B still holds it
    security.visit_lock_release(visit_id, fresh_token)
    assert security.visit_lock_acquire(visit_id, 75)


def test_lock_fails_open_on_a_redis_fault(redis):
    # Matches ai_singleflight_acquire: the authoritative spend guard is the
    # fail-CLOSED budget ceiling, so failing the lock closed would turn a blip
    # into an outage for no spend-safety gain.
    redis.fail = True

    assert security.visit_lock_acquire(security.new_visit_id(), 75)


def test_releasing_without_a_token_is_a_noop(redis):
    security.visit_lock_release(security.new_visit_id(), None)
