#!/usr/bin/env bash
# PreToolUse guard (Bash matcher): blocks `git commit` when the staged diff
# contains PHI or secret patterns. This repo has shipped a PHI-filled log file
# and a credential-bearing .env into git history — this hook is the tripwire
# against a third occurrence.
#
# Two scan tiers (PR #36 r1 — the old blanket exclusion let a real key into
# tests/ or db/seed/ pass silently):
#   - credential patterns (sk-ant-, AKIA, private key) scan EVERY path — a real
#     key is never legitimate anywhere, fake-data trees included (measured
#     2026-08-05: zero legitimate matches in tests/ or db/seed/).
#   - SSN-shaped and fuzzy secret-assignment patterns exclude tests/ and
#     db/seed/: adversarial tests deliberately plant fake SSNs (§5 rule, 12+
#     files) and the seed holds SSN-shaped demo values; scanning them would
#     block every legitimate commit.
# Residual, accepted: a REAL SSN pasted into tests/ is regex-indistinguishable
# from the fake ones §5 requires — no allowlist fixes that. CI gitleaks stays
# the tree-wide credential net.
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

# Added lines only, staged. Two corpora, one per scan tier (header).
full=$(git -C "$repo" diff --cached --unified=0 2>/dev/null | grep '^+' | grep -v '^+++') || true
[ -z "$full" ] && exit 0
fake_safe=$(git -C "$repo" diff --cached --unified=0 -- . ':(exclude)tests/' ':(exclude)db/seed/' 2>/dev/null | grep '^+' | grep -v '^+++') || true

declare -a hits=()

check() { # <corpus> <label> <extended-regex>
  if [ -n "$1" ] && printf '%s\n' "$1" | grep -qE "$3"; then
    hits+=("$2")
  fi
}

check "$full"      "Anthropic API key (sk-ant-)"           'sk-ant-[A-Za-z0-9_-]{8,}'
check "$full"      "AWS access key id (AKIA...)"           'AKIA[0-9A-Z]{16}'
check "$full"      "private key block"                     'BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY'
check "$fake_safe" "SSN-shaped value (NNN-NN-NNNN)"        '[0-9]{3}-[0-9]{2}-[0-9]{4}'
check "$fake_safe" "secret-like assignment w/ real value"  '(api[_-]?key|secret|password|token)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9+/_-]{20,}'

[ ${#hits[@]} -eq 0 ] && exit 0

reason="Staged diff matches PHI/secret patterns: $(IFS='; '; echo "${hits[*]}"). \
Inspect with 'git diff --cached'. Credential patterns scan every path, fake-data \
trees included; SSN and secret-assignment patterns exclude tests/ and db/seed/, \
so one of those hits is OUTSIDE the fake-data trees. If it is real PHI or a real \
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
