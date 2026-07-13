"""
Data loading + identity resolution for the RAG retrieval eval (RIV-160).

Torch-free by design: everything graded (identity resolution, duplicate rate,
fragment coverage) must run without ML dependencies. Embedding-based retrieval
lives in retriever.py behind a lazy import.

Encounter record ids are 1-based row indexes into encounters.csv — the same
numbering the contractor's goldset.json uses in `cites_records`.
"""
import csv
import json
import re
from dataclasses import dataclass, field
from typing import Dict, List

# Values that mean "no allergy recorded", not an allergy named "none known".
_NO_ALLERGY_SENTINELS = {"", "none", "none known", "nka", "no known allergies"}


@dataclass(frozen=True)
class Patient:
    id: int
    name: str
    dob: str
    ssn: str
    address: str
    created_via: str


@dataclass(frozen=True)
class Encounter:
    record_id: int  # 1-based row index; matches goldset cites_records
    patient_id: int
    encounter_type: str
    provider: str
    summary: str
    allergies: frozenset
    medications: frozenset
    occurred_at: str


@dataclass(frozen=True)
class GoldCase:
    query: str
    expected_patient_id: int
    expected_answer: str
    cites_records: tuple


@dataclass
class Identity:
    """One resolved human; groups the patient rows a match key unifies."""
    key: str
    patient_ids: List[int] = field(default_factory=list)


def normalize_ssn(ssn: str) -> str:
    """Digits only, so hyphenated and bare forms of one SSN collapse."""
    return re.sub(r"\D", "", ssn or "")


# SSA never issues area 000/666/900-999, group 00, or serial 0000, so
# placeholders like 000-00-0000 fail this check along with blank or
# non-numeric values.
_SSN_VALID = re.compile(r"^(?!000|666|9)\d{3}(?!00)\d{2}(?!0000)\d{4}$")


def is_valid_ssn(ssn: str) -> bool:
    """True when the normalized value is a structurally issuable 9-digit SSN."""
    return bool(_SSN_VALID.match(normalize_ssn(ssn)))


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    cleaned = re.sub(r"[^\w\s]", "", (name or "").lower())
    return " ".join(cleaned.split())


def parse_clinical_list(raw: str) -> frozenset:
    """
    Split a free-text allergy/medication cell into normalized items.

    Sentinels like "none known" mean the field was assessed and empty —
    they must not survive as items (else a patient grows a phantom
    allergy called "none known").

    Known limitations, acceptable for this export but not general: the
    sentinel list is a small hardcoded English set, and splitting on
    comma/semicolon breaks item names that themselves contain commas.
    """
    items = set()
    for part in re.split(r"[;,]", raw or ""):
        item = part.strip().lower()
        if item and item not in _NO_ALLERGY_SENTINELS:
            items.add(item)
    return frozenset(items)


def load_patients(path: str) -> List[Patient]:
    with open(path, newline="") as f:
        return [
            Patient(
                id=int(row["id"]),
                name=row["name"],
                dob=row["dob"],
                ssn=row["ssn"],
                address=row["address"],
                created_via=row["created_via"],
            )
            for row in csv.DictReader(f)
        ]


def load_encounters(path: str) -> List[Encounter]:
    with open(path, newline="") as f:
        return [
            Encounter(
                record_id=i,
                patient_id=int(row["patient_id"]),
                encounter_type=row["encounter_type"],
                provider=row["provider"],
                summary=row["summary"],
                allergies=parse_clinical_list(row["allergies"]),
                medications=parse_clinical_list(row["medications"]),
                occurred_at=row["occurred_at"],
            )
            for i, row in enumerate(csv.DictReader(f), start=1)
        ]


def load_goldset(path: str) -> List[GoldCase]:
    with open(path) as f:
        payload = json.load(f)
    return [
        GoldCase(
            query=case["query"],
            expected_patient_id=case["expected_patient_id"],
            expected_answer=case["expected_answer"],
            cites_records=tuple(case["cites_records"]),
        )
        for case in payload["cases"]
    ]


def resolve_identities(patients: List[Patient], match_key: str) -> List[Identity]:
    """
    Group patient rows into humans under a given match key.

    match_key:
      "none"     — intake's current behavior (intake.yaml match_key: none):
                   every row is its own human.
      "ssn"      — group by normalized SSN. Rows whose SSN is missing or
                   invalid (blank, non-numeric, placeholders like
                   000-00-0000) stay unmatched as their own identity — a
                   shared junk value must never merge unrelated patients.
      "name_dob" — group by (normalized name, dob). Included to show why it
                   fails: spelling drift and DOB typos defeat exact matching.
    """
    if match_key == "none":
        return [Identity(key=str(p.id), patient_ids=[p.id]) for p in patients]

    def key_for(p: Patient) -> str:
        if match_key == "ssn":
            if not is_valid_ssn(p.ssn):
                return f"unmatched:{p.id}"
            return normalize_ssn(p.ssn)
        if match_key == "name_dob":
            return f"{normalize_name(p.name)}|{p.dob}"
        raise ValueError(f"unknown match_key: {match_key!r}")

    groups: Dict[str, Identity] = {}
    for p in patients:
        k = key_for(p)
        groups.setdefault(k, Identity(key=k)).patient_ids.append(p.id)
    for identity in groups.values():
        identity.patient_ids.sort()
    return list(groups.values())
