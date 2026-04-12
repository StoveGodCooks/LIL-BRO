"""Status bar for THE BROS LOCAL -- one-line strip above the input bar.

Shows the current /focus goal (if any), a live "thinking" indicator for
whichever agent is mid-turn, the XP bar (when unlocked), and the
journal filename so the user always knows where their session is being
saved.

The thinking indicator is driven by a half-second timer that polls
``busy_for()`` on both agents.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.timer import Timer
from textual.widgets import Static

from src_local.ui.xp_bar import render_xp_line

if TYPE_CHECKING:
    from src_local.rpg.player import PlayerProfile


class StatusBar(Horizontal):
    """Thin strip rendering focus + busy indicator + journal path."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._focus: str | None = None
        self._focus_started_at: float | None = None
        self._last_focus_text: str = ""
        self._journal_name: str | None = None
        self._big_bro = None
        self._lil_bro = None
        self._busy_timer: Timer | None = None
        # Cache last-rendered busy string so we only call Static.update
        # when the displayed value actually changes.
        self._last_busy_text: str = ""
        # XP strip. Attached lazily so the status bar stays
        # usable without a profile (tests, early init).
        self._profile: "PlayerProfile | None" = None
        self._last_xp_text: str = ""
        self._model_name: str = ""
        self._bunkbed: bool = False

    def compose(self) -> ComposeResult:
        yield Static("", id="status-focus")
        yield Static("", id="status-bunkbed")
        yield Static("", id="status-busy")
        yield Static("", id="status-xp")
        yield Static("", id="status-journal")

    def on_mount(self) -> None:
        self._refresh()
        # 500ms polling -- fast enough that "... 14s -> ... 15s" feels live,
        # slow enough that idle CPU cost is negligible.
        self._busy_timer = self.set_interval(0.5, self._tick_busy)
        if self._model_name:
            try:
                self.query_one("#status-focus", Static).update(
                    f"model: {self._model_name}"
                )
            except Exception:  # noqa: BLE001
                pass

    def on_unmount(self) -> None:
        if self._busy_timer is not None:
            self._busy_timer.stop()
            self._busy_timer = None

    # ---- wiring ----

    def attach_agents(self, big_bro=None, lil_bro=None) -> None:
        """Give the status bar references to both agents so the poll
        timer can ask each one whether it's currently busy."""
        self._big_bro = big_bro
        self._lil_bro = lil_bro

    def attach_profile(self, profile: "PlayerProfile | None") -> None:
        """Bind a PlayerProfile so the XP slot updates on each tick."""
        self._profile = profile
        self._last_xp_text = ""
        self._tick_xp()

    def refresh_xp(self) -> None:
        """Nudge the XP slot to repaint after an XP-bearing action."""
        self._tick_xp()

    def _tick_xp(self) -> None:
        if self._profile is None:
            return
        text = render_xp_line(self._profile)
        if text == self._last_xp_text:
            return
        self._last_xp_text = text
        try:
            xp_widget = self.query_one("#status-xp", Static)
        except Exception:  # noqa: BLE001
            return
        xp_widget.update(text)

    # ---- setters ----

    def set_focus(self, goal: str | None) -> None:
        self._focus = goal
        self._focus_started_at = time.monotonic() if goal else None
        self._last_focus_text = ""
        self._refresh()

    def set_journal(self, path: Path | None) -> None:
        self._journal_name = path.name if path is not None else None
        self._refresh()

    def set_model(self, name: str) -> None:
        self._model_name = name
        try:
            self.query_one("#status-focus", Static).update(f"model: {name}")
        except Exception:  # noqa: BLE001
            pass

    def set_info(self, text: str) -> None:
        try:
            self.query_one("#status-journal", Static).update(text)
        except Exception:  # noqa: BLE001
            pass

    def set_bunkbed(self, on: bool) -> None:
        """Show or hide the BUNKBED indicator."""
        self._bunkbed = on
        try:
            widget = self.query_one("#status-bunkbed", Static)
            widget.update("BUNKBED" if on else "")
        except Exception:  # noqa: BLE001
            pass

    # ---- render ----

    def _focus_text(self) -> str:
        if not self._focus:
            return ""
        if self._focus_started_at is None:
            return f"focus: {self._focus}"
        elapsed = time.monotonic() - self._focus_started_at
        return f"focus: {self._focus} / {self._format_focus_elapsed(elapsed)}"

    def _refresh(self) -> None:
        try:
            focus_widget = self.query_one("#status-focus", Static)
            journal_widget = self.query_one("#status-journal", Static)
        except Exception:  # noqa: BLE001
            return
        text = self._focus_text()
        if self._model_name and not text:
            text = f"model: {self._model_name}"
        self._last_focus_text = text
        focus_widget.update(text)
        journal_widget.update(
            f"journal: {self._journal_name}" if self._journal_name else ""
        )

    def _tick_busy(self) -> None:
        """Recompute the busy indicator and repaint only on change."""
        # Piggyback the focus timer on the same poll.
        if self._focus is not None and self._focus_started_at is not None:
            new_focus_text = self._focus_text()
            if new_focus_text != self._last_focus_text:
                self._last_focus_text = new_focus_text
                try:
                    self.query_one("#status-focus", Static).update(new_focus_text)
                except Exception:  # noqa: BLE001
                    pass
        parts: list[str] = []
        if self._big_bro is not None:
            elapsed = self._big_bro.busy_for()
            if elapsed is not None:
                parts.append(f"Big Bro thinking {self._format_elapsed(elapsed)}")
        if self._lil_bro is not None:
            elapsed = self._lil_bro.busy_for()
            if elapsed is not None:
                parts.append(f"Lil Bro thinking {self._format_elapsed(elapsed)}")
        text = "  /  ".join(parts)
        if text == self._last_busy_text:
            return
        self._last_busy_text = text
        try:
            busy_widget = self.query_one("#status-busy", Static)
        except Exception:  # noqa: BLE001
            return
        busy_widget.update(text)
        # Piggyback XP repaint on the busy tick.
        self._tick_xp()

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        """Human-friendly elapsed time: '3s', '47s', '2m14s'."""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, rem = divmod(s, 60)
        return f"{m}m{rem:02d}s"

    @staticmethod
    def _format_focus_elapsed(seconds: float) -> str:
        """Coarser elapsed for the focus label: '12s', '3m', '1h14m'."""
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m, _ = divmod(s, 60)
        if m < 60:
            return f"{m}m"
        h, rem_m = divmod(m, 60)
        return f"{h}h{rem_m:02d}m"
