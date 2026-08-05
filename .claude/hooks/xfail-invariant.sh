#!/usr/bin/env bash
# PreToolUse guard (Bash matcher): blocks `git push` unless the container suite
# comes back on this repo's curriculum invariant — exactly 1 xfailed,
# 5 deselected, 0 failed (verify-stack §1).
#
# Why a hook: the invariant is a §6 landmine tripwire, not a style rule. The
# counted xfail is the IDOR test; an XPASS means someone changed auth behavior,
# and the correct response is to stop and investigate, never to adjust the test.
# Nothing enforced that before this hook — it survived on human memory.
#
# Why it RUNS the suite rather than parsing the last run: measured 13.7s wall
# warm (10.3s pytest + docker overhead). A cached transcript cannot tell you
# whether it reflects the tree being pushed, and a stale green is exactly the
# failure this guard exists to prevent.
#
# Escape hatch: ALLOW_UNVERIFIED_PUSH=1 (same doctrine as the pre-commit guard's
# ALLOW_IGNORE_DELETE=1). Test seam: XFAIL_INVARIANT_OUTPUT=<file> reads pytest
# output from a fixture instead of running the suite.
#
# Never echoes suite output — only the parsed counters — so nothing from a
# failing test body lands in the session transcript.

set -u

EXPECT_XFAILED=1
# Deselected counts the `integration`-marked tests (tests/integration/). It was
# 4 until PR #28 / a77ad08 added a fifth to test_records_flow.py. A deliberate
# change to that count means bumping this constant, on purpose.
EXPECT_DESELECTED=5
EXPECT_FAILED=0

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Backslash-newline continuations re-join into one line before any matching:
# grep applies the ERE per line, so a wrapped invocation (`git --git-dir /x \`
# NL `push`) otherwise never matches and skips every check below (r3
# reviewer, reproduced). All downstream extraction reads this normalized form.
cmd=${cmd//\\$'\n'/ }

# Match a git invocation whose SUBCOMMAND is push, not the literal substring —
# `git -C <dir> push` never contained "git push" (PR #36 r2) — and not any
# command merely containing the word: a bare word-match caught `git stash push`,
# which would run (and on red, deny) the suite before every stash (r2 reviewer).
# Arg-taking global options are enumerated (r3: space-separated `--git-dir
# <path>` never matched, so the command exited before the cross-tree check —
# a generic `--opt <arg>` branch is deliberately NOT used, it would re-match
# `git --paginate stash push` shapes and resurrect the stash regression;
# --attr-source is git >= 2.40, harmless to match on older git). Option args
# may carry quoted spaces (`-c user.name="A B"`) — Q_ARG accepts quoted runs,
# else the chain breaks at the space and the whole matcher misses (r3
# reviewer, reproduced with a staged key allowed through).
Q_ARG="([^[:space:]\"']|\"[^\"]*\"|'[^']*')+"
GIT_INV_RE="(^|[^[:alnum:]_])git([[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace|--config-env|--attr-source)[[:space:]]+$Q_ARG|[[:space:]]+-[^[:space:]]+)*[[:space:]]+push([^[:alnum:]_-]|\$)"
printf '%s' "$cmd" | grep -qE "$GIT_INV_RE" || exit 0

[ "${ALLOW_UNVERIFIED_PUSH:-}" = "1" ] && exit 0

repo="${CLAUDE_PROJECT_DIR:-$PWD}"

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

cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)

# A push that targets another git index must not be green-lit by this
# checkout's suite (PR #36 r2 / TODO-50): any repo-redirection form — `git -C`,
# --git-dir/--work-tree, GIT_DIR=/GIT_WORK_TREE=/GIT_INDEX_FILE= env prefixes,
# a cd/pushd compound, or a session cwd elsewhere — denies unless every target
# provably resolves onto THIS checkout's git index (`rev-parse
# --absolute-git-dir` identity, not path containment: a nested checkout such as
# a regression-proof worktree under .claude/worktrees/ sits inside the project
# dir yet owns a different index — r2 reviewer, reproduced). Unresolvable
# targets ($VAR, ~, quotes, substitution) deny too: a guard that must
# out-parse the shell loses. ALLOW_UNVERIFIED_PUSH=1 above still bypasses, as
# the explicit human override.
# Duplicated in phi-secret-guard.sh deliberately — hooks are standalone, no
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

# ALLOW_CROSS_TREE_GIT=1 skips ONLY the cross-tree check (the suite still
# runs) — for false positives where the command merely MENTIONS a redirection
# form. Same doctrine as the other escape env vars: user-confirmed, never a
# routine prefix.
if [ "${ALLOW_CROSS_TREE_GIT:-}" != "1" ]; then
  xtr=$(cross_tree_reason "$cmd" "$cwd")
  [ -n "$xtr" ] && deny "Cross-tree push blocked fail-closed: $xtr. The suite this \
hook runs validates only THIS checkout, so a push aimed at another repository \
would be green-lit by the wrong tree's tests. Push from a session rooted in that \
tree. If the command only MENTIONS a redirection form, re-run with \
ALLOW_CROSS_TREE_GIT=1 after the user confirms; ALLOW_UNVERIFIED_PUSH=1 skips \
the suite too."
fi

if [ -n "${XFAIL_INVARIANT_OUTPUT:-}" ]; then
  out=$(cat "$XFAIL_INVARIANT_OUTPUT" 2>/dev/null) || out=""
else
  out=$(cd "$repo" && make test-docker 2>&1) || true
fi

# The pytest summary line, e.g. "811 passed, 5 deselected, 1 xfailed in 10.34s".
summary=$(printf '%s\n' "$out" | grep -E '^=*[[:space:]]*[0-9]+ (passed|failed|error)' | tail -1)
[ -z "$summary" ] && summary=$(printf '%s\n' "$out" | grep -E '[0-9]+ (passed|failed|xfailed|xpassed|deselected|errors?)([,[:space:]]|$)' | tail -1)

if [ -z "$summary" ]; then
  deny "Could not verify the xfail invariant: the container suite produced no parsable \
pytest summary (Docker down, or the build failed). Run 'make test-docker' by hand and read \
the error. If you must push without the check, set ALLOW_UNVERIFIED_PUSH=1."
fi

count() { # <counter-name> -> prints the number, 0 if absent
  printf '%s' "$summary" | grep -oE "[0-9]+ $1" | tail -1 | grep -oE '^[0-9]+' || printf '0'
}

passed=$(count 'passed')
failed=$(count 'failed')
xfailed=$(count 'xfailed')
xpassed=$(count 'xpassed')
deselected=$(count 'deselected')
errors=$(count 'errors?')

counts="passed=$passed failed=$failed xfailed=$xfailed xpassed=$xpassed deselected=$deselected errors=$errors"

if [ "$xpassed" -ge 1 ] || [ "$xfailed" -ne "$EXPECT_XFAILED" ]; then
  deny "xfail invariant broken ($counts; expected xfailed=$EXPECT_XFAILED, xpassed=0). \
The counted xfail is the IDOR test: auth behavior changed — stop and investigate, do not \
adjust the test. CLAUDE.md §6 zone; this needs explicit human approval, not a test edit."
fi

if [ "$failed" -ne "$EXPECT_FAILED" ] || [ "$errors" -ne 0 ]; then
  deny "Container suite is not green ($counts). Run 'make test-docker' and fix the failures \
before pushing. Push is blocked; ALLOW_UNVERIFIED_PUSH=1 overrides if you know why."
fi

if [ "$deselected" -ne "$EXPECT_DESELECTED" ]; then
  deny "Deselected count drifted ($counts; expected deselected=$EXPECT_DESELECTED). \
Deselected counts the 'integration'-marked tests under tests/integration/. If you added or \
removed one on purpose, bump EXPECT_DESELECTED in .claude/hooks/xfail-invariant.sh in the \
same change. If you did not, a test is being silently skipped — find out why."
fi

exit 0
