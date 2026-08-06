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
# The scan reads the index as it stands BEFORE the command runs, so a commit
# that stages while it commits would be validated against the wrong index
# (PR #36 r4, [high]). An index-stability gate denies those shapes up front —
# see the block above the scan for the allowlist rationale.
#
# On match: emits a PreToolUse "deny" decision. Never prints the matched
# content itself (that would copy the secret into the session transcript);
# points at `git diff --cached` instead.

set -u

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)

# Backslash-newline continuations re-join into one line before any matching:
# grep applies the ERE per line, so a wrapped invocation (`git --git-dir /x \`
# NL `commit`) otherwise never matches and skips every check below (r3
# reviewer, reproduced). All downstream extraction reads this normalized form.
cmd=${cmd//\\$'\n'/ }

# `git commit` can carry global options between the words (`git -C <dir> commit`,
# `git -c a=b commit`) — match a git invocation whose SUBCOMMAND is commit, not
# the literal substring (PR #36 r2: that never fired on redirected forms) and not
# any command merely containing the word (r2 reviewer: a bare word-match caught
# `git stash`-style siblings and post-subcommand flags like `git commit -C HEAD`).
# Arg-taking global options are enumerated (r3: space-separated `--git-dir
# <path>` never matched, so the command exited before the cross-tree check —
# a generic `--opt <arg>` branch is deliberately NOT used, it would re-match
# `git --paginate stash push` shapes and resurrect the stash regression;
# --attr-source is git >= 2.40, harmless to match on older git). Option args
# may carry quoted spaces (`-c user.name="A B"`) — Q_ARG accepts quoted runs,
# else the chain breaks at the space and the whole matcher misses (r3
# reviewer, reproduced with a staged key allowed through).
Q_ARG="([^[:space:]\"']|\"[^\"]*\"|'[^']*')+"
GIT_INV_RE="(^|[^[:alnum:]_])git([[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace|--config-env|--attr-source)[[:space:]]+$Q_ARG|[[:space:]]+-[^[:space:]]+)*[[:space:]]+commit([^[:alnum:]_-]|\$)"
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

# ---------------------------------------------------------------------------
# Index-stability gate (PR #36 r4, [high]). The scan below reads `git diff
# --cached` BEFORE the command executes, so every invocation that stages as
# part of committing is checked against an index that is about to change:
# `git commit -a/-am/--all`, `git commit <pathspec>`, `-i/--include`,
# `-o/--only`, `-p/--patch`, and `git add … && git commit`. All of those got
# PHI/secrets past this guard.
#
# Fixed by ALLOWLIST, not by enumerating the bypass shapes. Everything after
# the `commit` word must be a flag that provably cannot touch the index;
# anything else denies. An option nobody anticipated therefore produces a false
# DENY — annoying, and escapable with ALLOW_ONE_SHOT_COMMIT=1 — never a silent
# bypass. That is the point: docs/review-loop-metrics.md tracks matcher-shape
# misses as a recurring class, and a blocklist would put every future miss back
# in the [high] column.
#
# The command is walked left to right and EVERY git invocation in it is
# classified, not just the first (r4 diff-reviewer, reproduced: `git commit -m x
# && git commit -am y` and `git commit -m x && git add . && git commit -m y`
# both slipped a first-match-only gate — the second commit was never looked at,
# and staging BETWEEN two commits sat in neither the prefix nor the tail).
# Non-commit subcommands are checked against a read-only ALLOWLIST for the same
# reason the tail is: a blocklist of staging verbs missed `git checkout <ref> --
# <path>`, `git reset <ref> -- <path>`, `git stash pop --index`, `git apply
# --cached`, `git update-index --add` and `git cherry-pick -n`, all reproduced
# bypasses, and the first of those is the idiom verify-stack §4 itself
# prescribes. A staging verb only matters when a commit FOLLOWS it, so
# `git commit -m x && git add .` is still allowed.
#
# Accepted residuals, both fail-closed and both escapable:
#   - The match is lexical, with no notion of shell quoting (the r2 residual,
#     widened here): a command that merely MENTIONS a commit shape — `echo 'git
#     commit -am wip'`, `grep -rn 'git commit -a' docs/` — is denied. Kept
#     deliberately. Narrowing it to command position would let `bash -c "git
#     commit -am x"` through, which is a bypass, and this whole gate exists
#     because bypasses here are [high] while false denies are an inconvenience.
#     Pinned by harness cases so the size of the surface stays on record.
#   - With ALLOW_ONE_SHOT_COMMIT=1 the scan still runs against the pre-stage
#     index, so an approved one-shot commit is only partly covered.
# CI gitleaks stays the tree-wide net; TODO-50's git-native .githooks/ gate is
# the endpoint that closes both.
NL=$'\n'
# Commit options that take an argument and never stage. (-C/-c/-t here are
# commit's own --reuse-message/--reedit-message/--template, not git's global
# flags — those sit before the subcommand and are handled by GIT_INV_RE.)
RE_COMMIT_ARG='^(--message|--file|--reuse-message|--reedit-message|--author|--date|--template|--trailer|-m|-F|-C|-c|-t)'
RE_COMMIT_ARG_EQ='^(--message|--file|--reuse-message|--reedit-message|--author|--date|--template|--trailer)='
# Commit options that take no argument and never stage. -n/--no-verify is
# deliberately ABSENT: it is index-safe, but it is also what would disable
# TODO-50's git-native .githooks/ gate, and the two guards must not both be
# satisfiable by one flag (r4 diff-reviewer).
RE_COMMIT_BARE='^(--amend|--no-edit|--edit|--signoff|--allow-empty|--allow-empty-message|--dry-run|--no-gpg-sign|--verbose|--quiet|-e|-v|-q|-s|-S)([[:blank:]]|$)'
# Any git invocation, whatever its subcommand — same prefix machinery as
# GIT_INV_RE, which stays the trigger matcher.
GIT_ANY_RE="(^|[^[:alnum:]_])git([[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace|--config-env|--attr-source)[[:space:]]+$Q_ARG|[[:space:]]+-[^[:space:]]+)*[[:space:]]+[a-zA-Z][a-zA-Z-]*([^[:alnum:]_-]|\$)"
# Subcommands that provably cannot write the index. Anything absent counts as
# staging. `commit` is here because each commit invocation is classified on its
# own tail below, not because it is inert.
RE_GIT_READONLY='^(commit|log|status|diff|diff-tree|diff-index|show|show-ref|shortlog|whatchanged|blame|grep|rev-parse|rev-list|name-rev|merge-base|describe|ls-files|ls-tree|ls-remote|cat-file|for-each-ref|symbolic-ref|reflog|config|var|version|help|count-objects|check-ignore|check-attr|verify-commit|verify-tag|branch|tag|notes|remote|fetch|push|bisect)$'
# Unquoted characters that end a bare token: whitespace, quote openers, a
# backslash escape, and every shell separator. Omitting the separators let a
# `;` glue itself onto the preceding value, so `git commit -m x; git log`
# false-denied while the `&&` spelling allowed (r4 diff-reviewer).
TOK_STOP='[[:space:]"'\''\;\&\|\<\>\)\\]'
# Inside a double-quoted run only the closing quote and a backslash matter.
DQ_STOP='[\\"]'

# Consumes one argument off $t (dynamic scope: $t belongs to commit_residue).
# Quoted runs may span newlines — `-m "$(cat <<'EOF' … EOF )"` is this repo's
# normal commit shape and must not read as a residue. Backslash escapes are
# consumed as a unit so the POSIX apostrophe idiom `'\''` does not unbalance
# the walk (r4 diff-reviewer: `git commit -m 'don'\''t ship'` false-denied).
consume_value() {
  local v
  t=${t#"${t%%[![:blank:]]*}"}
  while [ -n "$t" ]; do
    case "$t" in
      \\*)  t=${t#?}; t=${t#?} ;;
      '"'*) # Double quotes honour \" — a single-quoted run never does (POSIX),
            # which is why only this branch walks escapes.
            t=${t#\"}
            while :; do
              case "$t" in
                '')   parse_error=1; return ;;
                '"'*) t=${t#\"}; break ;;
                \\*)  t=${t#?}; t=${t#?} ;;
                *)    v=${t%%$DQ_STOP*}
                      [ -z "$v" ] && { parse_error=1; t=""; return; }
                      t=${t#"$v"} ;;
              esac
            done ;;
      "'"*) v=${t#\'}; case "$v" in *"'"*) t=${v#*\'} ;; *) parse_error=1; t=""; return ;; esac ;;
      [[:space:]]*) break ;;
      *) v=${t%%$TOK_STOP*}; [ -z "$v" ] && break; t=${t#"$v"} ;;
    esac
  done
}

commit_residue() { # <text after the commit word> -> leftover; empty = index-stable,
                   # 'unbalanced-quoting' = could not parse (its own denial)
  local t="$1" parse_error=""
  while :; do
    t=${t#"${t%%[![:blank:]]*}"}
    [ -z "$t" ] && break
    case "$t" in
      ';'*|'&'*|'|'*|'<'*|'>'*|')'*) t=""; break ;;
    esac
    [ "${t:0:1}" = "$NL" ] && { t=""; break; }
    if [[ $t =~ $RE_COMMIT_ARG_EQ ]]; then
      t=${t#*=}
      consume_value
    elif [[ $t =~ $RE_COMMIT_ARG ]]; then
      t=${t#"${BASH_REMATCH[1]}"}
      consume_value
    elif [[ $t =~ $RE_COMMIT_BARE ]]; then
      t=${t#"${BASH_REMATCH[1]}"}
    else
      break
    fi
  done
  [ -n "$parse_error" ] && { printf 'unbalanced-quoting'; return; }
  printf '%s' "$t"
}

# ALLOW_ONE_SHOT_COMMIT=1 skips ONLY this gate (cross-tree check above and the
# pattern scan below still run) — same user-confirmed doctrine as
# ALLOW_CROSS_TREE_GIT, never a routine prefix.
if [ "${ALLOW_ONE_SHOT_COMMIT:-}" != "1" ]; then
  rest="$cmd"
  staged_first=""
  while : ; do
    seg=$(printf '%s' "$rest" | grep -oE "$GIT_ANY_RE" | head -1)
    [ -z "$seg" ] && break
    rest=${rest#*"$seg"}
    # Last word of the matched invocation, minus the delimiter GIT_ANY_RE ate.
    sub=$(printf '%s' "$seg" | sed -E 's/[^a-zA-Z-]+$//; s/.*[^a-zA-Z-]//')
    if [ "$sub" != "commit" ]; then
      [[ $sub =~ $RE_GIT_READONLY ]] || staged_first="$sub"
      continue
    fi
    if [ -n "$staged_first" ]; then
      deny "Compound stage-then-commit blocked fail-closed: this command runs 'git \
$staged_first' before it commits, and that can write the index, but the scan below \
already read the index as it was BEFORE the command ran. Run the staging command on \
its own so the scan sees its result, then commit. Only provably read-only git \
subcommands may precede a commit in one command; if '$staged_first' is one of them and \
the allowlist does not know it, re-run with ALLOW_ONE_SHOT_COMMIT=1 after the user \
confirms."
    fi
    residue=$(commit_residue "$rest")
    if [ "$residue" = "unbalanced-quoting" ]; then
      deny "Commit blocked fail-closed: this guard could not parse the command's \
quoting, so it cannot tell whether the invocation stages anything. It scans 'git diff \
--cached' BEFORE the command runs, and an unreadable command is treated as unsafe \
rather than assumed safe. Simplify the quoting (a message file with -F avoids it \
entirely), or re-run with ALLOW_ONE_SHOT_COMMIT=1 after the user confirms."
    fi
    if [ -n "$residue" ]; then
      deny "One-shot commit blocked fail-closed: unrecognised commit argument \
'${residue%%[[:space:]]*}'. This guard scans 'git diff --cached' BEFORE the command \
runs, so anything that stages while it commits (-a/-am/--all, a pathspec, -i/-o/-p) \
is validated against the wrong index. Stage with a separate 'git add', let this guard \
see the result, then commit with flags only. If the argument is index-safe and the \
allowlist simply does not know it — or if this command is not a commit at all and only \
quotes one — re-run with ALLOW_ONE_SHOT_COMMIT=1 after the user confirms."
    fi
  done
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
