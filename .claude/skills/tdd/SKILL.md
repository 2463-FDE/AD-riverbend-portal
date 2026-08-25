---
name: tdd
description: Test-first inner loop for the implement stage (docs/workflow/README.md). One EARS clause → one failing test → minimal code to green. Use when implementing a planned slice, when the user says "tdd", "test-first", "red-green", or when invoked by the implementation skill. Python services only.
---

# TDD loop

The discipline for writing code during workflow stage 4. The outer pipeline (entry gates,
suite runs, PR) is `.claude/skills/implementation/`; this skill owns only the loop.

**Scope: where a test runner exists.** Today that is the Python services (pytest). The
frontend has no harness until e1 lands (TODO-45, ADR 0018); after that, its Vitest suite
is in scope too. Never invent a runner mid-implementation — if the plan names no way to
test a slice, that is a stage-3 gap, not an invitation.

## Two modes — pick before writing anything

1. **New code (in a planned slice): red → green.** Write a failing test first, then the
   minimal code that passes it.
2. **Inherited code you must touch: characterization first.** Capture current behaviour
   under test, then change under green (`docs/landmines.md` §3). Never start with a
   "failing test for what it *should* do" against inherited behaviour — in this repo a
   red test against existing code is usually pointing at a **planted teaching defect**.
   Check `docs/debt-log.md` and the `docs/phi-logging-policy.md` register before treating
   any inherited behaviour as a bug; if it is registered, it stays. Making that test green
   destroys the exercise.

## The loop

One cycle = one vertical slice = one EARS clause from the plan's scope map.

1. Take the next SPEC id from the item's `## Plan` section
   (`docs/workflow/plans/<item>.md`, or the ticket file
   `docs/workflow/plans/<item>/<ticket>.md`), in plan order.
2. Write **one** failing test at the seam the plan names for it. The test takes the name
   the spec's `test:` cell planned (it carries the clause id:
   `test_w4_spec_3_booking_rejects_taken_slot`). Run it; watch it fail for the expected
   reason (assertion, not import error).
3. Write the minimal code to pass. Run the same test file, not the world.
4. Repeat. No refactoring inside the cycle — refactor under green at review, as its own
   commit.

Do not write all the tests up front (horizontal slicing): later slices are shaped by what
earlier ones teach.

## Where tests go

At seams the **plan** pre-agreed (stage 3) — public boundaries where behaviour is
observable without reaching into internals. `docs/onboarding-seam-map.md` names the six
safe extension points and the eight walls; a test that requires opening a wall is a plan
problem, not a testing problem — take it back to stage 3.

## Anti-patterns

- **Implementation-coupled** — asserts on private helpers or internal call structure;
  breaks on refactor with behaviour unchanged.
- **Tautological** — expected value computed the same way the code computes it; passes by
  construction.
- **Horizontal slicing** — full test file before any implementation; commits to imagined
  behaviour.

## Repo mechanics (each of these has burned someone)

- No shared package: load the module-under-test by file path via
  `tests/conftest.py::load_module`. Bare sibling names (`config`, `db`) collide across
  services — pin `sys.modules` before loading when the module imports siblings.
- Copy-pasted modules (per ADR 0001 layout) get a **parity test** — exemplar
  `tests/test_redaction.py`.
- Runner: `.venv/bin/python -m pytest tests/test_<x>.py -q` per cycle; bare `pytest` and
  `make test` fail on this machine (local Python is 3.8, suite needs 3.12). Full-suite
  and baseline rules live in the implementation skill.
- PHI, authz, or sanitization path → the negative-test rule applies: at least one
  adversarial test, and an end-to-end scan test for anything that logs a payload.
  `docs/landmines.md` §3 owns the rule and the worked example — read it there.
- Deliberate coverage gaps (the pinned xfails, deselected integration tests) stay
  visible. A gap that moved is a finding to report, not a number to update.
