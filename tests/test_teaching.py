"""Tests for ``src_local.teaching`` — adaptive engine, delivery router,
character sheet renderer."""

from __future__ import annotations

from src_local.teaching.adaptive import (
    DifficultyEngine,
    difficulty_instructions,
)
from src_local.teaching.character_sheet import collect, render
from src_local.teaching.delivery import (
    build_lesson_prompt,
    pick_backend,
    plan_lesson,
)


# ---------------------------------------------------------------------------
# DifficultyEngine
# ---------------------------------------------------------------------------


class TestDifficultyEngine:
    def test_no_signals_is_novice(self) -> None:
        fam = DifficultyEngine().score("recursion")
        assert fam.tier == "novice"
        assert fam.score == 0
        assert "no prior signal" in fam.rationale

    def test_empty_topic_is_novice(self) -> None:
        fam = DifficultyEngine().score("")
        assert fam.tier == "novice"
        assert "no topic" in fam.rationale

    def test_preference_signal_bumps_tier(self) -> None:
        events = [
            {"type": "learned", "value": "recursion deep dive"},
            {"type": "used",    "value": "recursion in parser"},
            {"type": "used",    "value": "recursion fib example"},
        ]
        eng = DifficultyEngine(pref_query=lambda _t: events)
        fam = eng.score("recursion")
        assert fam.score >= 3
        assert fam.tier in {"intermediate", "advanced"}
        assert "pref event" in fam.rationale

    def test_memory_signal_alone_capped(self) -> None:
        hits = [{"text": f"mem {i}"} for i in range(10)]
        eng = DifficultyEngine(memory_search=lambda _t: hits)
        fam = eng.score("graphql")
        # Memory signal caps at 3 -- novice by itself.
        assert fam.score == 3
        assert fam.tier == "intermediate"

    def test_skill_signal_maps_to_score(self) -> None:
        eng = DifficultyEngine(skill_level=lambda _t: 5)
        fam = eng.score("python")
        assert fam.score == 5
        assert fam.tier == "intermediate"

    def test_combined_signals_reach_advanced(self) -> None:
        eng = DifficultyEngine(
            pref_query=lambda _t: [
                {"type": "learned", "value": "asyncio basics"},
                {"type": "used", "value": "asyncio in prod"},
                {"type": "used", "value": "asyncio patterns"},
            ],
            memory_search=lambda _t: [{"text": "m"} for _ in range(3)],
            skill_level=lambda _t: 3,
        )
        fam = eng.score("asyncio")
        assert fam.tier == "advanced"

    def test_pref_query_exception_does_not_break(self) -> None:
        def boom(_t: str) -> list[dict]:
            raise RuntimeError("nope")

        fam = DifficultyEngine(pref_query=boom).score("x")
        assert fam.tier == "novice"

    def test_instructions_vary_by_tier(self) -> None:
        novice = difficulty_instructions("novice")
        inter = difficulty_instructions("intermediate")
        adv = difficulty_instructions("advanced")
        assert "NOVICE" in novice
        assert "INTERMEDIATE" in inter
        assert "ADVANCED" in adv


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


class TestPickBackend:
    def test_prefers_claude_when_available(self) -> None:
        assert pick_backend({"ollama", "claude"}) == "claude"

    def test_prefers_codex_over_ollama(self) -> None:
        assert pick_backend({"ollama", "codex"}) == "codex"

    def test_falls_back_to_ollama(self) -> None:
        assert pick_backend({"ollama"}) == "ollama"

    def test_falls_back_when_empty(self) -> None:
        assert pick_backend(set()) == "ollama"

    def test_pinned_wins_when_available(self) -> None:
        assert pick_backend({"ollama", "claude"}, pinned="ollama") == "ollama"

    def test_pinned_ignored_when_unavailable(self) -> None:
        # pinned=claude but only ollama available -> ollama.
        assert pick_backend({"ollama"}, pinned="claude") == "ollama"


class TestLessonPrompt:
    def test_prompt_includes_topic_and_difficulty(self) -> None:
        p = build_lesson_prompt("recursion", "The user is NOVICE.")
        assert "recursion" in p
        assert "NOVICE" in p
        for header in ("**What**", "**Why**", "**How**", "**Gotcha**", "**Next**"):
            assert header in p

    def test_blank_topic_uses_placeholder(self) -> None:
        p = build_lesson_prompt("", "note")
        assert "(unspecified)" in p

    def test_plan_lesson_composes_correctly(self) -> None:
        plan = plan_lesson("graphs", {"claude", "ollama"}, "note")
        assert plan.backend == "claude"
        assert plan.topic == "graphs"
        assert "graphs" in plan.prompt
        assert "note" in plan.prompt


# ---------------------------------------------------------------------------
# Character sheet
# ---------------------------------------------------------------------------


class _FakeProfile:
    def __init__(
        self,
        *,
        level: int = 3,
        xp: int = 42,
        xp_to_next: int = 100,
        skills: dict[str, int] | None = None,
        badges: list[str] | None = None,
    ) -> None:
        self.level = level
        self.xp = xp
        self.xp_to_next = xp_to_next
        self.skills = skills or {}
        self.badges = badges or []


class TestCharacterSheet:
    def test_collect_reads_fields(self) -> None:
        p = _FakeProfile(skills={"python": 5}, badges=["first-run"])
        s = collect(p)
        assert s.level == 3
        assert s.xp == 42
        assert s.skills == {"python": 5}
        assert s.badges == ["first-run"]

    def test_collect_handles_missing_attrs(self) -> None:
        class Bare: ...
        s = collect(Bare())
        assert s.level == 1
        assert s.xp == 0
        assert s.skills == {}
        assert s.badges == []

    def test_render_contains_core_labels(self) -> None:
        out = render(_FakeProfile(), persona="dad")
        assert "CHARACTER SHEET" in out
        assert "Level" in out
        assert "Persona: dad" in out

    def test_render_sorts_skills_by_level(self) -> None:
        p = _FakeProfile(skills={"go": 2, "python": 7, "rust": 4})
        out = render(p)
        lines = out.splitlines()
        skill_lines = [ln for ln in lines if ln.strip().startswith("- ")]
        assert len(skill_lines) == 3
        # python (7) first, then rust (4), then go (2).
        assert "python" in skill_lines[0]
        assert "rust" in skill_lines[1]
        assert "go" in skill_lines[2]

    def test_render_truncates_long_skill_list(self) -> None:
        skills = {f"s{i}": i for i in range(20)}
        out = render(_FakeProfile(skills=skills))
        assert "+8 more" in out  # 20 total, first 12 shown.

    def test_render_shows_badges(self) -> None:
        out = render(_FakeProfile(badges=["first-run", "ten-quests"]))
        assert "first-run" in out
