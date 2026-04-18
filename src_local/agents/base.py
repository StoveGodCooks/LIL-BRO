"""Abstract base for agent subprocess wrappers.

Holds shared lifecycle plumbing:

* a per-agent ``asyncio.Lock`` so concurrent ``request()`` calls serialize
  one-at-a-time inside the same process,
* a *set* of live tasks so the event loop keeps a strong reference and the
  GC can't prematurely drop an in-flight turn,
* a ``cancel_in_flight()`` hook that the Esc keybinding / ``/cancel``
  command / router can call to abort the currently-running turn without
  killing the subprocess.

Subclasses implement ``start()``, ``stop()``, and ``_stream_reply()``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from src_local.agents.phrases import get_next_phase as _get_next_phase

_TRANSCRIPT_DIR = Path.home() / ".lilbro" / "transcripts"

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel


EventKind = Literal["text_delta", "assistant_done", "tool_use", "error", "system"]


@dataclass
class AgentEvent:
    kind: EventKind
    text: str = ""


logger = logging.getLogger("lilbro.agent")

# Rolling activity window. Every ACTIVITY_CHECK_SECONDS the heartbeat
# watcher looks at whether the subprocess produced any new events since
# the last check:
#   * If yes  → post a rotating "working" phase message and continue.
#   * If no   → post a "(silent Xs — /restart if stuck)" warning.
# As long as tool calls / text deltas keep arriving, the turn runs
# indefinitely.
ACTIVITY_CHECK_SECONDS = 120.0   # 2 minutes
HEARTBEAT_CHECK_INTERVAL = 5.0   # inner poll cadence

# Defensive cap on a single stdout line from an agent subprocess.
# Anything larger is almost certainly a malformed or pathologically
# chunked event — we skip it, log the size, and post one system line
# so the user knows something was dropped.
MAX_STREAM_LINE_BYTES = 1_048_576

# RSS monitor: a background task per agent polls the subprocess's
# resident-set size every RSS_CHECK_INTERVAL seconds. When RSS crosses
# the soft ceiling, we wait for the current turn to finish and then
# recycle the subprocess. Hard ceiling (1.5× soft) force-restarts
# mid-turn.
RSS_CHECK_INTERVAL = 15.0
RSS_HARD_MULTIPLIER = 1.5

# Per-turn streamed-byte budget. When a single turn's cumulative text
# deltas cross this threshold, further chunks are dropped and a single
# "(backpressure: ...)" system line is posted. The budget resets at the
# start of every turn.
TURN_STREAM_BUDGET_BYTES = 2 * 1024 * 1024  # 2 MiB


def _fmt_bytes(n: int) -> str:
    """Human-friendly byte count: '1.3 GB', '742 MB', '12.0 KB'."""
    units = [("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]
    for unit, denom in units:
        if n >= denom:
            return f"{n / denom:.1f} {unit}"
    return f"{n} B"


def _read_rss_bytes(pid: int | None) -> int | None:
    """Return the RSS of the given pid in bytes, or None if unavailable."""
    if pid is None:
        return None
    try:
        import psutil  # type: ignore[import-not-found]

        try:
            return int(psutil.Process(pid).memory_info().rss)
        except psutil.NoSuchProcess:  # type: ignore[attr-defined]
            return None
        except Exception:  # noqa: BLE001
            return None
    except ImportError:
        pass
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as fh:
            for ln in fh:
                if ln.startswith("VmRSS:"):
                    parts = ln.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024  # kB → bytes
    except OSError:
        return None
    return None


async def safe_readline(
    stdout: asyncio.StreamReader, max_bytes: int = MAX_STREAM_LINE_BYTES
) -> tuple[bytes, int]:
    """Wrap ``stdout.readuntil('\\n')`` with a defensive line-length cap.

    Returns ``(line, skipped_bytes)``. ``readuntil`` (not ``readline``)
    is used so we get the raw ``LimitOverrunError`` and can drain the
    over-cap content cleanly, reporting exactly how many bytes were
    thrown away.
    """
    try:
        line = await stdout.readuntil(b"\n")
        return line, 0
    except asyncio.IncompleteReadError as exc:
        return exc.partial, 0
    except asyncio.LimitOverrunError as exc:
        skipped = 0
        try:
            await stdout.readexactly(exc.consumed)
            skipped += exc.consumed
        except asyncio.IncompleteReadError as exc2:
            skipped += len(exc2.partial)
            return b"", skipped
        except Exception:  # noqa: BLE001
            pass
        while True:
            try:
                rest = await stdout.readuntil(b"\n")
                skipped += len(rest)
                break
            except asyncio.LimitOverrunError as exc3:
                try:
                    await stdout.readexactly(exc3.consumed)
                    skipped += exc3.consumed
                except asyncio.IncompleteReadError as exc4:
                    skipped += len(exc4.partial)
                    break
                except Exception:  # noqa: BLE001
                    break
            except asyncio.IncompleteReadError as exc3:
                skipped += len(exc3.partial)
                break
            except Exception:  # noqa: BLE001
                break
        return b"", skipped


class AgentProcess(ABC):
    """Persistent subprocess wrapper interface.

    Subclasses spawn a persistent subprocess (Ollama HTTP client, Claude
    CLI, Codex CLI, ...) and stream its replies into a ``_BasePanel``.
    The base class owns lifecycle plumbing — lock, task tracking,
    heartbeat, RSS monitor, per-turn stream budget — so each connector
    only needs to implement the wire protocol.
    """

    DISPLAY_NAME: str = "Agent"
    RESTART_KEY: str = "agent"
    DEFAULT_RSS_SOFT_LIMIT_BYTES: int = 0

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task] = set()
        self._current_task: asyncio.Task | None = None
        self._turn_started_at: float | None = None
        self._last_activity_at: float | None = None
        self._rss_soft_limit_bytes: int = self.DEFAULT_RSS_SOFT_LIMIT_BYTES
        self._rss_monitor_task: asyncio.Task | None = None
        self._rss_recycle_pending: bool = False
        self._turn_stream_bytes: int = 0
        self._turn_stream_warned: bool = False

    @abstractmethod
    async def start(self) -> None:
        """Spawn the persistent subprocess and wait for readiness."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the subprocess."""

    @abstractmethod
    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        """Subclass hook — sends a prompt and streams the reply into the panel."""

    def request(self, prompt: str, panel: "_BasePanel") -> None:
        """Fire-and-forget request. Serializes writes via an asyncio.Lock."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error(
                "%s.request called outside a running event loop", self.DISPLAY_NAME
            )
            return
        task = loop.create_task(
            self._request_locked(prompt, panel),
            name=f"{self.DISPLAY_NAME}-turn",
        )
        self._tasks.add(task)
        self._current_task = task
        task.add_done_callback(self._tasks.discard)

    async def _request_locked(self, prompt: str, panel: "_BasePanel") -> None:
        async with self._lock:
            self._turn_stream_bytes = 0
            self._turn_stream_warned = False
            now = time.monotonic()
            self._turn_started_at = now
            self._last_activity_at = now
            heartbeat = asyncio.create_task(
                self._heartbeat_watch(panel),
                name=f"{self.DISPLAY_NAME}-heartbeat",
            )
            try:
                await self._stream_reply(prompt, panel)
            except asyncio.CancelledError:
                panel.append_system("(turn cancelled)")
                logger.info("%s turn cancelled by user", self.DISPLAY_NAME)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("%s crashed during turn", self.DISPLAY_NAME)
                panel.append_error(f"{self.DISPLAY_NAME} error: {exc}")
            finally:
                heartbeat.cancel()
                try:
                    await heartbeat
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    logger.exception("heartbeat task crashed during turn")
                self._turn_started_at = None
                self._last_activity_at = None
                if os.environ.get("LILBRO_DEBUG"):
                    self._write_transcript(prompt, panel)

    def _write_transcript(self, prompt: str, panel: "_BasePanel") -> None:
        """Write prompt + panel response to ~/.lilbro/transcripts/ for bug reports."""
        try:
            _TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            slug = self.DISPLAY_NAME.lower().replace(" ", "_")
            fname = f"{stamp}_{slug}.txt"
            response = getattr(panel, "_last_assistant_message", "") or ""
            content = (
                f"agent: {self.DISPLAY_NAME}\n"
                f"time:  {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"\n--- prompt ---\n{prompt}\n"
                f"\n--- response ---\n{response}\n"
            )
            (_TRANSCRIPT_DIR / fname).write_text(content, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    async def _heartbeat_watch(self, panel: "_BasePanel") -> None:
        """Post rolling phase messages while the subprocess is working."""
        phase_idx = 0
        last_seen: float | None = self._last_activity_at
        accumulated: float = 0.0
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_CHECK_INTERVAL)
                if self._last_activity_at is None:
                    return
                accumulated += HEARTBEAT_CHECK_INTERVAL
                if accumulated < ACTIVITY_CHECK_SECONDS:
                    continue
                accumulated = 0.0
                current = self._last_activity_at
                try:
                    if current != last_seen:
                        msg = _get_next_phase(phase_idx)
                        phase_idx += 1
                        last_seen = current
                        panel.append_system(f"({msg})")
                    else:
                        silence = int(time.monotonic() - (current or time.monotonic()))
                        panel.append_system(
                            f"(silent {silence}s — "
                            f"/restart {self.RESTART_KEY} if stuck)"
                        )
                except Exception:  # noqa: BLE001
                    pass
        except asyncio.CancelledError:
            raise

    def note_activity(self) -> None:
        """Subclass reader loops call this when a parsed event arrives."""
        if self._turn_started_at is not None:
            self._last_activity_at = time.monotonic()

    # ------------------------------------------------------------------
    # Per-turn stream-byte budget (reader-loop backpressure)
    # ------------------------------------------------------------------

    def note_stream_bytes(self, panel: "_BasePanel", nbytes: int) -> bool:
        """Charge ``nbytes`` against the current turn's stream budget.

        Returns True if the caller should paint the chunk, False if the
        chunk should be dropped (budget exceeded). Emits a single
        ``(backpressure: ...)`` system line the first time the budget
        trips in a given turn.
        """
        if self._turn_started_at is None:
            return False
        self._turn_stream_bytes += max(0, nbytes)
        if self._turn_stream_bytes <= TURN_STREAM_BUDGET_BYTES:
            return True
        if not self._turn_stream_warned:
            self._turn_stream_warned = True
            try:
                kb = TURN_STREAM_BUDGET_BYTES // 1024
                panel.append_system(
                    f"(backpressure: turn exceeded {kb} KB — dropping further "
                    f"stream chunks until the turn ends)"
                )
            except Exception:  # noqa: BLE001
                pass
        return False

    # ------------------------------------------------------------------
    # RSS ceiling + auto-recycle
    # ------------------------------------------------------------------

    def set_rss_limit(self, soft_bytes: int) -> None:
        """Configure the RSS soft ceiling. Call before ``start()``."""
        self._rss_soft_limit_bytes = max(0, int(soft_bytes))

    @property
    def rss_soft_limit_bytes(self) -> int:
        return self._rss_soft_limit_bytes

    def _get_pid(self) -> int | None:
        """Subclass hook — current subprocess PID, or None if not running."""
        return getattr(self, "pid", None)

    def start_rss_monitor(self, panel: "_BasePanel") -> None:
        """Spawn the background RSS poller. Idempotent."""
        if self._rss_soft_limit_bytes <= 0:
            return
        if self._rss_monitor_task is not None and not self._rss_monitor_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._rss_monitor_task = loop.create_task(
            self._rss_monitor_loop(panel),
            name=f"{self.DISPLAY_NAME}-rss-monitor",
        )

    def stop_rss_monitor(self) -> None:
        task = self._rss_monitor_task
        if task is None:
            return
        self._rss_monitor_task = None
        task.cancel()

    async def _rss_monitor_loop(self, panel: "_BasePanel") -> None:
        """Poll RSS every ``RSS_CHECK_INTERVAL`` seconds."""
        soft = self._rss_soft_limit_bytes
        if soft <= 0:
            return
        hard = int(soft * RSS_HARD_MULTIPLIER)
        try:
            while True:
                await asyncio.sleep(RSS_CHECK_INTERVAL)
                pid = self._get_pid()
                rss = _read_rss_bytes(pid)
                if rss is None:
                    continue
                logger.debug(
                    "%s RSS = %d bytes (soft=%d hard=%d)",
                    self.DISPLAY_NAME, rss, soft, hard,
                )
                if rss >= hard:
                    try:
                        panel.append_system(
                            f"(hard RSS cap hit — force-recycling "
                            f"{self.RESTART_KEY}; RSS was "
                            f"{_fmt_bytes(rss)})"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    self.cancel_in_flight()
                    try:
                        await self.restart(panel)
                    except Exception as exc:  # noqa: BLE001
                        try:
                            panel.append_error(
                                f"RSS-triggered restart failed: {exc}"
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        return
                    return
                if rss >= soft and not self._rss_recycle_pending:
                    self._rss_recycle_pending = True
                    while self.is_busy():
                        try:
                            await asyncio.sleep(1.0)
                        except asyncio.CancelledError:
                            raise
                    try:
                        panel.append_system(
                            f"(recycled {self.RESTART_KEY} — RSS was "
                            f"{_fmt_bytes(rss)}, soft cap "
                            f"{_fmt_bytes(soft)})"
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        await self.restart(panel)
                    except Exception as exc:  # noqa: BLE001
                        try:
                            panel.append_error(
                                f"RSS recycle failed: {exc}"
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "%s RSS monitor crashed: %s", self.DISPLAY_NAME, exc
            )
            return

    async def restart(self, panel: "_BasePanel") -> None:
        """Default restart: stop + start. Subclasses may override."""
        await self.stop()
        await self.start()

    def cancel_in_flight(self) -> bool:
        """Cancel the currently-running turn task, if any."""
        task = self._current_task
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def is_busy(self) -> bool:
        """True if a turn is currently in flight."""
        task = self._current_task
        return task is not None and not task.done()

    def busy_for(self) -> float | None:
        """Seconds the current turn has been running, or None if idle."""
        started = self._turn_started_at
        if started is None:
            return None
        return max(0.0, time.monotonic() - started)
