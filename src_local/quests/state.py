"""Persistent campaign progress — separate from PlayerProfile.

Why its own file: PlayerProfile tracks XP/skills/badges (universal
RPG state). CampaignState tracks quest-specific progress (which
quests are done, which area is current, boss chunk index, hint
usage). Splitting them means a user can reset their campaign
without losing their level, or vice versa.

On-disk path default: ``~/.lilbro-local/campaign_state.json``. Save is
atomic via tempfile + os.replace, mirrored from
``src/rpg/player.py:233-260``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src_local.quests.models import World


CAMPAIGN_STATE_VERSION = 1
DEFAULT_STATE_PATH = Path.home() / ".lilbro-local" / "campaign_state.json"


@dataclass
class CampaignState:
    """In-memory + on-disk record of the player's campaign progress."""

    current_area: str = ""
    current_quest_id: str = ""
    completed_quests: set[str] = field(default_factory=set)
    # area_id → count of completed quests in that area
    area_progress: dict[str, int] = field(default_factory=dict)
    # Active boss chunk index (0-based) for the quest referenced by
    # current_quest_id when that quest is a boss. Reset on fail.
    boss_chunk_index: int = 0
    # quest_id → number of hints consumed (so the bonus_xp_no_hints
    # payout stays honest across save/resume).
    hints_used: dict[str, int] = field(default_factory=dict)
    # quest_id → monotonic start time (seconds). Cleared on complete.
    start_times: dict[str, float] = field(default_factory=dict)
    teach_mode_on: bool = False
    version: int = CAMPAIGN_STATE_VERSION
    path: Path = field(default_factory=lambda: DEFAULT_STATE_PATH)

    # -----------------------------------------------------------------
    # Mutation
    # -----------------------------------------------------------------

    def start_quest(self, quest_id: str, area_id: str, now: float) -> None:
        """Record that the player just accepted *quest_id*."""
        self.current_quest_id = quest_id
        self.current_area = area_id
        self.boss_chunk_index = 0
        self.start_times[quest_id] = now
        self.hints_used.setdefault(quest_id, 0)

    def consume_hint(self, quest_id: str) -> int:
        """Bump the hint counter for *quest_id*, returns new value."""
        self.hints_used[quest_id] = self.hints_used.get(quest_id, 0) + 1
        return self.hints_used[quest_id]

    def mark_completed(self, quest_id: str, area_id: str) -> None:
        """Move a quest from "in progress" to "done"."""
        if quest_id in self.completed_quests:
            return
        self.completed_quests.add(quest_id)
        self.area_progress[area_id] = self.area_progress.get(area_id, 0) + 1
        # Clear the speedrun clock so a resumed quest doesn't get
        # phantom-credited next time.
        self.start_times.pop(quest_id, None)
        if self.current_quest_id == quest_id:
            self.current_quest_id = ""
            self.boss_chunk_index = 0

    def quest_elapsed(self, quest_id: str, now: float) -> float:
        """Monotonic seconds since ``start_quest`` (0.0 if never
        started or already completed)."""
        t0 = self.start_times.get(quest_id)
        if t0 is None:
            return 0.0
        return max(0.0, now - t0)

    # -----------------------------------------------------------------
    # Queries
    # -----------------------------------------------------------------

    def is_quest_done(self, quest_id: str) -> bool:
        return quest_id in self.completed_quests

    def is_area_unlocked(self, area_id: str, world: "World") -> bool:
        """An area unlocks when its predecessor is ≥80% complete.

        The first area (no ``unlock_requires``) is always unlocked.
        """
        area = world.area_by_id(area_id)
        if area is None:
            return False
        if not area.unlock_requires:
            return True
        prev = world.area_by_id(area.unlock_requires)
        if prev is None:
            return False
        total = prev.total_quests()
        if total == 0:
            return True
        done = self.area_progress.get(prev.id, 0)
        return (done / total) >= 0.8

    def area_completion_ratio(self, area_id: str, world: "World") -> float:
        area = world.area_by_id(area_id)
        if area is None or area.total_quests() == 0:
            return 0.0
        return min(1.0, self.area_progress.get(area_id, 0) / area.total_quests())

    def completion_percent(self, world: "World") -> float:
        """Overall campaign completion as 0.0..1.0."""
        total = world.total_quests()
        if total == 0:
            return 0.0
        return min(1.0, len(self.completed_quests) / total)

    # -----------------------------------------------------------------
    # Serialization
    # -----------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "current_area": self.current_area,
            "current_quest_id": self.current_quest_id,
            "completed_quests": sorted(self.completed_quests),
            "area_progress": dict(self.area_progress),
            "boss_chunk_index": int(self.boss_chunk_index),
            "hints_used": dict(self.hints_used),
            "start_times": dict(self.start_times),
            "teach_mode_on": bool(self.teach_mode_on),
        }

    @classmethod
    def from_dict(cls, data: dict, path: Path) -> "CampaignState":
        return cls(
            current_area=str(data.get("current_area", "")),
            current_quest_id=str(data.get("current_quest_id", "")),
            completed_quests=set(data.get("completed_quests") or []),
            area_progress={
                str(k): int(v)
                for k, v in (data.get("area_progress") or {}).items()
            },
            boss_chunk_index=int(data.get("boss_chunk_index", 0)),
            hints_used={
                str(k): int(v)
                for k, v in (data.get("hints_used") or {}).items()
            },
            start_times={
                str(k): float(v)
                for k, v in (data.get("start_times") or {}).items()
            },
            teach_mode_on=bool(data.get("teach_mode_on", False)),
            version=int(data.get("version", CAMPAIGN_STATE_VERSION)),
            path=path,
        )

    def save(self) -> None:
        """Atomic write — mirrors PlayerProfile.save()."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".campaign-", suffix=".tmp", dir=str(self.path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self.path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            pass

    @classmethod
    def load(cls, path: Path | None = None) -> "CampaignState":
        """Never raises — falls back to a fresh state on any error."""
        p = Path(path) if path is not None else DEFAULT_STATE_PATH
        if not p.exists():
            return cls(path=p)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls(path=p)
            return cls.from_dict(data, p)
        except (OSError, json.JSONDecodeError, ValueError):
            return cls(path=p)
