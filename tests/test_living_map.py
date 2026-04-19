"""Tests for ``src_local.roadmap.living_map.LivingMap``."""

from __future__ import annotations

from pathlib import Path

import pytest

from src_local.roadmap.living_map import LivingMap


@pytest.fixture
def rm_path(tmp_path: Path) -> Path:
    return tmp_path / "roadmap.json"


class TestMilestones:
    def test_add_milestone_assigns_short_id(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("Ship auth rewrite", description="gating")
        assert m.id.startswith("M-")
        assert m.state == "BACKLOG"
        assert m.description == "gating"

    def test_milestone_survives_reload(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("Pick DB driver")
        rm2 = LivingMap(rm_path)
        assert len(rm2.milestones) == 1
        assert rm2.milestones[0].id == m.id

    def test_only_one_in_progress_milestone(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m1 = rm.add_milestone("A")
        m2 = rm.add_milestone("B")
        rm.set_milestone_state(m1.id, "IN_PROGRESS")
        rm.set_milestone_state(m2.id, "IN_PROGRESS")
        assert rm.find_milestone(m1.id).state == "BACKLOG"
        assert rm.find_milestone(m2.id).state == "IN_PROGRESS"

    def test_set_milestone_state_rejects_invalid(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("x")
        with pytest.raises(ValueError):
            rm.set_milestone_state(m.id, "GARBAGE")  # type: ignore[arg-type]

    def test_delete_milestone_returns_false_when_missing(
        self, rm_path: Path
    ) -> None:
        rm = LivingMap(rm_path)
        assert rm.delete_milestone("M-nope") is False

    def test_delete_milestone_true_when_removed(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("x")
        assert rm.delete_milestone(m.id) is True
        assert rm.find_milestone(m.id) is None


class TestTasks:
    def test_add_task_to_missing_milestone_returns_none(
        self, rm_path: Path
    ) -> None:
        rm = LivingMap(rm_path)
        assert rm.add_task("M-nope", "x") is None

    def test_add_task_appended_to_milestone(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t = rm.add_task(m.id, "draft schema")
        assert t is not None
        assert t.id.startswith("T-")
        m = rm.find_milestone(m.id)
        assert m.tasks[0].id == t.id

    def test_set_task_state_transitions(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t = rm.add_task(m.id, "step 1")
        rm.set_task_state(t.id, "IN_PROGRESS")
        hit = rm.find_task(t.id)
        assert hit is not None
        assert hit[1].state == "IN_PROGRESS"
        rm.set_task_state(t.id, "COMPLETED")
        assert rm.find_task(t.id)[1].state == "COMPLETED"

    def test_only_one_in_progress_task_per_milestone(
        self, rm_path: Path
    ) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t1 = rm.add_task(m.id, "a")
        t2 = rm.add_task(m.id, "b")
        rm.set_task_state(t1.id, "IN_PROGRESS")
        rm.set_task_state(t2.id, "IN_PROGRESS")
        assert rm.find_task(t1.id)[1].state == "BACKLOG"
        assert rm.find_task(t2.id)[1].state == "IN_PROGRESS"

    def test_delete_task(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t = rm.add_task(m.id, "a")
        assert rm.delete_task(t.id) is True
        assert rm.find_task(t.id) is None
        assert rm.delete_task(t.id) is False


class TestViews:
    def test_active_milestone_and_task(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t = rm.add_task(m.id, "step")
        assert rm.active_milestone() is None
        rm.set_milestone_state(m.id, "IN_PROGRESS")
        rm.set_task_state(t.id, "IN_PROGRESS")
        assert rm.active_milestone().id == m.id
        assert rm.active_task().id == t.id

    def test_next_backlog_task_skips_done(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("feature")
        t1 = rm.add_task(m.id, "a")
        t2 = rm.add_task(m.id, "b")
        rm.set_milestone_state(m.id, "IN_PROGRESS")
        rm.set_task_state(t1.id, "COMPLETED")
        nxt = rm.next_backlog_task()
        assert nxt is not None
        assert nxt.id == t2.id

    def test_render_summary_empty(self, rm_path: Path) -> None:
        rm = LivingMap(rm_path)
        assert "empty" in rm.render_summary()

    def test_render_summary_includes_titles_and_states(
        self, rm_path: Path
    ) -> None:
        rm = LivingMap(rm_path)
        m = rm.add_milestone("Big Goal")
        rm.add_task(m.id, "Small step")
        out = rm.render_summary()
        assert "Big Goal" in out
        assert "Small step" in out
        assert m.id in out


class TestPersistenceResilience:
    def test_corrupt_file_treated_as_empty(self, rm_path: Path) -> None:
        rm_path.write_text("not json", encoding="utf-8")
        rm = LivingMap(rm_path)
        assert rm.milestones == []
        # Still usable after corrupt load.
        rm.add_milestone("fresh")
        assert len(rm.milestones) == 1

    def test_unknown_task_state_coerced(self, rm_path: Path) -> None:
        rm_path.write_text(
            '{"milestones":[{"id":"M-1","title":"t","state":"WEIRD",'
            '"tasks":[{"id":"T-1","title":"x","state":"????"}]}]}',
            encoding="utf-8",
        )
        rm = LivingMap(rm_path)
        assert rm.milestones[0].state == "BACKLOG"
        assert rm.milestones[0].tasks[0].state == "BACKLOG"
