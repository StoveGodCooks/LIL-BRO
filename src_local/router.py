"""Message routing for LIL BRO LOCAL.

Routes user input to the active agent (Big Bro or Lil Bro). Both are
local Ollama models — no CLI subprocess distinction, no file-write
permissions to enforce.

| Source          | Destinations                     |
|-----------------|----------------------------------|
| User input      | ONE of {Big Bro, Lil Bro}        |
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
    from src_local.ui.panels import BigBroPanel, LilBroPanel
    from src_local.ui.status_bar import StatusBar


Target = Literal["big", "bro"]


class Router:
    """Owns active-target state and dispatches user input."""

    def __init__(
        self,
        big_bro_panel: "BigBroPanel",
        lil_bro_panel: "LilBroPanel",
        big_bro_agent: "OllamaAgent",
        lil_bro_agent: "OllamaAgent",
        commands: "CommandHandler",
        journal: "JournalRecorder",
        status_bar: "StatusBar | None" = None,
    ) -> None:
        self.big_bro_panel = big_bro_panel
        self.lil_bro_panel = lil_bro_panel
        self.big_bro_agent = big_bro_agent
        self.lil_bro_agent = lil_bro_agent
        self.commands = commands
        self.journal = journal
        self.status_bar = status_bar
        self._active: Target = "big"
        self._input_bar: "InputBar | None" = None
        self._last_prompt: dict[Target, str] = {}

        self.big_bro_panel.active = True
        self.lil_bro_panel.active = False
        # When a cross-talk port truncates the message to fit the
        # single-line Input widget (>6000 chars), stash the FULL
        # untruncated text here so the next F3 can pre-fill compose.
        self._pending_compose_prefill: dict[Target, str] = {}

    # ---- active target ----

    @property
    def active_target(self) -> Target:
        return self._active

    def bind_input_bar(self, bar: "InputBar") -> None:
        self._input_bar = bar

    def switch_target(self) -> None:
        self._active = "bro" if self._active == "big" else "big"
        self.big_bro_panel.active = self._active == "big"
        self.lil_bro_panel.active = self._active == "bro"
        if self._input_bar is not None:
            self._input_bar.refresh_prefix()
            self._input_bar.focus_input()

    def set_target(self, target: Target) -> None:
        if self._active == target:
            return
        self._active = target
        self.big_bro_panel.active = target == "big"
        self.lil_bro_panel.active = target == "bro"
        if self._input_bar is not None:
            self._input_bar.refresh_prefix()
            self._input_bar.focus_input()

    # ---- user input routing ----

    async def route_user_input(self, text: str) -> None:
        self._last_prompt[self._active] = text

        # Slash commands always hit the handler first.
        if text.startswith("/"):
            result = self.commands.handle(text)
            target_panel = self._panel_for(self._active)
            target_panel.append_user_message(text)
            # Drain any RPG banners (level-ups, badge unlocks).
            if result.banners:
                forced = result.forced_target or self._active
                banner_panel = self._panel_for(forced)
                for line in result.banners:
                    try:
                        banner_panel.append_system(line)
                    except Exception:  # noqa: BLE001
                        pass
                if any("LEVEL UP" in b for b in result.banners):
                    try:
                        banner_panel.screen.action_flash_level_up()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
            if result.bypass_agent:
                if result.clear_panel:
                    target_panel.clear_log()
                    target_panel.append_system("(cleared)")
                elif result.toggle_wrap:
                    wrapped = target_panel.toggle_wrap()
                    target_panel.append_system(
                        f"(word wrap {'on' if wrapped else 'off'})"
                    )
                elif result.message:
                    target_panel.append_system(result.message)
                    if result.ingest_session_dump:
                        try:
                            target_panel.ingest_session_dump_for_port(result.message)
                        except Exception:  # noqa: BLE001
                            pass
                self.journal.record(self._active, "command", text, result.message)
                if self.status_bar is not None:
                    self.status_bar.set_journal(self.journal.current_path)
                if result.show_help:
                    try:
                        target_panel.screen.action_show_help()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
                if result.show_settings:
                    try:
                        target_panel.screen.action_show_settings()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
                if result.show_campaign_map:
                    try:
                        target_panel.screen.action_show_campaign_map()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
                if result.quit:
                    target_panel.app.exit()
                if result.async_work is not None:
                    try:
                        await result.async_work()
                    except Exception as exc:  # noqa: BLE001
                        target_panel.append_error(f"command follow-up failed: {exc}")
                if result.skill_coro is not None:
                    try:
                        skill_result = await result.skill_coro
                        if skill_result.message:
                            target_panel.append_system(skill_result.message)
                    except Exception as exc:  # noqa: BLE001
                        target_panel.append_error(f"skill failed: {exc}")
                return
            # .md skill prompt — forward directly to the active agent.
            if result.prompt is not None:
                forced = result.forced_target or self._active
                target_panel = self._panel_for(forced)
                self._last_prompt[forced] = text
                self._stream_to(forced, result.prompt)
                self.journal.record(forced, "command", text, None)
                return
            # Non-bypass commands (like /explain, /plan) fall through.
            forced = result.forced_target or self._active
            target_panel = self._panel_for(forced)
            self._last_prompt[forced] = text
            self._stream_to(forced, result.rewritten_prompt or text)
            self.journal.record(forced, "command", text, None)
            return

        target_panel = self._panel_for(self._active)
        target_panel.append_user_message(text)
        self._stream_to(self._active, text)
        self.journal.record(self._active, "user", text, None)
        # Award baseline XP for a user turn.
        tracker = getattr(self.commands, "skill_tracker", None)
        if tracker is not None:
            try:
                report = tracker.tag("user_turn")
                banners = report.banners()
                for line in banners:
                    target_panel.append_system(line)
                if any("LEVEL UP" in b for b in banners):
                    try:
                        target_panel.screen.action_flash_level_up()  # type: ignore[attr-defined]
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
        if self.status_bar is not None:
            self.status_bar.set_journal(self.journal.current_path)

    def _panel_for(self, target: Target):
        return self.big_bro_panel if target == "big" else self.lil_bro_panel

    def _agent_for(self, target: Target) -> "OllamaAgent":
        return self.big_bro_agent if target == "big" else self.lil_bro_agent

    def _stream_to(self, target: Target, prompt: str) -> None:
        agent = self._agent_for(target)
        panel = self._panel_for(target)
        agent.request(prompt, panel)

    # ---- retry ----

    async def retry_last_prompt(self) -> bool:
        text = self._last_prompt.get(self._active)
        if not text:
            other: Target = "bro" if self._active == "big" else "big"
            text = self._last_prompt.get(other)
            if not text:
                return False
        await self.route_user_input(text)
        return True

    # ---- cancel ----

    def cancel_current_turn(self) -> bool:
        active = self._agent_for(self._active)
        other = self._agent_for("bro" if self._active == "big" else "big")
        cancelled = False
        if active.cancel_in_flight():
            cancelled = True
        if other.cancel_in_flight():
            cancelled = True
        return cancelled

    # ---- cross-talk port ----

    def port_cross_talk(self, source: Target) -> None:
        """Take the source pane's last assistant message and draft it
        into the OTHER pane's input bar. Never auto-sends."""
        if source not in ("big", "bro"):
            return
        if self._input_bar is None:
            return
        dest: Target = "bro" if source == "big" else "big"
        src_panel = self._panel_for(source)
        dst_panel = self._panel_for(dest)

        raw = getattr(src_panel, "last_assistant_message", "") or ""
        if not isinstance(raw, str):
            try:
                raw = str(raw)
            except Exception:  # noqa: BLE001
                raw = ""
        last = raw

        if not last:
            src_label = "Big Bro" if source == "big" else "Lil Bro"
            dst_panel.append_system(
                f"(nothing to port from {src_label} — send it a message first)"
            )
            return

        # Hide any open command palette before retargeting.
        try:
            self._input_bar._hide_palette()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

        if self._active != dest:
            self.set_target(dest)

        self._input_bar.set_draft(last)

        src_label = "Big Bro" if source == "big" else "Lil Bro"
        char_count = len(last)
        dst_panel.append_system(
            f"(ported {char_count} chars from {src_label} — edit or Enter to send)"
        )
        if char_count > 6000:
            self._pending_compose_prefill[dest] = last
            dst_panel.append_system(
                "(message was truncated to 6000 chars — press F3 to open full text in compose)"
            )

    def take_compose_prefill(self, target: "Target | None" = None) -> str | None:
        """Pop any pending compose prefill for target (default: active)."""
        key: "Target" = target if target is not None else self._active
        return self._pending_compose_prefill.pop(key, None)
