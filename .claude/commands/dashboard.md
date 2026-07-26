---
description: Show engagement status — curriculum weeks vs. actual shipped debt fixes, PRs, and ADRs
---

Generate a fresh status dashboard for the Riverbend engagement. Do NOT answer from memory alone — memory can be stale. Re-derive current status from the repo every time this command runs, using the checks below, then render the report.

## 1. Gather ground truth

Run these three blocks **in one message, in parallel**. They are written to emit only the
deciding signal — resist widening them. This command is a status glance; the whole gather
should cost roughly 3k tokens of tool output, and every line below was chosen because a
cheaper form of the same check was measurably wasteful (see "Token budget" at the end).

**A — artifact inventory + PR ledger**

```bash
gh pr list --repo 2463-FDE/AD-riverbend-portal --state all --limit 50 \
  --json number,title,state --jq '.[]|"#\(.number) \(.state) \(.title)"'
ls adr/ docs/ docs/specs/ eval/rag/ tests/ tests/integration 2>/dev/null | grep -v __pycache__
```

The `tests/` listing is not optional padding — six criteria across W1/W3/W6/W7 read "proven by
test," and the test **filenames** are what discharge them (`test_payer_breaker.py`,
`test_intake_freeze_regression.py`, …). Without it you end up making a 4th call for it anyway.
Only `grep "def test"` inside a file when a filename genuinely doesn't settle the criterion.

**B — code markers, deliberate gaps, debt-log statuses**

```bash
grep -rn "D[0-9]" services/*/*.py \
  | grep -iE "remediat|fixed|flagged|not fixed|preserved|intentional|DEBT|deliberate"
grep -rn "xfail" tests/ --include='*.py'
grep -nE "^\| D[0-9]|^- \*\*Status:\*\*" docs/debt-log.md
```

**C — the acceptance criteria (this is the actual verdict evidence)**

```bash
for f in docs/specs/w*.md; do echo "### $f"; sed -n '/^## 5\./,/^## 6\./p' "$f"; done
```

Notes on the commands, so they don't get "helpfully" broadened again:

- `services/*/*.py` already covers every `app.py`. Do **not** also pass `services/*/app.py` —
  the globs overlap and every hit prints twice.
- Read `docs/debt-log.md` through the grep, not `head`/`Read`. The prose entries are long and
  the only thing this command needs from them is the per-D status line. (Hand-maintained and
  lags recent PRs — cross-check against the code markers, don't trust it blindly.)
- `grep -rn "D[0-9]"` beats enumerating `D1\b\|D4\b\|…` — it survives new debt IDs and is shorter.
- Never `find` for artifacts. It walks `.venv/`, `node_modules/`, and `.git/` and returns mostly
  noise. `ls` the directories you actually care about.
- **Only if an open PR exists**, get its CI state as one line — never dump `statusCheckRollup`
  JSON (12 check objects with URLs and timestamps, to learn one word):
  ```bash
  gh pr checks <N> --repo 2463-FDE/AD-riverbend-portal --json state --jq '[.[].state]|unique|join(",")'
  ```
  (Use the `--json state` form, not `| awk '{print $2}'` — the matrix jobs are named
  `services (gateway)` etc., so column 2 is the service name, not the check status.)
- If a PR's contents are genuinely unclear from its title, use
  `git show --stat --format=%s <sha>` — not bare `git show --stat`, which prints the full
  commit body.

Block C is the irreducible cost: ten specs × ~6–9 criteria is what makes the verdicts
auditable rather than vibes. Everything else reduces to "does artifact X exist," which the
`ls` and the greps answer. Only open a full spec doc when a criterion's wording is ambiguous
enough that you cannot judge it from the checklist line alone.

## 2. Reference: curriculum week → debt → deliverable

**Spec docs are the source of truth.** Every week now has a `docs/specs/w<N>.md`; that doc's **Acceptance criteria** section is the authoritative done-definition — check each criterion against the code/PRs/tests you gathered in step 1, not just "an artifact exists." The docs also own the full prose (client ask, decoded defect, scope in/out, deliverables, landmines). The index below is only a name/debt/ticket lookup so the render can label rows — read the matching spec for anything more. The **fallback** rule in step 3 applies only if a `w<N>.md` is somehow missing.

This index is stable (feature short-name + debt + ticket from the training program's `client-delivery.html`, healthcare/Riverbend track). Detail lives in the spec docs, not here.

| Wk | Feature | Debt ID / ticket | Spec |
|----|----|----|----|
| 1 | PHI-safe LLM wrapper | D1 | `docs/specs/w1.md` |
| 2 | RAG dedup/fragmentation eval | D5a / RIV-160 | `docs/specs/w2.md` |
| 3 | Eligibility agent (timeout/breaker) | D4 / RIV-088, RIV-141 | `docs/specs/w3.md` |
| 4 | Patient-view IDOR fix | D11, D8 | `docs/specs/w4.md` |
| 5 | Double-booking fix (spec only) | D5b / RIV-175 | `docs/specs/w5.md` |
| 6 | HL7 allergy/med mapping fix | D6 / RIV-160 | `docs/specs/w6.md` |
| 7 | Tracing + LLM guardrail | (new) | `docs/specs/w7.md` |
| 8 | Safe-Harbor de-id + BAA memo | D13, D14 | `docs/specs/w8.md` |
| 9 | RBAC + ROI authorization | D7, D12 | `docs/specs/w9.md` |
| 10 | Append-only audit trail (capstone) | D2, D12 | `docs/specs/w10.md` |

## 3. Classify each week

For each week, decide Done / In Progress / Pending using this rule, not vibes:

**If the week has a `docs/specs/w<N>.md`:** the verdict is driven by its **Acceptance criteria** checklist. Evaluate each criterion against step-1 evidence (PRs, code markers, tests, docs).
- **Done** — every acceptance criterion is met (with evidence).
- **In Progress** — some criteria met, some not.
- **Pending** — no criterion met.
Report *which* criteria are unmet (this is the point of the spec — the verdict is auditable, not a vibe). Note that a spec may intentionally cap a build week at analysis/prototype + human-approval gate (e.g. W4) — a criterion like "auth fix flagged for approval, not merged" is *satisfied* by the flag, so don't mark the week Pending just because the underlying bug is still live by design.

**If the week has NO spec doc yet** (fallback):
- **Done** — the week's deliverable artifact exists (PR merged shipping the described code/doc) AND, for build weeks, the code markers/tests confirm the described behavior actually changed. For the two spec-only weeks (5, 9), "Done" means the spec/ADR doc exists — a spec-only week is NOT pending just because the underlying bug is still open by design.
- **In Progress** — partial artifact exists (e.g. one half of a two-part deliverable shipped, or an open PR).
- **Pending** — no artifact found; code markers still say "flagged, not fixed" / "intentional" / xfail with no accompanying doc.

Watch for deliverables that shipped under a differently-named PR (e.g. a tracing/guardrail feature landing inside an unrelated-sounding PR title) — check ADRs and code, not just PR titles.

## 4. Also report, separately from the week table

- Any shipped work that falls **outside** the 10-week debt track (e.g. frontend UX/accessibility hardening) — list PR numbers, don't force them into a week row.
- Open PRs awaiting review, if any (`gh pr list --state open`).
- The single biggest currently-open risk (pick from the Pending rows + `docs/debt-log.md` — prefer PHI/authz/patient-safety items).

## 5. Render

Print one markdown report to chat (no file write) with:
1. A table: Week | Feature | Status | Spec | Evidence (PR #/ADR/commit) — use the Feature short-name from step 2, not just "W1"/"W2"; the **Spec** column marks whether a `docs/specs/w<N>.md` exists (✓ / —) so it's visible which verdicts are criteria-checked vs. fallback-judged; add a one-line Deliverable summary under each row if the Feature name alone doesn't make the ask clear
2. For any spec-backed week that is **not** Done, a one-line "unmet: …" listing the failing acceptance criteria
3. A short "shipped outside the track" list
4. A short "biggest open risk" line
5. If any spec doc's scope disagrees with the step-2 table, a one-line drift flag

Keep it terse — this is a status glance, not a new debt log. Do not modify `docs/debt-log.md` or any repo file as part of this command.

## 6. Token budget

Target: **~2.5k tokens of tool output** for the whole gather, in **3 tool calls** (the three
parallel blocks in step 1, +1 `gh pr checks` only if a PR is open). Measured: the 2026-07-26
run came in at ~2.4k / 4 calls against ~7k / 8 calls for the pre-patch version, with identical
week verdicts. Per-block: A ~500, B ~900, C ~950. Waste from that earlier run, kept here so
the same mistakes don't get re-invented:

| Anti-pattern | Cost | Cheap form |
|---|---|---|
| `head -80 docs/debt-log.md` | ~1.1k | grep the status lines (step 1B) |
| `gh pr view --json statusCheckRollup` | ~1k | `gh pr checks --json state --jq unique` |
| `find . -iname "*eval*"` | ~400 | `ls` the known dirs |
| Overlapping `services/` globs | ~350 | single `services/*/*.py` glob |
| `git show --stat <sha>` | ~500 | `--format=%s`, or skip |
| `--json …,url` on the PR list | ~200 | drop `url` and `mergedAt` |

If a check would produce more than ~30 lines, narrow it before running it rather than
skimming the output afterwards.
