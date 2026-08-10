"""Service side of the shared POST /intake payload declaration (E4-SPEC-19, E4-SPEC-20, E4-SPEC-21).

The intake contract break got past a green build because nothing compared the
two ends of this boundary: the portal sent `demographics.first_name` /
`insurance.carrier` / a consents OBJECT, intake's schema wanted
`demographics.name` / `insurance.payer_name` / a consents LIST, and both sides
had passing tests of their own.

contracts/intake-registration.json is the one declaration both suites assert
against — this file for the pydantic models, frontend/app/intake/payload.contract
.test.ts for the portal's builder. Either side drifting reddens its own CI job,
and both jobs gate docker-build (.github/workflows/ci.yml).
"""
import json
import pathlib
import sys

from conftest import load_module

_SIBLINGS = ("config", "db", "logging_config", "models", "schemas")
_saved = {name: sys.modules.pop(name, None) for name in _SIBLINGS}
schemas = load_module("services/intake-service/schemas.py", "intake_schemas_contract")
for _name, _module in _saved.items():
    if _module is not None:
        sys.modules[_name] = _module
    else:
        sys.modules.pop(_name, None)

CONTRACT = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "contracts"
        / "intake-registration.json"
    ).read_text()
)

# The declared object name -> the pydantic model that receives it.
MODELS = {
    "root": schemas.IntakeRequest,
    "demographics": schemas.Demographics,
    "insurance": schemas.Insurance,
}


def test_every_declared_object_names_exactly_the_model_fields():
    """Both directions, per object — the assertion that actually matters.

    IntakeRequest does not forbid extra keys, so validating the sample alone
    would have accepted `insurance.carrier` and dropped it silently, which is
    exactly how the live defect stayed invisible. A field the declaration is
    missing is just as bad: the portal would be free to stop sending it.
    """
    for obj, model in MODELS.items():
        declared = set(CONTRACT["request_fields"][obj])
        actual = set(model.model_fields)
        assert declared == actual, (
            f"contracts/intake-registration.json declares {sorted(declared)} for "
            f"{obj}, but {model.__name__} has {sorted(actual)}"
        )


def test_the_declared_objects_are_exactly_the_ones_the_contract_covers():
    assert set(CONTRACT["request_fields"]) == set(MODELS)


def test_the_sample_request_validates_against_the_schema():
    req = schemas.IntakeRequest.model_validate(CONTRACT["sample_request"])
    assert req.demographics.name
    assert req.insurance is not None


def test_the_declared_consent_vocabulary_is_the_enum(  # E4-SPEC-9, service side
):
    assert set(CONTRACT["consent_kinds"]) == {k.value for k in schemas.ConsentKind}


def test_every_portal_omission_is_optional_in_the_schema():
    """`portal_omits` records what the portal legitimately does not collect. It
    must never become an escape hatch for a required field — a required key
    declared omittable would let the portal drop it and the contract test still
    pass, which is the defect's own shape."""
    for obj, omitted in CONTRACT["portal_omits"].items():
        model = MODELS[obj]
        for field_name in omitted:
            assert field_name in model.model_fields, (
                f"{obj}.{field_name} is declared omitted but is not a field of "
                f"{model.__name__}"
            )
            assert not model.model_fields[field_name].is_required(), (
                f"{obj}.{field_name} is REQUIRED by {model.__name__} — it cannot be "
                "declared omittable by the portal"
            )


def test_the_sample_request_carries_no_seeded_identifiers():
    """The declaration is committed and read by two suites, so its sample must
    stay synthetic — a real-looking SSN or member id here would be a PHI-shaped
    literal in the tree with no clinical reason to exist."""
    blob = json.dumps(CONTRACT["sample_request"])
    assert "example" in blob.lower()
    assert CONTRACT["sample_request"]["demographics"]["ssn"] == "000000000"
