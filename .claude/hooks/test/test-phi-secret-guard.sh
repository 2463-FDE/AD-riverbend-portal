#!/usr/bin/env bash
# Golden test for .claude/hooks/phi-secret-guard.sh.
# The hook always exits 0 and signals via a PreToolUse "deny" JSON on stdout,
# so these cases assert on output, not exit code. Each case stages content in
# a scratch git repo and points the hook at it via CLAUDE_PROJECT_DIR.
#
# Secret/SSN-shaped fixture strings are built by CONCATENATION so this file
# never contains a matchable literal — otherwise the hook (and CI gitleaks)
# would fire on committing the test itself. Usage: bash test-phi-secret-guard.sh
set -uo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
HOOK="$PROJECT_DIR/.claude/hooks/phi-secret-guard.sh"

pass=0; fail=0
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

# Fixture strings, concatenated (see header).
AWS_KEY="AKIA""IOSFODNN7EXAMPLE"
ANT_KEY="sk-ant-""api03-abcdefgh"
PEM_HDR="-----BEGIN ""PRIVATE KEY-----"
FAKE_SSN="123-""45-6789"
SECRET_ASSIGN="password = \"aaaa""bbbbccccddddeeeeffff\""

new_repo() {
  local r="$SCRATCH/repo-$RANDOM$RANDOM"
  mkdir -p "$r" && git -C "$r" init -q >/dev/null 2>&1
  printf '%s' "$r"
}

stage() { # <repo> <relpath> <content>
  local repo="$1" rel="$2"
  mkdir -p "$repo/$(dirname "$rel")"
  printf '%s\n' "$3" > "$repo/$rel"
  git -C "$repo" add "$rel"
}

verdict() { # <repo> [command] -> prints deny|allow
  local out
  out=$(printf '{"tool_input":{"command":"%s"}}' "${2:-git commit -m x}" \
    | CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>/dev/null)
  case "$out" in
    *permissionDecision*deny*) echo deny ;;
    *) echo allow ;;
  esac
}

expect() { # <want> <label> <repo> [command]
  local want="$1" label="$2" got
  got=$(verdict "$3" "${4:-git commit -m x}")
  if [ "$got" = "$want" ]; then
    printf '  ok    %-42s %s\n' "$label" "$got"; pass=$((pass+1))
  else
    printf '  FAIL  %-42s want %s got %s\n' "$label" "$want" "$got"; fail=$((fail+1))
  fi
}

echo "Credential patterns must deny EVERYWHERE, fake-data trees included:"
r=$(new_repo); stage "$r" "tests/test_leak.py" "key = '$AWS_KEY'"
expect deny "AWS key staged in tests/" "$r"
r=$(new_repo); stage "$r" "db/seed/notes.sql" "-- $ANT_KEY"
expect deny "Anthropic key staged in db/seed/" "$r"
r=$(new_repo); stage "$r" "tests/fixtures/key.pem" "$PEM_HDR"
expect deny "private key staged in tests/" "$r"
r=$(new_repo); stage "$r" "services/gateway/config.py" "$ANT_KEY"
expect deny "Anthropic key staged in services/" "$r"

echo "SSN + secret-assignment keep the fake-tree exclusion (§5 rule):"
r=$(new_repo); stage "$r" "tests/test_adversarial.py" "ssn = '$FAKE_SSN'"
expect allow "fake SSN staged in tests/" "$r"
r=$(new_repo); stage "$r" "db/seed/generate_seed.py" "'$FAKE_SSN',"
expect allow "SSN-shaped seed value in db/seed/" "$r"
r=$(new_repo); stage "$r" "tests/conftest.py" "$SECRET_ASSIGN"
expect allow "secret assignment in tests/" "$r"

echo "...but still deny OUTSIDE the fake-data trees:"
r=$(new_repo); stage "$r" "services/records-service/app.py" "patient_ssn = '$FAKE_SSN'"
expect deny "SSN staged in services/" "$r"
r=$(new_repo); stage "$r" "services/gateway/settings.py" "$SECRET_ASSIGN"
expect deny "secret assignment in services/" "$r"

echo "Non-commit commands and clean diffs must allow:"
r=$(new_repo); stage "$r" "tests/test_leak.py" "key = '$AWS_KEY'"
expect allow "dirty stage, non-commit command" "$r" "ls -la"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive here"
expect allow "clean staged diff" "$r"
r=$(new_repo)
expect allow "empty stage" "$r"

echo "Degenerate payloads must allow (never block on bad input):"
for payload in '' 'not json' '{}' '{"tool_input":null}' '{"tool_input":{"command":123}}'; do
  out=$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$SCRATCH" bash "$HOOK" 2>/dev/null)
  case "$out" in
    *permissionDecision*deny*)
      printf '  FAIL  %-42s want allow got deny\n' "payload: ${payload:-<empty>}"; fail=$((fail+1)) ;;
    *)
      printf '  ok    %-42s allow\n' "payload: ${payload:-<empty>}"; pass=$((pass+1)) ;;
  esac
done

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
