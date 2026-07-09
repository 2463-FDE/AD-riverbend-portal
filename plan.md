# Engagement Plan — Riverbend Portal (living document)

> Updated as work lands. Week 1 scope agreed 2026-07-05.

## Context

Client asks (week 1 brief):
1. Registration page "spins" — maps to RIV-088 / RIV-141: inline, no-timeout eligibility call on the intake request path (debt marker D4).
2. "Stand up an AI assistant" drafting patient-friendly intake instructions.

This week's deliverable is **not** the AI feature. It is the safe foundation:
a production LLM client wrapper, a PHI-safe logging policy with a redaction
helper, a one-page onboarding seam map, and a debt log in business-risk terms.
The client's "we're fully HIPAA compliant" statement is contradicted by the
handoff docs (plaintext PHI, PHI in logs, no ROI authorization) — everything
built here treats PHI as unprotected until proven otherwise.

## Week 1 checklist

| # | Item | Status |
|---|------|--------|
| 1 | Repo `plan.md` (this file) | done |
| 2 | Resolve `anthropic` SDK pin, verify API surface | done — `anthropic==0.72.0` (newest pin compatible with local Python 3.8; no `messages.parse`, structured output via `extra_body` + manual validation) |
| 3 | `services/ai-assistant/` skeleton (config, logging, redaction, llm_client, app, requirements, Dockerfile, .dockerignore) | done — keyless import smoke passes |
| 4 | Tests: `tests/test_redaction.py`, `tests/test_llm_client.py`; `anthropic` in `requirements-dev.txt` | done — full suite 37 passed / 1 xfail on Python 3.12 (Docker; local 3.8 cannot run the repo's tests at all — pre-existing) |
| 5 | Intake D1 fix (`app.py:67` redacted logging) — **approved PHI-path edit** | done |
| 6 | Compose + CI matrix + `.env.example` | done — `make config` OK, `docker compose build ai-assistant` OK |
| 7 | Docs: PHI logging policy, seam map, debt log, ADR 0004 | done |
| 8 | Final verification (full test suite, compose config, git status review) | done |

## Decisions log

- **2026-07-05** — Debt log uses the repo's real seeded markers (D1, D4, D12
  primary). The client brief cited "D1/D9/D3"; D9 and D3 do not exist in this
  repo (they are curriculum day numbers). Discrepancy documented in
  `docs/debt-log.md`, which is now the canonical registry.
- **2026-07-05** — LLM wrapper lives in a new service skeleton
  `services/ai-assistant/` (port 8077), matching the removed `ai-orchestrator`
  prior art (commit d0905a1) and per-service layout (ADR 0001). No user-facing
  AI endpoint this week — healthz only.
- **2026-07-05** — Anthropic SDK direct (not Bedrock), model
  `claude-opus-4-8`. Key via `ANTHROPIC_API_KEY`; placeholder added to
  `.env.example` only. The committed `.env` is never touched.
- **2026-07-05** — Intake D1 fix approved by the team: the full-PHI log line at
  `services/intake-service/app.py:65` is replaced with redacted logging. This
  is the only non-additive change this week.
- **2026-07-05** — Per ADR 0001 (no shared Python lib), `redaction.py` is
  copy-pasted into consuming services; a parity test in `tests/test_redaction.py`
  guards against drift.

## Out of scope this week

Auth/sessions, ROI/disclosure logic, DB schema/migrations, the D4 timeout fix
itself, gateway routing to ai-assistant, scheduling race, HL7 parser. These
stay documented in `docs/debt-log.md`.

## Risks / flags

- `.env` is committed to git — real API keys must be added locally and never
  committed. Open item in the debt log.
- `logs/intake-service.log` is git-tracked and contains historical PHI. The D1
  code fix stops new leakage only; purge/gitignore/history-scrub is an open
  ops item (see PHI logging policy §violations).
- Remaining PHI-adjacent log sites (eligibility `insurance_id`, error-path URL
  leakage) are documented as OPEN, not fixed, by scope decision.
- Local dev Python is 3.8 while services run on 3.12 in Docker; new code is
  kept 3.8-compatible so the root test suite runs locally.

## Next-engagement candidates

- D4: bounded timeout + deferred/async eligibility verification (fixes
  RIV-088/RIV-141 directly).
- Gateway route + `AI_ASSISTANT_URL` wiring, then the patient-friendly
  intake-instructions endpoint on ai-assistant.
- Eligibility `insurance_id` log fix; error-path URL redaction.
- D12: ROI authorization enforcement — hard prerequisite before any AI feature
  touches patient data.
