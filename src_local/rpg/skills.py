"""Skill tracker — maps action events to domain skill XP.

``PlayerProfile.award_xp`` already supports a ``skill=`` kwarg, but
most of the callers in ``src/commands/handler.py`` and ``src/app.py``
don't know which domain an action belongs to. Rather than pollute
every call site, callers route events through ``SkillTracker.tag``
which looks up the domain in a small table and forwards the award
with the right skill attached.

This keeps the domain mapping in **one place** so adding a new
action-to-skill tag is a one-liner.
"""

from __future__ import annotations

from typing import Final

from src_local.rpg.player import AwardReport, PlayerProfile
from src_local.rpg.xp import SKILLS


# Action key → skill domain. Actions missing from this table still
# earn overall XP (via award_xp) but don't level any skill.
ACTION_SKILL_MAP: Final[dict[str, str]] = {
    # coding
    "file_edited":        "coding",
    "file_created":       "coding",
    "tests_run":          "coding",
    "user_turn":          "coding",      # tiny trickle — rewards engagement
    # debugging
    "debug_used":         "debugging",
    "trace_used":         "debugging",
    "retry_success":      "debugging",
    # learning
    "explain_used":       "learning",
    "compare_used":       "learning",
    "concept_discovered": "learning",
    # reviewing
    "review_used":        "reviewing",
    "review_file_used":   "reviewing",
    "explain_diff_used":  "reviewing",
    # planning
    "plan_before_code":   "planning",
    "focus_set":          "planning",
    "focus_completed":    "planning",
    # quest / campaign (Phase 18) — completing a quest trains learning
    "quest_completed":    "learning",
}


def skill_for_action(action: str) -> str | None:
    """Return the skill that *action* contributes to, or None."""
    skill = ACTION_SKILL_MAP.get(action)
    if skill is None or skill not in SKILLS:
        return None
    return skill


class SkillTracker:
    """Thin wrapper around ``PlayerProfile.award_xp`` that auto-tags
    the correct skill domain for each action.

    Usage::

        tracker = SkillTracker(profile)
        report = tracker.tag("explain_used", concept="asyncio")

    The returned ``AwardReport`` is identical to ``award_xp``'s so
    callers can surface banners the same way.
    """

    def __init__(self, profile: PlayerProfile) -> None:
        self.profile = profile

    def tag(
        self,
        action: str,
        *,
        concept: str | None = None,
        extra_xp: int = 0,
    ) -> AwardReport:
        """Award XP for *action* with the domain looked up from the
        static table. Unknown actions still work (they just don't
        contribute to any skill).

        ``extra_xp`` forwards to ``PlayerProfile.award_xp`` so per-call
        bonuses (e.g. quest no-hints bonus) flow through the same
        level-up detection path as the base action XP.
        """
        skill = skill_for_action(action)
        return self.profile.award_xp(
            action, skill=skill, concept=concept, extra_xp=extra_xp
        )

    def note(self, event: str) -> None:
        """Passthrough for ``note_event`` — lets callers go through
        a single object for all RPG instrumentation."""
        self.profile.note_event(event)
