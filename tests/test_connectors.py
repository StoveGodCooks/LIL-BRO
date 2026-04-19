"""Tests for the connector registry and provider/model parsing.

The registry is the single seam between config strings (like
``"claude/sonnet-4"``) and the concrete ``AgentProcess`` subclass that
will drive a pane. These tests lock in the parse rules, the factory
dispatch, and the backwards-compat shim for Phase 0 bare-model strings.
"""

from __future__ import annotations

import pytest

from src_local.agents.base import AgentProcess
from src_local.agents.claude_agent import ClaudeAgent
from src_local.agents.codex_agent import CodexAgent
from src_local.agents.connectors import (
    AVAILABLE_PROVIDERS,
    CONNECTORS,
    SUBSCRIPTION_PROVIDERS,
    build_agent,
    is_subscription_provider,
    list_providers,
    parse_model_string,
)
from src_local.agents.ollama_agent import OllamaAgent


class TestRegistryShape:
    def test_known_providers(self) -> None:
        assert set(CONNECTORS) == {"ollama", "claude", "codex", "flex"}

    def test_list_providers_matches_available(self) -> None:
        assert list_providers() == AVAILABLE_PROVIDERS

    def test_subscription_providers_set(self) -> None:
        assert SUBSCRIPTION_PROVIDERS == {"claude", "codex"}
        assert is_subscription_provider("claude") is True
        assert is_subscription_provider("CODEX") is True
        assert is_subscription_provider("ollama") is False


class TestParseModelString:
    def test_provider_slash_model(self) -> None:
        assert parse_model_string("claude/sonnet-4") == ("claude", "sonnet-4")
        assert parse_model_string("ollama/qwen2.5-coder:7b") == (
            "ollama",
            "qwen2.5-coder:7b",
        )
        assert parse_model_string("codex/gpt-5-codex") == ("codex", "gpt-5-codex")

    def test_bare_provider_name(self) -> None:
        assert parse_model_string("claude") == ("claude", None)
        assert parse_model_string("codex") == ("codex", None)
        assert parse_model_string("ollama") == ("ollama", None)

    def test_case_insensitive_provider(self) -> None:
        assert parse_model_string("Claude/sonnet-4") == ("claude", "sonnet-4")
        assert parse_model_string("OLLAMA/llama3.1:8b") == ("ollama", "llama3.1:8b")

    def test_legacy_bare_model_is_ollama(self) -> None:
        """Phase 0 configs shipped ``model: qwen2.5-coder:7b`` with no provider."""
        assert parse_model_string("qwen2.5-coder:7b") == (
            "ollama",
            "qwen2.5-coder:7b",
        )
        assert parse_model_string("llama3.1:8b") == ("ollama", "llama3.1:8b")

    def test_tuple_form(self) -> None:
        assert parse_model_string(("claude", "sonnet-4")) == ("claude", "sonnet-4")
        assert parse_model_string(("codex", None)) == ("codex", None)

    def test_tuple_with_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            parse_model_string(("mystery", "x"))

    def test_tuple_wrong_shape_raises(self) -> None:
        with pytest.raises(ValueError, match="tuple"):
            parse_model_string(("only-one",))  # type: ignore[arg-type]

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_model_string("")

    def test_slashed_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            parse_model_string("grok/beta")

    def test_trims_whitespace(self) -> None:
        assert parse_model_string("  claude/sonnet-4  ") == ("claude", "sonnet-4")

    def test_empty_model_after_slash_is_none(self) -> None:
        """``claude/`` means "use whatever model Claude defaults to"."""
        assert parse_model_string("claude/") == ("claude", None)


class TestBuildAgent:
    def test_builds_ollama(self) -> None:
        agent = build_agent(
            "ollama/qwen2.5-coder:7b",
            role="big",
            display_name="Big Bro",
        )
        assert isinstance(agent, OllamaAgent)
        assert isinstance(agent, AgentProcess)
        assert agent.model == "qwen2.5-coder:7b"
        assert agent.display_name == "Big Bro"

    def test_builds_claude(self) -> None:
        agent = build_agent(
            "claude/sonnet-4",
            role="big",
            display_name="Big Bro",
            sibling_name="Lil Bro",
            sibling_backend="Ollama",
        )
        assert isinstance(agent, ClaudeAgent)
        assert agent.role == "big"
        assert agent.display_name == "Big Bro"
        assert agent._configured_model == "sonnet-4"
        assert agent._sibling_backend == "Ollama"

    def test_builds_codex(self) -> None:
        agent = build_agent(
            ("codex", "gpt-5-codex"),
            role="lil",
            display_name="Lil Bro",
            write_access=False,
            sibling_name="Big Bro",
            sibling_backend="Claude",
        )
        assert isinstance(agent, CodexAgent)
        assert agent.role == "lil"
        assert agent._configured_model == "gpt-5-codex"
        assert agent._write_access is False

    def test_bare_provider_uses_default_model(self) -> None:
        agent = build_agent("claude", role="big", display_name="X")
        assert isinstance(agent, ClaudeAgent)
        assert agent._configured_model is None

    def test_legacy_bare_model_routes_to_ollama(self) -> None:
        agent = build_agent("llama3.1:8b", role="big", display_name="X")
        assert isinstance(agent, OllamaAgent)
        assert agent.model == "llama3.1:8b"

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown provider"):
            build_agent("mystery/v1", role="big", display_name="X")

    def test_extra_kwargs_passed_to_ollama(self, tmp_path) -> None:
        agent = build_agent(
            "ollama",
            role="big",
            display_name="X",
            temperature=0.5,
            project_dir=tmp_path,
        )
        assert isinstance(agent, OllamaAgent)
        assert agent.temperature == 0.5
        assert agent.project_dir == tmp_path

    def test_role_forwarded_to_cloud_connectors(self) -> None:
        """Cloud connectors validate role — must propagate, not swallow."""
        with pytest.raises(ValueError):
            build_agent("claude", role="middle", display_name="X")
        with pytest.raises(ValueError):
            build_agent("codex", role="middle", display_name="X")
