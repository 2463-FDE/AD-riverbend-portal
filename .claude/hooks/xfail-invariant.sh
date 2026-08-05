#!/usr/bin/env bash
# PreToolUse guard (Bash matcher): blocks `git push` unless the container suite
# comes back on this repo's curriculum invariant — exactly 1 xfailed,
# 5 deselected, 0 failed (verify-stack §1).
#
# Why a hook: the invariant is a §6 landmine tripwire, not a style rule. The
# counted xfail is the IDOR test; an XPASS means someone changed auth behavior,
# and the correct response is to stop and investigate, never to adjust the test.
# Nothing enforced that before this hook — it survived on human memory.
#
# Why it RUNS the suite rather than parsing the last run: measured 13.7s wall
# warm (10.3s pytest + docker overhead). A cached transcript cannot tell you
# whether it reflects the tree being pushed, and a stale green is exactly the
# failure this guard exists to prevent.
#
# Escape hatch: ALLOW_UNVERIFIED_PUSH=1 (same doctrine as the pre-commit guard's
# ALLOW_IGNORE_DELETE=1). Test seam: XFAIL_INVARIANT_OUTPUT=<file> reads pytest
# output from a fixture instead of running the suite.
#
# Never echoes suite output — only the parsed counters — so nothing from a
# failing test body lands in the session transcript.

set -u

EXPECT_XFAILED=1
# Deselected counts the `integration`-marked tests (tests/integration/). It was
# 4 until PR #28 / a77ad08 added a fifth to test_records_flow.py. A deliberate
# change to that count means bumping this constant, on purpose.
EXPECT_DESELECTED=5
EXPECT_FAILED=0

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)

case "$cmd" in
  *"git push"*) ;;
  *) exit 0 ;;
esac

[ "${ALLOW_UNVERIFIED_PUSH:-}" = "1" ] && exit 0

repo="${CLAUDE_PROJECT_DIR:-$PWD}"

deny() { # <reason>
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

if [ -n "${XFAIL_INVARIANT_OUTPUT:-}" ]; then
  out=$(cat "$XFAIL_INVARIANT_OUTPUT" 2>/dev/null) || out=""
else
  out=$(cd "$repo" && make test-docker 2>&1) || true
fi

# The pytest summary line, e.g. "811 passed, 5 deselected, 1 xfailed in 10.34s".
summary=$(printf '%s\n' "$out" | grep -E '^=*[[:space:]]*[0-9]+ (passed|failed|error)' | tail -1)
[ -z "$summary" ] && summary=$(printf '%s\n' "$out" | grep -E '[0-9]+ (passed|failed|xfailed|xpassed|deselected|errors?)([,[:space:]]|$)' | tail -1)

if [ -z "$summary" ]; then
  deny "Could not verify the xfail invariant: the container suite produced no parsable \
pytest summary (Docker down, or the build failed). Run 'make test-docker' by hand and read \
the error. If you must push without the check, set ALLOW_UNVERIFIED_PUSH=1."
fi

count() { # <counter-name> -> prints the number, 0 if absent
  printf '%s' "$summary" | grep -oE "[0-9]+ $1" | tail -1 | grep -oE '^[0-9]+' || printf '0'
}

passed=$(count 'passed')
failed=$(count 'failed')
xfailed=$(count 'xfailed')
xpassed=$(count 'xpassed')
deselected=$(count 'deselected')
errors=$(count 'errors?')

counts="passed=$passed failed=$failed xfailed=$xfailed xpassed=$xpassed deselected=$deselected errors=$errors"

if [ "$xpassed" -ge 1 ] || [ "$xfailed" -ne "$EXPECT_XFAILED" ]; then
  deny "xfail invariant broken ($counts; expected xfailed=$EXPECT_XFAILED, xpassed=0). \
The counted xfail is the IDOR test: auth behavior changed — stop and investigate, do not \
adjust the test. CLAUDE.md §6 zone; this needs explicit human approval, not a test edit."
fi

if [ "$failed" -ne "$EXPECT_FAILED" ] || [ "$errors" -ne 0 ]; then
  deny "Container suite is not green ($counts). Run 'make test-docker' and fix the failures \
before pushing. Push is blocked; ALLOW_UNVERIFIED_PUSH=1 overrides if you know why."
fi

if [ "$deselected" -ne "$EXPECT_DESELECTED" ]; then
  deny "Deselected count drifted ($counts; expected deselected=$EXPECT_DESELECTED). \
Deselected counts the 'integration'-marked tests under tests/integration/. If you added or \
removed one on purpose, bump EXPECT_DESELECTED in .claude/hooks/xfail-invariant.sh in the \
same change. If you did not, a test is being silently skipped — find out why."
fi

exit 0
