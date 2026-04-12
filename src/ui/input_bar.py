"""Input bar for LIL BRO LOCAL.

Shows which agent is the active target (prefix label) and dispatches
submitted text to the router.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

if TYPE_CHECKING:
    from src.router import Router


PLACEHOLDER_HINTS = [
    "Type a message  ·  Tab switch panes  ·  /help for commands  ·  Ctrl+Q quit",
    "Try: explain how decorators work",
    "Try: write a function that validates email addresses",
    "Try: /model to switch models  ·  /clear to reset",
]


class InputBar(Vertical):
    """Bottom input area: prefix + input field."""

    def __init__(self, router: "Router", **kwargs) -> None:
        super().__init__(**kwargs)
        self._router = router
        self._hint_index = 0

    def compose(self) -> ComposeResult:
        with Horizontal(id="input-row"):
            yield Static("[BRO A ▶]", id="input-prefix")
            yield Input(
                placeholder=PLACEHOLDER_HINTS[0],
                id="user-input",
            )

    def on_mount(self) -> None:
        self._router.bind_input_bar(self)
        self.refresh_prefix()

    def refresh_prefix(self) -> None:
        prefix = self.query_one("#input-prefix", Static)
        if self._router.active_target == "a":
            prefix.update("[BRO A ▶]")
        else:
            prefix.update("[▶ BRO B]")

    def focus_input(self) -> None:
        try:
            self.query_one("#user-input", Input).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        # Cycle placeholder hints.
        self._hint_index = (self._hint_index + 1) % len(PLACEHOLDER_HINTS)
        event.input.placeholder = PLACEHOLDER_HINTS[self._hint_index]

        # Route through the router (async).
        self.app.call_later(self._route, text)

    async def _route(self, text: str) -> None:
        await self._router.route_user_input(text)

    def set_draft(self, text: str) -> None:
        """Pre-fill the input with text (for cross-talk ports)."""
        inp = self.query_one("#user-input", Input)
        inp.value = text[:6000]
        inp.focus()
