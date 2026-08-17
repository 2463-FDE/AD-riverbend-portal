# Riverbend Patient Portal — Operations Runbook

Practical "how do I run / fix this" notes for whoever is on call. Stack is Docker
Compose; one stack per clinic region.

## Start / stop

```bash
make up        # docker compose up -d (Postgres seeds on first boot via initdb)
make down      # stop the stack
make logs      # tail all logs
make ps        # service status (docker compose ps)
```

Endpoints once up:
- Portal (Next.js): http://localhost:3070 — the only frontend
- Gateway + OpenAPI docs: http://localhost:8070/docs
- Domain services (8071–8076) have **no host ports** (ADR 0016) — check health
  with `make ps` or from inside the network (see Health checks below).

## First-boot data

On a fresh volume Postgres runs `db/schema.sql` then `db/seed/seed.sql`
automatically (mounted into `/docker-entrypoint-initdb.d`). To load schema and
demo data into a **freshly created, empty** DB:

```bash
make seed
```

⚠️ **Not an upgrade command, and not a reload.** `db/seed/seed.sql` carries no
`ON CONFLICT` anywhere, so against a database that already holds the demo data
the inserts that name their ids (`users`, `patients`, `encounters`, `records`,
`slots`) error and are skipped, while **every table whose ids are serial gets a
second copy** — measured 2026-08-13: `consents` 403→806, `insurance_coverages`
255→510, `appointments` 209→418, `roi_requests` 16→32, `audit_logs` 22→44,
`disclosures` 8→16. The result is a half-duplicated corpus, which is worse than
either outcome on its own: the new coverage and consent rows point at the
original patients. To start over:

```bash
docker compose down -v    # -v removes pgdata, compose's only named volume
make up                   # fresh volume → schema + seed run automatically
```

To regenerate the seed file (deterministic; writes a temp file and renames on
success, so a failed generator run never truncates the live seed):

```bash
make seed-gen
```

## Upgrading a database that predates a migration

`make migrate` is the single upgrade command. It runs the migration runner
(`db/migrate.py`) against the running stack's database, applying every
`db/migrations/*.sql` the database has not already recorded — in filename order,
each in its own transaction — and recording each in a `schema_migrations` ledger
so an applied migration is never re-run:

```bash
make migrate
```

A database initialized from `db/schema.sql` (a normal `make up` volume) is born
with the ledger pre-stamped for every migration the flattened schema already
contains, so `make migrate` reports "nothing to apply" there. It earns its keep
on a `pgdata` volume created *before* a migration: without it, the first service
that reads the new table catches the error and answers `503` on **every**
request through that path — container still reporting healthy, so it presents as
"the portal is broken", not "the database is behind".

**One-time step for a volume created before the runner existed (no ledger).**
Such a volume has no `schema_migrations` table, and the migration files are bare
DDL, so `make migrate` refuses it rather than blindly re-running `001` and
crashing. Record its already-applied migrations first:

```bash
make migrate ARGS=baseline
```

`baseline` does not take the operator's word that the volume is current: it
builds a throwaway database from the full migration set and compares the live
schema against it structurally (tables, columns, types, nullability, defaults,
PK/FK/UNIQUE constraints; indexes excluded). Only on a match does it stamp the
ledger and run nothing. On a **mismatch it refuses and stamps nothing** — a
volume that is *behind* head (missing a later migration's table or column) would
otherwise be recorded as current, and the runner would then skip the very
repairs it needs. A refused behind-head volume must be brought to head by hand
(apply the missing `db/migrations/00N_*.sql` files, reading each first) before
`baseline` will accept it. This one-time legacy step is the accepted residual of
the migration-runner work (`docs/debt-log.md`, "No migration runner").

## Demo accounts

All seeded users share password `portal123`, role `staff`. Examples:
`frontdesk`, `rdelgado`, `drnguyen`, `roiclerk`, `mokonkwo`.
(Full list: `db/seed/generate_seed.py`.)

## Health checks

```bash
make ps                               # healthcheck status for every container
curl -s localhost:8070/healthz        # gateway (published)
```

Domain services are network-internal since ADR 0016: curling their old 807x
ports from the host gets **connection refused on a healthy stack** — that is
the topology working, not six dead services. Do not "fix" it by republishing
ports in an override. Probe from inside the network instead (the service images
ship no curl, so use python):

```bash
for s in intake-service:8071 eligibility-service:8072 records-service:8073 \
         scheduling-service:8074 interop-service:8075 roi-service:8076; do
  docker compose exec -T gateway python -c \
    "import urllib.request; print(urllib.request.urlopen('http://$s/healthz').read().decode())"
done
```

The Next.js portal has a compose `healthcheck` (added by `e1`, ADR 0018) polling
its own `/healthz` route: `make ps` shows it `starting` during boot, then
`healthy`, and flips `unhealthy` if the app stops serving while the container
keeps running. `curl -s localhost:3070/healthz` → `{"status":"ok"}` when serving.

A service that won't become healthy is almost always (a) Postgres not ready yet
or (b) bad DB creds in `.env`. Check `make logs`.

## Common incidents

### "Registration spins for 4–5 seconds" (RIV-088)
Intake verifies eligibility **inline** on the request thread, so a slow payer is
still felt at the front desk. **Corrected 2026-08-08:** the call is no longer
unbounded — ADR 0010 put an 8s `ELIGIBILITY_TIMEOUT_SECONDS` on intake's call to
eligibility-service and a 1s connect / 2s read timeout on the payer call itself
(`services/intake-service/config.py`, `services/eligibility-service/config.py`).
Worst case is now bounded seconds, not indefinite. Still not an ops fix target:
the inline placement is architectural (see ARCHITECTURE §7, D4).

### "Whole intake screen froze ~20 min" (RIV-141)
The payer/clearinghouse was degraded. **Corrected 2026-08-08 — the mechanism
described here was fixed by ADR 0010 (Accepted 2026-07-23) and this section had
not caught up.** A payer outage no longer stalls intake: the payer call is
timeout-bounded, eligibility-service opens its own breaker after
`PAYER_BREAKER_FAIL_THRESHOLD` (5) failures, and intake opens a second one after
`ELIGIBILITY_BREAKER_FAIL_THRESHOLD` (3), returning `{"active": null, "status":
"unknown"}` rather than holding the request. The two budgets are pinned to each
other and the pinning is test-enforced
(`tests/test_eligibility_budget_alignment.py`) — **do not retune one value alone.**
What remains open is the async decoupling half of D4: verification is still on the
request path, just bounded. If intake genuinely stalls now, that is a new
incident, not this one.

### "Two confirmations / two people for one slot" (RIV-175)
Double-booking from the check-then-insert race (no UNIQUE on `appointments.slot_id`,
no idempotency). To find duplicates:

```sql
SELECT slot_id, count(*) FROM appointments
WHERE status='confirmed' GROUP BY slot_id HAVING count(*) > 1;
```

Resolve manually (cancel the later row) until the booking path is fixed.

### "Allergy list differs between charts for the same patient" (RIV-160)
Duplicate-patient problem: self-service intake created multiple charts for one
person, and inbound HL7 AL1/RXA segments are dropped by the parser. Since W2,
intake evaluates the ADR 0005 tier-1 match key and *flags* candidate pairs — it
still merges nothing, so charts stay split until someone merges them by hand.

Find the pairs in the portal's **Duplicate Review** queue (front-desk role, or
`GET /review-queue`). If the charts predate the match key, run the retroactive
pass below first. Reconcile charts manually; do not assume one chart is
complete. A clinician opening a flagged chart sees a disclosure banner saying so.

### Retroactive duplicate-match pass
Populates the review queue from patient rows that were created before the match
key existed (ADR 0005 decision 4). Read-only over `patients`: it SELECTs and
INSERTs queue rows, and never creates, modifies, or deletes a patient row.
Safe to re-run — the queue's ordered-pair UNIQUE constraint absorbs repeats, and
a pair someone already dispositioned is never re-queued.

```bash
docker compose exec intake-service python retro_match.py
```

Read the whole summary, not just the pair count:

- `rows with no usable ssn` — the match key could not be applied to these at
  all (tier 2 is deferred). They are unchecked, not clean.
- `recorded match-evaluation failures` — patients whose match check failed while
  they were being registered. Registration completed anyway, by design; this
  pass is what picks them up. `re-evaluated by this pass` is how many the run
  just covered, and `still unevaluated` is how many it could not (no usable SSN,
  or the row is gone). A non-zero `still unevaluated` is worth chasing.

This block is the only operator-facing view of `match_evaluation_failures`.
Then work the queue in the portal; **dispositioning is not merging** — the merge
itself is a Health Information Management procedure.

### Redis: "refusing to start an unauthenticated Redis" / gateway login 500s
Redis now requires a password and is no longer published on the host
(`docs/debt-log.md` D3b). The credential lives in `.env.redis` (gitignored,
loaded by the redis and gateway containers only); `make up` generates a random
one on first run.

```bash
# the container refuses to boot with an empty REDIS_PASSWORD — check the file
grep REDIS_PASSWORD .env.redis
# regenerate it (drops every session: everyone is logged out)
rm .env.redis && make down && make up
# redis-cli is now inside the network, and needs the password
docker compose exec redis sh -c 'redis-cli -a "$REDIS_PASSWORD" ping'
```

A gateway that logs `REDIS_PASSWORD is unset or a placeholder` is refusing to
put sessions and visit memory on an open store — that is the guard working, not
a Redis outage. Fix the credential; do not work around it by pointing
`REDIS_URL` at an unauthenticated instance.

### Rotating the registration content-binding key
`REGISTRATION_FINGERPRINT_KEY` keys the HMAC that lets intake tell an identical
registration retry from a corrected one (`e5b`). It lives in `.env.registration`
(gitignored, loaded by intake-service only); `make up` generates a random one on
first run, and intake fails closed — `GET /healthz` and `POST /intake` both 503,
naming the variable, never a value — if it is missing or not a real secret.

```bash
# check the key is present and real (>= 32 chars, not a placeholder)
grep REGISTRATION_FINGERPRINT_KEY .env.registration
# rotate it (see the bounded, visible cost below)
rm .env.registration && make down && make up
```

**Rotation invalidates every recorded fingerprint** — that is accepted and
bounded, not a fault to avoid. A registration submitted *before* the rotation
and retried *after* it will have its content re-fingerprinted under the new key,
which cannot match the stored one, so the retry answers **409** (the constant
"content does not match the original submission" message, surfaced at the desk as
a system-failure) instead of replaying. The window is only submissions
straddling the rotation; there is no key-versioning machinery by design (`e5b`
accepted residual, `docs/debt-log.md`). Rotate at a quiet time if a
straddling-retry 409 matters.

### Gateway is unhealthy with "session store" in the log
`GET /healthz` sends an authenticated Redis `PING` (each socket operation bounded
by `REDIS_PROBE_TIMEOUT_SECONDS`, default 0.5s), so the container goes red when
the store is unusable rather than only when the process has died. The verdict is
reused for 2s, so a burst of polls costs one PING; every 10s healthcheck still
gets a fresh answer. The log line names the cause — class plus Redis error code:

| log | meaning | fix |
|-----|---------|-----|
| `healthz: session store refused` | no credential configured, or a placeholder | the `.env.redis` steps above |
| `… did not answer: ConnectionError` | Redis is down or unreachable | `docker compose ps redis` |
| `… did not answer: AuthenticationError WRONGPASS` | the gateway's `REDIS_PASSWORD` has drifted from the server's `--requirepass` — both come from `.env.redis`, so check both containers loaded the same file | re-generate: `rm .env.redis && make down && make up` (logs everyone out) |
| `… did not answer: ResponseError ERR` | usually `Client sent AUTH, but no password is set` — **the store this gateway points at is running without `--requirepass`**. Sessions and visit memory would be readable by anything that can reach it | fix `REDIS_URL`/the store, do not disable the guard |
| `… did not answer: ResponseError OOM` / `MISCONF` | Redis is up but rejecting writes (`maxmemory` reached, or persistence failing) | `redis-cli info memory`, `… info persistence` |

The check recovers on the next poll (10s) once Redis answers; nothing drains or
restarts on this signal, so a red gateway during a Redis blip is the status
being accurate, not an incident of its own.

### Chat replies with `"visit_memory": "stale"` or `"unavailable"`
The turn was answered but its visit record could not be written; the gateway logs
`visit memory write failed; answering with memory=…`. Cause is a Redis write
fault — check the store as above (`OOM`/`MISCONF` are the usual ones).

- `stale` — a later turn. The visit still exists and `visit_id` is still returned;
  only that turn is missing from the transcript. The conversation continues.
- `unavailable` — the first turn. Nothing was stored, so no `visit_id` comes back
  and the clerk's next message opens a fresh visit.

No data recovery is possible or needed: visit memory is a 30-minute sliding
cache, never a system of record.

### DB connection errors after a restart
Postgres healthcheck gates the app services, but if you `down -v` you wipe the
volume and lose data; next `up` re-seeds from scratch.

## Backups (current state)

There is **no automated backup/restore job** configured. For ad-hoc:

```bash
docker compose exec -T postgres pg_dump -U riverbend_app riverbend > backup.sql
```

This is a known gap (HIPAA contingency / data-backup plan) — flagged for the
next team.

## Logs & PHI warning

`logs/intake-service.log` currently contains full request bodies **including
PHI** (name/DOB/SSN). Treat the logs directory as sensitive; do not copy it off
the host. Removing PHI from logs is an open remediation item.

## CI

`.github/workflows/ci.yml`: frontend build + JS gates (`typecheck`, `lint`,
`npm test`) and a `frontend-boot` job that runs the production image and polls
`/healthz` (ADR 0018, `e1`), per-service import smoke, unit tests
(`pytest -m "not integration"`), the RIV-160 retrieval-eval drift gate (`eval`),
and a `secret-scan` job, then `docker compose build`. `docker-build` is the
terminal fan-in job and `needs` all of them, so neither a boot-broken frontend
image nor a committed secret can show green there.

**Corrected 2026-08-08:** this section claimed there was no secret scan. There has
been one since PR #2 (`8858097`) — a pinned gitleaks `v8.18.4` job scanning the
tracked tree with `--no-git`, the recurrence guard for D9. It does **not** scan
git history, where the original exposure lives; that scan is step 4 of the
`docs/debt-log.md` remediation runbook and is only meaningful after the history
rewrite. Still genuinely absent: dependency-vuln scanning and image scanning.
