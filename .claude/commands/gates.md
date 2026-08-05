---
description: Show / toggle / update the frontend-rebuild gate track in the statusline
---

Drive the frontend-rebuild gate tracker that feeds this project's statusline. The state file
is `.claude/gates/state.json`; every read and write goes through `.claude/gates/gates.sh` so
the schema stays valid and the ids stay checked. Do not hand-edit the JSON.

`$ARGUMENTS` is passed through verbatim when it already matches a `gates.sh` subcommand.
With no arguments, show the board.

## The one rule

`docs/specs/frontend-rebuild.md` §6 (gates) and §5 (the `FE-R` table) are **authoritative**.
`state.json` is a display cache of position within them. So:

- Never mark a gate `signed` because work looks done. A gate is signed by the **user**, per the
  spec's "Signed by" column — all six say `user`, and G4 says `user, explicitly` because it is
  an auth change under CLAUDE.md §6. If the user has not said so in this session, the gate is
  at most `awaiting`.
- Never mark an `FE-R` `done` on inspection alone. The spec names a verification method per
  requirement (contract test, component test, driven repro, CI job, ADR review). Requirement
  done means **that** method passed and you saw it pass — CLAUDE.md's verification standard:
  first-hand, not inferred, and a 200 proves nothing on its own.
- If a gate or `FE-R` id changes in the spec, update `state.json`'s `gates`/`reqs` to match in
  the same change. Nothing cross-checks them.

## Subcommands

```bash
bash .claude/gates/gates.sh show               # the board: per-gate glyph, state, R counts, open reqs
bash .claude/gates/gates.sh preview            # render the statusline bar as it appears
bash .claude/gates/gates.sh on                 # show the bar   (working the rebuild)
bash .claude/gates/gates.sh off                # hide the bar   (working anything else)
bash .claude/gates/gates.sh gate G2 active     # todo | active | awaiting | signed | blocked
bash .claude/gates/gates.sh req FE-R1,FE-R2 done   # todo | done
```

Gate states mean: `todo` not started · `active` in progress · `awaiting` artifact complete,
user signoff owed · `signed` user signed it off · `blocked` cannot proceed (say why in chat).

## Behaviour

1. **No arguments, or `show`** — run `show`, then render it as a short read: which gate is in
   focus, what it needs to close per the spec's "Verified how" column, and what is open behind
   it. Name the blocking relationship when it bites: G2 blocks every later phase, so an unsigned
   G2 makes G3–G5 work unshippable.
2. **`on` / `off`** — flip it and say so in one line. Nothing else.
3. **A gate or requirement update** — apply it, then `preview` so the change is visible. If the
   update would mark something `signed`/`done` without the evidence the spec requires, say what
   is missing and ask before writing. That check is the point of this command; do not skip it to
   be agreeable.
4. **Anything else in `$ARGUMENTS`** — treat it as a plain-language request ("we finished the
   contract fixture", "G0 is signed"), map it to subcommands, state the mapping, then apply it
   under rule 3.

Statusline changes appear on the next render, not instantly — the bar redraws as the session
continues. Both scripts and the state file live under `.claude/`, which is gitignored here, so
the `SessionEnd` snapshot hook is what preserves them (CLAUDE.md §10.1).
