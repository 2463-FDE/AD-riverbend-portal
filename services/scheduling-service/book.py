"""Appointment booking. Read-check-then-insert, no transaction, no constraint.

This module deliberately keeps the legacy raw-psycopg2 path (copy-pasted from the
original service) rather than going through the ORM. The check-then-insert race is
load-bearing brownfield debt — see book() below.
"""
import os
import time
from typing import Optional


def get_conn():
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "riverbend"),
        user=os.getenv("DB_USER", "riverbend_app"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def slot_taken(slot_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM appointments WHERE slot_id = %s AND status = 'confirmed'",
        (slot_id,),
    )
    taken = cur.fetchone() is not None
    conn.close()
    return taken


def insert_appointment(
    patient_id: int,
    slot_id: int,
    provider: Optional[str] = None,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    scheduled_for=None,
) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO appointments "
        "(patient_id, slot_id, provider, reason, location, scheduled_for, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'confirmed') RETURNING id",
        (patient_id, slot_id, provider, reason, location, scheduled_for),
    )
    aid = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return aid


def book(
    patient_id: int,
    slot_id: int,
    provider: Optional[str] = None,
    reason: Optional[str] = None,
    location: Optional[str] = None,
    scheduled_for=None,
):
    """
    Classic check-then-act race. Two near-simultaneous requests (or a client
    retry of a slow POST) both pass slot_taken() and both insert. There is no
    UNIQUE constraint on slot_id and no idempotency key on the request, so the
    same slot ends up double-booked.
    """
    # small window where a concurrent caller can slip through
    if not slot_taken(slot_id):
        time.sleep(0.05)
        return insert_appointment(
            patient_id, slot_id, provider, reason, location, scheduled_for
        )
    return None
