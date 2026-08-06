#!/usr/bin/env bash
# PostToolUse gate: parse-check the file Edit/Write just produced.
#
# Picks the 3.12 interpreter the repo actually targets. The system python3 on
# this machine is 3.8 (CLAUDE.md §3) and would reject valid 3.12 syntax, so the
# venv is preferred and 3.8 is only a last resort — the launcher must never be
# the reason an edit is reported broken.
set -uo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CHECKER="$PROJECT_DIR/.claude/hooks/syntax_check.py"

[ -f "$CHECKER" ] || exit 0

for candidate in \
  "$PROJECT_DIR/.venv/bin/python3.12" \
  "$PROJECT_DIR/.venv/bin/python3" \
  python3.12 \
  python3
do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" "$CHECKER"
  fi
done

exit 0
