"""
The seeded sample corpus the w4 prototype runs on.

Built in memory, deterministically, from the constants below — no file read,
no database, no service call (w4-D-1, w4-D-11). Two consequences worth being
explicit about:

- **No PHI.** Every name, reason, and body string here is invented for this
  prototype. Nothing is copied from db/seed/ and nothing is read from the
  records tables, so the prototype never holds a real chart even by accident.
- **The ids echo the handover capture on purpose.** 1042 is the patient the
  QA capture was logged in as and 1043 is the sibling id it walked to
  (docs/handover/portal.har, docs/research/w4-findings.md). Reusing the pair
  lets eval/kg/run.py demonstrate the refusal against the same id walk the
  finding reproduces. The ids match; the data behind them does not.

The fixture patient carries 53 encounters — over the "real chart with 50+
encounters" the owner asked about (w4-D-10) — so bounded-at-scale measures the
retrieval count on a chart the production per-encounter pattern would spend 53
queries on.
"""
from dataclasses import dataclass
from typing import Dict, List, Tuple

from schema import LAB_KIND, NOTE_KIND, Encounter, Patient, Provider, Record

FIXTURE_PATIENT_ID = 1042
FIXTURE_ENCOUNTER_COUNT = 53
SIBLING_PATIENT_ID = 1043
SIBLING_ENCOUNTER_COUNT = 2
THIRD_PATIENT_ID = 1044
THIRD_ENCOUNTER_COUNT = 5

_PROVIDERS = (
    (1, "A. Reyes", "internal medicine"),
    (2, "K. Lindqvist", "cardiology"),
    (3, "T. Adeyemi", "endocrinology"),
)

_ENCOUNTER_TYPES = ("office visit", "follow-up", "telehealth")
_REASONS = ("routine follow-up", "medication review", "lab review")

# Patients in the sample, each as (id, name, encounter count).
_PATIENTS = (
    (FIXTURE_PATIENT_ID, "Sample Patient A", FIXTURE_ENCOUNTER_COUNT),
    (SIBLING_PATIENT_ID, "Sample Patient B", SIBLING_ENCOUNTER_COUNT),
    (THIRD_PATIENT_ID, "Sample Patient C", THIRD_ENCOUNTER_COUNT),
)


@dataclass(frozen=True)
class Corpus:
    """Every node in the sample, plus the indexes the store reads through."""

    patients: Tuple[Patient, ...]
    providers: Tuple[Provider, ...]
    encounters: Tuple[Encounter, ...]
    records: Tuple[Record, ...]

    def encounters_by_patient(self) -> Dict[int, List[Encounter]]:
        index: Dict[int, List[Encounter]] = {}
        for enc in self.encounters:
            index.setdefault(enc.patient_id, []).append(enc)
        return index

    def records_by_encounter(self) -> Dict[int, List[Record]]:
        index: Dict[int, List[Record]] = {}
        for rec in self.records:
            index.setdefault(rec.encounter_id, []).append(rec)
        return index


def build_corpus() -> Corpus:
    """The sample, built the same way every call — no randomness, no I/O."""
    providers = tuple(Provider(pid, name, spec) for pid, name, spec in _PROVIDERS)
    patients = tuple(Patient(pid, name) for pid, name, _ in _PATIENTS)

    encounters: List[Encounter] = []
    records: List[Record] = []
    encounter_id = 1
    record_id = 1

    for patient_id, _, count in _PATIENTS:
        for n in range(count):
            provider = providers[n % len(providers)]
            encounters.append(
                Encounter(
                    id=encounter_id,
                    patient_id=patient_id,
                    provider_id=provider.id,
                    encounter_type=_ENCOUNTER_TYPES[n % len(_ENCOUNTER_TYPES)],
                    reason=_REASONS[n % len(_REASONS)],
                    summary=(
                        f"Visit {n + 1} for patient {patient_id}: "
                        f"{_REASONS[n % len(_REASONS)]}, seen by {provider.name}."
                    ),
                    occurred_at=f"2026-{(n % 12) + 1:02d}-{(n % 28) + 1:02d}",
                )
            )
            # one lab and one note per encounter: the two things the ask names
            # ("their labs and visit summaries"), so every encounter in the
            # sample exercises both edges out of it.
            records.append(
                Record(
                    id=record_id,
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    kind=LAB_KIND,
                    title=f"Panel {n + 1}",
                    body=f"Sample lab result {n + 1} for patient {patient_id}.",
                )
            )
            records.append(
                Record(
                    id=record_id + 1,
                    encounter_id=encounter_id,
                    patient_id=patient_id,
                    kind=NOTE_KIND,
                    title=f"Clinical note {n + 1}",
                    body=f"Sample clinician note {n + 1} for patient {patient_id}.",
                )
            )
            encounter_id += 1
            record_id += 2

    return Corpus(
        patients=patients,
        providers=providers,
        encounters=tuple(encounters),
        records=tuple(records),
    )
