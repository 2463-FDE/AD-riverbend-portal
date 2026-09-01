"""
policy_index — the eligibility assistant's bounded, deterministic policy corpus
(eligibility-assistant, ADR 0019).

One loader, one index, one ordering site. `load()` is the only reader of
`policy_corpus/document-manifest.json`: it walks the whole `policy_corpus/` tree, requires
every file to be either one of the two named root files or a manifest row whose sha256
matches (`.DS_Store` is the single exempt name, at any depth), requires every manifest
row to be `approved`, and builds exactly one row per document — the manifest's own
fields plus the whole vendored file, never a heading split
(eligibility-assistant-D-61). A mismatch, an unlisted file or a non-approved row raises
`CorpusLoadError` before any lookup; `app.py` calls `load()` in its lifespan hook so the
container fails at boot, and `policy_tool` calls `categories()` at import so the CI
import smoke fails ahead of the hook.

The retriever is in-process, read-only and makes no network call. Query values are
closed enum members (`PAYERS`, `PRODUCTS`, `STATES`; `unconfirmed` is non-filtering on
product and state — eligibility-assistant-D-32); `*` is an INDEX-row value that matches
any query value and is never legal on the query side (eligibility-assistant-D-64).
`rank(rows)` is the one ordering site — its unit is `default_ranker`: tier rank asc,
`retrieval_date` desc, `document_id` asc (eligibility-assistant-D-62) — and `lookup`
applies it before the `A1_RETRIEVAL_MAX_ROWS` cut. A caller may substitute the unit with
`rank(rows, ranker=...)`, which changes the order of a filtered set and never its
membership (eligibility-assistant-SPEC-66).

Every lookup leaves a `LookupRecord` (eligibility-assistant-SPEC-63): the resolved value
of each filter axis with its provenance, the pre-filter / post-filter / returned counts,
the cap, and the `truncated` / `empty` flags. `lookup` and `fetch_by_id` return it
alongside the rows and emit it once as one structured log line — closed fields only, and
the log line is the record's only emitter in this item (eligibility-assistant-D-68). A
caller that names no provenance records `application_default` on every axis, so the
record is left for every caller, tool-bound or direct (eligibility-assistant-D-69).

Module state is published by the default root only: `load()` with no `root` sets
`_INDEX` and `MAX_ROW_BYTES`; `load(root=...)` returns the index it built and leaves
module state untouched, so a test's `tmp_path` variant can never repoint `lookup` for a
later test file (eligibility-assistant-D-57).
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Tuple, Union

from config import settings
from logging_config import configure

log = configure(settings.service_name)

__all__ = [
    "CorpusLoadError",
    "Row",
    "Index",
    "LookupRecord",
    "PROVENANCE_LABELS",
    "RECORD_LOG_MESSAGE",
    "PAYERS",
    "PRODUCTS",
    "STATES",
    "QUESTION_TYPES",
    "PROMPT_RESERVE_BYTES",
    "MAX_ROW_BYTES",
    "load",
    "categories",
    "lookup",
    "fetch_by_id",
    "needs_product_confirmation",
    "tier",
    "rank",
    "default_ranker",
]

DEFAULT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy_corpus")
MANIFEST_NAME = "document-manifest.json"
INDEX_NAME = "index.json"
ROOT_FILES = frozenset({MANIFEST_NAME, INDEX_NAME})
EXEMPT_NAME = ".DS_Store"
WILDCARD = "*"
UNCONFIRMED = "unconfirmed"

# The closed enums of eligibility-assistant-D-36. `payer` has no `unconfirmed`: the
# clerk always selects one. `product` / `state` `unconfirmed` is non-filtering.
QUESTION_TYPES: Tuple[str, ...] = (
    "covered_today",
    "will_it_pay",
    "in_network",
    "referral_needed",
    "prior_auth",
    "who_pays_first",
    "copay",
    "portal_down",
    "emergency",
)
PAYERS: Tuple[str, ...] = (
    "unitedhealthcare",
    "aetna",
    "cigna",
    "humana",
    "anthem_blue",
    "medicare",
    "medicaid",
)
PRODUCTS: Tuple[str, ...] = (
    "commercial",
    "medicare_advantage",
    "medicaid_mco",
    "chip",
    "original_medicare",
    UNCONFIRMED,
)
STATES: Tuple[str, ...] = ("CA", "other_us", UNCONFIRMED)

# Bytes `turn` may spend on system prompt, tool schema and the turn's own messages
# across both model calls; the row cap is sized so cap × MAX_ROW_BYTES + this reserve
# fits inside LLM_MAX_INPUT_TOKENS (eligibility-assistant-D-64).
PROMPT_RESERVE_BYTES = 5000

# Tier rule (eligibility-assistant-D-38, amendment note 2): license class × category.
_PUBLIC_DOMAIN_PREFIX = "US Government work; public domain"
_CITATION_ONLY_PREFIX = "Citation-only"
_SYNTHETIC_PREFIX = "Original synthetic training material"
_TIER_1_CATEGORIES = frozenset({"emergency-care-boundary", "privacy-minimum-necessary"})
_TIER_5_CATEGORY = "payer-training-summary"


class CorpusLoadError(RuntimeError):
    """The vendored corpus is not exactly the manifest's approved rows."""


@dataclass(frozen=True)
class Row:
    """One retrievable document — the six values that egress in a model payload."""

    id: str
    title: str
    section: str
    version: str
    retrieval_date: str
    section_text: str

    _KEYS = ("id", "title", "section", "version", "retrieval_date", "section-text")

    def __getitem__(self, key: str) -> str:
        if key == "section-text":
            return self.section_text
        if key in self._KEYS:
            return getattr(self, key)
        raise KeyError(key)

    def as_dict(self) -> Dict[str, str]:
        return {key: self[key] for key in self._KEYS}

    def byte_total(self) -> int:
        return sum(len(self[key].encode("utf-8")) for key in self._KEYS)


@dataclass(frozen=True)
class Entry:
    """One curated `index.json` entry — the filter axes for a row (never egresses)."""

    topics: Tuple[str, ...]
    payers: Union[str, Tuple[str, ...]]
    products: Union[str, Tuple[str, ...]]
    states: Union[str, Tuple[str, ...]]
    needs_product_confirmation: bool
    tier: int
    category: str
    license_disposition: str


@dataclass(frozen=True)
class Index:
    """What one `load()` returns: the rows, the manifest-wide categories, the axes."""

    rows: Tuple[Row, ...]
    categories: Tuple[str, ...]
    entries: Mapping[str, Entry]
    root: str

    def row(self, doc_id: str) -> Optional[Row]:
        for row in self.rows:
            if row.id == doc_id:
                return row
        return None


# The three-value provenance set of eligibility-assistant-SPEC-63. `application_default`
# is what an axis records when the caller names no provenance for it, so a direct module
# call leaves a complete record without knowing the tool exists (D-69).
PROVENANCE_LABELS: Tuple[str, ...] = ("clerk_selection", "model_topic", "application_default")
APPLICATION_DEFAULT = "application_default"

# The one structured line the record is emitted on (eligibility-assistant-D-68).
RECORD_LOG_MESSAGE = "policy lookup record=%s"

_AXES: Tuple[str, ...] = ("topic", "payer", "product", "state")


@dataclass(frozen=True)
class LookupRecord:
    """One lookup's metadata — fourteen closed fields, never any document or clerk text.

    Per axis the resolved value (`str | None`; `None` is the by-id path, which has no
    filter axes) and a label from `PROVENANCE_LABELS`; the row counts before and after
    filtering, the rows returned and the cap in force; and the two flags. There is no
    field that can carry a section text, a title, a path, a clerk message or a member id
    (eligibility-assistant-SPEC-63, §1 approval eligibility-assistant-D-56 as extended).
    """

    topic: Optional[str]
    topic_provenance: str
    payer: Optional[str]
    payer_provenance: str
    product: Optional[str]
    product_provenance: str
    state: Optional[str]
    state_provenance: str
    pre_filter_rows: int
    post_filter_rows: int
    returned_rows: int
    cap: int
    truncated: bool
    empty: bool

    def as_dict(self) -> Dict[str, Union[str, int, bool, None]]:
        return asdict(self)


def _provenance_of(provenance: Optional[Mapping[str, str]], axis: str) -> str:
    """The axis's label, or `application_default` when the caller named none."""
    label = (provenance or {}).get(axis, APPLICATION_DEFAULT)
    if label not in PROVENANCE_LABELS:
        raise ValueError("provenance label is not one of the three")
    return label


def _emit(record: LookupRecord) -> LookupRecord:
    """Emit the record as one structured log line — the record's only emitter."""
    try:
        log.info(RECORD_LOG_MESSAGE, json.dumps(record.as_dict()))
    except Exception as e:  # a record that cannot serialise must not break a lookup
        log.error("policy lookup record not emitted (%s)", type(e).__name__)
    return record


_INDEX: Optional[Index] = None
MAX_ROW_BYTES: Optional[int] = None


# --- loading --------------------------------------------------------------------


def _license_class(license_disposition: str) -> str:
    if license_disposition.startswith(_PUBLIC_DOMAIN_PREFIX):
        return "public_domain"
    if license_disposition.startswith(_CITATION_ONLY_PREFIX):
        return "citation_only"
    if license_disposition.startswith(_SYNTHETIC_PREFIX):
        return "synthetic"
    raise CorpusLoadError("unknown license_disposition class")


def _tier_of(license_disposition: str, category: str) -> int:
    klass = _license_class(license_disposition)
    if klass == "public_domain":
        return 1 if category in _TIER_1_CATEGORIES else 2
    if klass == "citation_only":
        return 3
    return 5 if category == _TIER_5_CATEGORY else 4


def _axis(value, enum: Tuple[str, ...], field: str, doc_id: str):
    if value == WILDCARD:
        return WILDCARD
    if not isinstance(value, list) or not value:
        raise CorpusLoadError(f"index.json {field} must be a non-empty list or '*' ({doc_id})")
    for member in value:
        if member not in enum or member == UNCONFIRMED:
            raise CorpusLoadError(f"index.json {field} value outside the enum ({doc_id})")
    return tuple(value)


def _walk(root: str) -> Iterator[str]:
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            yield os.path.relpath(os.path.join(dirpath, name), root)


def _read_json(path: str):
    with open(path, "rb") as fh:
        raw = fh.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise CorpusLoadError(f"unreadable {os.path.basename(path)} ({type(e).__name__})") from e


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def load(root: Optional[str] = None) -> Index:
    """Read, verify and index the corpus under `root` (default: the service's own).

    Raises `CorpusLoadError` on a sha mismatch, an unlisted file at any depth, a missing
    file, a non-`approved` manifest row, or an index entry that does not match the
    manifest. Only the default-root load publishes `_INDEX` / `MAX_ROW_BYTES`.
    """
    global _INDEX, MAX_ROW_BYTES
    publish = root is None
    root = os.path.abspath(DEFAULT_ROOT if root is None else root)
    manifest_path = os.path.join(root, MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        raise CorpusLoadError("manifest missing")
    manifest = _read_json(manifest_path)
    documents = manifest.get("documents") if isinstance(manifest, dict) else None
    if not isinstance(documents, list) or not documents:
        raise CorpusLoadError("manifest has no documents")

    by_path: Dict[str, dict] = {}
    for doc in documents:
        doc_id = doc.get("document_id")
        if not doc_id or doc.get("approval_status") != "approved":
            raise CorpusLoadError(f"manifest row not approved ({doc_id})")
        rel = doc.get("path")
        if not rel or rel in by_path:
            raise CorpusLoadError(f"manifest row path missing or duplicated ({doc_id})")
        by_path[os.path.normpath(rel)] = doc

    # SPEC-7: every file under the tree is a named root file or a pinned manifest row.
    seen = set()
    for rel in _walk(root):
        if os.path.basename(rel) == EXEMPT_NAME:
            continue
        if rel in ROOT_FILES:
            continue
        doc = by_path.get(os.path.normpath(rel))
        if doc is None:
            raise CorpusLoadError(f"unlisted file under the corpus ({rel})")
        if _sha256(os.path.join(root, rel)) != doc.get("content_sha256"):
            raise CorpusLoadError(f"sha256 mismatch ({doc['document_id']})")
        seen.add(os.path.normpath(rel))
    missing = set(by_path) - seen
    if missing:
        raise CorpusLoadError(f"manifest rows with no vendored file ({len(missing)})")

    index_path = os.path.join(root, INDEX_NAME)
    if not os.path.isfile(index_path):
        raise CorpusLoadError("index.json missing")
    raw_entries = _read_json(index_path)
    if not isinstance(raw_entries, list):
        raise CorpusLoadError("index.json is not a list")
    entries_by_id: Dict[str, dict] = {}
    for raw in raw_entries:
        doc_id = raw.get("document_id") if isinstance(raw, dict) else None
        if not doc_id or doc_id in entries_by_id:
            raise CorpusLoadError(f"index.json entry missing or duplicated ({doc_id})")
        entries_by_id[doc_id] = raw

    rows: List[Row] = []
    entries: Dict[str, Entry] = {}
    for rel, doc in by_path.items():
        doc_id = doc["document_id"]
        raw = entries_by_id.pop(doc_id, None)
        if raw is None:
            raise CorpusLoadError(f"approved row absent from index.json ({doc_id})")
        topics = raw.get("topics")
        if not isinstance(topics, list) or doc["category"] not in topics:
            raise CorpusLoadError(f"index.json topics do not carry the manifest category ({doc_id})")
        with open(os.path.join(root, rel), "rb") as fh:
            text = fh.read().decode("utf-8")
        rows.append(
            Row(
                id=doc_id,
                title=doc["title"],
                section=doc["section_labels"],
                version=doc["version_effective"],
                retrieval_date=doc["retrieval_date"],
                section_text=text,
            )
        )
        entries[doc_id] = Entry(
            topics=tuple(topics),
            payers=_axis(raw.get("payers"), PAYERS, "payers", doc_id),
            products=_axis(raw.get("products"), PRODUCTS, "products", doc_id),
            states=_axis(raw.get("states"), STATES, "states", doc_id),
            needs_product_confirmation=bool(raw.get("needs_product_confirmation", False)),
            tier=_tier_of(doc["license_disposition"], doc["category"]),
            category=doc["category"],
            license_disposition=doc["license_disposition"],
        )
    if entries_by_id:
        raise CorpusLoadError(f"index.json entries with no approved row ({len(entries_by_id)})")

    index = Index(
        rows=tuple(rows),
        categories=tuple(sorted({doc["category"] for doc in by_path.values()})),
        entries=entries,
        root=root,
    )
    if publish:
        _INDEX = index
        MAX_ROW_BYTES = max(row.byte_total() for row in index.rows)
    return index


def categories(root: Optional[str] = None) -> Tuple[str, ...]:
    """The sorted, manifest-wide category tuple — the model-facing `topic` enum."""
    return load(root=root).categories


def _current() -> Index:
    """The default-root index, loading it lazily for direct module callers."""
    return _INDEX if _INDEX is not None else load()


# --- retrieval ------------------------------------------------------------------


def _check_enum(value: str, enum: Tuple[str, ...], axis: str) -> None:
    if not isinstance(value, str) or value not in enum:
        raise ValueError(f"{axis} is not an enum member")


def _matches(row_values: Union[str, Tuple[str, ...]], query: str) -> bool:
    if query == UNCONFIRMED or row_values == WILDCARD:
        return True
    return query in row_values


def _filter(topic: str, payer: str, product: str, state: str, index: Optional[Index] = None) -> Iterator[Row]:
    """Candidate rows for the argument set, in index order, uncapped and unranked."""
    index = _current() if index is None else index
    _check_enum(topic, index.categories, "topic")
    _check_enum(payer, PAYERS, "payer")
    _check_enum(product, PRODUCTS, "product")
    _check_enum(state, STATES, "state")
    for row in index.rows:
        entry = index.entries[row.id]
        if topic not in entry.topics:
            continue
        if not _matches(entry.payers, payer):
            continue
        if not _matches(entry.products, product):
            continue
        if not _matches(entry.states, state):
            continue
        yield row


def needs_product_confirmation(document: Union[str, Row]) -> bool:
    """Whether a row's manifest entry is flagged as needing product confirmation.

    A named accessor rather than a reach into `entries`, which is outside `__all__`.
    """
    # Duck-typed on `.id`, not `isinstance(document, Row)`: the rig stands rows in
    # as `SimpleNamespace(id=...)`.
    doc_id = getattr(document, "id", document)
    entry = _current().entries.get(doc_id)
    if entry is None:
        raise ValueError("unknown document id")
    return bool(entry.needs_product_confirmation)


def tier(document: Union[str, Mapping[str, str], Row]) -> int:
    """The eligibility-assistant-D-38 tier: license_disposition prefix × category.

    Accepts a manifest row mapping, a loaded `Row`, or a document id (resolved through
    the loaded index).
    """
    if isinstance(document, Mapping):
        return _tier_of(document["license_disposition"], document["category"])
    doc_id = document.id if isinstance(document, Row) else document
    entry = _current().entries.get(doc_id)
    if entry is None:
        raise ValueError("unknown document id")
    return entry.tier


def default_ranker(rows: Iterable[Row]) -> List[Row]:
    """The ranking unit: tier rank asc, `retrieval_date` desc, `document_id` asc.

    A total order on closed manifest fields — no `version_effective` parse, which is
    prose on every row (eligibility-assistant-D-62).
    """
    index = _current()

    def _key(row: Row):
        entry = index.entries.get(row.id)
        row_tier = entry.tier if entry is not None else tier(row)
        return (row_tier, _desc(row.retrieval_date), row.id)

    return sorted(rows, key=_key)


def rank(
    rows: Iterable[Row],
    *,
    ranker: Optional[Callable[[Iterable[Row]], List[Row]]] = None,
) -> List[Row]:
    """The one ordering site, separate from filtering (eligibility-assistant-SPEC-66).

    `ranker` substitutes the ranking unit without patching this function; it defaults to
    `default_ranker`. Substitution changes the order and never the membership: the unit's
    output is checked against its input as a multiset of document ids, so a unit that
    drops, adds or duplicates a row raises rather than silently thinning the citations
    the caller then caps.
    """
    candidates = list(rows)
    ordered = list((ranker or default_ranker)(candidates))
    if sorted(row.id for row in ordered) != sorted(row.id for row in candidates):
        raise ValueError("ranking unit changed membership")
    return ordered


def _desc(date: str) -> Tuple[int, ...]:
    # ISO dates sort lexically; negate each code point so newest comes first
    return tuple(-ord(ch) for ch in date)


def _cap() -> int:
    return max(1, int(settings.a1_retrieval_max_rows))


def lookup(
    topic: str,
    payer: str,
    product: str,
    state: str,
    *,
    provenance: Optional[Mapping[str, str]] = None,
) -> Tuple[List[Row], LookupRecord]:
    """The retriever: filter, rank, cut at `A1_RETRIEVAL_MAX_ROWS`. In-process, read-only.

    Returns the rows and the `LookupRecord` they left (eligibility-assistant-SPEC-63).
    `provenance` is an optional axis → label mapping; every axis it omits records
    `application_default`.
    """
    index = _current()
    candidates = list(_filter(topic, payer, product, state, index))
    cap = _cap()
    rows = rank(candidates)[:cap]
    return rows, _emit(
        LookupRecord(
            topic=topic,
            topic_provenance=_provenance_of(provenance, "topic"),
            payer=payer,
            payer_provenance=_provenance_of(provenance, "payer"),
            product=product,
            product_provenance=_provenance_of(provenance, "product"),
            state=state,
            state_provenance=_provenance_of(provenance, "state"),
            pre_filter_rows=len(index.rows),
            post_filter_rows=len(candidates),
            returned_rows=len(rows),
            cap=cap,
            truncated=len(candidates) > cap,
            empty=not candidates,
        )
    )


def fetch_by_id(ids: Iterable[str]) -> Tuple[List[Row], LookupRecord]:
    """The application-side by-id entry (never a tool argument). Unknown id → ValueError.

    The path has no filter axes, so every axis records `None` at `application_default`
    and the cap, while reported, is not applied (eligibility-assistant-D-69).
    """
    index = _current()
    out: List[Row] = []
    for doc_id in ids:
        row = index.row(doc_id) if isinstance(doc_id, str) else None
        if row is None:
            raise ValueError("unknown document id")
        out.append(row)
    return out, _emit(
        LookupRecord(
            topic=None,
            topic_provenance=APPLICATION_DEFAULT,
            payer=None,
            payer_provenance=APPLICATION_DEFAULT,
            product=None,
            product_provenance=APPLICATION_DEFAULT,
            state=None,
            state_provenance=APPLICATION_DEFAULT,
            pre_filter_rows=len(index.rows),
            post_filter_rows=len(out),
            returned_rows=len(out),
            cap=_cap(),
            truncated=False,
            empty=not out,
        )
    )
