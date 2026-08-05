#!/bin/bash
# Statusline for this project: caveman badge + frontend-rebuild gate track.
#
# Wired from .claude/settings.json ("statusLine"). Project settings override the
# user-level statusLine entirely, so this script re-renders the global caveman
# badge itself before appending the gate bar -- do not drop that call.
#
# The gate bar renders only while .claude/gates/state.json has active=true, so a
# session not working the rebuild sees exactly the old statusline.
# Toggle with .claude/gates/gates.sh on|off.
#
# Gate definitions live in docs/specs/frontend-rebuild.md §6; that spec is
# authoritative. state.json is a display cache of where we are in it.

set -u

# Resolve the project root from the script's own location, not from stdin or the
# environment -- the statusline is invoked with the session JSON on stdin and no
# guarantee that CLAUDE_PROJECT_DIR is exported.
HOOK_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$HOOK_DIR/../.." && pwd)
STATE="$PROJECT_DIR/.claude/gates/state.json"

OUT=""

# --- caveman badge (user-level statusline, preserved) ------------------------
CAVEMAN="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/caveman-statusline.sh"
if [ -f "$CAVEMAN" ] && [ ! -L "$CAVEMAN" ]; then
  OUT=$(bash "$CAVEMAN" 2>/dev/null)
fi

emit() { printf '%s' "$OUT"; exit 0; }

# --- gate bar ---------------------------------------------------------------
[ -L "$STATE" ] && emit          # refuse a symlinked state file
[ -f "$STATE" ] || emit
command -v jq >/dev/null 2>&1 || emit

# One jq pass produces every field the bar needs, tab-separated:
#   active \t glyph-track \t focus-id \t focus-label \t focus-done/total \t all-done/total
FIELDS=$(jq -r '
  def glyph($d; $s): ($d.states[$s] // "○");
  def done($d; $rs): ($rs | map(select(($d.reqs[.] // "todo") == "done")) | length);
  . as $d
  | ($d.gates | map(select(.state != "signed")) | first) as $focus
  | ($d.gates | map(.reqs) | flatten) as $all
  | [
      (if $d.active then "1" else "0" end),
      ($d.gates | map(glyph($d; .state)) | join(",")),
      ($d.gates | map(.state) | join(",")),
      ($focus.id // "✓"),
      ($focus.label // "all gates signed"),
      (if $focus then
         ((done($d; $focus.reqs) | tostring) + "/" + ($focus.reqs | length | tostring))
       else "-" end),
      ((done($d; $all) | tostring) + "/" + ($all | length | tostring))
    ] | @tsv
' "$STATE" 2>/dev/null) || emit

[ -n "$FIELDS" ] || emit
IFS=$'\t' read -r ACTIVE GLYPHS STATES FID FLABEL FCOUNT TCOUNT <<<"$FIELDS"
[ "${ACTIVE:-0}" = "1" ] || emit

# Strip anything that could carry a terminal escape out of the state file's
# free-text label before it reaches the terminal on every render.
FLABEL=$(printf '%s' "$FLABEL" | tr -d '\000-\037' | cut -c1-40)
FID=$(printf '%s' "$FID" | tr -cd 'A-Za-z0-9-')

# Colour the track per gate: signed green, awaiting amber, active cyan, todo dim,
# blocked red. Glyphs are zipped with their state names rather than split out of a
# single string -- bash `read -n1` counts bytes, so splitting shreds the multibyte
# glyphs into replacement characters.
color_for() {
  case "$1" in
    signed)   printf '38;5;71'  ;;
    awaiting) printf '38;5;178' ;;
    active)   printf '38;5;80'  ;;
    blocked)  printf '38;5;167' ;;
    *)        printf '38;5;242' ;;   # todo / unknown
  esac
}

IFS=',' read -ra G_ARR <<<"$GLYPHS"
IFS=',' read -ra S_ARR <<<"$STATES"

[ -n "$OUT" ] && printf '%s  ' "$OUT"
printf '\033[38;5;242mFE\033[0m '
for i in "${!G_ARR[@]}"; do
  [ "$i" -gt 0 ] && printf '\033[38;5;238m─\033[0m'
  printf '\033[%sm%s\033[0m' "$(color_for "${S_ARR[$i]:-todo}")" "${G_ARR[$i]}"
done
printf '  \033[38;5;250m%s\033[0m \033[38;5;244m%s\033[0m' "$FID" "$FLABEL"
printf '  \033[38;5;242m%sR · %s\033[0m\n' "$FCOUNT" "$TCOUNT"
