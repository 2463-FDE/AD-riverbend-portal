"""
Data loading + identity resolution for the RAG retrieval eval (RIV-160).

Torch-free by design: everything graded (identity resolution, candidate
duplicate rate, fragment coverage) must run without ML dependencies. Embedding-based retrieval
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
    """
    One cluster of patient rows a match key unifies.

    A multi-row cluster is a *candidate* duplicate match pending human
    review, never a resolved human (ADR 0005: flag, never auto-merge).

    status:
      "unmatched" — single row; no other row shares its match key.
      "candidate" — rows share the match key AND every pair of rows in the
                    cluster has corroborating demographics; queued for human
                    review as a likely duplicate.
      "conflict"  — row shares an SSN with other rows but its demographics
                    conflict with all of them; non-mergeable, needs
                    investigation (shared/mistyped/fraudulent SSN).
      "ambiguous" — row belongs to an SSN group that chains together only
                    through bridge rows (A corroborates B, B corroborates C,
                    but A and C conflict). Corroboration does not chain, so
                    no mechanical cluster is safe: each row is emitted alone,
                    excluded from candidate counts, for human review.
    """
    key: str
    patient_ids: List[int] = field(default_factory=list)
    status: str = "unmatched"


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


def _edit_distance_leq1(a: str, b: str) -> bool:
    """True when the strings are equal or one edit (sub/ins/del) apart."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _names_similar(a: str, b: str) -> bool:
    """
    Same first initial and surnames within one edit — tolerates the drift
    seen in real intake data (Gonzalez/Gonzales, M. vs Maria) without
    accepting outright different names.
    """
    ta, tb = normalize_name(a).split(), normalize_name(b).split()
    if not ta or not tb:
        return False
    return ta[0][0] == tb[0][0] and _edit_distance_leq1(ta[-1], tb[-1])


def _dobs_compatible(a: str, b: str) -> bool:
    """Exact match, or the same date with month/day transposed (data-entry slip)."""
    if not a or not b:
        return False
    if a == b:
        return True
    pa, pb = a.split("-"), b.split("-")
    if len(pa) != 3 or len(pb) != 3:
        return False
    return pa[0] == pb[0] and pa[1] == pb[2] and pa[2] == pb[1]


def _addresses_match(a: str, b: str) -> bool:
    """
    Exact match after punctuation/case normalization. Known limitation:
    abbreviation drift ("12 Elm St" vs "12 Elm Street") does not match —
    acceptable for a corroborating signal that is one of three, never
    load-bearing alone.
    """
    na, nb = normalize_name(a), normalize_name(b)
    return bool(na) and na == nb


def _demographics_corroborate(p: Patient, q: Patient) -> bool:
    """
    At least two of three independent demographic signals must agree before
    an SSN match is trusted. One signal is not enough: family members can
    share an address (and, via fraud or error, an SSN) while being two
    different people.
    """
    signals = (
        _names_similar(p.name, q.name),
        _dobs_compatible(p.dob, q.dob),
        _addresses_match(p.address, q.address),
    )
    return sum(signals) >= 2


def _all_pairs_corroborate(rows: List[Patient]) -> bool:
    """True when every pair of rows has corroborating demographics."""
    return all(
        _demographics_corroborate(a, b)
        for i, a in enumerate(rows)
        for b in rows[i + 1:]
    )


def _split_ssn_cluster(ssn: str, rows: List[Patient]) -> List[Identity]:
    """
    An SSN is a candidate signal, not an identity (ADR 0005): rows sharing
    an SSN merge into a candidate cluster only where demographics
    corroborate — and corroboration must hold for EVERY pair in the
    cluster, not just chain through a bridge row (similarity built from
    edit-distance and transposition tolerance is not transitive). A
    connected component that is not a clique is emitted one row at a time
    as "ambiguous": picking which pair to merge would be an arbitrary,
    order-dependent choice no report should make. A row that corroborates
    with none of its SSN-mates is a conflict — same SSN, incompatible
    person. Neither is ever merged or counted as a duplicate.
    """
    components: List[List[Patient]] = []
    for p in rows:
        linked = [c for c in components if any(_demographics_corroborate(p, q) for q in c)]
        merged = [p]
        for c in linked:
            merged.extend(c)
            components.remove(c)
        components.append(merged)

    identities = []
    for comp in components:
        ids = sorted(x.id for x in comp)
        if len(comp) > 1 and _all_pairs_corroborate(comp):
            identities.append(Identity(key=ssn, patient_ids=ids, status="candidate"))
        elif len(comp) > 1:
            identities.extend(
                Identity(key=f"{ssn}:ambiguous:{i}", patient_ids=[i], status="ambiguous")
                for i in ids
            )
        elif len(rows) > 1:
            identities.append(
                Identity(key=f"{ssn}:conflict:{ids[0]}", patient_ids=ids, status="conflict")
            )
        else:
            identities.append(Identity(key=ssn, patient_ids=ids))
    return identities


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
    Group patient rows into candidate identities under a given match key.

    Multi-row clusters are candidate duplicate matches for human review,
    not resolved humans (ADR 0005: flag, never auto-merge).

    match_key:
      "none"     — intake's current behavior (intake.yaml match_key: none):
                   every row is its own identity.
      "ssn"      — group by normalized SSN, then require corroborating
                   demographics (two of: similar name, compatible DOB,
                   matching address) between EVERY pair of rows before they
                   cluster. Rows whose SSN is missing or invalid (blank,
                   non-numeric, all-zero placeholders) stay unmatched; rows
                   sharing a valid SSN whose demographics conflict are
                   flagged "conflict"; groups that only chain through a
                   bridge row are flagged "ambiguous" row-by-row. Neither is
                   ever merged — a shared or mistyped SSN must not weld two
                   real people into one record.
      "name_dob" — group by (normalized name, dob). Included to show why it
                   fails: spelling drift and DOB typos defeat exact matching.
    """
    if match_key == "none":
        return [Identity(key=str(p.id), patient_ids=[p.id]) for p in patients]

    if match_key == "ssn":
        by_ssn: Dict[str, List[Patient]] = {}
        unmatched: List[Identity] = []
        for p in patients:
            if is_valid_ssn(p.ssn):
                by_ssn.setdefault(normalize_ssn(p.ssn), []).append(p)
            else:
                unmatched.append(Identity(key=f"unmatched:{p.id}", patient_ids=[p.id]))
        identities: List[Identity] = []
        for ssn, rows in by_ssn.items():
            identities.extend(_split_ssn_cluster(ssn, rows))
        return identities + unmatched

    if match_key == "name_dob":
        groups: Dict[str, Identity] = {}
        for p in patients:
            k = f"{normalize_name(p.name)}|{p.dob}"
            groups.setdefault(k, Identity(key=k)).patient_ids.append(p.id)
        for identity in groups.values():
            identity.patient_ids.sort()
            if len(identity.patient_ids) > 1:
                identity.status = "candidate"
        return list(groups.values())

    raise ValueError(f"unknown match_key: {match_key!r}")
