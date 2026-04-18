"""Tests for the Codex MCP connector.

Structural tests only — no actual `codex` subprocess is spawned. The
real end-to-end behavior is covered by running the app, but these
tests lock in role-agnostic construction, briefing shape, JSON-RPC
dispatch, and event handling.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src_local.agents.base import AgentProcess
from src_local.agents.codex_agent import (
    CodexAgent,
    build_sibling_briefing,
    check_codex_health,
)


class _FakePanel:
    def __init__(self) -> None:
        self.system: list[str] = []
        self.errors: list[str] = []
        self.chunks: list[str] = []
        self.complete: list[str] = []
        self.thinking = False

    def append_system(self, text: str) -> None:
        self.system.append(text)

    def append_error(self, text: str) -> None:
        self.errors.append(text)

    def append_agent_chunk(self, text: str) -> None:
        self.chunks.append(text)

    def mark_assistant_complete(self, text: str = "") -> None:
        self.complete.append(text)

    def set_thinking(self, thinking: bool) -> None:
        self.thinking = bool(thinking)


def test_is_agent_process_subclass() -> None:
    agent = CodexAgent(role="big", display_name="Big Bro")
    assert isinstance(agent, AgentProcess)


def test_role_validation() -> None:
    CodexAgent(role="big", display_name="X")
    CodexAgent(role="lil", display_name="X")
    with pytest.raises(ValueError):
        CodexAgent(role="middle", display_name="X")


def test_restart_key_matches_role() -> None:
    big = CodexAgent(role="big", display_name="Big Bro")
    lil = CodexAgent(role="lil", display_name="Lil Bro")
    assert big.RESTART_KEY == "big"
    assert lil.RESTART_KEY == "lil"


def test_display_name_is_user_provided() -> None:
    agent = CodexAgent(role="lil", display_name="Navigator")
    assert agent.display_name == "Navigator"
    assert agent.DISPLAY_NAME == "Navigator"


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
    assert "workspace-write" in brief
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
    agent = CodexAgent(role="lil", display_name="Lil", write_access=False)
    assert agent._write_access is False
    agent.set_write_access(True)
    assert agent._write_access is True


def test_set_configured_model_normalizes_empty() -> None:
    agent = CodexAgent(role="big", display_name="X", model="gpt-5")
    assert agent._configured_model == "gpt-5"
    agent.set_configured_model("")
    assert agent._configured_model is None
    agent.set_configured_model("gpt-5-codex")
    assert agent._configured_model == "gpt-5-codex"


def test_set_sibling_updates_metadata() -> None:
    agent = CodexAgent(role="big", display_name="X")
    agent.set_sibling(sibling_name="New Bro", sibling_backend="Claude")
    assert agent._sibling_name == "New Bro"
    assert agent._sibling_backend == "Claude"


def test_reset_thread_clears_threadid() -> None:
    agent = CodexAgent(role="big", display_name="X")
    agent._thread_id = "thr_abc"
    agent.reset_thread()
    assert agent._thread_id is None


def test_clear_history_is_reset_thread() -> None:
    agent = CodexAgent(role="big", display_name="X")
    agent._thread_id = "thr_abc"
    agent.clear_history()
    assert agent._thread_id is None


def test_next_id_monotonic() -> None:
    agent = CodexAgent(role="big", display_name="X")
    assert agent._next_id() == 1
    assert agent._next_id() == 2
    assert agent._next_id() == 3


def test_dispatch_response_resolves_future() -> None:
    """A matching {id,result} message must complete the pending future."""
    async def _run() -> dict:
        agent = CodexAgent(role="big", display_name="X")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        agent._pending[42] = fut
        agent._dispatch({"jsonrpc": "2.0", "id": 42, "result": {"ok": True}})
        return await asyncio.wait_for(fut, timeout=1.0)

    resp = asyncio.run(_run())
    assert resp["result"] == {"ok": True}


def test_dispatch_error_sets_future_exception() -> None:
    async def _run() -> None:
        agent = CodexAgent(role="big", display_name="X")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        agent._pending[7] = fut
        agent._dispatch({
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -1, "message": "boom"},
        })
        with pytest.raises(RuntimeError, match="boom"):
            await asyncio.wait_for(fut, timeout=1.0)

    asyncio.run(_run())


def test_handle_session_configured_announces_once() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_codex_event({
        "type": "session_configured",
        "session_id": "abc123xyz",
        "model": "gpt-5-codex",
        "sandbox_policy": {"type": "read-only"},
    })
    agent._handle_codex_event({
        "type": "session_configured",
        "session_id": "abc123xyz",
        "model": "gpt-5-codex",
        "sandbox_policy": {"type": "read-only"},
    })
    banners = [m for m in panel.system if "connected" in m]
    assert len(banners) == 1
    assert agent._session_id == "abc123xyz"
    assert agent._model == "gpt-5-codex"


def test_handle_agent_message_delta_appends_chunk() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._turn_started_at = 1.0  # mark a turn live so budget counts
    agent._handle_codex_event({
        "type": "agent_message_delta",
        "delta": "hello world",
    })
    assert panel.chunks == ["hello world"]


def test_handle_error_event_writes_to_panel() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_codex_event({"type": "error", "message": "kaboom"})
    assert any("kaboom" in e for e in panel.errors)


def test_handle_token_count_warns_over_threshold() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_codex_event({
        "type": "token_count",
        "rate_limits": {"primary": {"used_percent": 85.0}},
    })
    assert any("rate limit" in s for s in panel.system)


def test_handle_token_count_silent_under_threshold() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._handle_codex_event({
        "type": "token_count",
        "rate_limits": {"primary": {"used_percent": 10.0}},
    })
    assert not any("rate limit" in s for s in panel.system)


def test_cancelled_turn_drops_deltas() -> None:
    agent = CodexAgent(role="big", display_name="X")
    panel = _FakePanel()
    agent._current_panel = panel
    agent._turn_id = 5
    agent._cancelled_turns.add(5)
    agent._handle_codex_event({
        "type": "agent_message_delta",
        "delta": "should drop",
    })
    assert panel.chunks == []


def test_elicitation_auto_deny_with_enum_preference() -> None:
    """Server elicitation with an enum must pick a deny-shaped value."""
    async def _run() -> dict:
        agent = CodexAgent(role="big", display_name="X")
        captured: list[dict] = []

        async def _fake_write(msg: dict) -> None:
            captured.append(msg)

        agent._write_line = _fake_write  # type: ignore[assignment]
        agent._handle_server_request({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "elicitation/create",
            "params": {
                "requestedSchema": {
                    "properties": {
                        "decision": {
                            "type": "string",
                            "enum": ["approve", "deny"],
                        }
                    },
                    "required": ["decision"],
                },
            },
        })
        # give the scheduled reply task a chance to run
        for _ in range(20):
            if captured:
                break
            await asyncio.sleep(0.01)
        return captured[0] if captured else {}

    reply = asyncio.run(_run())
    assert reply.get("id") == 99
    assert reply["result"]["action"] == "accept"
    assert reply["result"]["content"]["decision"] == "deny"


def test_sampling_request_rejected() -> None:
    async def _run() -> dict:
        agent = CodexAgent(role="big", display_name="X")
        captured: list[dict] = []

        async def _fake_write(msg: dict) -> None:
            captured.append(msg)

        agent._write_line = _fake_write  # type: ignore[assignment]
        agent._handle_server_request({
            "jsonrpc": "2.0",
            "id": 50,
            "method": "sampling/createMessage",
            "params": {},
        })
        for _ in range(20):
            if captured:
                break
            await asyncio.sleep(0.01)
        return captured[0] if captured else {}

    reply = asyncio.run(_run())
    assert reply.get("id") == 50
    assert "error" in reply
    assert reply["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_check_codex_health_when_missing(monkeypatch) -> None:
    """If `codex` isn't on PATH, health check reports installed=False."""
    import src_local.agents.codex_agent as mod
    monkeypatch.setattr(mod.shutil, "which", lambda _name: None)
    result = await check_codex_health()
    assert result["installed"] is False
    assert result["path"] is None


def test_json_rpc_message_serializes_as_single_line() -> None:
    """Sanity: our messages must be newline-delimited JSON objects."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    line = json.dumps(msg)
    assert "\n" not in line
    assert json.loads(line) == msg
