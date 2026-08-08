"""
Retrievers for the RAG eval (RIV-160).

Two implementations behind one duck-typed interface (`retrieve(query, k) ->
list of record ids`):

- StubRetriever — deterministic oracle used by unit tests and as a torch-free
  upper bound: it returns exactly what the gold-set expects, so recall and
  precision are 1.0 by construction. If the report "passes" even at this
  ceiling, passing clearly doesn't prove chart completeness.
- EmbeddingRetriever — sentence-transformers (all-MiniLM-L6-v2) with cosine
  top-k. Heavy imports are deferred into _load() so importing this module
  stays torch-free. Corpus embeddings are computed once and cached to disk
  keyed by a hash of (model name + corpus), per the engagement's quota
  guard: embed once and cache, never re-embed per run.
"""
import hashlib
import json
import os
from typing import Dict, List, Sequence

DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Ceiling on how many documents may be embedded in one run. The client's AI
# budget is the constraint ("basically a Claude Pro plan"), and embedding is the
# only place in this repo that spends against it. 1000 is far above today's
# 5-document corpus — the cap is a guard against a corpus that grew, not a
# working limit.
DEFAULT_MAX_CORPUS_DOCS = 1000


def _default_max_corpus_docs() -> int:
    """Read at call time, not import time, so an operator export is honoured
    without re-importing the module (and so tests can set it)."""
    return int(os.getenv("RAG_MAX_CORPUS_DOCS", str(DEFAULT_MAX_CORPUS_DOCS)))


class CorpusTooLarge(RuntimeError):
    """The corpus exceeds the configured embedding cap."""


class StubRetriever:
    """Oracle: maps each query to a fixed list of record ids."""

    def __init__(self, retrieved_by_query: Dict[str, Sequence[int]]):
        self._mapping = {q: list(ids) for q, ids in retrieved_by_query.items()}

    def retrieve(self, query: str, k: int) -> List[int]:
        return self._mapping.get(query, [])[:k]

    @classmethod
    def perfect_for(cls, cases: Sequence) -> "StubRetriever":
        """Oracle that answers every gold case with its own cites_records."""
        return cls({c.query: list(c.cites_records) for c in cases})


class EmbeddingRetriever:
    """
    Cosine top-k over cached local embeddings of the encounter corpus.

    corpus: {record_id: document text}. Embeddings are cached under
    cache_dir as <corpus_hash>.npy + .json; identical corpus + model never
    re-embeds. Queries are embedded per call (three short strings — cheap).
    """

    def __init__(
        self,
        corpus: Dict[int, str],
        cache_dir: str,
        model_name: str = DEFAULT_MODEL,
        max_corpus_docs: int = None,
    ):
        self._record_ids = sorted(corpus)
        self._docs = [corpus[rid] for rid in self._record_ids]
        self._cache_dir = cache_dir
        self._model_name = model_name
        self._max_corpus_docs = (
            _default_max_corpus_docs() if max_corpus_docs is None else max_corpus_docs
        )
        self._model = None
        self._doc_vectors = None

    def _corpus_hash(self) -> str:
        h = hashlib.sha256()
        h.update(self._model_name.encode())
        for rid, doc in zip(self._record_ids, self._docs):
            h.update(f"\x00{rid}\x00{doc}".encode())
        return h.hexdigest()[:16]

    def _load(self):
        if self._doc_vectors is not None:
            return
        # REFUSE, never truncate. Silently embedding the first N documents would
        # change every score in the report while the gate stayed green — a
        # smaller corpus scoring differently is indistinguishable from a
        # retrieval regression. Checked before the heavy imports, so an
        # over-cap corpus costs nothing at all.
        if len(self._docs) > self._max_corpus_docs:
            raise CorpusTooLarge(
                f"corpus has {len(self._docs)} documents, over the "
                f"{self._max_corpus_docs}-document embedding cap "
                "(RAG_MAX_CORPUS_DOCS / --max-corpus-docs). Raise the cap "
                "deliberately or shrink the corpus; the eval will not embed a "
                "truncated corpus, because the scores would be silently wrong."
            )
        try:
            import numpy as np  # noqa: F401 — heavy deps stay out of module import
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "EmbeddingRetriever needs the embedding dependencies: "
                "pip install -r eval/rag/requirements.txt "
                "(or run with --retriever stub for the torch-free path)"
            ) from e

        os.makedirs(self._cache_dir, exist_ok=True)
        stem = os.path.join(self._cache_dir, self._corpus_hash())
        vec_path, meta_path = stem + ".npy", stem + ".json"
        self._model = SentenceTransformer(self._model_name)
        if os.path.exists(vec_path):
            self._doc_vectors = np.load(vec_path)
        else:
            self._doc_vectors = self._model.encode(self._docs, normalize_embeddings=True)
            np.save(vec_path, self._doc_vectors)
            with open(meta_path, "w") as f:
                json.dump(
                    {"model": self._model_name, "record_ids": self._record_ids},
                    f,
                    indent=2,
                )

    def retrieve(self, query: str, k: int) -> List[int]:
        self._load()
        query_vec = self._model.encode([query], normalize_embeddings=True)[0]
        scores = self._doc_vectors @ query_vec  # cosine: both sides normalized
        ranked = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        return [self._record_ids[i] for i in ranked[:k]]


def encounter_document(patient_name: str, encounter) -> str:
    """Render one encounter row as the text the retriever indexes."""
    allergies = ", ".join(sorted(encounter.allergies)) or "none recorded"
    medications = ", ".join(sorted(encounter.medications)) or "none recorded"
    return (
        f"Patient {patient_name} (chart {encounter.patient_id}). "
        f"{encounter.encounter_type} with {encounter.provider} on {encounter.occurred_at}. "
        f"{encounter.summary} Allergies: {allergies}. Medications: {medications}."
    )
