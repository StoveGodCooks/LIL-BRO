"""Adaptive difficulty engine.

Scores how familiar the user is with a topic using three signals:

1. ``PreferenceLog`` entries tagged ``"learned"`` or ``"used"`` for the
   topic (strong signal).
2. Semantic matches in ``MemoryStore`` for the topic keyword (weak
   signal).
3. Player-profile skill level for the topic's domain when available
   (medium signal; pulled via a duck-typed callable).

The engine returns a tier (``novice`` / ``intermediate`` / ``advanced``)
and a short rationale string the lesson prompt can include verbatim.

Signals degrade gracefully: any unavailable source contributes zero
to the score, so the engine always returns *something* sensible even
with no history.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Literal

logger = logging.getLogger("lilbro-local.teaching.adaptive")

Tier = Literal["novice", "intermediate", "advanced"]


@dataclass
class Familiarity:
    topic: str
    tier: Tier
    score: int
    rationale: str


_TIER_FLOOR: dict[int, Tier] = {
    0: "novice",
    3: "intermediate",
    7: "advanced",
}


def _tier_for(score: int) -> Tier:
    if score >= 7:
        return "advanced"
    if score >= 3:
        return "intermediate"
    return "novice"


class DifficultyEngine:
    """Score user familiarity with a topic from memory + prefs.

    Inputs are duck-typed so the engine is trivially testable:

    - ``pref_query(topic)``    -> ``list[dict]`` of matching pref events
    - ``memory_search(topic)`` -> ``list[dict]`` of matching memories
    - ``skill_level(topic)``   -> ``int | None``; None when unknown
    """

    def __init__(
        self,
        *,
        pref_query: Callable[[str], list[dict]] | None = None,
        memory_search: Callable[[str], list[dict]] | None = None,
        skill_level: Callable[[str], int | None] | None = None,
    ) -> None:
        self._pref_query = pref_query
        self._memory_search = memory_search
        self._skill_level = skill_level

    def score(self, topic: str) -> Familiarity:
        t = (topic or "").strip()
        if not t:
            return Familiarity(
                topic="",
                tier="novice",
                score=0,
                rationale="no topic supplied",
            )
        score = 0
        reasons: list[str] = []

        # Preference signal: each "learned"/"used" event for this
        # topic is worth 2 points (cap 6).
        if self._pref_query is not None:
            try:
                events = self._pref_query(t) or []
                pref_hits = sum(
                    1 for e in events
                    if e.get("type") in {"learned", "used"}
                    and t.lower() in str(e.get("value", "")).lower()
                )
                bump = min(pref_hits * 2, 6)
                if bump:
                    score += bump
                    reasons.append(f"{pref_hits} prior pref event(s)")
            except Exception as exc:  # noqa: BLE001
                logger.debug("pref_query failed: %s", exc)

        # Memory signal: each relevant memory is 1 point (cap 3).
        if self._memory_search is not None:
            try:
                hits = self._memory_search(t) or []
                bump = min(len(hits), 3)
                if bump:
                    score += bump
                    reasons.append(f"{len(hits)} memory match(es)")
            except Exception as exc:  # noqa: BLE001
                logger.debug("memory_search failed: %s", exc)

        # Skill-level signal: map skill level 0..5 -> 0..5 points.
        if self._skill_level is not None:
            try:
                lvl = self._skill_level(t)
                if lvl is not None:
                    bump = max(0, min(int(lvl), 5))
                    if bump:
                        score += bump
                        reasons.append(f"skill level {bump}")
            except Exception as exc:  # noqa: BLE001
                logger.debug("skill_level failed: %s", exc)

        tier = _tier_for(score)
        rationale = (
            ", ".join(reasons) if reasons else "no prior signal"
        )
        return Familiarity(topic=t, tier=tier, score=score, rationale=rationale)


def difficulty_instructions(tier: Tier) -> str:
    """Return a one-sentence instruction the lesson prompt can embed."""
    if tier == "advanced":
        return (
            "The user is ADVANCED with this topic. Skip basics. "
            "Focus on nuance, tradeoffs, edge cases, and internals."
        )
    if tier == "intermediate":
        return (
            "The user is INTERMEDIATE. Recap the core idea in one line, "
            "then go deeper on the why and when. Assume common patterns "
            "are familiar."
        )
    return (
        "The user is a NOVICE with this topic. Use a plain-English "
        "analogy, define every term, and keep code snippets minimal."
    )
