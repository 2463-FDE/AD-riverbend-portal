#!/usr/bin/env bash
# SessionStart hook: inject open-PR + branch state so sessions don't spend a
# turn re-deriving it (the engagement-state memory says "check PR status
# first" — this does it automatically).

set -u
repo="${CLAUDE_PROJECT_DIR:-$PWD}"
cd "$repo" 2>/dev/null || exit 0

echo "== Riverbend repo state (auto-injected at session start) =="
echo "Branch: $(git branch --show-current 2>/dev/null || echo '?')  Tip: $(git log --oneline -1 2>/dev/null || echo '?')"

if command -v gh >/dev/null 2>&1; then
  prs=$(gh pr list --state open --json number,title,headRefName --jq \
    '.[] | "PR #\(.number) [\(.headRefName)]: \(.title)"' 2>/dev/null)
  if [ -n "$prs" ]; then
    echo "Open PRs:"
    echo "$prs"
  else
    echo "Open PRs: none (or gh offline)"
  fi
else
  echo "Open PRs: gh CLI not available"
fi

dirty=$(git status --short 2>/dev/null | head -5)
[ -n "$dirty" ] && { echo "Working tree (first 5):"; echo "$dirty"; }
exit 0
