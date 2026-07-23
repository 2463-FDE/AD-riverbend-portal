"""
Cross-service invariant (ADR 0010): eligibility-service's worst-case payer budget
must finish before intake-service gives up on it, so intake receives the graceful
degraded answer ("unknown"/"inactive") rather than timing out first and abandoning
a still-running downstream call (which would waste a retry and pin a worker).

Guards the checked-in defaults and any future change to either side. Red against
the pre-fix defaults, where the payer budget (2+3)*2 = 10s exceeded intake's 6s.
"""
from conftest import load_module

_elig = load_module("services/eligibility-service/config.py", "elig_config_budget").settings
_intake = load_module("services/intake-service/config.py", "intake_config_budget").settings

MARGIN_SECONDS = 1.0


def _payer_worst_case_seconds():
    per_attempt = _elig.payer_connect_timeout_seconds + _elig.payer_read_timeout_seconds
    attempts = _elig.payer_max_retries + 1
    return per_attempt * attempts


def test_payer_budget_fits_within_intake_timeout():
    inner = _payer_worst_case_seconds()
    outer = _intake.eligibility_timeout_seconds
    assert inner < outer, (
        f"payer worst-case {inner}s must be < intake eligibility timeout {outer}s, "
        "or intake abandons a still-running eligibility call"
    )
    assert outer - inner >= MARGIN_SECONDS, (
        f"need >= {MARGIN_SECONDS}s margin between payer worst-case ({inner}s) "
        f"and intake timeout ({outer}s); got {outer - inner}s"
    )
