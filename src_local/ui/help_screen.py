"""Help modal -- lists every slash command and keyboard shortcut.

Pushed on F1 / Ctrl+H / `/help`. Dismiss with Esc / F1 / Q.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from src_local.ui.commands_meta import COMMANDS


# -----------------------------------------------------------------------------
# Data -- single source of truth for the help display
# -----------------------------------------------------------------------------

HOTKEYS: list[tuple[str, str]] = [
    ("Type /",           "Open the inline slash-command palette (live filter)"),
    ("Tab",              "In palette: accept selection  /  Otherwise: switch Big Bro <-> Lil Bro"),
    ("Up / Down",        "In palette: move selection  /  Otherwise: scroll active panel"),
    ("Right arrow",      "Accept ghost-text autocomplete suggestion"),
    ("Ctrl+C",           "Port Big Bro's last reply -> Lil Bro's input"),
    ("Ctrl+B",           "Port Lil Bro's last reply -> Big Bro's input"),
    ("Ctrl+L",           "Clear the active panel's scrollback"),
    ("Ctrl+F",           "Find-in-panel / live-filter scrollback, Enter jumps to next match"),
    ("Ctrl+W",           "Toggle soft word-wrap on the active panel  /  same as /wrap"),
    ("Ctrl+Y",           "Copy active panel's last reply to clipboard"),
    ("Ctrl+Shift+Y",     "Copy last reply as shareable Markdown (header + attribution)"),
    ("Ctrl+R",           "Retry the last prompt on the active agent"),
    ("PgUp / PgDn",      "Scroll the active panel one page up / down"),
    ("Click panel",      "Switch active target to the clicked pane"),
    ("F1 / Ctrl+H",      "Open this help screen"),
    ("F2",               "Show SESSION.md live log in the active panel  /  same as /session"),
    ("F3",               "Open the multi-line compose modal (paste/edit large prompts)"),
    ("Esc",              "Close help/palette  /  Clear draft  /  Cancel in-flight turn"),
    ("Ctrl+N",           "Open NotesPad scratchpad  /  Ctrl+S inside saves to ~/.lilbro-local/notes.md"),
    ("Ctrl+P",           "Quick project switcher -- jump to a recent project directory"),
    ("Ctrl+Q",           "Quit THE BROS  (Ctrl+C is now 'port', not quit)"),
    ("Enter",            "Send the current input to the active agent"),
    ("Up (in input)",    "Recall previous command from history"),
    ("Down (in input)",  "Walk forward through history (restores unsent draft at end)"),
]

# COMMANDS is imported from src_local.ui.commands_meta -- single source of truth
# shared with the inline command palette.

AGENT_ROLES = [
    ("Big Bro (Coder)",      "#E8A838",     "Writes and edits code. Full workspace access."),
    ("Lil Bro (Helper)",     "#A8D840",     "Read-only helper for debugging, explaining, and reviewing."),
]


# -----------------------------------------------------------------------------
# Helpers to format tables with aligned columns
# -----------------------------------------------------------------------------

def _fmt_hotkey_table() -> Text:
    """Two-column hotkey table: KEY | description."""
    key_width = max(len(k) for k, _ in HOTKEYS) + 2
    t = Text()
    for key, desc in HOTKEYS:
        t.append(key.ljust(key_width), style="bold #E8A838")
        t.append("  ")
        t.append(desc, style="#E8E8E8")
        t.append("\n")
    return t


def _fmt_command_table() -> Text:
    """Three-column command table: /cmd | target | description."""
    cmd_width = max(len(c) for c, _, _ in COMMANDS) + 2
    tgt_width = max(len(t) for _, t, _ in COMMANDS) + 2
    t = Text()
    for cmd, target, desc in COMMANDS:
        t.append(cmd.ljust(cmd_width), style="bold #A8D840")
        color = "#E8A838" if "Big Bro" in target else "#A8D840" if "Lil Bro" in target else "#666666"
        t.append(target.ljust(tgt_width), style=color)
        t.append("  ")
        t.append(desc, style="#E8E8E8")
        t.append("\n")
    return t


def _fmt_roles_table() -> Text:
    t = Text()
    for name, color, desc in AGENT_ROLES:
        t.append(f"  {name}", style=f"bold {color}")
        t.append("\n    ")
        t.append(desc, style="#CCCCCC")
        t.append("\n")
    return t


# -----------------------------------------------------------------------------
# Modal screen
# -----------------------------------------------------------------------------

class HelpScreen(ModalScreen):
    """Floating help modal. Pops over the dual-pane screen."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-container {
        width: 90;
        height: 85%;
        border: round #3A3A3A;
        padding: 1 2;
        background: #1A1A1A;
    }
    #help-title {
        width: 100%;
        content-align: center middle;
        color: #A8D840;
        text-style: bold;
        margin-bottom: 0;
    }
    #help-subtitle {
        width: 100%;
        content-align: center middle;
        color: #888888;
        margin-bottom: 1;
    }
    .help-section-header {
        color: #E8A838;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
    }
    .help-table {
        margin-bottom: 1;
        padding: 0 1;
    }
    #help-footer {
        width: 100%;
        content-align: center middle;
        color: #888888;
        dock: bottom;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("f1", "close", "Close"),
        Binding("ctrl+h", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="help-container"):
            yield Static("THE BROS -- HELP", id="help-title")
            yield Static("local-model coding TUI -- powered by Ollama", id="help-subtitle")
            with VerticalScroll():
                yield Static("AGENTS", classes="help-section-header")
                yield Static(_fmt_roles_table(), classes="help-table")
                yield Static("KEYBOARD SHORTCUTS", classes="help-section-header")
                yield Static(_fmt_hotkey_table(), classes="help-table")
                yield Static("SLASH COMMANDS", classes="help-section-header")
                yield Static(_fmt_command_table(), classes="help-table")
            yield Static("[Esc / F1 / Q to close]", id="help-footer")

    def action_close(self) -> None:
        self.app.pop_screen()
