"""Tests for the Phase 2 memory subsystem.

- ProjectRegistry: roundtrip / list_recent / increment
- ContextInjector: with a mock MemoryStore
- SessionSummarizer: monkeypatched HTTP call
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest

from src_local.memory.project_registry import ProjectRegistry
from src_local.memory.context_injector import ContextInjector
from src_local.memory.session_summarizer import SessionSummarizer


# ── ProjectRegistry ────────────────────────────────────────────────────────

class TestProjectRegistry:
    def test_register_and_get(self, tmp_path: Path) -> None:
        reg = ProjectRegistry(tmp_path / "projects.json")
        cwd = str(tmp_path / "myproject")
        meta = reg.register(cwd, name="myproject")
        assert meta["name"] == "myproject"
        assert meta["session_count"] == 0
        assert "last_seen" in meta

        got = reg.get(cwd)
        assert got is not None
        assert got["name"] == "myproject"

    def test_get_unknown_returns_none(self, tmp_path: Path) -> None:
        reg = ProjectRegistry(tmp_path / "projects.json")
        assert reg.get("/nonexistent/project") is None

    def test_increment_session_count(self, tmp_path: Path) -> None:
        reg = ProjectRegistry(tmp_path / "projects.json")
        cwd = str(tmp_path)
        reg.register(cwd)
        reg.increment_session_count(cwd)
        reg.increment_session_count(cwd)
        got = reg.get(cwd)
        assert got is not None
        assert got["session_count"] == 2

    def test_list_recent_order(self, tmp_path: Path) -> None:
        reg = ProjectRegistry(tmp_path / "projects.json")
        p1 = str(tmp_path / "proj1")
        p2 = str(tmp_path / "proj2")
        reg.register(p1)
        time.sleep(0.01)  # ensure different timestamps
        reg.register(p2)
        recent = reg.list_recent(n=5)
        # proj2 was registered more recently
        assert recent[0]["path"] == str(Path(p2).resolve())

    def test_persist_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "projects.json"
        reg1 = ProjectRegistry(path)
        cwd = str(tmp_path / "alpha")
        reg1.register(cwd, name="alpha")

        # Reload from disk
        reg2 = ProjectRegistry(path)
        got = reg2.get(cwd)
        assert got is not None
        assert got["name"] == "alpha"

    def test_resolved_paths(self, tmp_path: Path) -> None:
        """Absolute path resolves correctly."""
        reg = ProjectRegistry(tmp_path / "projects.json")
        abs_path = str(tmp_path.resolve())
        reg.register(abs_path, name="root")
        got = reg.get(abs_path)
        assert got is not None


# ── ContextInjector ────────────────────────────────────────────────────────

class MockMemoryStore:
    """Minimal stand-in for MemoryStore."""

    def __init__(self, results: list[dict]) -> None:
        self._results = results

    def search(self, query: str, n: int = 5) -> list[dict]:
        return self._results[:n]


@pytest.mark.asyncio
async def test_injector_injects_memories() -> None:
    ts = 1713456789.0
    store = MockMemoryStore([
        {"text": "Fixed the router bug", "metadata": {"timestamp": ts}},
    ])
    injector = ContextInjector(store, max_memories=3)
    prompt = "What did we fix last time?"
    result = await injector.inject(prompt, project="/proj")
    assert "[Memory:" in result
    assert "Fixed the router bug" in result
    assert "---" in result
    assert result.endswith(prompt)


@pytest.mark.asyncio
async def test_injector_short_prompt_unchanged() -> None:
    store = MockMemoryStore([{"text": "some memory", "metadata": {}}])
    injector = ContextInjector(store)
    result = await injector.inject("hi")
    assert result == "hi"


@pytest.mark.asyncio
async def test_injector_no_memories_unchanged() -> None:
    store = MockMemoryStore([])
    injector = ContextInjector(store)
    prompt = "This is a long enough prompt to warrant injection"
    result = await injector.inject(prompt)
    assert result == prompt


@pytest.mark.asyncio
async def test_injector_store_failure_returns_original() -> None:
    class BrokenStore:
        def search(self, query: str, n: int = 5) -> list[dict]:
            raise RuntimeError("db offline")

    injector = ContextInjector(BrokenStore())  # type: ignore[arg-type]
    prompt = "This prompt is long enough to trigger injection logic"
    result = await injector.inject(prompt)
    assert result == prompt


# ── SessionSummarizer ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summarizer_empty_returns_empty() -> None:
    summarizer = SessionSummarizer()
    result = await summarizer.summarize("   ")
    assert result == ""


@pytest.mark.asyncio
async def test_summarizer_monkeypatched_urllib(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Monkeypatch urllib so no real HTTP call is made."""
    fake_response = json.dumps({"response": "Fixed a memory bug."}).encode()

    import urllib.request as _req

    class FakeHTTPResponse:
        def read(self) -> bytes:
            return fake_response

    monkeypatch.setattr(_req, "urlopen", lambda *a, **kw: FakeHTTPResponse())
    summarizer = SessionSummarizer()
    result = await summarizer._summarize_python(
        "http://127.0.0.1:11434/api/generate",
        b"{}",
    )
    assert result == "Fixed a memory bug."


@pytest.mark.asyncio
async def test_summarizer_falls_back_when_curl_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When curl is missing, _summarize_python is called."""
    import urllib.request as _req

    fake_response = json.dumps({"response": "Built a router."}).encode()

    class FakeHTTPResponse:
        def read(self) -> bytes:
            return fake_response

    monkeypatch.setattr(_req, "urlopen", lambda *a, **kw: FakeHTTPResponse())

    async def _fake_exec(*args: Any, **kwargs: Any) -> None:
        raise FileNotFoundError("curl not found")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)

    summarizer = SessionSummarizer()
    result = await summarizer.summarize("A long session transcript about routing.")
    assert result == "Built a router."
