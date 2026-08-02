# ADR 0016 — Domain services leave the Docker host: unpublish 8071–8076, allowlist what may publish

**Status:** Accepted
**Date:** 2026-08-02
**Author:** Riverbend engagement team
**Debt:** D15 (new entry, this change) — surfaced by Codex PR #26 rounds 3–4

## Context

Codex review round 3 on PR #26 reported `GET /schedule?date=…` — a clinic day of
appointments with patient names and MRNs — answering **unauthenticated on host port
8074**, and round 4 restated it as a no-ship. The finding is true but is not that
route's bug, and not that service's bug: `docker-compose.yml` published host ports
for all six domain services (8071–8076), and **no domain service has any auth
dependency** — each route carries `Depends(get_db)` and nothing else. The gateway's
`require_session` is the only place a session is checked (CLAUDE.md §1: "The portal
**never** calls a domain service directly — everything goes through the gateway,
which owns login + session validation"), so every published port was a path around
the only auth boundary the system has:

- `records-service:8073` — full charts including clinical notes, plus the unscoped
  `GET /records/search?q=`;
- `roi-service:8076` — release-of-information fulfillment;
- `interop-service:8075` — `POST /hl7/ingest`, an unauthenticated PHI **write**;
- `intake-service:8071`, `eligibility-service:8072`, `scheduling-service:8074` —
  registration PHI, coverage checks, the day queue.

The class was undocumented: `docs/debt-log.md` had D3b for Redis only; CLAUDE.md §6
never named it. Precedent existed twice — ai-assistant went `expose`-only in PR #7
round 3, Redis lost its publish in PR #14 round 1 (ADR 0011) — and
`tests/test_compose_topology.py` said out loud that the neighbors' published ports
were "pre-existing dev topology; do not copy that pattern."

## Decision

### 1. Unpublish all six domain services

`docker-compose.yml` drops `ports:` for intake, eligibility, records, scheduling,
interop and roi, replacing each with `expose:` on the same container port. `expose`
is documentation in Compose v2 — same-network services reach each other regardless —
so it pins intent and the URL agreement, not reachability. Nothing else moves: the
gateway reaches every service by compose DNS (`http://<service>:<port>`), container
healthchecks probe `localhost` inside the container, and the gateway keeps 8070.

### 2. Publishing is a closed allowlist, not a default

The sanctioned host surface is exactly `postgres`, `gateway`, `frontend`, `portal`.
`tests/test_compose_topology.py::test_host_publishing_is_a_closed_allowlist`
asserts every other service — including any **future** one — has no `ports` key.
Adding a published service now requires editing the allowlist in the same change,
which makes publishing a reviewed decision rather than a copied default. This is
the fix-the-class shape: the six current instances are also asserted individually,
but the allowlist is what stops instance seven.

### 3. Invariants the tests hold

- No domain service has a `ports` key (per-service + allowlist, above).
- Each domain service `expose`s the port the gateway's `*_URL` env var points at —
  the unpublish must not strand the sanctioned path.
- Every `http://<service>:<port>` env value anywhere in the compose file agrees
  with the target service's declared port (intake and ai-assistant carry their own
  `ELIGIBILITY_URL`), so a future port move cannot silently strand a caller.

These also satisfy round 4's ask for a direct-access rejection test, structurally:
no host mapping exists to answer.

### 4. The dev valve is a local override, not a republished port

Host-side debugging that genuinely needs a domain service directly uses
`docker compose exec gateway curl http://<service>:<port>/...`, or a **gitignored**
`docker-compose.override.yml` republishing a port on that machine only. The
topology tests assert on `docker-compose.yml` alone, so a local override does not
trip them — and does not ship. Per-service Swagger (`/docs`) moves behind the same
valve; the gateway's own `/docs` on 8070 stays.

### 5. HL7 ingress, when a real feed exists

Nothing on this machine posts to 8075 today — no script, doc, or test. When a real
hospital ADT/ORU feed is connected, it gets **dedicated authenticated ingress**
(mutual TLS or an authenticated MLLP/HTTP listener, decided then in its own ADR),
not a naked container port. Re-publishing 8075 as-is would restore an
unauthenticated PHI write path and is out.

### 6. Postgres stays published — for now

5432 remains on the host for local `psql`/tooling. Unlike the domain services it
authenticates (password), so it is not in the same unauthenticated-path class, but
it does hold plaintext PHI (D3) behind a default-`changeme` credential in
`.env.example`. Deliberately out of scope here: this ADR closes the
*unauthenticated* class; tightening Postgres exposure is registered as residual in
D15 rather than silently bundled.

## Alternatives considered

- **Add auth to each domain service** — rejected: duplicates the gateway's job
  across six services, contradicts the BFF topology (CLAUDE.md §1), and is W9-scale
  auth work; the topology fix removes the exposure without touching auth behavior
  (§6 approval-gated).
- **Keep ports published, bind to 127.0.0.1** (`"127.0.0.1:8071:8071"`) — rejected:
  still an unauthenticated PHI path for every process on the host (the D3b Redis
  rationale verbatim), and keeps the copy-me default alive.
- **Keep 8075 published for HL7 demos** — rejected, §5: nothing uses it today and
  the valve (§4) covers demos; an unauthenticated PHI write is the worst port of
  the six to keep.
- **Internal shared-secret headers per service** (the ai-assistant `X-Internal-Auth`
  pattern) — not taken here: that secret exists as defense-in-depth *behind* an
  unpublished port on a paid-capacity path, not a substitute for unpublishing. May
  still arrive later as depth; orthogonal to this decision.

## How this serves the client and domain

Riverbend gets the single-auth-boundary story restored in fact, not just in
architecture docs: the only way to PHI is through the gateway session check —
demonstrable to the client as "before: `curl localhost:8074/schedule` dumps a day
of names and MRNs; after: connection refused." Front-desk, clinician and ROI
workflows see no change; the portals and gateway are untouched.

## Accepted tradeoffs / deferred gaps

1. **Host-network processes are the threat model, not the LAN.** Compose port
   publishing binds `0.0.0.0` by default, so the pre-change exposure was any host
   *or LAN* caller; post-change, domain services are reachable only from
   containers on the compose network. A compromised container still reaches every
   domain service unauthenticated — that is D8/W9 (service-to-service auth)
   territory, priced and open.
2. **Postgres remains published with plaintext PHI** (§6). Registered in D15's
   residual; closes when local tooling moves to `docker compose exec psql` or the
   credential posture is hardened.
3. **The dev valve is unguarded by design** (§4): a developer *can* republish a
   port locally. The gitignore keeps it off main; the allowlist test keeps it out
   of the shipped topology. Residual is a developer machine exposing PHI-shaped
   seed data — acceptable on seeded demo data, revisit if real PHI ever lands in
   a dev database.

## Consequences

- `docker-compose.yml`: six `ports:` → `expose:`; comments name the class and the
  guard. The stale "do not copy that pattern" comment on ai-assistant is updated —
  the pattern it warned against no longer exists.
- `tests/test_compose_topology.py` gains the domain-service section (four tests,
  §3). Failures there are regressions of this decision.
- Host-side `curl localhost:807[1-6]` and per-service Swagger stop working; the §4
  valve replaces them. Measured before landing: zero references to
  `localhost:807[1-6]` in `Makefile`, `docs/`, `scripts/`, `eval/`, tests, or
  handover material — nothing breaks.
- CI unchanged: integration tests target `GATEWAY_URL=localhost:8070` only.
- `docs/debt-log.md` gains **D15** (the class, what closed it, the residuals);
  CLAUDE.md §6's IDOR bullet gains the topology note.
- A fresh `make up` seeds this topology by default — the fail-closed state is the
  shipped state.
