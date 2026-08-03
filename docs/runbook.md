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
- Portal (legacy Next.js): http://localhost:3070
- Portal (SvelteKit rebuild): http://localhost:3071 — no login yet; see `portal/README.md`
- Gateway + OpenAPI docs: http://localhost:8070/docs
- Domain services (8071–8076) have **no host ports** (ADR 0016) — check health
  with `make ps` or from inside the network (see Health checks below).

## First-boot data

On a fresh volume Postgres runs `db/schema.sql` then `db/seed/seed.sql`
automatically (mounted into `/docker-entrypoint-initdb.d`). To reload demo data
into an already-running DB:

```bash
make seed
```

To regenerate the seed file (deterministic):

```bash
python3 db/seed/generate_seed.py > db/seed/seed.sql
```

## Demo accounts

All seeded users share password `portal123`, role `staff`. Examples:
`frontdesk`, `rdelgado`, `drnguyen`, `roiclerk`, `mokonkwo`.
(Full list: `db/seed/generate_seed.py`.)

## Health checks

```bash
make ps                               # healthcheck status for every container
curl -s localhost:8070/healthz        # gateway (published)
curl -s localhost:3071/healthz        # SvelteKit portal (published)
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

The portal's probe reports liveness today. Once the session module lands it also
fails when the cookie encryption key or `ORIGIN` is missing, so `make ps` shows
the service unhealthy instead of up — it never echoes the key or a stack trace.

A service that won't become healthy is almost always (a) Postgres not ready yet
or (b) bad DB creds in `.env`. Check `make logs`.

## Common incidents

### "Registration spins for 4–5 seconds" (RIV-088)
Expected with the current build: intake verifies eligibility **inline** with a
synchronous, no-timeout payer call. Not a fix target for ops — it's an
architectural issue (see ARCHITECTURE §7).

### "Whole intake screen froze ~20 min" (RIV-141)
The payer/clearinghouse was degraded. Because the eligibility call has no
timeout/circuit breaker and sits on the intake request path, a payer outage
stalls intake. Mitigation today: wait for the payer to recover. Real fix:
make eligibility async + add timeout/breaker.

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
person (no match key), and inbound HL7 AL1/RXA segments are dropped by the
parser. Reconcile charts manually; do not assume one chart is complete.

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

`.github/workflows/ci.yml`: frontend build, per-service import smoke, unit tests
(`pytest -m "not integration"`), then `docker compose build`. There is no
secret-scan, dependency-vuln-scan, or image-scan step — another known gap.
