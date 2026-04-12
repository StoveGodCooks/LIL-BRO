"""LIL BRO RPG core.

Phase 15: the foundational data model for the "code your way to level
60" progression system layered on top of normal LIL BRO usage.

Public surface (imported lazily by consumers):

* :mod:`src_local.rpg.xp`       — action → XP table, level table, skill table,
                            concept catalog, ``level_for_xp``,
                            ``xp_to_next``.
* :mod:`src_local.rpg.player`   — ``PlayerProfile`` dataclass with atomic
                            ``load``/``save`` backed by
                            ``~/.lilbro-local/player.json`` and ``award_xp``
                            that returns any level-up messages the UI
                            should surface.
* :mod:`src_local.rpg.badges`   — 23 unlockable badges + ``check_badges`` to
                            unlock them in response to recorded events.
* :mod:`src_local.rpg.skills`   — ``SkillTracker`` that bumps per-skill XP on
                            domain-tagged events.

Everything in this package is pure-Python, filesystem-only — no
subprocess / network / Textual dependency. The goal is that the
tests can exercise every code path with a temp dir.
"""

from __future__ import annotations

__all__ = [
    "xp",
    "player",
    "badges",
    "skills",
]
