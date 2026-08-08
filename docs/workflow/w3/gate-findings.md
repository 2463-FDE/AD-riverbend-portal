# w3 gate findings

> Round log for the drift gate (see `.claude/skills/drift-gate/`). Gate sessions append
> rounds; the stage-3 revision session fills dispositions. Plan status lives in plan.md.

## Round 1 — 2026-08-07

2 findings, no stamp.

| # | SPEC | Finding | Disposition (stage 3) |
|---|------|---------|-----------------------|
| 1 | W3-SPEC-20 | Backfill finding 6 asserts "D14 has no definition anywhere (sole mention docs/todo.md:67)" — false: `docs/specs-deprecated/w8.md:7` defines D14 (fake de-identification; also `:20`, `:48`, `w10.md:46`), so the noncode PR's "resolve or correct the D14 reference" framing rests on a wrong premise | Confirmed in-repo 2026-08-07 (grep: w8.md:7,20,48; w10.md:46; still no debt-log rows for D13/D14). Rewrote finding 6: D14 defined in deprecated spec archive; noncode PR now files D13 *and* D14 debt-log rows sourcing the archive definition, dropping the resolve-or-correct/owner-input framing |
| 2 | W3-SPEC-21 | Plan cites the roles.yaml↔authz.py parity pin as `tests/test_gateway_authz.py:95`; the parity test is `test_roles_yaml_matches_enforced_map` at `:66` (line 95 sits inside the unrelated default-role test) | Confirmed (test list read 2026-08-07: parity test at `:66`; `:95` is inside `test_default_role_matches_schema_default`). Decision bullet now cites `tests/test_gateway_authz.py::test_roles_yaml_matches_enforced_map` at `:66` |

## Round 2 — 2026-08-07

Clean — stamped.
