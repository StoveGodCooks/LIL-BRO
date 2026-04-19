"""Smoke tests for the Phase 5 + 6 slash commands."""

from __future__ import annotations

from pathlib import Path

import pytest

from src_local.commands.handler import CommandHandler
from src_local.pwa import server as pwa_server


@pytest.fixture(autouse=True)
def sandbox_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("LILBRO_NTFY_TOPIC", raising=False)
    return tmp_path


class _FakeProfile:
    level = 2
    xp = 30
    xp_to_next = 100
    skills = {"python": 3}
    badges = ["first-run"]


class TestSheetCommand:
    def test_sheet_without_profile(self) -> None:
        h = CommandHandler()
        r = h.handle("/sheet")
        assert "CHARACTER SHEET" in r.message
        assert "no player profile" in r.message

    def test_sheet_with_profile(self) -> None:
        h = CommandHandler(player_profile=_FakeProfile())
        r = h.handle("/sheet")
        assert "python" in r.message
        assert "first-run" in r.message


class TestLessonCommand:
    def test_lesson_requires_topic(self) -> None:
        h = CommandHandler()
        r = h.handle("/lesson")
        assert "usage" in r.message.lower()

    def test_lesson_routes_and_prefixes_grandma(self) -> None:
        h = CommandHandler()
        r = h.handle("/lesson recursion")
        assert r.bypass_agent is False
        assert r.forced_target in {"big", "bro"}
        assert "GRANDMA" in (r.rewritten_prompt or "")
        assert "recursion" in (r.rewritten_prompt or "")
        assert "lesson on 'recursion'" in r.message


class TestPwaCommand:
    def teardown_method(self) -> None:
        # Always clean up between tests.
        pwa_server.stop()

    def test_status_when_not_running(self) -> None:
        h = CommandHandler()
        r = h.handle("/pwa")
        assert "not running" in r.message

    def test_start_then_url_then_stop(self) -> None:
        h = CommandHandler()
        r = h.handle("/pwa start 0")
        assert "running" in r.message
        r2 = h.handle("/pwa url")
        assert "http://" in r2.message
        r3 = h.handle("/pwa stop")
        assert "stopped" in r3.message

    def test_start_bad_port(self) -> None:
        h = CommandHandler()
        r = h.handle("/pwa start abc")
        assert "usage" in r.message.lower()


class TestNotifyCommand:
    def test_notify_no_topic(self) -> None:
        h = CommandHandler()
        r = h.handle("/notify hello")
        assert "no ntfy topic" in r.message

    def test_notify_usage(self) -> None:
        h = CommandHandler()
        r = h.handle("/notify")
        assert "usage" in r.message.lower()

    def test_notify_success(self, monkeypatch) -> None:
        monkeypatch.setenv("LILBRO_NTFY_TOPIC", "abc")

        class _Resp:
            status_code = 200
            text = "ok"

        import httpx  # type: ignore[import-not-found]
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: _Resp())  # noqa: ARG005

        h = CommandHandler()
        r = h.handle("/notify hi there")
        assert "notification sent" in r.message
