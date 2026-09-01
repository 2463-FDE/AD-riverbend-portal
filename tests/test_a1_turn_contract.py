"""
Service side of the shared POST /visit-chat turn payload declaration
(eligibility-assistant-D-45).

Same argument as `tests/test_intake_payload_contract.py`, applied to the turn: the
portal, the gateway and the assistant each grew a copy of the four closed selection
menus on this ticket, and three copies of a closed set is exactly the shape the
intake contract break had. ``contracts/visit-chat-turn.json`` is the one declaration
both suites assert against — this file for the pydantic models,
``frontend/app/assistant/turn.contract.test.ts`` for the portal's builder.
"""
import json
import pathlib

from a1_rig import assert_pinned, outcome, schemas

CONTRACT = json.loads(
    (
        pathlib.Path(__file__).resolve().parent.parent
        / "contracts"
        / "visit-chat-turn.json"
    ).read_text()
)

# The declared object name -> the pydantic model that receives it.
MODELS = {
    "root": schemas.VisitChatRequest,
    "facts": schemas.VisitFacts,
    "last_citations": schemas.Citation,
    "response": schemas.VisitChatResponse,
    "citations": schemas.RenderedCitation,
}


def test_every_declared_object_names_exactly_the_model_fields():
    assert_pinned()
    for obj, model in MODELS.items():
        declared = set(CONTRACT["request_fields"][obj])
        actual = set(model.model_fields)
        assert declared == actual, (
            f"contracts/visit-chat-turn.json declares {sorted(declared)} for "
            f"{obj}, but {model.__name__} has {sorted(actual)}"
        )


def test_the_declared_objects_are_exactly_the_ones_the_contract_covers():
    assert_pinned()
    assert set(CONTRACT["request_fields"]) == set(MODELS)


def test_the_declared_enums_are_the_service_enums():
    """The four clerk selections plus the three report sets, both directions.

    A fifth product added to `schemas.py` alone reddens here — which is the whole
    point of declaring them once (verification 17's break-then-revert).
    """
    assert_pinned()
    assert set(CONTRACT["enums"]["question_type"]) == {q.value for q in schemas.QuestionType}
    assert set(CONTRACT["enums"]["payer"]) == {p.value for p in schemas.Payer}
    assert set(CONTRACT["enums"]["product"]) == {p.value for p in schemas.Product}
    assert set(CONTRACT["enums"]["state"]) == {s.value for s in schemas.State}
    assert set(CONTRACT["enums"]["mode"]) == {m.value for m in outcome.Mode}
    assert set(CONTRACT["enums"]["reason"]) == {r.value for r in outcome.Reason}
    assert set(CONTRACT["enums"]["outcome"]) == {o.value for o in outcome.Outcome}


def test_the_sample_request_validates_against_the_schema():
    assert_pinned()
    req = schemas.VisitChatRequest.model_validate(CONTRACT["sample_request"])
    assert req.question_type is schemas.QuestionType.covered_today
    assert req.emergency is False
