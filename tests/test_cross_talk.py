"""Cross-talk tests — SESSION.md as the unified sibling-context layer.

Phase 1 retired ``BROS_LOG.md`` in favor of a single ``SESSION.md``
streamed by the journal recorder. OllamaAgent now reads the Live
Stream tail to inject sibling context; cloud connectors reference the
same file via their system-prompt briefing. These tests lock in the
Ollama side — the cloud briefings are already covered by
``test_claude_connector.py`` and ``test_codex_connector.py``.
"""

from __future__ import annotations

from pathlib import Path

from src_local.agents.ollama_agent import OllamaAgent


def _make_agent(tmp_path: Path, sibling_target: str) -> OllamaAgent:
    agent = OllamaAgent(display_name="Test Bro", project_dir=tmp_path)
    agent.set_session_log(tmp_path / "SESSION.md", sibling_target=sibling_target)
    agent._sibling_name = "Sibling"
    return agent


def test_no_injection_when_session_log_unset(tmp_path: Path) -> None:
    agent = OllamaAgent(display_name="X", project_dir=tmp_path)
    out = agent._inject_sibling_context("hello")
    assert out == "hello"


def test_no_injection_when_file_missing(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path, sibling_target="bro")
    # Path was set but nothing wrote to it — prompt must pass through unchanged.
    out = agent._inject_sibling_context("hello")
    assert out == "hello"


def test_injects_sibling_agent_lines(tmp_path: Path) -> None:
    session_md = tmp_path / "SESSION.md"
    session_md.write_text(
        "[10:00:00] USER big: /do the thing\n"
        "[10:00:01] AGENT big: I'll handle it.\n"
        "[10:00:02] TOOL bro: Read src/foo.py\n"
        "[10:00:03] AGENT bro: The bug is in parse().\n",
        encoding="utf-8",
    )
    agent = _make_agent(tmp_path, sibling_target="bro")
    out = agent._inject_sibling_context("what now?")
    assert "tail of SESSION.md live stream" in out
    assert "AGENT bro: The bug is in parse()." in out
    assert "TOOL bro: Read src/foo.py" in out
    # Original user prompt is preserved at the end.
    assert out.rstrip().endswith("what now?")


def test_filters_out_own_lines(tmp_path: Path) -> None:
    """A Big Bro agent must NOT see its own ``big`` lines as sibling context."""
    session_md = tmp_path / "SESSION.md"
    session_md.write_text(
        "[10:00:00] AGENT big: my own thought\n"
        "[10:00:01] AGENT bro: sibling thought\n",
        encoding="utf-8",
    )
    agent = _make_agent(tmp_path, sibling_target="bro")
    out = agent._inject_sibling_context("q")
    assert "sibling thought" in out
    assert "my own thought" not in out


def test_skips_user_and_banner_lines(tmp_path: Path) -> None:
    """USER / SESSION banner lines aren't sibling activity — drop them."""
    session_md = tmp_path / "SESSION.md"
    session_md.write_text(
        "[10:00:00] SESSION: project=/tmp big=x bro=y\n"
        "[10:00:01] USER bro: hey\n"
        "[10:00:02] AGENT bro: doing work\n",
        encoding="utf-8",
    )
    agent = _make_agent(tmp_path, sibling_target="bro")
    out = agent._inject_sibling_context("q")
    assert "AGENT bro: doing work" in out
    assert "USER bro: hey" not in out
    assert "SESSION:" not in out


def test_caps_to_last_five_entries(tmp_path: Path) -> None:
    session_md = tmp_path / "SESSION.md"
    lines = [f"[10:00:{i:02d}] AGENT bro: entry {i}\n" for i in range(10)]
    session_md.write_text("".join(lines), encoding="utf-8")
    agent = _make_agent(tmp_path, sibling_target="bro")
    out = agent._inject_sibling_context("q")
    # Only the last five should survive.
    assert "entry 9" in out
    assert "entry 5" in out
    assert "entry 4" not in out


def test_legacy_set_bros_log_is_noop(tmp_path: Path) -> None:
    """``set_bros_log`` was the Phase-0 API; it now does nothing."""
    agent = OllamaAgent(display_name="X", project_dir=tmp_path)
    agent.set_bros_log(tmp_path / "BROS_LOG.md")
    # Session log path remains unset, so no injection happens.
    assert agent._session_log_path is None
    assert agent._inject_sibling_context("hello") == "hello"


def test_log_turn_summary_is_noop(tmp_path: Path) -> None:
    """SESSION.md is streamed by JournalRecorder — Ollama no longer writes."""
    session_md = tmp_path / "SESSION.md"
    agent = _make_agent(tmp_path, sibling_target="bro")
    agent._log_turn_summary("prompt", "response")
    # Nothing should have been written by the agent itself.
    assert not session_md.exists()
