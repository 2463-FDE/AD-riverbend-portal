# w4 findings — cross-patient chart reads, chart-assembly N+1, non-expiring sessions

Written 2026-08-17 for w4 (`docs/workflow/w4.md`). Three findings from the material the
engagement owner handed over on 2026-08-16: the QA network capture, the query log for one
patient-view assembly, and the session configuration file.

**Scope.** w4 is analysis plus a prototype (w4-D-4). Nothing here is fixed by w4: the
defects below stay in the tree, and the prototype that demonstrates the boundary check
(`eval/kg/`) runs on its own synthetic sample, not on the production routes. Each finding
names where its fix is tracked.

---

## 1. IDOR — any logged-in caller reads any patient's chart (headline)

**Registry:** `docs/debt-log.md` D11 (OPEN) · fix tracked at `docs/todo.md` TODO-20 ·
approval-gated zone, `docs/landmines.md` §1.

### Reproduction (from the handed-over capture)

`docs/handover/portal.har` — two requests, one session:

| # | Request | Authorization header | Response |
|---|---|---|---|
| 1 | `GET /api/patients/1042/records` | `Bearer <patient-1042-token>` | `200` — own chart |
| 2 | `GET /api/patients/1043/records` | `Bearer <patient-1042-token>` | `200` — a different patient's chart |

The only change between the two requests is one digit in the path. The token is unchanged,
and the server does not distinguish the cases.

Both ids are live seeded charts, not gaps: `db/seed/seed.sql` seeds 255 patients, and 1042
(Maria Gonzalez) and 1043 (James O'Brien) are adjacent rows in that set (w4-D-14). The
capture is a read of real chart data on this system's own fixtures, not a 404 that happened
to return 200.

The behaviour is not incidental — it is stated in the code that serves it.
`services/records-service/app.py:115` carries the comment `# no ownership / authorization
check` inside `get_patient_records` (`:104`), and the gateway route that proxies it
(`services/gateway/app.py:325`) says the same: a valid session is required, but it is never
checked against `{patient_id}`.

### The two enablers

**(a) No session→patient bind.** The gateway is the only auth boundary in the estate; no
domain service has any authentication code at all. Its two guards answer two questions —
`require_session` answers *is this caller logged in*, `require_capability` (ADR 0017)
answers *does this caller's role hold `records.read`*. Neither answers *is this caller
entitled to this patient*, and no third guard exists. The integration test that would catch
it is present and `xfail`ed on purpose
(`tests/integration/test_records_flow.py:52`, `tests/README.md:54`).

There is a structural reason the bind is not a small patch: there is no patient principal to
bind to. `config/roles.yaml` declares staff roles only, and patient authentication does not
exist (TODO-20). A session today identifies a *staff user*, so "does the session own this
chart" is not yet a question the system can express. That is why w4 demonstrates the check
on a simulated principal in `eval/kg/` (w4-D-9) rather than landing it live.

**(b) Sequential, guessable ids.** `db/schema.sql:34` declares
`id SERIAL PRIMARY KEY, -- sequential, exposed in record URLs`, and the URL carries that
primary key directly. Guessing is not required — walking is enough. In the seeded estate the
255 patients span ids 1042–1851, so a caller who knows one id can enumerate the whole
population in 810 requests, with roughly a 31% hit rate on any single blind guess in that
span; adjacent hits like the captured 1042 → 1043 are common. Neither enabler is sufficient
alone: opaque ids without a bind would be security by obscurity, and a bind would make id
shape irrelevant. The fix is the bind; the id shape sets how cheap exploitation is.

### Exposure set — the swept 23-route table (sized per `docs/landmines.md` §1, not re-fixed here)

§1 requires the D11 fix to be sized against **every** route with the same property. Three
impl-gate rounds proved that an example list cannot stay complete — a route nobody listed is
simply absent and the "every route" claim silently lies (missed at r1, r3, r4). So the sized
set is not a list: it is a **classification-complete sweep of every one of the gateway's 23
declared `@app.` routes**, each classified in-set or excluded, and pinned by
`tests/test_w4_exposure_sweep.py` (w4-D-20) — a route added or missed reddens the suite
rather than waiting for a fourth manual catch.

Membership follows a two-clause property predicate read off the route's own signature, never
a registry (w4-D-30): a route is **in set** iff **(a)** its subject is chosen by
caller-supplied input — a path param, a query param, or a request-body field — naming a
patient or a patient-scoped resource on a walkable id, with no session→patient bind,
regardless of method and regardless of whether the response carries PHI; **or (b)** it
reaches data spanning patients by construction, with no per-patient narrowing at all.

This is **classification-complete, not verdict-correct** (w4-D-24): the sweep forces every
route to be classified and the test guards the partition against drift, but whether a given
route's verdict is *right* stays the human review — a route parked as excluded with a wrong
reason still passes green. `tests/test_w4_exposure_sweep.py` also pins this table, so when
the TODO-20 session→patient bind lands it must update that test.

| Method | Path | In set | Reason |
|---|---|---|---|
| GET | /patients/{patient_id} | (a) | path `patient_id`, `patients.read`, no bind — returns `PatientDetail` with plaintext `ssn`, `dob`, `address` (`records-service/schemas.py:18-32`), gateway `:320` |
| GET | /patients/{patient_id}/records | (a) | path `patient_id`, `records.read`, no bind — the captured route (`records-service/app.py:104`, gateway `:325`) |
| GET | /patients/{patient_id}/relevant-records | (a) | path `patient_id`, `records.read`, no bind — same property, inherited when W2 landed it (`records-service/app.py:194`, gateway `:332`) |
| GET | /appointments | (a) | query `patient_id`, `schedule.read`, no bind — returns `AppointmentOut` (free-text `reason`, `provider`, `location`, `scheduled_for`, `scheduling-service/schemas.py:27-38`), gateway `:365` |
| POST | /appointments | (a) | body `patient_id`, `appointments.write`, no bind — books against any patient's id, gateway `:374` |
| POST | /appointments/{appointment_id}/cancel | (a) | path `appointment_id`, `appointments.write`, no bind — any holder cancels any patient's appointment, gateway `:379` |
| POST | /review-queue/{pair_id}/disposition | (a) | path `pair_id`, `patients.write`, no bind — files a two-charts-are-one-person judgment on a sequential id, gateway `:284` |
| POST | /roi/requests | (a) | body `patient_id`, `disclosures.write`, no bind — opens a disclosure request against any patient, gateway `:401` |
| POST | /roi/requests/{request_id}/fulfill | (a) | path `request_id`, `disclosures.write`, no bind — fulfils on a sequential id (substantively D12's), gateway `:406` |
| GET | /patients | (b) | name search across all patients — hands out the very ids the walk needs, gateway `:305`; already in `docs/landmines.md` §1 |
| GET | /records/search | (b) | record search across all patients — e6 escaped the metacharacters and capped the result set (`e53cd81`, e6-SPEC-1/2/5), but the bounded page is still not patient-scoped, so a page of other patients' record bodies stays reachable — that residue is D11's, gateway `:343`; already in §1 |
| GET | /roi/requests | (b) | `patient_id` optional — returns disclosure records across patients under `disclosures.read`, gateway `:391`; already in §1 (and D12) |
| GET | /review-queue | (b) | candidate duplicate pairs across all patients with name + dob, `patients.write`, no per-patient narrowing (`intake-service/schemas.py:119-142`), gateway `:279` — the fourth (b) member, w4-D-35 |
| GET | /healthz | excluded | liveness/readiness probe, unauthenticated, no patient data, gateway `:179` |
| POST | /login | excluded | auth entry — the subject is credentials, not a patient, gateway `:208` |
| POST | /logout | excluded | tears down the caller's own session, gateway `:237` |
| GET | /me | excluded | returns the caller's own identity from the session, self-scoped, gateway `:243` |
| POST | /intake | excluded | creates a new registration — no caller-supplied selector onto an existing chart, gateway `:251` |
| GET | /eligibility | excluded | payer 270/271 coverage check on a caller-supplied `insurance_id` — reaches no stored chart, eligibility-service has no DB, gateway `:260` |
| GET | /slots | excluded | open scheduling slots, optional `provider_id` — not patient-scoped, no cross-patient PHI, gateway `:351` |
| POST | /ai/intake-instructions | excluded | closed-vocabulary intake facts → checklist — no existing-patient subject, gateway `:632` |
| POST | /ai/visit-chat | excluded | binds via `visit_memory_get(visit_id, owner)` — reaches only the caller's own visit memory (the counter-example), gateway `:1058` |
| POST | /hl7/ingest | excluded | inbound HL7 from an external sender — no caller-supplied patient selector onto an existing chart, gateway `:1260` |

The set the fix must be sized against is the 13 in-set routes above; `docs/landmines.md` §1
keeps `GET /patients`, `GET /records/search` and `GET /roi/requests` as its named
by-construction examples and now points at this swept table as the sized set (w4-D-23).
`docs/debt-log.md` D11 carries the same set as a registry row.

Amplifier, tracked separately: the portal stores the bearer token in `localStorage`
(`frontend/app/lib/session.ts:29-30`, `docs/debt-log.md` cross-cutting table). Combined with
finding 3 below, one XSS yields a credential that never expires and, through D11, reads
every chart in the estate.

**w4 does not re-fix any of these** (w4-D-4). The live session→patient bind lands with
TODO-20, after a patient principal exists.

---

## 2. N+1 on chart assembly (note)

**Registry:** `docs/debt-log.md` D8 · production fix out of w4's scope (w4-D-5) and of e6's.

The handed-over query log — `SELECT * FROM records WHERE encounter_id = ?` run 37 times for
one patient view, plus a full-table scan behind records search — matches the code exactly.
`services/records-service/app.py:104-140` fetches the patient's encounters in one query,
then loops:

```
# N+1: one extra query per encounter (deliberate — do not collapse to a join)
for enc in encounters:                      # app.py:128-129
```

So one chart assembly costs `1 + E` queries for `E` encounters. The count is read straight
from the source: the per-encounter query "runs 37 times (one per encounter)", so the
captured chart has **37 encounters** and costs 38 queries — one for the encounter list plus
37 per-encounter reads. The reported page-load metric — assembled patient view p95 **3.8s,
almost all DB time** — is consistent with per-query latency multiplied by encounter count
rather than with any single slow query.

**Why it does not hold for a real chart.** The cost is linear in encounter count, and
encounter count is unbounded: it grows for exactly the patients whose charts matter most —
chronic care, long tenure, frequent visits. On the 50+-encounter chart the owner asked
about, the same code path issues 51+ round trips where the data needs one pass; at the
captured p95 that is a page that gets slower every time the patient is seen. Worse, the
degradation is invisible in aggregate metrics dominated by short charts — the median chart
stays fast while the sickest patients' charts fall off. A `JOIN` or `selectinload` collapses
it to two queries independent of `E`, which is what `eval/kg/assemble.py` demonstrates on the
sample: three batch retrievals for a 53-encounter chart, unchanged from a 2-encounter one.

The second half of the log line — the full-table scan on records search — is the
`ILIKE '%q%'` with no supporting index at `records-service/app.py:335-370`. e6 bounded the
*result set* there (finding 1's table); the zero-index scan itself is deliberate and stays
(e6-D-2).

The production route is **not** refactored by w4: the per-encounter loop is a planted defect
carrying an explicit "do not collapse to a join" marker, and removing it silently would
destroy the exercise (`CLAUDE.md` §0, `docs/landmines.md` §1).

---

## 3. Sessions never expire (secondary)

**Registry:** `docs/debt-log.md` cross-cutting table, row "Sessions never expire, single
role, no MFA" (OPEN, approval-gated, unscheduled) · finding only per w4-D-7.

`services/gateway/auth.yaml:2` declares:

```
SESSION_TIMEOUT: never      # tokens issued at login do not expire
```

Two things are true about that line, and the second is the finding.

**The file is inert.** Nothing in the tree parses `auth.yaml` — it is a declarative artifact
with no reader. Editing it changes nothing, which is why w4 does not edit it.

**The behaviour it describes is real, and hardcoded.** `services/gateway/security.py:275-279`
creates the session with `hset` and no `EXPIRE`:

```
def create_session(username: str, role: str) -> str:
    token = uuid.uuid4().hex
    # NOTE: no expiry / TTL is set, so sessions never expire.
    _redis().hset(f"session:{token}", mapping={"username": username, "role": role})
```

A token issued at login stays valid until the Redis key is deleted by something else. There
is no idle timeout, no absolute lifetime, and no logout-invalidates-everywhere.

The operational case the owner raised is the sharp one: a clinician who walks away from a
shared workstation leaves a session that never ends. Automatic logoff is an *addressable*
HIPAA Security Rule implementation specification (45 CFR 164.312(a)(2)(iii)); "addressable"
requires a documented decision, not silence — and this is the documentation of the gap, not
a decision to accept it. Combined with finding 1, a single leaked or borrowed token reads
every chart in the estate for as long as the Redis key survives.

**No session-expiry code change is made by w4** (w4-D-7): session TTL is `docs/landmines.md`
§1 auth, and the fix is a separate scheduled auth item.
