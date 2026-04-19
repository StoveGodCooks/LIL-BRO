"""Persistent log of observed user preferences and patterns.

Stored at ``~/.lilbro-local/preferences.json`` as an append-only-ish
list of events.  Callers record small structured events (e.g. "used
dataclass for a DTO", "chose pytest fixture over monkeypatch") and the
log aggregates them into top patterns that can be surfaced back to the
user or fed into the context injector.

Intentionally boring: plain JSON, no external deps, safe to call at
startup.  Graceful no-op on IO errors -- memory features must never
break the app.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger("lilbro-local.memory.preferences")


class PreferenceLog:
    """Append-only-ish log of small preference events.

    File format (``preferences.json``)::

        {
          "events": [
            {"type": "naming_style",
             "value": "snake_case",
             "project": "/abs/path",
             "timestamp": 1713456789.0},
            ...
          ]
        }
    """

    MAX_EVENTS = 2000  # cap; oldest dropped when exceeded

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._events: list[dict] = []
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        value: str,
        *,
        project: str | None = None,
        extra: dict | None = None,
    ) -> None:
        """Append a preference event. Silently no-ops on IO failure."""
        entry: dict = {
            "type": str(event_type),
            "value": str(value),
            "project": project or "",
            "timestamp": time.time(),
        }
        if extra:
            entry["extra"] = dict(extra)
        self._events.append(entry)
        # Cap growth.
        if len(self._events) > self.MAX_EVENTS:
            self._events = self._events[-self.MAX_EVENTS :]
        self._save()

    def query(
        self,
        event_type: str | None = None,
        *,
        project: str | None = None,
    ) -> list[dict]:
        """Return matching events (most recent first)."""
        out = self._events
        if event_type:
            out = [e for e in out if e.get("type") == event_type]
        if project:
            key = str(Path(project).resolve())
            out = [
                e for e in out
                if e.get("project") and str(Path(e["project"]).resolve()) == key
            ]
        return list(reversed(out))

    def top_patterns(
        self,
        n: int = 5,
        *,
        event_type: str | None = None,
        project: str | None = None,
    ) -> list[dict]:
        """Return the top-*n* (type, value) pairs by occurrence count.

        Returned entries look like
        ``{"type": ..., "value": ..., "count": int}``.
        """
        events = self.query(event_type=event_type, project=project)
        counter: Counter[tuple[str, str]] = Counter(
            (e.get("type", ""), e.get("value", "")) for e in events
        )
        return [
            {"type": t, "value": v, "count": c}
            for (t, v), c in counter.most_common(n)
        ]

    def forget(self, match: str) -> int:
        """Drop events whose type or value contains *match*.

        Returns the number of events removed.
        """
        if not match:
            return 0
        needle = match.lower()
        before = len(self._events)
        self._events = [
            e for e in self._events
            if needle not in (e.get("type", "").lower())
            and needle not in (e.get("value", "").lower())
        ]
        removed = before - len(self._events)
        if removed:
            self._save()
        return removed

    def all_events(self) -> list[dict]:
        return list(self._events)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                data = json.loads(raw)
                events = data.get("events") if isinstance(data, dict) else None
                if isinstance(events, list):
                    self._events = [e for e in events if isinstance(e, dict)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("PreferenceLog: failed to load %s: %s", self._path, exc)
            self._events = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({"events": self._events}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("PreferenceLog: failed to save: %s", exc)
