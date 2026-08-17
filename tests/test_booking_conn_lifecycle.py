"""
Booking helpers release their DB connection on every path (e6-SPEC-7).

D5b trailing note: scheduling-service/book.py's ``slot_taken`` and
``insert_appointment`` open a raw psycopg2 connection and ``close()`` it only on
the success path — a raising query or insert leaks the connection. Under load
that exhausts the pool and the booking route starts failing to *acquire* a
connection, an availability failure layered on top of the seeded RIV-175 race.

These are the negative tests the §1 zone requires (docs/landmines.md §3): each
helper is driven to raise mid-operation and asserted to have closed its
connection before the error propagates. FAIL against the pre-fix
close-on-success-only code.

Scope guard (e6-SPEC-8): the fix is connection lifecycle only. The
check-then-insert race, the absent slot_id UNIQUE, and the absent idempotency
key stay seeded and are untouched — RIV-175 remains a curriculum defect.
"""
import sys

import pytest

from conftest import load_module

book_mod = load_module("services/scheduling-service/book.py", "sched_book_lifecycle")


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, *args, **kwargs):
        if self._conn.fail_on_execute:
            raise RuntimeError("statement blew up mid-flight")

    def fetchone(self):
        return (1,)


class _FakeConn:
    def __init__(self, fail_on_execute):
        self.fail_on_execute = fail_on_execute
        self.closed = False
        self.committed = False

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.committed = True

    def close(self):
        self.closed = True


def _wire(monkeypatch, conn):
    monkeypatch.setattr(book_mod, "get_conn", lambda: conn)


# ---------------------------------------------------------------- error paths

def test_slot_taken_closes_connection_when_query_raises(monkeypatch):
    conn = _FakeConn(fail_on_execute=True)
    _wire(monkeypatch, conn)
    with pytest.raises(RuntimeError):
        book_mod.slot_taken(7)
    assert conn.closed is True


def test_insert_appointment_closes_connection_when_insert_raises(monkeypatch):
    conn = _FakeConn(fail_on_execute=True)
    _wire(monkeypatch, conn)
    with pytest.raises(RuntimeError):
        book_mod.insert_appointment(patient_id=12, slot_id=7)
    assert conn.closed is True


# --------------------------------------------------- positive controls (success)

def test_slot_taken_still_closes_on_success(monkeypatch):
    conn = _FakeConn(fail_on_execute=False)
    _wire(monkeypatch, conn)
    assert book_mod.slot_taken(7) is True
    assert conn.closed is True


def test_insert_appointment_still_commits_and_closes_on_success(monkeypatch):
    conn = _FakeConn(fail_on_execute=False)
    _wire(monkeypatch, conn)
    aid = book_mod.insert_appointment(patient_id=12, slot_id=7)
    assert aid == 1
    assert conn.committed is True
    assert conn.closed is True
