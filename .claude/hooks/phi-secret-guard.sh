#!/usr/bin/env bash
# PreToolUse guard (Bash matcher): blocks `git commit` when the staged diff
# contains PHI or secret patterns. This repo has shipped a PHI-filled log file
# and a credential-bearing .env into git history — this hook is the tripwire
# against a third occurrence.
#
# Exclusions (fake-by-design data lives here; scanning them would block every
# legitimate commit):
#   - tests/     : adversarial tests deliberately plant fake SSNs/PHI (§5 rule)
#   - db/seed/   : deterministic fake demo patients, includes SSN-shaped values
#
# On match: emits a PreToolUse "deny" decision. Never prints the matched
# content itself (that would copy the secret into the session transcript);
# points at `git diff --cached` instead.

set -u

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)

case "$cmd" in
  *"git commit"*) ;;
  *) exit 0 ;;
esac

repo="${CLAUDE_PROJECT_DIR:-$PWD}"

# Added lines only, staged, minus the fake-data trees.
staged=$(git -C "$repo" diff --cached --unified=0 -- . ':(exclude)tests/' ':(exclude)db/seed/' 2>/dev/null | grep '^+' | grep -v '^+++') || true
[ -z "$staged" ] && exit 0

declare -a hits=()

check() { # <label> <extended-regex>
  if printf '%s\n' "$staged" | grep -qE "$2"; then
    hits+=("$1")
  fi
}

check "SSN-shaped value (NNN-NN-NNNN)"        '[0-9]{3}-[0-9]{2}-[0-9]{4}'
check "Anthropic API key (sk-ant-)"           'sk-ant-[A-Za-z0-9_-]{8,}'
check "AWS access key id (AKIA...)"           'AKIA[0-9A-Z]{16}'
check "private key block"                     'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
check "secret-like assignment w/ real value"  '(api[_-]?key|secret|password|token)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9+/_-]{20,}'

[ ${#hits[@]} -eq 0 ] && exit 0

reason="Staged diff matches PHI/secret patterns: $(IFS='; '; echo "${hits[*]}"). \
Inspect with 'git diff --cached' (tests/ and db/seed/ are excluded from this scan — \
a hit means the pattern is OUTSIDE the fake-data trees). If it is real PHI or a real \
credential: unstage it. If it is a false positive, commit with the user's explicit \
go-ahead after showing them the matching lines."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 0
