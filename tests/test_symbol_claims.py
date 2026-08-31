"""Every backticked symbol a Python comment or docstring names must exist.

The guard the `turn` impl gate asked for. Prose that cites a symbol by name is a
claim, and a diff that deletes, renames or retires that symbol falsifies the claim
silently: nothing imports a docstring, so the suite stays green while the file tells
the next reader something untrue. This has been the repeat failure on the
eligibility-assistant branch — swept once for eligibility-assistant-D-40, corrected
again in two gate rounds, and found a third time by the impl gate — so the class is
closed here with a check rather than another sweep.

**What this covers, and what it does not.** It resolves *symbol existence* only:
backticked identifiers that look like code — underscore-prefixed, or CamelCase —
must resolve to something defined, assigned, imported or taken as a parameter
somewhere under `services/` or `tests/`. It cannot tell whether a claim about
BEHAVIOUR is true, and it does not read Markdown or TypeScript. Those stay a
reviewer's job.

Deliberately generous about what counts as "defined": the point is to catch names
that exist NOWHERE, not to check that each file cites only its own symbols. A
narrower rule would fire on the many docstrings that legitimately name a symbol in
the module next door.
"""
import ast
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCANNED = ("services", "tests")

# Names that are deliberately absent from the tree, or belong to someone else's.
# An entry here is a statement that the citation is correct AS a citation — each one
# says why, so this list cannot quietly become a place to silence a real finding.
ALLOWED_ABSENT = {
    # The swallowing gateway proxy helpers, deleted by e5 (CLAUDE.md §4). The whole
    # subject of test_gateway_proxy_error_contract.py is that they are gone, so it
    # names them; so does the docstring of each replacement.
    "_get": "deleted by e5; cited as deliberately absent",
    "_post": "deleted by e5; cited as deliberately absent",
    # A suffix fragment in prose about `_post_checked`, not a symbol.
    "_checked": "name fragment, not a symbol",
    # Vendor and library types this repo never defines.
    "AccessDeniedException": "Bedrock error code",
    "ValidationException": "Bedrock error code",
    "RowMapping": "SQLAlchemy result type",
}

# A backticked or double-backticked identifier, optionally called.
_TOKEN = re.compile(r"``?([A-Za-z_][A-Za-z0-9_]*)(?:\(\))?``?")
# Cap, lowercase, then another Cap — `VisitChatResponse`, not `Bedrock` or `TODO`.
_CAMEL = re.compile(r"^[A-Z][a-z0-9]+[A-Z]")


def _python_files():
    for directory in SCANNED:
        for base, dirs, names in os.walk(os.path.join(REPO_ROOT, directory)):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules")]
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(base, name)


def _defined_names(trees):
    """Every name the tree binds: defs, classes, assignments, parameters, imports.

    Attribute names count too (`app_mod.agent_turn` binds nothing, but `.agent_turn`
    is a real symbol on the object), which is what keeps cross-module citations from
    firing.
    """
    names = set()
    for tree in trees.values():
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, ast.arg):
                names.add(node.arg)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.alias):
                names.add((node.asname or node.name).split(".")[0])
    return names


def test_backticked_symbols_resolve():
    sources, trees = {}, {}
    for path in _python_files():
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        sources[path] = source
        trees[path] = ast.parse(source)

    defined = _defined_names(trees)
    dangling = []
    for path, source in sources.items():
        for match in _TOKEN.finditer(source):
            name = match.group(1)
            if name.startswith("__") or name in ALLOWED_ABSENT or name in defined:
                continue
            if not (name.startswith("_") or _CAMEL.match(name)):
                continue
            line = source[: match.start()].count("\n") + 1
            dangling.append(
                "%s:%d names `%s`, which is defined nowhere under %s"
                % (os.path.relpath(path, REPO_ROOT), line, name, "/".join(SCANNED))
            )

    assert not dangling, (
        "in-code claims about symbols that do not exist:\n  "
        + "\n  ".join(sorted(dangling))
        + "\n\nFix the prose, or add the name to ALLOWED_ABSENT with the reason it is "
        "cited while absent."
    )
