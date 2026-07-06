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
| **Gateway auth/sessions** (`services/gateway/`, `security.py`, `auth.yaml`) | Sessions never expire, single `staff` role, no MFA (ADR 0003). Test coverage thin (RIV-201). Changes need explicit human approval. |
| **roi-service disclosure paths** (D12) | No 45 CFR 164.508 authorization enforcement. Never source data for a new feature (including anything AI) through this service until authz exists. |
| **Inline synchronous outbound calls on request threads** (D4) | Intake's eligibility call has no timeout — the "spinning registration" (RIV-088/141). Do not add more inline outbound calls; every new outbound call gets a timeout (see `ai-assistant/llm_client.py` for the pattern). |
| **Patient identity** (D5, no MPI) | Every intake creates a new chart; `patient_id` is not stable per person. Don't build features assuming one-chart-per-patient. |
| **Schema + migrations** | `db/schema.sql` and `db/migrations/*.sql` are hand-synced; only `schema.sql` runs on a fresh volume. Any schema change must update both, and needs approval. |
| **Committed `.env`** | Tracked in git. Never add secrets to it; placeholders go in `.env.example`. |
| **The `{"error": str(e)}` pattern** | Gateway/intake swallow errors into 200-OK bodies. Do not copy — raise typed errors (see `llm_client.py`) or return real HTTP status codes. |
| **PHI in logs** | See `docs/phi-logging-policy.md`. Bodies only via `safe_log_payload`. |
