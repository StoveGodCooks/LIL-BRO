"""Frozen dataclasses for the Codelands campaign.

Design notes
------------
Everything is ``frozen=True`` so quests behave like configuration
constants once loaded — no code path can accidentally mutate a quest
mid-run. Collections that the frozen constraint can't protect
(lists, dicts) are still aliased because YAML decodes into mutable
Python types; callers must treat them as read-only by convention.

Quest types
-----------
Five shapes, one dispatch field:

* ``retype``       — user retypes the solution close enough to match
* ``key_lines``    — user's submission must contain every key_line
* ``debug_trail``  — user lists the bugs in the given order
* ``explain``      — user writes an explanation matching key_lines
* ``boss``         — special, multi-chunk; see ``QuestChunk``

Boss chunks reuse the same type taxonomy so the existing validators
can dispatch on them without a second machinery.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple


# Five legal quest types. Keep in sync with validators.py dispatch.
QUEST_TYPES: Tuple[str, ...] = (
    "retype",
    "key_lines",
    "debug_trail",
    "explain",
    "boss",
)


@dataclass(frozen=True)
class QuestChunk:
    """One stage of a boss fight — evaluated like a mini quest."""

    id: str
    title: str
    type: str          # one of QUEST_TYPES (sans "boss")
    task: str          # the prompt shown to the user
    puzzle: str = ""   # pre-filled scratch buffer content
    solution: str = ""
    key_lines: tuple[str, ...] = field(default_factory=tuple)
    expected_trail: tuple[str, ...] = field(default_factory=tuple)
    hints: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Quest:
    """A single campaign quest.

    The ``type`` field drives validation. Regular quests set one of
    ``retype`` / ``key_lines`` / ``debug_trail`` / ``explain``. Boss
    quests set ``type="boss"`` and fill ``chunks`` with sequential
    ``QuestChunk`` entries instead.
    """

    id: str
    area: str
    title: str
    type: str
    concept_tags: tuple[str, ...]
    xp: int
    task: str
    # Optional story beats — everything below is safe to omit in YAML.
    story: str = ""
    puzzle: str = ""             # pre-filled scratch buffer text
    solution: str = ""           # canonical answer for retype-style
    key_lines: tuple[str, ...] = field(default_factory=tuple)
    expected_trail: tuple[str, ...] = field(default_factory=tuple)
    debrief: str = ""
    hints: tuple[str, ...] = field(default_factory=tuple)
    bonus_xp_no_hints: int = 0
    time_par_seconds: int = 0    # 0 = no speedrun bonus defined
    badges_triggered: tuple[str, ...] = field(default_factory=tuple)
    chunks: tuple[QuestChunk, ...] = field(default_factory=tuple)  # boss only

    def is_boss(self) -> bool:
        return self.type == "boss"


@dataclass(frozen=True)
class Area:
    """An ordered group of quests that share a theme."""

    id: str
    name: str
    description: str
    quest_ids: tuple[str, ...]
    boss_quest_id: str = ""      # empty when the area has no boss
    unlock_requires: str = ""    # id of prerequisite area, empty for first

    def total_quests(self) -> int:
        """Regular quests + 1 for the boss when present."""
        return len(self.quest_ids) + (1 if self.boss_quest_id else 0)


@dataclass(frozen=True)
class World:
    """Top-level container — every Area in display order."""

    areas: tuple[Area, ...]

    def area_by_id(self, area_id: str) -> "Area | None":
        for a in self.areas:
            if a.id == area_id:
                return a
        return None

    def total_quests(self) -> int:
        return sum(a.total_quests() for a in self.areas)

    def all_quest_ids(self) -> tuple[str, ...]:
        out: list[str] = []
        for a in self.areas:
            out.extend(a.quest_ids)
            if a.boss_quest_id:
                out.append(a.boss_quest_id)
        return tuple(out)
