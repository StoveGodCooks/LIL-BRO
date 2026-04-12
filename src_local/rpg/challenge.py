"""ChallengeManager — the state machine that runs a quest.

Responsibilities
----------------
* Own the lifecycle of an active quest: IDLE → PRESENTED → AWAITING →
  VALIDATING → DONE (or back to PRESENTED on a wrong submission).
* Push the ChallengeBlock into the active panel when a quest starts.
* Accept a submission, dispatch to ``src_local.quests.validators.validate``,
  award XP + badge unlocks on success.
* Track hints consumed + wall-clock elapsed so bonus/speedrun payouts
  stay honest.

What this class is NOT
----------------------
* It does not own the modal editor (that's ``TeachScratchScreen``).
* It does not pick quests (that's ``TeachMode`` or ``/quest``).
* It does not know about Textual — ``panel`` is duck-typed so tests
  can pass a fake.

State transitions
-----------------
    IDLE
     │ start(quest, panel)
     ▼
    PRESENTED ──── skip() ────────────▶ DONE (zero XP)
     │ open_scratch() / submit()
     ▼
    AWAITING_SUBMISSION
     │ submit(text)
     ▼
    VALIDATING ─ok=False─▶ PRESENTED (back for another try)
     │ ok=True
     ▼
    DONE (XP + badges awarded, completed_quests bumped)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from src_local.quests.models import Quest
from src_local.quests.state import CampaignState
from src_local.quests.validators import ValidationResult, validate

if TYPE_CHECKING:
    from src_local.quests.models import World
    from src_local.rpg.player import PlayerProfile
    from src_local.rpg.skills import SkillTracker


class ChallengeState(Enum):
    IDLE = "idle"
    PRESENTED = "presented"
    AWAITING = "awaiting"
    VALIDATING = "validating"
    DONE = "done"


@dataclass
class ChallengeOutcome:
    """Returned by ``submit()`` so the UI can react."""

    ok: bool
    result: ValidationResult
    xp_awarded: int = 0
    banners: list[str] = field(default_factory=list)


class ChallengeManager:
    """Owns the active quest lifecycle for one DualPaneScreen."""

    def __init__(
        self,
        profile: "PlayerProfile",
        tracker: "SkillTracker",
        campaign_state: CampaignState,
        *,
        now_fn: Callable[[], float] = time.monotonic,
        world: "World | None" = None,
    ) -> None:
        self._profile = profile
        self._tracker = tracker
        self._state_store = campaign_state
        self._now = now_fn
        # Phase 23 audit fix — when a World is attached, the area
        # counter bump distinguishes "progress" from "completed". The
        # old behavior (bump area_completed on every quest) is kept as
        # a fallback when world=None so tests that don't construct a
        # full World still exercise the badge triggers.
        self._world = world
        self.state: ChallengeState = ChallengeState.IDLE
        self.active_quest: Quest | None = None
        self.panel: Any = None
        self.hints_consumed: int = 0
        self._started_at: float = 0.0
        # Phase 22 — "hint_token" perk: if active and the daily token
        # hasn't been spent yet, the first hint request doesn't count
        # against the no-hints bonus. We track spend separately so we
        # can reconcile at finalize time.
        self._hint_token_spent: bool = False

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self, quest: Quest, panel: Any) -> None:
        """Present a new quest in *panel*. Transitions IDLE→PRESENTED."""
        if self.state not in (ChallengeState.IDLE, ChallengeState.DONE):
            # Forcefully replace whatever was running — the user just
            # picked a new quest, so we throw away the old one. No XP
            # is awarded for the abandoned attempt.
            self._reset()
        self.active_quest = quest
        self.panel = panel
        self.hints_consumed = 0
        self._hint_token_spent = False
        self._started_at = self._now()
        self.state = ChallengeState.PRESENTED
        self._state_store.start_quest(quest.id, quest.area, now=self._started_at)
        self._render_presentation()

    def _render_presentation(self) -> None:
        """Append a compact challenge block into the panel.

        The panel is duck-typed — we just look for ``append_system``
        which every ``_BasePanel`` subclass and every test fake has.
        """
        if self.panel is None or self.active_quest is None:
            return
        q = self.active_quest
        lines = [
            f"── QUEST: {q.title} ──",
            f"area: {q.area}   xp: {q.xp}   type: {q.type}",
        ]
        if q.concept_tags:
            lines.append(f"concepts: {', '.join(q.concept_tags)}")
        if q.story:
            lines.append("")
            lines.append(q.story.strip())
        lines.append("")
        lines.append(q.task.strip())
        lines.append("")
        lines.append("use /submit <text> · /hint · /skip")
        for line in lines:
            try:
                self.panel.append_system(line)
            except Exception:  # noqa: BLE001
                pass

    # -----------------------------------------------------------------
    # User actions
    # -----------------------------------------------------------------

    def hint(self) -> str | None:
        """Reveal the next hint if one exists. Bumps the hint counter
        so the bonus_xp_no_hints payout is disqualified. Returns the
        hint string so the caller can render it, or None if there are
        no hints left / no active quest."""
        if self.state not in (ChallengeState.PRESENTED, ChallengeState.AWAITING):
            return None
        q = self.active_quest
        if q is None:
            return None
        if self.hints_consumed >= len(q.hints):
            return None
        text = q.hints[self.hints_consumed]
        self.hints_consumed += 1
        self._state_store.consume_hint(q.id)
        # Phase 22 — hint_token perk: first hint of the day is free if
        # the perk is active and the daily token hasn't been spent yet.
        # We mark ``_hint_token_spent`` so _finalize_success can forgive
        # this hint when computing the no-hints bonus. Also bumps the
        # ``hint_tokens_used_today`` counter so the perk is one-per-day.
        if not self._hint_token_spent and self.hints_consumed == 1:
            try:
                perks = self._profile.active_perks()
            except Exception:  # noqa: BLE001
                perks = []
            if (
                "hint_token" in perks
                and self._profile.counters.get("hint_tokens_used_today", 0) < 1
            ):
                self._hint_token_spent = True
                self._profile.counters["hint_tokens_used_today"] = (
                    self._profile.counters.get("hint_tokens_used_today", 0) + 1
                )
        if self.panel is not None:
            try:
                suffix = " (hint token · free)" if self._hint_token_spent and self.hints_consumed == 1 else ""
                self.panel.append_system(
                    f"💡 hint {self.hints_consumed}: {text}{suffix}"
                )
            except Exception:  # noqa: BLE001
                pass
        return text

    def skip(self) -> None:
        """Abandon the current quest without XP. Transitions → DONE."""
        if self.state == ChallengeState.IDLE:
            return
        if self.panel is not None and self.active_quest is not None:
            try:
                self.panel.append_system(
                    f"· skipped quest '{self.active_quest.id}' — no XP awarded"
                )
            except Exception:  # noqa: BLE001
                pass
        self._tracker.tag("quest_skipped")
        self._reset()

    def submit(self, text: str) -> ChallengeOutcome:
        """Evaluate *text* against the active quest.

        On a pass: awards XP (base + no-hint bonus + speedrun counter),
        marks the quest complete, appends banners to the panel, and
        transitions to DONE.

        On a fail: stays in PRESENTED so the user can try again. The
        returned ``ChallengeOutcome`` carries the ``ValidationResult``
        so the UI can show a "missing X" hint.
        """
        if self.state not in (ChallengeState.PRESENTED, ChallengeState.AWAITING):
            return ChallengeOutcome(
                ok=False,
                result=ValidationResult(ok=False, message="no active quest"),
            )
        q = self.active_quest
        if q is None:
            return ChallengeOutcome(
                ok=False,
                result=ValidationResult(ok=False, message="no active quest"),
            )

        self.state = ChallengeState.VALIDATING
        if q.is_boss():
            # Boss quests are not handled here — Phase 20's
            # BossFightController is the right call site. We bail so
            # the manager's state machine stays honest.
            self.state = ChallengeState.PRESENTED
            return ChallengeOutcome(
                ok=False,
                result=ValidationResult(
                    ok=False, message="boss quests require BossFightController"
                ),
            )

        result = validate(q, text)
        if not result.ok:
            # Back to PRESENTED so the user can fix + retry.
            self.state = ChallengeState.PRESENTED
            if self.panel is not None:
                try:
                    self.panel.append_system(
                        f"✗ not quite — {result.message}"
                    )
                    for miss in result.missing[:5]:
                        self.panel.append_system(f"   missing: {miss}")
                except Exception:  # noqa: BLE001
                    pass
            return ChallengeOutcome(ok=False, result=result)

        # Success path — award XP, badges, and finalize state.
        return self._finalize_success(q, result)

    # -----------------------------------------------------------------
    # Success finalization
    # -----------------------------------------------------------------

    def _finalize_success(
        self, q: Quest, result: ValidationResult
    ) -> ChallengeOutcome:
        banners: list[str] = []

        # Phase 23 audit fix — route the no-hints bonus through
        # ``award_xp(extra_xp=...)`` so a level-up triggered purely by
        # the bonus still fires a banner. Previously the bonus was a
        # direct ``profile.xp +=`` bump that bypassed level-up detection.
        #
        # hint_token perk forgives exactly one hint: the player is
        # treated as having used one fewer hint for bonus purposes.
        effective_hints = self.hints_consumed - (1 if self._hint_token_spent else 0)
        bonus = q.bonus_xp_no_hints if (effective_hints <= 0 and q.bonus_xp_no_hints > 0) else 0

        concept = q.concept_tags[0] if q.concept_tags else None
        base_report = self._tracker.tag(
            "quest_completed", concept=concept, extra_xp=bonus
        )
        xp_awarded = base_report.xp_gained
        banners.extend(base_report.banners())

        if bonus > 0:
            self._profile.counters["quest_no_hints_clean"] = (
                self._profile.counters.get("quest_no_hints_clean", 0) + 1
            )
            banners.append(
                f"★ no-hints bonus: +{bonus} xp"
            )

        # Speedrun — award counter bump (not XP) so the badge catalog
        # can hook off it. time_par_seconds=0 disables the check.
        elapsed = self._now() - self._started_at
        if q.time_par_seconds > 0 and elapsed <= q.time_par_seconds:
            self._profile.counters["quest_speedrun"] = (
                self._profile.counters.get("quest_speedrun", 0) + 1
            )
            banners.append(
                f"⚡ speedrun! finished in {int(elapsed)}s "
                f"(par {q.time_par_seconds}s)"
            )

        # Mark complete in the campaign state BEFORE checking area
        # badges so "area_completed_cave" counters are up-to-date.
        self._state_store.mark_completed(q.id, q.area)
        self._bump_area_counter(q.area)

        # Badge sweep.
        try:
            from src_local.rpg.badges import check_badges
            for name in check_badges(self._profile, "quest_completed"):
                banners.append(f"🏅 Badge unlocked: {name}")
        except Exception:  # noqa: BLE001
            pass

        if self.panel is not None:
            try:
                self.panel.append_system("✓ quest complete!")
                for line in banners:
                    self.panel.append_system(line)
                if q.debrief:
                    self.panel.append_system("")
                    self.panel.append_system(q.debrief.strip())
            except Exception:  # noqa: BLE001
                pass

        self._reset()
        return ChallengeOutcome(
            ok=True,
            result=result,
            xp_awarded=xp_awarded,
            banners=banners,
        )

    def _bump_area_counter(self, area_id: str) -> None:
        """Maintain the per-area progress and completion counters.

        Semantics (Phase 23 audit fix):

        * ``area_progress_<slug>`` — bumped on EVERY quest completion
          in that area. Safe for "any quest in this area" triggers.
        * ``area_completed_<slug>`` — bumped EXACTLY ONCE per area,
          the first time every quest in the area is done. When a
          ``World`` is attached we can compute "done / total" for
          real; without one we fall back to the old behavior so
          tests that construct ChallengeManager without a World
          still see the counter tick.
        """
        progress_key = f"area_progress_{area_id}"
        self._profile.counters[progress_key] = (
            self._profile.counters.get(progress_key, 0) + 1
        )

        completed_key = f"area_completed_{area_id}"
        if self._world is None:
            # Legacy fallback — match the pre-audit behavior so tests
            # that don't wire a World still exercise the badge path.
            self._profile.counters[completed_key] = (
                self._profile.counters.get(completed_key, 0) + 1
            )
            return

        area = self._world.area_by_id(area_id)
        if area is None:
            return
        total = area.total_quests()
        if total == 0:
            return
        done = self._state_store.area_progress.get(area_id, 0)
        if done >= total and self._profile.counters.get(completed_key, 0) == 0:
            # First time all quests in the area are done — fire the
            # completion counter exactly once. Idempotent on replays
            # because we guard on the existing counter value.
            self._profile.counters[completed_key] = 1

    # -----------------------------------------------------------------
    # Cleanup
    # -----------------------------------------------------------------

    def _reset(self) -> None:
        self.state = ChallengeState.DONE if self.active_quest else ChallengeState.IDLE
        self.active_quest = None
        self.panel = None
        self.hints_consumed = 0
        self._started_at = 0.0
        # Caller is free to start again — the next start() will flip
        # us back into PRESENTED.
