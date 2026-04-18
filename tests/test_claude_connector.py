"""Tests for the Claude CLI connector.

Structural tests only — no actual `claude` subprocess is spawned. The
real end-to-end behavior is covered by running the app, but these
tests lock in role-agnostic construction, the system-prompt briefing
shape, and the event-dispatch logic.
"""

from __future__ import annotations

import pytest

from src_local.agents.base import AgentProcess
from src_local.agents.claude_agent import (
    ClaudeAgent,
    build_sibling_briefing,
    check_claude_health,
)


class _FakePanel:
    def __init__(self) -> None:
        self.system: list[str] = []
        self.errors: list[str] = []
        self.chunks: list[str] = []
        self.complete: list[str] = []
        self.tool_calls: list[tuple[str, str, str | None]] = []
        self.thinking = False

    def append_system(self, text: str) -> None:
        self.system.append(text)

    def append_error(self, text: str) -> None:
        self.errors.append(text)

    def append_agent_chunk(self, text: str) -> None:
        self.chunks.append(text)

    def mark_assistant_complete(self, text: str = "") -> None:
        self.complete.append(text)

    def append_tool_call(
        self, summary: str, detail: str = "", *, path: str | None = None
    ) -> None:
        self.tool_calls.append((summary, detail, path))

    def set_thinking(self, thinking: bool) -> None:
        self.thinking = bool(thinking)


def test_is_agent_process_subclass() -> None:
    """Any connector must be interchangeable via the base interface."""
    agent = ClaudeAgent(role="big", display_name="Big Bro")
    assert isinstance(agent, AgentProcess)


def test_role_validation() -> None:
    ClaudeAgent(role="big", display_name="X")
    ClaudeAgent(role="lil", display_name="X")
    with pytest.raises(ValueError):
        ClaudeAgent(role="middle", display_name="X")


def test_restart_key_matches_role() -> None:
    """The /restart key is the role so commands read naturally."""
    big = ClaudeAgent(role="big", display_name="Big Bro")
    lil = ClaudeAgent(role="lil", display_name="Lil Bro")
    assert big.RESTART_KEY == "big"
    assert lil.RESTART_KEY == "lil"


def test_display_name_is_user_provided() -> None:
    """User can label the pane whatever they want — not hard-coded."""
    agent = ClaudeAgent(role="big", display_name="Captain")
    assert agent.display_name == "Captain"
    assert agent.DISPLAY_NAME == "Captain"


def test_briefing_reflects_role_big_with_write() -> None:
    brief = build_sibling_briefing(
        role="big",
        sibling_name="Lil Bro",
        sibling_backend="Ollama (qwen2.5-coder:7b)",
        write_access=True,
    )
    assert "'Big Bro'" in brief
    assert "'Lil Bro'" in brief
    assert "Ollama (qwen2.5-coder:7b)" in brief
    assert "read, write, and edit" in brief
    assert "READ-ONLY" not in brief
    assert "SESSION.md" in brief


def test_briefing_reflects_role_lil_read_only() -> None:
    brief = build_sibling_briefing(
        role="lil",
        sibling_name="Big Bro",
        sibling_backend="Claude (sonnet-4)",
        write_access=False,
    )
    assert "'Lil Bro'" in brief
    assert "'Big Bro'" in brief
    assert "Claude (sonnet-4)" in brief
    assert "READ-ONLY" in brief


def test_set_write_access_persists() -> None:
    agent = ClaudeAgent(role="lil", display_name="Lil", write_access=False)
    assert agent._write_access is False
    agent.set_write_access(True)
    assert agent._write_access is True


def test_set_configured_model_normalizes_empty() -> None:
    agent = ClaudeAgent(role="big", display_name="X", model="sonnet-4")
    assert agent._configured_model == "sonnet-4"
    agent.set_configured_model("")
    assert agent._configured_model is None
    agent.set_configured_model("opus-4")
    assert agent._configured_model == "opus-4"


def test_set_sibling_updates_metadata() -> None:
    agent = ClaudeAgent(role="big", display_name="X")
    agent.set_sibling(sibling_name="New Bro", sibling_backend="Codex")
    assert agent._sibling_name == "New Bro"
    assert agent._sibling_backend == "Codex"


def test_handle_text_delta_appends_chunk() -> None:
    agent = ClaudeAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._turn_started_at = 1.0  # mark a turn live so budget counts
    agent._handle_event({
        "type": "stream_event",
        "event": {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hello world"},
        },
    })
    assert panel.chunks == ["hello world"]


def test_handle_assistant_marks_complete_and_notes_tool_use() -> None:
    agent = ClaudeAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_event({
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "Here's a fix:"},
                {
                    "type": "tool_use",
                    "name": "Edit",
                    "input": {
                        "file_path": "foo.py",
                        "old_string": "a",
                        "new_string": "b",
                    },
                },
            ]
        },
    })
    assert panel.complete == ["Here's a fix:"]
    assert len(panel.tool_calls) == 1
    summary, detail, path = panel.tool_calls[0]
    assert summary.startswith("Edit ")
    assert "foo.py" in summary
    # Detail is a unified diff of old→new
    assert "-a" in detail and "+b" in detail
    assert path == "foo.py"


def test_handle_system_init_announces_once() -> None:
    agent = ClaudeAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_event({
        "type": "system",
        "subtype": "init",
        "session_id": "abc123xy",
        "model": "sonnet-4",
    })
    agent._handle_event({
        "type": "system",
        "subtype": "init",
        "session_id": "abc123xy",
        "model": "sonnet-4",
    })
    # Exactly one connection banner — claude emits init on every turn.
    banners = [m for m in panel.system if "connected" in m]
    assert len(banners) == 1


def test_handle_result_sets_turn_done() -> None:
    agent = ClaudeAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._turn_done.clear()
    agent._handle_event({
        "type": "result",
        "subtype": "success",
        "duration_ms": 1200,
        "total_cost_usd": 0.0042,
    })
    assert agent._turn_done.is_set()
    assert any("done in 1200ms" in m for m in panel.system)


@pytest.mark.asyncio
async def test_check_claude_health_when_missing(monkeypatch) -> None:
    """If `claude` isn't on PATH, health check reports installed=False."""
    import src_local.agents.claude_agent as mod
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    result = await check_claude_health()
    assert result["installed"] is False
    assert result["path"] is None
