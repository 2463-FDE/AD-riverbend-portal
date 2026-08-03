"""
Role -> capability policy for the gateway (ADR 0017).

This module is the ENFORCED copy of the policy; `config/roles.yaml` is the
DECLARED copy that ops and docs read. No runtime code parses the YAML file —
the gateway would need a new dependency plus a mounted file, and a missing or
malformed file at boot would add a failure mode for zero behavioural gain.
Instead `tests/test_gateway_authz.py` pins the two equal, so an edit to either
without the other fails the suite (same discipline as the payer-prefix catalog
and the eligibility budget alignment).

`staff` deliberately holds every capability: it is the deprecated
compatibility role every pre-RBAC `users` row carries (`users.role` defaults
to 'staff'), so existing databases keep working unchanged. Only the four real
roles can be denied anything.
"""

CAPABILITIES = frozenset(
    {
        "profile.read",
        "patients.read",
        "patients.write",
        "records.read",
        "records.write",
        "records.search",
        "billing.read",
        "eligibility.check",
        "schedule.read",
        "schedule.day_queue.read",
        "appointments.write",
        "disclosures.read",
        "disclosures.write",
        "ai.use",
        "hl7.ingest",
    }
)

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    "front_desk": frozenset(
        {
            "profile.read",
            "patients.read",
            "patients.write",
            "eligibility.check",
            "schedule.read",
            "schedule.day_queue.read",
            "appointments.write",
            "ai.use",
        }
    ),
    "clinician": frozenset(
        {
            "profile.read",
            "patients.read",
            "records.read",
            "records.search",
            "schedule.read",
        }
    ),
    "roi_clerk": frozenset(
        {
            "profile.read",
            "patients.read",
            "records.read",
            "disclosures.read",
            "disclosures.write",
        }
    ),
    "admin": CAPABILITIES,
    # Deprecated compatibility role — every pre-RBAC account. Full grant, so
    # nothing an existing database row could do before RBAC is denied now.
    "staff": CAPABILITIES,
}


def capabilities_for(role: str | None) -> frozenset[str]:
    """Resolve a session role to its capability set.

    An unknown or missing role resolves to NO capabilities — every
    capability-gated route answers 403 rather than raising or falling back to
    a default grant (fail closed).
    """
    return ROLE_CAPABILITIES.get(role or "", frozenset())
