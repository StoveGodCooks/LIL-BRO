"""Inline slash-command palette.

When the user types `/` as the first character in the input bar, this
widget pops up just above the input with a live-filtered list of all
available slash commands. Navigation:

    Type more chars   -> filter narrows in real time
    Up / Down         -> move selection highlight
    Tab              -> accept the highlighted command into the input
    Enter            -> submit the raw input (palette is only a helper)
    Esc              -> dismiss the palette (keeps input text)

The palette is a passive display -- it never submits or mutates the
input by itself. The `InputBar` owns all keyboard interaction and
calls `filter(query)`, `move_selection(delta)`, and `current_command()`
on it.

Rendering: one `Static` child per visible row. Each row shows the
command name in a color matching its target, followed by the
description in dim text. The currently-selected row has a lime
background bar.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from src_local.ui.commands_meta import COMMANDS, canonical_trigger, filter_commands


# Max number of rows the palette will render at once. If more commands
# match, the excess are hidden; filter further to reach them.
# 25 is enough to show all current commands unfiltered with room to grow.
MAX_ROWS = 25


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
    """Floating slash-command picker above the input bar."""

    DEFAULT_CSS = ""  # all styling lives in app.tcss for consistency

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._query: str = ""
        self._matches: list[tuple[str, str, str]] = list(COMMANDS)
        self._selection: int = 0
        # Row widgets are created lazily on the first show() so this
        # constructor stays cheap.
        self._rows: list[Static] = []

    # -----------------------------------------------------------------
    # Mount / compose
    # -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static("slash commands", id="palette-header")
        yield Static("", id="palette-hint")
        for i in range(MAX_ROWS):
            row = Static("", classes="palette-row")
            self._rows.append(row)
            yield row

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
        self._refresh_rows()

    def move_selection(self, delta: int) -> None:
        """Move the selection highlight by delta rows (wraps around)."""
        if not self._matches:
            return
        n = min(len(self._matches), MAX_ROWS)
        self._selection = (self._selection + delta) % n
        self._refresh_rows()

    def reset_selection(self) -> None:
        self._selection = 0

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
    # Rendering
    # -----------------------------------------------------------------

    def _refresh_rows(self) -> None:
        # If we haven't been mounted yet, bail out -- on_mount will call us.
        # NOTE: do NOT rename this to `_render` -- that collides with
        # Textual's internal Widget._render() and breaks the render loop
        # (AttributeError: 'NoneType' object has no attribute 'render_strips').
        if not self._rows:
            return

        visible_matches = self._matches[:MAX_ROWS]

        # Update header showing match count + hint line.
        try:
            header = self.query_one("#palette-header", Static)
            total = len(self._matches)
            if total == 0:
                header.update(
                    Text("no matching commands", style="italic #888888")
                )
            elif total == 1:
                header.update(
                    Text("1 match  ·  Tab to complete  ·  Esc to cancel",
                         style="#888888")
                )
            else:
                header.update(
                    Text(f"{total} matches  ·  ↑↓ select  ·  Tab complete  ·  Esc cancel",
                         style="#888888")
                )
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

            if i == self._selection:
                row_widget.add_class("selected")
            else:
                row_widget.remove_class("selected")
            row_widget.update(line)
