#!/usr/bin/env bash
# Behavior tests for .gitleaks.toml — the successor to the retired
# .claude/hooks/test/test-phi-secret-guard.sh's behavior-level cases (fake key
# blocked / fake PHI blocked / clean file passes / fake-data trees allowlisted
# for PHI shapes but NOT for credentials). Cases that asserted the retired
# hook's internals (matcher shapes, deny JSON, escape env vars) were dropped
# with the hook (archive/pipe1-hooks-r5).
#
# Not wired into CI (needs docker-in-docker there); run by hand when the
# config changes:  bash tests/tooling/test-gitleaks-config.sh
# CI enforces the config itself via the secret-scan job.
#
# Secret-shaped values are built by concatenation so this file never trips the
# very scan it tests.

set -u

repo_root=$(cd "$(dirname "$0")/../.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

run_gitleaks() { # <dir> -> exit 0 clean, 1 leaks found
  if command -v gitleaks >/dev/null 2>&1; then
    gitleaks detect --no-git --source "$1" --config "$repo_root/.gitleaks.toml" \
      --redact >/dev/null 2>&1
  else
    # docker exits 125/126/127 for its own failures (observed: a transient
    # remount error on a just-recreated dir) — that is infra, not a gitleaks
    # verdict. One retry so it never reads as a config FAIL.
    local rc=0
    docker run --rm -v "$1:/scan" -v "$repo_root/.gitleaks.toml:/cfg.toml" \
      zricethezav/gitleaks:v8.18.4 \
      detect --no-git --source /scan --config /cfg.toml --redact >/dev/null 2>&1 || rc=$?
    if [ "$rc" -ge 125 ]; then
      sleep 1
      rc=0
      docker run --rm -v "$1:/scan" -v "$repo_root/.gitleaks.toml:/cfg.toml" \
        zricethezav/gitleaks:v8.18.4 \
        detect --no-git --source /scan --config /cfg.toml --redact >/dev/null 2>&1 || rc=$?
    fi
    return "$rc"
  fi
}

pass=0 fail=0
check() { # <name> <expected-exit> <file-relpath> <content>
  rm -rf "$tmp/case"
  mkdir -p "$tmp/case/$(dirname "$3")"
  printf '%s\n' "$4" > "$tmp/case/$3"
  local rc=0
  run_gitleaks "$tmp/case" || rc=$?
  if [ "$rc" = "$2" ]; then
    pass=$((pass + 1)); echo "ok   $1"
  else
    fail=$((fail + 1)); echo "FAIL $1 (expected exit $2, got $rc)"
  fi
}

AWS_KEY="AKIA""IOSFODNN7EXAMPLE"
# Not 123-45-6789 / 000-00-0000 — those are the config's allowlisted placeholders.
SSN="218-53""-1027"
# Secret-shaped values assembled at runtime — each half is under the rule's
# 20-char floor, so this script's own source never matches the rules it tests.
FAKE_PW="hunter2hunter2""hunter2X"
FAKE_ENV="abcdefghijkl""mnopqrstuvwx"
# One of the config's enumerated (anchored) fake-fixture values.
BLESSED="test-internal""-secret"
# PHI-shaped literals, split so this file's own lines never match riverbend-mrn
# / riverbend-dob (those rules allowlist tests/, but the claim above should be
# true without leaning on it).
MRN="M12""34"
DOB="1987-03""-14"

check "clean file passes"                          0 services/app.py 'def handler(): return {"ok": True}'
check "fake AWS key blocked"                       1 services/config.py "key = \"$AWS_KEY\""
check "fake AWS key blocked even in tests/"        1 tests/test_x.py  "key = \"$AWS_KEY\""
check "fake AWS key blocked even in db/seed/"      1 db/seed/x.sql    "-- $AWS_KEY"
check "SSN shape blocked outside fake-data trees"  1 services/models.py "ssn_example = \"$SSN\""
check "SSN shape allowed in tests/"                0 tests/test_intake.py "fake_ssn = \"$SSN\""
check "SSN shape allowed in db/seed/"              0 db/seed/seed.sql "INSERT INTO patients (ssn) VALUES ('$SSN');"
check "MRN assignment blocked outside fake-data trees" 1 services/models.py "mrn = \"$MRN\""
check "MRN assignment allowed in db/seed/"         0 db/seed/gen.py   "mrn = \"$MRN\""
check "DOB assignment blocked outside fake-data trees" 1 services/schemas.py "dob = \"$DOB\""
check "DOB assignment allowed in tests/"           0 tests/test_records.py "dob = \"$DOB\""
check "quoted secret-like assignment blocked"      1 services/config.py "password = \"$FAKE_PW\""
check "env-style secret assignment blocked"        1 config/app.env    "API_KEY=$FAKE_ENV"
# PR #37 r1: the secret-assignment rules carry NO path allowlist — a real
# low-entropy credential in a test helper or seed file must fail CI. Known
# fake fixtures are exempted by exact anchored value instead.
check "secret-like assignment blocked in tests/ too"   1 tests/conftest.py "password = \"$FAKE_PW\""
check "secret-like assignment blocked in db/seed/ too" 1 db/seed/gen.py    "password = \"$FAKE_PW\""
check "enumerated fake fixture value allowed"          0 tests/test_ai.py  "TEST_INTERNAL_SECRET = \"$BLESSED\""
check "anchoring: superstring of fake value blocked"   1 tests/helper.py   "password = \"$BLESSED-PROD-a8f3\""
check "identifier assignment to *_token allowed"   0 services/gw.py    'flight_token = ai_singleflight_acquire(cache_key, ttl)'
check "placeholder SSN 000-00-0000 allowed"        0 services/doc.py   '# placeholders like 000-00-0000 fail this check'
check "canonical example SSN allowed"              0 frontend/page.tsx '// a pasted "123-45-6789" would be truncated'

echo "----"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
