# To-do register

> Loose ends that are queued but not scheduled. This file is the **source of truth** for the
> to-do lane of the status dashboard (`make status`) — the generator parses it, so keep the
> line format. Requirements belong in `docs/specs/`, debt belongs in `docs/debt-log.md`;
> neither is restated here.

**Line format** — one item per line, pipe-separated:

```
- [ ] TODO-n | statement | key: value | key: value
```

Checkbox: `[ ]` open · `[~]` in progress · `[x]` done. Keys, all optional:

| Key | Meaning |
|---|---|
| `tags` | comma-separated. `live-defect`, `phi`, `compliance`, `process`, `memory`, `hygiene` |
| `blocked_by` | gate (`G0`), requirement (`FE-R3`), or another `TODO-n`. Comma-separated |
| `human_gate` | `yes` = parked awaiting a human decision, not actionable work |
| `src` | where the real detail lives — read that, not this line |

IDs are allocated once and never renumbered. Completed items stay, checked.

## Items

- [ ] TODO-1 | Intake contract break: portal payload 422s at intake-service, gateway relays 200, UI reports success; no patient row created. Fix shape resolved 2026-07-30 — folded into P2, `ConsentKind` widened by two values; the defect stays live on `main` until G2 | tags: live-defect, phi | blocked_by: G2 | src: docs/specs/frontend-rebuild.md §8 #1 and §8.1, docs/debt-log.md
- [ ] TODO-2 | Run ADR 0011's `make up` end-to-end PHI drill: two-turn visit chat, then confirm via redis-cli the stored transcript is metadata-only | tags: phi | src: adr/0011-eligibility-agent-and-visit-memory.md
- [x] TODO-3 | P0.5 design tokens — palette, type scale, density, component states; last artifact before G0 | src: docs/design/05-design-tokens.md (direction F, chosen 2026-07-30 by polled healthcare worker)
- [ ] TODO-4 | Commit or discard the in-flight W4 work left uncommitted on main (`docs/specs/w4.md`, `w4-multiagent.html`, two PDFs) | tags: hygiene
- [ ] TODO-5 | EARS rewrite of `docs/specs/w4.md` §5 into requirement IDs, so `address-review`'s design gate can reference IDs that exist | tags: process | src: docs/specs/_template.md
- [ ] TODO-6 | W3 portal chat UI: addendum inside `w3.md` (§4 deliverable + new §5b EARS block `W3-UI-R…`), not a new spec file and not a retro-rewrite of shipped prose criteria | src: docs/specs/w3.md
- [~] TODO-7 | Frontend test harness — ADR written (0013: Vitest, two projects, real-browser component tests); the harness itself lands in P2 with the contract fixture | blocked_by: G1 | src: adr/0013-frontend-test-harness.md
- [ ] TODO-8 | `CLAUDE.md` §9 still lists RIV-088/RIV-141 as `[~]` with W3 agent work pending, but PR #14 shipped it | tags: process
- [ ] TODO-9 | Capture a real Bedrock response from a live `complete()` / `complete_structured()` call and pin it as a fixture, so the mocks match a shape AWS actually returned | tags: hygiene
- [ ] TODO-10 | Gated live-LLM integration test; needs a real bearer key | blocked_by: TODO-9
- [ ] TODO-11 | Reply to the post-merge PR #2 no-ship (bot's premise was wrong; `output_config.format` is canonical). Reasoning drafted, user said do not post yet | human_gate: yes
- [ ] TODO-12 | `README.md:1,82` assert PHI is encrypted and the system is fully HIPAA compliant; the schema stores plaintext `TEXT`. Client-facing handoff material, so not a unilateral edit | tags: compliance | human_gate: yes | src: docs/debt-log.md
- [ ] TODO-13 | Delete the merged branch `feat/noref-eligibility-agent-visit-memory` (local + remote); content is fully in squash `074c346` | tags: hygiene
- [x] TODO-14 | Memory page `frontend-rebuild-plan` and the memory index both say `FE-R1`–`FE-R20`; the spec runs to `FE-R26` | tags: memory
- [ ] TODO-15 | Four of the five P0.5 review questions came back unanswered — row density (Dense vs Comfortable), identity-strip field order, whether the allergy banner reads urgent without becoming noise, and dark-mode appetite. Density currently defaulted to Dense against a stronger mis-click argument on the ROI queue | human_gate: yes | src: docs/design/05-design-tokens.md §7
- [ ] TODO-16 | `docs/ux-audit-2026-07.md` is cited by ADR 0008 but was never committed (`git log --all` empty, not gitignored). F1–F8 exist only in project memory + the PR bodies that shipped fixes. Either write the doc or drop the claim from memory | tags: hygiene | src: adr/0008-frontend-date-picker-dependency.md
- [x] TODO-17 | **Pre-P2 decision set CLOSED** — #1 on 2026-07-30 (intake fix folded into P2; `ConsentKind` widened by `financial_responsibility_ack` + `communications_opt_in`, carrying the `FE-R22` re-proof); #11–#15 on 2026-07-31: `adapter-node` multi-stage image · **token held BFF-side behind an `httpOnly` cookie + 10-min idle logoff (ADR 0014, `FE-R27`/`FE-R28`)** · `portal/` on 3071 · P2 = login + minimum intake path · `svelte-check` + eslint. Also added `FE-R29` (no patient data in web storage) and reopened decision #16 (patient surface) | tags: process | src: docs/specs/frontend-rebuild.md §8
- [ ] TODO-20 | **Decision #16 — patient-facing surface, reopened 2026-07-31.** Blocked on D11 session→`patient_id` binding (W4, §6 approval, G4), not on frontend work. Then a user call on audience separation and whether it shares the staff origin. `FE-R27`–`R29` already survive it, so it blocks nothing in P2 | tags: process, phi | human_gate: yes | blocked_by: G4 | src: docs/specs/frontend-rebuild.md §8 #16
- [~] TODO-18 | Uncommitted on branch `docs/noref-frontend-test-harness-adr`: ADRs 0013 + 0014, the ADR 0012 §3 amendment, and edits to the spec, `docs/debt-log.md`, `CLAUDE.md` and this file. **TODO-17 closed 2026-07-31, so the hold is discharged and this is now ready to commit and PR.** Tracked-file edits revert on any `git checkout`/`stash`/`reset --hard` until committed; the two new ADRs are untracked and safe | tags: hygiene
- [ ] TODO-19 | Later-phase decisions, parked deliberately: spec §8 #3 role tier (P5/G4), #5 component gallery + #6 unverified small-viewport behaviour (P3), #7 queue read endpoint + #9 who owns the wrong stored appointment instants (P6/G5), #10 E2E (needs its own artifact-retention ADR) | tags: process | src: docs/specs/frontend-rebuild.md §8
