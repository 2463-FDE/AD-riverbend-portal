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
    # every repo-relative path claimed as a source must still exist. Scan ONLY the
    # sources: list items -- the old "whole frontmatter block, only sources: holds paths"
    # assumption was false and cost a fabricated finding on 2026-08-05: a `description:`
    # reading "frontend/intake-service payload contract mismatch" is prose, not a path,
    # and was reported as a dead source. A sources: block is `- item` lines; the first
    # non-item line ends it. POSIX awk only -- no gawk match() capture groups.
    awk '/^---[[:space:]]*$/ { n++; next }
         n != 1 { next }
         /^[[:space:]]*sources:[[:space:]]*$/ { ins = 1; next }
         ins && /^[[:space:]]*-[[:space:]]/ { print; next }
         ins { ins = 0 }' "$f" \
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
echo "### roster (agents/workflows vs skill/command/CLAUDE.md references)"
# Guard against the stale-roster failure mode (see ../../WORKSPACE-NOTES.md): a doc
# naming an agent/workflow that no longer exists, or an agent/workflow file nothing
# references. Deterministic grep only — judgment about *content* drift is doc-drift's job.
R="${CLAUDE_PROJECT_DIR:-$PWD}"
if [ -d "$R/.claude/agents" ] || [ -d "$R/.claude/workflows" ]; then
  # Corpus: the tracked repo-root CLAUDE.md (§10.2 holds the roster table) + every local
  # skill and command. Paths contain no spaces; unquoted expansion matches CURATED above.
  CORPUS=$(ls "$R/CLAUDE.md" "$R"/.claude/skills/*/SKILL.md "$R"/.claude/commands/*.md 2>/dev/null)
  # Built-in agent types that are not repo files. Keep short; grow only on a real hit.
  BUILTINS='Explore general-purpose Plan'
  # Skill dirs + command basenames: legitimately backticked on roster lines, not agents.
  KNOWN=$( { ls "$R/.claude/skills" 2>/dev/null; ls "$R/.claude/commands" 2>/dev/null | sed 's/\.md$//'; } )

  # 1) explicit path references must resolve to a file
  grep -ohE '\.claude/(agents|workflows)/[A-Za-z0-9_-]+\.(md|js)' $CORPUS | sort -u | while read -r p; do
    [ -e "$R/$p" ] || echo "  dangling-roster-ref: $p is referenced but does not exist"
  done

  # 2) backticked names on lines mentioning agent/workflow must classify as: plugin
  #    (`:`-prefixed, or bare cavecrew-* — verify-stack's retirement notes write it
  #    unprefixed), builtin, skill/command, or an existing agent/workflow file.
  #    Two measured noise sources (first run, 2026-08-05):
  #    - "workflow" in the GitHub-Actions sense (`.github/workflows/`, "CI workflows")
  #      dragged in `Makefile` — exclude those lines;
  #    - snake_case code identifiers on prose lines ("W3 agent work" named
  #      `proxy_intake`) — roster names are kebab-case, so `_` is out of the class.
  grep -ih -e 'agent' -e 'workflow' $CORPUS 2>/dev/null \
    | grep -vE '\.github/workflows|CI workflows' \
    | grep -oE '`[A-Za-z][A-Za-z0-9:-]*`' | tr -d '`' | sort -u | while read -r tok; do
      case "$tok" in
        *:*) continue ;;
        cavecrew-*) continue ;;
        # this lint's own finding-class vocabulary, documented (backticked, on
        # agent/workflow lines) in memory-lint's SKILL.md — self-reference, not roster
        dangling-roster-ref|unknown-roster-name|orphan-agent|orphan-workflow) continue ;;
      esac
      # all-caps tokens are shell variables / constants (`BUILTINS`), never roster names
      printf '%s' "$tok" | grep -qE '^[A-Z0-9_-]+$' && continue
      printf '%s\n' $BUILTINS | grep -qx -e "$tok" && continue
      printf '%s\n' "$KNOWN" | grep -qx -e "$tok" && continue
      [ -f "$R/.claude/agents/$tok.md" ] && continue
      [ -f "$R/.claude/workflows/$tok.js" ] && continue
      echo "  unknown-roster-name: \`$tok\` on an agent/workflow line — not a repo agent/workflow, plugin, builtin, skill or command"
    done

  # 3) every agent/workflow file must be referenced by name somewhere in the corpus
  for f in "$R"/.claude/agents/*.md "$R"/.claude/workflows/*.js; do
    [ -e "$f" ] || continue
    s=$(basename "$f"); s="${s%.*}"
    kind=orphan-workflow; case "$f" in */agents/*) kind=orphan-agent ;; esac
    grep -qF -e "$s" $CORPUS || echo "  $kind: $s — no skill, command or CLAUDE.md references it"
  done
else
  echo "  (no $R/.claude/agents or .claude/workflows — skipped)"
fi

echo
echo "### index cost (the only figure that scales per-turn)"
wc -c "$IDX" | awk '{printf "  MEMORY.md %d bytes ~= %d tokens every turn (soft ceiling 8000 B / ~2k tok)\n", $1, $1/4}'
