"""Settings modal -- /settings or (future) Ctrl+, opens this.

A tabbed overview of every knob the user might want to tweak without
editing ~/.lilbro-local/config.yaml by hand. Four tabs:

    MODELS   -- current models for Big Bro / Lil Bro, quick switch field
    THEME    -- live color values from Config.colors
    LOGS     -- tail of ~/.lilbro-local/debug.log (read-only viewer)
    CONFIG   -- raw ~/.lilbro-local/config.yaml dumped for copy/paste reference

The modal is read-mostly: the only write path is the two "apply" buttons
on the MODELS tab, which hand the new model name back via ``dismiss()``
as a tuple ``(target, model_name)``. The caller (router / app.py) then
funnels that through the existing ``/model`` handler so all the
restart + journal-note plumbing is shared.

Everything else is a scrollable static view. Users who want to edit
config.yaml get the full path printed at the top of the CONFIG tab and
are expected to open it in their editor of choice -- we deliberately do
NOT ship an in-TUI yaml editor because the blast radius of a typo there
is "app won't start".
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static, TabbedContent, TabPane

if TYPE_CHECKING:
    from src_local.config import Config


_DEBUG_LOG = Path.home() / ".lilbro-local" / "debug.log"
_CONFIG_YAML = Path.home() / ".lilbro-local" / "config.yaml"
_LOG_TAIL_LINES = 200


def _tail(path: Path, n: int) -> str:
    """Return the last ``n`` lines of ``path`` as a single string, or a
    friendly placeholder if the file is missing / unreadable."""
    try:
        if not path.exists():
            return f"(no log yet -- {path} does not exist)"
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        tail = lines[-n:] if len(lines) > n else lines
        return "".join(tail) or "(log file is empty)"
    except OSError as exc:
        return f"(could not read {path}: {exc})"


def _describe_model(agent) -> str:
    """Best-effort model string for an agent (configured vs live)."""
    if agent is None:
        return "(unavailable)"
    configured = getattr(agent, "_configured_model", None)
    live = getattr(agent, "_model", None)
    if configured and live and configured != live:
        return f"{live}  (requested: {configured})"
    return str(configured or live or "(default)")


class SettingsScreen(ModalScreen):
    """Modal with a tabbed settings dashboard.

    Dismisses with one of:
      - ``None``                       user hit Esc / close
      - ``("big", "<model>")``          apply new Big Bro model
      - ``("lil", "<model>")``          apply new Lil Bro model
    """

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
    ]

    DEFAULT_CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-container {
        width: 96;
        height: 36;
        border: round #E8A838;
        background: #1A1A1A;
        padding: 0 1;
    }

    #settings-title {
        width: 100%;
        content-align: center middle;
        color: #E8A838;
        text-style: bold;
        height: 1;
        border-bottom: solid #333333;
    }

    #settings-footer {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: #666666;
        border-top: solid #333333;
    }

    SettingsScreen TabbedContent {
        height: 1fr;
        margin: 1 0;
    }

    SettingsScreen TabPane {
        padding: 0 1;
    }

    SettingsScreen VerticalScroll {
        height: 1fr;
    }

    SettingsScreen .settings-section {
        color: #A8D840;
        text-style: bold;
        padding: 1 0 0 0;
    }

    SettingsScreen .settings-kv {
        color: #E8E8E8;
        padding: 0 0 0 2;
    }

    SettingsScreen .settings-hint {
        color: #666666;
        padding: 0 0 0 2;
    }

    SettingsScreen #settings-log,
    SettingsScreen #settings-yaml {
        background: #111111;
        color: #CCCCCC;
        padding: 1;
        border: solid #333333;
    }

    SettingsScreen .apply-row {
        height: 3;
        padding: 1 0 0 0;
    }

    SettingsScreen Input {
        width: 40;
        margin: 0 1 0 0;
    }

    SettingsScreen Button {
        min-width: 14;
        margin: 0 1 0 0;
    }

    SettingsScreen Button.bro-a {
        background: #2A3518;
        color: #A8D840;
    }

    SettingsScreen Button.bro-b {
        background: #3D2E12;
        color: #E8A838;
    }
    """

    def __init__(
        self,
        config: "Config",
        big_bro_agent=None,
        lil_bro_agent=None,
    ) -> None:
        super().__init__()
        self._config = config
        self._big_bro = big_bro_agent
        self._lil_bro = lil_bro_agent

    # -----------------------------------------------------------------
    # Compose
    # -----------------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Container(id="settings-container"):
            yield Static("-- SETTINGS --", id="settings-title")
            with TabbedContent(initial="tab-models"):
                with TabPane("Models", id="tab-models"):
                    yield from self._compose_models_tab()
                with TabPane("Theme", id="tab-theme"):
                    yield from self._compose_theme_tab()
                with TabPane("Logs", id="tab-logs"):
                    yield from self._compose_logs_tab()
                with TabPane("Config", id="tab-config"):
                    yield from self._compose_config_tab()
            yield Static(
                "Esc close  /  switch tabs with Left / Right  /  Enter in a field applies",
                id="settings-footer",
            )

    # -----------------------------------------------------------------
    # Tabs
    # -----------------------------------------------------------------

    def _compose_models_tab(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("current models", classes="settings-section")
            yield Static(
                f"Big Bro:  {_describe_model(self._big_bro)}",
                classes="settings-kv",
            )
            yield Static(
                f"Lil Bro:  {_describe_model(self._lil_bro)}",
                classes="settings-kv",
            )
            yield Static("change model", classes="settings-section")
            yield Static(
                "Typing a new model name and pressing the apply button "
                "will restart that agent (conversation history will be "
                "cleared).",
                classes="settings-hint",
            )
            with Horizontal(classes="apply-row"):
                yield Input(
                    placeholder="e.g. llama3",
                    id="settings-a-input",
                )
                yield Button(
                    "Apply -> Big Bro", id="settings-apply-a", classes="bro-a"
                )
            with Horizontal(classes="apply-row"):
                yield Input(
                    placeholder="e.g. codellama",
                    id="settings-b-input",
                )
                yield Button(
                    "Apply -> Lil Bro", id="settings-apply-b", classes="bro-b"
                )

    def _compose_theme_tab(self) -> ComposeResult:
        c = self._config.colors
        with VerticalScroll():
            yield Static("palette", classes="settings-section")
            for label, value in [
                ("bro a      ", c.primary),
                ("bro b      ", c.secondary),
                ("user       ", c.user),
                ("bro a dim  ", c.primary_dim),
                ("bro b dim  ", c.secondary_dim),
                ("background ", c.bg),
                ("border     ", c.border),
            ]:
                line = Text()
                line.append(f"{label}", style="#888888")
                line.append("  ")
                line.append("####  ", style=value)
                line.append(value, style=value)
                yield Static(line, classes="settings-kv")
            yield Static(
                "Colors are loaded from ui.colors.* in ~/.lilbro-local/config.yaml "
                "(or the project config.yaml). Change them there and restart.",
                classes="settings-hint",
            )

    def _compose_logs_tab(self) -> ComposeResult:
        body = _tail(_DEBUG_LOG, _LOG_TAIL_LINES)
        with VerticalScroll():
            yield Static(
                f"last {_LOG_TAIL_LINES} lines of {_DEBUG_LOG}",
                classes="settings-section",
            )
            yield Static(body, id="settings-log")

    def _compose_config_tab(self) -> ComposeResult:
        yaml_body: str
        if _CONFIG_YAML.exists():
            try:
                yaml_body = _CONFIG_YAML.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                yaml_body = f"(could not read {_CONFIG_YAML}: {exc})"
        else:
            yaml_body = (
                f"(no user config at {_CONFIG_YAML} -- running with defaults)\n\n"
                "Create that file to override any of:\n"
                "  big_bro:\n"
                "    model: llama3\n"
                "  lil_bro:\n"
                "    model: codellama\n"
                "  ui:\n"
                "    colors: { bro: '#A8D840', cheese: '#E8A838', ... }\n"
                "  journal:\n"
                "    auto_save: true\n"
                "    keep: 100\n"
                "  keybindings: { help: 'f1', ... }\n"
            )
        with VerticalScroll():
            yield Static(
                f"{_CONFIG_YAML}",
                classes="settings-section",
            )
            yield Static(yaml_body, id="settings-yaml")
            yield Static(
                "THE BROS reads this file once at startup -- restart the app "
                "after editing.",
                classes="settings-hint",
            )

    # -----------------------------------------------------------------
    # Actions
    # -----------------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "settings-apply-a":
            self._apply_big_bro()
        elif event.button.id == "settings-apply-b":
            self._apply_lil_bro()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "settings-a-input":
            self._apply_big_bro()
        elif event.input.id == "settings-b-input":
            self._apply_lil_bro()

    def _apply_big_bro(self) -> None:
        value = self.query_one("#settings-a-input", Input).value.strip()
        if not value:
            return
        self.dismiss(("big", value))

    def _apply_lil_bro(self) -> None:
        value = self.query_one("#settings-b-input", Input).value.strip()
        if not value:
            return
        self.dismiss(("lil", value))
