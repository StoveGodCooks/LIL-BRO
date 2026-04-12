"""Message routing for LIL BRO LOCAL.

Routes user input to the active agent (Bro A or Bro B). Both are
local Ollama models — no CLI subprocess distinction, no file-write
permissions to enforce.

| Source          | Destinations                     |
|-----------------|----------------------------------|
| User input      | ONE of {Bro A, Bro B}            |
| Agent output    | Only its own panel               |
| Cross-talk port | Drafts into target pane's input  |
| Slash command   | Command handler first            |
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src_local.agents.ollama_agent import OllamaAgent
    from src_local.commands.handler import CommandHandler
    from src_local.journal.recorder import JournalRecorder
    from src_local.ui.input_bar import InputBar
    from src_local.ui.panels import BroAPanel, BroBPanel
    from src_local.ui.status_bar import StatusBar


Target = Literal["a", "b"]


class Router:
    """Owns active-target state and dispatches user input."""

    def __init__(
        self,
        bro_a_panel: "BroAPanel",
        bro_b_panel: "BroBPanel",
        bro_a_agent: "OllamaAgent",
        bro_b_agent: "OllamaAgent",
        commands: "CommandHandler",
        journal: "JournalRecorder",
        status_bar: "StatusBar | None" = None,
    ) -> None:
        self.bro_a_panel = bro_a_panel
        self.bro_b_panel = bro_b_panel
        self.bro_a_agent = bro_a_agent
        self.bro_b_agent = bro_b_agent
        self.commands = commands
        self.journal = journal
        self.status_bar = status_bar
        self._active: Target = "a"
        self._input_bar: "InputBar | None" = None
        self._last_prompt: dict[Target, str] = {}

        self.bro_a_panel.active = True
        self.bro_b_panel.active = False

    @property
    def active_target(self) -> Target:
        return self._active

    def bind_input_bar(self, bar: "InputBar") -> None:
        self._input_bar = bar

    def switch_target(self) -> None:
        self._active = "b" if self._active == "a" else "a"
        self.bro_a_panel.active = self._active == "a"
        self.bro_b_panel.active = self._active == "b"
        if self._input_bar is not None:
            self._input_bar.refresh_prefix()
            self._input_bar.focus_input()

    def set_target(self, target: Target) -> None:
        if self._active == target:
            return
        self._active = target
        self.bro_a_panel.active = target == "a"
        self.bro_b_panel.active = target == "b"
        if self._input_bar is not None:
            self._input_bar.refresh_prefix()
            self._input_bar.focus_input()

    async def route_user_input(self, text: str) -> None:
        self._last_prompt[self._active] = text

        # Slash commands.
        if text.startswith("/"):
            result = self.commands.handle(text)
            target_panel = self._panel_for(self._active)
            target_panel.append_user_message(text)
            if result.bypass_agent:
                if result.clear_panel:
                    target_panel.clear_log()
                    target_panel.append_system("(cleared)")
                elif result.message:
                    target_panel.append_system(result.message)
                if result.quit:
                    target_panel.app.exit()
                return
            # Non-bypass commands fall through to the agent.
            forced = result.forced_target or self._active
            target_panel = self._panel_for(forced)
            self._stream_to(forced, result.rewritten_prompt or text)
            self.journal.record(forced, "command", text, None)
            return

        target_panel = self._panel_for(self._active)
        target_panel.append_user_message(text)
        self._stream_to(self._active, text)
        self.journal.record(self._active, "user", text, None)

    def _panel_for(self, target: Target):
        return self.bro_a_panel if target == "a" else self.bro_b_panel

    def _agent_for(self, target: Target) -> "OllamaAgent":
        return self.bro_a_agent if target == "a" else self.bro_b_agent

    def _stream_to(self, target: Target, prompt: str) -> None:
        agent = self._agent_for(target)
        panel = self._panel_for(target)
        agent.request(prompt, panel)

    async def retry_last_prompt(self) -> bool:
        text = self._last_prompt.get(self._active)
        if not text:
            other: Target = "b" if self._active == "a" else "a"
            text = self._last_prompt.get(other)
            if not text:
                return False
        await self.route_user_input(text)
        return True

    def cancel_current_turn(self) -> bool:
        active = self._agent_for(self._active)
        other = self._agent_for("b" if self._active == "a" else "a")
        cancelled = False
        if active.cancel_in_flight():
            cancelled = True
        if other.cancel_in_flight():
            cancelled = True
        return cancelled

    def port_cross_talk(self, source: Target) -> None:
        """Copy source pane's last reply into the other pane's input."""
        if source not in ("a", "b"):
            return
        if self._input_bar is None:
            return
        dest: Target = "b" if source == "a" else "a"
        src_panel = self._panel_for(source)
        dst_panel = self._panel_for(dest)

        last = getattr(src_panel, "last_assistant_message", "") or ""
        if not isinstance(last, str):
            try:
                last = str(last)
            except Exception:
                last = ""

        if not last:
            src_label = "Bro A" if source == "a" else "Bro B"
            dst_panel.append_system(
                f"(nothing to port from {src_label} — send it a message first)"
            )
            return

        if self._active != dest:
            self.set_target(dest)

        self._input_bar.set_draft(last)
        src_label = "Bro A" if source == "a" else "Bro B"
        dst_panel.append_system(
            f"(ported {len(last)} chars from {src_label} — edit or Enter to send)"
        )
