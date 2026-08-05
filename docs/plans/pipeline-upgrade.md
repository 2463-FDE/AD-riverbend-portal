# Pipeline upgrade plan

> Plan for taking the repo from its current state (chat-only briefs, 1/11 spec conformance,
> unfireable design gate) to a staged, gated pipeline where **every stage output is a file with
> stable IDs**. That property — artifacts, not tooling — is what makes N parallel streams
> possible. This is deliberately the first file in `docs/plans/`, the directory the pipeline
> itself will use.
>
> Status: **APPROVED 2026-08-05, with amendments** (all applied below): (a1) PIPE-1 —
> `riverbend-demo`'s tip `07a0c0b` *dropped* its CLAUDE.md, so after the parent rename that
> worktree has no rules at all; rebase-or-retire is required before the rename. (a2) PIPE-6 —
> `brief` removed from the stage enum; under PIPE-2 the brief *is* the plan file, no artifact
> distinguishes a separate brief stage. (a3) PIPE-2 — dry-run ledger lines carry a `dry-run`
> tag. **PG-0 passed same day** — decisions recorded in §6. Work-package IDs (`PIPE-n`) and
> gate IDs (`PG-n`) are allocated once and never renumbered (`docs/specs/_template.md` §0
> discipline).

## 0. Target end state

```
/feature-start W6   → writes docs/specs/w6.md §1/§2   → PG-1: human confirms the decode
   spec stage       → writes §5 EARS + IDs, §6 gates  → PG-2: human signs the end state
   plan stage       → writes docs/plans/w6-<slug>.md  → spec-lens → PG-3: human amends
   impl             → worktree, pr-open → verify-stack → address-review
                       (design gate now FIRES — IDs exist to map findings against)
/dashboard          → reports pipeline stage per week, not just shipped artifacts
```

Verified current-state facts this plan builds on (2026-08-05): spec conformance is 1/11
(`rbac.md` only; `w1.md`–`w10.md` are pre-template prose, so `address-review`'s design-gate
trigger "maps to no requirement ID in the week's spec" is unfireable on 10/11 specs); the
`/feature-start` brief has no file home and `docs/plans/` did not exist before this file;
`/feature-start` has no path for a bad/thin spec (only "missing → stop"); `spec-lens` is
contractually fenced out of editing specs; `CLAUDE.md` lives untracked at `../CLAUDE.md`
(gitignored at `.gitignore:40`); registry-ID collision under parallelism has happened twice
(ADR 0005 numbering collision; TODO-40's "IDs 28–39 allocated in other working trees").

## 1. The gates this plan introduces or arms

Template §6 shape. "User" = the engagement owner running the session.

| Gate | Blocks | Artifact | Verified how | Signed by |
|---|---|---|---|---|
| PG-0 | PIPE-1 starting | this plan's OD-1 row, decided | decision recorded in §6 + `docs/todo.md` | user |
| PG-1 decode | spec stage for the week | `docs/specs/wN.md` §1 (verbatim ask) + §2 (decode) | human reads §1 against the pasted curriculum ask; §2 names debt IDs | user |
| PG-2 spec sign-off | plan stage | `wN.md` §5 EARS table + §6 gate table | EARS lint by inspection: "shall" only, one behaviour per ID, every row has a Verification cell | user |
| PG-3 plan amend | branching (`pr-open`) | `docs/plans/wN-<slug>.md` + spec-lens findings report | each finding amended into the plan file or waived in it by name | user |
| (existing) design gate | fix rounds in `address-review` | §3 design page citing `WN-Rn` IDs | per `address-review` §3 | user |

Gate measurement (extends `docs/review-loop-metrics.md` discipline): every PG-1/2/3 stop
appends one line to a new append-only §6 of `review-loop-metrics.md` — `PG-n / week / outcome`,
outcome ∈ {passed-unchanged, amended, redirected, aborted}. A gate whose outcomes are ~100%
passed-unchanged is a stop on taste — the exact failure `address-review`'s header warns about —
and gets removed or merged. The §5 section lands with PIPE-2; each gate's owner package wires
the append instruction into its tooling text.

## 2. Work packages

Ordered by dependency. Each is sized for pickup by one session; PIPE-2/3/4 can run in parallel
with each other and with PIPE-1's review, in separate sessions, once this plan is approved —
subject to the PIPE-4 reservation rule for any registry IDs they allocate.

Landmine check: no package touches auth, PHI columns, ROI logic, migrations, or secrets. All
prose and local tooling. The one approval-sensitive file is `CLAUDE.md` itself, and PIPE-1's
own new rule makes edits to it approval-gated.

---

### PIPE-1 — Track CLAUDE.md in-repo; decide `.claude/`

**Decision already taken with the human:** track `CLAUDE.md` in-repo, reversing PR #32.
Reasons of record: parallel worktrees/clones inherit the rules, 97 in-repo doc references, PR
review on rule changes. What is NOT yet decided is `.claude/` — that is OD-1 and gate PG-0.

**Sequence (agreed):**

1. Edit `.gitignore`: remove the `CLAUDE.md` ignore line (`.gitignore:40`) and rewrite its
   comment block (`.gitignore:32-39`), which currently says "CLAUDE.md joins them 2026-08-05
   … It now lives one directory up" — false once tracked. **Never `git add -f`** — the
   ignore rule must actually be removed so the state is self-consistent.
2. Copy `../CLAUDE.md` into the repo root.
3. Rewrite the self-describing header block (current lines 5–18: "**Where this file lives, and
   why.** It sits at `~/Documents/REVATURE/Riverbend/` … **not tracked** (untracked
   2026-08-05, PR #32)…") — it states its own location and untracked status, both of which
   become false. New header records the reversal and cites PR #32 → this PR.
4. Add one line to §7 (safety rules): CLAUDE.md edits are approval-gated — the rulebook does
   not change without a human signing the diff.
5. Disable the shadow-rename guard per its own instruction (CLAUDE.md §10.1: "If `CLAUDE.md`
   is ever re-tracked, **disable the guard rather than deleting it** — `git config
   riverbend.allowRepoClaudeMd true`"). Also confirm the pre-commit ignore-delete guard does
   not fire (we are adding, not deleting).
6. Add a `docs/todo.md` line recording the reversal (ID allocated per the PIPE-4 rule; IDs
   28–39 remain reserved to PR #26's branch).
7. Prose-only PR, single approval gate per [[workflow-preferences]].
   **Execution note (post-OD-1):** tracking `.claude/` adds executable files (`hooks/*.sh`,
   `gates.sh`, `memory-lint/lint.sh`, `render-pdf/render.py`, `workflows/*.js`), which are
   never codex-exempt (`pr-open`, the #17 precedent). PIPE-1 therefore ships as **two
   sequential PRs**: PR-A — prose only (CLAUDE.md tracking, `.gitignore` CLAUDE.md block,
   registry updates, this plan), exemption applies; PR-B — `.claude/` tracking (targeted
   `.gitignore` rewrite per OD-1 exclusions), full `@codex-review` loop.
8. **Only after merge AND after sibling trees are handled:** rename `../CLAUDE.md` to
   `../inactive-claude.md` so the parent copy cannot silently diverge from the tracked one.
   (Claude Code reads up the tree and the nearer copy wins, so the tracked copy already wins
   inside any checkout — the rename closes drift, not precedence.) Sibling inventory,
   re-verified 2026-08-05: only `riverbend-demo` (`spike/noref-portal-demo-iter2`) is a
   registered worktree; `guard-test` and `riverbend-proof-measure{,2,3}` exist as directories
   but are **not** worktrees of this repo and appear to have no `.git` — inspect and prune or
   ignore them explicitly before the rename, don't assume the advisory list was right.

**Files:** `.gitignore` (~10 lines), `CLAUDE.md` (new tracked file ~430 lines, ~20 lines
edited), `docs/todo.md` (+1 line), post-merge parent rename (outside repo). Plus OD-1's
outcome: either `.claude/` ignore block edits + ~40 tooling files added, or a one-line
CLAUDE.md §10.1 note that the half-portable state is accepted and why.

**Gate:** PG-0 (OD-1 decision) before starting; then the PR's single approval gate — which
this package's own §7 line makes the permanent gate for every future CLAUDE.md edit.

**Verification:** `git ls-files CLAUDE.md` shows it tracked; fresh-clone spot check (clone to
scratchpad, confirm CLAUDE.md present and header accurate); `git config --get
riverbend.allowRepoClaudeMd` returns `true`; after the rename, a session opened in
`riverbend-demo` still resolves the correct rules. **Amendment a1:** that worktree's tip
`07a0c0b` dropped its tracked CLAUDE.md, so today it reads the parent file — after the parent
rename it would have **no rules at all**. Rebase-or-retire `riverbend-demo` is a hard
precondition of the rename, not an option.

**Rollback/skip cost:** rollback is `git rm --cached CLAUDE.md` + restore the ignore line +
un-rename the parent — cheap, no code touched. Skipping the package leaves rules unreviewable
and worktree-fragile, and PIPE-4's rule has no reviewable home; PIPE-2/3 survive a skip,
PIPE-4 degrades to a local-only rule.

---

### PIPE-2 — Brief-as-file: `docs/plans/` + `feature-start`/`spec-lens` contract edits

Gives the plan stage a file home and stable IDs, replacing the chat-only brief.

**New files:**

- `docs/plans/_template.md` (~60 lines): plan-doc shape — header naming the week/spec it
  serves, `WN-P<n>` plan-item IDs (allocated once, never renumbered), a "requirements served"
  column mapping each plan item to `WN-Rn` spec IDs, a spec-lens findings/waivers section
  (PG-3's artifact), and the PG-3 outcome line destined for `review-loop-metrics.md` §6.
- `docs/review-loop-metrics.md` §6 "Pre-code gates" (~15 lines): the append-only gate ledger
  from §1 above. Append-only file — this adds a section, rewrites nothing.

**Contract edits:**

- `.claude/commands/feature-start.md` — the "After the brief" section currently ends the
  command at chat: "Ask the user how they want to proceed … Optional next step: once a plan
  brief exists, offer the `spec-lens` skill … Optional, never mandatory." Change: the brief is
  **written to `docs/plans/wN-<slug>.md`** from the template; spec-lens then runs against that
  file's content and PG-3 (human amends the file) replaces "optional, never mandatory" as the
  exit to `pr-open`. (Naming follows [[branch-names-describe-work]]: slug describes the work.)
- `.claude/skills/spec-lens/SKILL.md` — two lines change. Input line ("**Input:** the brief
  text plus the week's spec path") gains the file as the canonical source; the paste-in
  mechanic ("the main thread pastes the full brief text into each lens prompt") is **kept** —
  the main thread reads the plan file and pastes it, so lens fences don't widen. The
  never-edits contract ("This skill NEVER edits the brief or the spec … the human amends the
  brief") is **kept verbatim** — the human now amends a file instead of a chat message, which
  strengthens the HITL gate (the amendment is diffable).

**Gate:** introduces PG-3's artifact and ledger.

**Verification:** dry run — invoke `/feature-start` for a shipped week in report-only spirit,
confirm it writes a plan file matching the template and spec-lens consumes it; confirm the
ledger line lands in `review-loop-metrics.md` §6 **tagged `dry-run`** (amendment a3), so
dry-run stops never pollute the gate-effectiveness measurement.

**Rollback/skip cost:** revert two tooling files and delete the template — nothing downstream
hard-depends on it except PIPE-5/PIPE-6, which degrade to today's chat-brief behavior.
Note: while `.claude/` is untracked (OD-1 pending), these contract edits ship in no PR — the
snapshot repo is their only history. If OD-1 lands as "track", fold them into a PR.

**Size:** 2 new files (~75 lines), 2 edited tooling files (~25 lines).

---

### PIPE-3 — Spec template §5b amendment pattern; arm the design gate

Makes `address-review`'s design gate fireable by giving weeks requirement IDs — without
rewriting shipped client-ask prose.

**The pattern (generalizing TODO-6's precedent, already the settled W3 shape):**

- **Shipped weeks (W1–W3, W7):** §1–§4 stay verbatim — the client ask is the graded input.
  New work appends a `§5b` EARS block (`W3-UI-R…` style) + §6 gates; the shipped prose
  criteria in §5 are never retro-rewritten. Backfill IDs **lazily** — only when a review
  round actually needs to cite one.
- **Unshipped weeks (W5, W6, W8, W9, W10, plus whichever weeks take TODO-1 and TODO-44):**
  full template conformance, but the EARS §5 is written by the pipeline's **spec stage at
  `/feature-start` time** (PIPE-5), behind PG-2 — not bulk-converted now. Bulk conversion is
  speculative work on asks that may be re-decoded at PG-1.
- **W4 (next week up):** its §5 EARS rewrite is already registered as TODO-5; execute it
  under this package's pattern as the first live conversion, since W4's `address-review`
  rounds are the first that will need IDs.

**Files:** `docs/specs/_template.md` (+~20 lines: the amendment-pattern rules above, in the
§0 guidance voice); `docs/specs/w4.md` (§5 → EARS table with `W4-Rn` IDs, verification cells
mapping to the existing checklist criteria — discharges TODO-5); optionally `docs/specs/w3.md`
§5b as TODO-6 specifies, as the worked shipped-week example. `docs/todo.md`: check off
TODO-5 (and TODO-6 if done).

**Fence note (feeds OD-2):** writing §5 for our-owned sections does not breach spec-lens's
fence — the template's own header pattern ("scope / deliverables / acceptance criteria are
ours", e.g. `w6.md` line 3) marks §3–§6 as our work; the fence protects §1/§2, the graded
decode. But the fence's *wording* says "never the curriculum spec", full stop, so it must be
rewritten explicitly under OD-2, not silently narrowed.

**Gate:** serves the existing `address-review` design gate (arms its "maps to no requirement
ID" trigger); W4's conversion is reviewed at that PR's normal approval gate.

**Verification:** for w4.md — every EARS row satisfies the template rules (shall-only, one
behaviour, verification named); every old checklist criterion maps to ≥1 ID (no silent scope
change); `address-review` §3's "Requirement delta" step can name a real `W4-Rn`.

**Rollback/skip cost:** template edit reverts cleanly. Skipping leaves the design gate
unfireable on 10/11 specs — the central defect this plan exists to fix — and PIPE-5's spec
stage without a written pattern to follow.

**Size:** 1 template edit (~20 lines), 1 spec conversion (~30 lines), optional second (~15).

---

### PIPE-4 — ID-block reservation rule for shared registries

Turns the accidental fix ("IDs 28–39 are allocated on branch …") into a written rule, closing
the twice-proven collision class (ADR 0005 numbering; TODO-40).

**The rule (CLAUDE.md §10 material, drafted for the PR):** before a stream (parallel session,
worktree, or parked branch) allocates IDs in any shared append-target — `docs/todo.md`
TODO-n, `adr/` numbers, `docs/debt-log.md` D-n, spec `WN-Rn` blocks, `docs/plans/` `WN-P<n>`
— it reserves a block by a one-line note **in the registry itself on `main`** (the todo.md
"IDs 28–39" line is the worked example). Reservations are small (≤12), never reused even if
the branch dies, and gaps are deliberate, not renumbering targets. `review-loop-metrics.md`
rounds are per-PR-scoped and exempt.

**Files:** `CLAUDE.md` (new §10.6, ~15 lines); `docs/todo.md` header (generalize the existing
IDs-28–39 sentence into the rule's pointer, ~3 lines); `adr/_template.md` if it has a
numbering note to align (verify at implementation).

**Dependency:** soft on PIPE-1 — the rule can be written into the local CLAUDE.md today, but
only a tracked CLAUDE.md makes it PR-reviewed and visible to every worktree, which is the
point of a parallelism rule. Land it inside or immediately after PIPE-1's PR.

**Gate:** none of its own; the CLAUDE.md edit rides PIPE-1's approval gate (or its own PR's).

**Verification:** by inspection at PR review; first real test is the first pair of parallel
packages from this very plan allocating TODO/plan IDs without collision.

**Rollback/skip cost:** trivial revert. Skipping means the third collision is a matter of
time once PG-3 starts emitting parallel streams — the failure is proven, not hypothetical.

**Size:** 2–3 files, ~20 lines.

---

### PIPE-5 — `feature-start` synthesize/amend path (the front of the pipeline)

**Contract change (quoting the line being changed):** `feature-start.md` currently handles
only the missing case: "If a `w<N>.md` is somehow missing, say so and stop rather than
reconstructing the ask from memory — the spec docs are the only canonical copy of the
client's words." Replace the stop with two paths, keeping the rule's reason intact:

- **Missing spec → synthesize:** the human pastes the curriculum ask verbatim (the command
  still never reconstructs §1 from memory — that guard survives, it just gains a legitimate
  input); the command writes `wN.md` §1 (verbatim paste) + §2 (decode: defect, debt IDs,
  tickets) → **PG-1**: human confirms the decode against the paste.
- **Thin/pre-template spec → amend:** apply the PIPE-3 pattern (§5b for shipped weeks; full
  §5/§6 for unshipped) — the **spec stage**: write §5 EARS + IDs and §6 gates → **PG-2**:
  human signs the end state.
- Then the Phase-2 brief proceeds as today, exiting via PIPE-2's plan stage
  (`docs/plans/wN-<slug>.md` → spec-lens → PG-3).

Both PG-1 and PG-2 stops append their ledger line (§1 above).

**Files:** `.claude/commands/feature-start.md` (+~40 lines). Same untracked-tooling caveat
as PIPE-2 pending OD-1.

**Dependencies:** PIPE-2 (plan file home), PIPE-3 (amendment pattern to execute).

**Gates:** introduces PG-1 and PG-2.

**Verification:** live run — `/feature-start W6` (unshipped, real target): confirm it stops
at PG-1 with §1/§2 written, at PG-2 with §5/§6 written, and hands a plan file to spec-lens.
W6's existing spec is decent prose, so the run exercises the amend path end to end.

**Rollback/skip cost:** revert one tooling file; specs already written stay valid (they're
just template-conformant specs). Skipping keeps the pipeline headless — specs only get IDs
by hand, and PG-1/PG-2 never exist.

**Size:** 1 file, ~40 lines.

---

### PIPE-6 — `/dashboard` per-week pipeline-stage reporting

**Contract change (quoting the render spec being extended):** `dashboard.md` step 5 renders
"A table: Week | Feature | Status | Spec | Evidence (PR #/ADR/commit)". Add a **Stage**
column: `— / spec / plan / impl / shipped` (amendment a2: no `brief` stage — the brief *is*
the plan file), derived from artifacts, not memory:

- `spec` — `wN.md` §5 contains an EARS table (`grep -l '^| \`W[0-9]*-R'` over `docs/specs/`);
- `plan` — `docs/plans/wN-*.md` exists (`ls docs/plans/`);
- `impl` — open PR or branch for the week (already gathered in step 1A);
- `shipped` — existing Done verdict.

Two cheap additions to the step-1 gather (one `grep -l`, one `ls`) — respecting the command's
own token discipline (§6 budget table; the whole gather targets ~2.5k tokens, these add ~100).
Also render the last ledger line per gated week from `review-loop-metrics.md` §6, so gate
outcomes are visible where status is read.

**Files:** `.claude/commands/dashboard.md` (+~25 lines). Untracked-tooling caveat as above.

**Dependencies:** PIPE-2 (plans dir to detect), PIPE-3 (EARS marker to grep). Can land
before PIPE-5 — stages simply read `—` until the pipeline produces artifacts.

**Gate:** none; serves visibility of all of them.

**Verification:** run `/dashboard`; confirm stage column matches hand-derived truth for W4
(spec, after PIPE-3) and W6 (whatever PIPE-5's dry run left), and token cost stays in budget.

**Rollback/skip cost:** trivial revert. Skipping loses only visibility — nothing downstream
depends on it.

**Size:** 1 file, ~25 lines.

---

## 3. Dependency graph

```
PG-0 (OD-1) ─→ PIPE-1 ──(soft)──→ PIPE-4
approval ────→ PIPE-2 ──┬──→ PIPE-5 ──→ pipeline live (PG-1..3 firing)
             → PIPE-3 ──┤       │
                        └──→ PIPE-6 (can precede PIPE-5; reads richer after it)
```

Parallel-pickup guidance: PIPE-2, PIPE-3 and PIPE-4-drafting are independent of each other
and of PIPE-1's review. Any session picking one up cites its `PIPE-n` ID and reserves any
registry IDs it needs per the PIPE-4 rule (apply the rule from this plan even before it is
formally landed — it costs one line).

## 4. Deliberately NOT in scope

| Out | Why | Tracked where |
|---|---|---|
| Runtime parallelism (port offsets, concurrent `make up`) | `docker-compose.yml` publishes fixed host ports (5432, 8070, 3070); unit tests don't need the stack. Known limit, fix unplanned unless the human asks | CLAUDE.md §10.4 ("Only one Docker stack at a time across trees") |
| Retro-EARS on shipped weeks (W1–W3, W7 §5 rewrites) | Shipped prose criteria are the graded record; lazy backfill only | PIPE-3 pattern in `docs/specs/_template.md`; TODO-6 for W3's §5b |
| CI running `.claude/` tooling | Impossible by design even under full tracking — hooks don't run in CI; anything gating a merge belongs in `.github/workflows/` or the Makefile | `.gitignore` comment block; CLAUDE.md §10.1 |
| TODO-1 (intake contract break), TODO-44 (visit-chat UI) | Pipeline **cargo**, not pipeline work — they are the first weeks the pipeline should carry, not steps of it | `docs/todo.md` TODO-1 / TODO-44 |
| `.claude/gates` statusline revival | The `/gates` tracker was the rebuild's gate track, retired with it; PG-n visibility lives in `/dashboard` (PIPE-6) | TODO-23 (closed) is the record |

## 5. Risks worth naming

- **Half-portable state (if OD-1 = don't track):** a tracked CLAUDE.md cites skills a fresh
  clone doesn't have. Mitigation if so decided: a §10.1 line stating exactly that, so the gap
  is documented rather than discovered.
- **Untracked tooling edits (PIPE-2/5/6) have no PR review** until/unless OD-1 tracks
  `.claude/`. Mitigation: the snapshot repo captures them; this plan is their reviewed design.
- **Gate fatigue:** three new human stops per week. The §1 ledger is the countermeasure —
  measured, a gate that never amends anything gets removed, per the same discipline that
  justified `address-review`'s gate with 58% B+C evidence.
- **`riverbend-demo` staleness:** its branch tracks a pre-descope CLAUDE.md of its own;
  PIPE-1 step 8 must handle it explicitly rather than assume the rename suffices.

## 6. Open decisions (template §8 shape)

**All three decided at PG-0, 2026-08-05:**

- **OD-1 — DECIDED: track `.claude/`**, excluding `settings.local.json`, `gates/state.json`,
  `scheduled_tasks.lock`, and `__pycache__`; fixtures stay tracked.
- **OD-2 — DECIDED: as recommended**, including the Lens-4 traceability check (plan items
  citing `WN-Rn` IDs absent from §5 = finding).
- **OD-3 — DECIDED: the gate ledger lives in `review-loop-metrics.md`.** Numbering correction
  at execution: the decision said "§5" but that file already has a §5 ("How to reproduce"), so
  the ledger is **§6** — same file, same append-only discipline. Section seeded at approval
  with PG-0's line (user instruction overriding the original "lands with PIPE-2" — PIPE-2 now
  only wires the tooling appends).

Original rows kept for the record:

| # | Decision | Blocks | Unblocked by |
|---|---|---|---|
| OD-1 | **Track `.claude/` (skills/hooks/commands) alongside CLAUDE.md?** *Track:* rulebook and tooling travel together; fresh clones and parallel worktrees get identical pipeline behavior; contract edits (PIPE-2/5/6) become PR-reviewed. Costs: tooling churn lands on every branch again (the exact friction PR #32 removed), secrets/hooks hygiene review needed before first push, and CI still cannot run any of it (`.gitignore`'s own comment records that — tracking buys portability, not enforcement). *Don't track:* status quo, zero churn; costs the half-portable state — a tracked rulebook citing invisible tooling — accepted and documented. **Recommendation: track, excluding `settings.local.json` and anything secret-bearing** — this plan makes tooling load-bearing for a multi-stream pipeline, and unreviewed load-bearing tooling is the §10.1 failure mode. Human decides (PG-0). | PIPE-1 final shape; whether PIPE-2/5/6 edits ship in PRs | user decision at PG-0 |
| OD-2 | **spec-lens fence resolution.** The skill's rationale ("client asks are deliberately underspecified … 'completing' them would do the graded work") protects §1/§2; its wording ("never the curriculum spec") fences the whole file, contradicting a pipeline whose spec stage writes our-owned §5/§6. **Recommendation:** keep the never-edits contract absolute (spec-lens edits nothing, ever); rewrite the fence's *reviewing* scope to name §1/§2 as the protected decode; optionally add a cheap traceability check to Lens 4 (plan items citing `WN-Rn` IDs that don't exist in §5 = finding). Explicit rewrite in PIPE-2's spec-lens edit, never a silent override. | PIPE-2's spec-lens edit text | user sign-off on this plan (or an amended resolution at PG-0) |
| OD-3 | **Where the gate ledger lives:** `review-loop-metrics.md` §6 (recommended — one measurement file, same A/B/C discipline and audience) vs a new `docs/gate-ledger.md`. Low stakes; default to the recommendation unless the human objects at plan approval. | PIPE-2's ledger section | plan approval |

## 7. Registry updates on approval

On plan approval (not before): one `docs/todo.md` line pointing at this file for the pipeline
work (ID per PIPE-4 rule), and the PIPE-1 reversal line from its step 6. `wN.md` specs own
week requirements, `debt-log.md` owns risk — this plan owns only the pipeline build, and dies
(moves to done) when PIPE-1..6 are checked.
