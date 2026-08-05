#!/bin/bash
# gates.sh -- read/write the frontend-rebuild gate tracker that feeds the statusline.
#
#   gates.sh on|off                 show / hide the gate bar in the statusline
#   gates.sh show                   print the full board (gates + requirements)
#   gates.sh preview                render the statusline bar exactly as it appears
#   gates.sh gate G2 active         set a gate state: todo|active|awaiting|signed|blocked
#   gates.sh req FE-R3 done         set a requirement: todo|done
#   gates.sh req FE-R1,FE-R2 done   comma-separated batch
#
# Gate and requirement definitions belong to docs/specs/frontend-rebuild.md §6 and
# §5 -- this file only tracks position within them. If a gate or FE-R id changes
# there, change it here too; nothing cross-checks them.

set -euo pipefail

DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
STATE="$DIR/state.json"
GATE_STATES="todo active awaiting signed blocked"
REQ_STATES="todo done"

command -v jq >/dev/null 2>&1 || { echo "gates: jq is required" >&2; exit 1; }
[ -f "$STATE" ] || { echo "gates: no state file at $STATE" >&2; exit 1; }

write() {  # write() <jq-program> [args...]
  local prog="$1"; shift
  local tmp="$STATE.tmp.$$"
  jq "$@" "$prog" "$STATE" >"$tmp" && mv "$tmp" "$STATE"
}

valid() { case " $1 " in *" $2 "*) return 0 ;; *) return 1 ;; esac; }

case "${1:-show}" in
  on|off)
    v=$([ "$1" = on ] && echo true || echo false)
    write ".active = $v"
    echo "gate bar: $1"
    ;;

  gate)
    id="${2:?gates: gate <id> <state>}"; st="${3:?gates: gate <id> <state>}"
    valid "$GATE_STATES" "$st" || { echo "gates: state must be one of: $GATE_STATES" >&2; exit 1; }
    jq -e --arg id "$id" 'any(.gates[]; .id == $id)' "$STATE" >/dev/null \
      || { echo "gates: no such gate '$id'" >&2; exit 1; }
    write '(.gates[] | select(.id == $id) | .state) = $st' --arg id "$id" --arg st "$st"
    echo "$id -> $st"
    ;;

  req)
    ids="${2:?gates: req <id[,id...]> <state>}"; st="${3:?gates: req <id[,id...]> <state>}"
    valid "$REQ_STATES" "$st" || { echo "gates: state must be one of: $REQ_STATES" >&2; exit 1; }
    IFS=',' read -ra list <<<"$ids"
    for r in "${list[@]}"; do
      jq -e --arg r "$r" 'has("reqs") and (.reqs | has($r))' "$STATE" >/dev/null \
        || { echo "gates: no such requirement '$r'" >&2; exit 1; }
      write '.reqs[$r] = $st' --arg r "$r" --arg st "$st"
      echo "$r -> $st"
    done
    ;;

  preview)
    bash "$DIR/../hooks/gate-statusline.sh" </dev/null
    echo
    ;;

  show)
    jq -r '
      def glyph($d; $s): ($d.states[$s] // "?");
      . as $d
      | "tracker: \(.tracker)   bar: \(if .active then "ON" else "off" end)   spec: \(.spec)",
        "",
        (.gates[]
         | . as $g
         | "\(glyph($d; $g.state))  \($g.id)  \($g.state | (. + "          ")[0:9])  \($g.label)"
           + "   [" + (($g.reqs | map(select($d.reqs[.] == "done")) | length | tostring)
           + "/" + ($g.reqs | length | tostring)) + "R]"),
        "",
        "   " + ([.gates[].reqs] | flatten
                 | map(select($d.reqs[.] == "done") ) | length | tostring)
              + "/" + ([.gates[].reqs] | flatten | length | tostring)
              + " requirements done",
        "",
        "   open reqs per gate:",
        (.gates[] | select([.reqs[] | select($d.reqs[.] != "done")] | length > 0)
         | "   \(.id): " + ([.reqs[] | select($d.reqs[.] != "done")] | join(" ")))
    ' "$STATE"
    ;;

  *)
    sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
