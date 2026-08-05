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

# `git commit` can carry global options between the words (`git -C <dir> commit`,
# `git -c a=b commit`) — match a git invocation whose SUBCOMMAND is commit, not
# the literal substring (PR #36 r2: that never fired on redirected forms) and not
# any command merely containing the word (r2 reviewer: a bare word-match caught
# `git stash`-style siblings and post-subcommand flags like `git commit -C HEAD`).
GIT_INV_RE='(^|[^[:alnum:]_])git([[:space:]]+(-C|-c)[[:space:]]+[^[:space:]]+|[[:space:]]+-[^[:space:]]+)*[[:space:]]+commit([^[:alnum:]_-]|$)'
printf '%s' "$cmd" | grep -qE "$GIT_INV_RE" || exit 0

repo="${CLAUDE_PROJECT_DIR:-$PWD}"
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)

deny() { # <reason>
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

# A commit that targets another git index must not be validated against this
# checkout (PR #36 r2 / TODO-50): any repo-redirection form — `git -C`,
# --git-dir/--work-tree, GIT_DIR=/GIT_WORK_TREE=/GIT_INDEX_FILE= env prefixes,
# a cd/pushd compound, or a session cwd elsewhere — denies unless every target
# provably resolves onto THIS checkout's git index (`rev-parse
# --absolute-git-dir` identity, not path containment: a nested checkout such as
# a regression-proof worktree under .claude/worktrees/ sits inside the project
# dir yet owns a different index — r2 reviewer, reproduced). Unresolvable
# targets ($VAR, ~, quotes, substitution) deny too: a guard that must
# out-parse the shell loses. The process-correct cross-tree commit is a
# session rooted in that tree, where its own guards fire.
# Duplicated in xfail-invariant.sh deliberately — hooks are standalone, no
# shared lib; keep the two copies in sync (only GIT_INV_RE differs, per hook).
cross_tree_reason() { # <cmd> <cwd> -> prints a reason iff the target may be another git index
  local cmd="$1" cwd="$2" root root_gitdir t d targets git_segs
  root=$(cd "$repo" 2>/dev/null && pwd -P) || { printf 'project dir does not resolve'; return; }
  root_gitdir=$(git -C "$root" rev-parse --absolute-git-dir 2>/dev/null) || root_gitdir=""
  [ -z "$root_gitdir" ] && { printf 'project dir is not a git checkout'; return; }

  same_index() { # <dir> -> succeeds iff <dir> is on this checkout's git index
    local g
    g=$(git -C "$1" rev-parse --absolute-git-dir 2>/dev/null) || return 1
    [ "$g" = "$root_gitdir" ]
  }

  if [ -n "$cwd" ] && ! same_index "$cwd"; then
    printf "session cwd %s is not on this checkout's git index" "$cwd"
    return
  fi

  if printf '%s' "$cmd" | grep -qE '(^|[[:space:]])GIT_(DIR|WORK_TREE|INDEX_FILE)='; then
    printf 'GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE environment redirection'
    return
  fi

  # Scope flag extraction to the matched git invocation(s): a `-C` after the
  # subcommand (`git commit -C HEAD`) or on another tool (`make -C`) is not a
  # repo redirection (r2 reviewer false-deny class).
  git_segs=$(printf '%s' "$cmd" | grep -oE "$GIT_INV_RE")
  if printf '%s\n' "$git_segs" | grep -qE -- '--(git-dir|work-tree)'; then
    printf 'git --git-dir/--work-tree redirection'
    return
  fi

  targets=$(
    printf '%s\n' "$git_segs" | grep -oE '(^|[[:space:]])-C[[:space:]]+[^[:space:]]+' \
      | sed -E 's/^[[:space:]]*-C[[:space:]]+//'
    printf '%s' "$cmd" | grep -oE '(^|[^[:alnum:]_-])(cd|pushd)[[:space:]]+[^[:space:];|&]+' \
      | sed -E 's/^[^[:alnum:]]*(cd|pushd)[[:space:]]+//'
  )
  while IFS= read -r t; do
    [ -z "$t" ] && continue
    case "$t" in
      *'$'*|*'`'*|'~'*|*'"'*|*"'"*) printf 'unresolvable target %s' "$t"; return ;;
    esac
    case "$t" in
      /*) d=$(cd "$t" 2>/dev/null && pwd -P) || d="" ;;
      *)  d=$(cd "${cwd:-$root}" 2>/dev/null && cd "$t" 2>/dev/null && pwd -P) || d="" ;;
    esac
    [ -z "$d" ] && { printf 'target %s does not resolve' "$t"; return; }
    same_index "$d" || { printf "target %s is not on this checkout's git index" "$t"; return; }
  done <<<"$targets"
}

# ALLOW_CROSS_TREE_GIT=1 skips ONLY the cross-tree check (the pattern scan
# below still runs) — for false positives where the command merely MENTIONS a
# redirection form (heredoc/commit-message text; observed live on first use).
# Same doctrine as ALLOW_IGNORE_DELETE / ALLOW_UNVERIFIED_PUSH: user-confirmed
# escape, never a routine prefix.
if [ "${ALLOW_CROSS_TREE_GIT:-}" != "1" ]; then
  xtr=$(cross_tree_reason "$cmd" "$cwd")
  [ -n "$xtr" ] && deny "Cross-tree commit blocked fail-closed: $xtr. This guard can \
only scan THIS checkout's staged diff, so a commit aimed at another repository \
would be validated against the wrong index. Run the commit from a session rooted \
in that tree, where its own guards fire. Same-repo subdirectory cd is fine. If the \
command only MENTIONS a redirection form (heredoc or message text), re-run with \
ALLOW_CROSS_TREE_GIT=1 after the user confirms."
fi

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

deny "$reason"
