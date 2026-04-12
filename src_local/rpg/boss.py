"""BossFightController — multi-chunk final quest runner.

Boss quests (``type="boss"``) are a sequence of ``QuestChunk`` stages
that must be cleared in order. Unlike normal quests, a wrong answer
mid-fight *wipes* progress back to chunk 0 — there's a reason they're
the last thing in each act.

Lifecycle
---------
    start(quest, panel)
      │ renders chunk 0
      ▼
    submit(text)
      │ validate_boss_chunk(chunk, text)
      ├─ok=True, not final─▶ advance index, render next chunk
      ├─ok=True,     final─▶ award XP + boss_slayer counter, DONE
      └─ok=False         ─▶ wipe index back to 0, stay in fight

Why not fold this into ChallengeManager?
----------------------------------------
Chunk sequencing, wipe-on-fail, and the "final chunk awards the whole
quest" rule are all boss-only. ChallengeManager deliberately bails on
``quest.is_boss()`` so this controller owns the state cleanly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from src_local.quests.validators import ValidationResult, validate_boss_chunk

if TYPE_CHECKING:
    from src_local.quests.models import Quest, QuestChunk, World
    from src_local.quests.state import CampaignState
    from src_local.rpg.player import PlayerProfile
    from src_local.rpg.skills import SkillTracker


@dataclass
class BossOutcome:
    """Returned by ``submit()`` so the UI can react per-chunk."""

    ok: bool
    result: ValidationResult
    chunk_index: int
    advanced: bool = False       # True when we moved to the next chunk
    completed: bool = False      # True on final-chunk success
    wiped: bool = False          # True when a wrong answer reset to 0
    xp_awarded: int = 0
    banners: list[str] = field(default_factory=list)


class BossFightController:
    """Owns the active boss quest for one DualPaneScreen."""

    def __init__(
        self,
        profile: "PlayerProfile",
        tracker: "SkillTracker",
        campaign_state: "CampaignState",
        *,
        world: "World | None" = None,
    ) -> None:
        self._profile = profile
        self._tracker = tracker
        self._state_store = campaign_state
        # Phase 23 audit fix — World enables "area fully cleared"
        # detection for the final area-completion counter bump.
        self._world = world
        self.active_quest: "Quest | None" = None
        self.panel: Any = None

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    def start(self, quest: "Quest", panel: Any) -> None:
        """Begin a boss fight and render the first chunk."""
        if not quest.is_boss():
            raise ValueError(f"quest {quest.id!r} is not a boss quest")
        if not quest.chunks:
            raise ValueError(f"boss quest {quest.id!r} has no chunks")
        self.active_quest = quest
        self.panel = panel
        self._state_store.current_quest_id = quest.id
        self._state_store.current_area = quest.area
        self._state_store.boss_chunk_index = 0
        self._render_header()
        self._render_chunk(0)

    def current_chunk(self) -> "QuestChunk | None":
        if self.active_quest is None:
            return None
        idx = self._state_store.boss_chunk_index
        if idx < 0 or idx >= len(self.active_quest.chunks):
            return None
        return self.active_quest.chunks[idx]

    # -----------------------------------------------------------------
    # Submission
    # -----------------------------------------------------------------

    def submit(self, text: str) -> BossOutcome:
        """Evaluate *text* against the current chunk."""
        if self.active_quest is None:
            return BossOutcome(
                ok=False,
                result=ValidationResult(ok=False, message="no active boss"),
                chunk_index=0,
            )
        chunk = self.current_chunk()
        if chunk is None:
            return BossOutcome(
                ok=False,
                result=ValidationResult(ok=False, message="boss has no chunks"),
                chunk_index=0,
            )
        chunk_result = validate_boss_chunk(chunk, text)
        idx = self._state_store.boss_chunk_index
        total = len(self.active_quest.chunks)
        if not chunk_result.ok:
            self._state_store.boss_chunk_index = 0
            self._emit(
                f"✗ the boss wipes your progress — {chunk_result.message}"
            )
            self._emit("restart from chunk 1.")
            return BossOutcome(
                ok=False,
                result=chunk_result,
                chunk_index=idx,
                wiped=True,
            )

        # Chunk passed.
        self._emit(f"✓ chunk {idx + 1}/{total} cleared.")
        if idx + 1 < total:
            self._state_store.boss_chunk_index = idx + 1
            self._render_chunk(idx + 1)
            return BossOutcome(
                ok=True,
                result=ValidationResult(ok=True, message="chunk clear"),
                chunk_index=idx + 1,
                advanced=True,
            )

        # Final chunk — full boss clear.
        return self._finalize_victory(idx)

    # -----------------------------------------------------------------
    # Finalization
    # -----------------------------------------------------------------

    def _finalize_victory(self, chunk_index: int) -> BossOutcome:
        q = self.active_quest
        assert q is not None
        concept = q.concept_tags[0] if q.concept_tags else None

        banners: list[str] = []
        report = self._tracker.tag("quest_completed", concept=concept)
        xp_awarded = report.xp_gained
        banners.extend(report.banners())

        # Boss-specific counters.
        self._profile.counters["boss_slayer"] = (
            self._profile.counters.get("boss_slayer", 0) + 1
        )

        self._state_store.mark_completed(q.id, q.area)
        # Phase 23 audit fix — mirror ChallengeManager's split between
        # area_progress (bumped every quest) and area_completed (fired
        # exactly once when every quest in the area is done). Without
        # a World we keep the old "bump on boss clear" fallback so the
        # boss slayer still credits the area.
        self._bump_area_counter(q.area)

        # Badge sweep.
        try:
            from src_local.rpg.badges import check_badges
            for name in check_badges(self._profile, "quest_completed"):
                banners.append(f"🏅 Badge unlocked: {name}")
        except Exception:  # noqa: BLE001
            pass

        self._emit("⚔ BOSS DEFEATED ⚔")
        for line in banners:
            self._emit(line)
        if q.debrief:
            self._emit("")
            self._emit(q.debrief.strip())

        self.active_quest = None
        self.panel = None
        return BossOutcome(
            ok=True,
            result=ValidationResult(ok=True, message="boss cleared"),
            chunk_index=chunk_index,
            completed=True,
            xp_awarded=xp_awarded,
            banners=banners,
        )

    # -----------------------------------------------------------------
    # Rendering helpers
    # -----------------------------------------------------------------

    def _render_header(self) -> None:
        q = self.active_quest
        if q is None:
            return
        self._emit(f"── BOSS: {q.title} ──")
        if q.story:
            self._emit("")
            self._emit(q.story.strip())

    def _render_chunk(self, idx: int) -> None:
        q = self.active_quest
        if q is None:
            return
        if idx < 0 or idx >= len(q.chunks):
            return
        c = q.chunks[idx]
        total = len(q.chunks)
        self._emit("")
        self._emit(f"── chunk {idx + 1}/{total}: {c.title} ──")
        self._emit(c.task.strip())
        self._emit("use /submit <text>")

    def _bump_area_counter(self, area_id: str) -> None:
        """Same semantics as ChallengeManager._bump_area_counter — kept
        local so the two controllers don't share mutable state beyond
        the profile + campaign state they already share.
        """
        progress_key = f"area_progress_{area_id}"
        self._profile.counters[progress_key] = (
            self._profile.counters.get(progress_key, 0) + 1
        )
        completed_key = f"area_completed_{area_id}"
        if self._world is None:
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
            self._profile.counters[completed_key] = 1

    def _emit(self, line: str) -> None:
        if self.panel is None:
            return
        try:
            self.panel.append_system(line)
        except Exception:  # noqa: BLE001
            pass


def make_controller(
    profile: "PlayerProfile",
    tracker: "SkillTracker",
    campaign_state: "CampaignState",
    *,
    world: "World | None" = None,
) -> BossFightController:
    """Tiny factory kept so app.py can stay symmetric with ChallengeManager."""
    return BossFightController(profile, tracker, campaign_state, world=world)


# Kept so the plan's ``Callable[..., BossFightController]`` name resolves
# cleanly if anyone imports it — module-level type-only alias.
BossFactory = Callable[
    ["PlayerProfile", "SkillTracker", "CampaignState"],
    BossFightController,
]
