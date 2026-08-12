"""
intake-service — multi-step patient registration + insurance + consent capture.

Both the front desk and the self-service portal POST a full intake payload here.
We create the patient chart, attach insurance coverage (if supplied), record the
signed consents, and verify payer eligibility before returning.

Inherited shortcomings (left as-is from the handoff):
  * D1 — REMEDIATED 2026-07: intake no longer logs the request body at all.
    It logs only an allowlisted, non-PHI metadata shape (schemas.log_metadata)
    — never a raw request string. Redacting the body was not enough: pattern
    redaction misses names/DOBs smuggled into free-text fields (Codex review).
    See docs/phi-logging-policy.md. The historical logs/intake-service.log
    still contains pre-fix PHI — open ops item.
  * D5 — PARTLY REMEDIATED 2026-08 (ADR 0005, W2): there is still no master
    patient index, and every /intake creates a brand new patients row, so one
    person still forks into several charts. What changed is that the fork is no
    longer silent — intake now evaluates a tier-1 match key (normalized SSN plus
    corroborating demographics, intake.yaml match_key: ssn_corroborated) and
    queues candidate duplicate pairs for human review. Flag, never merge
    (ADR 0005 decision 3). Tier 2 (fuzzy name + DOB where the SSN is missing or
    invalid) is deferred, so a row without a usable SSN is still matched by
    nothing.
  * D4 / RIV-088 / RIV-141 — PARTLY REMEDIATED 2026-07 (ADR 0010): eligibility
    is still verified on the request thread, but the call is now bounded by a
    timeout and an intake-side circuit breaker, and the seeded time.sleep(4.2)
    is gone. Registration is therefore slowed, never frozen, by a bad payer —
    including one that keeps answering slowly, whose latency counts against the
    breaker on its own (review r6).
    Full register-first / out-of-band re-verification (instant 201 + async
    verify) remains the complete fix and is still open — it needs a job/result
    store (see ADR 0010 and docs/debt-log.md D4).
  * Patient, coverage and consents are written in ONE transaction (E4-SPEC-4).
    They used to commit separately, with a consent-write failure swallowed, so
    a fault mid-sequence left a half-registered patient behind a 201. Atomicity
    is per-request, not cross-service: a commit whose response is lost in
    transit still leaves a row the operator never sees confirmed. That is closed
    as of 2026-08-11 (e5, E5-SPEC-24..43) — the caller names the submission
    attempt (submission_id), the record binds it to the registration inside the
    same transaction, and a repeat of the attempt replays that registration
    instead of forking a second chart. A repeat is only a repeat if the content
    matches the recorded keyed fingerprint (E5-SPEC-41): an edited retry after a
    lost response is a different attempt and is refused (409, E5-SPEC-42),
    never answered with a confirmation of content the chart never received.
    Register-first / async re-verification is
    the other half of the same class and is still open (above): this makes the
    retry safe, register-first shrinks the window that makes it necessary.
"""
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import yaml
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

import matching
from breaker import CircuitBreaker, EligibilityBreakerOpen
from config import settings
from db import get_db
from logging_config import configure
from models import (
    Consent,
    DuplicateReviewQueue,
    InsuranceCoverage,
    MatchEvaluationFailure,
    Patient,
    RegistrationSubmission,
)
from schemas import (
    Demographics,
    DispositionRequest,
    DispositionResponse,
    Insurance,
    IntakeRequest,
    IntakeResponse,
    ReviewQueueItem,
    ReviewQueuePage,
    ReviewQueuePatient,
    disposition_log_metadata,
    log_metadata,
)

log = configure(settings.service_name)
app = FastAPI(title="Riverbend intake-service", version="1.3.0")

INTAKE_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "intake.yaml")

# Per-worker breaker on the intake -> eligibility hop (ADR 0010, review r4).
# Deliberately in-process, like eligibility-service's: no new infrastructure,
# fully reversible. Cost of per-worker state: with W workers, up to
# W x ELIGIBILITY_BREAKER_FAIL_THRESHOLD slow calls can still occur before every
# worker has opened its own circuit.
_breaker = CircuitBreaker(
    fail_threshold=settings.eligibility_breaker_fail_threshold,
    reset_seconds=settings.eligibility_breaker_reset_seconds,
)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": settings.service_name}


@app.get("/intake/config")
def intake_config():
    """Return the parsed intake.yaml so the front-desk UI can adapt its form."""
    try:
        with open(INTAKE_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        log.error("intake config missing at %s", INTAKE_CONFIG_PATH)
        raise HTTPException(status_code=500, detail="intake config not found")
    except yaml.YAMLError as e:
        log.error("intake config parse error: %s", e)
        raise HTTPException(status_code=500, detail="intake config invalid")


@app.post("/intake", response_model=IntakeResponse, status_code=201)
def create_intake(req: IntakeRequest, db: Session = Depends(get_db)):
    started = time.time()

    # D1 (remediated 2026-07): the front desk still gets a record of every
    # registration, but we log only an allowlisted, non-PHI metadata shape —
    # never the request body or any raw request string. Redacting the body was
    # insufficient because pattern redaction misses names/DOBs smuggled into
    # free-text fields (Codex review). See docs/phi-logging-policy.md.
    log.info('POST /intake meta=%s', json.dumps(log_metadata(req)))

    # Idempotency per submission ATTEMPT (e5, E5-SPEC-24/25/30). The window this
    # closes is the one e4 made reachable: the registration commits, the
    # response is lost in transit, the portal correctly says nothing was saved
    # (E4-SPEC-7), and the operator's retry used to fork a second chart with its
    # own coverage and consent rows. A recorded identifier means the retry gets
    # the registration the first attempt created, and creates nothing.
    #
    # This is NOT a master patient index (E5-SPEC-36): nothing here consults
    # demographics, so the same human submitted twice with two identifiers still
    # forks two charts and is still only queued for review. That is D5, and it
    # stays open by design.
    #
    # The identifier alone names the ATTEMPT, not its content. Computed here,
    # before the lookup, so the fail-closed key guard cannot be bypassed by a
    # replay-shaped request (E5-SPEC-41, plan D-19).
    fingerprint = _payload_fingerprint(req)
    replayed = _find_registration(db, req.submission_id)
    if replayed is not None:
        patient_id = _match_or_conflict(replayed, fingerprint)
    else:
        try:
            patient_id = _create_registration(db, req, fingerprint)
        except _SubmissionAlreadyRecorded:
            # A concurrent request carrying the same identifier won the race
            # (E5-SPEC-32). It has committed by definition — that is what
            # released the lock our insert was waiting on — so one re-read is
            # enough and nothing polls. The loser's content is compared too: it
            # may differ from the winner's, and answering the winner's
            # patient_id for different content is the same silent confirmation
            # E5-SPEC-42 exists to refuse.
            patient_id = _require_registration(db, req.submission_id, fingerprint)
        else:
            # D5 (partly remediated, ADR 0005 / W2): still no MPI, and every
            # intake inserts a brand new chart even for a returning patient — W2
            # merges nothing. What it adds is detection: the match key is
            # evaluated AFTER the patient row is committed, so a matcher fault
            # can never block or slow a registration, and a candidate match is
            # queued for a human rather than acted on. A replay reaches neither
            # this line nor the create above, so it queues nothing new.
            _evaluate_match_key(db, patient_id, req.demographics)

    # D4 / RIV-088 / RIV-141 (bounded, ADR 0010): eligibility verification still
    # runs on this request thread — it DOES delay the 201, by at most
    # ELIGIBILITY_TIMEOUT_SECONDS, and the intake-side breaker drops that to ~0
    # once the dependency is known-bad. So a slow/hung payer degrades
    # registration instead of freezing it (RIV-141), but this is not yet true
    # deferral. The registration is already committed above, so a degraded
    # result only changes what the eligibility *field* reports, never whether
    # the patient is saved. Register-first + async re-verification is the
    # remaining follow-up (ADR 0010, docs/debt-log.md D4).
    eligibility = _verify_eligibility_guarded(req.insurance)

    elapsed = round(time.time() - started, 2)
    log.info("POST /intake 201 patient_id=%s elapsed=%.2fs", patient_id, elapsed)
    return IntakeResponse(patient_id=patient_id, elapsed_seconds=elapsed, eligibility=eligibility)


class _SubmissionAlreadyRecorded(Exception):
    """The UNIQUE index rejected our identifier: a concurrent request won.

    Internal control flow, never surfaced to a caller — the loser of the race
    re-reads the winner's registration and answers with it (E5-SPEC-32).
    """


# The constraint by name, plus the shape SQLite spells the same collision with,
# so the collision path can tell OUR unique violation from any other integrity
# error (a foreign key, say) without stringifying an exception that would embed
# the bound patients row.
_SUBMISSION_CONSTRAINT = "uq_registration_submission_id"
_SUBMISSION_COLUMN = "registration_submissions.submission_id"


def _is_submission_collision(e: IntegrityError) -> bool:
    orig = str(getattr(e, "orig", "") or "")
    return _SUBMISSION_CONSTRAINT in orig or _SUBMISSION_COLUMN in orig


def _bound_the_collision_wait(db: Session) -> None:
    """Bound how long this transaction waits on a concurrent submission.

    The loser of a collision blocks on the UNIQUE index until the winner commits
    (its row is invisible until then), so without a bound a duplicate submission
    becomes a hang. `lock_timeout` turns that into a 55P03, which reaches the
    existing 503 branch (E5-SPEC-33).

    Postgres only: the endpoint tests run on in-memory SQLite, which serializes
    writers and has no such knob. The guard must not quietly become "never" —
    tests/test_intake_idempotency.py pins both halves.

    `SET` takes no bind parameters, so the value is interpolated. It is coerced
    to an int first and it comes from config, never from a request. The knob is
    SECONDS (config.registration_lock_wait_seconds, plan D-15) and
    `lock_timeout`'s unit here is MILLISECONDS: a dropped `* 1000` would shrink
    the bound 1000x and turn every routine collision wait into a 503, so the
    test pins the issued value and not merely that a statement was issued.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    milliseconds = int(settings.registration_lock_wait_seconds * 1000)
    db.execute(text(f"SET LOCAL lock_timeout = '{milliseconds}ms'"))


# A key that is committed, published or short is not a key. Templates ship
# non-empty placeholders and CI seeds `.env` from them (`cp .env.example .env`,
# .github/workflows/ci.yml), so a bare presence check would let a deploy that
# never set a real value compute PHI-derived fingerprints under a value anyone
# can read — dictionary-checkable from a database dump. The estate already
# answered this once the same way, for the same reason: llm_client's
# _PLACEHOLDER_BEARER_TOKENS (Codex review, PR #5 round 5). Matched
# case-insensitively after stripping; the substrings catch the next template
# value nobody thought to add here. PR #76 review round 3, owner decision
# 2026-08-12.
_PLACEHOLDER_FINGERPRINT_KEYS = frozenset({
    "changeme",
    "change-me",
    "change_me",
    "placeholder",
    "dev-registration-fingerprint-key-change-me",
    "your-key-here",
    "todo",
    "xxx",
})
_PLACEHOLDER_FINGERPRINT_MARKERS = ("changeme", "change-me", "change_me", "placeholder")
# 32 characters of a randomly generated secret. The fingerprint's inputs (DOB,
# SSN, member id) are guessable, so the key is the only thing standing between a
# stolen column and an offline confirmation oracle, and a short key is brute
# -forceable exactly there. Not a strength meter — a floor, in the one direction
# that fails closed.
_MIN_FINGERPRINT_KEY_CHARS = 32


def _fingerprint_key() -> str:
    """The configured fingerprint key, or a 503 if it is not a real one.

    Absence, an empty or whitespace-only value, known placeholder sentinels and
    anything under the length floor are all treated as "not configured". The
    value is only compared — never logged, echoed in the response, or embedded
    in the error.
    """
    key = (settings.registration_fingerprint_key or "").strip()
    normalized = key.lower()
    unusable = (
        not key
        or normalized in _PLACEHOLDER_FINGERPRINT_KEYS
        or any(marker in normalized for marker in _PLACEHOLDER_FINGERPRINT_MARKERS)
        or len(key) < _MIN_FINGERPRINT_KEY_CHARS
    )
    if unusable:
        # Configuration, not content: no submitted value and no key material in
        # this message. Deliberately does not say WHICH check refused — that
        # would narrow the value for anyone reading the log.
        log.error(
            "intake: REGISTRATION_FINGERPRINT_KEY is not set to a real secret "
            "(unset, a known placeholder, or under %d characters) — refusing to "
            "register rather than fingerprint under a guessable key",
            _MIN_FINGERPRINT_KEY_CHARS,
        )
        raise HTTPException(status_code=503, detail="registration store unavailable")
    return key


def _payload_fingerprint(req: IntakeRequest) -> str:
    """A keyed, non-reversible digest of what this submission asked for.

    The submission identifier names the ATTEMPT; it says nothing about the
    content. Without this, an operator who lost a response, corrected a typo'd
    DOB or member id and resubmitted was answered 201 for the ORIGINAL chart —
    the desk saw a confirmation while the edit was silently dropped (codex
    review round 2 on PR #76, spec D-18). So a replay is a replay only when the
    content matches (E5-SPEC-30); a mismatch is E5-SPEC-42's 409.

    KEYED, never a plain hash (E5-SPEC-41): the input is DOB, SSN, member id and
    a handful of other guessable fields, and the digest is persisted. A plain
    SHA-256 of that would let anyone holding the column confirm a guessed
    patient by recomputing it — a dictionary-reversible oracle over PHI. HMAC
    with a secret the database does not carry makes the stored value inert.

    FAIL-CLOSED on a key that is not a real secret — unset, a known placeholder,
    or under the length floor (`_fingerprint_key`) — in the /ai paths' style, and
    computed BEFORE the replay lookup so a replay-shaped request cannot slip past
    the guard. The answer is the existing store-unavailable 503: this is a
    deployment fault, not something the desk can correct, and the portal already
    renders it in the system-failure branch.

    Computed from the VALIDATED model, so spellings that validate identically
    (a braced identifier, a reordered consent list) fingerprint identically and
    a genuine re-submission still replays.
    """
    key = _fingerprint_key()
    dump = req.model_dump(mode="json")
    # The identifier is the key this fingerprint is stored under, not part of
    # the content it describes.
    dump.pop("submission_id", None)
    # use_enum_values makes these plain strings; order is a form artefact, not a
    # difference in what was consented to.
    dump["consents"] = sorted(dump.get("consents") or [])
    canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def _match_or_conflict(recorded: tuple[int, str], fingerprint: str) -> int:
    """The recorded registration if this really is a replay of it, else a 409.

    E5-SPEC-42. Nothing is created and nothing is modified: the recorded row and
    the chart it names are exactly as the original attempt left them. The detail
    is a constant — a mismatch is a statement about content, and echoing any of
    it would put submitted values in a response and a log line.

    When the portal's re-mint holds (E5-SPEC-43) this is unreachable from the
    portal: an edited form is a new attempt with a new identifier. It is the
    service-side guarantee for every other caller.
    """
    patient_id, recorded_fingerprint = recorded
    if not hmac.compare_digest(recorded_fingerprint or "", fingerprint):
        # The patient id only — the same value the 201 line already carries.
        # Never the differing fields, never either fingerprint: one is a keyed
        # digest of PHI and the pair would say which request changed what.
        log.warning(
            "intake: a recorded submission was replayed with different content, "
            "refusing (patient_id=%s)",
            patient_id,
        )
        raise HTTPException(status_code=409, detail="registration submission conflict")
    return patient_id


def _find_registration(db: Session, submission_id: str) -> Optional[tuple[int, str]]:
    """The registration this submission identifier already produced, if any.

    Returns the patient id AND the fingerprint recorded with it: whether a
    request naming this identifier is a replay is decided by the content, not
    by the identifier alone (E5-SPEC-41).
    """
    try:
        row = db.execute(
            select(
                RegistrationSubmission.patient_id,
                RegistrationSubmission.payload_fingerprint,
            ).where(RegistrationSubmission.submission_id == submission_id)
        ).one_or_none()
    except SQLAlchemyError as e:
        db.rollback()
        # Class only, same rule as _create_registration below.
        log.error("intake: failed to read the submission record (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="registration store unavailable")
    return None if row is None else (row[0], row[1])


def _require_registration(db: Session, submission_id: str, fingerprint: str) -> int:
    """The winner's registration after we lost the race, or a 503.

    Missing here means the row that rejected our insert has vanished, which is
    not a state a caller can act on — it is the store misbehaving, so it takes
    the same answer as any other store failure.
    """
    recorded = _find_registration(db, submission_id)
    if recorded is None:
        log.error("intake: submission record vanished after a unique violation")
        raise HTTPException(status_code=503, detail="registration store unavailable")
    return _match_or_conflict(recorded, fingerprint)


def _create_registration(db: Session, req: IntakeRequest, fingerprint: str) -> int:
    """Patient + coverage + consents, or nothing (E4-SPEC-4).

    One transaction, one commit. The three writes used to commit separately —
    and a consent failure was swallowed outright — so a fault between them left
    a patient with no consent rows, a 201 at the desk, and nothing to say the
    registration was half-written (docs/debt-log.md D4 residual 2). What a
    caller owes a failed registration is now decided here: nothing survives it.

    As of e5 the submission record joins that transaction (E5-SPEC-29). It has
    to: a record written outside it would either claim an identifier for a
    registration that then failed — so the retry replays a chart that does not
    exist — or leave a committed registration unclaimed, which is the window
    this whole path exists to close. The content fingerprint is written with it,
    in the same transaction and for the same reason (E5-SPEC-41): a record that
    cannot say WHAT was registered cannot tell a replay from an edited retry.
    """
    try:
        _bound_the_collision_wait(db)
        patient = Patient(
            name=req.demographics.name,
            dob=req.demographics.dob,
            ssn=req.demographics.ssn,
            gender=req.demographics.gender,
            address=req.demographics.address,
            phone=req.demographics.phone,
            email=req.demographics.email,
            notes=req.demographics.notes,
            created_via=req.demographics.created_via,
        )
        db.add(patient)
        # db.py's session is autoflush=False, so this is explicit and required:
        # it assigns the PK inside the transaction, without committing.
        db.flush()
        patient_id = patient.id     # read before commit expires the instance
        if req.insurance is not None:
            db.add(
                InsuranceCoverage(
                    patient_id=patient_id,
                    payer_name=req.insurance.payer_name,
                    member_id=req.insurance.member_id,
                    group_number=req.insurance.group_number,
                    plan_type=req.insurance.plan_type,
                )
            )
        for kind in req.consents:
            db.add(Consent(patient_id=patient_id, kind=kind))
        # Same transaction, same commit (E5-SPEC-29).
        db.add(
            RegistrationSubmission(
                submission_id=req.submission_id,
                payload_fingerprint=fingerprint,
                patient_id=patient_id,
            )
        )
        db.commit()
        return patient_id
    except IntegrityError as e:
        db.rollback()
        if _is_submission_collision(e):
            # Not a failure: a concurrent request carrying this identifier
            # committed first. The caller re-reads and replays it (E5-SPEC-32).
            raise _SubmissionAlreadyRecorded from None
        # Any other integrity error is a store failure like the ones below, and
        # gets the same class-only log for the same PHI reason.
        log.error("intake: failed to create registration (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="registration store unavailable")
    except SQLAlchemyError as e:
        db.rollback()
        # PHI policy rule 3: never stringify a statement-level DB error — a
        # DBAPIError embeds [SQL: ...] [parameters: (...)], i.e. the full bound
        # row (name, DOB, SSN, notes for the patient write; member_id and
        # group_number for the coverage one). Class name only, same idiom as
        # _verify_eligibility's 2026-07-08 fix.
        # Test: tests/test_intake_db_error_phi.py.
        log.error("intake: failed to create registration (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="registration store unavailable")


# --------------------------------------------------------------------------- #
# duplicate review queue (ADR 0005 decisions 3-4)
# --------------------------------------------------------------------------- #
@app.get("/review-queue", response_model=ReviewQueuePage)
def list_review_queue(db: Session = Depends(get_db)):
    """Candidate-duplicate pairs still awaiting a human judgment.

    Dispositioned pairs are not listed: the queue is a worklist, and its
    history lives in the rows themselves.
    """
    try:
        rows = (
            db.execute(
                select(DuplicateReviewQueue)
                .where(DuplicateReviewQueue.status == "pending")
                .order_by(DuplicateReviewQueue.id)
            )
            .scalars()
            .all()
        )
        patient_ids = {r.patient_id_a for r in rows} | {r.patient_id_b for r in rows}
        patients = {}
        if patient_ids:
            patients = {
                p.id: p
                for p in db.execute(select(Patient).where(Patient.id.in_(patient_ids)))
                .scalars()
                .all()
            }
    except SQLAlchemyError as e:
        # Rule 3: str(e) on a statement-level error embeds the bound patients row.
        log.error("review queue: database error (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="review queue unavailable")

    items = []
    for row in rows:
        a, b = patients.get(row.patient_id_a), patients.get(row.patient_id_b)
        if a is None or b is None:
            # A queued pair whose patient row has gone is not judgeable. The FK
            # makes it unreachable today; skipping beats rendering half a pair.
            log.warning("review queue: pair %s references a missing patient", row.id)
            continue
        items.append(
            ReviewQueueItem(
                id=row.id,
                patient_a=ReviewQueuePatient.model_validate(a),
                patient_b=ReviewQueuePatient.model_validate(b),
                source=row.source,
                created_at=row.created_at,
            )
        )
    return ReviewQueuePage(items=items)


@app.post("/review-queue/{pair_id}/disposition", response_model=DispositionResponse)
def disposition_review_pair(
    pair_id: int, req: DispositionRequest, db: Session = Depends(get_db)
):
    """Record a human judgment on a candidate pair.

    Touches ``duplicate_review_queue`` and nothing else. Confirming a duplicate
    does NOT merge, alter, or delete either patient row (W2-SPEC-27) — the merge
    is a manual HIM procedure, and a wrong automated one cross-contaminates two
    people's charts (ADR 0005 decision 3).
    """
    log.info(
        "POST /review-queue/%s/disposition meta=%s",
        pair_id,
        json.dumps(disposition_log_metadata(pair_id, req)),
    )
    try:
        if db.get(DuplicateReviewQueue, pair_id) is None:
            raise HTTPException(status_code=404, detail="review pair not found")
        # The status check lives IN the write, not before it. Read-check-write
        # lets two reviewers both observe `pending` and both commit, and the
        # later commit silently replaces the first verdict and decided_by —
        # losing the audit trail of a human duplicate-patient judgment. One
        # conditional UPDATE makes exactly one of them the winner; the loser
        # matches no row and gets the same 409 a sequential retry gets.
        updated = (
            db.execute(
                update(DuplicateReviewQueue)
                .where(
                    DuplicateReviewQueue.id == pair_id,
                    DuplicateReviewQueue.status == "pending",
                )
                .values(
                    status="dispositioned",
                    disposition=req.disposition,
                    decided_by=req.decided_by,
                    decided_at=datetime.now(timezone.utc),
                )
                .returning(
                    DuplicateReviewQueue.id,
                    DuplicateReviewQueue.status,
                    DuplicateReviewQueue.disposition,
                    DuplicateReviewQueue.decided_by,
                    DuplicateReviewQueue.decided_at,
                )
            )
            .mappings()
            .first()
        )
        if updated is None:
            # Not an error to retry — someone else already judged this pair,
            # either before this request or inside it. Their decision stands.
            db.rollback()
            raise HTTPException(status_code=409, detail="review pair already dispositioned")
        db.commit()
    except SQLAlchemyError as e:
        db.rollback()
        log.error(
            "review queue: failed to record disposition for pair %s (%s)",
            pair_id,
            type(e).__name__,
        )
        raise HTTPException(status_code=503, detail="review queue unavailable")

    return DispositionResponse.model_validate(dict(updated))


# Rows sharing the new row's SSN, normalized in the WHERE clause rather than by
# pulling every SSN-bearing patient into this process. There is no stored
# normalized column and this adds none: the expression mirrors
# matching.normalize_ssn's digits-only rule over the existing plaintext column,
# so evaluating the match key creates no new copy of an SSN anywhere (W2-SPEC-24).
# It is a sequential scan — D8 (the schema has zero indexes) is a registered
# deliberate defect and is not fixed here.
_SSN_MATES_SQL = text(
    "SELECT id, name, dob, ssn, address FROM patients "
    r"WHERE ssn IS NOT NULL AND regexp_replace(ssn, '\D', '', 'g') = :normalized"
)


def _evaluate_match_key(db: Session, patient_id: int, demo: Demographics) -> None:
    """Flag candidate duplicates for the just-registered patient (ADR 0005).

    Never raises. The patient row is already committed by the caller, and
    matching must not become a dependency of registering a human being — a
    matcher fault records itself and gets picked up by the retroactive pass
    (retro_match.py) instead of failing a registration (W2-SPEC-23, 32).

    Only candidate components produce pairs, so rows that merely share an SSN
    without corroborating demographics — ambiguous or non-mergeable — are never
    queued as duplicates (W2-SPEC-21). The insert set is deliberately not
    limited to pairs involving the new row: a new row can complete a clique
    among rows that were previously ambiguous, and those pairs are genuinely
    newly queueable.
    """
    try:
        normalized = matching.normalize_ssn(demo.ssn or "")
        if not matching.is_valid_ssn(normalized):
            # Tier 2 (fuzzy name + DOB) is deferred, so a row without a usable
            # SSN is matched by nothing — and we do not query for it either.
            return

        rows = db.execute(_SSN_MATES_SQL, {"normalized": normalized}).mappings().all()
        pairs = matching.candidate_pairs(rows)
        for patient_id_a, patient_id_b in pairs:
            # ON CONFLICT DO NOTHING against uq_review_pair is the idempotency
            # mechanism (W2-SPEC-31): a re-registration re-derives the same
            # pairs, and a pair that a human already dispositioned is never
            # re-queued (status is deliberately not part of the key).
            db.execute(
                pg_insert(DuplicateReviewQueue.__table__)
                .values(
                    patient_id_a=patient_id_a,
                    patient_id_b=patient_id_b,
                    source="intake",
                )
                .on_conflict_do_nothing(constraint="uq_review_pair")
            )
        db.commit()
        # patient_id and counts only — PHI policy rules 2-3. Never the SSN, the
        # sibling ids' demographics, or anything read off a patients row.
        log.info(
            "intake: match key evaluated for patient %s ssn_mates=%s candidate_pairs=%s",
            patient_id,
            len(rows),
            len(pairs),
        )
    except Exception as e:
        # Broad on purpose. Class name only: a statement-level SQLAlchemy error
        # stringifies with [SQL: ...] [parameters: (...)], i.e. the bound
        # patients row (name, DOB, SSN) — the same rule as _create_registration.
        log.error(
            "intake: match key evaluation failed for patient %s (%s)",
            patient_id,
            type(e).__name__,
        )
        _record_match_failure(db, patient_id, type(e).__name__)


def _record_match_failure(db: Session, patient_id: int, error_class: str) -> None:
    """Record that this patient was registered without a match-key check.

    Without this row the failure is invisible: the registration succeeded, so
    nothing else marks the patient as unchecked, and a matcher outage would
    leave an untraceable window of unmatched registrations (W2-SPEC-32).
    retro_match.py reads this table and re-evaluates those rows.

    Its own guarded transaction — the failing evaluation above may have left
    the session dirty, and a second failure here must still not affect the 201.
    """
    try:
        db.rollback()
        db.add(MatchEvaluationFailure(patient_id=patient_id, error_class=error_class))
        db.commit()
    except Exception as e:
        db.rollback()
        log.error(
            "intake: could not record match evaluation failure for patient %s (%s)",
            patient_id,
            type(e).__name__,
        )


def _verify_eligibility_guarded(ins: Optional[Insurance]) -> Optional[dict[str, Any]]:
    """Verification must never fail a completed registration (E4-SPEC-4).

    _verify_eligibility deliberately lets an unexpected exception propagate so
    the breaker's try/finally is provably reached (tests/test_intake_breaker.py
    ::test_unexpected_exception_records_a_failure_and_never_wedges_the_breaker).
    That contract is kept; the registration just no longer rides on it — the
    rows are committed before this runs, and a fault here would otherwise turn
    a saved patient into a 500 at the desk.
    """
    try:
        return _verify_eligibility(ins)
    except Exception as e:
        # Class only (PHI policy rule 3): an httpx exception embeds the failing
        # URL, which carries insurance_id=<member_id> as a query param.
        log.error("intake: eligibility verification failed unexpectedly (%s)", type(e).__name__)
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}


def _verify_eligibility(ins: Optional[Insurance]) -> Optional[dict[str, Any]]:
    if ins is None or not ins.member_id:
        return None

    # ADR 0010 / RIV-141: bounded best-effort verification, gated by an
    # intake-side circuit breaker. The timeout caps ONE registration's
    # worker-hold; the breaker caps the *sustained* cost, so a wedged
    # eligibility-service stops charging every front-desk save the full timeout
    # (adversarial review r4). Verification is best-effort either way — the
    # patient is already committed by the caller.
    try:
        _breaker.before_call()
    except EligibilityBreakerOpen:
        # Known-bad dependency: skip the outbound call entirely. No member_id in
        # this message (PHI policy rule 3).
        log.warning("intake: eligibility verification skipped, circuit open")
        return {"active": None, "status": "pending", "reason": "verification deferred"}

    # An admitted caller MUST record an outcome, including on an unexpected
    # exception — a half-open probe that records neither wedges the breaker shut.
    healthy = False
    try:
        result, healthy = _query_eligibility(ins)
    finally:
        if healthy:
            _breaker.record_success()
        else:
            _breaker.record_failure()
    return result


def _query_eligibility(ins: Insurance) -> tuple[dict[str, Any], bool]:
    """
    Call eligibility-service and shape the result.

    Returns (payload, healthy). `healthy` reports whether the DEPENDENCY is worth
    calling again — it drives the breaker and is never a coverage verdict. Two
    independent questions decide it, and conflating them is what earlier rounds
    got wrong:

      1. Was the answer USABLE? A definitive active/inactive is; so is a 4xx,
         which means eligibility-service rejected THIS request rather than
         failing (see the non-2xx branch). A timeout, a transport error, a 5xx,
         an unparseable body, or a shaped 2xx carrying no coverage verdict is not.
      2. Was it CHEAP? This breaker exists to bound how long a bad dependency
         holds intake workers, so latency counts against it on its own —
         whatever the answer was worth. A usable answer that burned the budget is
         still returned to the caller and still records a breaker failure
         (review r6).

    Both thresholds are latency, measured intake-side, so no new cross-service
    contract is needed and a downstream change cannot mis-signal them:

      * a DEGRADED answer (no verdict) is unhealthy at/over
        ELIGIBILITY_DEGRADED_SLOW_SECONDS (~1s). eligibility-service emits the
        same {"active": null, "status": "unknown"} both when its payer breaker
        short-circuits — milliseconds, costing this worker nothing — and when it
        spent its whole payer budget on a hanging payer. Treating all of them as
        healthy (review r4) left the breaker closed during the exact outage it
        guards (review r5); latency is what tells the two apart.
      * a DEFINITIVE answer gets a longer leash — ELIGIBILITY_SLOW_ANSWER_SECONDS
        (~2s) — because a real verdict is worth waiting for. That number is the
        FLOOR of the retried band, not the ceiling of a healthy attempt: a retry
        only happens after the first attempt's read timeout burned in full, so
        anchoring any higher lets the degrade-but-keep-answering payer (which
        answers in 2-4s, every save, forever) go on reading as healthy. That is
        RIV-088's partial-outage form and it is what this threshold exists to
        catch (review r6).

    Cost is the whole rule for the fast side too, so some outage modes (a payer
    refusing connections, a bad API key) are correctly read as healthy: they pin
    no worker, so they are not the RIV-141 mechanism, and suppressing a free call
    would only delay noticing the payer's recovery.

    (The seeded time.sleep(4.2) that produced the RIV-088 "spin" was removed — a
    synthetic block no timeout could bound.)
    """
    started = time.monotonic()
    try:
        resp = httpx.get(
            f"{settings.eligibility_url}/eligibility",
            params={"insurance_id": ins.member_id},
            timeout=settings.eligibility_timeout_seconds,
        )
    except httpx.TimeoutException:
        # Payer/eligibility too slow — do not block intake; verification deferred.
        # No member_id in this message.
        log.error("intake: eligibility check timed out")
        return {"active": None, "status": "pending", "reason": "verification timed out"}, False
    except Exception as e:
        # Broad on purpose (PHI policy rule 3): never stringify an outbound
        # exception here. The request URL carries insurance_id=<member_id> as a
        # query param, and httpx embeds the failing URL in its exception message —
        # so str(e) would leak a PHI-adjacent external identifier into the log AND
        # the /intake response. Log the exception class only, return a generic
        # degraded result for any transport failure.
        log.error("intake: eligibility check failed (%s)", type(e).__name__)
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False

    # Only a 2xx eligibility-shaped body is a definitive coverage answer. A
    # non-2xx response (e.g. a 500/503 {"detail": ...} from eligibility-service)
    # or a body that isn't the expected shape is never a coverage denial — map it
    # to "unknown", never "inactive". (raw_status is the HTTP code only, never
    # member_id — safe to log.)
    #
    # Whether it counts against the breaker depends on WHOSE fault it is. A 4xx
    # means eligibility-service rejected THIS request — a 422 on a blank or
    # malformed member_id, say — which says nothing about the dependency's
    # health. Counting those would let a handful of bad registrations (a botched
    # batch import, a scanner emitting whitespace) open the circuit and strip
    # eligibility verification from every OTHER patient for the reset window.
    # 408/429 are excluded from that carve-out and 5xx is a plain dependency
    # failure, matching check.py's transient/non-transient split.
    #
    # A caller-fault answer still has to have been CHEAP to read as healthy: a 422
    # that took two seconds to arrive held this worker exactly as long as a slow
    # verdict would have, and the breaker is about worker-hold (review r6). It is
    # judged on the definitive answer's threshold — eligibility-service reached a
    # conclusion about the request, it just wasn't a coverage one.
    #
    # `cheap` is computed BEFORE the `and`, deliberately not short-circuited: a slow
    # 5xx/408/429 is already unhealthy on fault, but the latency line is exactly the
    # diagnostic an on-call reader wants during a dependency incident, so it must
    # still be emitted.
    if resp.status_code // 100 != 2:
        caller_fault = 400 <= resp.status_code < 500 and resp.status_code not in (408, 429)
        log.error("intake: eligibility returned HTTP %s", resp.status_code)
        cheap = _answered_cheaply(
            started, settings.eligibility_slow_answer_seconds, "with an HTTP error"
        )
        return (
            {"active": None, "status": "unknown", "reason": "eligibility check failed"},
            caller_fault and cheap,
        )
    try:
        body = resp.json()
    except Exception:
        log.error("intake: eligibility returned a non-JSON body")
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False
    if not isinstance(body, dict) or ("status" not in body and "active" not in body):
        # A 2xx body that isn't eligibility-shaped — treat as degraded, not inactive.
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}, False

    # `active` is the authoritative tri-state (ADR 0010); `status` only carries
    # the finer detail, so DERIVE status from the boolean rather than trusting
    # whatever string the body supplied. Identity tests, because `None` is falsy
    # but is not False: a body carrying no boolean verdict must read "unknown".
    # Reading it as "inactive" would tell the front desk a patient is uninsured
    # because of an outage (the r3 misclassification, one layer down); reading it
    # as "active" on the strength of the string alone — a {"status": "active"}
    # with no `active` key, from a captive portal or a future responder — is the
    # same defect in the opposite direction, and since r5 it would also hold the
    # breaker closed while every call paid full latency.
    active = body.get("active")
    definitive = active is True or active is False
    body["status"] = ("active" if active else "inactive") if definitive else "unknown"

    if definitive:
        # A real coverage verdict is always RETURNED — a denial is never a breaker
        # failure and a slow-but-correct answer is still worth having — but the
        # dependency is only healthy if the answer did not hold this worker as long
        # as a retried payer attempt costs (review r6). Past that the payer is
        # degrading while still answering: bounded per call by the timeout,
        # unbounded in aggregate until the circuit opens — RIV-088's partial outage.
        return body, _answered_cheaply(
            started, settings.eligibility_slow_answer_seconds, "with a coverage verdict"
        )

    # Degraded: eligibility-service is up and shaped its reply, but gave no
    # coverage verdict. Judged on the tighter threshold — a reply worth nothing
    # has to be free, not merely fast — see the docstring.
    return body, _answered_cheaply(started, settings.eligibility_degraded_slow_seconds, "degraded")


def _answered_cheaply(started: float, threshold_seconds: float, kind: str) -> bool:
    """Did eligibility answer without holding this intake worker past
    `threshold_seconds`? Latency is half of the breaker's health signal (review
    r6): the other half is whether the answer was usable, which the caller has
    already decided.

    Logs the latency and a call-site literal only. Every other value in scope
    here comes out of a downstream response body, and this module never echoes
    downstream content into a log (PHI policy rule 3) — `kind` must therefore stay
    a constant, never anything read off the wire.
    """
    elapsed = time.monotonic() - started
    if elapsed < threshold_seconds:
        return True
    log.error(
        "intake: eligibility answered %s after %.2fs — counting against the circuit",
        kind,
        elapsed,
    )
    return False
