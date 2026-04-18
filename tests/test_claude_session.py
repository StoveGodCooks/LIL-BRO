"""Tests for Claude session persistence + tool-detail helpers.

Covers the project-aware session auto-restore machinery and the
`_build_tool_detail` / `_short_path` display helpers added alongside
the yellow-collapsible tool-call UI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src_local.agents import claude_agent
from src_local.agents.claude_agent import (
    ClaudeAgent,
    _build_tool_detail,
    _delete_project_session,
    _load_project_session,
    _project_session_file,
    _save_project_session,
    _short_path,
)


# ---------------------------------------------------------------------------
# _short_path
# ---------------------------------------------------------------------------


class TestShortPath:
    def test_short_path_keeps_single_component(self) -> None:
        assert _short_path("foo.py") == "foo.py"

    def test_short_path_truncates_long_windows_path(self) -> None:
        long = r"C:\Users\beebo\OneDrive\Desktop\LIL_BRO_LOCAL\src_local\ui\panels.py"
        short = _short_path(long)
        assert short.startswith(".../")
        assert "panels.py" in short
        assert "ui" in short
        assert len(short) <= 60

    def test_short_path_posix_style(self) -> None:
        short = _short_path("/home/user/project/src/main.py")
        assert short.startswith(".../")
        assert short.endswith("main.py")

    def test_short_path_respects_max_length(self) -> None:
        # Even with insane input, caps at 60 chars.
        huge = "/" + "/".join(["xxxxxxxxxx"] * 20) + "/final.py"
        assert len(_short_path(huge)) <= 60


# ---------------------------------------------------------------------------
# _build_tool_detail
# ---------------------------------------------------------------------------


class TestBuildToolDetail:
    def test_read_returns_file_contents(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("line one\nline two\n", encoding="utf-8")
        detail = _build_tool_detail("Read", str(f), {"file_path": str(f)})
        assert "line one" in detail
        assert "line two" in detail

    def test_read_truncates_large_files(self, tmp_path: Path) -> None:
        f = tmp_path / "big.txt"
        f.write_text("x" * 6000, encoding="utf-8")
        detail = _build_tool_detail("Read", str(f), {})
        assert "truncated" in detail
        assert len(detail) < 6000

    def test_read_missing_file_returns_placeholder(self, tmp_path: Path) -> None:
        detail = _build_tool_detail(
            "Read", str(tmp_path / "nope.txt"), {"file_path": "nope.txt"}
        )
        assert "could not read" in detail

    def test_edit_returns_unified_diff(self) -> None:
        detail = _build_tool_detail(
            "Edit",
            "foo.py",
            {"old_string": "hello\n", "new_string": "world\n"},
        )
        assert "-hello" in detail
        assert "+world" in detail
        assert "before" in detail and "after" in detail

    def test_edit_with_no_change_returns_no_diff(self) -> None:
        detail = _build_tool_detail(
            "Edit", "foo.py", {"old_string": "same", "new_string": "same"}
        )
        assert detail == "(no diff)"

    def test_multiedit_returns_combined_diff(self) -> None:
        detail = _build_tool_detail(
            "MultiEdit",
            "foo.py",
            {
                "edits": [
                    {"old_string": "a", "new_string": "b"},
                    {"old_string": "c", "new_string": "d"},
                ]
            },
        )
        assert "-a" in detail
        assert "+b" in detail
        assert "-c" in detail
        assert "+d" in detail

    def test_multiedit_empty_returns_placeholder(self) -> None:
        detail = _build_tool_detail("MultiEdit", "foo.py", {"edits": []})
        assert detail == "(no changes)"

    def test_bash_returns_shell_form(self) -> None:
        detail = _build_tool_detail(
            "Bash", "", {"command": "ls -la /tmp"}
        )
        assert detail == "$ ls -la /tmp"

    def test_write_returns_content(self) -> None:
        detail = _build_tool_detail(
            "Write", "new.py", {"content": "print('hi')"}
        )
        assert detail == "print('hi')"

    def test_write_without_content_placeholder(self) -> None:
        detail = _build_tool_detail("Write", "x.py", {})
        assert detail == "(no content)"

    def test_unknown_tool_returns_json_dump(self) -> None:
        detail = _build_tool_detail(
            "Mystery", "", {"alpha": 1, "beta": "two"}
        )
        assert '"alpha"' in detail
        assert '"beta"' in detail


# ---------------------------------------------------------------------------
# Project session persistence
# ---------------------------------------------------------------------------


@pytest.fixture
def sandbox_sessions_dir(tmp_path, monkeypatch):
    """Redirect the module-level _SESSIONS_DIR to a tmp dir for isolation."""
    sandbox = tmp_path / "sessions"
    monkeypatch.setattr(claude_agent, "_SESSIONS_DIR", sandbox)
    return sandbox


class TestProjectSessionPersistence:
    def test_session_file_keys_on_cwd_and_role(self, sandbox_sessions_dir) -> None:
        p1 = _project_session_file("/some/project", "big")
        p2 = _project_session_file("/some/project", "lil")
        p3 = _project_session_file("/other/project", "big")
        assert p1 != p2
        assert p1 != p3
        assert p1.parent == sandbox_sessions_dir

    def test_roundtrip_save_and_load(self, sandbox_sessions_dir) -> None:
        _save_project_session("/proj", "big", "abc-def-123")
        assert _load_project_session("/proj", "big") == "abc-def-123"

    def test_load_missing_returns_none(self, sandbox_sessions_dir) -> None:
        assert _load_project_session("/nowhere", "big") is None

    def test_delete_removes_file(self, sandbox_sessions_dir) -> None:
        _save_project_session("/proj", "lil", "xyz")
        _delete_project_session("/proj", "lil")
        assert _load_project_session("/proj", "lil") is None

    def test_delete_is_idempotent(self, sandbox_sessions_dir) -> None:
        # Must not raise on missing file.
        _delete_project_session("/never-written", "big")

    def test_save_creates_parent_dir(self, sandbox_sessions_dir) -> None:
        assert not sandbox_sessions_dir.exists()
        _save_project_session("/proj", "big", "abc")
        assert sandbox_sessions_dir.exists()


# ---------------------------------------------------------------------------
# ClaudeAgent resume / reset behavior
# ---------------------------------------------------------------------------


class TestResumeResetBehavior:
    def test_set_resume_session_stores_id(self) -> None:
        agent = ClaudeAgent(role="big", display_name="X")
        agent.set_resume_session("deadbeef-cafe-1234")
        assert agent._resume_session_id == "deadbeef-cafe-1234"

    def test_set_resume_session_empty_clears(self) -> None:
        agent = ClaudeAgent(role="big", display_name="X")
        agent._resume_session_id = "prev"
        agent.set_resume_session("   ")
        assert agent._resume_session_id is None

    def test_reset_thread_clears_both_ids(self, sandbox_sessions_dir) -> None:
        agent = ClaudeAgent(role="big", display_name="X")
        agent._session_id = "live-id"
        agent._resume_session_id = "saved-id"
        agent.reset_thread()
        assert agent._session_id is None
        assert agent._resume_session_id is None

    def test_reset_thread_deletes_project_session(
        self, sandbox_sessions_dir, tmp_path
    ) -> None:
        agent = ClaudeAgent(role="big", display_name="X", cwd=str(tmp_path))
        _save_project_session(str(tmp_path), "big", "old-session")
        assert _load_project_session(str(tmp_path), "big") == "old-session"
        agent.reset_thread()
        assert _load_project_session(str(tmp_path), "big") is None
