#!/usr/bin/env bash
# Golden test for .claude/hooks/xfail-invariant.sh.
# This hook signals with deny JSON on stdout (not an exit code, unlike
# syntax-check.sh), so every assertion reads permissionDecision out of the JSON.
#
# Every case injects pytest output via XFAIL_INVARIANT_OUTPUT, so the test never
# starts Docker and never touches the real suite — the deny paths are proven from
# fixtures rather than by breaking a test. Usage: bash test-xfail-invariant.sh
set -uo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
HOOK="$PROJECT_DIR/.claude/hooks/xfail-invariant.sh"
FIX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixtures"
export CLAUDE_PROJECT_DIR="$PROJECT_DIR"

pass=0; fail=0

ok()   { printf '  ok    %-38s %s\n' "$1" "$2"; pass=$((pass+1)); }
bad()  { printf '  FAIL  %-38s want %s got %s\n' "$1" "$2" "$3"; fail=$((fail+1)); }

# verdict <hook-stdout> -> allow|deny  (silence IS the allow signal)
verdict() {
  [ -z "$1" ] && { printf 'allow'; return; }
  printf '%s' "$1" | jq -r '.hookSpecificOutput.permissionDecision // "allow"' 2>/dev/null || printf 'allow'
}

# decision <command> <fixture> -> prints allow|deny
decision() {
  local out
  out=$(printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"%s"}}' "$1" \
        | XFAIL_INVARIANT_OUTPUT="$2" bash "$HOOK" 2>/dev/null)
  verdict "$out"
}

expect() { # expect <want> <label> <command> <fixture>
  local got; got="$(decision "$3" "$4")"
  [ "$got" = "$1" ] && ok "$2" "$got" || bad "$2" "$1" "$got"
}

echo "A green suite must allow the push:"
expect allow "1 xfailed / 5 deselected / 0 failed" "git push origin HEAD" "$FIX/pytest-ok.txt"

echo "A broken invariant must deny the push:"
expect deny  "XPASS (auth behavior changed)"  "git push origin HEAD" "$FIX/pytest-xpass.txt"
expect deny  "failed > 0"                     "git push origin HEAD" "$FIX/pytest-failed.txt"
expect deny  "errors > 0"                     "git push origin HEAD" "$FIX/pytest-error.txt"
expect deny  "deselected drift (4)"           "git push origin HEAD" "$FIX/pytest-deselect-drift.txt"
expect deny  "no parsable summary (docker)"   "git push origin HEAD" "$FIX/pytest-nosummary.txt"
expect deny  "empty output"                   "git push origin HEAD" "$FIX/pytest-empty.txt"
expect deny  "missing fixture file"           "git push origin HEAD" "$FIX/nope.txt"

echo "The XPASS denial must carry the mandated wording:"
reason=$(printf '{"tool_input":{"command":"git push"}}' \
         | XFAIL_INVARIANT_OUTPUT="$FIX/pytest-xpass.txt" bash "$HOOK" 2>/dev/null \
         | jq -r '.hookSpecificOutput.permissionDecisionReason // ""')
case "$reason" in
  *"auth behavior changed — stop and investigate, do not adjust the test"*)
    ok "auth-change wording present" "found" ;;
  *) bad "auth-change wording present" "the mandated sentence" "${reason:-<empty>}" ;;
esac

# Discriminating: these use the XPASS fixture, which WOULD deny if the hook ran
# its check — so an "allow" here proves the command matcher short-circuited.
echo "Non-push commands must short-circuit (never run the suite):"
expect allow "git status"      "git status"                 "$FIX/pytest-xpass.txt"
expect allow "git commit"      "git commit -m wip"          "$FIX/pytest-xpass.txt"
expect allow "ls"              "ls -la"                     "$FIX/pytest-xpass.txt"
expect allow "empty command"   ""                           "$FIX/pytest-xpass.txt"

echo "The bypass must allow an otherwise-denied push:"
got=$(verdict "$(printf '{"tool_input":{"command":"git push"}}' \
      | ALLOW_UNVERIFIED_PUSH=1 XFAIL_INVARIANT_OUTPUT="$FIX/pytest-xpass.txt" bash "$HOOK" 2>/dev/null)")
[ "$got" = allow ] && ok "ALLOW_UNVERIFIED_PUSH=1" "allow" || bad "ALLOW_UNVERIFIED_PUSH=1" allow "$got"

echo "Degenerate input must never block (allow):"
for payload in '' 'not json' '{}' '{"tool_input":null}' '{"tool_input":{"command":123}}'; do
  got=$(verdict "$(printf '%s' "$payload" \
        | XFAIL_INVARIANT_OUTPUT="$FIX/pytest-xpass.txt" bash "$HOOK" 2>/dev/null)")
  [ "$got" = allow ] && ok "payload: ${payload:-<empty>}" "allow" \
                     || bad "payload: ${payload:-<empty>}" allow "$got"
done

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
