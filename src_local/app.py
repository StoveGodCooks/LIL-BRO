"""LIL BRO LOCAL -- main Textual App.

A dual-pane TUI powered by local Ollama models. No API keys, no cloud,
no subscriptions. Just you and your local models.

First-run flow:
  1. Detect hardware (GPU, VRAM, RAM)
  2. Check if Ollama is installed + running
  3. If not -> guide through install (opens browser to ollama.com)
  4. Show model picker with 3B / 7B / 14B quick-pull buttons
  5. Pull selected model with progress bar
  6. Launch dual-pane screen

Usage:
    lilbro-local                          # first-run wizard
    lilbro-local --model qwen2.5-coder:7b # skip wizard, use this model
    lilbro-local --url http://host:11434  # custom Ollama URL
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import Screen
from textual.timer import Timer

from src_local.agents.ollama_agent import (
    OllamaAgent,
    CODER_SYSTEM_PROMPT,
    HELPER_SYSTEM_PROMPT,
)
from src_local.agents.ollama_install import stop_ollama_serve
from src_local.commands.handler import CommandHandler
from src_local.config import load_config
from src_local.vram import detect_vram_mb, calculate_context_windows
from src_local.journal.recorder import JournalRecorder
from src_local.journal.session_log import SessionLogStreamer
from src_local.router import Router
from src_local.rpg.badges import check_badges
from src_local.rpg.player import PlayerProfile
from src_local.rpg.skills import SkillTracker
from src_local.rpg.challenge import ChallengeManager
from src_local.rpg.teach_mode import TeachMode
from src_local.quests.state import CampaignState
from src_local.ui.compose_screen import ComposeScreen
from src_local.ui.debug_overlay import DebugOverlay, debug_overlay_enabled
from src_local.ui.first_run import FirstRunScreen
from src_local.ui.help_screen import HelpScreen
from src_local.ui.settings_screen import SettingsScreen
from src_local.ui.input_bar import InputBar
from src_local.ui.notes_screen import NotesScreen
from src_local.ui.panels import BigBroPanel, LilBroPanel
from src_local.ui.search_screen import SearchScreen
from src_local.ui.status_bar import StatusBar


logger = logging.getLogger("lilbro-local")

# State file -- remembers the model the user picked so we don't show
# the wizard on every launch.
STATE_FILE = Path.home() / ".lilbro-local" / "state.json"


def _setup_debug_log() -> Path | None:
    """Wire up a rotating debug log when LILBRO_DEBUG=1 is set.

    Writes to ``~/.lilbro-local/debug.log`` with 5 MB rotation + two backups.
    """
    if not os.environ.get("LILBRO_DEBUG"):
        return None
    try:
        log_dir = Path.home() / ".lilbro-local"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "debug.log"
        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(name)s %(levelname)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root = logging.getLogger("lilbro")
        level_str = os.environ.get("LILBRO_DEBUG_LEVEL", "DEBUG").upper()
        level = getattr(logging, level_str, logging.DEBUG)
        root.setLevel(level)
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(handler)
        root.info("---- LIL BRO LOCAL debug log opened (level=%s) ----", level_str)
        return log_path
    except Exception:  # noqa: BLE001
        return None


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
    """Main working screen -- two panes + status bar + input bar."""

    BINDINGS = [
        # Tab is NOT priority -- InputBar's command palette needs to
        # intercept it while visible so Tab can complete a slash command.
        Binding("tab", "switch_target", "Switch"),
        # Port hotkeys: Ctrl+C = send Big Bro's last reply -> Lil Bro's input,
        # Ctrl+B = send Lil Bro's last reply -> Big Bro's input.
        Binding("ctrl+c", "port_from_big", "Big->Lil", priority=True),
        Binding("ctrl+b", "port_from_bro", "Lil->Big", priority=True),
        Binding("ctrl+q", "quit_app", "Quit", priority=True),
        # Esc cancels the current in-flight turn if one is running.
        Binding("escape", "cancel_turn", "Cancel", show=False),
        Binding("f1", "show_help", "Help"),
        Binding("f2", "show_session", "Session"),
        Binding("f3", "compose_message", "Compose", show=False),
        Binding("ctrl+h", "show_help", "Help", show=False),
        Binding("ctrl+l", "clear_panel", "Clear", show=False),
        Binding("ctrl+y", "copy_last", "Copy", show=False),
        Binding("ctrl+r", "retry_last", "Retry", show=False),
        Binding("ctrl+f", "find_in_panel", "Find", show=False),
        Binding("ctrl+w", "toggle_wrap", "Wrap", show=False),
        Binding("ctrl+shift+d", "toggle_debug_overlay", "Debug", show=False),
        Binding("ctrl+n", "open_notes", "Notes", show=False),
        Binding("ctrl+shift+t", "toggle_teach_mode", "Teach", show=False),
        Binding("ctrl+shift+m", "show_campaign_map", "Campaign", show=False),
        # Panel resize -- Alt chord dodges the Ctrl+Left/Right word-jump
        # in the input field.
        Binding("alt+left", "shrink_big", "Shrink Big Bro", show=False),
        Binding("alt+right", "grow_big", "Grow Big Bro", show=False),
        Binding("alt+0", "reset_split", "Reset Split", show=False),
        Binding("up", "scroll_up", "Scroll Up", show=False),
        Binding("down", "scroll_down", "Scroll Down", show=False),
        Binding("pageup", "page_up", "Page Up", show=False),
        Binding("pagedown", "page_down", "Page Down", show=False),
    ]

    def __init__(
        self,
        router: Router,
        big_bro_agent: OllamaAgent,
        lil_bro_agent: OllamaAgent,
        status_bar: StatusBar,
        config,
        journal: JournalRecorder,
        session_log: SessionLogStreamer,
        player_profile: PlayerProfile,
        skill_tracker: SkillTracker,
        campaign_state: CampaignState,
        challenge_manager: ChallengeManager,
        teach_mode: TeachMode,
        world=None,
        quest_cache: dict | None = None,
        debug_overlay: DebugOverlay | None = None,
        keybindings: dict | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._router = router
        self._big_bro_agent = big_bro_agent
        self._lil_bro_agent = lil_bro_agent
        self._status_bar = status_bar
        self._config = config
        self._journal = journal
        self._session_log = session_log
        self.player_profile = player_profile
        self.skill_tracker = skill_tracker
        self.campaign_state = campaign_state
        self.challenge_manager = challenge_manager
        self.teach_mode = teach_mode
        self.world = world
        self._quest_cache: dict[str, object] = quest_cache or {}
        self._debug_overlay = debug_overlay or DebugOverlay(id="debug-overlay")
        self._debug_overlay_timer: Timer | None = None
        # Current Big Bro panel share of the horizontal split, in percent.
        self._big_bro_ratio: int = 50
        self._keybindings = keybindings or {}
        # NotesPad -- persists text across open/close for the session.
        self._notes_text: str = ""

    def compose(self) -> ComposeResult:
        with Container(id="main-container"):
            # Lil Bro on the LEFT (green), Big Bro on the RIGHT (orange)
            yield self._router.lil_bro_panel
            yield self._router.big_bro_panel
        yield self._status_bar
        yield InputBar(self._router, id="input-bar")
        # Overlay sits on the "overlay" layer so it paints above the
        # panes without stealing input focus.
        yield self._debug_overlay

    def on_mount(self) -> None:
        # Bind the input bar to the router so prefix/color updates on target switch.
        input_bar = self.query_one("#input-bar", InputBar)
        self._router.bind_input_bar(input_bar)

        # Apply any keybinding overrides from config.
        self._apply_keybinding_overrides()

        # Sweep session_start badges (e.g. "Welcome to LIL BRO")
        try:
            for name in check_badges(self.player_profile, "session_start"):
                self._router.big_bro_panel.append_system(f"Badge unlocked: {name}")
        except Exception:  # noqa: BLE001
            pass

        # Housekeeping: prune ancient journals on startup.
        try:
            journal_keep = getattr(self._config, "journal_keep", 100)
            removed = self._journal.prune_old_journals(journal_keep)
            if removed:
                self._router.big_bro_panel.append_system(
                    f"pruned {len(removed)} old journals "
                    f"(keeping newest {journal_keep})"
                )
        except Exception:  # noqa: BLE001
            pass

        # Kick off the live SESSION.md breadcrumb trail.
        try:
            self._session_log.session_start(
                project_dir=Path.cwd(),
                big_bro_model=self._big_bro_agent.model,
                bro_model=self._lil_bro_agent.model,
            )
        except Exception:  # noqa: BLE001
            pass

        # Beginner welcome banners.
        self._router.big_bro_panel.append_system(
            "Big Bro (Coder) -- reads, writes & edits files"
        )
        self._router.big_bro_panel.append_system(
            "type / for commands  --  Tab switch"
        )
        self._router.big_bro_panel.append_system(
            "F1 help  --  Ctrl+Q quit  --  Alt+Left/Right resize"
        )
        self._router.lil_bro_panel.append_system(
            "Lil Bro (Helper) -- reads files, explains & debugs"
        )
        self._router.lil_bro_panel.append_system(
            "/bunkbed to unlock write access"
        )
        self._router.lil_bro_panel.append_system(
            "Ctrl+C ports Big Bro's reply here"
        )

        model_line = f"model: {self._big_bro_agent.model}"
        self._router.big_bro_panel.append_system(model_line)
        self._router.lil_bro_panel.append_system(model_line)

        self._router.big_bro_panel.append_system("connecting to Ollama...")
        self._router.lil_bro_panel.append_system("connecting to Ollama...")
        self.run_worker(self._start_agents(), exclusive=True)

    async def _start_agents(self) -> None:
        """Spawn both agents in parallel."""
        import asyncio as _asyncio

        async def _start_a() -> None:
            try:
                await self._big_bro_agent.start()
                self._router.big_bro_panel.append_system(
                    f"Big Bro ready -- model: {self._big_bro_agent.model} (coder)"
                )
                self._big_bro_agent.send_intro(self._router.big_bro_panel)
                try:
                    self._session_log.log("STARTUP", "Big Bro started", "big")
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                self._router.big_bro_panel.append_error(f"Big Bro failed to start: {exc}")

        async def _start_b() -> None:
            try:
                await self._lil_bro_agent.start()
                self._router.lil_bro_panel.append_system(
                    f"Lil Bro ready -- model: {self._lil_bro_agent.model} (helper)"
                )
                self._lil_bro_agent.send_intro(self._router.lil_bro_panel)
                try:
                    self._session_log.log("STARTUP", "Lil Bro started", "bro")
                except Exception:  # noqa: BLE001
                    pass
            except Exception as exc:  # noqa: BLE001
                self._router.lil_bro_panel.append_error(f"Lil Bro failed to start: {exc}")

        await _asyncio.gather(_start_a(), _start_b())

        try:
            self.query_one("#user-input").focus()
        except Exception:  # noqa: BLE001
            pass

    async def on_unmount(self) -> None:
        """Stop agents and persist state when the screen is unmounted."""
        # Best-effort journal flush.
        try:
            if self._journal.directory is not None and self._journal.entries:
                self._journal.save()
        except Exception:  # noqa: BLE001
            pass
        # Persist RPG profile.
        try:
            self.player_profile.save()
        except Exception:  # noqa: BLE001
            pass
        # Persist campaign state.
        try:
            self.campaign_state.save()
        except Exception:  # noqa: BLE001
            pass
        # Close session log.
        try:
            self._session_log.session_end("dual pane unmounted")
        except Exception:  # noqa: BLE001
            pass
        # Stop agents.
        try:
            await self._big_bro_agent.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            await self._lil_bro_agent.stop()
        except Exception:  # noqa: BLE001
            pass

    # -- Keybinding overrides -----------------------------------------------

    _REBINDABLE: dict[str, str] = {
        "notes":            "open_notes",
        "compose":          "compose_message",
        "help":             "show_help",
        "find":             "find_in_panel",
        "wrap":             "toggle_wrap",
        "clear_panel":      "clear_panel",
        "copy_last":        "copy_last",
        "retry":            "retry_last",
        "port_from_big":      "port_from_big",
        "port_from_bro":      "port_from_bro",
        "debug_overlay":    "toggle_debug_overlay",
    }

    def _apply_keybinding_overrides(self) -> None:
        """Bind any user-configured key overrides from config."""
        for cfg_name, key in self._keybindings.items():
            action = self._REBINDABLE.get(cfg_name)
            if action is None:
                continue
            if key:
                try:
                    self.bind(key, action, show=False)
                except Exception:  # noqa: BLE001
                    pass

    # -- Resize anti-stutter ------------------------------------------------

    def on_resize(self, event: events.Resize) -> None:
        """Freeze auto_scroll on both panels during a terminal resize."""
        from textual.widgets import RichLog
        logs = self.query(RichLog)
        for log in logs:
            log.auto_scroll = False
        self.call_after_refresh(self._restore_auto_scroll)

    def _restore_auto_scroll(self) -> None:
        from textual.widgets import RichLog
        for log in self.query(RichLog):
            log.auto_scroll = True

    # -- Navigation ----------------------------------------------------------

    def action_switch_target(self) -> None:
        self._router.switch_target()

    def action_cancel_turn(self) -> None:
        cancelled = self._router.cancel_current_turn()
        if not cancelled:
            self._active_panel().append_system("(nothing to cancel)")

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_retry_last(self) -> None:
        """Ctrl+R -- re-send the most recent prompt to the active target."""

        async def _run() -> None:
            ok = await self._router.retry_last_prompt()
            if not ok:
                self._active_panel().append_system(
                    "(nothing to retry -- send a message first)"
                )

        self.run_worker(_run(), exclusive=False)

    def action_port_from_big(self) -> None:
        self._safe_port("big")

    def action_port_from_bro(self) -> None:
        self._safe_port("bro")

    def _safe_port(self, source: str) -> None:
        """Run ``router.port_cross_talk`` without ever crashing the TUI."""
        try:
            self._router.port_cross_talk(source)
        except Exception as exc:  # noqa: BLE001
            import traceback as _tb
            logging.getLogger("lilbro.port").error(
                "port_cross_talk(%s) crashed:\n%s",
                source,
                _tb.format_exc(),
            )
            try:
                panel = self._active_panel()
                panel.append_error(f"port failed: {exc.__class__.__name__}: {exc}")
            except Exception:  # noqa: BLE001
                pass

    # -- Help, Session, Compose, Settings ------------------------------------

    def action_show_help(self) -> None:
        self.app.push_screen(HelpScreen())

    def action_show_settings(self) -> None:
        """Open the settings modal and handle model-switch results."""

        def _on_settings_dismiss(result) -> None:
            if result is None:
                return
            who, new_model = result
            if who == "big":
                self._big_bro_agent.model = new_model
                panel = self._router.big_bro_panel
            else:
                self._lil_bro_agent.model = new_model
                panel = self._router.lil_bro_panel
            if panel is not None:
                panel.append_system(f"model switched to {new_model}")
            # Persist to state file so the choice survives restarts.
            state = _load_state()
            state["active_model"] = self._big_bro_agent.model
            _save_state(state)

        self.app.push_screen(
            SettingsScreen(
                self._config,
                big_bro_agent=self._big_bro_agent,
                lil_bro_agent=self._lil_bro_agent,
            ),
            callback=_on_settings_dismiss,
        )

    def action_show_session(self) -> None:
        self.run_worker(self._router.route_user_input("/session"), exclusive=False)

    def action_compose_message(self) -> None:
        """F3 -- open the multi-line compose modal."""

        def _handle(result: str | None) -> None:
            if result is None:
                return
            self.run_worker(
                self._router.route_user_input(result), exclusive=False
            )

        target = self._router.active_target
        label = "Big Bro" if target == "big" else "Lil Bro"
        prefill = self._router.take_compose_prefill() or ""
        self.app.push_screen(
            ComposeScreen(initial_text=prefill, target_label=label),
            _handle,
        )

    # -- Wrap, Find, Notes ---------------------------------------------------

    def action_toggle_wrap(self) -> None:
        """Ctrl+W -- toggle soft word-wrap on the active panel's log."""
        panel = self._active_panel()
        wrapped = panel.toggle_wrap()
        panel.append_system(f"(word wrap {'on' if wrapped else 'off'})")

    def action_find_in_panel(self) -> None:
        """Ctrl+F -- open the scrollback search modal on the active panel."""
        panel = self._active_panel()
        label = "Big Bro" if self._router.active_target == "big" else "Lil Bro"
        self.app.push_screen(SearchScreen(panel=panel, panel_label=label))

    def action_open_notes(self) -> None:
        """Ctrl+N -- open the NotesPad scratchpad modal."""
        def _on_close(text: str | None) -> None:
            if text is not None:
                self._notes_text = text

        self.app.push_screen(NotesScreen(initial_text=self._notes_text), _on_close)

    def action_port_to_notes(self) -> None:
        """Port the active panel's last reply into the NotesPad."""
        panel = self._active_panel()
        last = getattr(panel, "_last_assistant_message", "") or ""
        if not last:
            panel.append_system("(nothing to port -- no agent reply yet)")
            return
        self._notes_text = (self._notes_text + "\n\n" + last).lstrip()
        panel.append_system("(reply copied to Notes -- Ctrl+N to open)")

    # -- Teach mode, Campaign ------------------------------------------------

    def action_toggle_teach_mode(self) -> None:
        """Ctrl+Shift+T -- flip inline TeachMode on/off."""
        try:
            now_on = self.teach_mode.toggle()
        except Exception:  # noqa: BLE001
            return
        panel = self._active_panel()
        panel.append_system(f"teach mode: {'on' if now_on else 'off'}")

    def action_show_campaign_map(self) -> None:
        """Ctrl+Shift+M / /campaign -- open the CampaignMapScreen modal."""
        if self.world is None or self.campaign_state is None:
            panel = self._active_panel()
            panel.append_system("(campaign not loaded)")
            return
        try:
            from src_local.ui.campaign_map import CampaignMapScreen
        except Exception:  # noqa: BLE001
            return

        def _on_pick(quest: object) -> None:
            try:
                self.challenge_manager.start(quest, self._active_panel())
            except Exception:  # noqa: BLE001
                pass

        self.app.push_screen(
            CampaignMapScreen(
                self.world,
                self.campaign_state,
                on_select=_on_pick,
                quest_lookup=lambda qid: self._quest_cache.get(qid),
            )
        )

    def action_flash_level_up(self) -> None:
        """Pulse the active panel green for ~800ms on level up."""
        try:
            panel = self._active_panel()
        except Exception:  # noqa: BLE001
            return
        try:
            panel.add_class("level-up-flash")
        except Exception:  # noqa: BLE001
            return

        def _clear() -> None:
            try:
                panel.remove_class("level-up-flash")
            except Exception:  # noqa: BLE001
                pass

        try:
            self.set_timer(0.8, _clear)
        except Exception:  # noqa: BLE001
            _clear()

    # -- Debug overlay -------------------------------------------------------

    def action_toggle_debug_overlay(self) -> None:
        """Ctrl+Shift+D -- flip the debug overlay's visibility."""
        if not debug_overlay_enabled():
            return
        try:
            now_visible = self._debug_overlay.toggle()
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("lilbro.debug_overlay").error(
                "debug overlay toggle failed: %s", exc
            )
            return
        if now_visible:
            self._debug_overlay.refresh_snapshot()
            if self._debug_overlay_timer is None:
                self._debug_overlay_timer = self.set_interval(
                    1.0, self._debug_overlay.refresh_snapshot
                )
        else:
            if self._debug_overlay_timer is not None:
                try:
                    self._debug_overlay_timer.stop()
                except Exception:  # noqa: BLE001
                    pass
                self._debug_overlay_timer = None

    # -- Clear panel ---------------------------------------------------------

    def action_clear_panel(self) -> None:
        """Ctrl+L -- wipe the scrollback of whichever panel is active."""
        panel = self._active_panel()
        panel.clear_log()
        panel.append_system("(cleared)")

    # -- Pane resize ---------------------------------------------------------

    def action_shrink_big(self) -> None:
        self._adjust_split(-5)

    def action_grow_big(self) -> None:
        self._adjust_split(+5)

    def action_reset_split(self) -> None:
        if self._big_bro_ratio == 50:
            return
        self._big_bro_ratio = 50
        self._apply_split()
        self._active_panel().append_system("(split reset -- 50 / 50)")

    def _adjust_split(self, delta: int) -> None:
        new = max(20, min(80, self._big_bro_ratio + delta))
        if new == self._big_bro_ratio:
            return
        self._big_bro_ratio = new
        self._apply_split()
        lil_pct = 100 - new
        self._active_panel().append_system(
            f"(split -- Big Bro {new}% / Lil Bro {lil_pct}%)"
        )

    def _apply_split(self) -> None:
        try:
            a = self._big_bro_ratio
            b = 100 - a
            self._router.big_bro_panel.styles.width = f"{a}fr"
            self._router.lil_bro_panel.styles.width = f"{b}fr"
        except Exception:  # noqa: BLE001
            pass

    # -- Scrollback navigation -----------------------------------------------

    def _active_panel(self):
        return (
            self._router.big_bro_panel
            if self._router.active_target == "big"
            else self._router.lil_bro_panel
        )

    def action_scroll_up(self) -> None:
        self._active_panel().log_widget.scroll_up()

    def action_scroll_down(self) -> None:
        self._active_panel().log_widget.scroll_down()

    def action_page_up(self) -> None:
        self._active_panel().log_widget.scroll_page_up()

    def action_page_down(self) -> None:
        self._active_panel().log_widget.scroll_page_down()

    # -- Click to focus pane -------------------------------------------------

    def on_click(self, event: events.Click) -> None:
        node = event.control
        while node is not None:
            if isinstance(node, BigBroPanel):
                self._router.set_target("big")
                return
            if isinstance(node, LilBroPanel):
                self._router.set_target("bro")
                return
            node = node.parent  # type: ignore[assignment]

    # -- Copy last reply to clipboard ----------------------------------------

    def action_copy_last(self) -> None:
        """Ctrl+Y -- copy active panel's last assistant reply to clipboard."""
        panel = self._active_panel()
        text = panel.last_assistant_message
        if not text:
            panel.append_system("(nothing to copy)")
            return
        self.run_worker(self._copy_to_clipboard(panel, text), exclusive=False)

    async def _copy_to_clipboard(
        self, panel, text: str, label: str = "clipboard"
    ) -> None:
        import asyncio as _asyncio

        if sys.platform == "win32":
            cmd = ["clip.exe"]
        elif sys.platform == "darwin":
            cmd = ["pbcopy"]
        else:
            cmd = ["xclip", "-selection", "clipboard"]
        try:
            proc = await _asyncio.create_subprocess_exec(
                *cmd,
                stdin=_asyncio.subprocess.PIPE,
                stdout=_asyncio.subprocess.DEVNULL,
                stderr=_asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            panel.append_system(f"(copy failed: {cmd[0]} not installed)")
            return
        except Exception as exc:  # noqa: BLE001
            panel.append_system(f"(copy failed: {exc})")
            return
        try:
            _stdout, stderr = await _asyncio.wait_for(
                proc.communicate(input=text.encode("utf-8")),
                timeout=5.0,
            )
        except _asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            panel.append_system("(copy failed: clipboard helper timed out)")
            return
        except Exception as exc:  # noqa: BLE001
            panel.append_system(f"(copy failed: {exc})")
            return
        if proc.returncode != 0:
            err = (stderr or b"").decode("utf-8", errors="replace").strip()
            panel.append_system(f"(copy failed: rc={proc.returncode} {err})")
            return
        if label == "clipboard":
            panel.append_system("(copied to clipboard)")
        else:
            panel.append_system(f"(copied {label} to clipboard)")


class LilBroLocalApp(App):
    """LIL BRO LOCAL -- dual-pane local model TUI."""

    TITLE = "LIL BRO LOCAL"
    CSS_PATH = "ui/app.tcss"

    BINDINGS = [
        # App-level fallback quit for screens that don't override.
        Binding("ctrl+q", "quit", "Quit", show=False),
    ]

    def __init__(
        self,
        model: str | None = None,
        ollama_url: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model_override = model
        self._url_override = ollama_url
        self._selected_model: str | None = None  # Set by first-run wizard.
        self._config = load_config()

    def on_mount(self) -> None:
        base_url = self._url_override or self._config.ollama.base_url

        # Always show the landing page so the user can review
        # hardware / Ollama status and change models before launch.
        state = _load_state()
        if self._model_override:
            self._selected_model = self._model_override
        elif state.get("active_model"):
            self._selected_model = state["active_model"]

        self.push_screen(FirstRunScreen(ollama_url=base_url))

    def open_dual_pane(self) -> None:
        """Build and push the dual-pane screen on top of everything.

        Called by FirstRunScreen.action_continue(). The wizard stays
        in the stack underneath -- it doesn't matter because the
        dual-pane is on top.
        """
        base_url = self._url_override or self._config.ollama.base_url
        state = _load_state()
        model = (
            self._selected_model
            or state.get("active_model")
            or self._config.ollama.model
        )

        # Save model so we skip the wizard next launch.
        state["active_model"] = model
        _save_state(state)

        # -- Resolve context windows -----------------------------------------
        project_dir = Path.cwd()
        cfg_big = self._config.ollama.context_window_big
        cfg_lil = self._config.ollama.context_window_lil

        if cfg_big == "auto" or cfg_lil == "auto":
            vram = detect_vram_mb()
            auto_big, auto_lil, reason = calculate_context_windows(
                vram, model_name=model, base_url=base_url,
            )
            logger.info("VRAM auto-detect: %s", reason)
        else:
            auto_big, auto_lil = 8192, 4096  # unused fallback

        ctx_big = auto_big if cfg_big == "auto" else int(cfg_big)
        ctx_lil = auto_lil if cfg_lil == "auto" else int(cfg_lil)
        logger.info("Context windows: Big Bro %d, Lil Bro %d", ctx_big, ctx_lil)

        # -- Build agents ----------------------------------------------------
        big_bro = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Big Bro",
            system_prompt=CODER_SYSTEM_PROMPT,
            temperature=self._config.ollama.temperature,
            context_window=ctx_big,
            project_dir=project_dir,
            write_access=True,
        )

        lil_bro = OllamaAgent(
            base_url=base_url,
            model=model,
            display_name="Lil Bro",
            system_prompt=HELPER_SYSTEM_PROMPT,
            temperature=self._config.ollama.temperature,
            context_window=ctx_lil,
            project_dir=project_dir,
            write_access=False,
        )

        # -- Build panels + status bar ---------------------------------------
        big_bro_panel = BigBroPanel()
        lil_bro_panel = LilBroPanel()
        status_bar = StatusBar()
        status_bar.set_model(model)
        status_bar.attach_agents(big_bro, lil_bro)

        # -- Cross-talk: each bro can see the other's last reply -------------
        big_bro.set_sibling(lil_bro_panel, "Lil Bro", agent=lil_bro)
        lil_bro.set_sibling(big_bro_panel, "Big Bro", agent=big_bro)

        # -- Shared workspace log: bros passively see each other's activity --
        bros_log_path = project_dir / "BROS_LOG.md"
        big_bro.set_bros_log(bros_log_path)
        lil_bro.set_bros_log(bros_log_path)

        # -- Journal + session log -------------------------------------------
        journal = JournalRecorder(
            directory=self._config.journal_dir,
            auto_save=self._config.journal_auto_save,
        )

        session_log = SessionLogStreamer(path=Path.cwd() / "SESSION.md")
        journal.attach_streamer(session_log)

        # -- RPG profile + skill tracker -------------------------------------
        try:
            player_profile = PlayerProfile.load()
            player_profile.total_sessions += 1
            skill_tracker = SkillTracker(player_profile)
            player_profile.note_event("session_start")
            try:
                from datetime import datetime
                player_profile.touch_streak(datetime.now())
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            player_profile = PlayerProfile()
            skill_tracker = SkillTracker(player_profile)

        # Attach profile to status bar for XP strip.
        try:
            status_bar.attach_profile(player_profile)
        except Exception:  # noqa: BLE001
            pass

        # -- Campaign state + challenge manager + teach mode -----------------
        try:
            campaign_state = CampaignState.load()
        except Exception:  # noqa: BLE001
            campaign_state = CampaignState()

        world = None
        try:
            from src_local.quests.loader import load_world
            world_path = Path(__file__).parent / "quests" / "content" / "world.yaml"
            if world_path.exists():
                world = load_world(world_path)
        except Exception:  # noqa: BLE001
            world = None

        challenge_manager = ChallengeManager(
            player_profile,
            skill_tracker,
            campaign_state,
            world=world,
        )

        # Build a simple in-memory quest lookup by id if the world loaded.
        quest_cache: dict[str, object] = {}
        if world is not None:
            try:
                from src_local.quests.loader import load_quest
                content_dir = Path(__file__).parent / "quests" / "content"
                for area in world.areas:
                    for qid in list(area.quest_ids) + (
                        [area.boss_quest_id] if area.boss_quest_id else []
                    ):
                        qpath = content_dir / area.id / f"{qid}.yaml"
                        if qpath.exists():
                            try:
                                quest_cache[qid] = load_quest(qpath)
                            except Exception:  # noqa: BLE001
                                pass
            except Exception:  # noqa: BLE001
                pass

        teach_mode = TeachMode(
            manager=challenge_manager,
            quest_lookup=lambda qid: quest_cache.get(qid),
        )

        # -- Command handler -------------------------------------------------
        commands = CommandHandler(
            journal=journal,
            status_bar=status_bar,
            big_bro=big_bro,
            lil_bro=lil_bro,
            big_bro_panel=big_bro_panel,
            lil_bro_panel=lil_bro_panel,
            project_dir=Path.cwd(),
            player_profile=player_profile,
            skill_tracker=skill_tracker,
            challenge_manager=challenge_manager,
            teach_mode=teach_mode,
            world=world,
            campaign_state=campaign_state,
            config=self._config,
        )

        # -- Router ----------------------------------------------------------
        router = Router(
            big_bro_panel=big_bro_panel,
            lil_bro_panel=lil_bro_panel,
            big_bro_agent=big_bro,
            lil_bro_agent=lil_bro,
            commands=commands,
            journal=journal,
            status_bar=status_bar,
        )

        # -- Debug overlay ---------------------------------------------------
        debug_overlay = DebugOverlay(id="debug-overlay")
        debug_overlay.attach_agents(big_bro, lil_bro)

        # -- Build and push DualPaneScreen -----------------------------------
        main_screen = DualPaneScreen(
            router=router,
            big_bro_agent=big_bro,
            lil_bro_agent=lil_bro,
            status_bar=status_bar,
            config=self._config,
            journal=journal,
            session_log=session_log,
            player_profile=player_profile,
            skill_tracker=skill_tracker,
            campaign_state=campaign_state,
            challenge_manager=challenge_manager,
            teach_mode=teach_mode,
            world=world,
            quest_cache=quest_cache,
            debug_overlay=debug_overlay,
        )

        self.push_screen(main_screen)


def main() -> None:
    # Redirect __pycache__ folders into one hidden dir so users don't
    # see bytecode scattered across every package folder.
    import sys as _sys
    _cache_dir = Path.home() / ".lilbro-local" / ".pycache"
    _cache_dir.mkdir(parents=True, exist_ok=True)
    _sys.pycache_prefix = str(_cache_dir)

    parser = argparse.ArgumentParser(
        description="LIL BRO LOCAL -- dual-pane local model TUI"
    )
    parser.add_argument(
        "--model", "-m",
        help="Ollama model tag (e.g. qwen2.5-coder:3b). Pre-selects this model.",
    )
    parser.add_argument(
        "--url", "-u",
        help="Ollama base URL (default: http://127.0.0.1:11434)",
    )
    parser.add_argument(
        "--wizard", action="store_true",
        help="Clear saved state and show a fresh landing page.",
    )
    args = parser.parse_args()

    # If --wizard is passed, clear the saved state so the model picker shows.
    if args.wizard:
        try:
            STATE_FILE.unlink(missing_ok=True)
        except OSError:
            pass

    log_path = _setup_debug_log()
    if log_path is not None:
        print(f"[lilbro-local] debug log: {log_path}", file=sys.stderr)

    app = LilBroLocalApp(
        model=args.model,
        ollama_url=args.url,
    )
    try:
        app.run()
    finally:
        # Kill the Ollama daemon we started (if any).
        stop_ollama_serve()


if __name__ == "__main__":
    main()
