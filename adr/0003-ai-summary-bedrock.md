# ADR 0003 — AI summary via AWS Bedrock

- **Status:** Proposed / partially built
- **Date:** 2026-03-10
- **Author:** Helix Digital Partners

## Context
The Riverbend board wants an "AI" feature. The clearest quick win is an
assistant that drafts patient-friendly summaries of intake instructions and,
later, visit summaries.

## Decision
- Add an `ai-orchestrator` service that calls AWS Bedrock (Claude).
- For the summary, send the relevant patient/encounter record to the model and
  return its text to the portal.
- Keep it simple for v1: no max-token budget, no output validation, no
  de-identification step — get something on screen, harden later.

## Consequences
- Fast path to a board demo.
- The full record (name, DOB, MRN, notes) is sent to the LLM vendor as-is.
- The vendor relationship is governed by a standard SaaS ToS (no BAA yet).
- Model output is returned verbatim with no grounding/validation.
- Cost and latency are unbounded per request.
- All of the above marked "TODO before GA." (GA date TBD.)
