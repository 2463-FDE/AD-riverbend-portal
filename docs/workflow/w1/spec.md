# W1 Spec (EARS)

> Status: DRAFT
> Source: docs/workflow/w1/requirements.md (AGREED 2026-08-06)
>
> Backfill of record: these statements are derived from the requirements alone. Whether
> the existing `main` artifacts satisfy them is established at the verification step that
> follows agreement; a miss there is a finding, not a spec change.

## 1. Statements

### W1-REQ-1 — bounded call time

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-1 | When the LLM client issues an outbound provider request, it shall apply a configured time bound covering connection and response read | |
| W1-SPEC-2 | If the time bound is exceeded, then the LLM client shall abort the call and raise a typed timeout error to the caller | |

### W1-REQ-2 — bounded retry with backoff

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-3 | If a provider call fails with a transient fault (timeout, transport error, or retryable provider status), then the LLM client shall retry with increasing backoff up to a configured attempt budget | |
| W1-SPEC-4 | If a provider call fails with a non-transient fault (the provider rejecting the request itself), then the LLM client shall not retry and shall raise a typed error | |
| W1-SPEC-5 | If the attempt budget is exhausted, then the LLM client shall raise a typed error identifying the final fault class | |

### W1-REQ-3 — validated structured output

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-6 | When a provider response arrives, the LLM client shall validate it against the expected output structure before returning it to the caller | |
| W1-SPEC-7 | If structure validation fails, then the LLM client shall raise a typed parse error and shall never return partial or unvalidated content | |

### W1-REQ-4 — token/cost guard

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-8 | When a request is prepared, the LLM client shall enforce a configured cap on input size and refuse an over-cap request before any provider call is made | |
| W1-SPEC-9 | The LLM client shall bound response generation with a configured maximum output token limit on every call | |
| W1-SPEC-10 | When a call completes, the LLM client shall make actual token usage available to the caller for accounting | |

### W1-REQ-5 — no PHI in LLM-path logs

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-11 | The LLM path shall never write request or response bodies, prompts, or completions to any log | ⚠ human-gate; landmines §3 negative tests |
| W1-SPEC-12 | Log entries on the LLM path shall carry only allowlisted non-PHI metadata (status class, latency, token counts, exception class) | ⚠ human-gate; landmines §3 negative tests |
| W1-SPEC-13 | If an error is logged on the LLM path, then the entry shall identify the exception by class name only, never by stringified message | ⚠ human-gate; landmines §3 negative tests |

### W1-REQ-6 — written logging policy

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-14 | The engineering org shall maintain a written PHI-safe logging policy that enumerates what is loggable, bans request/response bodies from logs, and defines the reusable redaction/allowlist mechanism | ⚠ human-gate |
| W1-SPEC-15 | The logging policy shall carry a live register of known violations with per-item status | ⚠ human-gate |

### W1-REQ-7 — onboarding seam map

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-16 | A one-page onboarding seam map shall name the safe extension points and the do-not-touch load-bearing walls | |

### W1-REQ-8 — debt-log entry

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-17 | The debt log shall state the week-1 findings — plaintext-PHI logging, the unbounded eligibility call, secrets in tracked files — in business-risk terms, citing tickets where they exist | |
| W1-SPEC-18 | The debt log shall map the client brief's D1/D9/D3 numbering to the canonical seeded-marker IDs | |

### W1-REQ-9 — minimal visible surface

| ID | Statement | Notes |
|----|-----------|-------|
| W1-SPEC-19 | When a portal user requests patient-friendly intake instructions, the portal shall display instructions produced through the safe LLM client path (W1-SPEC-1..13) | ⚠ human-gate adjacency: vendor-egress path |
| W1-SPEC-20 | If the LLM path fails or is unavailable, then the surface shall present a deterministic non-PHI fallback rather than a raw error | |

## 2. Traceability

| REQ | SPECs |
|-----|-------|
| W1-REQ-1 | W1-SPEC-1, W1-SPEC-2 |
| W1-REQ-2 | W1-SPEC-3, W1-SPEC-4, W1-SPEC-5 |
| W1-REQ-3 | W1-SPEC-6, W1-SPEC-7 |
| W1-REQ-4 | W1-SPEC-8, W1-SPEC-9, W1-SPEC-10 |
| W1-REQ-5 | W1-SPEC-11, W1-SPEC-12, W1-SPEC-13 |
| W1-REQ-6 | W1-SPEC-14, W1-SPEC-15 |
| W1-REQ-7 | W1-SPEC-16 |
| W1-REQ-8 | W1-SPEC-17, W1-SPEC-18 |
| W1-REQ-9 | W1-SPEC-19, W1-SPEC-20 |

## 3. Open questions

None.
