#!/usr/bin/env bash
# PreToolUse (Bash matcher): deny git commit/push invocations that disable the
# .githooks/ gate (--no-verify, or commit's -n alias). Deliberately tiny and
# lexical — this is a courtesy tripwire for the agent, not a security control;
# a false negative here still lands on CI's secret-scan + branch protection,
# which are the enforcement layer. The hardened shell-text guards this
# replaces (and the review loop that retired them) are on archive/pipe1-hooks-r5.
# Note: `git push -n` is --dry-run, not --no-verify, so only --no-verify is
# matched for push.

set -u

cmd=$(cat | jq -r '.tool_input.command // empty' 2>/dev/null)

deny() {
  jq -n --arg r "$1" '{hookSpecificOutput: {hookEventName: "PreToolUse",
    permissionDecision: "deny", permissionDecisionReason: $r}}'
  exit 0
}

if printf '%s' "$cmd" | grep -qE 'git[^;|&]*\b(commit|push)\b[^;|&]*--no-verify'; then
  deny "git --no-verify disables the .githooks/ gitleaks gate. Drop the flag; if the hook is misfiring, show the user the output and let them run the bypass themselves."
fi

# -n may sit anywhere in a fused short-flag cluster (`-nm`, `-anm`): match any
# cluster containing n, accepting false denies on other n-flags (courtesy layer).
if printf '%s' "$cmd" | grep -qE 'git[^;|&]*\bcommit\b[^;|&]*[[:space:]]-[a-zA-Z]*n[a-zA-Z]*([[:space:]]|$)'; then
  deny "git commit -n is --no-verify and disables the .githooks/ gitleaks gate. Drop the flag; if the hook is misfiring, show the user the output and let them run the bypass themselves."
fi

exit 0
