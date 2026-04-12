"""TeachMode — surprise-quiz Big Bro after a file write.

Workflow
--------
When TeachMode is ``enabled`` and Big Bro finishes writing/editing a
file, ``_note_tool_use`` calls ``should_trigger(action, now)``. If it
says yes, ``trigger(panel, world, campaign_state)`` picks an eligible
quest from the campaign content and hands it to the injected
``ChallengeManager`` which renders the challenge block inline in the
panel.

Design notes
------------
* The cooldown is wall-clock seconds since the last trigger so a
  burst of edits doesn't spam the user with back-to-back quests.
* Quest selection prefers quests from the *current* area (what the
  player is already working on) and falls back to "first unlocked
  incomplete quest in the world" if nothing matches.
* ``ChallengeManager`` is the source of truth for XP + state — this
  module only picks the quest and flips the ``last_triggered_at``
  clock.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src_local.quests.models import Quest, World
    from src_local.quests.state import CampaignState
    from src_local.rpg.challenge import ChallengeManager


# Actions that are allowed to surprise-quiz the user. Add any new
# write-style hooks here; everything else is ignored.
TRIGGER_ACTIONS: frozenset[str] = frozenset({"file_edited", "file_created"})

DEFAULT_COOLDOWN_SECONDS: float = 60.0


@dataclass
class TeachMode:
    """Orchestrator that decides when to interrupt with a quest."""

    manager: "ChallengeManager"
    quest_lookup: Callable[[str], "Quest | None"]
    enabled: bool = False
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS
    last_triggered_at: float = 0.0
    session_triggers: int = 0
    # Random source is injectable so tests can pin the selection.
    rng: random.Random = field(default_factory=random.Random)
    now_fn: Callable[[], float] = time.monotonic

    # -------------------------------------------------------------
    # Toggles
    # -------------------------------------------------------------

    def toggle(self) -> bool:
        self.enabled = not self.enabled
        return self.enabled

    def turn_on(self) -> None:
        self.enabled = True

    def turn_off(self) -> None:
        self.enabled = False

    # -------------------------------------------------------------
    # Trigger decision
    # -------------------------------------------------------------

    def should_trigger(self, action: str, now: float | None = None) -> bool:
        """Return True iff this action should surprise-quiz the user."""
        if not self.enabled:
            return False
        if action not in TRIGGER_ACTIONS:
            return False
        t = now if now is not None else self.now_fn()
        if self.last_triggered_at == 0.0:
            return True
        return (t - self.last_triggered_at) >= self.cooldown_seconds

    # -------------------------------------------------------------
    # Quest selection + dispatch
    # -------------------------------------------------------------

    def pick_quest(
        self, world: "World", state: "CampaignState"
    ) -> "Quest | None":
        """Return an eligible quest for a surprise quiz, or None.

        Preference order:
          1. A random incomplete non-boss quest in the player's
             ``current_area`` (if one is set and unlocked).
          2. A random incomplete non-boss quest from the first
             unlocked area that still has todo items.
        """
        def _eligible_from(area_id: str) -> list["Quest"]:
            area = world.area_by_id(area_id)
            if area is None:
                return []
            if not state.is_area_unlocked(area_id, world):
                return []
            out: list["Quest"] = []
            for qid in area.quest_ids:
                if state.is_quest_done(qid):
                    continue
                q = self.quest_lookup(qid)
                if q is not None and not q.is_boss():
                    out.append(q)
            return out

        if state.current_area:
            pool = _eligible_from(state.current_area)
            if pool:
                return self.rng.choice(pool)

        for area in world.areas:
            pool = _eligible_from(area.id)
            if pool:
                return self.rng.choice(pool)
        return None

    def trigger(
        self,
        panel: Any,
        world: "World",
        state: "CampaignState",
        *,
        now: float | None = None,
    ) -> bool:
        """Pick a quest and hand it to the challenge manager.

        Returns True if a quest was actually started, False if nothing
        eligible was found (or the manager is already busy — we skip
        in that case so we don't clobber an in-progress challenge).
        """
        if self.manager.active_quest is not None:
            return False
        quest = self.pick_quest(world, state)
        if quest is None:
            return False
        self.manager.start(quest, panel)
        self.last_triggered_at = now if now is not None else self.now_fn()
        self.session_triggers += 1
        return True
