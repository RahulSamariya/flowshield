"""KnowledgeBase — in-process keyword retrieval over the FlowShield corpus.

Retrieval strategy
------------------
BM25-inspired term-frequency scoring using only the Python stdlib.
No numpy, no scikit-learn, no external vector store.

Algorithm
---------
1. On construction, build an inverted index: term → list of (chunk_id, tf).
   Terms are lowercased, punctuation-stripped tokens from title + text + tags.
   Tags are weighted 3×; title tokens 2×; body tokens 1×.
2. At query time, tokenise the query the same way.
3. Score each chunk:  sum of tf(term, chunk) * idf(term)
   where idf = log(1 + N / df) and df = number of chunks containing the term.
4. Return top-k chunks sorted by score descending.
5. Chunks with score == 0 are never returned.

Category filter
---------------
Pass ``category_filter`` to restrict retrieval to one KnowledgeCategory.
Useful when the caller knows whether it wants an SOP vs an escalation rule.

Citations
---------
Every RetrievedChunk exposes the source KnowledgeChunk so callers can read
``chunk.source_ref`` and ``chunk.title`` for citation text.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from src.knowledge.knowledge_chunk import KnowledgeCategory, KnowledgeChunk

# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieval hit.

    Attributes
    ----------
    chunk
        The matched KnowledgeChunk.
    relevance_score
        Non-negative float.  Higher = more relevant.  Not normalised to [0,1]
        (raw BM25-style score); use only for relative ranking within one query.
    """
    chunk: KnowledgeChunk
    relevance_score: float


@dataclass
class RetrievalResult:
    """Ordered retrieval results for one query.

    Attributes
    ----------
    query
        The original query string.
    hits
        Chunks ordered by relevance_score descending.
    category_filter
        The category restriction applied (or None if unrestricted).
    """
    query: str
    hits: list[RetrievedChunk]
    category_filter: KnowledgeCategory | None = None

    @property
    def chunks(self) -> list[KnowledgeChunk]:
        """Convenience: ordered list of KnowledgeChunk objects."""
        return [h.chunk for h in self.hits]

    @property
    def citations(self) -> list[str]:
        """Unique source references in retrieval order (duplicates removed)."""
        seen: set[str] = set()
        refs: list[str] = []
        for h in self.hits:
            ref = h.chunk.source_ref or h.chunk.title
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)
        return refs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[^a-z0-9\s]")
_SPACE = re.compile(r"\s+")

# Common English stop-words that carry no retrieval signal
_STOP = frozenset(
    "a an the and or but if in on at to of for with by is are was were be been "
    "this that these those it its will shall may must can could would should "
    "not no nor i we you he she they all any each from as so do does did".split()
)


def _tokenise(text: str) -> list[str]:
    """Lowercase, strip punctuation, split on whitespace, remove stop-words."""
    text = _PUNCT.sub(" ", text.lower())
    tokens = _SPACE.split(text.strip())
    return [t for t in tokens if t and t not in _STOP]


def _tf(tokens: list[str]) -> dict[str, float]:
    """Raw term frequencies (count / total tokens)."""
    if not tokens:
        return {}
    total = len(tokens)
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t] = counts.get(t, 0) + 1
    return {t: c / total for t, c in counts.items()}


# ---------------------------------------------------------------------------
# KnowledgeBase
# ---------------------------------------------------------------------------

class KnowledgeBase:
    """Corpus + inverted index for policy retrieval.

    Usage::

        kb = KnowledgeBase(chunks=[...])
        result = kb.retrieve("pump deployment waterlogging", top_k=3)
        for hit in result.hits:
            print(hit.relevance_score, hit.chunk.title)
            print("Cite:", hit.chunk.source_ref)

    Or with category filter::

        result = kb.retrieve("escalation authority", category_filter=KnowledgeCategory.ESCALATION)
    """

    def __init__(self, chunks: Sequence[KnowledgeChunk]) -> None:
        self._chunks: dict[str, KnowledgeChunk] = {c.id: c for c in chunks}
        # chunk_id → weighted TF dict
        self._chunk_tfs: dict[str, dict[str, float]] = {}
        # term → set of chunk_ids that contain it
        self._inv_index: dict[str, set[str]] = {}

        self._build_index()

    # ── public API ────────────────────────────────────────────────────────

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        category_filter: KnowledgeCategory | None = None,
    ) -> RetrievalResult:
        """Retrieve the top-k most relevant chunks for a query.

        Parameters
        ----------
        query:
            Free-text query (incident type, action description, reason code, etc.)
        top_k:
            Maximum number of results to return.
        category_filter:
            If set, only chunks of this category are eligible.

        Returns
        -------
        RetrievalResult
            Always returns a result; hits may be empty if nothing scores > 0.
        """
        query_tokens = _tokenise(query)
        if not query_tokens:
            return RetrievalResult(query=query, hits=[], category_filter=category_filter)

        N = len(self._chunks)
        scores: dict[str, float] = {}

        for term in query_tokens:
            df = len(self._inv_index.get(term, set()))
            if df == 0:
                continue
            idf = math.log(1.0 + N / df)
            for chunk_id, chunk_tf in self._chunk_tfs.items():
                tf_val = chunk_tf.get(term, 0.0)
                if tf_val:
                    scores[chunk_id] = scores.get(chunk_id, 0.0) + tf_val * idf

        # apply category filter
        if category_filter is not None:
            scores = {
                cid: s
                for cid, s in scores.items()
                if self._chunks[cid].category == category_filter
            }

        # sort and truncate
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

        hits = [
            RetrievedChunk(chunk=self._chunks[cid], relevance_score=round(score, 4))
            for cid, score in ranked
        ]
        return RetrievalResult(query=query, hits=hits, category_filter=category_filter)

    @property
    def size(self) -> int:
        """Number of chunks in the corpus."""
        return len(self._chunks)

    def categories(self) -> set[KnowledgeCategory]:
        """Set of all categories present in the corpus."""
        return {c.category for c in self._chunks.values()}

    def get(self, chunk_id: str) -> KnowledgeChunk | None:
        """Return a chunk by ID, or None."""
        return self._chunks.get(chunk_id)

    # ── index construction ────────────────────────────────────────────────

    def _build_index(self) -> None:
        for chunk in self._chunks.values():
            # Weight: tags 3×, title 2×, body 1×
            tag_tokens = _tokenise(" ".join(chunk.tags)) * 3
            title_tokens = _tokenise(chunk.title) * 2
            body_tokens = _tokenise(chunk.text)
            all_tokens = tag_tokens + title_tokens + body_tokens

            tf_map = _tf(all_tokens)
            self._chunk_tfs[chunk.id] = tf_map

            for term in tf_map:
                if term not in self._inv_index:
                    self._inv_index[term] = set()
                self._inv_index[term].add(chunk.id)
