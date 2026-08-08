"""
Retroactive duplicate-match pass over existing patient rows (ADR 0005 decision 4).

Flagging duplicates at chart-create only helps charts created from now on. Every
duplicate already in the table — starting with the Maria cluster behind RIV-160
— is invisible until something goes and looks. This is that something.

Run it inside the container, not through an HTTP route:

    docker compose exec intake-service python retro_match.py

Deliberately a CLI. A route would need a capability, an authz test, and a
gateway hop for an operation that is run by hand a handful of times and reads
every patient row; a `docker compose exec` adds no new authz surface at all.
See docs/runbook.md for the operator procedure.

What it does NOT do: create, modify, or delete any patient row (W2-SPEC-30). It
SELECTs patients and INSERTs queue rows. Merging charts is a manual HIM
procedure — dispositioning a queue entry records a human judgment, nothing more.

Re-running it is expected and safe: every insert carries ON CONFLICT DO NOTHING
against the queue's ordered-pair UNIQUE constraint, so a second pass queues
nothing, and a pair a human already dispositioned is never re-queued
(W2-SPEC-31).

It is also the only reader of ``match_evaluation_failures``. Without that the
table would be write-only — the D2 failure mode inverted — and "the failure is
recorded" would mean "visible in psql to whoever thinks to look".
"""
import sys
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

import matching
from db import SessionLocal
from models import DuplicateReviewQueue, MatchEvaluationFailure, Patient


def run(db) -> Dict[str, Any]:
    """Classify every patient row and queue the candidate pairs. Read-only over
    patients; returns the counts the operator summary is rendered from."""
    rows = (
        db.execute(
            select(Patient.id, Patient.name, Patient.dob, Patient.ssn, Patient.address)
        )
        .mappings()
        .all()
    )

    # Group by normalized SSN. The matcher would do this itself, but doing it
    # here is what lets the summary report how many rows the match key could not
    # be applied to at all — a row with no usable SSN is not "checked and clean",
    # it is unchecked, and tier 2 (which would catch it) is deferred.
    groups: Dict[str, List[Any]] = {}
    evaluated_ids = set()
    without_usable_ssn = 0
    for row in rows:
        raw = row["ssn"] or ""
        if matching.is_valid_ssn(raw):
            groups.setdefault(matching.normalize_ssn(raw), []).append(row)
            evaluated_ids.add(row["id"])
        else:
            without_usable_ssn += 1

    pairs: List[tuple] = []
    for group in groups.values():
        pairs.extend(matching.candidate_pairs(group))
    pairs.sort()

    queued = 0
    for patient_id_a, patient_id_b in pairs:
        result = db.execute(
            pg_insert(DuplicateReviewQueue.__table__)
            .values(
                patient_id_a=patient_id_a,
                patient_id_b=patient_id_b,
                source="retroactive",
            )
            .on_conflict_do_nothing(constraint="uq_review_pair")
        )
        queued += result.rowcount or 0
    db.commit()

    failures = (
        db.execute(
            select(MatchEvaluationFailure.patient_id, MatchEvaluationFailure.error_class)
        )
        .mappings()
        .all()
    )
    failure_counts: Dict[str, int] = {}
    failed_ids = set()
    for failure in failures:
        failure_counts[failure["error_class"]] = failure_counts.get(failure["error_class"], 0) + 1
        failed_ids.add(failure["patient_id"])

    re_evaluated = failed_ids & evaluated_ids
    return {
        "patients_scanned": len(rows),
        "ssn_groups": len(groups),
        "without_usable_ssn": without_usable_ssn,
        "candidate_pairs": len(pairs),
        "pairs": pairs,
        "queued": queued,
        "failure_counts": failure_counts,
        "failures_re_evaluated": len(re_evaluated),
        "failures_still_unevaluated": len(failed_ids - evaluated_ids),
    }


def render(summary: Dict[str, Any]) -> str:
    """Operator-facing summary. Patient ids, exception class names and counts
    only — patient_id is the allowlisted identifier (PHI policy rule 2), and
    this output gets captured into terminals, tickets and runbooks.
    """
    lines = [
        "retroactive duplicate-match pass (ADR 0005 tier 1 — flag, never merge)",
        f"  patients scanned:          {summary['patients_scanned']}",
        f"  ssn groups evaluated:      {summary['ssn_groups']}",
        f"  rows with no usable ssn:   {summary['without_usable_ssn']} (tier 2 deferred — unchecked)",
        f"  candidate pairs found:     {summary['candidate_pairs']}",
        f"  queue rows inserted:       {summary['queued']} (pairs already queued are left alone)",
    ]
    if summary["pairs"]:
        lines.append("  pairs:")
        lines.extend(f"    {a} <-> {b}" for a, b in summary["pairs"])

    lines.append("  recorded match-evaluation failures:")
    if not summary["failure_counts"]:
        lines.append("    none on record")
    else:
        for error_class, count in sorted(summary["failure_counts"].items()):
            lines.append(f"    {error_class}: {count}")
        lines.append(
            f"    re-evaluated by this pass: {summary['failures_re_evaluated']}; "
            f"still unevaluated: {summary['failures_still_unevaluated']}"
        )
    return "\n".join(lines)


def main() -> int:
    db = SessionLocal()
    try:
        print(render(run(db)))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
