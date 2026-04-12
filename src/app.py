"""LIL BRO LOCAL — main Textual App.

A dual-pane TUI powered by local Ollama models. No API keys, no cloud,
no subscriptions. Just you and your local models.

Usage:
    lilbro-local                          # defaults
    lilbro-local --model qwen2.5-coder:3b # override model
    lilbro-local --url http://host:11434  # custom Ollama URL
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen

from src.agents.ollama_agent import (
    OllamaAgent,
    CODER_SYSTEM_PROMPT,
    HELPER_SYSTEM_PROMPT,
)
from src.commands.handler import CommandHandler
from src.config import load_config
from src.journal.recorder import JournalRecorder
from src.router import Router
from src.ui.input_bar import InputBar
from src.ui.panels import BroAPanel, BroBPanel
from src.ui.startup import StartupScreen
from src.ui.status_bar import StatusBar


logger = logging.getLogger("lilbro-local")


CSS_PATH = Path(__file__).parent / "ui" / "app.tcss"


class DualPaneScreen(Screen):
    """Main screen with two local-model panes side by side."""

    BINDINGS = [
        Binding("tab", "switch_target", "Switch pane", show=False),
        Binding("escape", "cancel_turn", "Cancel", show=False),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
        Binding("ctrl+r", "retry", "Retry", show=False),
        Binding("ctrl+c", "port_from_a", "Port A→B", show=False),
        Binding("ctrl+b", "port_from_b", "Port B→A", show=False),
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
        # Start both agents.
        try:
            await self._bro_a_agent.start()
        except Exception as exc:
            self._router.bro_a_panel.append_error(f"Bro A failed to start: {exc}")

        try:
            await self._bro_b_agent.start()
        except Exception as exc:
            self._router.bro_b_panel.append_error(f"Bro B failed to start: {exc}")

        # Welcome messages.
        self._router.bro_a_panel.append_system(
            f"Bro A ready — model: {self._bro_a_agent.model} (coder)"
        )
        self._router.bro_b_panel.append_system(
            f"Bro B ready — model: {self._bro_b_agent.model} (helper)"
        )
        self._router.bro_a_panel.append_system(
            "Tab to switch panes · /help for commands · Ctrl+Q to quit"
        )

        # Focus the input.
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
    CSS_PATH = None  # We load CSS manually.

    def __init__(
        self,
        model: str | None = None,
        ollama_url: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model_override = model
        self._url_override = ollama_url

    def on_mount(self) -> None:
        # Load CSS from file.
        try:
            css_text = CSS_PATH.read_text(encoding="utf-8")
            self.stylesheet.parse(css_text, path=str(CSS_PATH))
        except Exception as exc:
            logger.warning("Failed to load CSS: %s", exc)

        config = load_config()

        model = self._model_override or config.ollama.model
        base_url = self._url_override or config.ollama.base_url

        # Create agents.
        bro_a = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Bro A",
            system_prompt=CODER_SYSTEM_PROMPT,
            temperature=config.ollama.temperature,
            context_window=config.ollama.context_window,
        )

        bro_b = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Bro B",
            system_prompt=HELPER_SYSTEM_PROMPT,
            temperature=config.ollama.temperature,
            context_window=config.ollama.context_window,
        )

        # Create UI components.
        bro_a_panel = BroAPanel()
        bro_b_panel = BroBPanel()
        status_bar = StatusBar()
        status_bar.set_model(model)
        status_bar.attach_agents(bro_a, bro_b)

        journal = JournalRecorder(
            journal_dir=config.journal_dir,
            auto_save=config.journal_auto_save,
        )

        commands = CommandHandler(config, bro_a=bro_a, bro_b=bro_b)

        router = Router(
            bro_a_panel=bro_a_panel,
            bro_b_panel=bro_b_panel,
            bro_a_agent=bro_a,
            bro_b_agent=bro_b,
            commands=commands,
            journal=journal,
            status_bar=status_bar,
        )

        # Push startup check, then main screen.
        main_screen = DualPaneScreen(
            router=router,
            bro_a_agent=bro_a,
            bro_b_agent=bro_b,
            status_bar=status_bar,
        )

        self.push_screen(main_screen)
        self.push_screen(StartupScreen(ollama_url=base_url))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LIL BRO LOCAL — dual-pane local model TUI"
    )
    parser.add_argument(
        "--model", "-m",
        help="Ollama model tag (e.g. qwen2.5-coder:7b)",
    )
    parser.add_argument(
        "--url", "-u",
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    args = parser.parse_args()

    app = LilBroLocalApp(model=args.model, ollama_url=args.url)
    app.run()


if __name__ == "__main__":
    main()
