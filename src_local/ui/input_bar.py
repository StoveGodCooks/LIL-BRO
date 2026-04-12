"""Input bar at the bottom of the dual-pane screen.

Shows which agent is the active target (prefix label), dispatches
submitted text to the router, and hosts the two beginner-friendliness
helpers:

- **Slash command palette** -- when the user types ``/`` as the first
  character, a live-filtered floating list of commands appears just
  above the input. Up/Down to select, Tab to accept, Esc to dismiss.
- **Ghost-text autocomplete** -- a :class:`SlashSuggester` is attached
  to the Input so that typing ``/pl`` shows a faded ``an`` suggestion
  the user can accept with the right arrow.

The InputBar owns ALL palette keyboard handling via ``on_key``. The
palette itself is passive -- it only filters, selects, and renders.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Static

from src_local.ui.command_palette import CommandPalette
from src_local.ui.slash_suggester import SlashSuggester

if TYPE_CHECKING:
    from src_local.router import Router


logger = logging.getLogger("lilbro.input")

# Command history persisted to ~/.lilbro-local/history.json so Up/Down recall
# survives across sessions. Capped so the file stays small.
HISTORY_PATH = Path.home() / ".lilbro-local" / "history.json"
HISTORY_MAX = 200

# Input above this many chars on submit is treated as a "paste bomb" --
# instead of sending immediately, we open the compose modal pre-filled
# with the text so the user can review before committing a huge turn.
PASTE_BOMB_THRESHOLD = 2500


# Placeholder cycles through these so new users discover features
# without needing to open the help screen.
PLACEHOLDER_HINTS = [
    "Type / for commands  /  Tab switch  /  F1 help  /  Ctrl+Q quit",
    "Try /plan add a login page  (Big Bro outlines steps first)",
    "Try /explain decorators  (Lil Bro teaches in 6 sections)",
    "Ctrl+C ports Big Bro's reply -> Lil Bro  /  Ctrl+B ports the other way",
]


class InputBar(Vertical):
    """Bottom input area: slash palette + prefix + input field."""

    def __init__(self, router: "Router", **kwargs) -> None:
        super().__init__(**kwargs)
        self._router = router
        self._palette: CommandPalette | None = None
        self._suggester = SlashSuggester()
        self._hint_index = 0
        # Command history -- newest entries at the end. `_history_index`
        # is a cursor for Up/Down recall; None = at "current draft" (not
        # browsing history). The draft is stashed so Down past the end
        # restores what the user was typing before they hit Up.
        self._history: list[str] = self._load_history()
        self._history_index: int | None = None
        self._history_draft: str = ""

    def compose(self) -> ComposeResult:
        # Palette sits ABOVE the prefix+input row so it reads as a
        # floating hint bar. It auto-hides when not in use.
        self._palette = CommandPalette(id="command-palette")
        yield self._palette
        # The actual input row -- horizontal layout of prefix + field.
        with Horizontal(id="input-row"):
            yield Static("[BIG BRO >]", id="input-prefix", classes="big")
            yield Input(
                placeholder=PLACEHOLDER_HINTS[0],
                id="input-field",
                suggester=self._suggester,
            )

    def on_mount(self) -> None:
        self.refresh_prefix()
        # Ensure the input field has initial target class for border color.
        field = self.query_one("#input-field", Input)
        if self._router.active_target == "big":
            field.add_class("target-big")
        else:
            field.add_class("target-bro")

    # -----------------------------------------------------------------
    # Prefix / target indicator
    # -----------------------------------------------------------------

    def refresh_prefix(self) -> None:
        prefix = self.query_one("#input-prefix", Static)
        field = self.query_one("#input-field", Input)
        if self._router.active_target == "big":
            prefix.update("[BIG BRO >]")
            prefix.remove_class("bro")
            prefix.add_class("big")
            field.remove_class("target-bro")
            field.add_class("target-big")
        else:
            prefix.update("[> LIL BRO]")
            prefix.remove_class("big")
            prefix.add_class("bro")
            field.remove_class("target-big")
            field.add_class("target-bro")

    def set_draft(self, text: str) -> None:
        """Populate the input field without sending (used for cross-talk port).

        Textual's ``Input`` is a single-line widget, so we must collapse
        embedded newlines and carriage returns before assigning. We also
        cap length at ``MAX_DRAFT_CHARS`` so pasting an entire agent
        reply can't wedge the widget.
        """
        MAX_DRAFT_CHARS = 6000
        # Collapse newlines -> space, drop stray carriage returns and tabs.
        flat = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
        # Collapse runs of whitespace so the draft reads cleanly.
        flat = " ".join(flat.split())
        if len(flat) > MAX_DRAFT_CHARS:
            flat = flat[:MAX_DRAFT_CHARS] + "  ...[truncated]"
        field = self.query_one("#input-field", Input)
        try:
            field.value = flat
        except Exception:  # noqa: BLE001
            # Never crash the UI on a draft -- worst case leave input empty.
            field.value = ""
        try:
            field.cursor_position = len(field.value)
        except Exception:  # noqa: BLE001
            pass
        field.focus()
        # Cross-talk drafts are free-form text, not slash commands.
        self._hide_palette()

    def focus_input(self) -> None:
        self.query_one("#input-field", Input).focus()

    # -----------------------------------------------------------------
    # Palette show / hide helpers
    # -----------------------------------------------------------------

    def _show_palette(self, query: str) -> None:
        if self._palette is None:
            return
        self._palette.reset_selection()
        self._palette.filter(query)
        self._palette.show()

    def _hide_palette(self) -> None:
        if self._palette is not None:
            self._palette.hide()

    # -----------------------------------------------------------------
    # Input reactions
    # -----------------------------------------------------------------

    # -----------------------------------------------------------------
    # File-drop / paste detection helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _detect_file_drop(value: str) -> Path | None:
        """Return a Path if *value* looks like a dropped/pasted file path
        that exists on disk, else None.

        Handles:
        - Windows absolute paths: ``C:\\Users\\...``, ``D:/projects/...``
        - UNC paths: ``\\\\server\\share\\file``
        - Unix/WSL absolute paths: ``/home/...``
        - Tilde paths: ``~/...``
        - Paths wrapped in single or double quotes (terminal drop convention)
        """
        import re
        text = value.strip()
        # Strip surrounding quotes from terminal file-drop
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            text = text[1:-1]
        # Must look like a path: Windows (X:\ or X:/), UNC (\\...), or Unix-style
        looks_like_path = bool(
            re.match(r"^[A-Za-z]:[/\\]", text)   # Windows absolute
            or text.startswith("\\\\")             # UNC
            or text.startswith("/")                # Unix
            or text.startswith("~")                # tilde
        )
        if not looks_like_path:
            return None
        try:
            p = Path(text).expanduser().resolve()
            if p.is_file():
                return p
        except Exception:  # noqa: BLE001
            pass
        return None

    def on_input_changed(self, event: Input.Changed) -> None:
        """Fires on every keystroke. Drives palette visibility + filter.

        Also detects when a file path is pasted/dropped into the input
        (e.g. drag-and-drop in Windows Terminal) and diverts it into the
        compose modal so the user can type a question around the path.
        """
        value = event.value
        if self._palette is None:
            return

        # File-drop detection: if the entire input is a valid file path,
        # redirect to compose instead of sending it bare.
        if value and not value.startswith("/"):
            dropped = self._detect_file_drop(value)
            if dropped is not None:
                event.input.value = ""
                self._hide_palette()
                self._open_compose_for_file(dropped)
                return

        # Show palette only while the user is composing a slash command
        # AND they haven't started typing arguments (no space yet).
        if value.startswith("/") and " " not in value:
            if not self._palette.visible:
                self._palette.reset_selection()
                self._palette.show()
            self._palette.filter(value)
        else:
            self._palette.hide()

    def _open_compose_for_file(self, file_path: Path) -> None:
        """Open the compose modal pre-filled with a dropped file path."""
        from src_local.ui.compose_screen import ComposeScreen

        target = self._router.active_target
        label = "Big Bro" if target == "big" else "Lil Bro"
        # Pre-fill: the path on its own line so the user can type above/below
        initial = str(file_path)

        panel = (
            self._router.big_bro_panel if target == "big" else self._router.lil_bro_panel
        )
        panel.append_system("(file dropped -- opening compose with path)")

        async def _run() -> None:
            result = await self.app.push_screen_wait(
                ComposeScreen(initial_text=initial, target_label=label)
            )
            if result is None:
                return
            self._record_history(result)
            await self._router.route_user_input(result)

        self.app.run_worker(_run(), exclusive=False)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        self._hide_palette()
        if not text:
            return
        # Rotate through the placeholder hints so a new user sees
        # different nudges over time.
        self._cycle_placeholder(event.input)
        # Paste-bomb guard: anything over PASTE_BOMB_THRESHOLD chars is
        # much more likely to be an accidental paste than a thoughtful
        # message. Divert into the compose modal so the user can review
        # before committing the turn.
        if len(text) >= PASTE_BOMB_THRESHOLD:
            self._handoff_to_compose(text)
            return
        # Record in history (dedupe trailing duplicate) and persist.
        self._record_history(text)
        await self._router.route_user_input(text)

    def _handoff_to_compose(self, text: str) -> None:
        """Open the compose modal pre-filled with ``text``."""
        from src_local.ui.compose_screen import ComposeScreen

        target = self._router.active_target
        label = "Big Bro" if target == "big" else "Lil Bro"
        panel = (
            self._router.big_bro_panel if target == "big" else self._router.lil_bro_panel
        )
        panel.append_system(
            f"(paste is {len(text):,} chars -- opening compose so you can review before sending)"
        )

        async def _run() -> None:
            result = await self.app.push_screen_wait(
                ComposeScreen(initial_text=text, target_label=label)
            )
            if result is None:
                return
            self._record_history(result)
            await self._router.route_user_input(result)

        self.app.run_worker(_run(), exclusive=False)

    def _cycle_placeholder(self, input_widget: Input) -> None:
        self._hint_index = (self._hint_index + 1) % len(PLACEHOLDER_HINTS)
        input_widget.placeholder = PLACEHOLDER_HINTS[self._hint_index]

    # -----------------------------------------------------------------
    # Keyboard interception for palette navigation
    # -----------------------------------------------------------------

    def on_key(self, event: events.Key) -> None:
        """Handle palette nav + command history BEFORE the Input gets them."""
        palette_open = self._palette is not None and self._palette.visible
        key = event.key

        if palette_open:
            if key == "up":
                self._palette.move_selection(-1)  # type: ignore[union-attr]
                event.stop()
                event.prevent_default()
                return
            if key == "down":
                self._palette.move_selection(1)  # type: ignore[union-attr]
                event.stop()
                event.prevent_default()
                return
            if key == "tab":
                self._accept_palette_selection()
                event.stop()
                event.prevent_default()
                return
            if key == "enter":
                self._accept_palette_selection()
                event.stop()
                event.prevent_default()
                return
            if key == "escape":
                self._hide_palette()
                event.stop()
                event.prevent_default()
                return
            return

        # --- palette closed: history recall + Esc draft clear ---
        if key == "up":
            if self._history_prev():
                event.stop()
                event.prevent_default()
            return
        if key == "down":
            if self._history_next():
                event.stop()
                event.prevent_default()
            return
        if key == "escape":
            field = self.query_one("#input-field", Input)
            if field.value:
                field.value = ""
                self._history_index = None
                self._history_draft = ""
                event.stop()
                event.prevent_default()
            # Empty field -> let Esc bubble up to the screen so
            # DualPaneScreen.action_cancel_turn can fire.
            return

    def _accept_palette_selection(self) -> None:
        """Copy the highlighted palette row's trigger into the input field."""
        if self._palette is None:
            return
        trigger = self._palette.current_command()
        if not trigger:
            return
        field = self.query_one("#input-field", Input)
        entry = self._palette.current_entry()
        needs_args = (
            entry is not None and ("<" in entry[0] or "[" in entry[0])
        )
        field.value = trigger + (" " if needs_args else "")
        try:
            field.cursor_position = len(field.value)
        except Exception:  # noqa: BLE001
            pass
        self._hide_palette()

    # -----------------------------------------------------------------
    # Command history (persisted to ~/.lilbro-local/history.json)
    # -----------------------------------------------------------------

    def _load_history(self) -> list[str]:
        try:
            if not HISTORY_PATH.exists():
                return []
            raw = HISTORY_PATH.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, list):
                return []
            # Defensive: accept only strings, cap to HISTORY_MAX.
            cleaned = [s for s in data if isinstance(s, str) and s]
            return cleaned[-HISTORY_MAX:]
        except Exception as exc:  # noqa: BLE001
            logger.debug("history load failed: %s", exc)
            return []

    def _save_history(self) -> None:
        try:
            HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            HISTORY_PATH.write_text(
                json.dumps(self._history[-HISTORY_MAX:], ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("history save failed: %s", exc)

    def _record_history(self, text: str) -> None:
        """Append ``text`` to history, dedup trailing duplicate."""
        if not text:
            return
        if self._history and self._history[-1] == text:
            self._history_index = None
            self._history_draft = ""
            return
        self._history.append(text)
        if len(self._history) > HISTORY_MAX:
            self._history = self._history[-HISTORY_MAX:]
        self._history_index = None
        self._history_draft = ""
        self._save_history()

    def _history_prev(self) -> bool:
        """Walk one step backward through history. Returns True if moved."""
        if not self._history:
            return False
        field = self.query_one("#input-field", Input)
        if self._history_index is None:
            self._history_draft = field.value
            self._history_index = len(self._history) - 1
        else:
            if self._history_index == 0:
                return True  # already at oldest entry, stay
            self._history_index -= 1
        field.value = self._history[self._history_index]
        try:
            field.cursor_position = len(field.value)
        except Exception:  # noqa: BLE001
            pass
        return True

    def _history_next(self) -> bool:
        """Walk one step forward through history. Returns True if moved."""
        if self._history_index is None:
            return False
        field = self.query_one("#input-field", Input)
        if self._history_index >= len(self._history) - 1:
            field.value = self._history_draft
            self._history_index = None
            self._history_draft = ""
        else:
            self._history_index += 1
            field.value = self._history[self._history_index]
        try:
            field.cursor_position = len(field.value)
        except Exception:  # noqa: BLE001
            pass
        return True
