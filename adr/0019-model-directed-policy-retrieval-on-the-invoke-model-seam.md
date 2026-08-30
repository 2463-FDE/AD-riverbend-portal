# ADR 0019 — Model-directed policy retrieval on the `invoke_model` seam: a bounded agent loop over a deterministic, sha-pinned corpus

**Status:** Accepted — landing ticket by ticket (`docs/workflow/eligibility-assistant.md`
`## Delivery`); §1 below landed with the `corpus` ticket, §2–§6 are appended by the ticket
that lands each mechanism
**Date:** 2026-08-29
**Author:** Riverbend engagement team
**Debt:** D13 (no BAA on the vendor path — the constraint this design keeps intact, not one it
narrows)

## Context

ADR 0011 landed the front-desk eligibility assistant with the vendor boundary closed by
construction: intent derivation and the payer lookup are deterministic and the model sees only
closed vocabulary. The engagement's eligibility-assistant item (contract
`docs/workflow/eligibility-assistant.md`, spec FROZEN at 66 rows) asks for the next step — an
assistant that can *cite* the clinic's approved policy documents on a coverage question — and the
client package that came with it is 87 approved documents under a manifest with per-file sha256,
plus a 32-case harness and seven `FIX-NEG-*` fixtures that must never become citable.

Three forces shape the decision. First, `docs/landmines.md` §1 "PHI handling": any prompt may
carry PHI and D13 stands OPEN, so nothing free-text may reach the model and no new egress path
may open. Second, the corpus is the client's approval boundary: what the assistant may cite is
exactly the manifest's approved rows, and a silent narrowing or widening of that set is the
failure the whole design must make impossible. Third, the model must be able to *choose* which
topic to retrieve for — that is the one judgement this feature delegates — while ranking,
applicability and outcome stay computed in code (SPEC-42/43).

## Decision

The decision list, as eligibility-assistant-D-42 records it; each numbered section is authored
by the ticket whose diff lands the mechanism, and a section not yet written is not yet landed.

### 1. Deterministic retriever, tracked index, tier rule (`corpus`)

- **The corpus is a closed set pinned by sha.** `services/ai-assistant/policy_corpus/` holds the
  87 documents byte-identical to the package beside a verbatim `document-manifest.json`.
  `policy_index.load()` is the *one* reader of that manifest: it walks the whole tree at every
  depth and requires every file to be one of the two named root files or a manifest row whose
  sha256 matches (`.DS_Store` is the single exempt name), and requires every row to be
  `approved` — anything else raises `CorpusLoadError` before any lookup. `app.py` calls `load()`
  in its lifespan hook so a fault fails the container at **boot**, and `policy_tool` builds its
  topic enum through the same loader at **import**, so CI's keyless `import app` smoke reddens
  ahead of the hook. The seven `FIX-NEG-*` fixtures live under `tests/` only.
- **One row per document, the client's own labels.** Each index row is `id`, `title`,
  `section` (the manifest `section_labels` string verbatim), `version`, `retrieval_date` and the
  whole vendored file as `section-text` — no heading split, no invented boundary
  (eligibility-assistant-D-61). The cap therefore counts documents.
- **The model's whole argument surface is one closed enum.** `policy_tool.make_policy_lookup`
  returns a LangChain `StructuredTool` whose explicit `args_schema` (`extra="forbid"`) has the
  single field `topic: Literal[<the 25 manifest categories>]`; payer, product and state are bound
  by the application from the clerk's selections at construction. An extra key, a free-text value
  or a document id each raise before `policy_index.lookup` is reached. The schema is explicit
  because the pinned `langchain-core==1.6.0` inferred schema drops `extra="forbid"` and would
  silently discard an extra key. `fetch_by_id` is the application-side by-id entry for the
  reason table and is deliberately *not* a tool argument.
- **Filtering, ranking and the cap are code.** `policy_corpus/index.json` is a tracked, curated
  artifact mapping each approved row to `topics` / `payers` / `products` / `states` (`*` = matches
  any query value; `unconfirmed` on product or state is non-filtering,
  eligibility-assistant-D-32); query values are enum members only and `*` is never legal on the
  query side (D-64). `rank(rows)` is the one ordering site — tier rank asc, `retrieval_date` desc,
  `document_id` asc (D-62) — and `lookup` applies it before the `A1_RETRIEVAL_MAX_ROWS` cut.
  The tier is license class × category (D-38): 1 = public-domain × {emergency-care-boundary,
  privacy-minimum-necessary}, 2 = other public-domain, 3 = citation-only, 4 = original synthetic
  not `payer-training-summary`, 5 = `payer-training-summary` — partition 9 / 32 / 16 / 23 / 7,
  never model judgement.
- **Invariant, pinned:** `A1_RETRIEVAL_MAX_ROWS × policy_index.MAX_ROW_BYTES +
  PROMPT_RESERVE_BYTES ≤ LLM_MAX_INPUT_TOKENS` — the row cap is sized against the *binding* byte
  gate of `llm_client._enforce_budget`, text and row metadata together (2,789 B max today,
  computed at load), with 5,000 B reserved for `turn`'s prompt; and at least one legal argument
  set exceeds the cap, so the cap clause has a real exercise. Raising the cap or
  `LLM_MAX_INPUT_TOKENS` alone reddens `tests/test_a1_retriever.py::test_cap_binds_on_a_legal_call`
  by design; the latter is a PHI-egress bound and is never raised to make room.
- **Failure from outside:** a corpus fault is a container that does not boot (`docker compose ps`
  shows ai-assistant exited; the gateway's `/ai/*` proxies return their upstream-failure contract),
  never a turn that cites a partial set.

### 2. Seam binding (`llm-seam`)

- **The framework's only egress is `llm_client._call`.** `services/ai-assistant/agent_binding.py`
  defines `SeamChatModel(BaseChatModel)`, whose `_generate` converts framework messages into the
  Anthropic body and calls `_call`. The framework never constructs a provider client of its own,
  so the four **pre-egress** controls that live on `_call` — the gross-size char cap, the
  token/cost budget gate against the byte-based upper bound, the bearer fail-closed guard, and the
  typed-error mapping — apply to the bytes an agent run actually emits. Tool definitions ride
  `extra_body["tools"]`, which `_enforce_char_cap` and `max_input_tokens` both count, so the tool
  surface is inside the budget gate rather than beside it. This is the eligibility-assistant-D-9
  shape-(ii) reason: a Converse-style client would have been gated on a payload that is not the
  egress payload.
- **The system prompt is `_call`'s `system` argument.** Exactly one `SystemMessage`, and only as
  the leading message, maps to `body["system"]` — the key `max_input_tokens` counts on its own
  line. A `SystemMessage` elsewhere, more than one, or a non-`None` `stop` raises `ValueError`
  before `_call`, with zero egress. Folding the system prompt into a `user` turn is exactly the
  smuggling the separate byte line exists to prevent.
- **A post-egress twin guard, not a bypass of ADR 0004.** `_call` returns before
  `_result_from_response`, so the two post-egress controls ADR 0004 names (`:38-40`, `:57`) do not
  come for free on this path: `_generate` applies them itself, as **three** checks rather than two
  — fail closed on a malformed 200 (content present; every field the receive half reads
  shape-checked, `id` / `name` str and `input` dict on a `tool_use` block and `text` str on a text
  block, because those fields exist on this path and `_adapt` defaults them to `None`; explicit
  integer usage), errors carrying the field name and the request id only, and emit the same
  metadata-only `llm call model=… in_tokens=… out_tokens=… cost=… latency=… request_id=…` line.
  The third check is what keeps the guarantee typed: without it a malformed `tool_use` block leaves
  the binding as a pydantic `ValidationError` — not an `LLMError`, and carrying the offending value
  in its message.
  The one deliberate difference is that a `tool_use` block satisfies the content check beside
  `text`, because a tool-only turn is the agent path's valid answer — which is why
  `_result_from_response`'s text-required guard could not simply be reused; it is untouched, and
  `test_non_text_content_block_raises_through_adapter` still pins the rejection for `complete()`.
  `tests/test_llm_client.py::test_a1_binding_guard_parity` pins the binding's log record and
  `complete()`'s against one six-field pattern, so this is a second application of every ADR 0004
  control, not a bypass of any.
- **`_adapt` is a superset, not a rewrite.** Content blocks now carry `id` / `name` / `input` on
  every block and the response carries `stop_reason`, all `None` when the body does not have them.
  The text-only shape is byte-for-byte what it was.
- **The binding cannot stream (SPEC-30).** `_stream` is deliberately unimplemented and raises.
  LangSmith's `hide_inputs` / `hide_outputs` redaction — the two-layer hide ADR 0006 relies on to
  keep trace payloads metadata-only — is bypassed on streamed payloads, so the guarantee is
  structural rather than a policy line asking callers not to stream.
  `tests/test_a1_trace.py::test_model_call_not_streamed` pins both halves: no
  `invoke_model_with_response_stream` reference exists in the service, and `_stream` raises.
- **This ticket lands dark.** `app.py` imports the binding so CI's keyless `services` smoke proves
  it against the *service* requirements; no route calls it and no model call is made. The one new
  log site is the twin guard's `llm call` line, metadata-only and unreached at runtime here.
- **Not proven here:** the composition's live Bedrock leg under the pinned `langsmith==0.10.5`
  (E-4 ran on `0.11.1`, E-5 measured the pins offline only); it is first exercised at SPEC-17 /
  SPEC-32's opt-in runs in `turn` / `trace`. And SPEC-30 is proven for this service — the
  gateway's own LangSmith client is `trace`'s row to state and prove.

### 3–6. Bounded loop and outcome derivation · trace shape · lifecycle · retrieval record and eval

Appended by `turn`, `trace`, `lifecycle` and `retrieval-eval` respectively, each as a
change row of its own ticket plan, so that no decision a review round could reopen rests on a
plan file that is deleted at merge (eligibility-assistant-D-42, note 2026-08-27).

## Alternatives considered

- **Model-chosen document ids or free-text queries.** Rejected: an id or free-text argument is a
  channel from the model into the retriever, which is exactly the surface REQ-3‴ closes (the
  clerk's text never enters a query). The topic-only enum leaves the model one bounded choice.
- **Embeddings / a vector store.** Rejected for this scope: the corpus is ~131 KB over 87 files
  and fits a deterministic metadata filter; a vector path would add a second store, PHI-adjacent
  embeddings, and a ranking the client cannot read. A ranker ladder (BM25 → rerank → embeddings)
  is a follow-on, and `rank` is kept as its own function so `retrieval-eval`'s SPEC-66
  substitution lands without a refactor.
- **Section-split rows from the manifest labels.** Rejected (D-61): 62 of 87 documents have no
  label that is a heading, so a split would put citations on boundaries the client never drew.
- **A lazy first-turn load.** Rejected (D-35 amendment): SPEC-59 reads "fail at load, before any
  turn"; a boot-time hook plus the import-time verification make the fault visible before a clerk
  can be served a narrowed corpus.

## Accepted tradeoffs / deferred gaps

1. **Curation is hand-read.** `index.json` axes are curated from 81 distinct prose applicability
   strings; `test_index_covers_every_row` proves every row is indexed, not that each bucket is
   right. `retrieval-eval`'s recall baseline (SPEC-64) is the first measurement that would show a
   curation error.
2. **The boot-fail hook is proven by test and hand check, not by CI running a container.** CI's
   `services` smoke proves the import-time verification; the hook itself is pinned by
   `test_startup_hook_fails_boot_on_corpus_error` and first observed in a real container at
   `lifecycle`'s runbook step.
3. **Isolation, not resistance.** The fixtures are proven absent from the corpus, the index and
   the approved set, and rejected as inputs; whether the model resists fixture text placed in front
   of it is `turn`'s SPEC-13 / SPEC-17.
4. **The LangChain composition's live leg is un-run at this ticket.** The pins
   (`langchain==1.3.16`, `langchain-core==1.6.0`, `langgraph==1.2.11`) were measured offline
   beside `langsmith==0.10.5` (E-5); the live Bedrock leg is first exercised at SPEC-17 / SPEC-32's
   opt-in runs. This ticket lands dark and makes no model call.

## Consequences

- New: `services/ai-assistant/policy_index.py`, `policy_tool.py`, `policy_corpus/` (manifest,
  87 documents, `index.json`), config `A1_RETRIEVAL_MAX_ROWS` (fresh-deploy default **5**, clamped
  ≥ 1), `.dockerignore` `**/.DS_Store`, the LangChain pins in both requirements files, and the
  lifespan hook in `app.py`. Nothing on the request path is wired: the tool lands dark.
- New (`llm-seam`): `services/ai-assistant/agent_binding.py` (`SeamChatModel`), the `_adapt`
  superset in `llm_client.py`, and the dark `import agent_binding` in `app.py`. Nothing on the
  request path is wired: the binding lands dark.
- Fixtures: `tests/fixtures/a1/` (harness jsonl verbatim, `case_selections.json`, seven
  `FIX-NEG-*` under `fix_neg/`) and the pinned module rig `tests/a1_corpus_rig.py`
  (eligibility-assistant-D-66).
- Tests that now hold the line: `tests/test_a1_corpus.py` (sha pin, fixture isolation, seven
  negatives, approval gate, module-state non-publish, boot-fail hook), `tests/test_a1_retriever.py`
  (topic-only tool, extra-key rejection, in-process/read-only/no-network/capped, cap sizing, enum
  three-way equality, non-filtering `unconfirmed`, index coverage and row shape, case selections),
  `tests/test_a1_conflict.py` (tier partition over all 87 rows, rank key), and — from `llm-seam` —
  `tests/test_llm_client.py::test_a1_binding_*` plus `tests/test_a1_trace.py`.
- ADR 0006 and ADR 0011 carry an `Extended by ADR 0019` status note; their decisions are unchanged.
- Harder from here: widening what the model may pass to the retriever, or adding a second
  manifest reader — both redden a pinned test and re-open the §1 approval of record
  (eligibility-assistant-D-56).
