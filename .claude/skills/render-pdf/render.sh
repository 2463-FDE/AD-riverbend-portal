#!/usr/bin/env bash
# Launcher for render.py — see SKILL.md.
# Picks the 3.12 interpreter (system python3 here is 3.8, CLAUDE.md §3) and
# forwards every argument through untouched.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(cd "$SKILL_DIR/../../.." && pwd)}"

for candidate in \
  "$PROJECT_DIR/.venv/bin/python3.12" \
  "$PROJECT_DIR/.venv/bin/python3" \
  python3.12 \
  python3
do
  if command -v "$candidate" >/dev/null 2>&1; then
    exec "$candidate" "$SKILL_DIR/render.py" "$@"
  fi
done

echo "error: no python3 found" >&2
exit 1
