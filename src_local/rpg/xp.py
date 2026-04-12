"""XP tables, action rewards, level thresholds, and concept catalog.

This module is **pure data** + **tiny helpers**. No I/O, no side
effects, no mutation — every public function is a pure look-up so
tests can pin the values at will.

Actions → XP
------------
Every user action that the rest of LIL BRO routes through
``PlayerProfile.award_xp(action_key, ...)`` needs a row here.
Unknown keys return 0 XP (silently, so adding instrumentation
doesn't crash).

Levels
------
60 levels total. The XP needed to reach level N is cumulative and
follows a gentle quadratic curve: level 1 at 0 XP, level 60 at
~60_000 XP. Early levels are cheap (first hour of use should earn
~3–5 levels), late levels taper (top levels demand consistent
multi-week engagement). The table is hard-coded rather than
computed so an auditor reading the file can see the contract.

Skills
------
Five domain skills that level independently, capped at 10 each.
Each skill has its own XP table (shallower curve than overall
level). Skills unlock passive perks (applied elsewhere in the
``PlayerProfile``).

Concepts
--------
The catalog of "things you can learn" that earn Concept XP. Used
by ``/explain``, ``/review``, ``/compare`` and friends to tag the
topic. Unknown concepts still earn XP (the catalog is a hint for
the UI, not a gate) but aren't tracked in the discovered set.
"""

from __future__ import annotations

from typing import Final


# ---------------------------------------------------------------------
# Action → XP
# ---------------------------------------------------------------------

XP_ACTIONS: Final[dict[str, int]] = {
    # Everyday usage — keep these small so grinding doesn't dominate.
    "user_turn":            2,    # sent any prompt
    "slash_command":        1,    # used a slash command
    "journal_save":         3,    # /save
    "focus_set":            5,    # /focus <goal>
    "focus_completed":      15,   # /focus cleared after >2min on a goal

    # Learning actions — the meat of the progression curve.
    "explain_used":         10,   # /explain <topic>
    "compare_used":         12,   # /compare a vs b
    "review_used":          8,    # /review
    "debug_used":           10,   # /debug
    "trace_used":           8,    # /trace
    "explain_diff_used":    12,   # /explain-diff
    "review_file_used":     12,   # /review-file

    # Workflow actions — reward planning + verification.
    "plan_before_code":     15,   # /plan <task>
    "cross_talk_port":      5,    # Ctrl+C / Ctrl+B port
    "retry_success":        4,    # Ctrl+R after a crash and it worked
    "notes_saved":          3,    # Ctrl+S in NotesPad

    # File actions — big rewards to encourage real work.
    "file_edited":          20,   # Big Bro wrote a file
    "file_created":         25,   # Big Bro created a new file
    "tests_run":            15,   # user invoked a test command

    # Concept discovery — bonus on first encounter.
    "concept_discovered":   10,   # any new concept tag
    "badge_earned":         25,   # any badge unlock

    # Session milestones.
    "session_start":        1,    # per process start
    "session_1_hour":       20,   # continuous session 60+ min
    "session_3_hours":      60,

    # Quest / campaign actions (Phase 18). Quest completion awards a
    # flat base; the bonus fields are counter-style (zero XP here,
    # payout comes from quest.bonus_xp_no_hints + badge unlocks).
    "quest_completed":      30,
    "quest_no_hints_bonus":  0,
    "quest_skipped":         0,
    "quest_speedrun":        0,
    "boss_slayer":           0,
    "area_completed":        0,
}


def xp_for(action: str) -> int:
    """Return the XP reward for *action*, or 0 for unknown keys."""
    return XP_ACTIONS.get(action, 0)


# ---------------------------------------------------------------------
# Level table — cumulative XP needed for each level
# ---------------------------------------------------------------------
#
# Generated with:
#     LEVEL_TABLE[N] = int(round(12 * N ** 1.85))  for N in 1..60
# but hard-coded so auditors don't have to run Python to read the file.
# Level 1 starts at 0 XP (you begin the game at lvl 1).

LEVEL_TABLE: Final[list[int]] = [
    0,       # 1
    43,      # 2
    91,      # 3
    154,     # 4
    231,     # 5
    322,     # 6
    425,     # 7
    541,     # 8
    668,     # 9
    806,     # 10
    955,     # 11
    1115,    # 12
    1285,    # 13
    1465,    # 14
    1655,    # 15
    1854,    # 16
    2062,    # 17
    2280,    # 18
    2506,    # 19
    2742,    # 20
    2986,    # 21
    3239,    # 22
    3500,    # 23
    3770,    # 24
    4048,    # 25
    4334,    # 26
    4628,    # 27
    4930,    # 28
    5240,    # 29
    5558,    # 30
    5884,    # 31
    6217,    # 32
    6558,    # 33
    6906,    # 34
    7262,    # 35
    7625,    # 36
    7995,    # 37
    8373,    # 38
    8758,    # 39
    9150,    # 40
    9549,    # 41
    9955,    # 42
    10368,   # 43
    10788,   # 44
    11215,   # 45
    11648,   # 46
    12088,   # 47
    12535,   # 48
    12989,   # 49
    13449,   # 50
    13916,   # 51
    14389,   # 52
    14869,   # 53
    15355,   # 54
    15848,   # 55
    16347,   # 56
    16852,   # 57
    17363,   # 58
    17881,   # 59
    18405,   # 60
]

MAX_LEVEL: Final[int] = len(LEVEL_TABLE)  # 60


def level_for_xp(xp: int) -> int:
    """Return the highest level whose threshold <= *xp*. 1 <= ret <= 60.

    Unknown / negative XP clamps to level 1. XP above the level-60
    threshold caps at 60.
    """
    if xp <= 0:
        return 1
    # Reverse linear scan is fast enough (60 entries) and keeps the
    # code trivially inspectable. Could binary-search but there's no
    # measurable win.
    for lvl in range(MAX_LEVEL, 0, -1):
        if xp >= LEVEL_TABLE[lvl - 1]:
            return lvl
    return 1


def xp_to_next(xp: int) -> int:
    """XP remaining until the next level. 0 if already at max level."""
    cur = level_for_xp(xp)
    if cur >= MAX_LEVEL:
        return 0
    return LEVEL_TABLE[cur] - xp  # LEVEL_TABLE is 0-indexed; [cur] is lvl cur+1


def level_progress(xp: int) -> tuple[int, int, int]:
    """Return ``(current_level, xp_into_level, xp_needed_for_level)``.

    Handy for rendering progress bars: ``xp_into_level / xp_needed_for_level``
    is the fill ratio. At max level both of the last two are 0.
    """
    cur = level_for_xp(xp)
    if cur >= MAX_LEVEL:
        return (cur, 0, 0)
    cur_threshold = LEVEL_TABLE[cur - 1]
    next_threshold = LEVEL_TABLE[cur]
    return (cur, xp - cur_threshold, next_threshold - cur_threshold)


# ---------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------
#
# Five domains that level independently. Each skill caps at 10.
# Skill XP is earned alongside overall XP when an action is tagged
# with a domain (via ``PlayerProfile.award_xp(..., skill="coding")``).

SKILLS: Final[tuple[str, ...]] = (
    "coding",       # writing code, editing files, running tests
    "debugging",    # /debug, fixing errors, reading stack traces
    "learning",     # /explain, /compare, concept discovery
    "reviewing",    # /review, /review-file, /explain-diff
    "planning",     # /plan, /focus, structured thinking
)

SKILL_MAX_LEVEL: Final[int] = 10

# XP required to reach each skill level. Shallower curve than the
# overall level table because skills are sub-progressions.
SKILL_LEVELS: Final[list[int]] = [
    0,      # 1
    25,     # 2
    60,     # 3
    110,    # 4
    180,    # 5
    275,    # 6
    400,    # 7
    560,    # 8
    760,    # 9
    1000,   # 10
]


def skill_level_for_xp(xp: int) -> int:
    """Return the skill level (1–10) corresponding to skill XP."""
    if xp <= 0:
        return 1
    for lvl in range(SKILL_MAX_LEVEL, 0, -1):
        if xp >= SKILL_LEVELS[lvl - 1]:
            return lvl
    return 1


# ---------------------------------------------------------------------
# Concept catalog
# ---------------------------------------------------------------------
#
# Known learning tags. When a concept is discovered (via /explain etc.)
# and it matches an entry here, the player unlocks it in their
# ``discovered_concepts`` set and earns the "concept_discovered" bonus.
# Unknown concepts are allowed but don't count toward badges that
# demand "discovered N catalog concepts".

CONCEPTS: Final[dict[str, tuple[str, ...]]] = {
    # Area → concepts
    "python_basics": (
        "variables", "functions", "classes", "dataclasses", "type hints",
        "list comprehensions", "generators", "decorators", "context managers",
    ),
    "async": (
        "asyncio", "async generators", "await", "event loops",
        "tasks", "futures", "cancellation", "timeouts",
    ),
    "testing": (
        "pytest", "fixtures", "monkeypatch", "parametrize", "mocking",
        "assertions", "coverage", "integration tests",
    ),
    "web": (
        "http", "rest", "json", "async web", "websockets",
        "sessions", "cookies", "cors",
    ),
    "data": (
        "sqlite", "transactions", "indexes", "joins", "migrations",
        "pandas", "csv", "parquet",
    ),
}


def all_concept_tags() -> set[str]:
    """Flat set of every known concept tag across all areas."""
    out: set[str] = set()
    for tags in CONCEPTS.values():
        out.update(tags)
    return out


def area_for_concept(concept: str) -> str | None:
    """Return the area a concept belongs to, or None if not cataloged."""
    for area, tags in CONCEPTS.items():
        if concept in tags:
            return area
    return None
