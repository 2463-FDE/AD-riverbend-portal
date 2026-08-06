"""PostToolUse syntax gate — see .claude/hooks/syntax-check.sh for how it is invoked.

Reads the PostToolUse hook payload on stdin, works out which file the tool just
wrote, and runs the cheapest check that can prove that file is still parseable.
Exits 2 with the diagnostic on stderr when a check fails, so the finding is fed
straight back to Claude instead of being discovered at run time.

Scope is deliberately narrow: every check here must be (a) fast enough to run on
every edit and (b) free of false positives. A check that cries wolf gets muted by
the first person it interrupts, which is worse than no check at all. Anything that
needs a project-wide type graph (`tsc --noEmit` over the Next.js app) is out —
it is seconds, not milliseconds, and belongs in CI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from html.parser import HTMLParser

# Directories whose contents we never authored, so never check.
SKIP_PARTS = ("node_modules", "site-packages", "/.venv/", "/.git/", "__pycache__")

# Characters that cannot legally appear in an HTML attribute *name*. Seeing one
# means the parser fell out of an attribute value early — the signature of a
# nested quote, e.g. style="font-family: "Inter", sans-serif". That construct
# silently truncates the attribute and has broken a whole stylesheet here before.
BAD_ATTR_CHARS = set("\"',;:(){}")


class AttrSanityParser(HTMLParser):
    """Flags attribute names that can only come from a broken quote nesting."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for name, _value in attrs:
            bad = sorted(set(name) & BAD_ATTR_CHARS)
            if bad:
                line, col = self.getpos()
                self.problems.append(
                    f"line {line}, col {col}: <{tag}> has attribute name "
                    f"{name!r} containing {''.join(bad)!r} — an attribute value "
                    f"almost certainly ended early on a nested quote"
                )


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return 0, ""  # tool absent on this machine — not the edit's fault
    except subprocess.TimeoutExpired:
        return 0, ""
    return proc.returncode, (proc.stderr or proc.stdout).strip()


def check_python(path: str, src: str) -> str | None:
    # Compile with THIS interpreter (3.12 via the launcher). Compiling repo code
    # under the system 3.8 would reject valid 3.12 syntax, so if the launcher's
    # last-resort python3 is older than the repo target, skip — fail open like
    # every tool-absent checker; the launcher must never be why an edit is
    # reported broken.
    if sys.version_info < (3, 12):
        return None
    try:
        compile(src, path, "exec")
    except SyntaxError as exc:
        return f"line {exc.lineno}: {exc.msg}"
    return None


def check_json(path: str, src: str) -> str | None:
    try:
        json.loads(src)
    except json.JSONDecodeError as exc:
        return f"line {exc.lineno}, col {exc.colno}: {exc.msg}"
    return None


def check_yaml(path: str, src: str) -> str | None:
    try:
        import yaml
    except ImportError:
        return None
    try:
        list(yaml.safe_load_all(src))
    except yaml.YAMLError as exc:
        return str(exc).replace("\n", " ")
    return None


def check_html(path: str, src: str) -> str | None:
    parser = AttrSanityParser()
    try:
        parser.feed(src)
        parser.close()
    except Exception as exc:  # html.parser is lenient; this is belt-and-braces
        return f"unparseable: {exc}"
    return "; ".join(parser.problems) if parser.problems else None


def check_shell(path: str, src: str) -> str | None:
    shell = "zsh" if path.endswith(".zsh") else "bash"
    code, out = _run([shell, "-n", path])
    if code == 0:
        return None
    return out or f"{shell} -n exited {code}"


def check_node(path: str, src: str) -> str | None:
    code, out = _run(["node", "--check", path])
    if code == 0:
        return None
    # node prints "<path>:<line>", the offending source, a caret, then the real
    # "SyntaxError: ..." message, then a stack. Line 1 alone is just the path.
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    message = next((line for line in lines if "Error:" in line), "")
    lineno = ""
    if lines and lines[0].startswith(path):
        lineno = lines[0][len(path) :].lstrip(":").split(":")[0]
    if message:
        return f"line {lineno}: {message}" if lineno else message
    return f"node --check exited {code}"


CHECKS = {
    ".py": check_python,
    ".json": check_json,
    ".yaml": check_yaml,
    ".yml": check_yaml,
    ".html": check_html,
    ".htm": check_html,
    ".sh": check_shell,
    ".bash": check_shell,
    ".zsh": check_shell,
    ".js": check_node,
    ".mjs": check_node,
    ".cjs": check_node,
}


def target_paths(payload: dict) -> list[str]:
    """Every file path this tool call may have written.

    Reads the documented PostToolUse shape (`tool_input.file_path`) and also
    honours CLAUDE_FILE_PATHS, so a change to either contract degrades to
    "checked nothing" rather than "crashed on every edit".
    """
    found: list[str] = []
    tool_input = payload.get("tool_input") or {}
    for key in ("file_path", "notebook_path", "path"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    for value in (os.environ.get("CLAUDE_FILE_PATHS") or "").split():
        if value:
            found.append(value)
    seen: set[str] = set()
    return [p for p in found if not (p in seen or seen.add(p))]


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # never let a malformed payload block an edit

    failures: list[str] = []
    for path in target_paths(payload):
        if any(part in path for part in SKIP_PARTS):
            continue
        check = CHECKS.get(os.path.splitext(path)[1].lower())
        if check is None or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                src = handle.read()
        except OSError:
            continue
        problem = check(path, src)
        if problem:
            failures.append(f"{path}: {problem}")

    if failures:
        sys.stderr.write(
            "Syntax check failed on the file just written. Fix this before "
            "continuing or running it:\n  " + "\n  ".join(failures) + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
