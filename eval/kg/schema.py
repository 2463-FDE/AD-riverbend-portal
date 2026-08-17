"""
Knowledge-graph schema for the w4 patient-view prototype.

Four node types and the three edges that connect them:

    Patient --has_encounter--> Encounter --seen_by--> Provider
                                   |
                                   +--produced--> Record

That chain is exactly what assembling "one patient's labs and visit summaries"
needs (w4-SPEC-1): the visit summary is a field on the encounter, the labs are
the records the encounter produced, and the provider is who the patient saw.

This is a graph over a **seeded sample corpus**, not a redescription of
db/schema.sql (w4-D-1). Two deliberate differences from the production tables:

- ``Provider`` is a node with an id. In the production schema there is no
  providers table at all — ``encounters.provider`` is free text. Modelling the
  provider as a node is the point of a knowledge graph; it is also what makes
  the third batch read (providers-by-id) meaningful.
- No PHI-carrying columns are modelled. There is no ssn, no dob, no address:
  the corpus is synthetic and the prototype has no reason to hold them.

Stdlib only, on purpose — see eval/kg/corpus.py and the kg-self-contained test.
"""
import dataclasses
from dataclasses import dataclass
from typing import Tuple

LAB_KIND = "lab"
NOTE_KIND = "note"
RECORD_KINDS = (LAB_KIND, NOTE_KIND)


@dataclass(frozen=True)
class Patient:
    """A person the graph can assemble a view for."""

    id: int
    name: str


@dataclass(frozen=True)
class Provider:
    """A clinician an encounter was seen by."""

    id: int
    name: str
    specialty: str


@dataclass(frozen=True)
class Encounter:
    """One visit. Carries the visit summary; owns its records."""

    id: int
    patient_id: int
    provider_id: int
    encounter_type: str
    reason: str
    summary: str
    occurred_at: str


@dataclass(frozen=True)
class Record:
    """One document produced by an encounter — a lab result or a note.

    ``patient_id`` is denormalised from the encounter so the ownership check
    can be argued about a record without a second hop; assembly never relies
    on it, which is why a record can never enter a view whose encounter did
    not (see eval/kg/assemble.py).
    """

    id: int
    encounter_id: int
    patient_id: int
    kind: str
    title: str
    body: str


@dataclass(frozen=True)
class Edge:
    """A declared relationship between two node types.

    ``fk_on``/``fk_attr`` name the node type that carries the foreign key and
    the field holding it, so the declaration is checkable against the
    dataclasses rather than being prose (kg-schema-shape).
    """

    name: str
    source: type
    target: type
    fk_on: type
    fk_attr: str


NODE_TYPES: Tuple[type, ...] = (Patient, Encounter, Provider, Record)

EDGES: Tuple[Edge, ...] = (
    Edge("has_encounter", Patient, Encounter, Encounter, "patient_id"),
    Edge("seen_by", Encounter, Provider, Encounter, "provider_id"),
    Edge("produced", Encounter, Record, Record, "encounter_id"),
)
