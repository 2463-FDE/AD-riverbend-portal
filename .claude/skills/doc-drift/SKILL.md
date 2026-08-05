---
name: doc-drift
description: Week-boundary drift sweep - spawn one read-only Haiku reader per doc family (ADRs, specs, debt-log, CLAUDE.md §9, local tooling docs) to find doc claims contradicted by current code, and print a consolidated report. Report only, never edits. Use at a curriculum-week boundary alongside memory-lint, or when a doc claim looks stale.
---

# Doc-drift sweep

`memory-lint` catches structural rot mechanically; it cannot judge whether an ADR claim
still holds. This skill is the judgment half: one reader per doc family, each checking a
named set of docs against the current code and reporting contradictions.

**Contract — read before running anything:**

- **This skill NEVER edits a doc.** Output is a consolidated drift report to stdout;
  the human reads it and decides. If a finding is obviously right, it still goes in the
  report, not into an edit.
- **Readers run sequentially, one at a time — never in parallel.** CLAUDE.md §10.2 caps
  delegation at one subagent per step; this skill's instruction is the authorization for
  each reader (same doctrine as verify-stack §6's adversarial review). Wait for each
  reader to return before spawning the next.
- **Readers are read-only and Haiku-tier.** Spawn with the `Explore` agent type and
  `model: "haiku"` — the tiering lives in the Agent call, not in the prompt prose.
- **`logs/` is out of scope for every reader.** Historical PHI. No family includes it,
  and no reader prompt may point one there.
- A run can cover any subset of families. The full 5-family sweep is the week-boundary
  ritual; a single family is fine when one doc is in doubt.

## Finding format

Every reader returns findings exactly as:

```
doc:line — claim — contradicting evidence file:line
```

or the literal string `no findings`. No summaries, no praise, no improvement suggestions.
The main thread concatenates the per-family results into one report, grouped by family,
and prints it. That report is the whole deliverable.

## The five families

Spawn each reader with the template below, substituting the family block. Every prompt
must (a) name the exact files in scope, (b) forbid repo-wide wandering, (c) state the
finding format above.

**Prompt template:**

> Read-only drift check. Scope: ONLY the files named below plus the specific code files
> needed to verify a claim — do not wander the repo, do not read `logs/`.
> If the doc text is pasted into this prompt, do NOT re-read it from disk, and open
> ONLY the code files it cites — a tool call on any other file is out of scope.
> For each checked doc, verify claims of *current state* against the code and report
> each contradiction as `doc:line — claim — contradicting evidence file:line`.
> Return only the findings list, or `no findings`.
> [family block]

**Single-file families (3 and 4) are paste-in:** the main thread pastes the target
doc's full text — with line numbers (`cat -n`), so `doc:line` findings stay exact —
into the reader prompt. The reader's tool calls are then only for opening cited code
files. Motivated by the first measured run: 63.4k tokens against a 15–30k target
with the doc read via tools; the transcript is unrecoverable, so the fix is
structural rather than diagnostic (see Token budget).

**Family 1 — ADRs.** Scope: `adr/*.md`. Check Accepted ADRs' claims about current code
(file paths, behavior, enforcement points). ADRs 0012–0015 carry
`Status: Superseded 2026-08-05` — their status header is honest, so skip their content
claims entirely; only an Accepted ADR contradicted by code is drift.

**Family 2 — specs.** Scope: `docs/specs/*.md`. **`w7.md`–`w10.md` describe unbuilt
curriculum work** (their drop commit died with closed PR #26): a spec *ask* with no
implementation is NOT drift. Only a spec's claim about *current state* ("X already does
Y", "the portal currently…") contradicted by code counts.

**Family 3 — debt log.** Scope: `docs/debt-log.md`, pasted into the prompt with
line numbers (single-file family — see paste-in rule above); tool calls only for
the code files entries cite. Check each entry's status line
(open / partly closed / closed-by-PR-N) against the code markers it cites — does the
cited fix exist, does the claimed-open gap still reproduce in the code as described.

**Family 4 — CLAUDE.md §9.** Scope: the §9 "Known debt" section of the repo-root
`CLAUDE.md` (tracked since PR #35, 2026-08-05, reversing PR #32). **Baseline =
`git log -1 --format=%as -- CLAUDE.md`**, falling back to the newest date §9
itself mentions if that file has no history yet on the current branch. The main thread pastes the §9 text verbatim into
the reader prompt (the reader never opens CLAUDE.md itself) and instructs: run
`git log --oneline --since=<baseline date>` in the repo and report any merged change
that contradicts a §9 status row.

**Family 5 — local tooling docs.** Scope: `.claude/skills/*/SKILL.md` and
`.claude/commands/*.md`, their claims about the *environment* (Python versions,
make targets, ports, file locations, tool availability). Verify first-hand before
flagging — e.g. run `python3 --version` before touching any "local Python is 3.8"
line. Negative test, verified 2026-08-05: local python3 was 3.8.8, so verify-stack's
"local Python is 3.8 and cannot run the suite" was a CORRECT claim — a reader that
flags it while 3.8 is still installed is broken. (This family is an addition to the
original four-family spec: the expected first real catch — those verify-stack lines,
once the uv per-project venv upgrade lands — lives here.)

## Token budget

**Not yet a measured band.** The only measurement so far: the family-3 (debt-log)
reader — the *smallest* family — spent **63.4k tokens over 20 tool uses** on its
first run (2026-08-05, before the paste-in tightening above). Treat **~15–30k per
reader as the target, not a measurement**; re-measure at the next week-boundary
sweep and baseline the real band then — leaving a number standing as if measured
is exactly the drift class this skill exists to catch. Same budgeting discipline
as `commands/dashboard.md` §6. A reader that opens files its doc does not cite is
wandering: tighten the fence, do not raise the budget. The full 5-family sweep is
a week-boundary ritual, not a per-session check.
