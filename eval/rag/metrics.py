"""
Graded metrics for the RAG retrieval eval (RIV-160).

Torch-free and import-light on purpose: these functions take plain data
(objects with the attributes data.py's dataclasses expose) so they unit-test
without any ML stack. The headline metrics — duplicate rate and fragment
coverage gap — need no retrieval at all.
"""
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class DuplicateRate:
    total_rows: int
    distinct_humans: int
    duplicate_rows: int
    rate: float  # duplicate_rows / total_rows


@dataclass(frozen=True)
class FragmentGap:
    """What one chart shows vs. everything known about the human it belongs to."""
    chart_id: int
    identity_patient_ids: Tuple[int, ...]
    union_allergies: frozenset
    union_medications: frozenset
    chart_allergies: frozenset
    chart_medications: frozenset

    @property
    def missed_allergies(self) -> frozenset:
        return self.union_allergies - self.chart_allergies

    @property
    def missed_medications(self) -> frozenset:
        return self.union_medications - self.chart_medications

    @property
    def is_complete(self) -> bool:
        return not self.missed_allergies and not self.missed_medications


@dataclass(frozen=True)
class RetrievalCaseScore:
    query: str
    expected_record_ids: Tuple[int, ...]
    retrieved_record_ids: Tuple[int, ...]
    recall: float
    precision: float


@dataclass(frozen=True)
class RetrievalScores:
    cases: Tuple[RetrievalCaseScore, ...]
    macro_recall: float
    macro_precision: float


def duplicate_rate(patients: Sequence, identities: Sequence) -> DuplicateRate:
    """Rows beyond one-per-human are duplicates."""
    total = len(patients)
    humans = len(identities)
    dupes = total - humans
    return DuplicateRate(
        total_rows=total,
        distinct_humans=humans,
        duplicate_rows=dupes,
        rate=(dupes / total) if total else 0.0,
    )


def chart_profile(encounters: Sequence, patient_id: int) -> Tuple[frozenset, frozenset]:
    """All allergies and medications recorded under one patient id."""
    allergies, medications = set(), set()
    for e in encounters:
        if e.patient_id == patient_id:
            allergies |= e.allergies
            medications |= e.medications
    return frozenset(allergies), frozenset(medications)


def fragment_coverage_gap(
    identity_patient_ids: Sequence[int], encounters: Sequence, chart_id: int
) -> FragmentGap:
    """
    Compare one chart against the union of all charts belonging to the same
    resolved human. Anything in the union but not on the chart is invisible
    to a clinician who opens that chart.
    """
    union_allergies, union_medications = set(), set()
    for pid in identity_patient_ids:
        a, m = chart_profile(encounters, pid)
        union_allergies |= a
        union_medications |= m
    chart_allergies, chart_medications = chart_profile(encounters, chart_id)
    return FragmentGap(
        chart_id=chart_id,
        identity_patient_ids=tuple(sorted(identity_patient_ids)),
        union_allergies=frozenset(union_allergies),
        union_medications=frozenset(union_medications),
        chart_allergies=chart_allergies,
        chart_medications=chart_medications,
    )


def retrieval_scores(
    cases: Sequence, retrieved_by_query: Dict[str, Sequence[int]]
) -> RetrievalScores:
    """
    Recall/precision of retrieved record ids against each gold case's
    cites_records, macro-averaged. This is the contractor's definition of
    success — it says nothing about whether the cited chart is complete.
    """
    scored: List[RetrievalCaseScore] = []
    for case in cases:
        expected = set(case.cites_records)
        retrieved = list(retrieved_by_query.get(case.query, ()))
        hits = expected & set(retrieved)
        scored.append(
            RetrievalCaseScore(
                query=case.query,
                expected_record_ids=tuple(sorted(expected)),
                retrieved_record_ids=tuple(retrieved),
                recall=(len(hits) / len(expected)) if expected else 0.0,
                precision=(len(hits) / len(retrieved)) if retrieved else 0.0,
            )
        )
    n = len(scored)
    return RetrievalScores(
        cases=tuple(scored),
        macro_recall=(sum(c.recall for c in scored) / n) if n else 0.0,
        macro_precision=(sum(c.precision for c in scored) / n) if n else 0.0,
    )
