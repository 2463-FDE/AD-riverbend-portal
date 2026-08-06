---
name: spec-lens
description: Perspective review of a /feature-start brief before branching - three sequential read-only lenses (security/authz, ops/runbook, decision record) check whether the plan contradicts the project's own record (auth boundary, runbook/port/migration policy, ADRs). Report only, never edits. Use after /feature-start produces a brief and before pr-open.
---

# Spec-lens — perspective review at plan phase

Reviews **the brief** a `/feature-start` run produced — **never the curriculum spec**.
The client asks in `docs/specs/wN.md` are deliberately underspecified as part of the
exercise; "completing" them would do the graded work. The lenses ask one question only:
does *this plan* contradict the project's own record?

**Contract — read before running anything:**

- **Input:** the brief text plus the week's spec path (`docs/specs/wN.md`).
- **This skill NEVER edits the brief or the spec.** Output is a consolidated findings
  report to stdout; the human amends the brief, then proceeds to branch (`pr-open`).
  **That amendment step is the HITL gate** — the skill ends at the report.
- **Each lens returns only contradictions and omissions**, formatted exactly as:

  ```
  brief claim — conflicts with doc:line — suggested amendment
  ```

  or the literal string `no findings`. **General spec-improvement suggestions are
  forbidden** — a lens that says "the brief could also…" is out of contract. No
  summaries, no praise.
- **Lenses run sequentially, one read-only subagent each — never in parallel.**
  CLAUDE.md §10.2 caps delegation at one subagent per step; this skill's instruction
  is the authorization for each lens (same doctrine as doc-drift's readers). Wait for
  each lens to return before spawning the next.
- **These are judgment reviews — session model, not Haiku** (unlike doc-drift's
  readers). Spawn with the `Explore` agent type and **no `model` override** — omitting
  the parameter inherits the session model. The tiering lives in the Agent invocation,
  not in the prompt prose.
- **Paste-in:** the brief is small — the main thread pastes the full brief text into
  each lens prompt. A lens's tool calls are ONLY for the record docs its lens block
  names (plus a code file one of those docs cites, when needed to verify a claim).
  A lens that re-reads the brief from disk or wanders the repo is out of scope.
- **`logs/` is out of scope for every lens.** Historical PHI. No lens block includes
  it, and no lens prompt may point one there.
- A run can cover any subset of lenses; the decision-record lens alone is a valid
  cheap pass. Full three-lens run is the default before branching.

## Finding format (state it in every lens prompt)

**Prompt template:**

> Read-only perspective review of a work brief. The brief is pasted below — do NOT
> re-read it from disk. Your tool calls are ONLY for the record docs named in your
> lens block (plus a code file one of them cites, if needed to verify). Do not wander
> the repo, do not read `logs/`. Report each contradiction or omission as
> `brief claim — conflicts with doc:line — suggested amendment`.
> Return only the findings list, or `no findings`. General improvement suggestions
> are forbidden — only conflicts with the record.
> [brief text] [week spec path] [lens block]

## The three lenses

**Lens 1 — Security/authz.** Brief vs the auth boundary: gateway contracts
(`services/gateway/app.py`, `authz.py`), session→identity binding (sessions are NOT
patient-bound today — a brief must not assume they are), and the deliberate coverage
gaps listed in `tests/README.md` — **count them live from the file, never trust a
remembered number** — a brief must not silently close one (landmines §3: deliberate
gaps need explicit human approval to close). Relevant accepted ADRs: 0003 (auth and
sessions), 0017 (RBAC capability enforcement).

**Lens 2 — REMOVED (design conformance).** The original WS6 spec had a lens checking
briefs against `docs/design/` (operators, design tokens, P2 mockups) and
`docs/specs/frontend-rebuild.md` FE-R requirements. **All of that corpus was pruned at
the PR #31 descope (2026-08-05):** `docs/design/` now holds only the W4 assembly
artifacts, `frontend-rebuild.md` is gone, and the frontend ADRs 0012–0015 are
Superseded. A lens with no record to check against would invent findings. The one live
piece of the frontend case moved into the decision-record lens below: a brief touching
`frontend/` must not resurrect a decision a Superseded ADR retired. **Reinstate this
lens if and when a design-doc corpus exists again.** Numbering kept so the removal
stays visible.

**Lens 3 — Ops/runbook.** Brief vs `docs/runbook.md`, the port policy pinned by
`tests/test_compose_topology.py` (ADR 0016: domain services 8071–8076 and Redis are
`expose`-only, never published), `.env` prerequisites (`.env.example` → `.env`,
generated `.env.ai-proxy` / `.env.redis`), and the migration/schema hand-sync rule:
any schema touch needs BOTH `db/schema.sql` and a new ordered `db/migrations/00N_*.sql`
— a brief planning one without the other is a finding.

**Lens 4 — Decision record.** Brief vs `adr/*.md`:

- **Name every accepted ADR the plan touches** (its decision, not just its files).
- **Flag anything needing a new ADR** per the `_template.md` trigger: "if a future
  review round could reasonably re-open this, it needs an ADR."
- **Flag any brief element that re-opens a Superseded ADR's retired decision** —
  including the frontend case from removed lens 2: a brief touching `frontend/` must
  not resurrect SvelteKit-era patterns or any other decision ADRs 0012–0015 retired.
  (`FE-R*`, `G0`–`G6`, `P2`–`P7` in a brief are dead vocabulary — automatic finding.)

## Token budget

**Not yet measured.** Treat **~15–25k tokens per lens as the target, not a
measurement** — doc-drift's first real reader ran 2× its documented band, so state
the band honestly and **re-baseline after the first real run**; leaving a number
standing as if measured is exactly the drift class these tools exist to catch. Same
budgeting discipline as `commands/dashboard.md` and doc-drift. A lens that opens
files its lens block does not name is wandering: tighten the fence, do not raise
the budget.
