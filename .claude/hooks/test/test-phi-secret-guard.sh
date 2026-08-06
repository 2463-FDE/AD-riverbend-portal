#!/usr/bin/env bash
# Golden test for .claude/hooks/phi-secret-guard.sh.
# The hook always exits 0 and signals via a PreToolUse "deny" JSON on stdout,
# so these cases assert on output, not exit code. Each case stages content in
# a scratch git repo and points the hook at it via CLAUDE_PROJECT_DIR.
#
# Secret/SSN-shaped fixture strings are built by CONCATENATION so this file
# never contains a matchable literal — otherwise the hook (and CI gitleaks)
# would fire on committing the test itself. Usage: bash test-phi-secret-guard.sh
set -uo pipefail

PROJECT_DIR="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
HOOK="$PROJECT_DIR/.claude/hooks/phi-secret-guard.sh"

pass=0; fail=0
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT

# Fixture strings, concatenated (see header).
AWS_KEY="AKIA""IOSFODNN7EXAMPLE"
ANT_KEY="sk-ant-""api03-abcdefgh"
PEM_HDR="-----BEGIN ""PRIVATE KEY-----"
FAKE_SSN="123-""45-6789"
SECRET_ASSIGN="password = \"aaaa""bbbbccccddddeeeeffff\""

new_repo() {
  local r="$SCRATCH/repo-$RANDOM$RANDOM"
  mkdir -p "$r" && git -C "$r" init -q >/dev/null 2>&1
  printf '%s' "$r"
}

stage() { # <repo> <relpath> <content>
  local repo="$1" rel="$2"
  mkdir -p "$repo/$(dirname "$rel")"
  printf '%s\n' "$3" > "$repo/$rel"
  git -C "$repo" add "$rel"
}

verdict() { # <repo> [command] [cwd] -> prints deny|allow
  local out payload
  if [ -n "${3:-}" ]; then
    payload=$(printf '{"tool_input":{"command":"%s"},"cwd":"%s"}' "${2:-git commit -m x}" "$3")
  else
    payload=$(printf '{"tool_input":{"command":"%s"}}' "${2:-git commit -m x}")
  fi
  out=$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>/dev/null)
  case "$out" in
    *permissionDecision*deny*) echo deny ;;
    *) echo allow ;;
  esac
}

expect() { # <want> <label> <repo> [command] [cwd]
  local want="$1" label="$2" got
  got=$(verdict "$3" "${4:-git commit -m x}" "${5:-}")
  if [ "$got" = "$want" ]; then
    printf '  ok    %-42s %s\n' "$label" "$got"; pass=$((pass+1))
  else
    printf '  FAIL  %-42s want %s got %s\n' "$label" "$want" "$got"; fail=$((fail+1))
  fi
}

echo "Credential patterns must deny EVERYWHERE, fake-data trees included:"
r=$(new_repo); stage "$r" "tests/test_leak.py" "key = '$AWS_KEY'"
expect deny "AWS key staged in tests/" "$r"
r=$(new_repo); stage "$r" "db/seed/notes.sql" "-- $ANT_KEY"
expect deny "Anthropic key staged in db/seed/" "$r"
r=$(new_repo); stage "$r" "tests/fixtures/key.pem" "$PEM_HDR"
expect deny "private key staged in tests/" "$r"
r=$(new_repo); stage "$r" "services/gateway/config.py" "$ANT_KEY"
expect deny "Anthropic key staged in services/" "$r"

echo "SSN + secret-assignment keep the fake-tree exclusion (§5 rule):"
r=$(new_repo); stage "$r" "tests/test_adversarial.py" "ssn = '$FAKE_SSN'"
expect allow "fake SSN staged in tests/" "$r"
r=$(new_repo); stage "$r" "db/seed/generate_seed.py" "'$FAKE_SSN',"
expect allow "SSN-shaped seed value in db/seed/" "$r"
r=$(new_repo); stage "$r" "tests/conftest.py" "$SECRET_ASSIGN"
expect allow "secret assignment in tests/" "$r"

echo "...but still deny OUTSIDE the fake-data trees:"
r=$(new_repo); stage "$r" "services/records-service/app.py" "patient_ssn = '$FAKE_SSN'"
expect deny "SSN staged in services/" "$r"
r=$(new_repo); stage "$r" "services/gateway/settings.py" "$SECRET_ASSIGN"
expect deny "secret assignment in services/" "$r"

echo "Non-commit commands and clean diffs must allow:"
r=$(new_repo); stage "$r" "tests/test_leak.py" "key = '$AWS_KEY'"
expect allow "dirty stage, non-commit command" "$r" "ls -la"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive here"
expect allow "clean staged diff" "$r"
r=$(new_repo)
expect allow "empty stage" "$r"

echo "Cross-tree redirection must deny fail-closed (PR #36 r2):"
r=$(new_repo); other=$(new_repo)
expect deny  "git -C <other repo> commit, clean session"  "$r" "git -C $other commit -m x"
expect deny  "cd <other repo> && git commit"              "$r" "cd $other && git commit -m x"
expect deny  "git --git-dir redirection"                  "$r" "git --git-dir=$other/.git commit -m x"
expect deny  "unresolvable cd target (variable)"          "$r" "cd \$DIR && git commit -m x"
expect deny  "nonexistent -C target"                      "$r" "git -C /no/such/dir commit -m x"
expect deny  "pushd <other repo> compound"                "$r" "pushd $other && git commit -m x"
expect deny  "GIT_DIR env-prefix redirection"             "$r" "GIT_DIR=$other/.git git commit -m x"
expect deny  "GIT_WORK_TREE env-prefix redirection"       "$r" "GIT_WORK_TREE=$other git commit -m x"
expect deny  "--git-dir space-separated"                  "$r" "git --git-dir $other/.git commit -m x"
expect deny  "--work-tree space-separated"                "$r" "git --work-tree $other commit -m x"
expect deny  "--git-dir + --work-tree space-separated"    "$r" "git --git-dir $other/.git --work-tree $other commit -m x"

jverdict() { # <repo> <command-via-jq> -> prints deny|allow (for commands with quotes/newlines)
  local out
  out=$(jq -n --arg c "$2" '{tool_input:{command:$c}}' \
    | CLAUDE_PROJECT_DIR="$1" bash "$HOOK" 2>/dev/null)
  case "$out" in
    *permissionDecision*deny*) echo deny ;;
    *) echo allow ;;
  esac
}
jexpect() { # <want> <label> <repo> <command>
  local got; got=$(jverdict "$3" "$4")
  if [ "$got" = "$1" ]; then
    printf '  ok    %-42s %s\n' "$2" "$got"; pass=$((pass+1))
  else
    printf '  FAIL  %-42s want %s got %s\n' "$2" "$1" "$got"; fail=$((fail+1))
  fi
}

echo "Continuations and quoted option args still match (r3 reviewer):"
r=$(new_repo); other=$(new_repo)
jexpect deny "backslash-newline cross-tree commit"  "$r" "git -C $other \\
commit -m x"
r=$(new_repo); stage "$r" "services/x.py" "key = '$AWS_KEY'"
jexpect deny "quoted spaced -c value, staged key"   "$r" 'git -c user.name="Armaan D" commit -m x'
r=$(new_repo); stage "$r" "services/x.py" "key = '$AWS_KEY'"
jexpect deny "--attr-source form, staged key"       "$r" 'git --attr-source HEAD commit -m x'
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive"
jexpect allow "quoted spaced -c value, clean stage" "$r" 'git -c user.name="Armaan D" commit -m x'

echo "A nested checkout INSIDE the project dir is still another index:"
r=$(new_repo); nested="$r/.claude/worktrees/wf_x-1"
mkdir -p "$nested" && git -C "$nested" init -q >/dev/null 2>&1
expect deny  "cd <nested checkout> && git commit"         "$r" "cd .claude/worktrees/wf_x-1 && git commit -m x"
expect deny  "git -C <nested checkout> commit"            "$r" "git -C $nested commit -m x"

echo "Session cwd decides bare git commit (payload .cwd):"
r=$(new_repo); other=$(new_repo)
expect deny  "bare git commit, cwd in other repo"         "$r" "git commit -m x" "$other"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive"
expect allow "bare git commit, cwd project subdir"        "$r" "git commit -m x" "$r/docs"

echo "...but same-repo redirection still allows (and still scans):"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive"
expect allow "git -C <this repo> commit"                  "$r" "git -C $r commit -m x"
expect allow "cd docs && git commit (same-repo subdir)"   "$r" "cd docs && git commit -m x"
r=$(new_repo); stage "$r" "services/gw/settings.py" "$SECRET_ASSIGN"
expect deny  "git -C <this repo> commit still scanned"    "$r" "git -C $r commit -m x"

echo "Broadened matcher: options between git and commit are caught:"
r=$(new_repo); stage "$r" "services/gw/settings.py" "$SECRET_ASSIGN"
expect deny  "git -c a=b commit is pattern-scanned"       "$r" "git -c user.name=x commit -m x"

echo "Post-subcommand and other-tool flags are NOT repo redirection:"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive"
expect allow "git commit -C HEAD (reuse-message flag)"    "$r" "git commit -C HEAD"
expect allow "make -C elsewhere, then git commit"         "$r" "make -C /tmp build && git commit -m x"

echo "ALLOW_CROSS_TREE_GIT=1 skips the cross-tree check but NOT the scan:"
r=$(new_repo); other=$(new_repo)
got=$(printf '{"tool_input":{"command":"git -C %s commit -m x"}}' "$other" \
  | ALLOW_CROSS_TREE_GIT=1 CLAUDE_PROJECT_DIR="$r" bash "$HOOK" 2>/dev/null)
case "$got" in
  *permissionDecision*deny*) printf '  FAIL  %-42s want allow got deny\n' "escape: cross-tree cmd allowed"; fail=$((fail+1)) ;;
  *) printf '  ok    %-42s allow\n' "escape: cross-tree cmd allowed"; pass=$((pass+1)) ;;
esac
r=$(new_repo); stage "$r" "services/gw/settings.py" "$SECRET_ASSIGN"
got=$(printf '{"tool_input":{"command":"git -C %s commit -m x"}}' "$r" \
  | ALLOW_CROSS_TREE_GIT=1 CLAUDE_PROJECT_DIR="$r" bash "$HOOK" 2>/dev/null)
case "$got" in
  *permissionDecision*deny*) printf '  ok    %-42s deny\n' "escape: pattern scan still denies"; pass=$((pass+1)) ;;
  *) printf '  FAIL  %-42s want deny got allow\n' "escape: pattern scan still denies"; fail=$((fail+1)) ;;
esac

# One-shot commit shapes stage AFTER this hook has read the index, so the
# secret lives in a TRACKED, MODIFIED, UNSTAGED file: the staged diff is clean,
# which is exactly why the r3 hook allowed these through. The verdict must now
# come from the shape, before any scan.
echo "One-shot commit shapes must deny fail-closed (PR #36 r4):"
unstaged_secret_repo() { # -> repo whose working tree (not index) holds a key
  local r; r=$(new_repo)
  mkdir -p "$r/services"
  printf 'x = 1\n' > "$r/services/app.py"
  git -C "$r" add services/app.py >/dev/null 2>&1
  git -C "$r" -c user.email=t@example.com -c user.name=t \
    commit -qm init >/dev/null 2>&1
  printf "key = '%s'\n" "$AWS_KEY" > "$r/services/app.py"
  printf '%s' "$r"
}

r=$(unstaged_secret_repo); expect deny  "git commit -am x"            "$r" "git commit -am x"
r=$(unstaged_secret_repo); expect deny  "git commit -a -m x"          "$r" "git commit -a -m x"
r=$(unstaged_secret_repo); expect deny  "git commit --all -m x"       "$r" "git commit --all -m x"
r=$(unstaged_secret_repo); expect deny  "git commit <pathspec>"       "$r" "git commit services/app.py -m x"
r=$(unstaged_secret_repo); expect deny  "git commit -i <pathspec>"    "$r" "git commit -i services/app.py -m x"
r=$(unstaged_secret_repo); expect deny  "git add . && git commit"     "$r" "git add . && git commit -m x"
r=$(unstaged_secret_repo); expect deny  "unknown option (--squash=)"  "$r" "git commit --squash=HEAD -m x"

echo "...but the normal two-step shape and index-safe flags still allow:"
r=$(unstaged_secret_repo); expect allow "git commit -m x, clean index"    "$r" "git commit -m x"
r=$(unstaged_secret_repo); expect allow "git commit --amend --no-edit"    "$r" "git commit --amend --no-edit"
r=$(unstaged_secret_repo); expect allow "git commit -m x && git log"      "$r" "git commit -m x && git log --oneline"
r=$(new_repo); stage "$r" "docs/note.md" "nothing sensitive"
expect allow "git commit --author + -q"       "$r" "git commit --author 'A B <a@b.c>' -q -m x"
jexpect allow "multi-line quoted -m body"     "$r" 'git commit -m "$(cat <<EOF
feat: something

body line
EOF
)"'

echo "ALLOW_ONE_SHOT_COMMIT=1 skips the shape gate but NOT the scan:"
r=$(unstaged_secret_repo)
got=$(printf '{"tool_input":{"command":"git commit -am x"}}' \
  | ALLOW_ONE_SHOT_COMMIT=1 CLAUDE_PROJECT_DIR="$r" bash "$HOOK" 2>/dev/null)
case "$got" in
  *permissionDecision*deny*) printf '  FAIL  %-42s want allow got deny\n' "escape: one-shot allowed"; fail=$((fail+1)) ;;
  *) printf '  ok    %-42s allow\n' "escape: one-shot allowed"; pass=$((pass+1)) ;;
esac
r=$(new_repo); stage "$r" "services/gw/settings.py" "$SECRET_ASSIGN"
got=$(printf '{"tool_input":{"command":"git commit -am x"}}' \
  | ALLOW_ONE_SHOT_COMMIT=1 CLAUDE_PROJECT_DIR="$r" bash "$HOOK" 2>/dev/null)
case "$got" in
  *permissionDecision*deny*) printf '  ok    %-42s deny\n' "escape: pattern scan still denies"; pass=$((pass+1)) ;;
  *) printf '  FAIL  %-42s want deny got allow\n' "escape: pattern scan still denies"; fail=$((fail+1)) ;;
esac

echo "Degenerate payloads must allow (never block on bad input):"
for payload in '' 'not json' '{}' '{"tool_input":null}' '{"tool_input":{"command":123}}'; do
  out=$(printf '%s' "$payload" | CLAUDE_PROJECT_DIR="$SCRATCH" bash "$HOOK" 2>/dev/null)
  case "$out" in
    *permissionDecision*deny*)
      printf '  FAIL  %-42s want allow got deny\n' "payload: ${payload:-<empty>}"; fail=$((fail+1)) ;;
    *)
      printf '  ok    %-42s allow\n' "payload: ${payload:-<empty>}"; pass=$((pass+1)) ;;
  esac
done

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
