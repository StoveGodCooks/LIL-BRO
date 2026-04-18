"""Tests for the /resume and /reset slash commands.

Validates that /reset resets BOTH agents (not just the active one) and
that /resume correctly routes a session ID to the right bro using the
`big | lil` prefix syntax (defaulting to Big Bro).
"""

from __future__ import annotations

from src_local.commands.handler import CommandHandler


class _FakeClaudeAgent:
    """Minimal ClaudeAgent-shaped stub that records method calls."""

    def __init__(self) -> None:
        self.history_cleared = 0
        self.thread_reset = 0
        self.resume_ids: list[str] = []

    def clear_history(self) -> None:
        self.history_cleared += 1

    def reset_thread(self) -> None:
        self.thread_reset += 1

    def set_resume_session(self, session_id: str) -> None:
        self.resume_ids.append(session_id)


class _FakeOllamaAgent:
    """Agent without `set_resume_session` / `reset_thread` — mimics Ollama."""

    def __init__(self) -> None:
        self.history_cleared = 0

    def clear_history(self) -> None:
        self.history_cleared += 1


# ---------------------------------------------------------------------------
# /reset
# ---------------------------------------------------------------------------


class TestResetCommand:
    def test_reset_clears_both_agents(self) -> None:
        big = _FakeClaudeAgent()
        lil = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big, lil_bro=lil)
        result = h.handle("/reset")
        assert big.history_cleared == 1
        assert lil.history_cleared == 1
        assert big.thread_reset == 1
        assert lil.thread_reset == 1
        assert result.bypass_agent is True
        assert "Big Bro" in result.message
        assert "Lil Bro" in result.message

    def test_reset_handles_agent_without_reset_thread(self) -> None:
        big = _FakeOllamaAgent()  # no reset_thread attr
        lil = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big, lil_bro=lil)
        result = h.handle("/reset")
        assert big.history_cleared == 1
        assert lil.history_cleared == 1
        assert lil.thread_reset == 1  # Claude side still resets
        assert result.bypass_agent is True

    def test_reset_with_no_agents(self) -> None:
        h = CommandHandler()
        result = h.handle("/reset")
        assert result.bypass_agent is True
        assert "No agents" in result.message


# ---------------------------------------------------------------------------
# /resume
# ---------------------------------------------------------------------------


class TestResumeCommand:
    def test_resume_bare_id_defaults_to_big(self) -> None:
        big = _FakeClaudeAgent()
        lil = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big, lil_bro=lil)
        result = h.handle("/resume abc12345")
        assert big.resume_ids == ["abc12345"]
        assert lil.resume_ids == []
        assert result.bypass_agent is True
        assert "Big Bro" in result.message
        assert "[abc12345]" in result.message

    def test_resume_explicit_big(self) -> None:
        big = _FakeClaudeAgent()
        lil = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big, lil_bro=lil)
        h.handle("/resume big beef1234")
        assert big.resume_ids == ["beef1234"]
        assert lil.resume_ids == []

    def test_resume_explicit_lil(self) -> None:
        big = _FakeClaudeAgent()
        lil = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big, lil_bro=lil)
        h.handle("/resume lil cafe5678")
        assert lil.resume_ids == ["cafe5678"]
        assert big.resume_ids == []

    def test_resume_empty_shows_usage(self) -> None:
        h = CommandHandler(big_bro=_FakeClaudeAgent())
        result = h.handle("/resume")
        assert result.bypass_agent is True
        assert "Usage" in result.message

    def test_resume_prefix_without_id(self) -> None:
        big = _FakeClaudeAgent()
        h = CommandHandler(big_bro=big)
        result = h.handle("/resume big")
        assert big.resume_ids == []
        assert "No session ID" in result.message

    def test_resume_on_ollama_agent_warns(self) -> None:
        big = _FakeOllamaAgent()
        h = CommandHandler(big_bro=big)
        result = h.handle("/resume sometoken")
        assert result.bypass_agent is True
        assert "Ollama" in result.message or "only apply" in result.message

    def test_resume_without_agent(self) -> None:
        h = CommandHandler()
        result = h.handle("/resume lil abc")
        assert result.bypass_agent is True
        assert "not available" in result.message
