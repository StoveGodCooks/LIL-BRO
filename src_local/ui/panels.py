"""Dual pane widgets for LIL BRO LOCAL.

Two panes side by side:
- Lil Bro (left, green #A8D840) -- helper/explainer role
- Big Bro (right, orange #E8A838) -- coder role

Each panel has three vertically stacked regions:

  +-- Header (sticky, 1 line) ---------+
  | -- BRO A --                        |
  +------------------------------------+
  | VerticalScroll log                 |
  |   Static   <- completed text       |
  |   Static   <- streaming partial    |
  |   Collapsible tool-call blocks     |
  +------------------------------------+
  | PacMan heartbeat track             |
  +------------------------------------+

**Streaming contract**

Agent chunks arrive as arbitrarily-sized text deltas. We keep a single
"live" Static at the end of the log showing the pending partial line.
When a newline lands, that partial graduates to a permanent rendered
line and a fresh partial is mounted for the remaining buffer. This
keeps the live text inside the scrollable log (so it flows naturally
top-to-bottom with older content pushing up) instead of pinned to the
panel's bottom edge.

**Auto-scroll**

Auto-scroll only pins to bottom when the user was *already* at the
bottom. Scroll up to read older content and new streamed chunks will
no longer yank the viewport.

**Tool calls**

`append_tool_call(summary, detail)` mounts a collapsed block the user
can expand to see the full tool input/output. Used for Read/Edit/Bash
so the panel stays scannable while full detail is one click away.

**File-path highlighting**

Any file path mentioned in agent output or tool badges is rendered in
purple (`#C878E8`) so the user can spot exactly what files the agents
are working on at a glance.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Collapsible, Static

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

# Simple code-fence detection for basic markdown-like rendering.
_CODE_FENCE_RE = re.compile(r"^```(\w*)$")

# Strip markdown link syntax [label](url) → label before rendering.
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


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
    BODY_COLOR: str = "#D0D0D0"
    CODE_BG: str = "#1A1A1A"
    BORDER_COLOR: str = "#FFFFFF"
    BORDER_DIM: str = "#333333"
    TARGET: str = "agent"  # "big" | "bro"
    journal: "JournalRecorder | None" = None

    # Max chars kept inside a Collapsible tool-detail body before truncation.
    TOOL_DETAIL_MAX = 8000

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stream_buffer: str = ""
        self._last_assistant_message: str = ""
        self._thinking: bool = False
        self._spinner_frame: int = 0
        self._spinner_timer: Timer | None = None
        # Ordered list of (searchable_text, widget_ref) for Ctrl+F.
        self._search_corpus: list[tuple[str, Static | Collapsible]] = []
        self._in_code_fence: bool = False
        self._code_lang: str = ""
        # Streaming partial line widget. Mounted at the tail of the log
        # while a stream is in flight; replaced with permanent Statics as
        # newlines arrive.
        self._partial_static: Static | None = None
        # Chunk-batching: accumulate deltas for CHUNK_BATCH_MS before painting.
        self._pending_chunks: str = ""
        self._chunk_flush_timer: Timer | None = None
        self._scroll_counter: int = 0

    def attach_journal(self, journal: "JournalRecorder") -> None:
        self.journal = journal

    def compose(self) -> ComposeResult:
        with Vertical(classes="panel-body"):
            yield Static("", classes="panel-header")
            yield VerticalScroll(classes="panel-log")
            yield PacManTrack(color=self.AGENT_COLOR, classes="panel-pacman")

    def on_mount(self) -> None:
        self._render_header()
        # Give the scroll a dynamic `auto_scroll` attribute so the search
        # screen can freeze it without us needing a new API.
        log = self.log_widget
        log.auto_scroll = True  # type: ignore[attr-defined]

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
                self._spinner_timer = self.set_interval(0.2, self._tick_spinner)
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
    def log_widget(self) -> VerticalScroll:
        return self.query_one(".panel-log", VerticalScroll)

    # ---- scroll helpers ----

    def _is_at_bottom(self) -> bool:
        """True if the user is already pinned to the bottom of the log."""
        try:
            log = self.log_widget
            # Within 2 rows of the end counts as "at bottom" for UX purposes.
            return log.scroll_y >= max(0, log.max_scroll_y - 2)
        except Exception:  # noqa: BLE001
            return True

    def _auto_scroll_on(self) -> bool:
        try:
            return bool(getattr(self.log_widget, "auto_scroll", True))
        except Exception:  # noqa: BLE001
            return True

    def _maybe_scroll_end(self, was_at_bottom: bool) -> None:
        """Scroll to end only if the user was pinned there AND auto-scroll
        hasn't been frozen (e.g. by Ctrl+F)."""
        if not was_at_bottom or not self._auto_scroll_on():
            return
        try:
            self.log_widget.scroll_end(animate=False)
        except Exception:  # noqa: BLE001
            pass

    def _ensure_scroll_end(self) -> None:
        """Legacy unconditional scroll — kept for callers that still rely
        on it. Respects the auto_scroll freeze but ignores scroll position."""
        if not self._auto_scroll_on():
            return
        try:
            self.log_widget.scroll_end(animate=False)
        except Exception:  # noqa: BLE001
            pass

    # ---- partial-line streaming ----

    def _ensure_partial(self) -> Static:
        if self._partial_static is None:
            self._partial_static = Static(
                "", markup=False, classes="log-line log-partial"
            )
            self.log_widget.mount(self._partial_static)
        return self._partial_static

    def _update_partial(self, text: str) -> None:
        static = self._ensure_partial()
        rendered = Text(text, style=self.BODY_COLOR)
        _highlight_file_paths(rendered)
        static.update(rendered)

    def _remove_partial(self) -> None:
        if self._partial_static is not None:
            try:
                self._partial_static.remove()
            except Exception:  # noqa: BLE001
                pass
            self._partial_static = None

    # ---- write helpers ----

    def _write_log(self, renderable: "Text", searchable: str) -> None:
        """Mount a Text as a permanent Static line in the log. Placed before
        the streaming partial (if any) so the partial stays at the tail."""
        was_at_bottom = self._is_at_bottom()
        static = Static(renderable, markup=False, classes="log-line")
        log = self.log_widget
        try:
            if self._partial_static is not None:
                log.mount(static, before=self._partial_static)
            else:
                log.mount(static)
        except Exception:  # noqa: BLE001
            # Fallback: mount at end.
            try:
                log.mount(static)
            except Exception:  # noqa: BLE001
                return
        if searchable:
            self._search_corpus.append((searchable, static))
        self._maybe_scroll_end(was_at_bottom)

    def append_user_message(self, text: str) -> None:
        self._flush_stream_to_log()
        stamp = datetime.now().strftime("%H:%M:%S")
        line = Text()
        line.append(f"[{stamp}] ", style="dim #666666")
        line.append("you ", style="bold #E8E8E8")
        line.append(text, style="#E8E8E8")
        _highlight_file_paths(line)
        self._write_log(line, f"you {text}")

    def start_agent_stream(self) -> None:
        """Called by the agent before streaming begins. Writes a timestamp
        header and activates the thinking spinner."""
        self._stream_buffer = ""
        self._pending_chunks = ""
        self._scroll_counter = 0
        if self._chunk_flush_timer is not None:
            self._chunk_flush_timer.stop()
            self._chunk_flush_timer = None
        self._in_code_fence = False
        self._code_lang = ""
        self._remove_partial()
        stamp = datetime.now().strftime("%H:%M:%S")
        header = Text()
        header.append(f"[{stamp}] ", style="dim #666666")
        header.append(f"{self.AGENT_NAME}", style=f"bold {self.AGENT_COLOR}")
        self._write_log(header, f"{self.AGENT_NAME}")
        self.set_thinking(True)

    # Batch incoming deltas for this many seconds before repainting.
    _CHUNK_BATCH_SECS = 0.04

    def append_agent_chunk(self, chunk: str) -> None:
        """Buffer a streamed delta. Defers painting by CHUNK_BATCH_SECS so
        rapid token bursts are batched into fewer Textual repaints."""
        if not chunk:
            return
        self._pending_chunks += chunk
        if self._chunk_flush_timer is None:
            self._chunk_flush_timer = self.set_timer(
                self._CHUNK_BATCH_SECS, self._flush_pending_chunks
            )

    def _flush_pending_chunks(self) -> None:
        """Paint all pending chunk data accumulated since the last flush."""
        self._chunk_flush_timer = None
        chunk = self._pending_chunks
        self._pending_chunks = ""
        if not chunk:
            return
        was_at_bottom = self._is_at_bottom()
        self._stream_buffer += chunk
        while "\n" in self._stream_buffer:
            line, self._stream_buffer = self._stream_buffer.split("\n", 1)
            self._remove_partial()
            self._write_agent_line(line)
        if self._stream_buffer:
            self._update_partial(self._stream_buffer)
        else:
            self._remove_partial()
        # Throttle scroll_end: only scroll every 5 flushes to reduce work.
        self._scroll_counter += 1
        if self._scroll_counter >= 5 or was_at_bottom:
            self._scroll_counter = 0
            self._maybe_scroll_end(was_at_bottom)

    def append_agent_message(self, text: str) -> None:
        """Append a full (non-streamed) agent message."""
        self._flush_stream_to_log()
        self._last_assistant_message = text
        stamp = datetime.now().strftime("%H:%M:%S")
        header = Text(f"[{stamp}] {self.AGENT_NAME}", style=f"bold {self.AGENT_COLOR}")
        self._write_log(header, f"{self.AGENT_NAME}")
        for raw_line in text.split("\n"):
            self._write_agent_line(raw_line)

    def mark_assistant_complete(self, text: str = "") -> None:
        """End-of-turn marker. Flushes pending stream, clears partial, stops
        spinner, records the full message for cross-talk + the journal."""
        self.set_thinking(False)
        self._in_code_fence = False
        self._code_lang = ""
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

    def append_intro(self, text: str) -> None:
        """Render the agent's startup intro as a highlighted bro-colored
        message so it stands out from the grey system lines above it."""
        self._flush_stream_to_log()
        stamp = datetime.now().strftime("%H:%M:%S")
        header = Text(f"[{stamp}] {self.AGENT_NAME}", style=f"bold {self.AGENT_COLOR}")
        self._write_log(header, self.AGENT_NAME)
        body = Text(text, style=f"bold {self.AGENT_COLOR}")
        self._write_log(body, text)

    def append_file_action(self, action: str, path: str) -> None:
        """Render a distinct purple banner for a file-touching tool call.

        Kept as a simple one-liner (no expand) for backward compatibility
        with Ollama's tool loop. Richer tool surfaces should use
        ``append_tool_call``."""
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

    def append_tool_call(
        self,
        summary: str,
        detail: str = "",
        *,
        path: str | None = None,
    ) -> None:
        """Mount a collapsed Collapsible block showing a tool call.

        ``summary`` becomes the header (visible when collapsed).
        ``detail`` is the body (visible when expanded) — typically the
        content read, command output, or full diff. Oversized bodies are
        truncated with a note. ``path`` is recorded in the journal as a
        file-touch when provided."""
        self._flush_stream_to_log()
        was_at_bottom = self._is_at_bottom()
        stamp = datetime.now().strftime("%H:%M:%S")
        title = f"[{stamp}] {summary}"
        raw = detail or "(no detail captured)"
        original_len = len(raw)
        if original_len > self.TOOL_DETAIL_MAX:
            raw = raw[: self.TOOL_DETAIL_MAX] + (
                f"\n... [{original_len - self.TOOL_DETAIL_MAX} more chars truncated]"
            )
        body_text = Text(raw, style="#C8C8C8")
        _highlight_file_paths(body_text)
        body_widget = Static(body_text, classes="tool-detail", markup=False)
        collapsible = Collapsible(
            body_widget,
            title=title,
            collapsed=True,
            classes="tool-call",
        )
        try:
            if self._partial_static is not None:
                self.log_widget.mount(collapsible, before=self._partial_static)
            else:
                self.log_widget.mount(collapsible)
        except Exception:  # noqa: BLE001
            try:
                self.log_widget.mount(collapsible)
            except Exception:  # noqa: BLE001
                return
        self._search_corpus.append((f"{summary} {raw[:500]}", collapsible))
        if self.journal is not None:
            try:
                self.journal.record(self.TARGET, "tool", summary)
                if path:
                    self.journal.note_file_changed(path)
            except Exception:  # noqa: BLE001
                pass
        self._maybe_scroll_end(was_at_bottom)

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
                t.stylize("#50C878")
            elif stripped.startswith("-"):
                t.stylize("#E85050")
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
        """Toggle soft-wrap across all existing log lines. Returns new state."""
        # VerticalScroll doesn't have a wrap attr; we stash it on the panel
        # and apply to each log-line Static.
        current = getattr(self, "_soft_wrap", True)
        new = not current
        self._soft_wrap = new
        for child in self.log_widget.query(".log-line"):
            try:
                child.styles.width = "100%"
            except Exception:  # noqa: BLE001
                pass
        self.log_widget.refresh(layout=True)
        return new

    def clear_log(self) -> None:
        """Ctrl+L / /clear -- wipe the panel's scrollback."""
        self._stream_buffer = ""
        self._remove_partial()
        for child in list(self.log_widget.children):
            try:
                child.remove()
            except Exception:  # noqa: BLE001
                pass
        self._search_corpus.clear()
        self._render_header()

    # ---- Ctrl+F scrollback search ----

    def search(self, query: str) -> list:
        """Return widget references for every corpus entry containing ``query``."""
        if not query:
            return []
        q = query.lower()
        return [widget for text, widget in self._search_corpus if q in text.lower()]

    def scroll_to_strip(self, target) -> None:
        """Scroll the log so the target match is visible. ``target`` is a
        widget reference from ``search()``."""
        try:
            if hasattr(target, "scroll_visible"):
                target.scroll_visible(animate=False, center=True)
        except Exception:  # noqa: BLE001
            pass

    # ---- streaming internals ----

    def _write_agent_line(self, line: str) -> None:
        """Render one completed line as a permanent Static in the log."""
        if line == "":
            self._write_log(Text(""), "")
            return

        # Strip markdown link syntax [label](url) → label so raw markdown
        # from model output doesn't show through as jumbled text.
        line = _MD_LINK_RE.sub(r"\1", line)

        fence_match = _CODE_FENCE_RE.match(line.strip())
        if fence_match:
            if not self._in_code_fence:
                self._in_code_fence = True
                self._code_lang = fence_match.group(1)
                lang_label = self._code_lang or "code"
                rendered = Text(f"  ╭─ {lang_label} ", style=f"dim {self.AGENT_COLOR}")
                self._write_log(rendered, line)
            else:
                self._in_code_fence = False
                self._code_lang = ""
                rendered = Text("  ╰─────", style=f"dim {self.AGENT_COLOR}")
                self._write_log(rendered, line)
            return

        if self._in_code_fence:
            rendered = Text("  │ ", style=f"dim {self.AGENT_COLOR}")
            rendered.append(line, style="#C8C8C8")
            _highlight_file_paths(rendered)
            self._write_log(rendered, line)
            return

        stripped = line.strip()

        if stripped.startswith("# ") or stripped.startswith("## ") or stripped.startswith("### "):
            heading_text = stripped.lstrip("#").strip()
            rendered = Text(heading_text, style=f"bold {self.AGENT_COLOR}")
            self._write_log(rendered, line)
            return

        if stripped.startswith("- ") or stripped.startswith("* "):
            rendered = Text("  • ", style=f"bold {self.AGENT_COLOR}")
            rendered.append(stripped[2:], style=self.BODY_COLOR)
            _highlight_file_paths(rendered)
            self._write_log(rendered, line)
            return

        if len(stripped) > 2 and stripped[0].isdigit() and ". " in stripped[:5]:
            dot_pos = stripped.index(". ")
            num = stripped[:dot_pos + 1]
            rest = stripped[dot_pos + 2:]
            rendered = Text(f"  {num} ", style=f"bold {self.AGENT_COLOR}")
            rendered.append(rest, style=self.BODY_COLOR)
            _highlight_file_paths(rendered)
            self._write_log(rendered, line)
            return

        rendered = Text.from_ansi(line)
        rendered.style = self.BODY_COLOR
        _highlight_file_paths(rendered)

        try:
            rendered.highlight_regex(
                r"\*\*(.+?)\*\*", style=f"bold {self.AGENT_COLOR}"
            )
        except Exception:  # noqa: BLE001
            pass

        try:
            rendered.highlight_regex(
                r"`([^`]+)`", style="bold #C8C8C8"
            )
        except Exception:  # noqa: BLE001
            pass

        self._write_log(rendered, line)

    def _flush_stream_to_log(self) -> None:
        """Drain any pending stream buffer into the log and clear the partial."""
        # Cancel the batch timer and fold any pending chunks into the buffer.
        if self._chunk_flush_timer is not None:
            self._chunk_flush_timer.stop()
            self._chunk_flush_timer = None
        if self._pending_chunks:
            self._stream_buffer += self._pending_chunks
            self._pending_chunks = ""
        if self._stream_buffer:
            parts = self._stream_buffer.split("\n")
            for part in parts:
                self._remove_partial()
                self._write_agent_line(part)
            self._stream_buffer = ""
        self._remove_partial()

    @property
    def last_assistant_message(self) -> str:
        return self._last_assistant_message

    def ingest_session_dump_for_port(self, dump: str) -> None:
        """Scan a SESSION.md tail dump for this panel's most recent
        ``AGENT <role>:`` line and populate ``_last_assistant_message``."""
        import re as _re

        role = self.TARGET
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
    BODY_COLOR = "#A8D840"  # Lil Bro speaks in green
    CODE_BG = "#101810"
    BORDER_COLOR = "#A8D840"
    BORDER_DIM = "#2A3518"
    TARGET = "bro"


class BigBroPanel(_BasePanel):
    """Right pane -- coder role (orange)."""
    AGENT_NAME = "BIG BRO"
    AGENT_COLOR = "#E8A838"
    BODY_COLOR = "#E8A838"  # Big Bro speaks in orange
    CODE_BG = "#181410"
    BORDER_COLOR = "#E8A838"
    BORDER_DIM = "#3A2A18"
    TARGET = "big"
