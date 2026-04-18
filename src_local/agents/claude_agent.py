"""Claude Code CLI connector for LIL BRO LOCAL.

Spawns the `claude` CLI in bidirectional stream-json mode so context
lives inside the long-lived process. Role-agnostic: the same class can
drive either the Big Bro pane or the Lil Bro pane — the user assigns
which connector powers which bro in config.yaml / first-run setup.

Event shapes (claude 2.x):
  {"type":"system","subtype":"init","session_id":"...",...}
  {"type":"stream_event","event":{"type":"content_block_delta",
      "delta":{"type":"text_delta","text":"..."}}, ...}
  {"type":"stream_event","event":{"type":"content_block_start",
      "content_block":{"type":"tool_use","name":"...","input":{...}}},...}
  {"type":"assistant","message":{...}}
  {"type":"result","subtype":"success","duration_ms":...,"total_cost_usd":...}
  {"type":"rate_limit_event","rate_limit_info":{...}}

No API keys. Auth is handled by the user's Claude Max / Pro subscription
via `claude auth login` (same flow the CLI already uses standalone).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re as _re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src_local.agents.base import (
    ACTIVITY_CHECK_SECONDS,
    AgentProcess,
    safe_readline,
)

logger = logging.getLogger("lilbro-local.claude")

_STDERR_NOISE = (
    "DeprecationWarning",
    "ResourceWarning",
    "RuntimeWarning",
)
_ANSI_RE = _re.compile(r"\x1B\[[0-9;]*[A-Za-z]")

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel


_WRITE_TOOLS = frozenset(
    {"Write", "Edit", "MultiEdit", "NotebookEdit", "Update", "Create"}
)

# ---------------------------------------------------------------------------
# Project session persistence
# ---------------------------------------------------------------------------
# Session IDs are keyed by (cwd, role) and stored under
# ~/.lilbro-local/sessions/.  Auto-save/load only happens when the cwd is in
# the user's recent-projects list — ad-hoc directories always start fresh.

_SESSIONS_DIR = Path.home() / ".lilbro-local" / "sessions"


def _project_session_file(cwd: str, role: str) -> Path:
    import hashlib
    key = hashlib.md5(cwd.encode()).hexdigest()[:12]
    return _SESSIONS_DIR / f"{key}_{role}.session"


def _is_known_project(cwd: str) -> bool:
    """True if cwd is in the user's recent-projects list."""
    try:
        from src_local.ui.project_switcher import load_recent_projects
        abs_cwd = str(Path(cwd).resolve())
        return abs_cwd in load_recent_projects()
    except Exception:  # noqa: BLE001
        return False


def _load_project_session(cwd: str, role: str) -> str | None:
    """Return the saved session ID for this project+role, or None."""
    try:
        f = _project_session_file(cwd, role)
        if f.exists():
            return f.read_text(encoding="utf-8").strip() or None
    except Exception:  # noqa: BLE001
        pass
    return None


def _save_project_session(cwd: str, role: str, session_id: str) -> None:
    """Persist the session ID for this project+role."""
    try:
        f = _project_session_file(cwd, role)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(session_id, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _delete_project_session(cwd: str, role: str) -> None:
    """Remove the persisted session (called by /reset)."""
    try:
        _project_session_file(cwd, role).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass

_FILE_TOOLS: dict[str, str] = {
    "Read": "Read",
    "Write": "Write",
    "Edit": "Edit",
    "MultiEdit": "MultiEdit",
    "NotebookRead": "Read",
    "NotebookEdit": "Edit",
    "Update": "Update",
    "Create": "Create",
    "Grep": "Grep",
    "Glob": "Glob",
    "Bash": "Bash",
    "Task": "Task",
    "WebSearch": "Search",
    "WebFetch": "Fetch",
}


def _short_path(path: str) -> str:
    """Return a display-friendly path: last two components, max ~50 chars."""
    from pathlib import PurePosixPath, PureWindowsPath
    try:
        p = PureWindowsPath(path) if "\\" in path else PurePosixPath(path)
        parts = p.parts
        if len(parts) > 2:
            short = f".../{p.parent.name}/{p.name}"
        else:
            short = str(p)
        return short[:60]
    except Exception:
        return path[:60]


def _build_tool_detail(name: str, path: str, inp: dict) -> str:
    """Build the expandable body for a tool-call Collapsible."""
    if name in ("Read", "NotebookRead"):
        try:
            from pathlib import Path
            content = Path(path).read_text(encoding="utf-8", errors="replace")
            if len(content) > 4000:
                content = content[:4000] + f"\n... [{len(content) - 4000} chars truncated]"
            return content
        except Exception:
            return f"(could not read: {path})"

    if name in ("Edit", "NotebookEdit"):
        import difflib
        old = inp.get("old_string", "") or ""
        new = inp.get("new_string", "") or ""
        lines = list(difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile="before", tofile="after", n=3,
        ))
        return "".join(lines) if lines else "(no diff)"

    if name == "MultiEdit":
        import difflib
        from pathlib import PureWindowsPath, PurePosixPath
        parts = []
        for edit in (inp.get("edits") or []):
            if not isinstance(edit, dict):
                continue
            old = edit.get("old_string", "") or ""
            new = edit.get("new_string", "") or ""
            ep = edit.get("file_path") or path
            lines = list(difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"before {_short_path(ep)}",
                tofile=f"after {_short_path(ep)}",
                n=2,
            ))
            if lines:
                parts.append("".join(lines))
        return "\n".join(parts) or "(no changes)"

    if name == "Bash":
        cmd = inp.get("command", inp.get("cmd", ""))
        return f"$ {cmd}"

    if name in ("Write", "Create", "Update"):
        content = inp.get("content", "") or inp.get("new_content", "") or ""
        if content:
            if len(content) > 3000:
                content = content[:3000] + f"\n... [{len(content) - 3000} chars truncated]"
            return content
        return "(no content)"

    import json as _json
    try:
        return _json.dumps(inp, indent=2, ensure_ascii=False)[:2000]
    except Exception:
        return str(inp)[:2000]


STARTUP_GRACE_SECONDS = 0.5
RESTART_COOLDOWN_SECONDS = 30.0
MAX_RESTART_ATTEMPTS_IN_WINDOW = 3
RESTART_WINDOW_SECONDS = 300.0


def build_sibling_briefing(
    *,
    role: str,
    sibling_name: str,
    sibling_backend: str,
    write_access: bool,
) -> str:
    """Assemble the --append-system-prompt briefing for this connector.

    Role-aware and backend-aware so the same Claude connector can be
    assigned to either pane. The user decides which backend drives
    which bro; the briefing reflects whatever they picked rather than
    assuming Claude is always the senior developer.
    """
    pane_name = "Big Bro" if role == "big" else "Lil Bro"
    sibling_pane = "Lil Bro" if role == "big" else "Big Bro"
    perms = (
        "You can read, write, and edit files in the project directory."
        if write_access
        else "You are in READ-ONLY mode — you can inspect files but must "
        "not write or edit anything. If the user wants a change made, "
        "describe what to do and let them invoke the other pane."
    )
    return (
        f"You are running inside LIL BRO, a dual-agent coding TUI. You are "
        f"'{pane_name}'. {perms}\n\n"
        f"You are paired with '{sibling_pane}' — a separate agent powered by "
        f"{sibling_backend}. Cross-talk between panes is user-mediated: the "
        f"user ports messages with Ctrl+B and Ctrl+C. You never call "
        f"{sibling_pane} directly.\n\n"
        f"Stay focused on the actual coding work. Be concise. The user is "
        f"watching your output stream live in a terminal pane.\n\n"
        f"Note: there is a file called SESSION.md in the project directory "
        f"where LIL BRO streams append-only breadcrumbs of what each pane is "
        f"doing. You can read SESSION.md to see what {sibling_pane} is up to "
        f"in real time. You don't need to write to it — LIL BRO does that "
        f"automatically."
    )


class ClaudeAgent(AgentProcess):
    """Persistent `claude` CLI wrapper. Role-agnostic by design.

    Instantiated with ``role="big"`` or ``role="lil"`` and a sibling
    backend name so the system-prompt briefing is accurate for whichever
    pane this instance is driving.
    """

    def __init__(
        self,
        *,
        role: str,
        display_name: str,
        cwd: str | None = None,
        model: str | None = None,
        write_access: bool = True,
        sibling_name: str = "the other pane",
        sibling_backend: str = "another model",
    ) -> None:
        super().__init__()
        if role not in ("big", "lil"):
            raise ValueError(f"role must be 'big' or 'lil', got {role!r}")
        self.role = role
        self.DISPLAY_NAME = display_name
        self.RESTART_KEY = role  # /restart big | /restart lil
        self.display_name = display_name
        self._cwd = str(cwd) if cwd else os.getcwd()
        self._configured_model = model or None
        self._write_access = write_access
        self._sibling_name = sibling_name
        self._sibling_backend = sibling_backend

        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None
        self._turn_id: int = 0
        self._cancelled_turns: set[int] = set()
        self._restart_count: int = 0
        self._restart_attempts_in_window: int = 0
        self._restart_window_started_at: float = 0.0
        self._restart_frozen: bool = False
        self._turn_done = asyncio.Event()
        self._turn_done.set()
        self._current_panel: "_BasePanel | None" = None
        self._session_id: str | None = None
        # Preserved across stop()/start() so we can pass --resume on restart.
        # Cleared only by reset_thread() (explicit /reset from user).
        self._resume_session_id: str | None = None
        self._model: str | None = None
        self._last_start_time: float = 0.0
        self._stopping = False
        self._crashed = False
        self._announced_ready = False
        self._quiet_mode = False
        self._slow_mode_delay: float = 0.0

    # -----------------------------------------------------------------
    # Public knobs
    # -----------------------------------------------------------------

    def set_write_access(self, enabled: bool) -> None:
        """Toggle write access. Takes effect on next restart()."""
        self._write_access = bool(enabled)

    def set_configured_model(self, model: str | None) -> None:
        """Update the model used on the NEXT spawn. Call restart() to apply."""
        self._configured_model = model or None

    def set_sibling(self, *, sibling_name: str, sibling_backend: str) -> None:
        """Update sibling metadata. Takes effect on next restart()."""
        self._sibling_name = sibling_name
        self._sibling_backend = sibling_backend

    def set_bros_log(self, path: Path) -> None:  # noqa: ARG002
        """No-op for parity with OllamaAgent — Phase 1 cross-talk is
        moving to SESSION.md and this connector already references it
        via the system-prompt briefing."""
        return

    def send_intro(self, panel) -> None:
        """Post the YERRR intro banner. Matches OllamaAgent's surface so
        the app can call it on any backend without type-checking."""
        from src_local.agents.phrases import BIG_BRO_INTRO, LIL_BRO_INTRO
        if "Big" in self.display_name:
            panel.append_intro(BIG_BRO_INTRO)
        else:
            panel.append_intro(LIL_BRO_INTRO)

    def update_system_prompt(self, prompt: str) -> None:  # noqa: ARG002
        """No-op — ClaudeAgent builds its role briefing from the sibling
        context on every subprocess restart. ``set_write_access`` already
        triggers a restart, so /bunkbed works without this."""
        return

    def set_resume_session(self, session_id: str) -> None:
        """Tell this agent to resume a specific session on next start.

        Used by project-mode auto-restore and the /resume command.
        """
        self._resume_session_id = session_id.strip() or None

    def reset_thread(self) -> None:
        """Clear conversation state so the next turn starts fresh.
        Clears both the live session ID and the resume key, and removes
        any persisted project session file."""
        self._session_id = None
        self._resume_session_id = None
        _delete_project_session(self._cwd, self.role)

    def set_slow_mode(self, delay_seconds: float) -> None:
        self._slow_mode_delay = max(0.0, float(delay_seconds))

    def set_quiet_mode(self, quiet: bool) -> None:
        self._quiet_mode = bool(quiet)

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def model(self) -> str | None:
        # ``_model`` is populated only after the CLI emits session_configured.
        # Before that — including at startup / intro time — surface the
        # configured model (or "claude" as a last resort) so the UI doesn't
        # render "model: None".
        return self._model or self._configured_model or "claude"

    @model.setter
    def model(self, value: str | None) -> None:
        """Allow ``agent.model = "..."`` from the /model command handler."""
        self.set_configured_model(value)

    @property
    def restart_count(self) -> int:
        return self._restart_count

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self) -> None:
        claude_path = shutil.which("claude")
        if claude_path is None:
            raise RuntimeError(
                "`claude` CLI not found in PATH. Install Claude Code and "
                "run `claude auth login`."
            )
        briefing = build_sibling_briefing(
            role=self.role,
            sibling_name=self._sibling_name,
            sibling_backend=self._sibling_backend,
            write_access=self._write_access,
        )
        permission_mode = "acceptEdits" if self._write_access else "plan"
        args = [
            claude_path,
            "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode", permission_mode,
            "--append-system-prompt", briefing,
        ]
        if self._configured_model:
            args += ["--model", self._configured_model]
        # Project-mode auto-restore: load a saved session if this cwd is a
        # known project AND no explicit resume was already requested.
        if not self._resume_session_id and _is_known_project(self._cwd):
            saved = _load_project_session(self._cwd, self.role)
            if saved:
                self._resume_session_id = saved
        if self._resume_session_id:
            args += ["--resume", self._resume_session_id]

        self._stopping = False
        self._crashed = False
        self._announced_ready = False
        self._last_start_time = time.monotonic()

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                cwd=self._cwd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=1024 * 1024,
            )
        except OSError as exc:
            raise RuntimeError(f"failed to spawn claude: {exc}") from exc

        self._reader_task = asyncio.create_task(
            self._reader_loop(), name=f"{self.role}-claude-reader"
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_loop(), name=f"{self.role}-claude-stderr"
        )

        await asyncio.sleep(STARTUP_GRACE_SECONDS)
        if self._proc.returncode is not None:
            try:
                assert self._proc.stderr is not None
                err_bytes = await self._proc.stderr.read()
                err = err_bytes.decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001
                err = ""
            raise RuntimeError(
                f"claude exited immediately (rc={self._proc.returncode}). "
                f"{err or 'no stderr — check that claude is logged in (`claude auth login`).'}"
            )

    async def stop(self) -> None:
        self._stopping = True
        self.stop_rss_monitor()
        if self._proc is not None and self._proc.returncode is None:
            try:
                if self._proc.stdin is not None and not self._proc.stdin.is_closing():
                    self._proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                await self._kill_process()
        for task in (self._reader_task, self._stderr_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:  # noqa: BLE001
                    logger.exception("claude task crashed during stop()")
        self._reader_task = None
        self._stderr_task = None
        # Fresh by default — _resume_session_id is only set via
        # set_resume_session() (project mode) or manual /resume command.
        self._session_id = None
        self._model = None
        self._announced_ready = False
        self._proc = None

    async def _kill_process(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.kill()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pass

    async def restart(self, panel: "_BasePanel | None" = None) -> None:
        # Determine if project mode will auto-resume after the restart.
        will_resume = bool(self._resume_session_id) or (
            _is_known_project(self._cwd)
            and bool(_load_project_session(self._cwd, self.role))
        )
        if panel is not None:
            ctx_note = " (project session will resume)" if will_resume else " (fresh session)"
            panel.append_system(
                f"restarting {self.display_name}...{ctx_note}"
            )
        await self.stop()
        await self.start()
        self._restart_count += 1
        self._restart_frozen = False
        self._restart_attempts_in_window = 0
        self._restart_window_started_at = time.monotonic()
        if panel is not None:
            panel.append_system(
                f"{self.display_name} restarted (#{self._restart_count})"
            )

    def clear_history(self) -> None:
        """Claude's context lives in the subprocess; restart to clear."""
        # Caller coordinates with restart(); no-op here so the router can
        # call clear_history() on either backend uniformly.
        return

    # -----------------------------------------------------------------
    # Per-turn send
    # -----------------------------------------------------------------

    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        if self._proc is None or self._proc.returncode is not None:
            if self._restart_frozen:
                panel.append_error(
                    f"{self.display_name} is stuck in a restart loop — run "
                    f"/restart {self.RESTART_KEY} or check `claude auth login`."
                )
                return
            if (
                self._crashed
                and time.monotonic() - self._last_start_time
                > RESTART_COOLDOWN_SECONDS
            ):
                now = time.monotonic()
                if now - self._restart_window_started_at > RESTART_WINDOW_SECONDS:
                    self._restart_window_started_at = now
                    self._restart_attempts_in_window = 0
                self._restart_attempts_in_window += 1
                if self._restart_attempts_in_window > MAX_RESTART_ATTEMPTS_IN_WINDOW:
                    self._restart_frozen = True
                    panel.append_error(
                        f"{self.display_name} crashed "
                        f"{MAX_RESTART_ATTEMPTS_IN_WINDOW}+ times in "
                        f"{int(RESTART_WINDOW_SECONDS)}s — freezing auto-restart. "
                        f"Run /restart {self.RESTART_KEY} or check "
                        f"`claude auth login`."
                    )
                    return
                try:
                    await self.restart(panel)
                except Exception as exc:  # noqa: BLE001
                    panel.append_error(f"restart failed: {exc}")
                    return
            else:
                panel.append_error(
                    f"{self.display_name} is not running. Restart the app "
                    f"or wait and try again."
                )
                return

        if self._proc.stdin is None:
            panel.append_error(f"{self.display_name} stdin is unavailable.")
            return

        self._current_panel = panel
        self._turn_id += 1
        this_turn = self._turn_id
        self._turn_done.clear()
        try:
            panel.set_thinking(True)
        except Exception:  # noqa: BLE001
            pass

        message = {
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }
        line = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            panel.append_error(f"write failed, subprocess is gone: {exc}")
            self._crashed = True
            self._current_panel = None
            self._turn_done.set()
            return

        last_seen = self._last_activity_at
        try:
            while not self._turn_done.is_set():
                try:
                    await asyncio.wait_for(
                        self._turn_done.wait(), timeout=ACTIVITY_CHECK_SECONDS
                    )
                    break
                except asyncio.TimeoutError:
                    current = self._last_activity_at
                    if current != last_seen:
                        last_seen = current
                        continue
                    panel.append_error(
                        f"{self.display_name} went silent for "
                        f"{ACTIVITY_CHECK_SECONDS:.0f}s — killing and restarting."
                    )
                    await self._kill_process()
                    self._crashed = True
                    break
        except asyncio.CancelledError:
            self._cancelled_turns.add(this_turn)
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            self._current_panel = None
            self._turn_done.set()
            raise
        finally:
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            self._current_panel = None

    # -----------------------------------------------------------------
    # Reader loop
    # -----------------------------------------------------------------

    async def _reader_loop(self) -> None:
        assert self._proc is not None
        stdout = self._proc.stdout
        if stdout is None:
            return
        try:
            while True:
                raw, skipped = await safe_readline(stdout)
                if skipped > 0:
                    logger.warning(
                        "%s dropped over-cap stdout line (%d bytes)",
                        self.display_name, skipped,
                    )
                    if self._current_panel is not None:
                        self._current_panel.append_system(
                            f"(dropped oversized stream line — {skipped} bytes "
                            f"exceeded 1 MiB cap)"
                        )
                    continue
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    if self._current_panel is not None:
                        self._current_panel.append_system(
                            f"(unparsed line) {line[:120]}"
                        )
                    continue
                self.note_activity()
                if self._turn_id in self._cancelled_turns:
                    if event.get("type") == "result":
                        self._cancelled_turns.discard(self._turn_id)
                        self._turn_done.set()
                    continue
                self._handle_event(event)
                if self._slow_mode_delay > 0 and self._is_text_delta(event):
                    await asyncio.sleep(self._slow_mode_delay)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._current_panel is not None:
                self._current_panel.append_error(f"reader crashed: {exc}")
            self._turn_done.set()
        finally:
            if not self._stopping:
                self._crashed = True
                if self._current_panel is not None:
                    self._current_panel.append_error(
                        f"{self.display_name} subprocess exited unexpectedly."
                    )
            self._turn_done.set()

    async def _stderr_loop(self) -> None:
        """Drain stderr so the kernel pipe can't fill up and wedge claude."""
        assert self._proc is not None
        stderr = self._proc.stderr
        if stderr is None:
            return
        try:
            while True:
                raw = await stderr.readline()
                if not raw:
                    break
                text = _ANSI_RE.sub(
                    "", raw.decode("utf-8", errors="replace")
                ).rstrip()
                if not text:
                    continue
                if any(n in text for n in _STDERR_NOISE):
                    continue
                if self._current_panel is not None:
                    self._current_panel.append_system(
                        f"(claude stderr) {text[:200]}"
                    )
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("%s stderr loop crashed", self.display_name)

    # -----------------------------------------------------------------
    # Event handling
    # -----------------------------------------------------------------

    @staticmethod
    def _is_text_delta(event: dict[str, Any]) -> bool:
        if event.get("type") != "stream_event":
            return False
        inner = event.get("event", {}) or {}
        if inner.get("type") != "content_block_delta":
            return False
        delta = inner.get("delta", {}) or {}
        return delta.get("type") == "text_delta" and bool(delta.get("text"))

    def _note_tool_use(self, block: dict[str, Any]) -> None:
        name = block.get("name", "")
        label = _FILE_TOOLS.get(name, name)
        inp = block.get("input") or {}
        panel = self._current_panel
        if panel is None:
            return

        path = (
            inp.get("file_path")
            or inp.get("path")
            or inp.get("notebook_path")
            or inp.get("filename")
            or inp.get("pattern")
            or ""
        )
        # Build short summary and expandable detail.
        if path:
            summary = f"{label} {_short_path(str(path))}"
        elif name == "Bash":
            cmd = inp.get("command", inp.get("cmd", ""))
            summary = f"Bash  {str(cmd)[:60]}{'...' if len(str(cmd)) > 60 else ''}"
        else:
            summary = label

        detail = _build_tool_detail(name, str(path), inp)
        try:
            panel.append_tool_call(
                summary,
                detail=detail,
                path=str(path) if path else None,
            )
        except Exception:  # noqa: BLE001
            pass

    def _handle_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        panel = self._current_panel

        if etype == "system":
            if event.get("subtype") == "init":
                self._session_id = event.get("session_id")
                self._model = event.get("model")
                if not self._announced_ready and panel is not None:
                    model = self._model or "?"
                    sid = self._session_id or "?"
                    resumed = (
                        self._resume_session_id is not None
                        and sid.startswith(self._resume_session_id[:8])
                    )
                    ctx_tag = " · resumed" if resumed else ""
                    # Show short tag for readability; full ID on hover
                    panel.append_system(
                        f"· connected · model {model} · session [{sid[:8]}]{ctx_tag}"
                    )
                    self._resume_session_id = None  # consumed
                    self._announced_ready = True
                    # Persist session for project-mode auto-restore
                    if self._session_id and _is_known_project(self._cwd):
                        _save_project_session(self._cwd, self.role, self._session_id)
            return

        if etype == "stream_event":
            inner = event.get("event", {})
            inner_type = inner.get("type")
            if inner_type == "content_block_delta":
                delta = inner.get("delta", {})
                if delta.get("type") == "text_delta" and panel is not None:
                    text = delta.get("text", "")
                    if text:
                        nbytes = len(text.encode("utf-8", errors="replace"))
                        if self.note_stream_bytes(panel, nbytes):
                            panel.append_agent_chunk(text)
                return
            if inner_type == "content_block_start":
                return
            return

        if etype == "assistant":
            content = event.get("message", {}).get("content", [])
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block.get("text", ""))
                elif btype == "tool_use":
                    self._note_tool_use(block)
            if panel is not None:
                joined = "".join(text_parts).strip()
                if joined:
                    panel.mark_assistant_complete(joined)
            return

        if etype == "result":
            subtype = event.get("subtype")
            if subtype == "success" and panel is not None:
                cost = event.get("total_cost_usd")
                dur = event.get("duration_ms")
                if cost is not None and dur is not None:
                    panel.append_system(f"· done in {dur}ms (${cost:.4f})")
            elif subtype and panel is not None:
                panel.append_error(f"turn ended: {subtype}")
            self._turn_done.set()
            return

        if etype == "rate_limit_event":
            info = event.get("rate_limit_info", {})
            status = info.get("status", "unknown")
            if status != "allowed" and panel is not None:
                panel.append_system(f"· rate limit status: {status}")
            return

        if etype in (
            "user", "message_start", "message_delta", "message_stop",
            "content_block_stop", "ping",
        ):
            return

        if panel is not None:
            panel.append_system(f"(unknown event: {etype})")


async def check_claude_health() -> dict[str, Any]:
    """Check whether the `claude` CLI is installed and responsive.

    Returns a dict with:
      - installed: bool — `claude` found on PATH
      - path: str | None — resolved binary location
      - logged_in: bool | None — None if unknown, True/False if detected
      - version: str | None
    """
    result: dict[str, Any] = {
        "installed": False,
        "path": None,
        "logged_in": None,
        "version": None,
    }
    claude_path = shutil.which("claude")
    if claude_path is None:
        return result
    result["installed"] = True
    result["path"] = claude_path
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            return result
        if proc.returncode == 0:
            result["version"] = stdout.decode("utf-8", errors="replace").strip()
    except Exception:  # noqa: BLE001
        pass
    return result
