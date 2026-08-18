"""w4 D11 exposure-set sweep — route-set closure + findings-table parity.

w4-SPEC-11 requires the IDOR fix to be sized against *every* route with the
same property. The gate loop proved three separate times (impl-gate r1/r3/r4)
that an example list cannot stay complete: a new route, or one nobody thought
of, is simply absent and the "every route" claim silently lies. So the sized
set is not a list — it is a **partition of the gateway's declared routes**,
pinned here so a route added or missed reddens the suite (w4-D-20).

Two things this file buys, and one it does not (w4-D-24):

- **Classification-completeness.** ``test_route_set_closure`` enumerates every
  declared ``APIRoute`` ``(method, path)`` and asserts it lands in exactly one
  of ``EXPOSURE_SET`` / ``EXCLUDED``. A route in neither, or a stale set entry
  for a route that no longer exists, reddens — mirroring the proxy-contract
  route-set closure (tests/test_gateway_proxy_error_contract.py:482,502,
  CLAUDE.md §4).
- **Table parity, both directions, exact cell match.** Every ``EXPOSURE_SET``
  route and every ``EXCLUDED`` route + reason has its own ``(method, path)`` row
  in the sweep table of docs/research/w4-findings.md, matched on the exact
  Method and Path *cells*, never substring containment — so ``GET /patients``
  is pinned by its own row and not by a longer sibling's (w4-D-27, w4-D-31).
  Excluded rows additionally pin the Reason cell's opening clause against the
  ``EXCLUDED`` reason string (codex r1 f2); the trailing gateway line ref is
  the one part left free to move.
- **Not verdict-correctness.** The closure forces every route to be *classified*
  and guards the set against drift; whether a given route's in-set/excluded
  verdict is *right* stays the ``gate:`` human read (w4-D-24). A route parked in
  ``EXCLUDED`` with a wrong reason still passes green.

Membership follows the two-clause property predicate (w4-D-30), read off the
route's own signature, never a registry:

  (a) the subject is chosen by caller-supplied input — a path param, a query
      param, or a request-body field — naming a patient or a patient-scoped
      resource on a walkable id, with no session→patient bind, regardless of
      method and regardless of whether the response carries PHI; **or**
  (b) it reaches data spanning patients by construction, with no per-patient
      narrowing at all.

Loading gateway/app.py pulls in its bare-named siblings (config, db, models,
security, authz); pin and restore sys.modules around the load exactly as the
mirror test does (tests/test_gateway_proxy_error_contract.py:31-46, CLAUDE.md
§6), or the copies collide with every other service's bare `config`/`db` in the
same session.
"""
import os
import re
import sys

from fastapi.routing import APIRoute

from conftest import REPO_ROOT, load_module

_PINNED = ("config", "logging_config", "db", "models", "security", "authz")
_saved = {name: sys.modules.pop(name, None) for name in _PINNED}
sys.modules["config"] = load_module("services/gateway/config.py", "gw_sweep_config")
sys.modules["logging_config"] = load_module(
    "services/gateway/logging_config.py", "gw_sweep_logging_config"
)
sys.modules["db"] = load_module("services/gateway/db.py", "gw_sweep_db")
sys.modules["models"] = load_module("services/gateway/models.py", "gw_sweep_models")
sys.modules["security"] = load_module("services/gateway/security.py", "gw_sweep_security")
sys.modules["authz"] = load_module("services/gateway/authz.py", "gw_sweep_authz")
gw = load_module("services/gateway/app.py", "gw_sweep_app")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

FINDINGS_DOC = os.path.join(REPO_ROOT, "docs", "research", "w4-findings.md")


# --- the sized set, partitioned by the two-clause predicate (w4-D-30) ------- #
# Membership is keyed on (method, path-template). Each entry's value records
# which clause admits it (in set) or the one-line reason it is out (excluded) —
# for excluded routes, the exact opening clause of the findings table's Reason
# cell, asserted by test_excluded_doc_parity.

# Clause (a): caller-supplied subject on a walkable id, no session→patient bind.
# Clause (b): cross-patient by construction, no per-patient narrowing.
EXPOSURE_SET = {
    # (a) — per-patient chart reads, the captured route and its kin
    ("GET", "/patients/{patient_id}"): "(a) path patient_id, patients.read, no bind — PatientDetail (ssn/dob/address)",
    ("GET", "/patients/{patient_id}/records"): "(a) path patient_id, records.read, no bind — the captured route",
    ("GET", "/patients/{patient_id}/relevant-records"): "(a) path patient_id, records.read, no bind — same property",
    # (a) — caller-selected patient / patient-scoped resource, other services
    ("GET", "/appointments"): "(a) query patient_id, schedule.read, no bind — AppointmentOut",
    ("POST", "/appointments"): "(a) body patient_id, appointments.write, no bind — books on any patient",
    ("POST", "/appointments/{appointment_id}/cancel"): "(a) path appointment_id, appointments.write, no bind — cancels any patient's appointment",
    ("POST", "/review-queue/{pair_id}/disposition"): "(a) path pair_id, patients.write, no bind — files a two-charts-are-one judgment",
    ("POST", "/roi/requests"): "(a) body patient_id, disclosures.write, no bind — opens a disclosure on any patient",
    ("POST", "/roi/requests/{request_id}/fulfill"): "(a) path request_id, disclosures.write, no bind — fulfils on a sequential id (D12)",
    # (b) — cross-patient by construction, no per-patient selector at all
    ("GET", "/patients"): "(b) name search across all patients — hands out the ids the walk needs",
    ("GET", "/records/search"): "(b) record search across all patients — bounded page reachable (e6 closed the metachar/LIMIT vector)",
    ("GET", "/roi/requests"): "(b) patient_id optional — disclosure records across patients under disclosures.read",
    ("GET", "/review-queue"): "(b) candidate duplicate pairs across all patients (name+dob), no per-patient narrowing (w4-D-35)",
}

EXCLUDED = {
    ("GET", "/healthz"): "liveness/readiness probe, unauthenticated, no patient data",
    ("POST", "/login"): "auth entry — the subject is credentials, not a patient",
    ("POST", "/logout"): "tears down the caller's own session",
    ("GET", "/me"): "returns the caller's own identity from the session, self-scoped",
    ("POST", "/intake"): "creates a new registration — no caller-supplied selector onto an existing chart",
    ("GET", "/eligibility"): "payer 270/271 coverage check on a caller-supplied insurance_id — reaches no stored chart, eligibility-service has no DB",
    ("GET", "/slots"): "open scheduling slots, optional provider_id — not patient-scoped, no cross-patient PHI",
    ("POST", "/ai/intake-instructions"): "closed-vocabulary intake facts → checklist — no existing-patient subject",
    ("POST", "/ai/visit-chat"): "binds via visit_memory_get(visit_id, owner) — reaches only the caller's own visit memory (the counter-example)",
    ("POST", "/hl7/ingest"): "inbound HL7 from an external sender — no caller-supplied patient selector onto an existing chart",
}


def _declared_routes():
    """Every declared gateway route as (method, path-template), the way the
    proxy-contract closure enumerates them (CLAUDE.md §4)."""
    declared = set()
    for r in gw.app.routes:
        if not isinstance(r, APIRoute):
            continue
        for method in r.methods - {"HEAD", "OPTIONS"}:
            declared.add((method, r.path))
    return declared


def test_route_set_closure():
    """Every declared route partitions into exactly one of EXPOSURE_SET /
    EXCLUDED. A new or renamed route lands in neither and reddens here; a stale
    set entry that no longer names a real route reddens too — so the sized set
    the gate reads cannot silently fall behind the gateway (w4-D-20)."""
    declared = _declared_routes()
    classified = set(EXPOSURE_SET) | set(EXCLUDED)

    assert set(EXPOSURE_SET).isdisjoint(EXCLUDED), (
        "a route is in both partitions: "
        f"{sorted(set(EXPOSURE_SET) & set(EXCLUDED))}"
    )
    unclassified = declared - classified
    stale = classified - declared
    assert not unclassified, f"gateway route in neither partition: {sorted(unclassified)}"
    assert not stale, f"set entry names no declared route: {sorted(stale)}"


# --- findings-table parity (w4-D-27 both directions, w4-D-31 exact cells) ---- #

_ROW = re.compile(r"^\|(.+)\|\s*$")


def _sweep_table_rows():
    """(method, path, verdict, reason) for each body row of the findings sweep
    table.

    The table is located by a header row carrying the Method, Path and 'In set'
    columns; parsing is on exact cell content, so a path that prefixes another
    declared route is pinned by its own row, never a longer sibling's (w4-D-31).
    """
    with open(FINDINGS_DOC, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    header_idx = None
    for i, line in enumerate(lines):
        m = _ROW.match(line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        lowered = [c.lower() for c in cells]
        if "method" in lowered and "path" in lowered and "in set" in lowered:
            header_idx = i
            col = {
                name: lowered.index(name)
                for name in ("method", "path", "in set", "reason")
            }
            break
    assert header_idx is not None, "no sweep table (Method | Path | In set) in findings doc"

    rows = []
    for line in lines[header_idx + 2 :]:  # skip header + separator
        m = _ROW.match(line)
        if not m:
            break
        cells = [c.strip() for c in m.group(1).split("|")]
        if set(cells[0]) <= set("-: "):  # a second separator, if any
            continue
        method = cells[col["method"]].upper()
        path = cells[col["path"]].strip("`")
        verdict = cells[col["in set"]].lower()
        reason = cells[col["reason"]]
        rows.append((method, path, verdict, reason))
    return rows


def test_exposure_set_doc_parity():
    """Every EXPOSURE_SET route has its own in-set row in the sweep table, and
    the table's in-set rows are exactly EXPOSURE_SET — neither drifts from the
    other (w4-D-27 forward direction, w4-D-31 exact-cell)."""
    rows = _sweep_table_rows()
    doc_in_set = {(m, p) for m, p, v, _ in rows if v in ("a", "b", "(a)", "(b)")}
    assert doc_in_set == set(EXPOSURE_SET), (
        f"in-set table drift: missing_from_table={sorted(set(EXPOSURE_SET) - doc_in_set)} "
        f"extra_in_table={sorted(doc_in_set - set(EXPOSURE_SET))}"
    )


def test_excluded_doc_parity():
    """Every EXCLUDED route has its own excluded row in the sweep table, and the
    table's excluded rows are exactly EXCLUDED — the excluded half of the
    partition is pinned too, not just EXPOSURE_SET (w4-D-27 reverse direction).

    The Reason cell is pinned too (codex r1 f2): each excluded row's reason must
    open with the reason string EXCLUDED carries, backticks ignored, so the
    stated grounds for exclusion cannot drift out of the table silently. The
    trailing gateway line ref stays unpinned (it moves with unrelated gateway
    edits), and whether the reason is *right* stays the human read (w4-D-24)."""
    rows = _sweep_table_rows()
    doc_excluded = {(m, p): r for m, p, v, r in rows if v in ("excluded", "no", "out")}
    assert set(doc_excluded) == set(EXCLUDED), (
        f"excluded table drift: missing_from_table={sorted(set(EXCLUDED) - set(doc_excluded))} "
        f"extra_in_table={sorted(set(doc_excluded) - set(EXCLUDED))}"
    )
    drifted = {
        key: {"pinned": EXCLUDED[key], "table": reason}
        for key, reason in doc_excluded.items()
        if not reason.replace("`", "").startswith(EXCLUDED[key])
    }
    assert not drifted, f"excluded reason drift: {drifted}"
