"""YAML → dataclass conversion for quests and worlds.

The loader is deliberately strict about required fields so a typo in
a content file fails loudly at load time rather than at quest-start
time (which would be a much worse UX). Optional fields fall through
to the dataclass defaults.

Usage::

    from src_local.quests.loader import load_world, load_quest
    world = load_world(Path("src_local/quests/content/world.yaml"))
    quest = load_quest(Path("src_local/quests/content/cave/cave_01.yaml"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from src_local.quests.models import QUEST_TYPES, Area, Quest, QuestChunk, World


class QuestLoadError(ValueError):
    """Raised when a YAML file is missing a required field or has a
    type error that would make the quest unusable."""


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _require(mapping: Mapping[str, Any], key: str, path: Path) -> Any:
    if key not in mapping:
        raise QuestLoadError(f"{path}: missing required field '{key}'")
    return mapping[key]


def _str_tuple(value: Any) -> tuple[str, ...]:
    """Coerce a YAML list/None into a tuple[str, ...]."""
    if value is None:
        return tuple()
    if isinstance(value, str):
        return (value,)
    return tuple(str(v) for v in value)


def _read_yaml(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise QuestLoadError(f"{path}: file not found")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise QuestLoadError(f"{path}: YAML parse error: {exc}") from exc
    if data is None:
        raise QuestLoadError(f"{path}: empty document")
    if not isinstance(data, Mapping):
        raise QuestLoadError(f"{path}: top-level must be a mapping, got {type(data).__name__}")
    return data


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def load_quest(path: Path) -> Quest:
    """Load a single quest YAML. Raises QuestLoadError on any problem."""
    data = _read_yaml(path)

    qid = str(_require(data, "id", path))
    area = str(_require(data, "area", path))
    title = str(_require(data, "title", path))
    qtype = str(_require(data, "type", path))
    task = str(_require(data, "task", path))
    xp = int(_require(data, "xp", path))

    if qtype not in QUEST_TYPES:
        raise QuestLoadError(
            f"{path}: type '{qtype}' not in {QUEST_TYPES}"
        )

    concept_tags = _str_tuple(data.get("concept_tags"))

    chunks_raw = data.get("chunks") or []
    if qtype == "boss" and not chunks_raw:
        raise QuestLoadError(f"{path}: boss quest must define 'chunks'")
    if qtype != "boss" and chunks_raw:
        raise QuestLoadError(
            f"{path}: only boss quests may define 'chunks' (type is '{qtype}')"
        )
    chunks = tuple(_chunk_from_dict(c, path) for c in chunks_raw)

    return Quest(
        id=qid,
        area=area,
        title=title,
        type=qtype,
        concept_tags=concept_tags,
        xp=xp,
        task=task,
        story=str(data.get("story", "")),
        puzzle=str(data.get("puzzle", "")),
        solution=str(data.get("solution", "")),
        key_lines=_str_tuple(data.get("key_lines")),
        expected_trail=_str_tuple(data.get("expected_trail")),
        debrief=str(data.get("debrief", "")),
        hints=_str_tuple(data.get("hints")),
        bonus_xp_no_hints=int(data.get("bonus_xp_no_hints", 0)),
        time_par_seconds=int(data.get("time_par_seconds", 0)),
        badges_triggered=_str_tuple(data.get("badges_triggered")),
        chunks=chunks,
    )


def _chunk_from_dict(raw: Any, path: Path) -> QuestChunk:
    if not isinstance(raw, Mapping):
        raise QuestLoadError(f"{path}: chunk entries must be mappings")
    ctype = str(_require(raw, "type", path))
    if ctype not in QUEST_TYPES or ctype == "boss":
        raise QuestLoadError(
            f"{path}: chunk type '{ctype}' invalid (no nested bosses)"
        )
    return QuestChunk(
        id=str(_require(raw, "id", path)),
        title=str(_require(raw, "title", path)),
        type=ctype,
        task=str(_require(raw, "task", path)),
        puzzle=str(raw.get("puzzle", "")),
        solution=str(raw.get("solution", "")),
        key_lines=_str_tuple(raw.get("key_lines")),
        expected_trail=_str_tuple(raw.get("expected_trail")),
        hints=_str_tuple(raw.get("hints")),
    )


def load_world(path: Path) -> World:
    """Load a world YAML — the top-level map of areas + quest ids.

    Expected schema::

        areas:
          - id: cave
            name: The Cave
            description: ...
            quests: [cave_01, cave_02, ...]
            boss: ""                # optional
            unlock_requires: ""     # optional, previous area id
    """
    data = _read_yaml(path)
    areas_raw = _require(data, "areas", path)
    if not isinstance(areas_raw, list):
        raise QuestLoadError(f"{path}: 'areas' must be a list")

    areas: list[Area] = []
    for entry in areas_raw:
        if not isinstance(entry, Mapping):
            raise QuestLoadError(f"{path}: area entry must be a mapping")
        areas.append(
            Area(
                id=str(_require(entry, "id", path)),
                name=str(_require(entry, "name", path)),
                description=str(entry.get("description", "")),
                quest_ids=_str_tuple(entry.get("quests")),
                boss_quest_id=str(entry.get("boss", "") or ""),
                unlock_requires=str(entry.get("unlock_requires", "") or ""),
            )
        )
    return World(areas=tuple(areas))
