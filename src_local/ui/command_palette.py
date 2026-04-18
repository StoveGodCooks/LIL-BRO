"""Inline slash-command palette with rolodex scrolling.

When the user types `/` as the first character in the input bar, this
widget pops up just above the input with a live-filtered list of all
available slash commands. Navigation:

    Type more chars   -> filter narrows in real time
    Up / Down         -> move selection highlight (wraps & scrolls)
    Tab              -> accept the highlighted command into the input
    Enter            -> submit the raw input (palette is only a helper)
    Esc              -> dismiss the palette (keeps input text)

The palette uses a windowed "rolodex" view: only VISIBLE_ROWS rows
are rendered at once. As the selection moves past the visible window,
the window shifts to follow it, with scroll indicators (▲/▼) showing
how many items are above/below.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from src_local.ui.commands_meta import COMMANDS, canonical_trigger, filter_commands


# Number of command rows visible at once. The window scrolls around
# the selection like a rolodex.
VISIBLE_ROWS = 12

# Max rows we'll ever render (allocated on mount).
MAX_ROWS = VISIBLE_ROWS


# Color used for commands that target Big Bro.
BIG_BRO_COLOR = "#E8A838"
# Color used for commands that target Lil Bro.
LIL_BRO_COLOR = "#A8D840"
# Dim gray for generic commands.
GENERIC_COLOR = "#888888"
# Active row background marker (CSS paints the real background).
SELECTION_STYLE = "bold reverse"


def _target_color(target: str) -> str:
    if "Big Bro" in target:
        return BIG_BRO_COLOR
    if "Lil Bro" in target:
        return LIL_BRO_COLOR
    return GENERIC_COLOR


class CommandPalette(Vertical):
    """Floating slash-command picker above the input bar (rolodex style)."""

    DEFAULT_CSS = ""  # all styling lives in app.tcss for consistency

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._query: str = ""
        self._matches: list[tuple[str, str, str]] = list(COMMANDS)
        self._selection: int = 0
        # The index of the first visible row in the match list.
        self._window_start: int = 0
        # Row widgets are created lazily on the first show() so this
        # constructor stays cheap.
        self._rows: list[Static] = []

    # -----------------------------------------------------------------
    # Mount / compose
    # -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("slash commands", id="palette-header")
        yield Static("", id="palette-scroll-up", classes="palette-scroll-hint")
        for i in range(MAX_ROWS):
            row = Static("", classes="palette-row")
            self._rows.append(row)
            yield row
        yield Static("", id="palette-scroll-down", classes="palette-scroll-hint")

    def on_mount(self) -> None:
        # Start hidden -- the InputBar shows it when user types '/'.
        self.display = False
        self._refresh_rows()

    # -----------------------------------------------------------------
    # Public API (called by InputBar)
    # -----------------------------------------------------------------

    @property
    def visible(self) -> bool:
        return bool(self.display)

    def show(self) -> None:
        self.display = True
        self._refresh_rows()

    def hide(self) -> None:
        self.display = False

    def filter(self, query: str) -> None:
        """Update the query and refresh the rendered list."""
        self._query = query
        new_matches = filter_commands(query)
        self._matches = new_matches
        # Clamp selection whenever the match list changes.
        if self._selection >= len(self._matches):
            self._selection = max(0, len(self._matches) - 1)
        self._adjust_window()
        self._refresh_rows()

    def move_selection(self, delta: int) -> None:
        """Move the selection highlight by delta rows (wraps around)."""
        if not self._matches:
            return
        n = len(self._matches)
        self._selection = (self._selection + delta) % n
        self._adjust_window()
        self._refresh_rows()

    def reset_selection(self) -> None:
        self._selection = 0
        self._window_start = 0

    def current_command(self) -> str | None:
        """The canonical trigger of the selected row (e.g. ``"/plan"``),
        or None if there's nothing to accept."""
        if not self._matches:
            return None
        row = self._matches[min(self._selection, len(self._matches) - 1)]
        return canonical_trigger(row[0])

    def current_entry(self) -> tuple[str, str, str] | None:
        """The full (name, target, description) tuple for the selected row."""
        if not self._matches:
            return None
        return self._matches[min(self._selection, len(self._matches) - 1)]

    # -----------------------------------------------------------------
    # Window management (rolodex)
    # -----------------------------------------------------------------

    def _adjust_window(self) -> None:
        """Shift the visible window so the selection is always on screen."""
        n = len(self._matches)
        if n <= VISIBLE_ROWS:
            self._window_start = 0
            return

        # If selection is above the window, shift up.
        if self._selection < self._window_start:
            self._window_start = self._selection
        # If selection is below the window, shift down.
        elif self._selection >= self._window_start + VISIBLE_ROWS:
            self._window_start = self._selection - VISIBLE_ROWS + 1

        # Clamp.
        self._window_start = max(0, min(self._window_start, n - VISIBLE_ROWS))

    # -----------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------

    def _refresh_rows(self) -> None:
        # If we haven't been mounted yet, bail out -- on_mount will call us.
        if not self._rows:
            return

        n = len(self._matches)
        window_end = min(self._window_start + VISIBLE_ROWS, n)
        visible_matches = self._matches[self._window_start:window_end]

        # Update header showing match count + hint line.
        try:
            header = self.query_one("#palette-header", Static)
            if n == 0:
                header.update(
                    Text("no matching commands", style="italic #888888")
                )
            elif n == 1:
                header.update(
                    Text("1 match  ·  Tab to complete  ·  Esc to cancel",
                         style="#888888")
                )
            else:
                pos_text = f"[{self._selection + 1}/{n}]"
                header.update(
                    Text(f"{pos_text}  ·  ↑↓ select  ·  Tab complete  ·  Esc cancel",
                         style="#888888")
                )
        except Exception:  # noqa: BLE001
            pass

        # Scroll indicators.
        above = self._window_start
        below = max(0, n - window_end)
        try:
            up_hint = self.query_one("#palette-scroll-up", Static)
            if above > 0:
                up_hint.update(Text(f"  ▲ {above} more above", style="dim #666666"))
                up_hint.display = True
            else:
                up_hint.update("")
                up_hint.display = False
        except Exception:  # noqa: BLE001
            pass
        try:
            down_hint = self.query_one("#palette-scroll-down", Static)
            if below > 0:
                down_hint.update(Text(f"  ▼ {below} more below", style="dim #666666"))
                down_hint.display = True
            else:
                down_hint.update("")
                down_hint.display = False
        except Exception:  # noqa: BLE001
            pass

        # Compute column widths from visible rows for aligned output.
        if visible_matches:
            cmd_w = max(len(name) for name, _, _ in visible_matches) + 2
            tgt_w = max(len(tgt) for _, tgt, _ in visible_matches) + 2
        else:
            cmd_w = tgt_w = 0

        for i, row_widget in enumerate(self._rows):
            if i >= len(visible_matches):
                row_widget.update("")
                row_widget.remove_class("selected")
                row_widget.display = False
                continue
            row_widget.display = True
            actual_index = self._window_start + i
            name, target, desc = visible_matches[i]
            line = Text()
            # Command name in its target color.
            name_color = _target_color(target)
            line.append(name.ljust(cmd_w), style=f"bold {name_color}")
            # Target hint in the same color, dimmer.
            line.append(target.ljust(tgt_w), style=name_color)
            # Description in neutral.
            line.append("  ")
            line.append(desc, style="#CCCCCC")

            if actual_index == self._selection:
                row_widget.add_class("selected")
            else:
                row_widget.remove_class("selected")
            row_widget.update(line)
