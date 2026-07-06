<!--
  Riverbend PR. Narrative-driven (house style) — see CONTRIBUTING.md.
  Title: type(scope): <RIV-### | W#-F#> short description
  Delete sections that don't apply. Keep it scoped.
-->

## Overview
<!-- What this PR does and the problem it solves, in a few sentences.
     If it adds/changes endpoints, include the table: -->

| Method | Path | Returns |
|--------|------|---------|
|        |      |         |

Refs: <!-- RIV-088 / W#-F# / none -->

## Behavior
<!-- Bold subheaders for each notable behavior or decision. e.g.:
**Time-bounded eligibility**: the 270/271 call now has a 3s timeout and degrades
to "eligibility unavailable" instead of blocking Save.
**No schema change**: read-path only. -->

## Wiring
<!-- Gateway routing, compose/env, frontend proxy, or composition changes. Omit if none. -->

## Risk & landmines
<!-- REQUIRED for a HIPAA production repo. State which CLAUDE.md §6 landmines this
     touches — auth/sessions, PHI columns, ROI/disclosures, migrations, secrets/.env,
     inline eligibility, booking race, HL7 mapping — or state "none touched".
     If any: explain the blast radius and request human sign-off here.
     Confirm no PHI added to logs/error bodies/fixtures. If schema changed, confirm
     both db/schema.sql and a new db/migrations/00N_*.sql were updated. -->

## Verification
<!-- Bold-prefixed, like: **make test**: 24 passed. **Live gateway round-trip**: login →
     /patients/1042/records returns chart. State anything skipped, don't hide failures. -->

## Impact
<!-- Closing line: what this unblocks or the follow-ups it leaves open. -->
