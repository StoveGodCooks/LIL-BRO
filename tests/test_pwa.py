"""Tests for the PWA server + ntfy wrapper.

The server is exercised end-to-end against a real loopback port,
since it's stdlib-only and starts instantly.  ntfy is tested at the
config/topic-resolution layer -- the actual HTTP POST is mocked.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from src_local.pwa import notify, server


@pytest.fixture
def sandbox_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("LILBRO_NTFY_TOPIC", raising=False)
    monkeypatch.delenv("LILBRO_NTFY_SERVER", raising=False)
    return tmp_path


@pytest.fixture
def running_server(sandbox_home: Path):
    # Use an ephemeral port by passing 0 and reading back.
    server.stop()  # defensive
    server.start(host="127.0.0.1", port=0)
    # After starting on port 0, State.port holds the real bound port.
    port = server._State.port  # noqa: SLF001
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()


class TestServerLifecycle:
    def test_start_then_stop(self, sandbox_home: Path) -> None:
        server.start(host="127.0.0.1", port=0)
        try:
            assert server.is_running()
            assert server.current_url() is not None
        finally:
            server.stop()
        assert not server.is_running()
        assert server.current_url() is None

    def test_double_start_raises(self, sandbox_home: Path) -> None:
        server.start(host="127.0.0.1", port=0)
        try:
            with pytest.raises(RuntimeError):
                server.start(host="127.0.0.1", port=0)
        finally:
            server.stop()

    def test_stop_when_not_running_is_safe(self, sandbox_home: Path) -> None:
        server.stop()  # must not raise


class TestServerEndpoints:
    def _get(self, base: str, path: str) -> tuple[int, bytes, str]:
        req = urllib.request.Request(base + path)
        with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")

    def test_index_returns_html(self, running_server: str) -> None:
        status, body, ctype = self._get(running_server, "/")
        assert status == 200
        assert b"LIL BRO" in body
        assert "text/html" in ctype

    def test_manifest_served(self, running_server: str) -> None:
        status, body, ctype = self._get(running_server, "/manifest.webmanifest")
        assert status == 200
        data = json.loads(body)
        assert data["name"] == "LIL BRO LOCAL"
        assert "manifest" in ctype

    def test_service_worker_served(self, running_server: str) -> None:
        status, body, ctype = self._get(running_server, "/service-worker.js")
        assert status == 200
        assert b"serviceWorker" not in body  # SW file itself, not a loader
        assert b"caches" in body
        assert "javascript" in ctype

    def test_static_asset(self, running_server: str) -> None:
        status, body, ctype = self._get(running_server, "/static/style.css")
        assert status == 200
        assert b":root" in body
        assert "css" in ctype

    def test_static_missing_returns_404(self, running_server: str) -> None:
        with pytest.raises(urllib.error.HTTPError) as ei:  # type: ignore[attr-defined]
            self._get(running_server, "/static/nope.css")
        assert ei.value.code == 404

    def test_api_health(self, running_server: str) -> None:
        status, body, _ = self._get(running_server, "/api/health")
        assert status == 200
        assert json.loads(body)["ok"] is True

    def test_api_roadmap_empty(
        self, running_server: str, sandbox_home: Path
    ) -> None:
        # No roadmap.json yet -> empty milestones list.
        status, body, _ = self._get(running_server, "/api/roadmap")
        assert status == 200
        assert json.loads(body) == {"milestones": []}

    def test_api_roadmap_reads_file(
        self, running_server: str, sandbox_home: Path
    ) -> None:
        (sandbox_home / ".lilbro-local").mkdir(parents=True, exist_ok=True)
        (sandbox_home / ".lilbro-local" / "roadmap.json").write_text(
            json.dumps(
                {"milestones": [{"id": "M-x", "title": "t", "state": "BACKLOG",
                                 "tasks": []}]},
            ),
            encoding="utf-8",
        )
        status, body, _ = self._get(running_server, "/api/roadmap")
        data = json.loads(body)
        assert status == 200
        assert data["milestones"][0]["title"] == "t"

    def test_api_icebox_empty(
        self, running_server: str, sandbox_home: Path
    ) -> None:
        status, body, _ = self._get(running_server, "/api/icebox")
        assert status == 200
        assert json.loads(body) == {"items": []}

    def test_unknown_route_404(self, running_server: str) -> None:
        with pytest.raises(urllib.error.HTTPError) as ei:  # type: ignore[attr-defined]
            self._get(running_server, "/nope")
        assert ei.value.code == 404


# ---------------------------------------------------------------------------
# ntfy wrapper
# ---------------------------------------------------------------------------


class TestNotify:
    def test_no_topic_returns_error(self, sandbox_home: Path) -> None:
        ok, detail = notify.send_notification("hello")
        assert ok is False
        assert "no ntfy topic" in detail

    def test_empty_message(self, sandbox_home: Path) -> None:
        ok, detail = notify.send_notification("   ", topic="abc")
        assert ok is False
        assert "empty" in detail

    def test_env_var_topic_wins(
        self, sandbox_home: Path, monkeypatch
    ) -> None:
        monkeypatch.setenv("LILBRO_NTFY_TOPIC", "my-secret-topic")
        topic = notify._load_topic()  # noqa: SLF001
        assert topic == "my-secret-topic"

    def test_config_yaml_topic(self, sandbox_home: Path) -> None:
        cfg = sandbox_home / ".lilbro-local" / "config.yaml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("notify:\n  topic: fromfile\n", encoding="utf-8")
        assert notify._load_topic() == "fromfile"  # noqa: SLF001

    def test_post_success(self, sandbox_home: Path, monkeypatch) -> None:
        class _Resp:
            status_code = 200
            text = "ok"

        posted: dict = {}

        def fake_post(url, content=None, headers=None, timeout=None):  # noqa: ANN001
            posted["url"] = url
            posted["content"] = content
            posted["headers"] = headers or {}
            return _Resp()

        import httpx  # type: ignore[import-not-found]
        monkeypatch.setattr(httpx, "post", fake_post)
        ok, detail = notify.send_notification(
            "hello world", title="t", topic="abc"
        )
        assert ok is True
        assert "abc" in detail
        assert posted["content"] == b"hello world"
        assert posted["headers"].get("Title") == "t"

    def test_post_failure_returns_false(
        self, sandbox_home: Path, monkeypatch
    ) -> None:
        class _Resp:
            status_code = 500
            text = "boom"

        import httpx  # type: ignore[import-not-found]
        monkeypatch.setattr(
            httpx, "post", lambda *a, **kw: _Resp()  # noqa: ARG005
        )
        ok, detail = notify.send_notification("x", topic="abc")
        assert ok is False
        assert "500" in detail

    def test_post_exception_returns_false(
        self, sandbox_home: Path, monkeypatch
    ) -> None:
        import httpx  # type: ignore[import-not-found]

        def boom(*_a, **_kw) -> None:
            raise httpx.ConnectError("down")

        monkeypatch.setattr(httpx, "post", boom)
        ok, detail = notify.send_notification("x", topic="abc")
        assert ok is False
        assert "failed" in detail
