"""NotesPad modal -- Ctrl+N freeform scratchpad.

Features
--------
* Ctrl+N  opens/closes the pad from anywhere in the dual-pane screen.
* Ctrl+S  appends the current contents to ~/.lilbro-local/notes.md with a
          timestamp header. Existing notes are never overwritten.
* Ctrl+V  (port) pastes the active panel's last agent reply into the
          TextArea at the cursor position.
* Esc     closes without saving (unsaved text is preserved in memory
          for the session -- re-opening the pad shows it again).
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea

if TYPE_CHECKING:
    pass


class NotesScreen(ModalScreen):
    """Floating scratchpad modal.  Ctrl+N to open/close."""

    BINDINGS = [
        Binding("escape",    "close",      "Close",      priority=True),
        Binding("ctrl+s",    "save_notes", "Save",       priority=True),
        Binding("ctrl+n",    "close",      "Close",      priority=True, show=False),
    ]

    DEFAULT_CSS = """
    NotesScreen {
        align: center middle;
    }

    #notes-container {
        width: 80;
        height: 28;
        border: round #E8A838;
        background: #1A1A1A;
        padding: 0 1;
    }

    #notes-title {
        width: 100%;
        content-align: center middle;
        color: #E8A838;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid #333333;
        height: 1;
    }

    #notes-area {
        width: 100%;
        height: 22;
        background: #111111;
        color: #E8E8E8;
        border: none;
        margin: 1 0;
    }

    #notes-footer {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: #666666;
        border-top: solid #333333;
    }
    """

    def __init__(self, initial_text: str = "") -> None:
        super().__init__()
        self._initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Container(id="notes-container"):
            yield Static("-- NOTES --", id="notes-title")
            yield TextArea(self._initial_text, id="notes-area", language=None)
            yield Static(
                "Ctrl+S save / Ctrl+V port from panel / Esc close",
                id="notes-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#notes-area", TextArea).focus()

    def action_close(self) -> None:
        # Stash current text back to the caller so re-opening preserves it.
        text = self.query_one("#notes-area", TextArea).text
        self.dismiss(text)

    def action_save_notes(self) -> None:
        text = self.query_one("#notes-area", TextArea).text.strip()
        if not text:
            self._show_status("(nothing to save)")
            return
        notes_path = Path.home() / ".lilbro-local" / "notes.md"
        try:
            notes_path.parent.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            header = f"\n\n## {stamp}\n\n"
            with notes_path.open("a", encoding="utf-8") as f:
                f.write(header + text + "\n")
            self._show_status(f"(saved to {notes_path})")
        except OSError as exc:
            self._show_status(f"(save failed: {exc})")

    def _show_status(self, msg: str) -> None:
        self.query_one("#notes-footer", Static).update(msg)
