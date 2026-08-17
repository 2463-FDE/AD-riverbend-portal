"""
Ownership check at the graph boundary (w4-SPEC-5..8).

These are the docs/landmines.md §3 negative tests for the prototype: the
adversarial case (a caller walking to a sibling patient's id, exactly the walk
docs/handover/portal.har captured against the production route) gets its own
test, and refusal is asserted to happen *before* any read rather than merely
to produce an empty result.

Scope, so this file is not mistaken for a guard on the live defect: the
boundary here is eval/kg/'s own, deciding against a seeded/simulated principal
(w4-D-9). The production route GET /patients/{id}/records is unchanged and
still has no session→patient bind — D11 stays open (w4-D-4, TODO-20), and its
integration xfail stays visible.

Pinned test ids: boundary-authorized-served · boundary-cross-patient-refused ·
boundary-before-traversal · boundary-simulated-principal.
"""
import sys

import pytest
from conftest import load_module

kg_schema = load_module("eval/kg/schema.py", "kg_schema")
# one identity for the node dataclasses across the package — see the same
# pinning note in tests/test_kg_prototype.py
sys.modules["schema"] = kg_schema
kg_corpus = load_module("eval/kg/corpus.py", "kg_corpus")
sys.modules["corpus"] = kg_corpus
kg_assemble = load_module("eval/kg/assemble.py", "kg_assemble")

OWN = kg_corpus.FIXTURE_PATIENT_ID
SIBLING = kg_corpus.SIBLING_PATIENT_ID


@pytest.fixture
def store():
    return kg_assemble.GraphStore(kg_corpus.build_corpus())


# --- boundary-authorized-served (w4-SPEC-5) --------------------------------


def test_boundary_authorized_served(store):
    """The patient the caller IS bound to is served."""
    view = kg_assemble.assemble_patient_view(
        store, kg_assemble.Principal.for_patient(OWN), OWN
    )
    assert view.patient_id == OWN
    assert view.encounters


# --- boundary-cross-patient-refused (w4-SPEC-6) ----------------------------


def test_boundary_cross_patient_refused(store):
    """The id walk the HAR captured — own id, then the next one — is refused,
    and no node of the sibling's graph comes back with the refusal."""
    corpus = kg_corpus.build_corpus()
    sibling_records = [r for r in corpus.records if r.patient_id == SIBLING]
    assert sibling_records, "refusal would be vacuous: sibling has nothing to leak"

    principal = kg_assemble.Principal.for_patient(OWN)
    with pytest.raises(kg_assemble.NotAuthorized) as exc:
        kg_assemble.assemble_patient_view(store, principal, SIBLING)

    # the refusal carries the requested id and nothing else — no node, no
    # count, no body text
    message = str(exc.value)
    assert exc.value.patient_id == SIBLING
    for rec in sibling_records:
        assert rec.body not in message
        assert rec.title not in message
    assert str(len(sibling_records)) not in message.replace(str(SIBLING), "")


# --- boundary-before-traversal (w4-SPEC-7) ---------------------------------


def test_boundary_before_traversal(store):
    """Refusal happens before any store read, so it cannot depend on what the
    sample contains."""
    principal = kg_assemble.Principal.for_patient(OWN)

    with pytest.raises(kg_assemble.NotAuthorized):
        kg_assemble.assemble_patient_view(store, principal, SIBLING)
    assert store.retrievals == 0

    # a patient absent from the sample refuses identically — an unauthorized
    # caller cannot tell an existing chart from a non-existent one
    absent = max(p.id for p in kg_corpus.build_corpus().patients) + 1000
    with pytest.raises(kg_assemble.NotAuthorized):
        kg_assemble.assemble_patient_view(store, principal, absent)
    assert store.retrievals == 0


# --- boundary-simulated-principal (w4-SPEC-8) ------------------------------


def test_boundary_simulated_principal(store):
    """Authorization is decided against the seeded binding handed in, not a
    gateway session (no patient principal exists — TODO-20, w4-D-9)."""
    # the same requested patient flips outcome purely on the binding
    bound_to_sibling = kg_assemble.Principal.for_patient(SIBLING)
    view = kg_assemble.assemble_patient_view(store, bound_to_sibling, SIBLING)
    assert view.patient_id == SIBLING

    with pytest.raises(kg_assemble.NotAuthorized):
        kg_assemble.assemble_patient_view(
            store, kg_assemble.Principal.for_patient(OWN), SIBLING
        )

    # the binding is explicit data on the principal, not a token or a session
    # lookup: a multi-patient binding serves both, and nothing else is consulted
    guardian = kg_assemble.Principal(
        subject="sample-guardian", patient_ids=frozenset({OWN, SIBLING})
    )
    assert guardian.may_assemble(OWN) and guardian.may_assemble(SIBLING)
    assert not kg_assemble.Principal.for_patient(OWN).may_assemble(SIBLING)
