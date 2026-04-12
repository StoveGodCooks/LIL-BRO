"""Ctrl+F scrollback search modal.

A tiny floating modal that live-filters writes recorded in the active
panel's ``_search_corpus`` and jumps the RichLog viewport to each match.

Design notes
------------

* The modal is intentionally stupid: each keystroke re-queries the
  active panel's corpus. The corpus is a flat list of
  ``(plain_text, strip_index)`` tuples built as writes happen, so this
  is O(n) per keystroke -- fine for the thousands of lines a typical
  panel will ever hold.
* Enter / Down advances to the next match. Up goes back. We wrap around
  at both ends so the user never gets stuck.
* Jumping a match uses ``panel.scroll_to_strip(strip_index)``, which
  calls ``RichLog.scroll_to(y=...)``. RichLog's built-in auto_scroll
  would normally yank us back to the bottom when the next delta
  arrives, so we temporarily freeze auto_scroll while the modal is up
  and restore it on dismissal.
* Matches are stable within a search session -- we snapshot the list
  of indices on every query so incoming writes don't shift the cursor
  underneath the user mid-search.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel


class SearchScreen(ModalScreen):
    """Floating find-in-panel modal. Spawned by Ctrl+F on the active panel."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("enter", "next_match", "Next", priority=True),
        Binding("down", "next_match", "Next", priority=True),
        Binding("up", "prev_match", "Prev", priority=True),
    ]

    def __init__(self, panel: "_BasePanel", panel_label: str) -> None:
        super().__init__()
        self.panel = panel
        self.panel_label = panel_label
        self._matches: list[int] = []
        self._cursor: int = -1
        # Freeze auto_scroll on the target log so jumping backwards
        # doesn't get immediately undone by the next streamed chunk.
        # We capture the prior value so we can restore it on close.
        self._prior_auto_scroll: bool = True
        try:
            self._prior_auto_scroll = bool(panel.log_widget.auto_scroll)
        except Exception:  # noqa: BLE001
            pass

    def compose(self) -> ComposeResult:
        with Container(id="search-container"):
            yield Static(
                f"Find in {self.panel_label}",
                id="search-title",
            )
            with Horizontal(id="search-row"):
                yield Input(placeholder="search text...", id="search-input")
                yield Static("", id="search-count")
            yield Static(
                "Enter / Down next  /  Up prev  /  Esc close",
                id="search-footer",
            )

    def on_mount(self) -> None:
        try:
            self.panel.log_widget.auto_scroll = False
        except Exception:  # noqa: BLE001
            pass
        self.query_one("#search-input", Input).focus()

    def on_unmount(self) -> None:
        # Restore the panel's prior auto_scroll state so incoming deltas
        # resume pinning to the bottom.
        try:
            self.panel.log_widget.auto_scroll = self._prior_auto_scroll
        except Exception:  # noqa: BLE001
            pass

    # ---- actions ----

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "search-input":
            return
        query = event.value.strip()
        self._matches = self.panel.search(query)
        self._cursor = 0 if self._matches else -1
        self._update_count()
        if self._matches:
            self._jump_to_cursor()

    def action_next_match(self) -> None:
        if not self._matches:
            return
        self._cursor = (self._cursor + 1) % len(self._matches)
        self._update_count()
        self._jump_to_cursor()

    def action_prev_match(self) -> None:
        if not self._matches:
            return
        self._cursor = (self._cursor - 1) % len(self._matches)
        self._update_count()
        self._jump_to_cursor()

    def action_close(self) -> None:
        self.app.pop_screen()

    # ---- helpers ----

    def _jump_to_cursor(self) -> None:
        if not (0 <= self._cursor < len(self._matches)):
            return
        strip_index = self._matches[self._cursor]
        self.panel.scroll_to_strip(strip_index)

    def _update_count(self) -> None:
        count = self.query_one("#search-count", Static)
        if not self._matches:
            count.update(Text("0 matches", style="dim #888888"))
            return
        text = Text()
        text.append(f"{self._cursor + 1}", style="bold #E8A838")
        text.append(" / ", style="dim #888888")
        text.append(f"{len(self._matches)}", style="bold #E8E8E8")
        text.append(" matches", style="dim #888888")
        count.update(text)
