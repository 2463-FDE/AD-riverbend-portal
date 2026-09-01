"""Assertions on PHI-control tests cannot be weakened without saying so.

The class this guards: a diff changes a shape, a RETAINED test's assertion is
edited to match, and nothing reddens. The rule is *disclose, then move*
(eligibility-assistant-D-73, D-84, D-87), and what went missing repeatedly was
the disclosure step.

**Why a hash and not a count.** The known weakenings changed the STRENGTH of a
comparison (exact equality to subset, equality to `in`), not the number of
`assert` statements, so what is pinned is the normalized source of every
`assert` expression in each guarded test, hashed.

**What this buys.** Editing any assertion in a guarded test reddens this file and
forces a visible pin update in the same diff. It does NOT stop the edit; it stops
the edit from being SILENT.

**What it does not cover.** Python only, and only the tests named below — the
PHI, log-closure and prompt-purity controls of `docs/landmines.md` §3. It says
nothing about whether an assertion is *correct*, only whether it changed. It
cannot see TypeScript, so the frontend retained tests stay a reviewer's job.
"""
import ast
import hashlib
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each entry: the control the test holds closed, and the hash of its assertion
# set. A changed hash is not a failure to route around — it is the disclosure
# prompt. Update it in the SAME commit that moves the assertion, and record the
# move in the item's Deviations, exactly as the five ratified moves were.
ASSERTION_PINS = {
    # docs/phi-logging-policy.md rule 5: adding a field to the chat log line means
    # adding it on purpose.
    ("tests/test_ai_visit_chat.py", "test_the_log_says_whether_a_payer_was_asked_on_this_turn"):
        "ac9174ecd90d1e41",
    # SPEC-12: no clerk free text reaches either model payload.
    ("tests/test_ai_visit_chat.py", "test_the_prompt_contains_no_free_text_from_the_clerk"):
        "14904e3a7401925e",
    # Invalid model ids are gated and never reach a log record.
    ("tests/test_ai_visit_chat.py", "test_invalid_ids_never_reach_a_log_record"):
        "f5c581e3139be7de",
    # The strongest PHI claim in the repo: each model payload is a pure function of
    # closed inputs.
    ("tests/test_visit_chat_phi.py", "test_the_prompt_is_exactly_the_deterministic_build"):
        "0183772762f9710b",
    ("tests/test_visit_chat_phi.py", "test_no_phi_reaches_the_prompt"): "a4867c98f43ce64b",
    ("tests/test_visit_chat_phi.py", "test_no_phi_reaches_any_log_record"): "4ce54e652a222f86",
    ("tests/test_visit_chat_phi.py", "test_no_phi_in_logs_when_the_payer_call_fails"): "2e16507df1c0224b",
    ("tests/test_visit_chat_phi.py", "test_degrade_log_carries_no_exception_message"): "d46645c4d72c3134",
    ("tests/test_visit_chat_phi.py", "test_a_degraded_error_string_is_never_persisted"): "925bf94d90a15925",
    ("tests/test_visit_chat_phi.py", "test_no_phi_in_the_http_response"): "bc72cc454a4f44b1",
    ("tests/test_visit_chat_phi.py", "test_an_ssn_is_never_shipped_to_the_payer"): "3fd6feecb0bdfa52",
    ("tests/test_visit_chat_phi.py", "test_the_payer_only_ever_receives_the_member_id"): "330cd4a5206dea69",
    ("tests/test_visit_chat_phi.py", "test_another_clerk_cannot_read_a_visit"): "fd0fef9bbe2a52f3",
}


def _assertion_digest(path, function_name):
    """Normalized hash of every `assert` expression in one test function.

    `ast.unparse` throws away comments, formatting and line breaks, so reflowing a
    test or rewriting its prose does not fire this guard; changing what an
    assertion CHECKS does. Nested functions inside the test are walked too — the
    helpers these tests build are part of what they assert.
    """
    with open(os.path.join(REPO_ROOT, path), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            expressions = [
                ast.unparse(child.test)
                for child in ast.walk(node)
                if isinstance(child, ast.Assert)
            ]
            assert expressions, "%s::%s runs no assertions at all" % (path, function_name)
            return hashlib.sha256("\n".join(expressions).encode("utf-8")).hexdigest()[:16]
    return None


def test_phi_control_assertions_are_pinned():
    moved, missing = [], []
    for (path, function_name), pinned in sorted(ASSERTION_PINS.items()):
        actual = _assertion_digest(path, function_name)
        if actual is None:
            missing.append("%s::%s is pinned here but no longer exists" % (path, function_name))
        elif actual != pinned:
            moved.append(
                "%s::%s assertions changed: pinned %s, now %s"
                % (path, function_name, pinned, actual)
            )

    assert not missing, (
        "a pinned PHI-control test was renamed or deleted:\n  "
        + "\n  ".join(missing)
        + "\n\nRenaming or removing one of these is an owner decision, not a "
        "refactor — record it before updating this file."
    )
    assert not moved, (
        "assertions on a PHI-control test moved:\n  "
        + "\n  ".join(moved)
        + "\n\nThis is the disclosure prompt, not a veto. If the move is intended, "
        "update the pin IN THIS COMMIT and record it in the item's Deviations. If it "
        "is not intended, you have just weakened a control by accident — which is "
        "what this guard exists to catch."
    )
