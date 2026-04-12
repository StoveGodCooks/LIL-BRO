"""TeachScratchScreen -- modal code editor for submitting quest answers.

Opened by ``ChallengeManager.open_scratch`` (or the ``/submit`` pathway)
when the user wants a full multi-line editor to type their solution.
Mirrors ``NotesScreen``: a floating ``TextArea`` with Ctrl+S to commit
and Esc to cancel.

Contract
--------
* ``dismiss(text)`` on Ctrl+S -> caller treats *text* as the submission.
* ``dismiss(None)``          on Esc       -> caller treats as cancel.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static, TextArea


class TeachScratchScreen(ModalScreen[str | None]):
    """Floating scratch editor for quest submissions."""

    BINDINGS = [
        Binding("escape",  "cancel", "Cancel", priority=True),
        Binding("ctrl+s",  "submit", "Submit", priority=True),
    ]

    DEFAULT_CSS = """
    TeachScratchScreen {
        align: center middle;
    }

    #scratch-container {
        width: 90;
        height: 26;
        max-height: 90%;
        border: round #A8D840;
        background: #1A1A1A;
        padding: 0 1;
    }

    #scratch-title {
        width: 100%;
        content-align: center middle;
        color: #A8D840;
        text-style: bold;
        padding: 0 1;
        border-bottom: solid #333333;
        height: 1;
    }

    #scratch-task {
        width: 100%;
        height: auto;
        max-height: 5;
        color: #B8B8B8;
        padding: 0 1;
    }

    #scratch-area {
        width: 100%;
        height: 1fr;
        background: #0E0E0E;
        color: #E8E8E8;
        border: round #3A3A3A;
        margin: 1 0 0 0;
    }

    #scratch-area:focus {
        border: round #A8D840;
    }

    #scratch-footer {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: #666666;
        border-top: solid #333333;
    }
    """

    def __init__(
        self,
        *,
        title: str = "TEACH SCRATCH",
        task: str = "",
        initial_text: str = "",
    ) -> None:
        super().__init__()
        self._title = title
        self._task = task
        self._initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Container(id="scratch-container"):
            yield Static(f"-- {self._title} --", id="scratch-title")
            if self._task:
                yield Static(self._task.strip(), id="scratch-task")
            yield TextArea(self._initial_text, id="scratch-area", language=None)
            yield Static(
                "Ctrl+S submit / Esc cancel",
                id="scratch-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#scratch-area", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        text = self.query_one("#scratch-area", TextArea).text
        self.dismiss(text)
