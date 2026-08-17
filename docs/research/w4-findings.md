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

### Exposure set (sized per `docs/landmines.md` §1, not re-fixed here)

§1 requires the D11 fix to be sized against every route with the same property, so the list
is here even though w4 closes none of it. Most of it is already registered — `docs/landmines.md`
§1 names `GET /patients`, `GET /records/search` and `GET /roi/requests`; `docs/debt-log.md` D11
names the two per-patient chart routes. Two rows below were on neither list and are filed by w4:

| Surface | Property | Status |
|---|---|---|
| `GET /patients/{id}/records` (`records-service/app.py:104`, gateway `:325`) | the captured route; per-patient chart read, session not patient-bound | OPEN |
| `GET /patients/{id}/relevant-records` (`records-service/app.py:194`, gateway `:332`) | same property, same `records.read` capability — inherited in kind when W2 landed it, already listed in D11 | OPEN |
| `GET /patients/{id}` (gateway `:320`) | returns `PatientDetail` — plaintext `ssn`, `dob`, `address` (`records-service/schemas.py:18-32`); same id walk, `patients.read` only | OPEN — **was on neither list**; filed by w4 into `docs/debt-log.md` D11 |
| `GET /appointments?patient_id=` (`scheduling-service/app.py:71-93`, gateway `:365-371`) | same id walk against a different service: `schedule.read` only, no patient bind, returns `AppointmentOut` — free-text `reason`, `provider`, `location`, `scheduled_for` (`scheduling-service/schemas.py:27-38`). Write twin `POST /appointments/{appointment_id}/cancel` (gateway `:379`, `scheduling-service/app.py:138-139`) takes an appointment id and no patient bind either, so any `appointments.write` holder cancels any patient's appointment | OPEN — **was on neither list**; filed by w4 into `docs/debt-log.md` D11 |
| `GET /patients?q=` (gateway `:305`) | name search across all patients — not per-patient at all, so it hands out the ids the walk needs | OPEN, already in `docs/landmines.md` §1 |
| `GET /roi/requests` (gateway `:391`) | `patient_id` optional; returns disclosure records across patients under `disclosures.read` | OPEN, already in `docs/landmines.md` §1 (and D12) |
| `GET /records/search?q=` (`records-service/app.py:335`, gateway `:343`) | was the worst vector: an un-escaped `q` let `%` match every row with no `LIMIT` — one request, whole corpus, no ids needed | **Corpus-read vector CLOSED by e6** (`e53cd81`, 2026-08-17): metacharacters escaped and the result set capped (e6-SPEC-1/2/5). Search is still not patient-scoped, so a bounded page of other patients' record bodies is still reachable — that residue is D11's, not e6's |

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

So one chart assembly costs `1 + E` queries for `E` encounters: the captured 37 means 36
encounters plus the encounter query. The reported page-load metric — assembled patient view
p95 **3.8s, almost all DB time** — is consistent with per-query latency multiplied by
encounter count rather than with any single slow query.

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
