"""End-to-end-ish tests for the Phase 3/4 slash commands.

Uses a sandboxed ``HOME`` so JSON state lives in tmp_path and the
user's real ``~/.lilbro-local/`` is never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src_local.commands.handler import CommandHandler


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Path.home() on Windows prefers USERPROFILE.
    return tmp_path


class TestRoadmapCommand:
    def test_roadmap_empty(self) -> None:
        h = CommandHandler()
        r = h.handle("/roadmap")
        assert r.bypass_agent
        assert "empty" in r.message.lower()

    def test_milestone_add_then_roadmap_shows_it(self) -> None:
        h = CommandHandler()
        r = h.handle("/milestone Ship auth rewrite")
        assert "milestone locked" in r.message
        r2 = h.handle("/roadmap")
        assert "Ship auth rewrite" in r2.message

    def test_milestone_start_and_done(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone foo").message.split()[2]
        r = h.handle(f"/milestone start {mid}")
        assert "IN_PROGRESS" in r.message
        r2 = h.handle(f"/milestone done {mid}")
        assert "COMPLETED" in r2.message

    def test_milestone_delete(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone x").message.split()[2]
        r = h.handle(f"/milestone delete {mid}")
        assert "deleted" in r.message

    def test_milestone_usage_when_blank(self) -> None:
        h = CommandHandler()
        r = h.handle("/milestone")
        assert "usage" in r.message.lower()


class TestTaskCommand:
    def test_task_add_and_list(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone m").message.split()[2]
        r = h.handle(f"/task add {mid} write schema")
        assert "task added" in r.message
        r2 = h.handle("/task list")
        assert "write schema" in r2.message

    def test_task_lifecycle(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone m").message.split()[2]
        add_msg = h.handle(f"/task add {mid} step one").message
        tid = next(tok for tok in add_msg.split() if tok.startswith("T-"))
        assert h.handle(f"/task start {tid}").message.endswith("step one")
        # render_summary uses icons: [>] = IN_PROGRESS, [x] = COMPLETED.
        assert "[>]" in h.handle("/task list").message
        assert "COMPLETED" in h.handle(f"/task done {tid}").message
        assert "deleted" in h.handle(f"/task delete {tid}").message

    def test_task_add_missing_milestone(self) -> None:
        h = CommandHandler()
        r = h.handle("/task add M-nope hello")
        assert "no milestone" in r.message


class TestBrainstormAndPlanTasks:
    def test_brainstorm_routes_to_lil_bro(self) -> None:
        h = CommandHandler()
        r = h.handle("/brainstorm rewrite auth")
        assert r.bypass_agent is False
        assert r.forced_target == "bro"
        assert "rewrite auth" in (r.rewritten_prompt or "")

    def test_plan_tasks_routes_to_big_bro(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone Rewrite auth").message.split()[2]
        r = h.handle(f"/plan-tasks {mid}")
        assert r.bypass_agent is False
        assert r.forced_target == "big"
        assert "Rewrite auth" in (r.rewritten_prompt or "")

    def test_plan_tasks_missing_milestone(self) -> None:
        h = CommandHandler()
        r = h.handle("/plan-tasks M-nope")
        assert "no milestone" in r.message


class TestExecute:
    def test_execute_nothing_to_do(self) -> None:
        h = CommandHandler()
        r = h.handle("/execute")
        assert "nothing to execute" in r.message.lower()

    def test_execute_promotes_and_starts(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone m").message.split()[2]
        add_msg = h.handle(f"/task add {mid} first step").message
        tid = next(tok for tok in add_msg.split() if tok.startswith("T-"))
        r = h.handle("/execute")
        assert r.bypass_agent is False
        assert r.forced_target == "big"
        assert "first step" in (r.rewritten_prompt or "")
        # After execute, the task is marked IN_PROGRESS -- icon is [>].
        listing = h.handle("/task list").message
        assert "[>]" in listing
        assert tid in listing


class TestIceboxCommand:
    def test_capture_and_list(self) -> None:
        h = CommandHandler()
        r = h.handle("/icebox try switching to httpx")
        assert "iceboxed" in r.message
        r2 = h.handle("/icebox list")
        assert "httpx" in r2.message

    def test_drop(self) -> None:
        h = CommandHandler()
        msg = h.handle("/icebox explore X").message
        iid = msg.split()[1].rstrip(":")
        r = h.handle(f"/icebox drop {iid}")
        assert "dropped" in r.message

    def test_promote_requires_milestone(self) -> None:
        h = CommandHandler()
        msg = h.handle("/icebox explore X").message
        iid = msg.split()[1].rstrip(":")
        r = h.handle(f"/icebox promote {iid} M-nope")
        assert "no milestone" in r.message

    def test_promote_creates_task(self) -> None:
        h = CommandHandler()
        mid = h.handle("/milestone m").message.split()[2]
        msg = h.handle("/icebox explore httpx").message
        iid = msg.split()[1].rstrip(":")
        r = h.handle(f"/icebox promote {iid} {mid}")
        assert "promoted" in r.message
        listing = h.handle("/task list").message
        assert "httpx" in listing


class TestPersonaCommands:
    def test_persona_default_is_auto(self) -> None:
        h = CommandHandler()
        r = h.handle("/persona")
        assert "auto" in r.message

    def test_persona_set_and_show(self) -> None:
        h = CommandHandler()
        h.handle("/persona dad")
        assert h.active_persona == "dad"
        r = h.handle("/persona")
        assert "dad" in r.message

    def test_persona_invalid(self) -> None:
        h = CommandHandler()
        r = h.handle("/persona uncle")
        assert "usage" in r.message.lower()

    def test_mom_routes_to_big_bro(self) -> None:
        h = CommandHandler()
        r = h.handle("/mom where are we?")
        assert r.bypass_agent is False
        assert r.forced_target == "big"
        assert "MOM" in (r.rewritten_prompt or "")

    def test_dad_routes_to_big_bro(self) -> None:
        h = CommandHandler()
        r = h.handle("/dad ship it")
        assert r.forced_target == "big"
        assert "DAD" in (r.rewritten_prompt or "")

    def test_grandma_routes_to_lil_bro(self) -> None:
        h = CommandHandler()
        r = h.handle("/grandma what did we try before?")
        assert r.forced_target == "bro"
        assert "GRANDMA" in (r.rewritten_prompt or "")

    def test_persona_direct_requires_arg(self) -> None:
        h = CommandHandler()
        r = h.handle("/dad")
        assert "usage" in r.message.lower()
