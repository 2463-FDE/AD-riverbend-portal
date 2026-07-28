#!/usr/bin/env bash
# Mechanical health check for the project's Claude Code memory directory.
# Phase 1 of the memory-lint skill: structure only. Everything that needs
# judgment (contradictions, stale claims, index-vs-body drift) is phase 2,
# driven by this script's output. See SKILL.md.
#
# Usage: bash .claude/skills/memory-lint/lint.sh [memory_dir]
# Exit code is always 0 — findings are advisory, and a non-zero exit would
# make this unusable from a hook without gating unrelated work.

set -uo pipefail

M="${1:-}"
if [ -z "$M" ]; then
  root="${CLAUDE_PROJECT_DIR:-$PWD}"
  M="$HOME/.claude/projects/$(printf '%s' "$root" | tr '/' '-')/memory"
fi
[ -d "$M" ] || { echo "memory dir not found: $M"; exit 0; }
IDX="$M/MEMORY.md"

# `grep` may be ugrep on this machine. Any pattern that can begin with `-`
# (wikilink slugs, backticked flags like `--build`) MUST go through `-e`,
# or it is parsed as an option. This bit once produced a fake finding.
pages() { find "$M" -maxdepth 1 -name '*.md' ! -name 'MEMORY.md' | sort; }

# Append-only logs written by hooks: exempt from frontmatter, and excluded from
# co-mention clustering because a raw transcript log mentions every artifact and
# so joins every cluster (measured: it polluted 5 of 14 clusters on the first run).
LOGS='session-handoffs.md'
is_log() { printf '%s\n' $LOGS | grep -qx -e "$1"; }

echo "## memory-lint — $(pages | wc -l | tr -d ' ') pages, $(du -sh "$M" | cut -f1) on disk"

echo
echo "### index integrity"
grep -oE '\]\([^)]+\.md\)' "$IDX" | tr -d ']()' | while read -r f; do
  [ -f "$M/$f" ] || echo "  dangling-pointer: MEMORY.md links $f — no such page"
done
pages | while read -r f; do
  b=$(basename "$f")
  grep -qF -e "($b)" "$IDX" || echo "  orphan-page: $b has no MEMORY.md pointer"
done

echo
echo "### frontmatter"
pages | while read -r f; do
  b=$(basename "$f"); slug=$(basename "$f" .md)
  is_log "$b" && continue
  n=$(grep -m1 '^name:' "$f" | sed 's/^name: *//')
  [ -z "$n" ] && { echo "  no-frontmatter: $b — add it, or whitelist it in LOGS if a hook writes it"; continue; }
  [ "$n" = "$slug" ] || echo "  slug-mismatch: $b declares name: '$n'"
  grep -q '^description:' "$f" || echo "  no-description: $b (recall matches on this line)"
  grep -qE '^ +type: (user|feedback|project|reference)' "$f" || echo "  bad-type: $b"
done

echo
echo "### wikilink graph"
grep -ohE '\[\[[a-z0-9-]+\]\]' "$M"/*.md | tr -d '[]' | sort -u | while read -r n; do
  [ -f "$M/$n.md" ] || echo "  unresolved: [[$n]] (unwritten memory = fine; skill/doc name = wrong link type)"
done
pages | while read -r f; do
  b=$(basename "$f" .md)
  grep -qhF -e "[[$b]]" "$M"/*.md || echo "  in-degree-0: $b (reachable only via the index)"
done

echo
echo "### provenance (sources: frontmatter — see SKILL.md 'gap 2')"
missing=0
pages | while read -r f; do
  b=$(basename "$f"); is_log "$b" && continue
  # The memory store REWRITES frontmatter on save: a top-level `sources:` is moved under
  # `metadata:` and re-indented, so match it anywhere in the block, not at column 0.
  if grep -qE '^ *sources:' "$f"; then
    # every repo-relative path claimed as a source must still exist. Scan the whole
    # frontmatter block (only sources: holds paths) rather than a fragile sed range.
    awk '/^---[[:space:]]*$/{n++; next} n==1' "$f" \
      | grep -oE '(adr|docs|services|tests|db|frontend|config|\.claude)/[A-Za-z0-9_./-]+' \
      | sort -u | while read -r p; do
        [ -e "${CLAUDE_PROJECT_DIR:-$PWD}/$p" ] || echo "  dead-source: $b cites $p — gone from repo"
      done
  else
    echo "$b" >> /tmp/.memlint-nosrc.$$
  fi
done
if [ -f /tmp/.memlint-nosrc.$$ ]; then
  echo "  no-sources: $(wc -l < /tmp/.memlint-nosrc.$$ | tr -d ' ') pages carry no sources: field (unauditable once they age)"
  rm -f /tmp/.memlint-nosrc.$$
fi

echo
echo "### age (oldest first, top 6)"
find "$M" -maxdepth 1 -name '*.md' -exec stat -f '%Sm %N' -t '%Y-%m-%d' {} \; \
  | sed "s|$M/||" | sort | head -6 | sed 's/^/  /'

echo
echo "### co-mention clusters (phase-2 contradiction candidates)"
echo "  read only these page sets; 3-5 pages is the useful band — 6+ is a hub, not a pair"
CURATED=$(pages | while read -r f; do is_log "$(basename "$f")" || printf '%s\n' "$f"; done)
grep -ohE 'PR #[0-9]+|ADR 00[0-9]+|D[0-9]{1,2}\b|RIV-[0-9]+' $CURATED | sort -u | while read -r tok; do
  hits=$(grep -lE -e "$tok" $CURATED 2>/dev/null | xargs -n1 basename | tr '\n' ' ')
  n=$(printf '%s' "$hits" | wc -w)
  [ "$n" -ge 3 ] && [ "$n" -le 5 ] && echo "  $tok -> $hits"
done

echo
echo "### index cost (the only figure that scales per-turn)"
wc -c "$IDX" | awk '{printf "  MEMORY.md %d bytes ~= %d tokens every turn (soft ceiling 8000 B / ~2k tok)\n", $1, $1/4}'
