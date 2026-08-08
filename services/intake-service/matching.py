"""
Duplicate-patient match key (ADR 0005, tier 1: SSN + corroborating demographics).

Copy-pasted per service — there is no shared Python library (ADR 0001). The
intake-service and records-service copies are kept BYTE-IDENTICAL and
tests/test_matching_parity.py enforces it; apply every edit to both.

Semantics are ported from eval/rag/data.py, which measured the candidate
duplicate rate published in eval/rag/REPORT.md. The serving matcher must agree
with the harness row for row, or the report describes a system that no longer
exists. Ported: normalize_ssn / is_valid_ssn / normalize_name, the name, DOB and
address comparators, _demographics_corroborate, and — the load-bearing part —
the connected-component split and per-component classification of
_split_ssn_cluster. resolve_identities itself is NOT ported: it is only the
driver loop over SSN groups and carries none of the semantics.

Tier 2 (fuzzy name + DOB where the SSN is missing or invalid) is deliberately
NOT ported. W2's detection floor is the SSN-corroborated tier by owner decision,
so a row without a usable SSN yields no candidate, no disclosure, and no queue
entry (W2-SPEC-20).

PHI: SSN values live in local variables only. Nothing this module returns —
component dicts, pairs, statuses — contains a name, DOB, address, or SSN, because
every one of those return values flows into a log line or an API response
downstream (W2-SPEC-24).
"""
import re
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Tuple

# One row's classification within its SSN group. Never a whole-group verdict:
# one SSN can carry a corroborating clique AND rows that corroborate with
# nobody, and a single verdict cannot express that (W2-SPEC-21).
CANDIDATE = "candidate"
AMBIGUOUS = "ambiguous"
CONFLICT = "conflict"
NONE = "none"


def normalize_ssn(ssn: str) -> str:
    """Digits only, so hyphenated and bare forms of one SSN collapse."""
    return re.sub(r"\D", "", ssn or "")


# SSA never issues area 000/666/900-999, group 00, or serial 0000, so
# placeholders like 000-00-0000 fail this check along with blank or
# non-numeric values. Without it, a common junk value becomes a shared match
# key and welds unrelated patients into one candidate duplicate.
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


def _name_agreement(a: str, b: str) -> str:
    """
    How strongly two names agree, once surnames are within one edit:

      "strong" — both first names are full and themselves within one edit
                 (Maria/Marie, Gonzalez/Gonzales); genuine same-name drift.
      "weak"   — first names agree only through a bare initial, i.e. one side
                 is a single letter matching the other's first letter
                 (M. vs Maria). Consistent, but a weak signal on its own.
      "none"   — surnames differ, or two *full* first names differ beyond one
                 edit even when they share an initial (John vs Jane). A shared
                 initial is NOT a match when both names are spelled out.

    Two different people (John Smith / Jane Smith) must land in "none": a
    shared first initial is drift only when the longer name could plausibly
    be the same person written short, never when both are full and distinct.
    """
    ta, tb = normalize_name(a).split(), normalize_name(b).split()
    if not ta or not tb:
        return "none"
    if not _edit_distance_leq1(ta[-1], tb[-1]):
        return "none"
    fa, fb = ta[0], tb[0]
    if len(fa) == 1 or len(fb) == 1:
        return "weak" if fa[0] == fb[0] else "none"
    return "strong" if _edit_distance_leq1(fa, fb) else "none"


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


def _field(row: Any, name: str) -> str:
    """Read one field off a row that may be a mapping or an ORM object.

    Callers hand this module SQLAlchemy result rows (``RowMapping`` — a Mapping
    but not a dict); tests and the eval fixtures hand it plain dicts and
    dataclasses. All of them must exercise the same code path, or the unit
    tests stop describing what the services run.
    """
    if isinstance(row, Mapping):
        value = row.get(name)
    else:
        value = getattr(row, name, None)
    return "" if value is None else str(value)


def _row_id(row: Any) -> int:
    return int(row["id"] if isinstance(row, Mapping) else row.id)


def _demographics_corroborate(p: Any, q: Any) -> bool:
    """
    Two independent demographic signals must agree before an SSN match is
    trusted, and a name only counts as one of them when it is a *strong*
    match (full first names that agree). One signal is never enough: family
    members share an address (and, via fraud or error, an SSN) while being
    two different people.

    A weak name match (initial-only) or no name match cannot pair with a
    single other signal — it needs BOTH DOB and address. So "same initial +
    same DOB, different address" (John/Jane Smith) does not corroborate: the
    name evidence is too weak to trust a shared SSN over a differing address.
    """
    strong_name = _name_agreement(_field(p, "name"), _field(q, "name")) == "strong"
    dob = _dobs_compatible(_field(p, "dob"), _field(q, "dob"))
    addr = _addresses_match(_field(p, "address"), _field(q, "address"))
    return (strong_name and (dob or addr)) or (dob and addr)


def _all_pairs_corroborate(rows: List[Any]) -> bool:
    """True when every pair of rows has corroborating demographics."""
    return all(
        _demographics_corroborate(a, b)
        for i, a in enumerate(rows)
        for b in rows[i + 1:]
    )


def _split_one_ssn_group(rows: List[Any]) -> List[Dict[str, Any]]:
    """
    Classify the rows sharing one normalized, valid SSN.

    An SSN is a candidate signal, not an identity (ADR 0005): rows sharing an
    SSN cluster only where demographics corroborate — and corroboration must
    hold for EVERY pair in the cluster, not merely chain through a bridge row
    (similarity built from edit-distance and transposition tolerance is not
    transitive). So the rows are first split into connected components under
    corroboration, then each component is classified on its own:

      * a component of >= 2 rows that is a clique  -> "candidate"
      * a component of >= 2 rows that is not       -> "ambiguous", one row at a
        time; picking which pair to merge would be an arbitrary, order-dependent
        choice no queue entry should encode
      * a single row inside a multi-row SSN group  -> "conflict" (non-mergeable:
        same SSN, incompatible person — shared, mistyped, or fraudulent)

    A single-row SSN group has nothing to compare against and yields no
    component at all.
    """
    if len(rows) < 2:
        return []

    components: List[List[Any]] = []
    for p in rows:
        linked = [c for c in components if any(_demographics_corroborate(p, q) for q in c)]
        merged = [p]
        for c in linked:
            merged.extend(c)
            components.remove(c)
        components.append(merged)

    out: List[Dict[str, Any]] = []
    for comp in components:
        ids = sorted(_row_id(x) for x in comp)
        if len(comp) > 1 and _all_pairs_corroborate(comp):
            out.append({"patient_ids": ids, "status": CANDIDATE})
        elif len(comp) > 1:
            out.extend({"patient_ids": [i], "status": AMBIGUOUS} for i in ids)
        else:
            out.append({"patient_ids": ids, "status": CONFLICT})
    return out


def classify_ssn_group(rows: Iterable[Any]) -> List[Dict[str, Any]]:
    """
    Classify patient rows into components, one entry per component:
    ``{"patient_ids": [int], "status": "candidate" | "ambiguous" | "conflict"}``.

    Rows without a usable SSN, and rows that are alone under their SSN, produce
    no component — there is nothing to disclose or queue for them.

    Callers prefilter by normalized SSN in SQL, but this does not rely on that:
    handed a mixed set it groups by normalized SSN first and classifies each
    group independently, so a broken prefilter can never weld two SSN groups
    into one candidate pair. Components are returned in ascending patient-id
    order so the output is stable across query orderings.
    """
    by_ssn: Dict[str, List[Any]] = {}
    for row in rows:
        raw = _field(row, "ssn")
        if is_valid_ssn(raw):
            by_ssn.setdefault(normalize_ssn(raw), []).append(row)

    out: List[Dict[str, Any]] = []
    for group in by_ssn.values():
        out.extend(_split_one_ssn_group(group))
    out.sort(key=lambda c: c["patient_ids"])
    return out


def candidate_pairs(rows: Iterable[Any]) -> List[Tuple[int, int]]:
    """
    Ordered ``(a, b)`` pairs with ``a < b``, drawn from candidate components
    only.

    Ambiguous and conflict rows contribute nothing, and no pair ever spans two
    components (W2-SPEC-21) — which is exactly why this is derived from
    components rather than from the SSN group.
    """
    pairs: List[Tuple[int, int]] = []
    for component in classify_ssn_group(rows):
        if component["status"] != CANDIDATE:
            continue
        ids = component["patient_ids"]
        pairs.extend((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    pairs.sort()
    return pairs


def status_for(rows: Iterable[Any], patient_id: int) -> str:
    """
    The status of the component CONTAINING ``patient_id`` — the disclosure
    predicate — or ``"none"`` when the row has no usable SSN, no SSN-mates, or
    is not in ``rows`` at all.

    Asking "does this SSN group classify candidate?" instead would be wrong for
    a mixed group in both directions: it would suppress the disclosure the
    clique's members are owed, or assert one over a row that corroborates with
    nobody.
    """
    for component in classify_ssn_group(rows):
        if patient_id in component["patient_ids"]:
            return component["status"]
    return NONE
