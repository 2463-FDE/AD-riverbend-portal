# Onboarding Seam Map (1 page)

> Where to land changes safely in this codebase — and where not to.
> Written 2026-07-05 alongside the ai-assistant service, which is the worked
> example of the "new service" seam.

## Seams — safe extension points

| Seam | How to use it | Worked example |
|------|---------------|----------------|
| **New service directory** | Copy the per-service layout (`config.py` / `logging_config.py` / `app.py` / `requirements.txt` / `Dockerfile`), pick the next port, add a compose block + CI matrix entry. Nothing else changes. | `services/ai-assistant/` (port 8077) |
| **Per-service module copy-paste** | ADR 0001: no shared lib. Copy the module in, note the source in its header, add a parity test. | `redaction.py` in ai-assistant + intake-service, parity-tested in `tests/test_redaction.py` |
| **Path-loaded unit tests** | `tests/conftest.py::load_module` loads any service module by file path; monkeypatch its module-level client. Caveat: bare sibling names (`config`) collide across services — pin `sys.modules` first (see `tests/test_llm_client.py`). | `tests/test_llm_client.py`, `tests/test_eligibility_check.py` |
| **Gateway fan-out** | To expose a service to the portal later: add `<NAME>_URL` env in the gateway compose block, a proxy route in `services/gateway/app.py`, and a BFF handler in `frontend/app/lib/gateway.ts`. Single wiring point per layer. | (pending — ai-assistant not yet routed) |
| **Config-driven intake form** | `services/intake-service/intake.yaml` drives the front-desk form; served by `GET /intake/config`. Form changes need no code. | `intake.yaml` |
| **Deterministic seed data** | `db/seed/generate_seed.py` → `make seed-gen` → `make seed`. Add demo data here, never by hand-editing `seed.sql`. | demo logins |

## Load-bearing walls — do not lean on these

| Wall | Why |
|------|-----|
| **Gateway auth/sessions** (`services/gateway/`, `security.py`, `authz.py`) | Sessions never expire and there is no MFA (ADR 0003). **Corrected 2026-08-08:** not a single `staff` role — ADR 0017 landed four real roles (`front_desk`, `clinician`, `roi_clerk`, `admin`) with per-route capability enforcement in `authz.py`, pinned against `config/roles.yaml` by `tests/test_gateway_authz.py`; `staff` survives as the full-capability legacy role every pre-RBAC `users` row still holds, which is why a leaked token on an existing database is still all-access (`docs/debt-log.md`). `auth.yaml` is declarative only and enforces nothing (`docs/landmines.md` §1). Changes need explicit human approval. |
| **roi-service disclosure paths** (D12) | No 45 CFR 164.508 authorization enforcement. Never source data for a new feature (including anything AI) through this service until authz exists. |
| **Inline synchronous outbound calls on request threads** (D4) | Intake verifies eligibility inline — the "spinning registration" (RIV-088/141). **Corrected 2026-08-08:** the call is bounded now, not untimed — ADR 0010 added timeouts and a breaker on both sides, pinned to each other by `tests/test_eligibility_budget_alignment.py`. The wall is the placement, not the missing timeout: verification still runs on the request thread. Do not add more inline outbound calls; every new outbound call gets a timeout (see `ai-assistant/llm_client.py` for the pattern). |
| **Patient identity** (D5, tier-1 match key, flag-and-review only) | Every intake still creates a new chart; `patient_id` is not stable per person. Since W2 a candidate duplicate is *flagged* for human review (ADR 0005), but nothing merges and there is still no MPI — so both consequences stand. Don't build features assuming one-chart-per-patient. |
| **Schema + migrations** | `db/schema.sql` and `db/migrations/*.sql` are hand-synced; only `schema.sql` runs on a fresh volume. Any schema change must update both, and needs approval. |
| **`.env` and the secrets in git history** | **Corrected 2026-08-08:** `.env` is no longer tracked — it has been gitignored since `56645fc`, and CI's gitleaks `secret-scan` job fails the build if a secret reappears in the tracked tree. The wall is what the old tracking left behind: the credentials are still in **git history** (`git show b9364ca:.env`), un-rotated, so the exposure is live and only rotation plus a history rewrite closes it (`docs/debt-log.md` — the **Remediation runbook** table and the cross-cutting `` `.env` committed with secrets `` row; the client brief's "D9" is misnumbering, per the note at `docs/debt-log.md:6-10`, and neither entry carries a D-number). Never add secrets to a tracked file; placeholders go in `.env.example`. |
| **The `{"error": str(e)}` pattern** | Gateway/intake swallow errors into 200-OK bodies. Do not copy — raise typed errors (see `llm_client.py`) or return real HTTP status codes. |
| **PHI in logs** | See `docs/phi-logging-policy.md`. Bodies only via `safe_log_payload`. |
