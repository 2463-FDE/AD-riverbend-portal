"""
Cross-service invariants (ADR 0010) on the intake -> eligibility -> payer chain.
Neither service can see the other's config at runtime, so these budgets can only
be kept aligned here.

1. eligibility-service's worst-case payer budget must finish before
   intake-service gives up on it, so intake receives the graceful degraded answer
   ("unknown"/"inactive") rather than timing out first and abandoning a
   still-running downstream call (which would waste a retry and pin a worker).
   Red against the pre-fix defaults, where the payer budget (2+3)*2 = 10s
   exceeded intake's 6s.
2. intake's degraded-answer latency threshold must separate eligibility's free
   short-circuit from a real payer round trip (adversarial review r5).
3. intake's slow-*answer* threshold — the one that judges a real coverage verdict
   on what it cost — must be reachable by the cheapest answer that needed a payer
   retry, or it never fires (adversarial review r6).

Each invariant is checked against BOTH sources of truth: the code defaults in
`config.py` AND the values in `.env.example`. The template is what a fresh deploy
actually seeds (`cp .env.example .env`, and CI does the same), so a code default
that satisfies the invariant proves nothing if the template overrides it with a
value that does not — the fail-closed lesson from PR #5 r5.
"""
import os
import re

from conftest import load_module

_elig = load_module("services/eligibility-service/config.py", "elig_config_budget").settings
_intake = load_module("services/intake-service/config.py", "intake_config_budget").settings

MARGIN_SECONDS = 1.0

# Floor for the degraded-answer threshold. eligibility-service's short-circuited
# reply is one local HTTP round trip — sub-10ms in-cluster — so the threshold only
# has to clear ordinary jitter to classify it as free. 100ms is two orders of
# magnitude above that reply and an order of magnitude below the 1s connect
# timeout, so both sides of the invariant have real headroom. "> 0" would be
# decorative: 1ms sits below the round trip itself and would make every free
# short-circuit a breaker failure.
MIN_DEGRADED_SLOW_SECONDS = 0.1

_ENV_EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.example")


def _env_example_values():
    """Parse .env.example — the values `cp .env.example .env` actually deploys."""
    values = {}
    with open(_ENV_EXAMPLE) as f:
        for line in f:
            match = re.match(r"^([A-Z0-9_]+)=(.*)$", line.strip())
            if match:
                values[match.group(1)] = match.group(2)
    return values


def _budgets(source):
    """(payer worst case, intake timeout, degraded-slow threshold, connect timeout)."""
    connect = source["PAYER_CONNECT_TIMEOUT_SECONDS"]
    per_attempt = connect + source["PAYER_READ_TIMEOUT_SECONDS"]
    worst_case = per_attempt * (source["PAYER_MAX_RETRIES"] + 1)
    return worst_case, source["ELIGIBILITY_TIMEOUT_SECONDS"], source["ELIGIBILITY_DEGRADED_SLOW_SECONDS"], connect


def _answer_thresholds(source):
    """(degraded threshold, slow-answer threshold, floor cost of a retried answer).

    The retried floor is the payer READ timeout alone: `check.py` retries only
    after an attempt has burned its read timeout in full, and there is no backoff
    between attempts, so the very cheapest answer that needed a retry costs
    read_timeout + (a fast second attempt). Connect time is deliberately NOT added
    — a hanging read does not slow the TCP handshake, so a degraded payer's
    connects stay fast and including them would overstate the floor.
    """
    return (
        source["ELIGIBILITY_DEGRADED_SLOW_SECONDS"],
        source["ELIGIBILITY_SLOW_ANSWER_SECONDS"],
        source["PAYER_READ_TIMEOUT_SECONDS"],
    )


def _from_code_defaults():
    return {
        "PAYER_CONNECT_TIMEOUT_SECONDS": _elig.payer_connect_timeout_seconds,
        "PAYER_READ_TIMEOUT_SECONDS": _elig.payer_read_timeout_seconds,
        "PAYER_MAX_RETRIES": _elig.payer_max_retries,
        "ELIGIBILITY_TIMEOUT_SECONDS": _intake.eligibility_timeout_seconds,
        "ELIGIBILITY_DEGRADED_SLOW_SECONDS": _intake.eligibility_degraded_slow_seconds,
        "ELIGIBILITY_SLOW_ANSWER_SECONDS": _intake.eligibility_slow_answer_seconds,
    }


def _from_env_example():
    raw = _env_example_values()
    missing = [
        key
        for key in _from_code_defaults()
        if key not in raw
    ]
    assert not missing, f".env.example is missing {missing} — a fresh deploy would not seed them"
    return {key: float(raw[key]) for key in _from_code_defaults()}


def _both_sources():
    return {"config.py defaults": _from_code_defaults(), ".env.example": _from_env_example()}


def test_payer_budget_fits_within_intake_timeout():
    for label, source in _both_sources().items():
        inner, outer, _, _ = _budgets(source)
        assert inner < outer, (
            f"[{label}] payer worst-case {inner}s must be < intake eligibility timeout "
            f"{outer}s, or intake abandons a still-running eligibility call"
        )
        assert outer - inner >= MARGIN_SECONDS, (
            f"[{label}] need >= {MARGIN_SECONDS}s margin between payer worst-case "
            f"({inner}s) and intake timeout ({outer}s); got {outer - inner}s"
        )


def test_degraded_slow_threshold_separates_short_circuit_from_payer_attempt():
    """intake counts a degraded eligibility answer against its breaker only once
    the answer has held the worker `ELIGIBILITY_DEGRADED_SLOW_SECONDS`. That
    number only classifies correctly between two bounds.

    Upper: at or below the payer connect timeout, the floor cost of a payer
    attempt that fails *by timing out*. Set it higher and a genuine payer outage
    reads as free — the r5 bypass, one layer down. (Payer failures that cost
    nothing at all — connection refused, a hard 401 — do read as free, and that
    is correct: they pin no worker, so they are not the RIV-141 mechanism.)

    Lower: comfortably above one local HTTP round trip, so eligibility's free
    short-circuit is never mistaken for a payer round trip and does not trip the
    circuit on a dependency that is answering instantly."""
    for label, source in _both_sources().items():
        _, _, threshold, connect_timeout = _budgets(source)
        assert threshold >= MIN_DEGRADED_SLOW_SECONDS, (
            f"[{label}] ELIGIBILITY_DEGRADED_SLOW_SECONDS ({threshold}s) must be >= "
            f"{MIN_DEGRADED_SLOW_SECONDS}s — below that, eligibility-service's free "
            "short-circuit counts as a breaker failure and intake stops calling a "
            "dependency that is answering instantly"
        )
        assert threshold <= connect_timeout, (
            f"[{label}] ELIGIBILITY_DEGRADED_SLOW_SECONDS ({threshold}s) must be <= the "
            f"payer connect timeout ({connect_timeout}s), the floor cost of a payer "
            "attempt that times out — otherwise a real payer outage never counts "
            "against intake's breaker"
        )


def test_slow_answer_threshold_is_reachable_by_a_retried_payer_answer():
    """intake counts a *definitive* eligibility answer against its breaker once it
    has held the worker `ELIGIBILITY_SLOW_ANSWER_SECONDS` (adversarial review r6).
    The threshold has to sit at or below the CHEAPEST answer that needed a payer
    retry, or the check is dead code.

    This test exists because the first attempt at that number got the anchor
    backwards. It was set to one healthy attempt's *ceiling* (connect + read = 3s)
    and shipped as 4s — but the retried band with realistic (fast) connects tops
    out just under 2 x read_timeout = 4s, so no degrading payer could ever reach
    it. Measured against the real `check.py` with a fake payer: a retry answering
    in 0.1s / 1.0s / 1.9s costs intake 2.13s / 3.01s / 3.93s, all classified
    healthy under a 4s threshold. Every registration kept paying it — the exact
    unbounded-aggregate cost r6 rejected. An invariant is only worth having if it
    forbids the wrong number, so this one asserts against the retried FLOOR.

    Upper bound: the payer read timeout, the floor cost of a retried answer (no
    backoff between attempts, so nothing else is guaranteed to be spent).
    Lower bound: the degraded threshold — a real verdict must never be judged more
    harshly than a no-verdict shrug. `config.py` also clamps this at runtime, so an
    operator override cannot invert it; the assertion pins the shipped values."""
    for label, source in _both_sources().items():
        degraded, threshold, retried_floor = _answer_thresholds(source)
        assert threshold <= retried_floor, (
            f"[{label}] ELIGIBILITY_SLOW_ANSWER_SECONDS ({threshold}s) must be <= "
            f"PAYER_READ_TIMEOUT_SECONDS ({retried_floor}s), the floor cost of an "
            "answer that needed a payer retry — above it, the degrade-but-keep-"
            "answering payer this threshold exists to catch still reads as healthy "
            "and the check is dead code"
        )
        assert threshold >= degraded, (
            f"[{label}] ELIGIBILITY_SLOW_ANSWER_SECONDS ({threshold}s) must be >= "
            f"ELIGIBILITY_DEGRADED_SLOW_SECONDS ({degraded}s) — a real coverage "
            "verdict must not be judged more harshly than a reply carrying no "
            "verdict at all"
        )
