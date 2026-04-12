"""Quick project switcher -- Ctrl+P.

Shows the 10 most recently used project directories in a floating modal.
Arrow keys + Enter selects one; the app relaunches both agents in the
new directory. Esc closes without switching.

Recent-projects list lives at ``~/.lilbro-local/recent_projects.json``:

    ["<abs_path>", "<abs_path>", ...]   # newest first, max 10

Call ``record_project(path)`` once per session start to keep the list
fresh. The active project is shown at the top and marked with >.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import ListItem, ListView, Static

MAX_RECENT = 10
_RECENT_FILE = Path.home() / ".lilbro-local" / "recent_projects.json"


# ---------------------------------------------------------------------------
# Persistence helpers (called from app startup, not from the modal)
# ---------------------------------------------------------------------------

def load_recent_projects() -> list[str]:
    """Return the recent project list, newest first.  Never raises."""
    try:
        data = json.loads(_RECENT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(p) for p in data[:MAX_RECENT]]
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return []


def record_project(path: str | Path) -> None:
    """Prepend *path* to the recent list and persist it.  Never raises."""
    try:
        abs_path = str(Path(path).resolve())
        recent = load_recent_projects()
        # Deduplicate -- move to front if already present.
        recent = [p for p in recent if p != abs_path]
        recent.insert(0, abs_path)
        recent = recent[:MAX_RECENT]
        _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_FILE.write_text(
            json.dumps(recent, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Modal
# ---------------------------------------------------------------------------

class ProjectSwitcherScreen(ModalScreen):
    """Floating project-switcher modal.  Ctrl+P to open/close."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("ctrl+p", "close", "Close", priority=True, show=False),
    ]

    DEFAULT_CSS = """
    ProjectSwitcherScreen {
        align: center middle;
    }

    #switcher-container {
        width: 70;
        height: auto;
        max-height: 20;
        border: round #A8D840;
        background: #1A1A1A;
        padding: 0 1;
    }

    #switcher-title {
        width: 100%;
        content-align: center middle;
        color: #A8D840;
        text-style: bold;
        height: 1;
        border-bottom: solid #333333;
        padding: 0 1;
    }

    #switcher-list {
        width: 100%;
        height: auto;
        max-height: 14;
        background: #111111;
        margin: 1 0;
    }

    #switcher-empty {
        width: 100%;
        content-align: center middle;
        color: #666666;
        height: 3;
        margin: 1 0;
    }

    #switcher-footer {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: #666666;
        border-top: solid #333333;
    }

    ListItem {
        padding: 0 1;
        color: #E8E8E8;
    }

    ListItem.--highlight {
        background: #2A3518;
        color: #A8D840;
    }
    """

    def __init__(self, current_dir: str, on_switch: Callable[[str], None]) -> None:
        super().__init__()
        self._current = str(Path(current_dir).resolve())
        self._on_switch = on_switch
        self._projects = load_recent_projects()

    def compose(self) -> ComposeResult:
        with Container(id="switcher-container"):
            yield Static("-- SWITCH PROJECT --", id="switcher-title")
            if self._projects:
                items = []
                for p in self._projects:
                    label = ("> " if p == self._current else "  ") + p
                    items.append(ListItem(Static(label)))
                yield ListView(*items, id="switcher-list")
            else:
                yield Static(
                    "No recent projects yet.\nOpen a project with: thebros <path>",
                    id="switcher-empty",
                )
            yield Static("Enter select / Esc close", id="switcher-footer")

    def on_mount(self) -> None:
        if self._projects:
            lv = self.query_one("#switcher-list", ListView)
            lv.focus()
            # Highlight the current project if it's in the list.
            try:
                idx = self._projects.index(self._current)
                lv.index = idx
            except ValueError:
                pass

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index
        if idx is not None and 0 <= idx < len(self._projects):
            chosen = self._projects[idx]
            self.dismiss(None)
            self._on_switch(chosen)

    def action_close(self) -> None:
        self.dismiss(None)
