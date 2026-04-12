"""PlayerProfile — persistent RPG state for LIL BRO.

Stored as JSON at ``~/.lilbro-local/player.json`` (path can be overridden
for tests). The profile holds:

* Overall XP + level
* Per-skill XP (dict keyed by skill name, see ``src_local.rpg.xp.SKILLS``)
* Unlocked badges (set serialised as a list)
* Discovered concepts (set serialised as a list)
* Counters for action triggers (``/explain`` uses, files edited, etc.)
* Session start timestamp (for 1h / 3h milestone badges)
* Display name (defaults to "dev")

All state transitions go through ``award_xp`` and ``note_event`` so
there's one place to add instrumentation. ``save`` is atomic
(tempfile + ``os.replace``) — a crash mid-write leaves the previous
profile on disk, never a corrupted half-file.

The profile is intentionally tiny (one dict, one file) so the TUI
can load it synchronously on startup without any perceptible latency.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src_local.rpg.xp import (
    MAX_LEVEL,
    SKILLS,
    area_for_concept,
    level_for_xp,
    level_progress,
    skill_level_for_xp,
    xp_for,
    xp_to_next,
)


DEFAULT_PROFILE_PATH = Path.home() / ".lilbro-local" / "player.json"
PROFILE_VERSION = 1


@dataclass
class LevelUp:
    """Reported by ``award_xp`` when the action bumped the overall level."""

    old_level: int
    new_level: int
    xp_total: int

    def banner(self) -> str:
        return f"🎉 LEVEL UP! {self.old_level} → {self.new_level}  (total XP: {self.xp_total})"


@dataclass
class SkillLevelUp:
    skill: str
    old_level: int
    new_level: int

    def banner(self) -> str:
        return f"✨ Skill up — {self.skill} {self.old_level} → {self.new_level}"


@dataclass
class AwardReport:
    """Returned by ``award_xp`` — tells the caller what happened."""

    xp_gained: int = 0
    level_up: LevelUp | None = None
    skill_up: SkillLevelUp | None = None
    badges_unlocked: list[str] = field(default_factory=list)
    concept_discovered: bool = False

    def banners(self) -> list[str]:
        """Human-readable lines for the UI to append to the active panel."""
        out: list[str] = []
        if self.level_up is not None:
            out.append(self.level_up.banner())
        if self.skill_up is not None:
            out.append(self.skill_up.banner())
        for badge in self.badges_unlocked:
            out.append(f"🏅 Badge unlocked: {badge}")
        return out


@dataclass
class PlayerProfile:
    """Persistent RPG state. Load via ``load``, save via ``save``."""

    display_name: str = "dev"
    xp: int = 0
    skills: dict[str, int] = field(default_factory=dict)
    badges: list[str] = field(default_factory=list)
    discovered_concepts: list[str] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    session_started_at: float = field(default_factory=time.time)
    total_sessions: int = 0
    # Phase 22 — daily streak tracking. Bumped by touch_streak(now)
    # which compares today's date to last_active_date; consecutive
    # days increment, gaps reset to 1. Stored as ISO date string
    # (YYYY-MM-DD) so back-compat with old profiles is trivial.
    streak_days: int = 0
    last_active_date: str = ""
    path: Path = field(default_factory=lambda: DEFAULT_PROFILE_PATH)
    version: int = PROFILE_VERSION

    # -----------------------------------------------------------------
    # Derived views
    # -----------------------------------------------------------------

    @property
    def level(self) -> int:
        return level_for_xp(self.xp)

    @property
    def xp_to_next_level(self) -> int:
        return xp_to_next(self.xp)

    def level_progress(self) -> tuple[int, int, int]:
        return level_progress(self.xp)

    def skill_level(self, skill: str) -> int:
        return skill_level_for_xp(self.skills.get(skill, 0))

    def is_max_level(self) -> bool:
        return self.level >= MAX_LEVEL

    # -----------------------------------------------------------------
    # Mutation — the ONE place XP is earned
    # -----------------------------------------------------------------

    def award_xp(
        self,
        action: str,
        *,
        skill: str | None = None,
        concept: str | None = None,
        extra_xp: int = 0,
    ) -> AwardReport:
        """Award the XP for *action* and return what changed.

        ``skill`` — if provided, the skill's XP is also bumped by the
        same amount (to a cap of the skill's max level threshold).

        ``concept`` — if provided and cataloged, the concept is added
        to the discovered set and a bonus XP award is applied.

        ``extra_xp`` — optional flat amount stacked ON TOP of the
        action's base XP + concept bonus. Used by the quest stack to
        apply per-quest bonuses (e.g. ``bonus_xp_no_hints``) through
        the same level-up detection path as the base award, so a
        player who crosses a level boundary from the bonus ALONE
        still sees a level-up banner. Negative values are clamped
        to 0 to keep award_xp a monotonic function.
        """
        report = AwardReport()
        gain = xp_for(action) + max(0, int(extra_xp))
        # Concept discovery stacks an additional reward ON TOP of the
        # action's base XP.
        if concept and concept not in self.discovered_concepts:
            if area_for_concept(concept) is not None:
                self.discovered_concepts.append(concept)
                report.concept_discovered = True
                gain += xp_for("concept_discovered")

        if gain <= 0:
            # Still bump counters so badges can unlock on counter
            # thresholds even for zero-XP actions.
            self._bump_counter(action)
            return report

        old_level = self.level
        self.xp += gain
        report.xp_gained = gain
        new_level = self.level
        if new_level > old_level:
            report.level_up = LevelUp(
                old_level=old_level, new_level=new_level, xp_total=self.xp
            )

        if skill is not None and skill in SKILLS:
            old_skill_lvl = self.skill_level(skill)
            self.skills[skill] = self.skills.get(skill, 0) + gain
            new_skill_lvl = self.skill_level(skill)
            if new_skill_lvl > old_skill_lvl:
                report.skill_up = SkillLevelUp(
                    skill=skill, old_level=old_skill_lvl, new_level=new_skill_lvl
                )

        self._bump_counter(action)
        return report

    def note_event(self, event: str) -> None:
        """Bump a bare counter without awarding XP. Used by badge
        triggers that only care about occurrence counts."""
        self._bump_counter(event)

    def _bump_counter(self, key: str) -> None:
        self.counters[key] = self.counters.get(key, 0) + 1

    def touch_streak(self, now: Any = None) -> int:
        """Record activity for *now* and return the current streak.

        Rules:
          * First ever call → streak becomes 1.
          * Same calendar day as ``last_active_date`` → no change.
          * Exactly one day later → streak += 1.
          * Any larger gap → streak resets to 1.

        ``now`` defaults to ``datetime.now()`` so callers can inject
        a fixed time in tests.
        """
        from datetime import datetime
        if now is None:
            now = datetime.now()
        today = now.date().isoformat()
        last = self.last_active_date
        if not last:
            self.streak_days = 1
            self.last_active_date = today
            return self.streak_days
        if last == today:
            return self.streak_days
        try:
            last_date = datetime.fromisoformat(last).date()
        except ValueError:
            self.streak_days = 1
            self.last_active_date = today
            return self.streak_days
        gap = (now.date() - last_date).days
        if gap == 1:
            self.streak_days += 1
        else:
            self.streak_days = 1
        self.last_active_date = today
        return self.streak_days

    def unlock_badge(self, badge: str) -> bool:
        """Unlock a badge if not already owned. Returns True on first
        unlock so the caller can append a banner."""
        if badge in self.badges:
            return False
        self.badges.append(badge)
        return True

    # -----------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "display_name": self.display_name,
            "xp": self.xp,
            "skills": dict(self.skills),
            "badges": list(self.badges),
            "discovered_concepts": list(self.discovered_concepts),
            "counters": dict(self.counters),
            "session_started_at": self.session_started_at,
            "total_sessions": self.total_sessions,
            "streak_days": self.streak_days,
            "last_active_date": self.last_active_date,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], path: Path) -> "PlayerProfile":
        return cls(
            path=path,
            version=int(data.get("version", PROFILE_VERSION)),
            display_name=str(data.get("display_name", "dev")),
            xp=max(0, int(data.get("xp", 0))),
            skills={str(k): int(v) for k, v in (data.get("skills") or {}).items()},
            badges=list(data.get("badges") or []),
            discovered_concepts=list(data.get("discovered_concepts") or []),
            counters={str(k): int(v) for k, v in (data.get("counters") or {}).items()},
            session_started_at=float(data.get("session_started_at", time.time())),
            total_sessions=int(data.get("total_sessions", 0)),
            streak_days=int(data.get("streak_days", 0)),
            last_active_date=str(data.get("last_active_date", "")),
        )

    def save(self) -> None:
        """Atomically persist to ``self.path``. Silently swallows
        filesystem errors so a flaky disk can't crash the TUI."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # tempfile + os.replace = crash-safe write. The old file
            # stays intact until the rename commits.
            fd, tmp_name = tempfile.mkstemp(
                prefix=".player-", suffix=".tmp", dir=str(self.path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(self.to_dict(), fh, indent=2, ensure_ascii=False)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, self.path)
            except Exception:
                # Clean up the temp file if rename failed — don't
                # leave ``.player-XXXX.tmp`` litter behind.
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError:
            # Disk full / permission denied / etc. — non-fatal for
            # the app; progression will just fail to persist this turn.
            pass

    @classmethod
    def load(cls, path: Path | None = None) -> "PlayerProfile":
        """Load a profile from *path*, or return a fresh default
        profile if the file is missing / malformed. Never raises."""
        p = Path(path) if path is not None else DEFAULT_PROFILE_PATH
        if not p.exists():
            return cls(path=p)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls(path=p)
            return cls.from_dict(data, p)
        except (OSError, json.JSONDecodeError, ValueError):
            return cls(path=p)

    # -----------------------------------------------------------------
    # Perks (passive modifiers applied elsewhere)
    # -----------------------------------------------------------------

    def active_perks(self) -> list[str]:
        """Flat list of perk names the player has earned. Consumed by
        UI code that wants to apply subtle modifiers (e.g. unlock
        colors, add keybindings). Keep names lowercase/snake_case so
        matching is unambiguous.
        """
        perks: list[str] = []
        if self.level >= 5:
            perks.append("ghost_lines_unlock")
        if self.level >= 10:
            perks.append("xp_bar_unlock")
        if self.level >= 20:
            perks.append("compact_mode")
        if self.level >= 30:
            perks.append("rainbow_border")
        if self.level >= 40:
            perks.append("party_pacman")
        if self.level >= 50:
            perks.append("boss_badge_glow")
        if self.skill_level("debugging") >= 5:
            perks.append("debug_scrub_hints")
        if self.skill_level("planning") >= 5:
            perks.append("auto_focus_prompt")
        if self.skill_level("learning") >= 5:
            perks.append("concept_map_unlock")
        # Phase 22 — level-gated perks. Names are snake_case so UI code
        # can feature-test without string munging. These stack with the
        # older "*_unlock" names above; never rename either set.
        if self.level >= 2:
            perks.append("apprentice")
        if self.level >= 3:
            perks.append("cartographer")
        if self.level >= 4:
            perks.append("ghost_lines_idle")
        if self.level >= 5:
            perks.append("hint_token")
        if self.level >= 7:
            perks.append("oracle")
        if self.level >= 10:
            perks.append("veteran")
        if self.level >= 13:
            perks.append("sage")
        if self.level >= 15:
            perks.append("architect")
        return perks
