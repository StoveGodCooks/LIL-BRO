"""Append-only idea capture.

Ideas that surface mid-execution go into the icebox so they are not
lost *and* do not derail the current task. Later they can be promoted
to tasks under a milestone or dropped.

Stored as plain JSON at ``~/.lilbro-local/icebox.json``.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger("lilbro-local.roadmap.icebox")


@dataclass
class IceboxItem:
    id: str
    text: str
    created_at: float = field(default_factory=time.time)
    promoted_to: str | None = None  # task id when promoted; else None
    dropped: bool = False


class Icebox:
    """Tiny append-only-ish idea log."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self.items: list[IceboxItem] = []
        self._load()

    def add(self, text: str) -> IceboxItem:
        item = IceboxItem(id=f"I-{uuid.uuid4().hex[:8]}", text=text)
        self.items.append(item)
        self._save()
        return item

    def list_open(self) -> list[IceboxItem]:
        return [i for i in self.items if i.promoted_to is None and not i.dropped]

    def find(self, item_id: str) -> IceboxItem | None:
        for i in self.items:
            if i.id == item_id:
                return i
        return None

    def promote(self, item_id: str, task_id: str) -> bool:
        item = self.find(item_id)
        if item is None or item.dropped:
            return False
        item.promoted_to = task_id
        self._save()
        return True

    def drop(self, item_id: str) -> bool:
        item = self.find(item_id)
        if item is None:
            return False
        item.dropped = True
        self._save()
        return True

    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                return
            self.items = [
                IceboxItem(
                    id=str(i.get("id") or ""),
                    text=str(i.get("text") or ""),
                    created_at=float(i.get("created_at") or time.time()),
                    promoted_to=i.get("promoted_to"),
                    dropped=bool(i.get("dropped")),
                )
                for i in items
                if isinstance(i, dict) and i.get("id")
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Icebox: failed to load %s: %s", self._path, exc)
            self.items = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(
                    {"items": [asdict(i) for i in self.items]},
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Icebox: failed to save: %s", exc)
