# E4 Code Plan — registration works, fails honestly, and is contract-guarded

> Status: GATED 2026-08-10
>
> **Gate record.** Gated 2026-08-10 after four rounds (17 findings, all fixed; `findings.md`
> §Gate). Round 4 was fresh-context over the whole final text; its two findings — both
> verification/measurement text, no production change behind either — were fixed and the plan
> stamped **in that same gate session by owner direction**, overriding the skill's
> never-edit-the-plan rule and the round-3 escalation's fresh-session re-gate. The two edited
> paragraphs (verification step 8, the E4-SPEC-9 decision bullet) are therefore the only part of
> this plan no cold session has read.
>
> **Residuals accepted, inherited by implementation and review without re-deriving them:**
> **E4-SPEC-4** — atomicity is per-request, not cross-service; a commit whose response is lost in
> transit leaves a patient row the operator never sees confirmed (idempotency key on `POST /intake`
> is register-first's territory, `e5`+). **E4-SPEC-25** — `VerdictBadge` renders the four-value
> eligibility vocabulary only, so an off-vocabulary degraded verdict falls into the "not checked"
> line and reads as unchecked rather than degraded.
>
> Plan maturity only. The plan header never carries delivery state (IMPLEMENTED, pushed,
> merged) — that lives in `docs/workflow/e4/pr-body.md`. The impl gate does not touch
> this header.
> Workflow stage 3 (code plan). Anchors to the frozen spec `docs/workflow/e4/spec.md`
> (E4-SPEC-1..28). Requirements: `docs/workflow/e4/requirements.md` (AGREED 2026-08-10).

## Context

Patient registration through the portal is completely non-functional on `main` and the UI
reports success. Four layers compound (`docs/debt-log.md` "Intake contract break", TODO-1):
the portal payload 422s at intake-service, `proxy_intake` (`services/gateway/app.py:252-253`)
relays that as HTTP 200 via the error-swallowing `_post` (`app.py:1245-1251`), the BFF
(`frontend/app/lib/gateway.ts`) relays status and body verbatim, and
`frontend/app/intake/page.tsx:108` guards on `!res.ok || data?.error` — a 422 body carries
`detail`, which is neither, so the success branch runs and `:115` prints a fallback string.

E4 fixes all four layers, makes the *class* impossible with one shared payload declaration
asserted from both suites, closes the endpoint-coverage gap (TODO-55) and the discarded
eligibility verdict (TODO-56), and corrects the registries that still describe the defect as
unscheduled.

Approval-gated zones deliberately touched, owner-approved at requirements stage (D-1) and
carried here: **gateway error handling** (the open half of D4) and the **`ConsentKind` PHI
control** (`services/intake-service/schemas.py:9-24`). No auth, no PHI column, no ROI
disclosure logic, no migration, no secret file. `consents.kind` is plain `TEXT` with no
`CHECK` (`db/schema.sql:121-125`), so widening the enum needs no schema change — verified
this session.

**Decisions carried into this plan** (plan-stage, owner-confirmed 2026-08-10):

- **E4-SPEC-9 (consent set equality) is satisfied by adding a fifth consent to the intake
  form: release of information (`roi_consent`).** Measured this session: the form offers four
  (`page.tsx:328-341`) and `ConsentKind` has **three** today
  (`services/intake-service/schemas.py:21-23`) — and the vocabulary this item lands is
  **five**, since §1 applies the inherited 2026-07-30 widening. Neither number matches the
  form's four, so equality is unsatisfiable without either a new form item or a spec
  amendment. `adr/0013-frontend-test-harness.md:218-247` (Superseded) hit the same wall on
  2026-07-31 and retracted equality in favour of subset + literal pin. The owner chose the form
  item instead: the spec stays frozen as written and the vocabularies match on both sides. Risk
  named in Landmines/risk — an intake-time `roi_consent` is **not** a 45 CFR 164.508
  authorization and nothing may read it as one (D12 stays open, untouched).
- **The shared payload declaration is one JSON file, `contracts/intake-registration.json`,**
  read by both suites — pytest via a path from the repo root, Vitest via `node:fs` with a
  relative URL. New top-level directory, language-neutral, no build step. Not under `tests/`
  (the portal suite would be reaching into the pytest tree) and not under `frontend/`
  (the reverse).
- **The gateway registration bound is a new `INTAKE_TIMEOUT_SECONDS`, default 30s** — the same
  number `_post` hardcoded, so the bound does not move, but now configured and pinned. The
  pinning invariant goes in `tests/test_eligibility_budget_alignment.py`, the established home
  for cross-service budget alignment, checked against **both** sources of truth (code defaults
  and `.env.example`) per that file's convention.
- **Value-rejection is HTTP 400 and 422; every other non-2xx is a system failure.** That is the
  category E4-SPEC-6/7 branch on, carried as status class only (E4-SPEC-14, bounded by
  E4-SPEC-16).
- **Registration becomes one database transaction** (patient + coverage + consents, one
  commit), with the ADR 0005 match-key hook and eligibility verification both **after** it —
  preserving the property that neither can block or fail a registration.
- **A live document that names a deleted symbol is retargeted; a dated decision record is
  amended, never rewritten.** `docs/phi-logging-policy.md` and `docs/debt-log.md` are live
  registers and are edited in place; `adr/0010-eligibility-resilience.md` takes a dated
  `> Amended` blockquote per `adr/_template.md`. `docs/workflow/**` delivery records are frozen
  and are not touched at all. This is what bounds verification step 14's grep.
  **Self-consistency, and it is a real trap:** every one of those edits must land *without*
  restating the dead name — no "formerly `_create_patient`", no "`_create_coverage` is now
  …" — or the plan's own step 14 goes red on the plan's own upkeep. The retargeted rows and
  the ADR blockquote carry the *finding, the blast radius and the date* forward and name only
  `_create_registration`; the old names survive in `git log` and in the frozen `docs/workflow/`
  records, which is where a superseded symbol belongs.
- **The ADR 0005 ordering test is re-bound on a first-commit-only marker, not on `flush()`
  and not on an unguarded `commit()`.** `_create_registration` calls neither `refresh()` (what
  the stub keys on today) nor `commit()` uniquely — `_evaluate_match_key` commits too. The
  mechanism and the reason each alternative fails are in §2.
- **The portal sends `created_via: "self_service"` explicitly** and omits only `notes` (not a
  patient-entered field). The contract declares the omission, and pytest asserts every omitted
  key is optional in the schema, so `portal_omits` cannot become an escape hatch.

## Scope map (spec → change)

| SPEC | Change |
|------|--------|
| E4-SPEC-1 | Portal sends the schema's shape (`demographics.name`, `payer_name`, `consents` as a list of kinds); intake writes the patient row |
| E4-SPEC-2 | Portal sends `insurance: null` when every insurance field is blank, the object otherwise; intake's existing `_create_coverage` write moves into the single registration transaction |
| E4-SPEC-3 | Form replaces the free-text "Policy holder name" with an "I am the policy holder" checkbox; nothing policy-holder-shaped is sent or stored |
| E4-SPEC-4 | `_create_registration` — one transaction, one commit, rollback on any failure; consent-write errors stop swallowing |
| E4-SPEC-5 | Success branch requires a numeric `patient_id`; the "Intake submitted successfully." fallback is deleted |
| E4-SPEC-6 | 400/422 → "not saved, correctable at the desk" |
| E4-SPEC-7 | any other non-2xx, or a 2xx with no `patient_id` → "not saved, system failure" |
| E4-SPEC-8 | All five collected consents map to `ConsentKind` members and are written in the registration transaction |
| E4-SPEC-9 | `ConsentKind` widens by `financial_responsibility_ack` + `communications_opt_in`; the form gains the ROI consent; the contract file declares the one vocabulary both sides assert against |
| E4-SPEC-10 | Unchanged pydantic boundary behaviour (unknown kind → 422), re-proved at the endpoint and now with nothing written (rests on E4-SPEC-4) |
| E4-SPEC-11..14 | `proxy_intake` moves from `_post` to `_post_checked` |
| E4-SPEC-15,16 | Inherited from `_post_checked`: exception **class** only in the log, generic detail when the downstream body's `detail` is not a plain string (FastAPI's 422 body is a list, so no field names and no `input` values relay) |
| E4-SPEC-17,18 | New `settings.intake_timeout_seconds` (30s) passed to `_post_checked`; invariant test pins it ≥ intake's `ELIGIBILITY_TIMEOUT_SECONDS` + margin from both sources, and a compose-topology guard closes the per-service / scoped-template override vectors those two sources cannot see |
| E4-SPEC-19 | New `contracts/intake-registration.json` |
| E4-SPEC-20 | `tests/test_intake_payload_contract.py` (pytest job) + `frontend/app/intake/payload.contract.test.ts` (frontend job) |
| E4-SPEC-21 | Both jobs already gate `docker-build` (`.github/workflows/ci.yml:135`) — either divergence reddens CI with no workflow edit |
| E4-SPEC-22,23 | New `tests/test_intake_endpoint.py` — `TestClient` over intake-service, driving `POST /intake`; `tests/README.md:56-58` stops asserting the gap is open |
| E4-SPEC-24,25 | Confirmation renders `VerdictBadge` plus an explicit not-checked line when there is no verdict in the vocabulary |
| E4-SPEC-26 | TODO-1 closed; `docs/landmines.md` §1 registration bullet rewritten as delivered |
| E4-SPEC-27 | `docs/debt-log.md:333-336` JS-harness claim retracted (stale since `e1`/ADR 0018) |
| E4-SPEC-28 | TODO-55, TODO-56 closed; D4's follow-up line records the registration half delivered and the remaining thirteen routes deferred to `e5` |
| — (registry upkeep) | `CLAUDE.md` §5 registration paragraph and §6 baseline count self-corrected in the same PR; `docs/phi-logging-policy.md`'s register rows retargeted off the three deleted functions and its `_post`/`_get` row narrowed to the thirteen remaining routes; `docs/debt-log.md:139` (D4 residual 3, still open) and `adr/0010:154` (dated amendment) retargeted the same way; `tests/README.md`'s closed-gap note |

## Implementation

### 1. Consent vocabulary (SPEC-8, 9)

`services/intake-service/schemas.py` — `ConsentKind` gains two members:

```python
    financial_responsibility_ack = "financial_responsibility_ack"
    communications_opt_in = "communications_opt_in"
```

Resolved 2026-07-30, inherited not reopened (requirements §2). The docstring keeps its PHI
rationale and gains the two names; the `# npp_ack | treatment_consent | roi_consent` comments
on `models.Consent.kind` (`services/intake-service/models.py:44`) and `db/schema.sql:124` are
corrected to the five. **No migration** — the column is untyped `TEXT`.

The enum is a documented PHI control, so the widening is re-proved rather than assumed inert:
`tests/test_intake_schemas.py`'s adversarial cases (free-text PHI, unknown identifier) are
re-run against the widened enum and a new case pins the members as five literals — a silent
sixth member, or a widening back to bare `str`, fails.

### 2. Single-transaction registration (SPEC-1, 2, 4, 8, 10)

`services/intake-service/app.py`. Today `_create_patient`, `_create_coverage` and
`_record_consents` each commit (the last one per consent, and swallows its error), so a fault
mid-sequence leaves a patient with no consents and a 500 at the desk — D4 residual 2,
`docs/debt-log.md:126-138`. E4-SPEC-4 decides what that request owes the caller: nothing
survives.

Replace the three committing helpers with one:

```python
def _create_registration(db: Session, req: IntakeRequest) -> int:
    """Patient + coverage + consents, or nothing (E4-SPEC-4).

    One transaction, one commit. The three writes used to commit separately —
    and a consent failure was swallowed outright — so a fault between them left
    a patient with no consent rows (docs/debt-log.md D4 residual 2).
    """
    try:
        patient = Patient(name=req.demographics.name, ...)
        db.add(patient)
        db.flush()                      # assigns the PK inside the transaction
        patient_id = patient.id         # read before commit expires the instance
        if req.insurance is not None:
            db.add(InsuranceCoverage(patient_id=patient_id, ...))
        for kind in req.consents:
            db.add(Consent(patient_id=patient_id, kind=kind))
        db.commit()
        return patient_id
    except SQLAlchemyError as e:
        db.rollback()
        # PHI policy rule 3, unchanged idiom: a statement-level DBAPIError
        # stringifies with the bound patients row (name, DOB, SSN).
        log.error("intake: failed to create registration (%s)", type(e).__name__)
        raise HTTPException(status_code=503, detail="registration store unavailable")
```

`db.py`'s session is `autoflush=False`, so the `flush()` is explicit and required.

`create_intake` becomes:

```python
    patient_id = _create_registration(db, req)
    _evaluate_match_key(db, patient_id, req.demographics)   # after the commit, never raises
    eligibility = _verify_eligibility_guarded(req.insurance)
```

Ordering is load-bearing and keeps two inherited properties intact:

- The match-key hook still runs **after** the patient row is committed, so a matcher fault can
  never block or slow a registration (ADR 0005 decision, W2-SPEC-23/32,
  `tests/test_intake_match_key.py:333-350`).

  That test binds the property through a stub, and the stub keys on a method this change
  removes from the path, so the binding is re-made rather than assumed: `_OrderedSession`
  (`:338-346`) appends its `"patient-committed"` marker from **`refresh()`** (`:339-341`),
  which `_create_registration` never calls. The marker moves to **`commit()`**, not to
  `flush()` — `flush()` fires *inside* the transaction, so keying it there would silently
  weaken the assertion from "the hook runs after the row is committed" to "after the row is
  flushed", which is not the ADR 0005 property.

  `commit()` is the right *event* but not a unique one: `_evaluate_match_key` commits on its
  own success path (`services/intake-service/app.py:350`), so an unguarded marker fires twice
  and `order` becomes `["patient-committed", "match-evaluated", "patient-committed"]` against
  the `==` assertion at `:350` — red. The marker is therefore **first-commit-only**
  (plan-stage decision, owner-confirmed 2026-08-10), which leaves the assertion text exactly
  as it stands today:

  ```python
      class _OrderedSession(_StubSession):
          def commit(self):
              # _evaluate_match_key commits too (app.py:350); only the first
              # commit is the registration boundary ADR 0005 orders the hook against.
              if "patient-committed" not in order:
                  order.append("patient-committed")
              super().commit()
  ```

  `_StubSession.refresh` (`:96-97`) becomes `flush`, so the double keeps modelling only what
  `app.py` actually calls — but **not** with the same body: `_create_registration` calls
  `db.flush()` with no arguments while `refresh(self, obj)` takes one, so keeping the body
  would raise `TypeError` on all 16 `create_intake` calls in the file. `flush()` assigns
  `NEW_ID` from what the stub already recorded in `self.added`, which is where the PK now
  comes from:

  ```python
      def flush(self):
          for obj in self.added:
              if getattr(obj, "id", None) is None:
                  obj.id = NEW_ID
  ```

  Only the patient is in `self.added` at the one `flush()` call site (coverage and consents
  are added after it), so this assigns exactly the PK `refresh()` used to. The test's
  docstring citation of `_create_patient` (`:334`) is retargeted with it.
- Eligibility verification still runs on the request thread and is still best-effort, but it
  now runs **after** the writes, so a degraded or failed verification cannot affect whether the
  patient is saved — which is what ADR 0010's comment already claims and what the new ordering
  makes true unconditionally.

`_verify_eligibility_guarded` is a thin call-site wrapper, **not** a change to
`_verify_eligibility`:

```python
def _verify_eligibility_guarded(ins):
    """Verification must never fail a completed registration (E4-SPEC-4, D4 residual 2).

    _verify_eligibility deliberately lets an unexpected exception propagate so
    the breaker's try/finally is provably reached (tests/test_intake_breaker.py
    ::test_unexpected_exception_records_a_failure_and_never_wedges_the_breaker).
    That contract is kept; the registration just no longer rides on it.
    """
    try:
        return _verify_eligibility(ins)
    except Exception as e:
        log.error("intake: eligibility verification failed unexpectedly (%s)", type(e).__name__)
        return {"active": None, "status": "unknown", "reason": "eligibility check failed"}
```

The module docstring's "Consents are inserted one at a time (a commit per consent)" bullet and
the D4 bullet are corrected in place. So is one comment in a function that **survives**:
`_evaluate_match_key`'s except block cites the deleted `_create_patient` as the reference for the
rule-3 class-only idiom (`app.py:362`), and points at `_create_registration` instead — the two
`# Rule 3 (see _create_patient)` comments at `:408` and `:426` leave with their own functions.

An unaccepted consent kind still 422s at the pydantic boundary, before any write — so
E4-SPEC-10's "reject rather than discard" is now literally true end to end, which it was not
while `_record_consents` swallowed write failures.

### 3. Gateway: failure reaches the caller as failure (SPEC-11..18)

`services/gateway/config.py` — new setting beside the AI timeouts:

```python
    # Bound on the registration fan-out (E4-SPEC-17/18). Same 30s the inherited
    # _post hardcoded, but configured and PINNED: it must never be shorter than
    # intake's own budget for the registration path (ELIGIBILITY_TIMEOUT_SECONDS,
    # 8s), or the gateway aborts a registration intake is still legitimately
    # processing. tests/test_eligibility_budget_alignment.py enforces it against
    # both this default and .env.example.
    intake_timeout_seconds = float(os.getenv("INTAKE_TIMEOUT_SECONDS", "30"))
```

`services/gateway/app.py:251-253`:

```python
@app.post("/intake")
def proxy_intake(payload: dict, session: dict = Depends(require_capability("patients.write"))):
    return _post_checked("intake", "/intake", payload, timeout=settings.intake_timeout_seconds)
```

Everything E4-REQ-4 and E4-REQ-5 need is already in `_post_checked` (`app.py:1295-1331`) and is
inherited, not rewritten: downstream 4xx/5xx relayed with their own status, `httpx.TimeoutException`
→ 504, `httpx.HTTPError` → 502, non-JSON → 502, exception **class** only in every log line, and a
`detail` taken from the downstream body only when it is a plain string. FastAPI's 422 body carries
a *list* of errors — each with the offending `input` value — so the generic-`detail` branch is what
keeps PHI out of the response (E4-SPEC-16); this gets its own negative test rather than resting on
the read.

`.env.example` gains `INTAKE_TIMEOUT_SECONDS=30` in the gateway block, with the invariant stated
in its comment. No per-service `environment:` override in `docker-compose.yml` — but that is a
convention, not a pinned one: `tests/test_compose_topology.py` pins the shared-`.env` rule for
`AI_MEMBER_ID_PREFIXES` only (`:344`, `:354`, `:363`), and the gateway *does* carry an
`environment:` block (`docker-compose.yml:83-90`). An `INTAKE_TIMEOUT_SECONDS: 4` there — or in
one of the two scoped templates the gateway loads *after* `.env` (`.env.ai-proxy`, `.env.redis`;
compose lets a later `env_file` beat an earlier one) — would defeat the E4-SPEC-17 bound with a
fully green suite, because §8's invariant test reads the code default and `.env.example` and
neither of those. So the guard is landed rather than the residual named:
`tests/test_compose_topology.py` gains a section mirroring the catalog one, keyed on
`INTAKE_TIMEOUT_SECONDS` —

```python
# --- the registration bound must reach the gateway from ONE place (E4-SPEC-17) -
# tests/test_eligibility_budget_alignment.py pins the value at its two sources of
# truth (config.py default, .env.example). A per-service `environment:` entry or a
# scoped env template overrides BOTH invisibly, so the gateway would abort a
# registration intake is still legitimately processing with the suite green.
BOUND_KEY = "INTAKE_TIMEOUT_SECONDS"


def test_the_registration_bound_is_never_set_per_service(): ...      # _environment_keys
def test_no_scoped_env_template_can_override_the_registration_bound(): ...  # .env.*.example
```

Both reuse the file's existing `_all_services()` / `_environment_keys()` helpers and its
`.env.*.example` glob. The gateway already reads the shared `.env` (`docker-compose.yml:79-82`),
so no third "must load `.env`" assertion is needed — the catalog's version of it already covers
the gateway. **Self-consistency:** that glob resolves to `.env.ai-proxy.example` and
`.env.redis.example` only — `.env.example` does not match it (measured this session) — so this
plan's own `INTAKE_TIMEOUT_SECONDS=30` in `.env.example` is exactly where the guard leaves it,
and the guard and §8's `.env.example` source do not contradict each other.

The other thirteen inherited `_post`/`_get` call sites are untouched (requirements §4, `e5`).

### 4. The shared payload declaration (SPEC-19, 20, 21)

New `contracts/intake-registration.json` — the one artifact both languages assert against:

```json
{
  "$comment": "Single source of truth for the POST /intake request contract (E4-SPEC-19). Asserted by tests/test_intake_payload_contract.py and frontend/app/intake/payload.contract.test.ts. Synthetic values only.",
  "consent_kinds": ["npp_ack", "treatment_consent", "roi_consent",
                    "financial_responsibility_ack", "communications_opt_in"],
  "request_fields": {
    "root": ["demographics", "insurance", "consents"],
    "demographics": ["name", "dob", "ssn", "gender", "address", "phone", "email", "notes", "created_via"],
    "insurance": ["payer_name", "member_id", "group_number", "plan_type"]
  },
  "portal_omits": { "demographics": ["notes"] },
  "sample_request": { "demographics": { ... }, "insurance": { ... }, "consents": [ ... ] }
}
```

`tests/test_intake_payload_contract.py` (pytest job):

1. `set(request_fields[obj])` equals the pydantic model's field names **exactly**, per model,
   both directions. This is the assertion that matters: `IntakeRequest` does not forbid extra
   keys, so `model_validate(sample_request)` alone would have accepted `insurance.carrier` and
   dropped it silently — which is exactly how the live defect got past a green build.
2. `sample_request` validates against `IntakeRequest`.
3. `set(consent_kinds)` equals `set(ConsentKind)` exactly (E4-SPEC-9, service side).
4. Every key in `portal_omits` is optional in its schema model — a required field can never be
   declared omittable.

`frontend/app/intake/payload.contract.test.ts` (frontend job) reads the same file with
`node:fs` (not an `import`, so nothing outside `frontend/` enters the TS project) and asserts:

1. `buildIntakePayload(filledForm)` has exactly `request_fields` minus `portal_omits`, per
   object (E4-SPEC-9/20, portal side).
2. The form's consent catalog maps onto `consent_kinds` — same set, no extra, none missing.
3. The all-blank insurance state yields `insurance: null` while keeping the root key
   (E4-SPEC-2).

Either side drifting reddens its own job, and both `tests` and `frontend` are already in
`docker-build`'s `needs` list (`.github/workflows/ci.yml:135`) — E4-SPEC-21 with no workflow
edit.

### 5. Portal: payload builder, error contract, verdict (SPEC-1..7, 24, 25)

New `frontend/app/intake/payload.ts` — a plain module so the contract test can call it without
mounting a component:

```ts
export const CONSENT_KIND = {
  treatment: "treatment_consent",
  privacy: "npp_ack",
  financial: "financial_responsibility_ack",
  communications: "communications_opt_in",
  roi: "roi_consent",
} as const;

export function buildIntakePayload(demo, ins, consents) { ... }
```

- `demographics.name` is `` `${first} ${last}`.trim() `` — the 422 (`Field required`) the whole
  defect starts from.
- `insurance.payer_name` carries the carrier field; the free-text `policy_holder` is gone
  (E4-SPEC-3, decided 2026-07-31 and not reopened).
- `consents` is the selected kinds as a list, not the boolean object.
- `created_via: "self_service"`; `notes` omitted.
- Every insurance field blank → `insurance: null`, so a self-pay walk-in does not get an
  empty coverage row (E4-SPEC-2's "carries insurance details").

`frontend/app/intake/page.tsx`:

- Step 1 loses the "Policy holder name" field and gains a checkbox, default **checked**:
  "I am the policy holder." `fetchInstructions` reads `ins.policy_holder_is_self` directly
  instead of deriving it from the free-text field's emptiness (`page.tsx:147`). The Review step
  shows "Policy holder — Self" / "Not the patient".
- Step 2 gains the fifth consent, optional like financial and communications:
  "Release of information — I authorize Riverbend to release my records as described in the
  Notice of Privacy Practices." Wording deliberately points at the NPP and grants no specific
  disclosure (see Landmines/risk).
- `submit()` uses `buildIntakePayload` and the new result contract:

```ts
const res = await apiFetch("/api/intake", { ... });
const data = await res.json().catch(() => null);
if (!res.ok) {
  const rejected = res.status === 400 || res.status === 422;
  setResult({ ok: false, text: rejected
    ? "Registration was not saved. Some of the details entered could not be accepted — please correct them at the desk."
    : "Registration was not saved. The system could not complete it. Your answers are still on this page — please try again shortly." });
} else if (typeof data?.patient_id !== "number") {
  // A success status that confirms no record is not a success (E4-SPEC-5).
  setResult({ ok: false, text: "<system-failure text>" });
} else {
  setResult({ ok: true, patientId: data.patient_id, eligibility: data.eligibility ?? null });
}
```

  The `data?.error` guard is **deleted**, not kept as a belt: it is live today only because the
  gateway answers 200-with-error-body, and step 3 removes that (requirements §2). The
  `data.patient_id ? … : "Intake submitted successfully."` fallback — the string operators
  actually see today — goes with it.

- The confirmation card renders the verdict (E4-SPEC-24/25), reusing W3's component:

```tsx
{verdictTone(result.eligibility?.status)
  ? <VerdictBadge eligibility={result.eligibility} />
  : <p className="rb-muted">Insurance eligibility was not checked.</p>}
```

  `VerdictBadge` covers the four-value vocabulary including the two degraded ones
  (`unknown` → "Unverified — not a denial", `pending` → "Pending verification — not a denial")
  and renders nothing outside it, so the explicit not-checked line is what keeps a null or
  unrecognised verdict visible instead of absent — E4-SPEC-25's whole point.

`frontend/app/intake/page.test.tsx` keeps its three W1 checklist tests (its `submitIntake`
helper now needs a numeric `patient_id` in the mocked 200 to reach the confirmation) and gains
the E4 cases: success only on a confirmed record, the two failure categories, and the verdict
states.

### 6. Endpoint-level intake tests (SPEC-22, 23)

New `tests/test_intake_endpoint.py` — the first `TestClient` over intake-service anywhere in
`tests/` (TODO-55). Sibling-pinning idiom from `tests/test_intake_match_key.py:27-44`;
`app.dependency_overrides[get_db]` yields a session on an in-memory SQLite engine with
`Base.metadata.create_all`. `_evaluate_match_key` is monkeypatched out (its `pg_insert`
`ON CONFLICT` is Postgres-only and it is already covered by `tests/test_intake_match_key.py`)
and `_query_eligibility` is faked, so the tests assert the route, not the hops. No new dev
dependency: SQLite is stdlib and `fastapi` + `httpx` (what `TestClient` needs) are already in
`requirements-dev.txt`.

Cases, one per behaviour the spec states of the service:

1. A full valid submission → 201, patient + coverage + all five consent rows present
   (E4-SPEC-1, 2, 8, 23).
2. An unknown consent kind → 422, and `patients`, `insurance_coverages`, `consents` are all
   empty afterwards (E4-SPEC-10, 4).
3. A consent-write failure mid-transaction → 503, and no patient or coverage row survives
   (E4-SPEC-4).
4. A verification fault after the commit → still 201, verdict reported as degraded
   (E4-SPEC-4 the other way: a completed registration is not undone by a best-effort hop).

### 7. Gateway registration tests (SPEC-11..18)

New `tests/test_gateway_intake_proxy.py`, harness copied from
`tests/test_gateway_ai_proxy.py:14-40` (module pinning + `dependency_overrides`, `httpx.post`
faked at the module seam, no Redis or DB I/O):

- intake 422 → gateway answers 422, not 200 (E4-SPEC-11, 13).
- `httpx.TimeoutException` → 504; `httpx.ConnectError` → 502 (E4-SPEC-12).
- The 422 and the 502 are distinguishable by status class alone (E4-SPEC-14).
- **Negative:** a FastAPI-shaped 422 body whose `detail` list embeds the submitted `name`,
  `ssn` and `member_id` → none of those strings appears in the gateway response body or in any
  log record; no request URL, no query string, no `str(e)` (E4-SPEC-15, 16). This is the
  landmines §3 adversarial case for the path.
- The timeout `_post_checked` receives equals `settings.intake_timeout_seconds` (E4-SPEC-17).

### 8. Budget pinning (SPEC-17, 18)

`tests/test_eligibility_budget_alignment.py` gains a sixth section, following the file's own
two-sources rule:

```python
def test_the_gateway_registration_bound_never_preempts_intake():
    # config.py defaults AND .env.example — a code default that satisfies the
    # invariant proves nothing if `cp .env.example .env` overrides it (PR #5 r5).
    for label, gw_timeout, intake_timeout in _registration_budget_sources():
        assert gw_timeout >= intake_timeout + MARGIN_SECONDS, ...
```

30s vs 8s + 1s margin. Set `INTAKE_TIMEOUT_SECONDS` below intake's budget and the suite goes
red — the observable form of E4-SPEC-18.

### 9. Registries (SPEC-26, 27, 28)

- `docs/todo.md`: TODO-1, TODO-55, TODO-56 closed with what closed them and what did not
  (`e5`), per the file's closed-entry convention.
- `docs/landmines.md` §1: the registration bullet rewritten — delivered in `e4`, the consent
  enum and gateway registration path now guarded; the approval-gated framing stays for the
  remaining thirteen routes.
- `docs/debt-log.md`: the "Intake contract break" section marked delivered with the payload
  table kept as the record; **`:333-336` retracted** — Vitest + RTL landed with `e1` (ADR 0018)
  and CI runs `npm test`, so the class is guarded, not unguarded (E4-SPEC-27). D4's follow-up
  line records the registration half done and the estate deferred to `e5`; D4 residual 2 marked
  closed by E4-SPEC-4; residual 3 (persisting the verdict) explicitly still open — and its
  opening sentence (`:139`, "`_create_coverage` writes `payer_name`/`member_id`/…only")
  retargeted at `_create_registration`, since §2 deletes the symbol while leaving the residual's
  claim true. A still-open residual naming a function that no longer exists is the same
  falsified-register failure as the `docs/phi-logging-policy.md` rows.
- `adr/0010-eligibility-resilience.md`: `:154` states the same fact in its Consequences prose
  ("`_create_coverage` never writes `insurance_coverages.status` / `verified_at`"). The decision
  and its trade are untouched and the property is unchanged by e4 — only the symbol dies — so
  this takes a dated **`> Amended 2026-08-10`** blockquote naming `_create_registration` and
  confirming D4 residual 3 still open, per the repo's ADR convention (`adr/_template.md`: never
  rewrite history in place; the amendment idiom as used in ADRs 0011, 0013, 0014). Owner-confirmed
  2026-08-10. Not a status change: ADR 0010 stays `Accepted`, and its budget values are untouched
  (§3, §8).
- `docs/phi-logging-policy.md`: the known-violations register carries one row per function for
  `_create_patient` (`:86`), `_create_coverage` (`:87`) and `_record_consents` (`:88`), all
  **FIXED 2026-08-05**. §2 deletes all three functions, so the live register would name three
  symbols that no longer exist. The three rows collapse into one for
  `_create_registration`, keeping each original's dated finding and its blast-radius note (the
  patients row for the patient write, `member_id`/`group_number` for the coverage write) as the
  record of what the class-only idiom is protecting — the fix is inherited by the merged helper,
  not re-made. The `_record_consents` row additionally records that its swallowed write failure
  is gone (E4-SPEC-4), which the row's "fixed for class completeness" note was silent about.
  Test citation stays `tests/test_intake_db_error_phi.py`, retargeted per Files touched. The
  `_post`/`_get` proxy row is edited too: it says the fix "belongs to the D4 `_post_checked`
  migration", which e4 performs for the registration route only — the row records that route as
  migrated and the other thirteen as still `_post`/`_get` and deferred to `e5`. **Register upkeep
  only** — no policy rule, threshold or status is changed.
- `tests/README.md`: `:56-58` asserts "**No test drives `POST /intake` as an endpoint** … the
  route's own wiring is unguarded (`docs/todo.md` TODO-55)" under the heading "Known coverage
  gaps (deliberate)" — the exact gap §6 closes. The bullet moves out of that list into the file's
  own "**entries left this list**" note (added 2026-08-08 for the two ADR 0010 / ADR 0017
  closures), naming `tests/test_intake_endpoint.py` as what closed it. Not a deliberate gap:
  `docs/todo.md:69` states so explicitly and `docs/landmines.md` §3's deliberate list never
  contained it — verified this session, so no §3 edit and no gap moved. The area section above
  also gains the new intake-endpoint and contract tests.
- New `docs/todo.md` entry, id **TODO-61** (highest today is **TODO-60**, verified 2026-08-10 —
  TODO-59 is the dead push-hook claim in `docs/landmines.md:127` and TODO-60 the ADR
  `LLMTimeout` enumerations, both open; ids are never reused, so re-check again at landing):
  registration now collects `roi_consent`, and nothing may read that row as a 45 CFR 164.508
  authorization while D12 is open.
- `CLAUDE.md` §5's registration paragraph and §6's baseline count self-corrected in the same PR.

## Files touched

| File | Change |
|------|--------|
| `services/intake-service/schemas.py` | `ConsentKind` + 2 members; docstring |
| `services/intake-service/app.py` | `_create_registration` replaces three committing helpers; `_verify_eligibility_guarded`; ordering; docstring corrections; `_evaluate_match_key`'s rule-3 comment retargeted off the deleted `_create_patient` (`:362`) |
| `services/intake-service/models.py`, `db/schema.sql` | consent-kind comments only (no schema change, no migration) |
| `services/gateway/app.py` | `proxy_intake` → `_post_checked` with the configured timeout |
| `services/gateway/config.py` | `intake_timeout_seconds` |
| `.env.example` | `INTAKE_TIMEOUT_SECONDS=30` + invariant comment |
| `contracts/intake-registration.json` | new — the shared declaration |
| `frontend/app/intake/payload.ts` | new — payload builder + consent map |
| `frontend/app/intake/page.tsx` | policy-holder checkbox, ROI consent, payload builder, error contract, verdict on confirmation |
| `frontend/app/intake/page.test.tsx` | success/failure/verdict cases; mocked 200 gains `patient_id` |
| `frontend/app/intake/payload.contract.test.ts` | new — portal side of the contract |
| `tests/test_intake_payload_contract.py` | new — service side of the contract |
| `tests/test_intake_endpoint.py` | new — `POST /intake` end to end (TODO-55) |
| `tests/test_gateway_intake_proxy.py` | new — status classes + the PHI negative case |
| `tests/test_intake_db_error_phi.py` | retargeted at `_create_registration`; three PHI cases kept, one added for the no-longer-swallowed consent failure |
| `tests/test_intake_match_key.py` | `_StubSession.refresh` (`:96-97`) → no-arg `flush()` assigning the PK off `self.added`; `_OrderedSession`'s (`:338-346`) `"patient-committed"` marker re-keyed from `refresh()` to a **first-commit-only** `commit()`, keeping the post-commit property and the `:350` assertion text unchanged (§2); docstring `:334` retargeted off `_create_patient` |
| `tests/test_intake_schemas.py` | widened-enum re-proof + five-literal pin |
| `tests/test_eligibility_budget_alignment.py` | gateway↔intake registration-bound invariant |
| `tests/test_compose_topology.py` | new section: `INTAKE_TIMEOUT_SECONDS` never per-service, never in a scoped env template |
| `docs/todo.md`, `docs/landmines.md`, `docs/debt-log.md`, `CLAUDE.md` | registry upkeep (§9 above) |
| `docs/phi-logging-policy.md` | register upkeep — three deleted-function rows collapse into `_create_registration`; the `_post`/`_get` row records the registration route migrated (§9) |
| `adr/0010-eligibility-resilience.md` | dated amendment blockquote at `:154` only — `_create_coverage` → `_create_registration`, property and decision unchanged (§9) |
| `tests/README.md` | the TODO-55 coverage gap moves to the closed-entries note; new tests listed by area (§9) |

## Out of scope (from requirements §7)

- **The other thirteen inherited gateway proxy call sites** — deferred to `e5` per D-3, with the
  requirement recorded as E4-REQ-11 in §4 rather than dropped. They inherit e4's frozen contract
  and carry no further decisions, so the deferral is chunked delivery rather than narrowed scope:
  the decision lands here, the remaining route contracts land there. It is not deferred because
  the portal is unaffected — §2's correction and E4-REQ-12 record that it is (corrected by D-6,
  2026-08-10). This is the rest of D4's follow-up line.
- **Persisting the eligibility verdict to `insurance_coverages.status`** — D4 residual 3. The
  verdict reaching a screen (E4-REQ-9) and the verdict reaching the database are separate needs;
  the second is a storage change on a PHI path with its own gate.
- **Register-first / out-of-band eligibility re-verification** — D4's named remaining follow-up
  (instant 201 + async verify). It is what fully closes RIV-141; it is a request-path
  architecture change, not a contract fix.
- **Capturing policy-holder identity** — the 2026-07-31 decision removes the field rather than
  storing it. Naming a non-patient policy holder needs a new `InsuranceCoverage` column plus a
  hand-synced migration; recorded in the debt log as deliberate absence.
- **D11 / IDOR and unbounded search** — adjacent PHI exposure on the records path, sized against
  its own whole set per `docs/landmines.md` §1. Nothing here touches it.
- **CI check routing** — `e3`'s chunk, untouched (`docs/workflow/e2/requirements.md` §4.3).
- **Correcting the README compliance claim** — TODO-12, human-gated by scenario design.
- **The seeded `staff`-role capability grant, the booking race, and the HL7 AL1/RXA gap** — named
  in the same landmines section and unrelated to this path.

## Verification (end-to-end)

1. **Contract, both directions.** `make test-docker` → `tests/test_intake_payload_contract.py`
   green; `cd frontend && npm test` → `payload.contract.test.ts` green (E4-SPEC-19, 20).
   **Negative:** rename `payer_name` → `carrier` in the contract file → the pytest side goes red
   (schema divergence); revert. Rename it in `payload.ts` instead → the Vitest side goes red
   (portal divergence); revert. Both halves must fire on their own (E4-SPEC-21) — this is the
   defect's own failure mode, so the check is not decorative.
2. **Consent vocabulary.** Delete `roi_consent` from the form's catalog → the Vitest set
   assertion goes red; delete `communications_opt_in` from `ConsentKind` → the pytest set
   assertion and the five-literal pin both go red; revert both (E4-SPEC-9).
3. **Registration works.** `tests/test_intake_endpoint.py` case 1 → 201 with patient, coverage
   and five consent rows (E4-SPEC-1, 2, 8, 22, 23).
4. **Nothing partial.** Cases 2 and 3 → 422 / 503 with all three tables empty (E4-SPEC-4, 10).
   **Negative:** restore the per-consent commit and case 3 goes red with an orphan patient row;
   revert.
5. **Gateway surfaces failure.** `tests/test_gateway_intake_proxy.py` → 422 stays 422, timeout
   → 504, transport → 502, and no 2xx body carries an `error` key (E4-SPEC-11, 12, 13, 14).
   **Negative:** point `proxy_intake` back at `_post` → the 422 test goes red with a 200;
   revert.
6. **No exception text.** The adversarial case: PHI planted in the downstream 422 `detail` list
   never reaches the gateway response body or any log record; no URL, no query string, no
   `str(e)` (E4-SPEC-15, 16, landmines §3).
7. **Budget pinning.** `tests/test_eligibility_budget_alignment.py` green. **Negative:** set
   `INTAKE_TIMEOUT_SECONDS=4` in `.env.example` → red from the `.env.example` source, proving
   the template is checked and not only the code default; revert (E4-SPEC-17, 18).
   **Negative, the override vectors:** add `INTAKE_TIMEOUT_SECONDS: 4` to the gateway's
   `environment:` block in `docker-compose.yml` → red from the new
   `tests/test_compose_topology.py` section while step 7's own two sources stay green, which is
   the point; revert. Same with `INTAKE_TIMEOUT_SECONDS=4` in `.env.redis.example` → red from the
   scoped-template assertion; revert (E4-SPEC-17, 18).
8. **Portal contract.** `npm test` on `page.test.tsx`: a 200 with `patient_id` → confirmation;
   a 200 **without** `patient_id` → failure; 422 → the correctable-at-the-desk message; 502/504
   → the system-failure message; neither message carries a downstream `detail`
   (E4-SPEC-5, 6, 7). The deleted fallback is then proved gone by scope, not by eye:
   `grep -rn "Intake submitted successfully" frontend/ services/ tests/` returns **nothing**.
   The scope is the live product tree on purpose, and the exclusions are the same two classes
   step 14 names: the string must survive in `docs/debt-log.md:321` — the "Intake contract
   break" record §9 keeps as the account of what this PR fixed — and in
   `adr/0013-frontend-test-harness.md:30`, a `Superseded` decision record the plan's own
   never-rewrite-history rule forbids editing. Both are records of the defect, which is
   exactly where a deleted string belongs (measured 2026-08-10: those two files and
   `page.tsx:115` are the only hits in the tree).
9. **Verdict visible.** `eligibility: {status:"active"}` → "Coverage active"; `"unknown"` and
   `"pending"` → the two not-a-denial labels; `eligibility: null` and an off-vocabulary status →
   "Insurance eligibility was not checked" (E4-SPEC-24, 25).
10. **Policy holder.** No `policy_holder` key in the built payload and no such string in the
    submitted body; the checklist call still sends `policy_holder_is_self` (E4-SPEC-3).
11. **Stack check.** `make up`; register through the portal at `localhost:3070/intake`; a
    patient row exists (`docker compose exec postgres psql …`), the confirmation shows the id
    and a verdict state. Stop `intake-service` and resubmit → the portal shows the system-failure
    message, not success (E4-SPEC-7, 11, 12).
12. **Whole suite + baseline.** `make test-docker`. Baseline today is
    **940 passed, 1 xfailed, 5 deselected** (`CLAUDE.md` §6). E4 adds tests and closes TODO-55's
    coverage gap, which `docs/todo.md:69` states is **not** one of the deliberate gaps in
    `docs/landmines.md` §3 — so the pass count moves by a deliberate addition, the xfail and
    deselected counts must not move, and the new count is recorded in `CLAUDE.md` §6 and the PR
    body with what added it.
13. **Registries.** TODO-1, TODO-55, TODO-56 read as closed; `docs/debt-log.md:333-336` no
    longer claims the class is unguarded; D4's follow-up line names `e5` (E4-SPEC-26, 27, 28).
    The new `roi_consent` entry lands at an id above the highest open one, re-checked against
    `docs/todo.md` at landing rather than trusted from this plan.
14. **No live document names a symbol this PR deleted.**
    `grep -rn "_create_patient\|_create_coverage\|_record_consents" services/ tests/ adr/ docs/*.md CLAUDE.md`
    returns nothing. The scope is the live set on purpose, and the two exclusions are deliberate,
    not convenience: `docs/workflow/**` holds **frozen delivery records** that must not be
    rewritten (`w2/plan.md:202,206,647`, `w2/pr-body.md:143` — and e4's own `plan.md` and
    `findings.md`, which name all three symbols in the course of deciding to delete them), and
    `docs/specs-deprecated/` and `docs/handover/` are archives; none of the three appears in
    either today (measured 2026-08-10). `docs/*.md` is a flat glob and reaches exactly the live
    registries — `todo.md`, `debt-log.md`, `landmines.md`, `phi-logging-policy.md`,
    `runbook.md`, `onboarding-seam-map.md`. The live hits it must clear are known and each has an
    owner in this plan: `phi-logging-policy.md:86-88` and `debt-log.md:139` (§9),
    `adr/0010:154` (§9, dated amendment), `tests/test_intake_db_error_phi.py` and
    `tests/test_intake_match_key.py:334` (Files touched), and — easy to miss because its function
    **survives** — `services/intake-service/app.py:362`, an in-code comment in
    `_evaluate_match_key`'s except block citing `_create_patient` for the rule-3 idiom, plus the
    two `# Rule 3 (see _create_patient)` comments that go with the deleted helpers (§2).
    The step is only passable if the upkeep in §9 is written without restating the dead names —
    see the plan-stage decision above; a "formerly `_create_coverage`" in the collapsed PHI row,
    the debt-log residual or the ADR blockquote fails this step, by design.
    Same check for `tests/README.md`: it no longer asserts `POST /intake` is undriven, and
    `docs/landmines.md` §3's deliberate-gap list is unchanged, so the count move in step 12 is a
    deliberate addition and not a moved gap.
15. **The ADR 0005 ordering test still binds after the re-key.**
    `tests/test_intake_match_key.py::test_match_evaluation_runs_after_the_patient_row_is_committed`
    green, `order == ["patient-committed", "match-evaluated"]` unchanged (E4-SPEC-1, 4).
    **Negative, the property:** move `_evaluate_match_key(...)` above `_create_registration(...)`
    in `create_intake` → red, marker order inverted; revert. **Negative, the re-key itself:** drop
    the `if "patient-committed" not in order` guard → red with a third element, proving the guard
    is load-bearing and not decoration; revert. **Negative, the stub:** restore `flush()`'s
    `obj` parameter → all 16 `create_intake` calls in the file raise `TypeError`; revert. The
    three together are what stop a green suite from re-certifying a weaker property than ADR 0005
    states.

## Landmines / risk

- **`docs/landmines.md` §1 zones touched, both owner-approved (requirements D-1):** gateway
  error handling (the open half of D4) on the registration route only, and the `ConsentKind`
  PHI control. Not touched: auth, PHI columns, ROI/disclosure logic, migrations, secrets.
  The eligibility timeout/breaker values (ADR 0010) are **not** widened or loosened — the new
  gateway bound sits outside them and is pinned to them by test, at all four places it can be
  set: the code default, `.env.example`, a per-service `environment:` block and a scoped
  `.env.*.example` template (§3, §8). **ADR 0010 itself does appear in the diff** — a dated
  amendment to one Consequences sentence that names a function this PR deletes (§9). No budget
  value, no status, no decision text changes; called out because an ADR 0010 hunk is the other
  shape review should stop on.
- **`docs/phi-logging-policy.md` is edited, and it is a live control document.** The edit is
  register upkeep forced by §2 deleting three of the functions the register names — no rule,
  threshold, or row status changes, and no row moves from OPEN to FIXED. Called out because a
  PHI-policy file in a diff is the shape review should stop on.
- **New risk: an intake-time `roi_consent` is not an ROI authorization.** The owner chose to
  satisfy E4-SPEC-9 by adding the consent to the form rather than amending the spec. D12 (ROI
  goes out with no recorded 45 CFR 164.508 authorization and no accounting trail) is untouched
  and stays open; nothing in `roi-service` reads `consents`, verified this session. The wording
  points at the Notice of Privacy Practices and authorizes no specific disclosure, and the new
  `docs/todo.md` entry (**TODO-61**, §9 — re-checked at landing) records that no code may later
  treat the row as an authorization. If review judges this a
  compliance widening, the fallback is `adr/0013`'s subset + literal pin, which needs a spec
  amendment (owner decision, stage 2).
- **Deliberate defects preserved.** Nothing here touches D5 (no MPI — every `/intake` still
  forks a new chart), D5b, D8, D11, the booking race, or the HL7 gap. The registration defect
  itself is inherited breakage, not a seeded teaching artifact: no `D<n>` marker, filed in the
  debt log without a D-number, and TODO-1 asks for it to be fixed (requirements §5).
- **One inherited behaviour deliberately changed without a registry entry to cite:** the
  per-consent commit and the swallowed consent-write failure. It carries no D-number, no
  landmines bullet and no debt-log row — it is described only as an inherited shortcoming in
  the intake module docstring. E4-SPEC-4 requires one transaction, so it goes, and the docstring
  is corrected rather than left asserting the old shape. Flagged here because "inherited oddity
  with no registry entry" is exactly the shape that is usually a teaching artifact.
- **Accepted residual on E4-SPEC-4:** atomicity is per-request, not cross-service. A
  registration that commits and then has its response lost in transit leaves a patient row the
  operator never sees confirmed — the portal will report a system failure and the row exists.
  Closing that needs an idempotency key on `POST /intake`, which is register-first's territory
  (D4 follow-up, `e5`+). Named rather than implied by the scope map.
- **Accepted residual on E4-SPEC-25:** `VerdictBadge` renders the four-value vocabulary only
  (`active | inactive | unknown | pending`); everything else — including a well-formed verdict
  from a future responder — falls into the single "not checked" line, which understates a
  *degraded* state as an *unchecked* one. Chosen over widening the badge's tone map, whose cost
  is not blast radius but contract: `VerdictBadge` is imported by exactly one page today,
  `frontend/app/assistant/page.tsx:6` (measured this session; the four-page component is
  `StatusBadge`, which W3 deliberately left alone — `VerdictBadge.tsx:10-15`). Widening it would
  change that frozen W3 surface too, and inventing a tone for a status outside the eligibility
  path's own vocabulary is what W3-SPEC-6 rules out and
  `frontend/app/components/VerdictBadge.test.tsx:67-96` pins. The intake confirmation therefore
  takes the same rule and states the gap in prose.
- **Gate interaction:** no CI workflow edit is needed for E4-SPEC-20/21 — the `tests` and
  `frontend` jobs already exist and are both in `docker-build`'s `needs` list. Consequence: a
  contract break attributes to whichever job owns the drifting side, which is the attribution we
  want. `next build` type-checks `frontend/**`, so `payload.contract.test.ts` must compile
  under `tsc --noEmit` too — it imports `describe`/`it`/`expect` explicitly (e1's no-globals
  convention) and reads the JSON via `node:fs` rather than `import`, so nothing outside
  `frontend/` enters the TS project.
- **Version caveat, unchanged from e1:** `next lint` is deprecated from Next 15.3+; at the
  pinned 15.1.3 it works. Recorded, not acted on.
- PR body "Risk & landmines" section: "Touches two §1 zones with owner approval — gateway error
  handling (registration route only, the open half of D4) and the `ConsentKind` PHI control.
  No auth, PHI column, ROI logic, migration or secret touched. New: the intake form now collects
  `roi_consent`; it is not a 164.508 authorization and D12 stays open (TODO-61)."
- Follows `CONTRIBUTING.md`: no `Co-Authored-By` trailer; no schema change, so no migration.
