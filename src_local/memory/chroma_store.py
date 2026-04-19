"""Local vector memory backed by ChromaDB.

Optional dependency — if chromadb is not installed, every method
no-ops gracefully and a warning is logged once.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("lilbro-local.memory")

# Attempt to import chromadb once at module load time.
try:
    import chromadb  # type: ignore[import-not-found]
    from chromadb.config import Settings  # type: ignore[import-not-found]
    _available: bool = True
except ImportError:
    _available = False
    logger.debug(
        "chromadb not installed — memory features disabled. "
        "Install with: pip install chromadb"
    )


_WARNED_ONCE: bool = False


def _warn_unavailable() -> None:
    global _WARNED_ONCE  # noqa: PLW0603
    if not _WARNED_ONCE:
        _WARNED_ONCE = True
        logger.warning(
            "chromadb is not installed — /remember, /recall, and session memory "
            "are disabled. Install with: pip install chromadb"
        )


class MemoryStore:
    """ChromaDB-backed vector store.

    All public methods are safe to call when ``chromadb`` is not installed;
    they return empty/no-op results and log a one-time warning.

    Usage::

        store = MemoryStore(Path.home() / ".lilbro-local" / "memory")
        mid = store.add("some text", metadata={"type": "manual"})
        results = store.search("some query", n=5)
    """

    def __init__(self, store_dir: Path) -> None:
        self._dir = Path(store_dir)
        self._client: Any = None
        self._collection: Any = None
        if not _available:
            return
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.Client(  # type: ignore[union-attr]
                Settings(
                    persist_directory=str(self._dir),
                    anonymized_telemetry=False,
                )
            )
            self._collection = self._client.get_or_create_collection(
                name="lilbro_memory"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryStore init failed: %s", exc)
            self._client = None
            self._collection = None

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def add(self, text: str, metadata: dict | None = None) -> str:
        """Embed and store *text*. Returns the generated ID."""
        if not _available or self._collection is None:
            _warn_unavailable()
            return ""
        mid = str(uuid.uuid4())
        meta = dict(metadata or {})
        # ChromaDB requires all metadata values to be str/int/float/bool.
        meta = {k: _coerce_meta(v) for k, v in meta.items()}
        try:
            self._collection.add(
                documents=[text],
                metadatas=[meta],
                ids=[mid],
            )
            return mid
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryStore.add failed: %s", exc)
            return ""

    def search(self, query: str, n: int = 5) -> list[dict]:
        """Semantic search. Returns list of ``{text, metadata, distance}``."""
        if not _available or self._collection is None:
            _warn_unavailable()
            return []
        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, max(1, self._collection.count())),
            )
            out: list[dict] = []
            docs = (results.get("documents") or [[]])[0]
            metas = (results.get("metadatas") or [[]])[0]
            dists = (results.get("distances") or [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                out.append({"text": doc, "metadata": meta, "distance": dist})
            return out
        except Exception as exc:  # noqa: BLE001
            logger.warning("MemoryStore.search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Session-specific helpers
    # ------------------------------------------------------------------

    def add_session(
        self,
        session_id: str,
        summary: str,
        project: str,
        timestamp: float | None = None,
    ) -> str:
        """Store a session summary with standard metadata."""
        return self.add(
            summary,
            metadata={
                "type": "session",
                "session_id": session_id,
                "project": project,
                "timestamp": str(timestamp or time.time()),
            },
        )

    def search_sessions(self, query: str, n: int = 5) -> list[dict]:
        """Search only session-type memories."""
        results = self.search(query, n=n * 2)
        return [
            r for r in results if r.get("metadata", {}).get("type") == "session"
        ][:n]


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _coerce_meta(v: Any) -> str | int | float | bool:
    """Coerce a metadata value to a ChromaDB-safe type."""
    if isinstance(v, (str, int, float, bool)):
        return v
    return str(v)
