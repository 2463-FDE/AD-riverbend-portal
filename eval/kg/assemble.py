"""
Retrieval over the knowledge graph: one authorized caller, one patient view.

Two things this module exists to demonstrate, both of which the production
chart route (services/records-service/app.py, DEBT D11 + D8) does the opposite
of:

1. **The ownership check is at the graph boundary.** ``assemble_patient_view``
   decides authorization as its first statement and raises before it touches
   the store at all, so a refusal cannot leak a node — not the encounter list,
   not a count, not a 404-vs-403 distinction drawn from what the sample holds
   (w4-SPEC-6/7). The check is on the *entry to the graph*, not on each read,
   which is why adding a fourth accessor later cannot open a hole around it.
2. **Retrieval is bounded.** Assembly issues exactly three batch reads —
   encounters-for-patient, records-for-encounters, providers-by-id — whatever
   the encounter count (w4-SPEC-15/16). The production route runs one records
   query per encounter; on the 53-encounter fixture that is 53 reads to this
   module's 3.

The caller→patient binding is a **seeded/simulated principal** (w4-D-9). No
patient principal exists in config/roles.yaml (TODO-20), so this deliberately
does not reach for a gateway session: ``Principal`` is handed in by whoever
constructs the run. That keeps the whole prototype outside the gateway auth
boundary — nothing here is, or claims to be, the live D11 fix.
"""
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, List, Sequence, Tuple

from schema import LAB_KIND, Encounter, Provider, Record


class NotAuthorized(Exception):
    """The caller is not bound to the patient whose graph was requested.

    Carries the requested patient id only — never a node, a count, or any hint
    of whether that patient exists in the sample.
    """

    def __init__(self, patient_id: int):
        super().__init__(f"caller is not authorized for patient {patient_id}")
        self.patient_id = patient_id


class IncompleteCorpus(Exception):
    """An encounter points at a provider the sample does not model.

    The provider accessor drops ids it cannot resolve, so the gap surfaces at
    the merge. Naming it here keeps the two halves consistent: a defective
    corpus fails with the id that is missing, rather than a bare ``KeyError``
    raised from the middle of assembly.
    """

    def __init__(self, provider_id: int):
        super().__init__(f"corpus models no provider {provider_id}")
        self.provider_id = provider_id


class MisattributedRecord(Exception):
    """A record points at an encounter of one patient but claims another.

    ``Record.patient_id`` is denormalised from the encounter (schema.py); a
    mismatch means the corpus is defective, and assembly cross-checks it at
    the merge so the defect fails loudly rather than attaching one patient's
    record to another patient's view. Carries ids only — never a record title
    or body.
    """

    def __init__(self, record_id: int, encounter_id: int):
        super().__init__(
            f"corpus misattributes record {record_id} on encounter {encounter_id}"
        )
        self.record_id = record_id
        self.encounter_id = encounter_id


@dataclass(frozen=True)
class Principal:
    """The seeded caller→patient binding the boundary decides against.

    ``patient_ids`` is a set rather than a single id so the shape survives the
    obvious next case (a guardian bound to two charts) without the boundary
    check changing.
    """

    subject: str
    patient_ids: FrozenSet[int]

    @classmethod
    def for_patient(cls, patient_id: int) -> "Principal":
        return cls(
            subject=f"sample-caller:{patient_id}",
            patient_ids=frozenset({patient_id}),
        )

    def may_assemble(self, patient_id: int) -> bool:
        return patient_id in self.patient_ids


@dataclass(frozen=True)
class AssembledEncounter:
    """One encounter with its provider resolved and its records attached."""

    encounter: Encounter
    provider: Provider
    records: Tuple[Record, ...]


@dataclass(frozen=True)
class PatientView:
    """The single result: everything one patient's graph holds for them.

    Identified by ``patient_id`` rather than a Patient node — resolving the
    node would be a fourth read for a value the caller already supplied, and
    the retrieval count is the thing this prototype is measured on.
    """

    patient_id: int
    encounters: Tuple[AssembledEncounter, ...]

    def visit_summaries(self) -> Tuple[str, ...]:
        return tuple(a.encounter.summary for a in self.encounters)

    def labs(self) -> Tuple[Record, ...]:
        return tuple(
            rec
            for a in self.encounters
            for rec in a.records
            if rec.kind == LAB_KIND
        )


class GraphStore:
    """Read access to the sample corpus, with every read counted.

    Exactly three accessors, each a **batch** read: that is what makes the
    bound in w4-SPEC-15 structural rather than a discipline the caller has to
    keep. ``retrievals`` counts accessor calls, not rows.
    """

    def __init__(self, corpus):
        self._encounters_by_patient = corpus.encounters_by_patient()
        self._records_by_encounter = corpus.records_by_encounter()
        self._providers = {p.id: p for p in corpus.providers}
        self.retrievals = 0

    def reset_retrievals(self) -> None:
        self.retrievals = 0

    def encounters_for_patient(self, patient_id: int) -> List[Encounter]:
        self.retrievals += 1
        return list(self._encounters_by_patient.get(patient_id, ()))

    def records_for_encounters(self, encounter_ids: Sequence[int]) -> List[Record]:
        """One read for all the encounters, not one per encounter — the whole
        point of the contrast with the production route."""
        self.retrievals += 1
        seen = set()
        records: List[Record] = []
        for enc_id in encounter_ids:
            if enc_id in seen:
                continue
            seen.add(enc_id)
            records.extend(self._records_by_encounter.get(enc_id, ()))
        return records

    def providers_by_id(self, provider_ids: Iterable[int]) -> Dict[int, Provider]:
        self.retrievals += 1
        return {
            pid: self._providers[pid]
            for pid in set(provider_ids)
            if pid in self._providers
        }


def assemble_patient_view(
    store: GraphStore, principal: Principal, patient_id: int
) -> PatientView:
    """Assemble ``patient_id``'s view for ``principal``, or refuse.

    The refusal is the first statement on purpose (w4-SPEC-7): everything
    below it is a read, and a check placed after even one read has already
    answered a question the caller was not entitled to ask.
    """
    if not principal.may_assemble(patient_id):
        raise NotAuthorized(patient_id)

    encounters = store.encounters_for_patient(patient_id)
    records = store.records_for_encounters([e.id for e in encounters])
    providers = store.providers_by_id(e.provider_id for e in encounters)

    records_by_encounter: Dict[int, List[Record]] = {}
    for rec in records:
        if rec.patient_id != patient_id:
            raise MisattributedRecord(rec.id, rec.encounter_id)
        records_by_encounter.setdefault(rec.encounter_id, []).append(rec)

    assembled = tuple(
        AssembledEncounter(
            encounter=enc,
            provider=_resolve_provider(providers, enc.provider_id),
            records=tuple(records_by_encounter.get(enc.id, ())),
        )
        for enc in encounters
    )
    return PatientView(patient_id=patient_id, encounters=assembled)


def _resolve_provider(providers: Dict[int, Provider], provider_id: int) -> Provider:
    try:
        return providers[provider_id]
    except KeyError:
        raise IncompleteCorpus(provider_id) from None
