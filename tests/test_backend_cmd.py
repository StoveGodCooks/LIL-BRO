"""Tests for the /backend command parsing and dispatch.

- Parses big|lil correctly
- Parses provider and provider/model specs
- Calls swapper callback with correct arguments
- Returns appropriate error messages for bad input
"""

from __future__ import annotations

import asyncio
from typing import Any

from src_local.commands.handler import CommandHandler


# ── Helpers ────────────────────────────────────────────────────────────────

def _make_handler() -> CommandHandler:
    return CommandHandler()


def _run(coro) -> Any:
    return asyncio.run(coro)


# ── Parsing tests ──────────────────────────────────────────────────────────

class TestBackendCommandParsing:
    def test_no_args_shows_usage(self) -> None:
        h = _make_handler()
        result = h.handle("/backend")
        assert result.bypass_agent is True
        assert "usage" in result.message.lower()

    def test_missing_spec_shows_usage(self) -> None:
        h = _make_handler()
        result = h.handle("/backend big")
        assert "usage" in result.message.lower()

    def test_unknown_role_error(self) -> None:
        h = _make_handler()
        result = h.handle("/backend main ollama")
        assert "unknown role" in result.message.lower()

    def test_big_ollama(self) -> None:
        h = _make_handler()
        result = h.handle("/backend big ollama")
        assert result.bypass_agent is True
        assert "Big Bro" in result.message
        assert result.async_work is not None

    def test_lil_codex(self) -> None:
        h = _make_handler()
        result = h.handle("/backend lil codex")
        assert result.bypass_agent is True
        assert "Lil Bro" in result.message
        assert result.async_work is not None

    def test_big_claude_with_model(self) -> None:
        h = _make_handler()
        result = h.handle("/backend big claude/sonnet-4")
        assert "Big Bro" in result.message
        assert result.async_work is not None

    def test_lil_flex(self) -> None:
        h = _make_handler()
        result = h.handle("/backend lil flex")
        assert "Lil Bro" in result.message
        assert result.async_work is not None

    def test_big_aliases(self) -> None:
        for alias in ("bigbro", "big_bro"):
            h = _make_handler()
            result = h.handle(f"/backend {alias} ollama")
            assert "Big Bro" in result.message

    def test_lil_aliases(self) -> None:
        for alias in ("lilbro", "lil_bro"):
            h = _make_handler()
            result = h.handle(f"/backend {alias} ollama")
            assert "Lil Bro" in result.message


# ── Swapper callback tests ─────────────────────────────────────────────────

class TestBackendSwapper:
    def test_swapper_called_with_correct_args(self) -> None:
        h = _make_handler()
        calls: list[tuple] = []

        async def _swapper(role: str, spec: str, panel: Any) -> None:
            calls.append((role, spec, panel))

        h.set_backend_swapper(_swapper)

        result = h.handle("/backend big claude/sonnet-4")
        assert result.async_work is not None
        _run(result.async_work())
        assert len(calls) == 1
        assert calls[0][0] == "big"
        assert calls[0][1] == "claude/sonnet-4"

    def test_lil_swapper_called(self) -> None:
        h = _make_handler()
        calls: list[tuple] = []

        async def _swapper(role: str, spec: str, panel: Any) -> None:
            calls.append((role, spec))

        h.set_backend_swapper(_swapper)
        result = h.handle("/backend lil ollama")
        _run(result.async_work())
        assert calls == [("lil", "ollama")]

    def test_no_swapper_posts_message(self, capsys) -> None:
        """When no swapper is wired, async_work should not crash."""
        h = _make_handler()

        class FakePanel:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def append_system(self, msg: str) -> None:
                self.messages.append(msg)

        # Give it a fake panel so the "not wired up" path executes.
        panel = FakePanel()
        h.big_bro_panel = panel

        result = h.handle("/backend big ollama")
        assert result.async_work is not None
        _run(result.async_work())
        # Should post a "not wired up" message via the panel.
        assert any("not wired" in m.lower() for m in panel.messages)


# ── /flex command tests ────────────────────────────────────────────────────

class TestFlexCommand:
    def test_no_lil_bro_returns_message(self) -> None:
        h = _make_handler()
        result = h.handle("/flex")
        assert "not available" in result.message.lower()

    def test_flex_on_non_flex_agent(self) -> None:
        """When Lil Bro is not FlexAgent, /flex should switch to flex."""
        from unittest.mock import MagicMock

        h = _make_handler()
        mock_agent = MagicMock()
        # Not a FlexAgent instance.
        mock_agent.__class__.__name__ = "OllamaAgent"
        h.lil_bro = mock_agent

        calls: list[tuple] = []

        async def _swapper(role: str, spec: str, panel: Any) -> None:
            calls.append((role, spec))

        h.set_backend_swapper(_swapper)
        result = h.handle("/flex")
        assert result.async_work is not None
        _run(result.async_work())
        assert ("lil", "flex") in calls
