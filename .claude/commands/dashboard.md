---
description: Show engagement status — curriculum weeks vs. actual shipped debt fixes, PRs, and ADRs
---

Generate a fresh status dashboard for the Riverbend engagement. Do NOT answer from memory alone — memory can be stale. Re-derive current status from the repo every time this command runs, using the checks below, then render the report.

## 1. Gather ground truth (run these fresh, in parallel where possible)

- `gh pr list --repo 2463-FDE/AD-riverbend-portal --state all --json number,title,state,mergedAt,url` — shipped PRs
- `ls adr/` — ADRs written
- `docs/debt-log.md` — canonical debt registry + stated status per D-number (note: this file is hand-maintained and may lag recent PRs — cross-check against code, don't trust it blindly)
- `grep -rn "D1\b\|D4\b\|D5\b\|D6\b\|D8\b\|D11\b\|D12\b" services/*/app.py` — inline debt markers left in code; "REMEDIATED" vs "flagged, not fixed" / "intentional" language tells you the real current status, which can differ from docs/debt-log.md
- `grep -rn "xfail" tests/` — deliberately-left-open gaps (IDOR, HL7 AL1/RXA)
- `ls docs/` for any week-specific artifact (spec docs, comprehension reports, RBAC/ROI ADRs, audit-trail design docs)
- `ls docs/specs/` and read any `w<N>.md` present — these are the **per-week engagement specs** and are the **authoritative done-definition** for the weeks they cover (see step 2)

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
