"""Quest engine — pure data layer for the Codelands campaign.

Everything in this package is independent of Textual and of the
running app. Phase 17+ builds the UI layer on top; Phase 15.5 wired
the RPG engine into the live app; this package adds the campaign
structure (areas, quests, boss chunks) that drives it.

Exports:
    * ``Quest``, ``QuestChunk``, ``Area``, ``World`` — frozen models
    * ``QuestLoadError`` — raised by the loader on malformed YAML
    * ``load_world``, ``load_quest`` — YAML → dataclass
    * ``validate`` + typed ``ValidationResult`` — dispatches by quest type
    * ``CampaignState`` — persistent progress tracker
"""

from src_local.quests.models import Area, Quest, QuestChunk, World
from src_local.quests.loader import QuestLoadError, load_quest, load_world
from src_local.quests.state import CampaignState
from src_local.quests.validators import (
    ValidationResult,
    validate,
    validate_boss_chunk,
    validate_debug_trail,
    validate_key_lines,
    validate_retype,
)

__all__ = [
    "Area",
    "Quest",
    "QuestChunk",
    "World",
    "QuestLoadError",
    "load_quest",
    "load_world",
    "CampaignState",
    "ValidationResult",
    "validate",
    "validate_boss_chunk",
    "validate_debug_trail",
    "validate_key_lines",
    "validate_retype",
]
