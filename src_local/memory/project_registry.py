"""Persistent registry of known projects.

Stored at ``~/.lilbro-local/projects.json`` as a dict keyed by
resolved absolute path.  All operations are synchronous and safe to
call at startup without blocking the event loop for more than a few
milliseconds (file is small by design).

Usage::

    registry = ProjectRegistry(Path.home() / ".lilbro-local" / "projects.json")
    registry.register(str(Path.cwd()))
    projects = registry.list_recent(n=5)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("lilbro-local.memory.registry")


class ProjectRegistry:
    """Persistent registry of known projects.

    File format (``projects.json``)::

        {
          "/abs/path/to/project": {
            "name": "my-project",
            "last_seen": 1713456789.0,
            "session_count": 3,
            "tags": []
          }
        }
    """

    def __init__(self, registry_file: Path) -> None:
        self._path = Path(registry_file)
        self._data: dict[str, dict] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, cwd: str, name: str | None = None) -> dict:
        """Register or update a project. Returns project metadata."""
        key = str(Path(cwd).resolve())
        existing = self._data.get(key, {})
        auto_name = name or Path(key).name or key
        entry: dict = {
            "name": existing.get("name") or auto_name,
            "last_seen": time.time(),
            "session_count": existing.get("session_count", 0),
            "tags": existing.get("tags", []),
        }
        # Override name only if explicitly supplied.
        if name:
            entry["name"] = name
        self._data[key] = entry
        self._save()
        return dict(entry)

    def get(self, cwd: str) -> dict | None:
        """Return project metadata or None if unknown."""
        key = str(Path(cwd).resolve())
        entry = self._data.get(key)
        return dict(entry) if entry else None

    def list_recent(self, n: int = 10) -> list[dict]:
        """Return the *n* most recently seen projects as enriched dicts."""
        items = sorted(
            self._data.items(),
            key=lambda kv: kv[1].get("last_seen", 0.0),
            reverse=True,
        )
        out: list[dict] = []
        for path_str, meta in items[:n]:
            entry = dict(meta)
            entry["path"] = path_str
            out.append(entry)
        return out

    def increment_session_count(self, cwd: str) -> None:
        """Increment the session counter for a project."""
        key = str(Path(cwd).resolve())
        if key not in self._data:
            return
        self._data[key]["session_count"] = (
            self._data[key].get("session_count", 0) + 1
        )
        self._save()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self._path.exists():
                raw = self._path.read_text(encoding="utf-8")
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    self._data = loaded
        except Exception as exc:  # noqa: BLE001
            logger.warning("ProjectRegistry: failed to load %s: %s", self._path, exc)
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ProjectRegistry: failed to save: %s", exc)
