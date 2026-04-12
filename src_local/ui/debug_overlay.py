"""Translucent in-panel debug overlay.

Toggled by ``Ctrl+Shift+D`` on ``DualPaneScreen``. When visible, a
1-second ``Timer`` refreshes the body with:

- Asyncio task count (``len(asyncio.all_tasks())``)
- Big Bro RSS + Lil Bro RSS (via the existing ``_read_rss_bytes`` helper)
- Big Bro + Lil Bro turn state (idle / busy + seconds elapsed)
- Last 10 lines of ``~/.lilbro-local/debug.log``
- Frame counter (incremented every tick -- a crude "refresh is alive"
  indicator since Textual doesn't expose a real FPS figure)

Deliberately uses only a ``Static`` widget and a ``Timer`` -- no new
dependencies, no reactive attributes, no compose hierarchy. The whole
thing is one file + ~10 lines of CSS + one binding.

The overlay positions itself over the top-right corner of the panes
container via absolute dock. When hidden (the default), it has
``display: none`` and the timer is not running -- zero cost when off.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections import deque
from pathlib import Path

from rich.text import Text
from textual.widgets import Static


logger = logging.getLogger("lilbro.debug_overlay")

_DEBUG_LOG_PATH = Path.home() / ".lilbro-local" / "debug.log"
_TAIL_LINES = 10


def _fmt_mb(n_bytes: int | None) -> str:
    """Human-readable megabyte figure, or ``?`` if unknown."""
    if n_bytes is None or n_bytes <= 0:
        return "?"
    mb = n_bytes / (1024 * 1024)
    if mb < 10:
        return f"{mb:.1f} MB"
    return f"{int(mb)} MB"


def _tail_debug_log(path: Path, lines: int) -> list[str]:
    """Return the last ``lines`` lines of ``path``, or ``[]`` on any error.

    Uses a bounded ``deque`` so we never load a large rotating log file
    into memory.
    """
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return list(deque(fh, maxlen=lines))
    except Exception:  # noqa: BLE001
        return []


class DebugOverlay(Static):
    """A Static widget that paints a live diagnostic snapshot.

    Owned by ``DualPaneScreen``. Its parent wires up the 1 Hz refresh
    timer when shown and tears it down when hidden -- the overlay
    itself just knows how to ``render()``.
    """

    DEFAULT_CSS = """
    DebugOverlay {
        dock: top;
        offset: 0 1;
        layer: overlay;
        width: 48;
        height: auto;
        padding: 0 1;
        background: #0A0A0A 85%;
        border: round #E8A838;
        color: #E8E8E8;
        display: none;
    }
    DebugOverlay.visible {
        display: block;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._frame: int = 0
        self._big_bro = None
        self._lil_bro = None

    def attach_agents(self, big_bro, lil_bro) -> None:
        self._big_bro = big_bro
        self._lil_bro = lil_bro

    # -----------------------------------------------------------------
    # Visibility
    # -----------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return self.has_class("visible")

    def show(self) -> None:
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    def toggle(self) -> bool:
        """Flip visibility. Returns True if now visible, False if now hidden."""
        if self.visible:
            self.hide()
            return False
        self.show()
        return True

    # -----------------------------------------------------------------
    # Refresh
    # -----------------------------------------------------------------

    def refresh_snapshot(self) -> None:
        """Rebuild the overlay body from current agent + loop state.

        Never raises -- any probe that throws is rendered as ``?``.
        """
        try:
            self._frame += 1
            body = self._build_body()
            self.update(body)
        except Exception:  # noqa: BLE001
            logger.exception("debug overlay refresh failed")

    def _build_body(self) -> Text:
        text = Text()
        text.append("-- DEBUG OVERLAY --", style="bold #E8A838")
        text.append(f"  (frame {self._frame})\n", style="#666666")

        # Event loop snapshot
        try:
            task_count = len(asyncio.all_tasks())
        except RuntimeError:
            task_count = -1
        text.append("tasks: ", style="#888888")
        text.append(f"{task_count if task_count >= 0 else '?'}\n", style="#E8E8E8")

        # Per-agent snapshot
        text.append(self._agent_line("big bro", self._big_bro))
        text.append(self._agent_line("lil bro", self._lil_bro))

        # Last N debug log lines (trimmed + wrapped by RichLog implicitly)
        text.append("-- last log --\n", style="bold #888888")
        for raw in _tail_debug_log(_DEBUG_LOG_PATH, _TAIL_LINES):
            line = raw.rstrip("\n")
            # Hard-truncate every line so a 500-char stack trace can't
            # balloon the overlay. 44 fits inside the 48-wide border.
            if len(line) > 44:
                line = line[:41] + "..."
            text.append(f"{line}\n", style="#888888")
        return text

    def _agent_line(self, label: str, agent) -> Text:
        line = Text()
        line.append(f"{label}: ", style="#888888")
        if agent is None:
            line.append("--\n", style="#666666")
            return line
        busy = False
        try:
            busy = bool(agent.is_busy())
        except Exception:  # noqa: BLE001
            busy = False
        state = "busy" if busy else "idle"
        state_style = "#E8E038" if busy else "#A8D840"
        line.append(f"{state}\n", style=state_style)
        return line


def debug_overlay_enabled() -> bool:
    """Cheap feature flag: the overlay is always wired; users enable it
    per-session via ``Ctrl+Shift+D``. Kept as a function so a future
    ``LILBRO_DEBUG_OVERLAY=0`` env-var disable is a one-line patch."""
    return os.environ.get("LILBRO_DEBUG_OVERLAY", "1") != "0"
