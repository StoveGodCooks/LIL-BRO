"""LIL BRO LOCAL — main Textual App.

A dual-pane TUI powered by local Ollama models. No API keys, no cloud,
no subscriptions. Just you and your local models.

First-run flow:
  1. Detect hardware (GPU, VRAM, RAM)
  2. Check if Ollama is installed + running
  3. If not → guide through install (opens browser to ollama.com)
  4. Show model picker with 3B / 7B / 14B quick-pull buttons
  5. Pull selected model with progress bar
  6. Launch dual-pane screen

Usage:
    lilbro-local                          # first-run wizard
    lilbro-local --model qwen2.5-coder:3b # skip wizard, use this model
    lilbro-local --url http://host:11434  # custom Ollama URL
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen

from src_local.agents.ollama_agent import (
    OllamaAgent,
    CODER_SYSTEM_PROMPT,
    HELPER_SYSTEM_PROMPT,
)
from src_local.commands.handler import CommandHandler
from src_local.config import load_config
from src_local.journal.recorder import JournalRecorder
from src_local.router import Router
from src_local.ui.first_run import FirstRunScreen
from src_local.ui.input_bar import InputBar
from src_local.ui.panels import BroAPanel, BroBPanel
from src_local.ui.status_bar import StatusBar


logger = logging.getLogger("lilbro-local")

CSS_PATH = Path(__file__).parent / "ui" / "app.tcss"

# State file — remembers the model the user picked so we don't show
# the wizard on every launch.
STATE_FILE = Path.home() / ".lilbro-local" / "state.json"


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


class DualPaneScreen(Screen):
    """Main screen with two local-model panes side by side."""

    BINDINGS = [
        Binding("tab", "switch_target", "Switch pane", show=False),
        Binding("escape", "cancel_turn", "Cancel", show=False),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
        Binding("ctrl+r", "retry", "Retry", show=False),
        Binding("ctrl+c", "port_from_a", "Port A->B", show=False),
        Binding("ctrl+b", "port_from_b", "Port B->A", show=False),
    ]

    def __init__(
        self,
        router: Router,
        bro_a_agent: OllamaAgent,
        bro_b_agent: OllamaAgent,
        status_bar: StatusBar,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._router = router
        self._bro_a_agent = bro_a_agent
        self._bro_b_agent = bro_b_agent
        self._status_bar = status_bar

    def compose(self) -> ComposeResult:
        with Container(id="main-container"):
            yield self._router.bro_a_panel
            yield self._router.bro_b_panel
        yield self._status_bar
        yield InputBar(self._router, id="input-bar")

    async def on_mount(self) -> None:
        try:
            await self._bro_a_agent.start()
        except Exception as exc:
            self._router.bro_a_panel.append_error(f"Bro A failed to start: {exc}")

        try:
            await self._bro_b_agent.start()
        except Exception as exc:
            self._router.bro_b_panel.append_error(f"Bro B failed to start: {exc}")

        self._router.bro_a_panel.append_system(
            f"Bro A ready -- model: {self._bro_a_agent.model} (coder)"
        )
        self._router.bro_b_panel.append_system(
            f"Bro B ready -- model: {self._bro_b_agent.model} (helper)"
        )
        self._router.bro_a_panel.append_system(
            "Tab to switch panes - /help for commands - Ctrl+Q to quit"
        )

        try:
            self.query_one("#user-input").focus()
        except Exception:
            pass

    async def on_unmount(self) -> None:
        try:
            await self._bro_a_agent.stop()
        except Exception:
            pass
        try:
            await self._bro_b_agent.stop()
        except Exception:
            pass

    def action_switch_target(self) -> None:
        self._router.switch_target()

    def action_cancel_turn(self) -> None:
        cancelled = self._router.cancel_current_turn()
        if not cancelled:
            panel = self._router._panel_for(self._router.active_target)
            panel.append_system("(nothing to cancel)")

    def action_quit_app(self) -> None:
        self.app.exit()

    async def action_retry(self) -> None:
        retried = await self._router.retry_last_prompt()
        if not retried:
            panel = self._router._panel_for(self._router.active_target)
            panel.append_system("(nothing to retry)")

    def action_port_from_a(self) -> None:
        self._router.port_cross_talk("a")

    def action_port_from_b(self) -> None:
        self._router.port_cross_talk("b")


class LilBroLocalApp(App):
    """LIL BRO LOCAL — dual-pane local model TUI."""

    TITLE = "LIL BRO LOCAL"
    CSS_PATH = None

    def __init__(
        self,
        model: str | None = None,
        ollama_url: str | None = None,
        skip_wizard: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model_override = model
        self._url_override = ollama_url
        self._skip_wizard = skip_wizard
        self._selected_model: str | None = None  # Set by first-run wizard.
        self._config = load_config()

    def on_mount(self) -> None:
        # Load CSS.
        try:
            css_text = CSS_PATH.read_text(encoding="utf-8")
            self.stylesheet.parse(css_text, path=str(CSS_PATH))
        except Exception as exc:
            logger.warning("Failed to load CSS: %s", exc)

        base_url = self._url_override or self._config.ollama.base_url

        # Decide whether to show the first-run wizard.
        state = _load_state()
        has_model = self._model_override or state.get("active_model")

        if has_model or self._skip_wizard:
            # Skip wizard — go straight to dual-pane.
            model = self._model_override or state.get("active_model", self._config.ollama.model)
            self._open_dual_pane(model, base_url)
        else:
            # First run — show the wizard, then open dual-pane when it closes.
            wizard = FirstRunScreen(ollama_url=base_url)
            self.push_screen(wizard, callback=self._on_wizard_done)

    def _on_wizard_done(self, _result=None) -> None:
        """Called when the first-run wizard screen is dismissed."""
        base_url = self._url_override or self._config.ollama.base_url
        model = self._selected_model or self._config.ollama.model

        # Save the selected model so we skip the wizard next time.
        state = _load_state()
        state["active_model"] = model
        _save_state(state)

        self._open_dual_pane(model, base_url)

    def _open_dual_pane(self, model: str, base_url: str) -> None:
        """Construct and push the main dual-pane screen."""
        bro_a = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Bro A",
            system_prompt=CODER_SYSTEM_PROMPT,
            temperature=self._config.ollama.temperature,
            context_window=self._config.ollama.context_window,
        )

        bro_b = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Bro B",
            system_prompt=HELPER_SYSTEM_PROMPT,
            temperature=self._config.ollama.temperature,
            context_window=self._config.ollama.context_window,
        )

        bro_a_panel = BroAPanel()
        bro_b_panel = BroBPanel()
        status_bar = StatusBar()
        status_bar.set_model(model)
        status_bar.attach_agents(bro_a, bro_b)

        journal = JournalRecorder(
            journal_dir=self._config.journal_dir,
            auto_save=self._config.journal_auto_save,
        )

        commands = CommandHandler(self._config, bro_a=bro_a, bro_b=bro_b)

        router = Router(
            bro_a_panel=bro_a_panel,
            bro_b_panel=bro_b_panel,
            bro_a_agent=bro_a,
            bro_b_agent=bro_b,
            commands=commands,
            journal=journal,
            status_bar=status_bar,
        )

        main_screen = DualPaneScreen(
            router=router,
            bro_a_agent=bro_a,
            bro_b_agent=bro_b,
            status_bar=status_bar,
        )

        self.push_screen(main_screen)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LIL BRO LOCAL -- dual-pane local model TUI"
    )
    parser.add_argument(
        "--model", "-m",
        help="Ollama model tag (e.g. qwen2.5-coder:7b). Skips the first-run wizard.",
    )
    parser.add_argument(
        "--url", "-u",
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--wizard", action="store_true",
        help="Force the first-run wizard even if a model is already configured.",
    )
    args = parser.parse_args()

    # If --wizard is passed, clear the saved state so the wizard shows.
    if args.wizard:
        try:
            STATE_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    app = LilBroLocalApp(
        model=args.model,
        ollama_url=args.url,
        skip_wizard=bool(args.model),
    )
    app.run()


if __name__ == "__main__":
    main()
