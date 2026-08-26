# eligibility-assistant / llm-seam

Status: plan DRAFT 2026-08-25 (re-sliced from item plan; gate rounds 1–2 on the monolithic plan are in plans/eligibility-assistant.md)
Scope: SPEC rows eligibility-assistant-SPEC-24 (eligibility-assistant-D-34, PR-1b — the egress seam; lands dark, not wired to the request path). The 1b change list also lands SPEC-30's `test_model_call_not_streamed`; SPEC-30 is scoped to `trace` — row ownership is gate round 2 finding f4, open
Depends on: none

## Plan

Changes (file level):

- `services/ai-assistant/llm_client.py` — `_adapt` becomes the E-4 superset: content blocks carry `id` / `name` / `input` on `tool_use` and the response carries `stop_reason`; `_result_from_response` untouched (eligibility-assistant-SPEC-24 / eligibility-assistant-D-9, E-4 delta i)
- `services/ai-assistant/agent_binding.py` — NEW: `SeamChatModel(BaseChatModel)` — `_generate` → `llm_client._call`; `bind_tools` → Anthropic `tools` in `extra_body`; message conversion with the role-alternation merge; `_stream` deliberately unimplemented (raises) so the binding cannot stream (eligibility-assistant-SPEC-24/30 / eligibility-assistant-D-37, E-4 delta iii)
- `tests/test_llm_client.py` — `test_a1_binding_uses_seam_fail_closed` (bearer unset → `LLMConfigError(egressed=False)` through the binding with zero egress; budget and char caps run on the tool payload; typed errors propagate) plus a characterization of `_adapt` on a text-only body (eligibility-assistant-SPEC-24)
- `tests/test_a1_trace.py` (1b half) — `test_model_call_not_streamed` (no `invoke_model_with_response_stream` reference in the service; the binding's `_stream` raises) (eligibility-assistant-SPEC-30)

Verification (runnable, expected output stated; numbering carried from the item plan):
6. `.venv/bin/python -m pytest tests/test_llm_client.py tests/test_a1_trace.py -q -k "a1 or adapt or streamed"` → passed (eligibility-assistant-SPEC-24/30; 1b)
7. break-then-revert: in `agent_binding.py` replace the `llm_client._call` egress with a direct `boto3` call → `test_a1_binding_uses_seam_fail_closed` red (bearer guard bypassed, egress attempted); revert → green (eligibility-assistant-SPEC-24; 1b)

- Cross-reference: verification 5 (keyless offline import smoke) repeats on this ticket with `agent_binding`; full text in `turn.md`.
- Cross-reference: verifications 8, 9, 19, 20, 21 are per-PR or every-PR checks that run on this ticket too; full text in `trace.md`.
- Cross-reference: the CI `services` import smoke gate interaction covers the LangChain import landed here; full text in `turn.md`.

## Landmines

- No §1 zone is entered by SPEC-24 on its own: the owner's §1 PHI approval of record covers SPEC-7–10, 12, 20, 28–31, which this ticket does not carry. The PHI-handling entry is recorded verbatim in `corpus.md`, `turn.md` and `trace.md`; Auth/sessions, IDOR and Inline-eligibility-call in `turn.md`; Secrets, Migrations/schema and the partial-coverage residual-honesty bullet in `trace.md`.

## Findings

Gate rounds start at 1 for this ticket; carried findings: none.
