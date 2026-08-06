#!/usr/bin/env bash
# Golden test for .claude/hooks/syntax-check.sh.
# Asserts exit codes only — the message text is checked by eye, the exit code is
# what the harness actually acts on. Usage: bash test-syntax-check.sh
set -uo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
HOOK="$PROJECT_DIR/.claude/hooks/syntax-check.sh"
FIX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fixtures"
export CLAUDE_PROJECT_DIR="$PROJECT_DIR"

pass=0; fail=0

# hook_exit <path> -> prints exit code, discards output
hook_exit() {
  printf '{"hook_event_name":"PostToolUse","tool_name":"Write","tool_input":{"file_path":"%s"}}' "$1" \
    | bash "$HOOK" >/dev/null 2>&1
  printf '%s' "$?"
}

expect() { # expect <want> <label> <path>
  local want="$1" label="$2" got
  got="$(hook_exit "$3")"
  if [ "$got" = "$want" ]; then
    printf '  ok    %-34s exit %s\n' "$label" "$got"; pass=$((pass+1))
  else
    printf '  FAIL  %-34s want %s got %s\n' "$label" "$want" "$got"; fail=$((fail+1))
  fi
}

echo "Broken files must exit 2:"
for f in bad.py bad2.sh bad.json bad.yaml bad.html bad.js; do expect 2 "$f" "$FIX/$f"; done

echo "Valid files must exit 0:"
for f in ok.py ok.sh ok.json ok.yaml ok.html ok.js; do expect 0 "$f" "$FIX/$f"; done

echo "Real repo files must exit 0 (no false positives):"
for f in services/gateway/app.py db/seed/generate_seed.py docker-compose.yml \
         .claude/settings.json .claude/hooks/syntax_check.py \
         .claude/hooks/syntax-check.sh docs/design/w4-multi-agent-assembly.html \
         frontend/package.json; do
  expect 0 "$f" "$PROJECT_DIR/$f"
done

echo "Degenerate input must never block an edit (exit 0):"
expect 0 "missing file"     "$FIX/nope.py"
# A tracked .md: any file with an extension the hook does not parse-check. Was CLAUDE.md
# until 2026-08-05, when it was untracked and moved to Riverbend/ -- a fixture must be a file
# a fresh checkout actually has.
expect 0 "unchecked ext"    "$PROJECT_DIR/docs/landmines.md"
expect 0 "node_modules"     "$PROJECT_DIR/frontend/node_modules/x/bad.py"

for payload in '' 'not json' '{}' '{"tool_input":null}' '{"tool_input":{"file_path":123}}'; do
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1
  got=$?
  if [ "$got" = 0 ]; then
    printf '  ok    %-34s exit 0\n' "payload: ${payload:-<empty>}"; pass=$((pass+1))
  else
    printf '  FAIL  %-34s want 0 got %s\n' "payload: ${payload:-<empty>}" "$got"; fail=$((fail+1))
  fi
done

echo "CLAUDE_FILE_PATHS fallback must still catch a break (exit 2):"
CLAUDE_FILE_PATHS="$FIX/bad.json" bash -c \
  'printf "{\"tool_input\":{}}" | bash "$1" >/dev/null 2>&1' _ "$HOOK"
got=$?
if [ "$got" = 2 ]; then
  printf '  ok    %-34s exit 2\n' "env fallback"; pass=$((pass+1))
else
  printf '  FAIL  %-34s want 2 got %s\n' "env fallback" "$got"; fail=$((fail+1))
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
