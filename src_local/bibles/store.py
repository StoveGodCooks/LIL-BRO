"""Bible retrieval engine for LIL BRO LOCAL.

Loads the precompiled bible JSON files (coding + reasoning) and their
tag indexes.  Provides fast tag-scored lookup so agents can pull
relevant reference chunks at query time.

Design
------
Each bible is a list of chunks with ``id``, ``tags``, ``source_id``,
``heading_path``, and ``text``.  The companion index maps every tag to
the list of chunk IDs that carry it.

Retrieval flow:
  1. Tokenize the user query into candidate tags (``topic:X``)
  2. Score each chunk by how many query-tags it matches (weighted)
  3. Return the top-K highest-scoring chunks
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("lilbro-local.bible")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BIBLES_DIR = Path(__file__).parent

# Noise words stripped when converting a query into topic tags.
_NOISE = frozenset(
    "a an and are as at be by can do for from get has have how i if in"
    " into is it its me my no not of on or our so than that the then"
    " there these they this to us was we what when where which who why"
    " will with you your".split()
)

# Minimum word length to consider as a topic tag.
_MIN_WORD_LEN = 2

# Default number of results.
DEFAULT_TOP_K = 8


# ---------------------------------------------------------------------------
# Chunk dataclass (lightweight, not a full dataclass to save memory)
# ---------------------------------------------------------------------------

class BibleChunk:
    """Single bible entry — thin wrapper around the raw dict."""

    __slots__ = ("id", "tags", "source_id", "heading_path", "text")

    def __init__(self, raw: dict[str, Any]) -> None:
        self.id: str = raw["id"]
        self.tags: list[str] = raw["tags"]
        self.source_id: str = raw["source_id"]
        self.heading_path: list[str] = raw.get("heading_path", [])
        self.text: str = raw["text"]

    def summary_line(self) -> str:
        """One-line summary for display in tool output."""
        path = " > ".join(self.heading_path) if self.heading_path else self.source_id
        return f"[{self.id}] {path}"

    def to_context(self) -> str:
        """Format this chunk as context for injection into a prompt."""
        header = " > ".join(self.heading_path) if self.heading_path else self.source_id
        return f"--- {header} ({self.id}) ---\n{self.text}"


# ---------------------------------------------------------------------------
# BibleStore
# ---------------------------------------------------------------------------

class BibleStore:
    """In-memory bible with tag-scored retrieval.

    Load once at app startup; both agents share the same instance.
    """

    def __init__(self) -> None:
        # {bible_name: {chunk_id: BibleChunk}}
        self._chunks: dict[str, dict[str, BibleChunk]] = {}
        # {bible_name: {tag: [chunk_id, ...]}}
        self._indexes: dict[str, dict[str, list[str]]] = {}
        self._loaded = False

    # ---- loading ----

    def load(self) -> None:
        """Load both bibles + indexes from the package directory."""
        if self._loaded:
            return
        for name in ("coding", "reasoning"):
            bible_path = _BIBLES_DIR / f"{name}.bible.json"
            index_path = _BIBLES_DIR / f"{name}.index.json"
            if not bible_path.exists():
                logger.warning("Bible file not found: %s", bible_path)
                continue
            self._load_bible(name, bible_path, index_path)
        self._loaded = True
        total = sum(len(c) for c in self._chunks.values())
        logger.info("Bible store loaded: %d chunks across %d bibles",
                     total, len(self._chunks))

    def _load_bible(self, name: str, bible_path: Path, index_path: Path) -> None:
        """Load a single bible + its index."""
        try:
            raw_entries = json.loads(bible_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load bible %s", bible_path)
            return

        chunks: dict[str, BibleChunk] = {}
        for entry in raw_entries:
            chunk = BibleChunk(entry)
            chunks[chunk.id] = chunk
        self._chunks[name] = chunks
        logger.info("Loaded %d chunks from %s", len(chunks), name)

        # Load the companion tag index.
        if index_path.exists():
            try:
                self._indexes[name] = json.loads(
                    index_path.read_text(encoding="utf-8")
                )
            except Exception:
                logger.exception("Failed to load index %s", index_path)
                self._indexes[name] = self._build_index(chunks)
        else:
            logger.warning("Index not found, building in-memory: %s", index_path)
            self._indexes[name] = self._build_index(chunks)

    @staticmethod
    def _build_index(chunks: dict[str, BibleChunk]) -> dict[str, list[str]]:
        """Build a tag -> [chunk_id] index in memory (fallback)."""
        index: dict[str, list[str]] = {}
        for chunk in chunks.values():
            for tag in chunk.tags:
                index.setdefault(tag, []).append(chunk.id)
        return index

    # ---- retrieval ----

    def lookup(
        self,
        query: str,
        bible: str = "coding",
        top_k: int = DEFAULT_TOP_K,
        source_filter: str | None = None,
        category_filter: str | None = None,
    ) -> list[BibleChunk]:
        """Find the most relevant chunks for a natural-language query.

        Parameters
        ----------
        query : str
            The user's question or topic.
        bible : str
            Which bible to search (``"coding"`` or ``"reasoning"``).
        top_k : int
            Maximum number of results.
        source_filter : str, optional
            If given, only return chunks from this source_id.
        category_filter : str, optional
            If given, only return chunks tagged with this ``cat:`` tag.
        """
        if not self._loaded:
            self.load()

        chunks = self._chunks.get(bible)
        index = self._indexes.get(bible)
        if not chunks or not index:
            return []

        # Tokenize query into candidate tags.
        query_tags = self._query_to_tags(query)
        if not query_tags:
            return []

        # Score each chunk by how many query-tags it matches.
        # tag_weight: topic: = 1, cat: = 2 (broader, should boost), src: = 0.5
        scores: dict[str, float] = {}
        for tag in query_tags:
            chunk_ids = index.get(tag, [])
            weight = self._tag_weight(tag)
            for cid in chunk_ids:
                scores[cid] = scores.get(cid, 0) + weight

        if not scores:
            return []

        # Apply filters.
        if source_filter:
            src_tag = f"src:{source_filter}"
            allowed = set(index.get(src_tag, []))
            scores = {k: v for k, v in scores.items() if k in allowed}

        if category_filter:
            cat_tag = category_filter if category_filter.startswith("cat:") else f"cat:{category_filter}"
            allowed = set(index.get(cat_tag, []))
            scores = {k: v for k, v in scores.items() if k in allowed}

        # Sort by score descending, break ties by chunk ID for stability.
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))

        results: list[BibleChunk] = []
        for cid, _score in ranked[:top_k]:
            chunk = chunks.get(cid)
            if chunk is not None:
                results.append(chunk)

        return results

    def coding_lookup(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[BibleChunk]:
        """Convenience: search the coding bible."""
        return self.lookup(query, bible="coding", top_k=top_k)

    def reasoning_lookup(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[BibleChunk]:
        """Convenience: search the reasoning bible."""
        return self.lookup(query, bible="reasoning", top_k=top_k)

    def search_by_tag(self, tag: str, bible: str = "coding", top_k: int = DEFAULT_TOP_K) -> list[BibleChunk]:
        """Direct tag lookup — for when you know the exact tag."""
        chunks = self._chunks.get(bible, {})
        index = self._indexes.get(bible, {})
        chunk_ids = index.get(tag, [])
        return [chunks[cid] for cid in chunk_ids[:top_k] if cid in chunks]

    def list_sources(self, bible: str = "coding") -> list[str]:
        """List all source_ids in a bible."""
        index = self._indexes.get(bible, {})
        return sorted(tag[4:] for tag in index if tag.startswith("src:"))

    def list_categories(self, bible: str = "coding") -> list[str]:
        """List all categories in a bible."""
        index = self._indexes.get(bible, {})
        return sorted(tag[4:] for tag in index if tag.startswith("cat:"))

    def stats(self) -> dict[str, Any]:
        """Return summary stats for display."""
        out: dict[str, Any] = {}
        for name, chunks in self._chunks.items():
            index = self._indexes.get(name, {})
            out[name] = {
                "chunks": len(chunks),
                "tags": len(index),
                "sources": len([t for t in index if t.startswith("src:")]),
                "categories": len([t for t in index if t.startswith("cat:")]),
                "topics": len([t for t in index if t.startswith("topic:")]),
            }
        return out

    # ---- internals ----

    @staticmethod
    def _query_to_tags(query: str) -> list[str]:
        """Convert a natural-language query into candidate lookup tags.

        Extracts words, filters noise, and generates ``topic:word`` tags.
        Also looks for explicit patterns like ``python``, ``asyncio``, etc.
        """
        # Clean: lowercase, strip punctuation, split.
        text = re.sub(r"[^\w\s]", " ", query.lower())
        words = text.split()

        tags: list[str] = []
        for w in words:
            if len(w) < _MIN_WORD_LEN:
                continue
            if w in _NOISE:
                continue
            tags.append(f"topic:{w}")

        # Deduplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for t in tags:
            if t not in seen:
                seen.add(t)
                unique.append(t)

        return unique

    @staticmethod
    def _tag_weight(tag: str) -> float:
        """Assign a scoring weight based on tag type."""
        if tag.startswith("cat:"):
            return 2.0
        if tag.startswith("src:"):
            return 0.5
        # topic: tags = default weight
        return 1.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: BibleStore | None = None


def get_bible_store() -> BibleStore:
    """Get or create the global BibleStore singleton."""
    global _store
    if _store is None:
        _store = BibleStore()
        _store.load()
    return _store
