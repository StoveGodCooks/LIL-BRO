"""Help modal -- lists every slash command and keyboard shortcut.

Pushed on F1 / Ctrl+H / `/help`. Dismiss with Esc / F1 / Q.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
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
    ("Ctrl+Shift+V",     "Paste clipboard screenshot -- auto-saves to ~/.lilbro-local/tmp/ and attaches path"),
    ("Esc",              "Close help/palette  /  Clear draft  /  Cancel in-flight turn"),
    ("Ctrl+N",           "Open NotesPad scratchpad  /  Ctrl+S inside saves to ~/.lilbro-local/notes.md"),
    ("Ctrl+P",           "Quick project switcher -- jump to a recent project directory"),
    ("Ctrl+Q",           "Quit THE BROS  (Ctrl+C is now 'port', not quit)"),
    ("Enter",            "Send the current input to the active agent"),
    ("Up (in input)",    "Recall previous command from history"),
    ("Down (in input)",  "Walk forward through history (restores unsent draft at end)"),
]

AGENT_ROLES = [
    ("Big Bro (Coder)",      "#E8A838",     "Writes and edits code. Full workspace access."),
    ("Lil Bro (Helper)",     "#A8D840",     "Read-only helper for debugging, explaining, and reviewing."),
]

# Fixed column widths (chars). Description gets the rest via 1fr.
_CMD_W = max(len(c) for c, _, _ in COMMANDS) + 1   # e.g. 21
_TGT_W = max(len(t) for _, t, _ in COMMANDS) + 2   # e.g. 12
_KEY_W = max(len(k) for k, _ in HOTKEYS) + 2        # e.g. 18


def _tgt_color(target: str) -> str:
    if "Big Bro" in target:
        return "#E8A838"
    if "Lil Bro" in target:
        return "#A8D840"
    return "#666666"


# -----------------------------------------------------------------------------
# Modal screen
# -----------------------------------------------------------------------------

class HelpScreen(ModalScreen):
    """Floating help modal. Pops over the dual-pane screen."""

    DEFAULT_CSS = f"""
    HelpScreen {{
        align: center middle;
    }}
    #help-container {{
        width: 90;
        height: 85%;
        border: round #3A3A3A;
        padding: 1 2;
        background: #1A1A1A;
    }}
    #help-title {{
        width: 100%;
        content-align: center middle;
        color: #A8D840;
        text-style: bold;
        margin-bottom: 0;
    }}
    #help-subtitle {{
        width: 100%;
        content-align: center middle;
        color: #888888;
        margin-bottom: 1;
    }}
    .help-section-header {{
        color: #E8A838;
        text-style: bold;
        margin-top: 1;
        margin-bottom: 0;
        padding-left: 1;
    }}
    /* ── row layout ─────────────────────────────── */
    .help-row {{
        height: auto;
        padding: 0 1;
    }}
    .help-cmd {{
        width: {_CMD_W};
        color: #A8D840;
        text-style: bold;
    }}
    .help-tgt {{
        width: {_TGT_W};
    }}
    .help-desc {{
        width: 1fr;
        color: #E8E8E8;
    }}
    .help-key {{
        width: {_KEY_W};
        color: #E8A838;
        text-style: bold;
    }}
    /* ── role block ─────────────────────────────── */
    .role-row {{
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }}
    .role-name {{
        width: 22;
        text-style: bold;
    }}
    .role-desc {{
        width: 1fr;
        color: #CCCCCC;
    }}
    #help-footer {{
        width: 100%;
        content-align: center middle;
        color: #888888;
        dock: bottom;
    }}
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
            yield Static(
                "model-agnostic coding TUI -- Ollama / Claude / Codex",
                id="help-subtitle",
            )
            with VerticalScroll():
                yield Static("AGENTS", classes="help-section-header")
                for name, color, desc in AGENT_ROLES:
                    name_widget = Static(name, markup=False,
                                         classes="role-name")
                    name_widget.styles.color = color
                    with Horizontal(classes="role-row"):
                        yield name_widget
                        yield Static(desc, classes="role-desc",
                                     markup=False)

                yield Static("KEYBOARD SHORTCUTS", classes="help-section-header")
                for key, desc in HOTKEYS:
                    with Horizontal(classes="help-row"):
                        yield Static(key, classes="help-key", markup=False)
                        yield Static(desc, classes="help-desc", markup=False)

                yield Static("SLASH COMMANDS", classes="help-section-header")
                for cmd, target, desc in COMMANDS:
                    tgt_widget = Static(target, markup=False,
                                        classes="help-tgt")
                    tgt_widget.styles.color = _tgt_color(target)
                    with Horizontal(classes="help-row"):
                        yield Static(cmd, classes="help-cmd", markup=False)
                        yield tgt_widget
                        yield Static(desc, classes="help-desc", markup=False)

            yield Static("[Esc / F1 / Q to close]", id="help-footer")

    def action_close(self) -> None:
        self.app.pop_screen()
