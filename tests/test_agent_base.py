"""Tests for the shared AgentProcess base class.

Covers lifecycle plumbing that every connector depends on: lock
serialization, cancel-in-flight, busy/busy_for state, activity bumps,
and the per-turn stream-byte backpressure budget.
"""

from __future__ import annotations

import asyncio

import pytest

from src_local.agents.base import (
    AgentProcess,
    TURN_STREAM_BUDGET_BYTES,
    _fmt_bytes,
)


class _FakePanel:
    """Minimal panel stub matching the subset of _BasePanel the base uses."""

    def __init__(self) -> None:
        self.system: list[str] = []
        self.errors: list[str] = []

    def append_system(self, text: str) -> None:
        self.system.append(text)

    def append_error(self, text: str) -> None:
        self.errors.append(text)


class _EchoAgent(AgentProcess):
    """Deterministic connector stub used by these tests."""

    DISPLAY_NAME = "Echo"
    RESTART_KEY = "echo"

    def __init__(self, *, stream_delay: float = 0.0) -> None:
        super().__init__()
        self._stream_delay = stream_delay
        self.started = False
        self.stopped = False
        self.replies: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def _stream_reply(self, prompt: str, panel) -> None:  # noqa: ANN001
        if self._stream_delay:
            await asyncio.sleep(self._stream_delay)
        self.replies.append(prompt)
        self.note_activity()


@pytest.mark.asyncio
async def test_idle_state() -> None:
    agent = _EchoAgent()
    assert not agent.is_busy()
    assert agent.busy_for() is None


@pytest.mark.asyncio
async def test_request_runs_stream_reply() -> None:
    agent = _EchoAgent()
    panel = _FakePanel()
    agent.request("hello", panel)
    # Let the event loop run the scheduled turn to completion.
    await asyncio.sleep(0.05)
    assert agent.replies == ["hello"]
    assert not agent.is_busy()


@pytest.mark.asyncio
async def test_requests_serialize_via_lock() -> None:
    """Two requests fired back-to-back must not interleave inside the lock."""
    agent = _EchoAgent(stream_delay=0.05)
    panel = _FakePanel()
    agent.request("first", panel)
    agent.request("second", panel)
    # Wait long enough for both turns to complete sequentially.
    await asyncio.sleep(0.25)
    assert agent.replies == ["first", "second"]


@pytest.mark.asyncio
async def test_cancel_in_flight() -> None:
    agent = _EchoAgent(stream_delay=1.0)
    panel = _FakePanel()
    agent.request("slow", panel)
    await asyncio.sleep(0.05)
    assert agent.is_busy()
    cancelled = agent.cancel_in_flight()
    assert cancelled
    # Let cancellation propagate.
    await asyncio.sleep(0.05)
    assert not agent.is_busy()
    assert any("cancelled" in msg for msg in panel.system)


@pytest.mark.asyncio
async def test_cancel_when_idle_returns_false() -> None:
    agent = _EchoAgent()
    assert agent.cancel_in_flight() is False


@pytest.mark.asyncio
async def test_busy_for_tracks_turn_duration() -> None:
    agent = _EchoAgent(stream_delay=0.1)
    panel = _FakePanel()
    agent.request("slow", panel)
    await asyncio.sleep(0.03)
    elapsed = agent.busy_for()
    assert elapsed is not None and elapsed > 0
    await asyncio.sleep(0.2)
    assert agent.busy_for() is None


@pytest.mark.asyncio
async def test_note_stream_bytes_under_budget() -> None:
    agent = _EchoAgent(stream_delay=0.1)
    panel = _FakePanel()
    agent.request("x", panel)
    await asyncio.sleep(0.01)
    # Inside a live turn, a small chunk should pass the budget.
    assert agent.note_stream_bytes(panel, 1024) is True
    await asyncio.sleep(0.15)


@pytest.mark.asyncio
async def test_note_stream_bytes_trips_backpressure() -> None:
    agent = _EchoAgent(stream_delay=0.2)
    panel = _FakePanel()
    agent.request("x", panel)
    await asyncio.sleep(0.01)
    over = TURN_STREAM_BUDGET_BYTES + 1
    assert agent.note_stream_bytes(panel, over) is False
    # A single one-shot system warning is posted, not one per chunk.
    assert agent.note_stream_bytes(panel, 1024) is False
    warnings = [m for m in panel.system if "backpressure" in m]
    assert len(warnings) == 1
    await asyncio.sleep(0.25)


@pytest.mark.asyncio
async def test_note_stream_bytes_when_idle_returns_false() -> None:
    agent = _EchoAgent()
    panel = _FakePanel()
    # No active turn — chunks are always dropped and never counted.
    assert agent.note_stream_bytes(panel, 512) is False


def test_set_rss_limit_clamps_negative_to_zero() -> None:
    agent = _EchoAgent()
    agent.set_rss_limit(-1)
    assert agent.rss_soft_limit_bytes == 0
    agent.set_rss_limit(1024)
    assert agent.rss_soft_limit_bytes == 1024


def test_fmt_bytes() -> None:
    assert _fmt_bytes(512) == "512 B"
    assert _fmt_bytes(2048) == "2.0 KB"
    assert _fmt_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert _fmt_bytes(2 * 1024 * 1024 * 1024) == "2.0 GB"
