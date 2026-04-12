"""Dual pane widgets for LIL BRO LOCAL.

Two local-model panes side by side:
- Lil Bro (left, green #A8D840) -- helper/explainer role
- Big Bro (right, orange #E8A838) -- coder role

Both talk to local Ollama models. Either can be the "active" pane
that receives user input.

Each panel has three vertically stacked regions:

  +-- Header (sticky, 1 line) ---------+
  | -- BRO A --                        |
  +------------------------------------+
  | RichLog (scrollable, completed)    |
  | ...                                |
  +------------------------------------+
  | Stream preview (partial line)      |
  +------------------------------------+

**Streaming contract**

Agent chunks arrive as arbitrarily-sized text deltas. We buffer them
and only flush completed lines to the `RichLog`. The still-pending tail
lives in the streaming preview so the user sees it grow in real time
without every delta becoming its own log line.

When the turn ends, `mark_assistant_complete()` flushes the remaining
buffer into the log and clears the preview.

**File-path highlighting**

Any file path mentioned anywhere in user input, agent output, or tool
badges is rendered in purple (`#C878E8`) so the user can spot exactly
what files the agents are working on at a glance.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import RichLog, Static

from src_local.ui.pacman import PacManTrack

if TYPE_CHECKING:
    from src_local.journal.recorder import JournalRecorder


_SPINNER_FRAMES = "\u280B\u2819\u2839\u2838\u283C\u2834\u2826\u2827\u2807\u280F"

# Purple used throughout the UI for anything file-related.
FILE_PURPLE = "#C878E8"

# Regex that matches reasonably file-path-shaped tokens in flowing text.
FILE_PATH_RE = re.compile(
    r"""
    (?<![A-Za-z0-9_.@/])         # left boundary: nothing filename-y before
    (?:
        [A-Za-z]:[\\/]           # Windows drive: "C:\"
      | ~[\\/]                   # tilde home:  "~/foo"
      | \.{1,2}[\\/]             # relative:    "./foo" or "../foo"
    )?
    (?:[A-Za-z0-9_-]+[\\/])*     # zero or more intermediate dirs
    [A-Za-z][A-Za-z0-9_-]*       # basename must start with a letter
    \.[A-Za-z]{1,6}              # extension
    (?![A-Za-z0-9_])             # no alnum immediately after extension
    (?!\.[A-Za-z])               # and not followed by another .letter
                                 # (rejects domain names like www.foo.com)
    """,
    re.VERBOSE,
)


def _highlight_file_paths(text: "Text") -> None:
    """In-place: recolor any file-path-looking tokens in purple."""
    try:
        text.highlight_regex(FILE_PATH_RE, style=f"bold {FILE_PURPLE}")
    except Exception:  # noqa: BLE001
        pass


class _BasePanel(Container):
    """Shared panel behavior. Subclassed by BigBroPanel and LilBroPanel."""

    active: reactive[bool] = reactive(False)

    AGENT_NAME: str = "Agent"
    AGENT_COLOR: str = "#FFFFFF"
    BORDER_COLOR: str = "#FFFFFF"
    BORDER_DIM: str = "#333333"
    TARGET: str = "agent"  # "big" | "bro" -- set by subclasses
    journal: "JournalRecorder | None" = None

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stream_buffer: str = ""
        self._last_assistant_message: str = ""
        self._thinking: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None
        # Parallel index of writes for Ctrl+F scrollback search.
        self._search_corpus: list[tuple[str, int]] = []

    def attach_journal(self, journal: "JournalRecorder") -> None:
        self.journal = journal

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-body"):
            yield Static("", classes="panel-header")
            yield RichLog(
                highlight=False,
                markup=False,
                wrap=True,
                auto_scroll=True,
                classes="panel-log",
            )
            yield Static("", classes="panel-stream")
            yield PacManTrack(color=self.AGENT_COLOR, classes="panel-pacman")

    def on_mount(self) -> None:
        self._render_header()

    def _render_header(self) -> None:
        header = self.query_one(".panel-header", Static)
        title = Text(f"-- {self.AGENT_NAME} --", style=f"bold {self.AGENT_COLOR}")
        header.update(title)

    def set_thinking(self, thinking: bool) -> None:
        """Show/hide an animated spinner in the panel header."""
        self._thinking = thinking
        if thinking:
            self._spinner_frame = 0
            if self._spinner_timer is None:
                self._spinner_timer = self.set_interval(0.1, self._tick_spinner)
        else:
            if self._spinner_timer is not None:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self._render_header()

    def _tick_spinner(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        frame = _SPINNER_FRAMES[self._spinner_frame]
        try:
            header = self.query_one(".panel-header", Static)
        except Exception:  # noqa: BLE001
            return
        title = Text()
        title.append(f"{frame} ", style=f"bold {self.AGENT_COLOR}")
        title.append(f"-- {self.AGENT_NAME} --", style=f"bold {self.AGENT_COLOR}")
        header.update(title)

    def watch_active(self, active: bool) -> None:
        if active:
            self.add_class("active-panel")
        else:
            self.remove_class("active-panel")

    # ---- widget accessors ----

    @property
    def log_widget(self) -> RichLog:
        return self.query_one(".panel-log", RichLog)

    @property
    def stream_widget(self) -> Static:
        return self.query_one(".panel-stream", Static)

    # ---- write helpers ----

    def _write_log(self, renderable: "Text", searchable: str) -> None:
        """Write a Text to the RichLog and record it in the search corpus."""
        log = self.log_widget
        try:
            strip_index = len(log.lines)
        except Exception:  # noqa: BLE001
            strip_index = 0
        log.write(renderable)
        if searchable:
            self._search_corpus.append((searchable, strip_index))

    def append_user_message(self, text: str) -> None:
        # Flush any in-flight stream first so the user message doesn't land
        # in the middle of a partial assistant line.
        self._flush_stream_to_log()
        stamp = datetime.now().strftime("%H:%M:%S")
        line = Text()
        line.append(f"[{stamp}] ", style="dim #666666")
        line.append("you ", style="bold #E8E8E8")
        line.append(text, style="#E8E8E8")
        _highlight_file_paths(line)
        self._write_log(line, f"you {text}")

    def start_agent_stream(self) -> None:
        """Called by OllamaAgent before streaming begins. Clears the
        stream buffer and activates the thinking spinner."""
        self._stream_buffer = ""
        self._refresh_stream_preview()
        self.set_thinking(True)

    def append_agent_chunk(self, chunk: str) -> None:
        """Buffer a streamed delta. Writes completed lines to the log and
        re-renders the pending partial in the stream preview."""
        if not chunk:
            return
        self._stream_buffer += chunk
        # Split off any complete lines and write them as individual log lines.
        while "\n" in self._stream_buffer:
            line, self._stream_buffer = self._stream_buffer.split("\n", 1)
            self._write_agent_line(line)
        # Refresh the preview with whatever partial line is still pending.
        self._refresh_stream_preview()

    def append_agent_message(self, text: str) -> None:
        """Append a full (non-streamed) agent message -- used for mock agents
        and the final flush path. Also remembers it for cross-talk."""
        self._flush_stream_to_log()
        self._last_assistant_message = text
        stamp = datetime.now().strftime("%H:%M:%S")
        header = Text(f"[{stamp}] {self.AGENT_NAME}", style=f"bold {self.AGENT_COLOR}")
        self._write_log(header, f"{self.AGENT_NAME}")
        body = Text.from_ansi(text)
        body.style = self.AGENT_COLOR
        _highlight_file_paths(body)
        self._write_log(body, text)

    def mark_assistant_complete(self, text: str = "") -> None:
        """End-of-turn marker. Flushes any pending stream into the log,
        clears the preview, stops the spinner, and records the full
        message for cross-talk + the journal."""
        self.set_thinking(False)
        self._flush_stream_to_log()
        if not text:
            return
        self._last_assistant_message = text
        if self.journal is not None:
            self.journal.record(self.TARGET, "agent", text)

    def append_error(self, text: str) -> None:
        self._flush_stream_to_log()
        err = Text(f"x {text}", style="bold #E85050")
        self._write_log(err, f"error {text}")
        if self.journal is not None:
            self.journal.record(self.TARGET, "error", text)

    def append_system(self, text: str) -> None:
        self._flush_stream_to_log()
        sys_line = Text(f"/ {text}", style="italic #888888")
        _highlight_file_paths(sys_line)
        self._write_log(sys_line, text)

    def append_file_action(self, action: str, path: str) -> None:
        """Render a distinct purple banner for a file-touching tool call."""
        self._flush_stream_to_log()
        stamp = datetime.now().strftime("%H:%M:%S")
        banner = Text()
        banner.append(f"[{stamp}] ", style="dim #666666")
        banner.append(f"{action} ", style=f"bold {FILE_PURPLE}")
        banner.append(path, style=f"bold {FILE_PURPLE}")
        self._write_log(banner, f"{action} {path}")
        if self.journal is not None:
            try:
                self.journal.record(self.TARGET, "tool", f"{action} {path}")
                self.journal.note_file_changed(path)
            except Exception:  # noqa: BLE001
                pass

    def append_diff(self, path: str, old_string: str, new_string: str) -> None:
        """Render a colored inline unified-diff for an Edit operation."""
        import difflib

        self._flush_stream_to_log()
        diff = list(
            difflib.unified_diff(
                old_string.splitlines(keepends=True),
                new_string.splitlines(keepends=True),
                n=2,
            )
        )
        if not diff:
            return
        body = diff[2:]
        for dl in body[:30]:
            stripped = dl.rstrip("\n")
            t = Text(stripped)
            if stripped.startswith("+"):
                t.stylize("#50C878")   # green add
            elif stripped.startswith("-"):
                t.stylize("#E85050")   # red remove
            elif stripped.startswith("@@"):
                t.stylize("dim cyan")
            else:
                t.stylize("dim #666666")
            self._write_log(t, stripped)
        remaining = len(body) - 30
        if remaining > 0:
            self._write_log(
                Text(f"  ... {remaining} more diff lines", style="dim #888888"), ""
            )

    def toggle_wrap(self) -> bool:
        """Toggle soft-wrap on the log widget. Returns the new wrap state."""
        log = self.log_widget
        log.wrap = not getattr(log, "wrap", True)
        log.refresh(layout=True)
        return bool(log.wrap)

    def clear_log(self) -> None:
        """Ctrl+L / /clear -- wipe the panel's scrollback."""
        self._stream_buffer = ""
        self.log_widget.clear()
        self._search_corpus.clear()
        self._refresh_stream_preview()
        self._render_header()

    # ---- Ctrl+F scrollback search ----

    def search(self, query: str) -> list[int]:
        """Return strip indices of every corpus entry containing ``query``."""
        if not query:
            return []
        q = query.lower()
        return [idx for text, idx in self._search_corpus if q in text.lower()]

    def scroll_to_strip(self, strip_index: int) -> None:
        """Scroll the RichLog so the given strip row is visible near the top."""
        log = self.log_widget
        try:
            log.scroll_to(y=max(0, strip_index), animate=False)
        except Exception:  # noqa: BLE001
            pass

    # ---- streaming internals ----

    def _write_agent_line(self, line: str) -> None:
        """Write one completed line into the RichLog in the agent's color."""
        if line == "":
            self.log_widget.write(Text(""))
            return
        rendered = Text.from_ansi(line)
        rendered.style = self.AGENT_COLOR
        _highlight_file_paths(rendered)
        self._write_log(rendered, line)

    def _refresh_stream_preview(self) -> None:
        """Update the stream preview Static with the current partial line."""
        preview = self.stream_widget
        if not self._stream_buffer:
            preview.update("")
            return
        tail = self._stream_buffer
        PREVIEW_TAIL = 400
        if len(tail) > PREVIEW_TAIL:
            tail = "... " + tail[-PREVIEW_TAIL:]
        rendered = Text.from_ansi(tail)
        rendered.style = self.AGENT_COLOR
        _highlight_file_paths(rendered)
        preview.update(rendered)

    def _flush_stream_to_log(self) -> None:
        """Drain any pending stream buffer into the log and clear the preview."""
        if self._stream_buffer:
            parts = self._stream_buffer.split("\n")
            for part in parts:
                self._write_agent_line(part)
            self._stream_buffer = ""
        self._refresh_stream_preview()

    @property
    def last_assistant_message(self) -> str:
        return self._last_assistant_message

    def ingest_session_dump_for_port(self, dump: str) -> None:
        """Scan a SESSION.md tail dump for this panel's most recent
        ``AGENT <role>:`` line and populate ``_last_assistant_message``."""
        import re as _re

        role = self.TARGET  # "big" or "bro"
        pattern = _re.compile(
            rf"^\[\d{{2}}:\d{{2}}:\d{{2}}\]\s+AGENT\s+{_re.escape(role)}:\s*(.*)$"
        )
        last_body: str | None = None
        for line in dump.splitlines():
            m = pattern.match(line)
            if m:
                last_body = m.group(1)
        if not last_body:
            return
        cleaned = last_body.rstrip()
        if cleaned.endswith("..."):
            cleaned = cleaned[:-3].rstrip()
        if cleaned:
            self._last_assistant_message = cleaned


class LilBroPanel(_BasePanel):
    """Left pane -- helper/explainer role (green)."""
    AGENT_NAME = "LIL BRO"
    AGENT_COLOR = "#A8D840"
    BORDER_COLOR = "#A8D840"
    BORDER_DIM = "#2A3518"
    TARGET = "bro"


class BigBroPanel(_BasePanel):
    """Right pane -- coder role (orange)."""
    AGENT_NAME = "BIG BRO"
    AGENT_COLOR = "#E8A838"
    BORDER_COLOR = "#E8A838"
    BORDER_DIM = "#3A2A18"
    TARGET = "big"
