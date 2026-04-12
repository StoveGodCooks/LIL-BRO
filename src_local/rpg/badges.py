"""Badge catalog + unlock checker.

23 badges split into two groups:

* **Skill badges** — 3 tiers × 5 skills = 15. Unlocked by repeating a
  domain action enough times (e.g. edit 50 files → "architect").
* **Meta badges** — 8 cross-cutting achievements (reach level 5, play
  a 3-hour session, discover a concept in every area, etc.).

Every badge has:

* ``key``         — stable machine id (snake_case, never rename)
* ``name``        — display name
* ``description`` — short flavor text
* ``trigger``     — a callable ``(profile, event) -> bool`` deciding
                    whether the badge unlocks *right now*. The checker
                    passes every action-key and counter state in; the
                    trigger reads whatever it needs off the profile.

``check_badges(profile, event)`` is called by the UI/router after every
``award_xp`` call. It walks the catalog, unlocks any newly-qualifying
badge on the profile, and returns the list of freshly-unlocked names
so the caller can append banner lines.

Triggers deliberately read live counters off the profile rather than
taking the event payload verbatim — that way we never miss an unlock
because an event was routed through ``note_event`` instead of
``award_xp`` (or vice versa).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Final

from src_local.rpg.xp import CONCEPTS


# ---------------------------------------------------------------------
# Badge records
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class Badge:
    key: str
    name: str
    description: str
    trigger: Callable[["_Profile", str], bool]


# The trigger callable takes a PlayerProfile-shaped object. We don't
# import it at module load time to avoid a circular import — badges.py
# is imported FROM player.py via check_badges. The protocol below is
# all we need from a profile.
class _Profile:  # pragma: no cover — typing shim only
    xp: int
    counters: dict[str, int]
    badges: list[str]
    discovered_concepts: list[str]

    def skill_level(self, skill: str) -> int: ...  # noqa: D401,E704
    @property
    def level(self) -> int: ...  # noqa: D401,E704


# ---------------------------------------------------------------------
# Trigger helpers — small closures keep the catalog readable
# ---------------------------------------------------------------------


def _counter_at_least(key: str, n: int) -> Callable[["_Profile", str], bool]:
    def trig(profile: "_Profile", _event: str) -> bool:
        return profile.counters.get(key, 0) >= n
    return trig


def _level_at_least(n: int) -> Callable[["_Profile", str], bool]:
    def trig(profile: "_Profile", _event: str) -> bool:
        return profile.level >= n
    return trig


def _concepts_discovered(n: int) -> Callable[["_Profile", str], bool]:
    def trig(profile: "_Profile", _event: str) -> bool:
        return len(profile.discovered_concepts) >= n
    return trig


def _one_concept_per_area(profile: "_Profile", _event: str) -> bool:
    found: set[str] = set()
    for tag in profile.discovered_concepts:
        for area, tags in CONCEPTS.items():
            if tag in tags:
                found.add(area)
    return len(found) >= len(CONCEPTS)


def _badge_count_at_least(n: int) -> Callable[["_Profile", str], bool]:
    # NB: self-referential — "earn 10 badges" counts the other 22. We
    # subtract 1 for the completionist badge itself in case it's in the
    # list during the check (it isn't, because we unlock in order).
    def trig(profile: "_Profile", _event: str) -> bool:
        return len([b for b in profile.badges if b != "completionist"]) >= n
    return trig


# ---------------------------------------------------------------------
# The catalog — 23 badges, order matters (earlier unlocks first)
# ---------------------------------------------------------------------


BADGES: Final[tuple[Badge, ...]] = (
    # ----- skill: coding -----
    Badge(
        "first_edit", "First Edit",
        "Big Bro wrote a file on your behalf.",
        _counter_at_least("file_edited", 1),
    ),
    Badge(
        "builder", "Builder",
        "Ship 10 file edits.",
        _counter_at_least("file_edited", 10),
    ),
    Badge(
        "architect", "Architect",
        "Ship 50 file edits. You've built something real.",
        _counter_at_least("file_edited", 50),
    ),

    # ----- skill: debugging -----
    Badge(
        "bug_hunter", "Bug Hunter",
        "Use /debug for the first time.",
        _counter_at_least("debug_used", 1),
    ),
    Badge(
        "exterminator", "Exterminator",
        "Use /debug 10 times.",
        _counter_at_least("debug_used", 10),
    ),
    Badge(
        "rubber_ducker", "Rubber Ducker",
        "Use /debug 25 times — most bugs give up when you explain them.",
        _counter_at_least("debug_used", 25),
    ),

    # ----- skill: learning -----
    Badge(
        "curious", "Curious",
        "Use /explain for the first time.",
        _counter_at_least("explain_used", 1),
    ),
    Badge(
        "scholar", "Scholar",
        "Discover 10 distinct concepts from the catalog.",
        _concepts_discovered(10),
    ),
    Badge(
        "polymath", "Polymath",
        "Discover 25 distinct concepts.",
        _concepts_discovered(25),
    ),

    # ----- skill: reviewing -----
    Badge(
        "reviewer", "Reviewer",
        "Use /review for the first time.",
        _counter_at_least("review_used", 1),
    ),
    Badge(
        "critic", "Critic",
        "Use /review 10 times.",
        _counter_at_least("review_used", 10),
    ),
    Badge(
        "sentinel", "Sentinel",
        "Use /review 25 times.",
        _counter_at_least("review_used", 25),
    ),

    # ----- skill: planning -----
    Badge(
        "planner", "Planner",
        "Use /plan for the first time.",
        _counter_at_least("plan_before_code", 1),
    ),
    Badge(
        "strategist", "Strategist",
        "Use /plan 10 times.",
        _counter_at_least("plan_before_code", 10),
    ),
    Badge(
        "chessmaster", "Chessmaster",
        "Use /plan 25 times — measure twice, cut once.",
        _counter_at_least("plan_before_code", 25),
    ),

    # ----- meta -----
    Badge(
        "welcome", "Welcome to LIL BRO",
        "Your first session.",
        _counter_at_least("session_start", 1),
    ),
    Badge(
        "level_5", "Apprentice",
        "Reach level 5.",
        _level_at_least(5),
    ),
    Badge(
        "level_25", "Journeyman",
        "Reach level 25.",
        _level_at_least(25),
    ),
    Badge(
        "level_60", "Grandmaster",
        "Reach level 60 — max level.",
        _level_at_least(60),
    ),
    Badge(
        "marathoner", "Marathoner",
        "Complete a 3-hour continuous session.",
        _counter_at_least("session_3_hours", 1),
    ),
    Badge(
        "explorer", "Explorer",
        "Discover at least one concept from every catalog area.",
        _one_concept_per_area,
    ),
    Badge(
        "journalist", "Journalist",
        "Save the journal 10 times.",
        _counter_at_least("journal_save", 10),
    ),
    Badge(
        "completionist", "Completionist",
        "Earn 10 other badges.",
        _badge_count_at_least(10),
    ),

    # ----- Phase 20 quest/campaign badges -----
    Badge(
        "speed_run", "Speedrunner",
        "Finish a quest under the par time.",
        _counter_at_least("quest_speedrun", 1),
    ),
    Badge(
        "no_hints", "No Hints Needed",
        "Clear 5 quests without using a single hint.",
        _counter_at_least("quest_no_hints_clean", 5),
    ),
    Badge(
        "boss_slayer", "Boss Slayer",
        "Defeat the final boss of the Codelands.",
        _counter_at_least("boss_slayer", 1),
    ),
    Badge(
        "cave_crawler", "Cave Crawler",
        "Complete a quest in The Cave.",
        _counter_at_least("area_completed_cave", 1),
    ),
    Badge(
        "loop_lord", "Loop Lord",
        "Complete a quest in Loop Labyrinth.",
        _counter_at_least("area_completed_loop", 1),
    ),
    Badge(
        "lord_of_the_keep", "Lord of the Keep",
        "Complete a quest in the OOP Keep.",
        _counter_at_least("area_completed_oop", 1),
    ),
    Badge(
        "event_loop_operator", "Event Loop Operator",
        "Complete a quest in the Async Expanse.",
        _counter_at_least("area_completed_async", 1),
    ),
    Badge(
        "exception_handler", "Exception Handler",
        "Complete a quest in the Error Marsh.",
        _counter_at_least("area_completed_marsh", 1),
    ),
)


assert len(BADGES) == 31, f"badge catalog expected 31 entries, got {len(BADGES)}"
assert len({b.key for b in BADGES}) == 31, "duplicate badge key detected"


# ---------------------------------------------------------------------
# Runtime check
# ---------------------------------------------------------------------


def check_badges(profile: "_Profile", event: str = "") -> list[str]:
    """Walk the catalog and unlock any freshly-qualifying badges.

    Returns the *names* of newly unlocked badges (not keys) so the
    caller can use them directly in banner lines. Also bumps the
    ``badge_earned`` counter on the profile for each unlock — that's
    what the XP engine reads to award the ``badge_earned`` bonus.

    ``event`` is the action key that triggered the check (optional —
    every trigger reads live counters anyway). Mostly useful for
    future instrumentation.
    """
    unlocked: list[str] = []
    for badge in BADGES:
        if badge.key in profile.badges:
            continue
        try:
            if badge.trigger(profile, event):
                profile.badges.append(badge.key)
                profile.counters["badge_earned"] = (
                    profile.counters.get("badge_earned", 0) + 1
                )
                unlocked.append(badge.name)
        except Exception:
            # A broken trigger shouldn't crash the whole unlock pass —
            # log-and-continue so the other 22 badges still work.
            continue
    return unlocked


def badge_by_key(key: str) -> Badge | None:
    for b in BADGES:
        if b.key == key:
            return b
    return None


def badge_name(key: str) -> str:
    """Friendly display for a stored key. Falls back to the key itself
    so old profiles with badges we've since removed still render."""
    b = badge_by_key(key)
    return b.name if b is not None else key
