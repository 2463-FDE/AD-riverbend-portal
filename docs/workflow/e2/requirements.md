# E2 Requirements

> Status: DRAFT
> Source: engagement owner ask, 2026-08-08 (re-synthesized same day, see §1)

## 1. Raw ask (verbatim)

Original ask:

> we'll explore adding reqs to expedite noncode merge while keeping two things in mind: we
> still scan/verify docs to remain compliant in terms of secrets/phi, and keeping blast
> radius small

Preceding context in the same session:

> How is Riverbend CI currently configured? Currenlty, it seems to run full pipeline
> regardless of diff. For example, it when we do non-code merge we must wait for full
> pipeline check for just doc changes. Would changing CI behavior to only check services
> that had change touch a landmine zone? Thoughts only

Re-framing ask, after a review of the first draft:

> e2 -> reconsider e2 reqs from the lens of tackling existing reqs and debt. Speed efficiency
> is a nice reward but not the primary goal. Address the reqs that you wrote with the insights
> youve gathered

Governing principle, stated earlier in the same session:

> We should be able to finish e2 and not have to reverse a decison later to tackle existing
> depth. If we can arrive at a solution that does both we should. We can break up the planned
> work into chunks if we have to later. speeding up noncode merge is nice, but not at the cost
> of having to revisit this later

## 2. What this document is now

The first draft of this file was organized around merge latency, with compliance as a
constraint on it. The re-framing ask inverts that, and the inversion is warranted by what the
repo measurement actually found: **the compliance controls the original ask assumed were in
place are partly absent, and three registry entries describe CI enforcement that does not
exist.** Latency is a by-product of fixing those, not the reason to.

This is a full re-synthesis, not an edit. Requirement IDs are preserved where the requirement
survives (they are allocated once and never renumbered); §7 records what changed and why,
including four defects in the first draft.

## 3. Context

### 3.1 What CI does today

`.github/workflows/ci.yml` — seven jobs, no path filtering, every push and every PR runs
everything. Measured on run `31243409882` (PR #59, docs-only diff):

| | job | duration |
|---|---|---|
| critical path | `frontend` → `frontend-boot` → `docker-build` | 58s → 65s → 80s = **203s** |
| off critical path | `tests` 60s, `services` ×8 (11–19s), `secret-scan` 9s, `eval` 7s | all inside 60s |

Whole workflow **3m31s**. Every merge fires two runs — the PR run (blocking) and a push run on
`main` after squash (~200s, unwatched).

### 3.2 Gap 1 — the boot probe gates nothing

Branch protection, live (`gh api repos/:owner/:repo/branches/main/protection`): twelve required
contexts — `frontend`, `services (×8)`, `tests`, `secret-scan`, `eval`. **`docker-build` and
`frontend-boot` are absent.** `strict: true`.

Three tracked documents say otherwise:

- `docs/todo.md` TODO-45 (closed by e1): "wired into the terminal `docker-build` fan-in via
  `needs` (codex r2) — a boot-broken image now goes red, not green, **on the job branch
  protection reads**."
- `docs/workflow/e1/review-findings.md` row 1: "Anything reading `docker-build` as the terminal
  signal (branch protection, merge queue, deploy automation) can go green while the boot probe
  fails."
- `docs/runbook.md` CI section.

The `needs:` edge e1 added is real and correct. The claim that branch protection reads it is
not. e1's central deliverable — a boot-broken frontend cannot ship green — is **currently
unenforced**, and TODO-45 is closed on a claim that does not hold.

### 3.3 Gap 2 — PHI in the documentation surface is unguarded

CI runs gitleaks v8.18.4 with **no repo-root `.gitleaks.toml`**, so the default ruleset only:
credential regexes and entropy. No SSN, DOB, or name rule.

`docs/phi-logging-policy.md:1-4` scopes itself to "every service in this repo, on every log
handler." Its register is code sites plus one file. **Tracked documentation and workflow
artifacts appear nowhere in it, and nothing scans them.**

Live instance — `docs/workflow/w1/requirements.md:14`, tracked, on `main`, landed via the
non-code fast path:

```
body={"name":"Maria Gonzalez","dob":"1971-03-02","ssn":"412-55-9981","insurance_id":"BCBS4471"}
```

Same SSN twice more in `docs/workflow/w2/requirements.md:13,45` (untracked at time of writing).
Per `CLAUDE.md` §0 the corpus is synthetic but the handling discipline is the graded surface.

The import path is structural, not accidental: `.claude/skills/requirement-synthesis/SKILL.md`
step 1 mandates the owner's ask be quoted **verbatim, never paraphrased**, and these asks are
drawn from log lines and CSV exports. The stage that opens every work item is the stage most
likely to import PHI into a tracked file.

**Precedent:** the phi-logging-policy register already carries `logs/intake-service.log`
(git-tracked) as **OPEN — ops**, "Historical entries contain plaintext PHI." Same class — PHI
resident in a tracked non-code file. This is a second instance, not a new category.

### 3.4 The PHI surface, measured

Enumerated across tracked files (`git ls-files`), not just docs. SSN-shaped strings:

| location | hits | disposition |
|---|---|---|
| `db/seed/seed.sql` | **256** | intentional; byte-pinned by `eval/rag/check_drift.py`. Cannot change. |
| `db/seed/patients.csv` | 5 | generator input. Cannot change. |
| `tests/**` — 12 files | many | fixtures that exist to test redaction. Must not change. |
| `frontend/app/intake/page.tsx:279` | 1 | `"123-45-6789"` inside a comment. |
| `eval/rag/data.py` | 1 | eval corpus. |
| `docs/workflow/w1/requirements.md:14` | 1 | **unmanaged — the actual finding** |
| `docs/workflow/w2/requirements.md:13,45` | 2 | **unmanaged — untracked, not yet landed** |

This is the decisive constraint on the detector's design and it invalidates the first draft's
approach (§7, defect 1). A repo-wide SSN rule fails CI immediately on seventeen files, none of
them remediable. **The distinction that matters is not the pattern, it is the surface:** PHI in
seed, tests, and eval data is deliberate, registered, and load-bearing; PHI in the narrative
documentation surface is unmanaged and has no owner. The check belongs on the second surface
only — which is the same path set `noncode-merge` already calls non-code.

### 3.5 Gap 3 — registry entries that describe a CI that does not exist

- `.github/workflows/ci.yml:113` labels the job "recurrence guard for **D9**".
  `docs/debt-log.md:6-7`: "the client's week-1 brief referenced D1/D9/D3. **D9 and D3 do not
  exist in this repo**." The comment cites a debt ID with no entry.
- `docs/debt-log.md:312` (cross-cutting): "No secret/dependency/image scanning in CI — OPEN",
  contradicting `:285` four rows up, which records the secret half **DONE** in PR #2
  (`8858097`). Two rows, same file, opposite claims.
- TODO-45 / `e1/review-findings.md` / `runbook.md` per §3.2.

None appear in TODO-52's doc-drift file list, so all are new.

### 3.6 Registry alignment

Checked before treating anything here as new (`CLAUDE.md` §8):

| Registry item | Relation to e2 |
|---|---|
| `docs/todo.md` TODO-27 — path routing, deliberately declined 2026-07-31 | **Untouched by e2** (D-8). Reopens only at `e3`. Grounds for reopening, recorded so they do not have to be re-derived: TODO-27 measured routing *by service* — correct then, still correct — but never measured the *frontend chain*, which did not exist at the time (the `portal` job was the frontend cost, and TODO-27 itself records its removal; `frontend-boot` and `npm test` arrived with e1 on 2026-08-07, taking the critical path 130s → 203s). Its blockers are answerable, not waivable: (a) is void if `tests` is never routed, which is TODO-27's own prescription; (b) requires gating **steps**, not jobs — a job skipped by job-level `if:` reports `skipped`, a job with no-op steps reports `success`. |
| `docs/todo.md` TODO-45 — closed by e1 | Closure claim false against live config. E2-REQ-12 makes it true; E2-REQ-13 corrects the text. |
| `docs/debt-log.md:312` | E2-REQ-13. Stale OPEN. |
| `docs/debt-log.md:285` step 4 | E2-REQ-2 preserves it. Full-history half excluded (§6). |
| `docs/landmines.md:67` | Confirms gitleaks is `--no-git`, no dep/image scan. |
| `docs/todo.md` TODO-43 — drift gate blind to eval-code changes | Not overlapping, but it is the same failure shape E2-REQ-8 guards: a green gate covering less than it appears to. This repo has shipped one already. |
| `docs/todo.md` TODO-53 — 17 docs invoke dead tooling | Its sequencing rule ("build the process first, then reconcile") backs E2-REQ-11: amending a live skill is building the process. |
| `docs/todo.md` TODO-52 — doc-drift sweep | Does not list `ci.yml`, `debt-log.md:312`, or the TODO-45 drift. All new. |
| `docs/phi-logging-policy.md` register — `logs/intake-service.log`, OPEN | Precedent for E2-REQ-9 (§3.3). |

For the stamp's expectations: **e2 closes zero open TODO lines.** TODO-45 is already checked;
e2 makes its closure claim true (REQ-12/13) and narrows TODO-52 by one item (the runbook CI
section). The value is enforcement and new-gap coverage, not register burn-down.

### 3.7 Standing constraints

- `CLAUDE.md` §11 — skills and hooks run only in a Claude Code session and **cannot gate a
  merge**. Only `.github/workflows/ci.yml` and the `Makefile` can.
- TODO-27 blocker (b) — a workflow-level `paths:` filter never reports a required check, so a
  filtered-out required job leaves the PR unmergeable forever.
- TODO-27 blocker (a) — `tests/test_compose_topology.py:249` reads both `docker-compose.yml`
  and `ci.yml`; coupling no path glob can see. `tests` is therefore never routed.
- `noncode-merge` "Never" — `docs/specs-deprecated/**` is frozen archive.

## 4. Requirements

### 4.1 Decisions carried forward

| # | Decision | Status |
|---|---|---|
| D-2′ | PHI detector matches **SSN shape (`NNN-NN-NNNN`), scoped to the documentation surface** (`docs/**`, `adr/**`, `*.md`, `.claude/**`), and blocks. | **Revised** — the first draft's repo-wide rule was unworkable (§7 defect 1). |
| D-3 | Guard and remediate together; e2 redacts existing unmanaged PHI as well as guarding new. | Unchanged. |
| D-4 | Amend `requirement-synthesis` to quote-with-redaction, inside e2. | Unchanged. |
| D-5 | Fold registry housekeeping in rather than filing to TODO-52. | Unchanged. |
| D-6 | Delivery may be chunked across PRs; chunking is sequencing, never scope reduction. | Unchanged, and load-bearing — it is what D-8 acts on. |
| D-7 | CI is where reduced-check state is displayed, not the merge report or PR body. | Unchanged, but **governs `e3`, not e2** — nothing in e2 runs a reduced set of checks. |
| D-1 | *Withdrawn* — it bundled "make the gates real" with "route the frontend chain". Those separate cleanly. | **Split** into D-8. |
| D-8 | **e2 delivers the compliance chunk only. The routing chunk is deferred to a separate item (`e3`).** | Owner decision 2026-08-08, shape B. e2 is latency-neutral (§4.5) and leaves TODO-27 untouched. Deferred requirements listed in §4.4, and the spec stage freezes only §4.2. |
| D-9 | Branch-protection drift recurrence is an **accepted cost**, not a requirement. | Owner decision 2026-08-08. E2-REQ-13 is point-in-time truth; no machine assertion of the required-context set (would need an admin-scoped token — new secret surface). Named in §4.4. |
| D-10 | **Redact-then-quote is the standing policy** for SSN-shaped content in the documentation surface. | Owner decision 2026-08-08. An E2-REQ-3 block on a future legit quote (incident write-up, register entry) is intended behavior — redact, then quote. No allowlist for SSN in docs, ever; matches E2-REQ-11. |

### 4.2 Requirements

| ID | Requirement | Notes |
|----|-------------|-------|
| E2-REQ-12 | A frontend image that builds but does not boot cannot reach `main`. | **Primary.** `frontend-boot` and `docker-build` become required contexts. Makes e1's delivered-but-unenforced boot probe actually gate. |
| E2-REQ-3 | Every change landing on `main` is checked for SSN-shaped content in the documentation surface, and a finding blocks the merge. | ⚠ human-gate — PHI, `docs/landmines.md` §1. **No such check exists.** Scope per D-2′; §3.4 is why. Applies to all PRs, not only fast-path ones (§7 defect 2). A block on a legitimate future quote is intended behavior — redact-then-quote, per D-10. No allowlist. |
| E2-REQ-9 | The guarantee holds for content already on `main`: existing unmanaged SSN-shaped content is redacted as part of e2. | ⚠ human-gate — editing a PHI-carrying tracked artifact is itself a §1 touch. `w1/requirements.md:14`; `w2/requirements.md:13,45`. Fidelity cost acknowledged in §4.3. |
| E2-REQ-11 | The requirement-synthesis stage can quote an owner ask verbatim without importing PHI into a tracked artifact. | Per D-4. Without it the skill mandates exactly what E2-REQ-3 blocks. |
| E2-REQ-13 | Every claim in the registries about what CI enforces matches what CI enforces. | TODO-45 text, `e1/review-findings.md` row 1, `runbook.md` CI section, `ci.yml:113`'s D9, `debt-log.md:312`. `CLAUDE.md` §10's failure mode: the confident stale copy wins. |
| E2-REQ-2 | Every change landing on `main` is scanned for committed secrets before merge, with no reduction in coverage or blocking strength relative to today's `secret-scan`. | Recurrence guard, `docs/debt-log.md:285`, PR #2. The live risk is the detector work weakening it — see §4.3. |
| E2-REQ-4′ | No change is verified *less* than it is today. | **Revised** (§7 defect 3). The first draft said a code PR's pipeline must be "byte-identical", which E2-REQ-12 contradicts by design — it makes code PRs block on checks they previously did not. Verified-no-less is the real floor. |
| E2-REQ-6 | No change to the merge path may leave a PR unmergeable by a required check that never reports. | Acceptance condition on adding required contexts; also covers the switchover (§4.6). |
| E2-REQ-7 | "Non-code" has exactly one definition, shared by the fast path's scope guard and the PHI detector's scope. | Two consumers in e2, a third (the CI-side classifier) when e3 lands. Drifting copies are `CLAUDE.md` §10's named failure — so the definition must be written to be consumed a third time, not inlined twice. |
| E2-REQ-10 | Enforcement of E2-REQ-2 and E2-REQ-3 sits at a point that can actually block a merge. | `CLAUDE.md` §11 — an advisory check does not satisfy a compliance requirement. |

### 4.3 Deferred to `e3` (routing chunk)

Per D-8 these are **not** in e2's scope and the e2 spec must not freeze them. Recorded here so
nothing is lost between items; IDs are re-homed when `e3`'s requirements are synthesized.
D-7 (CI is where reduced-check state is displayed) governs this set, not e2.

| ID | Requirement | Why it waits |
|----|-------------|--------------|
| E2-REQ-1 | A non-code change can land on `main` without waiting on checks the diff provably cannot affect. | The original ask, now explicitly secondary. Baseline 3m31s; floor ~60s, set by `tests`, which is never routed. |
| E2-REQ-5 | When diff classification is ambiguous, mixed, or fails, the full pipeline runs. | Fail-closed classification only exists once there is a classifier. |
| E2-REQ-8 | A merge that ran a reduced set of checks says so in the CI run — which checks did no work, on what classification — on both the PR run and the `main` push run. | Nothing runs a reduced set until routing exists. |
| E2-REQ-14 | The classification is computed once, by CI; every other surface quotes that result rather than recomputing it. | Extends REQ-7 from one *definition* to one *evaluator*. |

`e3` also inherits the two costs that belong to routing rather than to e2: `docker-build` green
ceasing to mean "the image builds" on non-code diffs, and the fact that the PR checks list
cannot show the difference (required contexts match by exact string, so the context name cannot
vary without breaking branch protection — TODO-27 blocker (b)).

**TODO-27 is untouched by e2** and reopens only when `e3` is taken up. The grounds for
reopening it are recorded in §3.6 and do not expire.

### 4.4 Accepted costs

Named here rather than discovered at review:

- **E2-REQ-9 degrades a verbatim record.** Redacting `w1/requirements.md:14` alters a quoted
  owner ask in a section whose purpose is exactness. Judged worth it; the alternative is a
  permanent allowlisted exception.
- **E2-REQ-3's implementation is the single largest risk to E2-REQ-2.** If the detector is
  added as a repo-root `.gitleaks.toml` without `[extend] useDefault = true`, the custom config
  *replaces* the default ruleset and silently disables all credential detection — weakening the
  secrets guard in the act of adding the PHI one. Belongs in the plan as an explicit negative
  test per `docs/landmines.md` §3.
- **The required-context set can drift again, silently (D-9).** Branch protection is click-ops
  GitHub state — not in the repo, not reviewable, asserted by nothing. E2-REQ-12/13 make it
  correct today; the exact mechanism behind the false TODO-45 closure (a job added, protection
  never updated) recurs when any future job lands. Accepted rather than guarded: a machine
  assertion needs an admin-scoped token, a new secret surface on a compliance repo. Whoever adds
  a CI job decides its required status at that moment — nothing enforces that they do.

### 4.5 e2 is latency-neutral

Worth stating plainly, because "we made the pipeline stricter" usually is not free. It is here:

| | today | after e2 |
|---|---|---|
| required contexts | 12 | 14 |
| last required context green at | ~60s | ~203s (`docker-build`) |
| what `noncode-merge` step 6 actually waits for | all 7 jobs, **~3m31s** | all 7 jobs, **~3m31s** |

The skill already waits for every check, so raising the required set to match what is already
being waited on costs nothing in practice. e2 neither speeds up nor slows down a merge; it
changes what a green merge *means*. The latency win is `e3`'s to deliver.

### 4.6 Switchover

Adding required contexts changes merge eligibility for PRs already open when the setting flips.
`gh pr list --state open` currently returns nothing, so the flip is free today. It becomes live
only if e2's own PRs are open at that moment — a plan-stage ordering constraint, not a risk to
resolve now. E2-REQ-6 covers the steady state.

## 5. Open questions

None. Resolved as D-2′ through D-8; awaiting the owner's agreement stamp.

## 6. Out of scope

- **Path routing of `tests`, `services`, `secret-scan`, `eval`** — the original framing of the
  CI question. Zero wall-clock benefit (all finish inside the `frontend` job's 58s), and
  TODO-27 blocker (a) makes `tests` unsafe to route at any speed.
- **PHI in `db/seed/**`, `tests/**`, `eval/**`, `frontend/**`** — 17 files, 260+ SSN-shaped
  strings, all intentional and several byte-pinned by `check_drift.py`. Deliberate, registered,
  load-bearing; a detector firing there produces unremediable red (§3.4).
- **DOB and patient-name detection** — `docs/phi-logging-policy.md` rule 2 makes both PHI even
  alone, so hits are true positives, but they land on `adr/0005-mpi-match-key.md:20`,
  `docs/handover/jira-tickets.md:19`, and `docs/specs-deprecated/w2.md:44` — the last frozen
  archive that `noncode-merge` forbids editing. Unremediable by construction. Revisit only with
  an allowlist design.
- **Full-history secret scan** — open half of the committed-secret remediation
  (`debt-log.md:285` step 4); meaningful only after the human-run history rewrite.
- **Dependency and container image scanning** — the remaining half of `debt-log.md:312`. Lands
  on the critical path and needs its own item.
- **Batching artifacts into fewer PRs** — measured at ~15–18 min over 2.5 days; cannot help the
  stage stamps, which are the merges that most need to land promptly, and trades away the
  cold-readable workflow state `docs/workflow/README.md` is built on. Free and it composes;
  worth a habit for the tooling-refinement class, not a requirement.
- **Any UI surface** — e2 changes CI and merge mechanics; no portal surface. Recorded
  explicitly per the TODO-44 lesson.
- **D3 / PHI column encryption** — the real compliance gap. e2 covers what documentation
  carries, not what the database stores.

## 7. What changed from the first draft

Four defects, three found by the owner's review, one by measurement:

1. **D-2 was unworkable.** It specified a repo-wide SSN rule on the existing `secret-scan` job
   and claimed "fires nowhere else in the tree, false positives: 0". That was measured over
   `docs/`, `adr/` and root `*.md` only. Across tracked files it fires on 17, including 256
   hits in the byte-pinned `db/seed/seed.sql`. Corrected to D-2′ (documentation surface only),
   which also sharpened §3.4's distinction between managed and unmanaged PHI.
2. **E2-REQ-2 and E2-REQ-3 were under-scoped.** Both said "via the fast path". `secret-scan`
   runs on every PR over the whole tracked tree, so the requirement was narrower than the
   implementation — and as written, a fast-path-only PHI check would satisfy REQ-3 while
   leaving code PRs unscanned. Now "every change landing on `main`".
3. **E2-REQ-4 contradicted E2-REQ-12.** "A code PR's pipeline must be byte-identical" is false
   by design once `frontend-boot` becomes required: code PRs then block on a check they
   previously did not. Restated as E2-REQ-4′, verified-no-less.
4. **The document was organized around the wrong primary.** Speed led; thirteen of fourteen
   requirements served the constraints. Re-organized so the enforcement and PHI gaps lead and
   latency is explicitly secondary — and, per D-8, separated out entirely.

Also added: §4.3 accepted costs, §4.4 switchover, and the `logs/intake-service.log` precedent.
