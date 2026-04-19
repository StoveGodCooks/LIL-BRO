"""Tests for the roadmap prompt helpers, icebox, and executor."""

from __future__ import annotations

from pathlib import Path

import pytest

from src_local.roadmap.brainstorm import build_brainstorm_prompt
from src_local.roadmap.executor import Executor
from src_local.roadmap.icebox import Icebox
from src_local.roadmap.living_map import LivingMap
from src_local.roadmap.planner import build_plan_prompt, parse_task_list


class TestBrainstormPrompt:
    def test_includes_goal(self) -> None:
        p = build_brainstorm_prompt("ship the auth rewrite")
        assert "ship the auth rewrite" in p
        assert "milestone" in p.lower()

    def test_blank_goal_uses_fallback(self) -> None:
        p = build_brainstorm_prompt("")
        assert "what should we work on" in p.lower()

    def test_prompt_has_all_six_sections(self) -> None:
        p = build_brainstorm_prompt("x")
        for token in ("Restate", "Assumptions", "Unknowns", "constraints",
                      "candidate milestones", "Recommended"):
            assert token in p


class TestPlanPrompt:
    def test_includes_title(self) -> None:
        p = build_plan_prompt("Rewrite auth middleware")
        assert "Rewrite auth middleware" in p
        assert "dash" in p.lower() or "- " in p

    def test_extra_context_included(self) -> None:
        p = build_plan_prompt("x", extra_context="legal flagged tokens")
        assert "legal flagged tokens" in p


class TestParseTaskList:
    def test_dashes(self) -> None:
        out = parse_task_list("- one\n- two\n- three")
        assert out == ["one", "two", "three"]

    def test_asterisks_and_bullets(self) -> None:
        out = parse_task_list("* one\n• two")
        assert out == ["one", "two"]

    def test_numbered(self) -> None:
        out = parse_task_list("1. first\n2) second")
        assert out == ["first", "second"]

    def test_strips_trailing_punct_and_whitespace(self) -> None:
        out = parse_task_list("-   hello world.   ")
        assert out == ["hello world"]

    def test_dedupes_preserving_order(self) -> None:
        out = parse_task_list("- a\n- a\n- b")
        assert out == ["a", "b"]

    def test_ignores_non_list_lines(self) -> None:
        reply = "Here are the tasks:\n\n- one\nplain line\n- two"
        assert parse_task_list(reply) == ["one", "two"]

    def test_caps_at_max(self) -> None:
        reply = "\n".join(f"- t{i}" for i in range(20))
        assert len(parse_task_list(reply, max_tasks=5)) == 5

    def test_empty_input(self) -> None:
        assert parse_task_list("") == []


# ---------------------------------------------------------------------------
# Icebox
# ---------------------------------------------------------------------------


@pytest.fixture
def ice_path(tmp_path: Path) -> Path:
    return tmp_path / "icebox.json"


class TestIcebox:
    def test_add_and_persist(self, ice_path: Path) -> None:
        box = Icebox(ice_path)
        item = box.add("explore switching from requests to httpx")
        assert item.id.startswith("I-")
        assert ice_path.exists()
        box2 = Icebox(ice_path)
        assert len(box2.items) == 1
        assert box2.items[0].text.startswith("explore")

    def test_list_open_excludes_promoted_and_dropped(
        self, ice_path: Path
    ) -> None:
        box = Icebox(ice_path)
        a = box.add("a")
        b = box.add("b")
        c = box.add("c")
        box.drop(a.id)
        box.promote(b.id, "T-xxx")
        open_items = box.list_open()
        assert [i.id for i in open_items] == [c.id]

    def test_promote_missing_returns_false(self, ice_path: Path) -> None:
        box = Icebox(ice_path)
        assert box.promote("I-nope", "T-1") is False


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class TestExecutor:
    def test_prepare_next_returns_none_with_no_milestone(
        self, tmp_path: Path
    ) -> None:
        rm = LivingMap(tmp_path / "r.json")
        assert Executor(rm).prepare_next() is None

    def test_prepare_next_returns_first_backlog_task(
        self, tmp_path: Path
    ) -> None:
        rm = LivingMap(tmp_path / "r.json")
        m = rm.add_milestone("feature")
        rm.set_milestone_state(m.id, "IN_PROGRESS")
        rm.add_task(m.id, "first")
        rm.add_task(m.id, "second")
        step = Executor(rm).prepare_next()
        assert step is not None
        assert step.task.title == "first"
        assert step.milestone.id == m.id
        assert step.task_id == step.task.id
        assert "first" in step.brief_prompt
        assert step.task.id in step.brief_prompt

    def test_prepare_next_honors_milestone_override(
        self, tmp_path: Path
    ) -> None:
        rm = LivingMap(tmp_path / "r.json")
        m1 = rm.add_milestone("one")
        m2 = rm.add_milestone("two")
        rm.add_task(m1.id, "a")
        rm.add_task(m2.id, "b")
        step = Executor(rm).prepare_next(m2.id)
        assert step is not None
        assert step.task.title == "b"

    def test_start_complete_block_transitions(self, tmp_path: Path) -> None:
        rm = LivingMap(tmp_path / "r.json")
        m = rm.add_milestone("feature")
        rm.set_milestone_state(m.id, "IN_PROGRESS")
        t = rm.add_task(m.id, "a")
        ex = Executor(rm)
        assert ex.start(t.id).state == "IN_PROGRESS"
        assert ex.block(t.id, "waiting on schema").state == "BLOCKED"
        assert ex.complete(t.id).state == "COMPLETED"

    def test_prepare_next_none_when_all_done(self, tmp_path: Path) -> None:
        rm = LivingMap(tmp_path / "r.json")
        m = rm.add_milestone("feature")
        rm.set_milestone_state(m.id, "IN_PROGRESS")
        t = rm.add_task(m.id, "only")
        rm.set_task_state(t.id, "COMPLETED")
        assert Executor(rm).prepare_next() is None
