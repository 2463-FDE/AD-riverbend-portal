# Tests

```bash
pip install -r ../requirements-dev.txt
pytest -m "not integration"     # unit tests, no infra needed
pytest -m integration           # needs `make up` (Postgres + Redis + stack)
```

There is no shared Python package across services (adr/0001), so unit tests load
the module under test by file path (see `conftest.py::load_module`).

## What's covered

> Corrected 2026-08-08: this named five files when 33 sit in `tests/` plus one under
> `tests/integration/`. By area, not by file — `ls tests/` is the roster.

- **Gateway auth + RBAC** — password hashing (`test_gateway_security.py`), per-route
  capability enforcement pinned against `config/roles.yaml` (`test_gateway_authz.py`,
  ADR 0017), Redis credential fail-closed (`test_gateway_redis_auth.py`).
- **Eligibility resilience** — payer response shaping (`test_eligibility_check.py`),
  both circuit breakers (`test_payer_breaker.py`, `test_intake_breaker.py`), deferred
  verification (`test_intake_deferred.py`) and the timeout/breaker budget alignment
  ADR 0010 pinned (`test_eligibility_budget_alignment.py`).
- **PHI redaction and log hygiene** — the copied-module parity test
  (`test_redaction.py`), the engine-level `hide_parameters` guard
  (`test_db_engine_hide_parameters.py`), and a per-service DB-error negative test on
  every PHI-bearing path (`test_intake_db_error_phi.py`,
  `test_gateway_login_db_error_phi.py`, `test_records_search_db_error_phi.py`,
  `test_roi_db_error_phi.py`, `test_scheduling_booking_db_error_phi.py`,
  `test_eligibility_phi.py`, `test_intake_eligibility_phi.py`,
  `test_visit_chat_phi.py`). `docs/phi-logging-policy.md` holds the violation register.
- **AI paths** — LLM client budget/retry/structured output (`test_llm_client.py`),
  both features (`test_ai_intake_instructions.py`, `test_ai_visit_chat.py`), the
  gateway-side proxy, chat controls and Redis rate limit (`test_gateway_ai_proxy.py`,
  `test_gateway_ai_chat_controls.py`, `test_gateway_ai_rate_limit.py`), visit memory
  (`test_visit_memory.py`), tracing (`test_tracing.py`), and the eligibility-assistant
  policy corpus — sha pin, fixture isolation, boot-fail hook (`test_a1_corpus.py`), the
  topic-only retriever tool, index and cap (`test_a1_retriever.py`), the tier rule and rank key
  (`test_a1_conflict.py`), the lookup record and its metadata-only negative
  (`test_a1_retrieval_record.py`), and the recall baseline and substitutable ranking unit
  (`test_a1_retrieval_eval.py`); all five share the pinned module rig `a1_corpus_rig.py`. The agent
  binding on the `invoke_model` seam — fail-closed guards on the tool payload, the send/receive
  round trip, the SystemMessage rules, the post-egress guard/telemetry parity with
  `complete()` and the control-by-control enumeration of that twin — is in `test_llm_client.py`
  (`test_a1_binding_*`), and the never-stream guarantee
  in `test_a1_trace.py`, which the `trace` ticket extends. The adapter that feeds both halves is
  pinned total over a drifted 200 body in the same file
  (`test_a1_adapt_total_over_non_dict_bodies`, `test_a1_call_types_shape_errors_outside_adapt`).
- **Intake and HL7** — payload validation (`test_intake_schemas.py`), the route itself
  end to end (`test_intake_endpoint.py`), the two-sided payload declaration
  (`test_intake_payload_contract.py`, whose portal twin is
  `frontend/app/intake/payload.contract.test.ts`), the gateway's registration proxy
  (`test_gateway_intake_proxy.py`), the intake freeze regression
  (`test_intake_freeze_regression.py`), HL7 PID/PV1 (`test_hl7_parser.py`, with the
  AL1/RXA gap as the suite's one `xfail`).
- **Topology and gates** — the host-published-port allowlist
  (`test_compose_topology.py`, ADR 0016) and the RIV-160 retrieval-eval drift gate
  (`test_rag_eval.py`, `test_drift_check.py`).
- `integration/test_records_flow.py` — login + auth-gating + chart read (the only
  test needing live infra).

## Known coverage gaps (deliberate — this is an inherited codebase)
These are NOT oversights to "fix" in the test suite; they mirror real gaps:
- **No tests for the scheduling race / double-booking** (`book.py`). The happy
  path is exercised manually only.
- **No tests asserting IDOR is prevented** — there's an `xfail` documenting that
  cross-patient reads currently succeed (they shouldn't).
- **HL7 allergy/medication extraction is `xfail`** — the parser silently drops
  AL1/RXA; the test documents the gap rather than hiding it.
- **No tests for ROI authorization enforcement** — none exists to test.
- **No tests for input normalization / duplicate-patient prevention.**

> **Three entries have left this list, closed by shipped work.** 2026-08-08: the eligibility
> timeout/breaker gap (ADR 0010 — `test_intake_breaker.py`, `test_payer_breaker.py`) and
> "auth coverage is thin (RIV-201)" (ADR 0017 — `test_gateway_authz.py` pins the enforced
> capability map against the declared one). 2026-08-10: "no test drives `POST /intake` as an
> endpoint", closed by `tests/test_intake_endpoint.py` (`e4`, TODO-55) — it was never a
> deliberate gap, just missing coverage. `docs/landmines.md` §3 still owns the negative-test
> rule for new work on these paths.
