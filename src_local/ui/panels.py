"""Dual pane widgets for LIL BRO LOCAL.

Two local-model panes side by side:
- Bro A (left, lime) — coder role
- Bro B (right, blue) — helper/explainer role

Both talk to local Ollama models. Either can be the "active" pane
that receives user input.
"""

from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.widgets import RichLog, Static


class _BasePanel(Container):
    """Shared panel behavior."""

    active: reactive[bool] = reactive(False)

    DISPLAY_NAME = "Agent"
    BORDER_COLOR = "#A8D840"
    BORDER_DIM = "#2A3518"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stream_buffer: list[str] = []
        self._last_assistant_message: str = ""

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"── {self.DISPLAY_NAME} ──", id="panel-header")
            yield RichLog(highlight=True, markup=True, wrap=True, id="log")
            yield Static("", id="stream-preview")

    def watch_active(self, value: bool) -> None:
        self.set_class(value, "active-panel")
        self.set_class(not value, "inactive-panel")

    @property
    def last_assistant_message(self) -> str:
        return self._last_assistant_message

    def _log_widget(self) -> RichLog:
        return self.query_one("#log", RichLog)

    def _preview_widget(self) -> Static:
        return self.query_one("#stream-preview", Static)

    def append_user_message(self, text: str) -> None:
        log = self._log_widget()
        stamp = datetime.now().strftime("%H:%M")
        styled = Text()
        styled.append(f"[{stamp}] ", style="dim")
        styled.append("You: ", style="bold #E8E8E8")
        styled.append(text)
        log.write(styled)

    def append_system(self, text: str) -> None:
        log = self._log_widget()
        styled = Text(text, style="dim italic #888888")
        log.write(styled)

    def append_error(self, text: str) -> None:
        log = self._log_widget()
        styled = Text(f"ERROR: {text}", style="bold red")
        log.write(styled)

    def start_agent_stream(self) -> None:
        """Called when an agent starts streaming a response."""
        self._stream_buffer = []
        self._preview_widget().update("")

    def append_agent_chunk(self, chunk: str) -> None:
        """Append a streaming text chunk from the agent."""
        self._stream_buffer.append(chunk)
        text = "".join(self._stream_buffer)

        # Flush completed lines to the log, keep partial in preview.
        lines = text.split("\n")
        if len(lines) > 1:
            log = self._log_widget()
            for line in lines[:-1]:
                if line:
                    styled = Text(line)
                    log.write(styled)
            self._stream_buffer = [lines[-1]]

        # Show the trailing partial in the preview.
        partial = "".join(self._stream_buffer)
        if partial:
            try:
                self._preview_widget().update(Text(partial))
            except Exception:
                pass

    def mark_assistant_complete(self) -> None:
        """Flush any remaining buffer and finalize the response."""
        remaining = "".join(self._stream_buffer)
        if remaining.strip():
            log = self._log_widget()
            log.write(Text(remaining))

        self._last_assistant_message = remaining
        # Reconstruct the full message from the log isn't feasible, but
        # we at least capture the final buffer. For cross-talk ports the
        # user can Ctrl+C/B the last visible chunk.
        self._stream_buffer = []
        try:
            self._preview_widget().update("")
        except Exception:
            pass

        # Separator between turns.
        log = self._log_widget()
        log.write(Text("─" * 40, style="dim #333333"))

    def clear_log(self) -> None:
        self._log_widget().clear()


class BroAPanel(_BasePanel):
    """Left pane — coder role (lime green)."""
    DISPLAY_NAME = "BRO A"
    BORDER_COLOR = "#A8D840"
    BORDER_DIM = "#2A3518"


class BroBPanel(_BasePanel):
    """Right pane — helper role (sky blue)."""
    DISPLAY_NAME = "BRO B"
    BORDER_COLOR = "#6EC8E8"
    BORDER_DIM = "#1A2E38"
