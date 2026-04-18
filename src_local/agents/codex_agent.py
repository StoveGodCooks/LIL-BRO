"""OpenAI Codex CLI connector for LIL BRO LOCAL.

Spawns `codex mcp-server` once per session and speaks MCP (JSON-RPC 2.0)
over stdio. Role-agnostic: the same class drives either Big Bro or Lil
Bro depending on how the user wires it up in config.

Per-turn flow:
  - First turn  → call the `codex` tool with just a prompt
  - Subsequent  → call `codex-reply` with the stored threadId
  - While a call runs, the server emits `codex/event` notifications
    with streaming deltas (`agent_message_delta`), piped into the panel
    via `append_agent_chunk`.

No API keys. Auth is handled by the user's ChatGPT Plus / Pro
subscription via `codex login`.
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

from src_local.agents.base import AgentProcess, safe_readline

logger = logging.getLogger("lilbro-local.codex")

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel


INIT_TIMEOUT_SECONDS = 10.0
TURN_TIMEOUT_SECONDS = 180.0
RESTART_COOLDOWN_SECONDS = 30.0
PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "lilbro-local"
CLIENT_VERSION = "0.2.0"


def build_sibling_briefing(
    *,
    role: str,
    sibling_name: str,
    sibling_backend: str,
    write_access: bool,
) -> str:
    """Assemble the system-context briefing prepended to Codex's first turn.

    Codex's mcp-server has no dedicated system-prompt slot on tool-call
    args, so we inline this as a prefix on the first turn only. The
    thread carries it forward for every subsequent `codex-reply`.
    """
    pane_name = "Big Bro" if role == "big" else "Lil Bro"
    sibling_pane = "Lil Bro" if role == "big" else "Big Bro"
    perms = (
        "You have workspace-write access — you can inspect, write, and "
        "edit files in the project directory."
        if write_access
        else "Your sandbox is locked to READ-ONLY — you cannot write, "
        "edit, or create files, and you should not try to. Your strengths "
        "are explaining concepts, reviewing code, debugging, and answering "
        "learning questions."
    )
    return (
        f"[SYSTEM CONTEXT — read carefully before responding]\n"
        f"You are running inside LIL BRO, a dual-agent coding TUI. You are "
        f"'{pane_name}'. {perms}\n\n"
        f"You are paired with '{sibling_pane}' — a separate agent powered by "
        f"{sibling_backend}. Cross-talk between panes is user-mediated: the "
        f"user ports messages with Ctrl+B and Ctrl+C. You never call "
        f"{sibling_pane} directly.\n\n"
        f"Stay focused and concise. The user is watching your output stream "
        f"live in a terminal pane.\n\n"
        f"IMPORTANT — SESSION.md breadcrumb file: there is a file called "
        f"SESSION.md in the current project directory. LIL BRO writes "
        f"append-only one-line breadcrumbs to a '## Live Stream' section at "
        f"the bottom of that file IN REAL TIME as each pane does work. If "
        f"the user ever asks 'what's going on' or 'what is {sibling_pane} "
        f"doing', read SESSION.md first (especially the tail of the Live "
        f"Stream section) and summarize from it. Each line looks like: "
        f"`[HH:MM:SS] KIND target: body`.\n\n"
        f"[END SYSTEM CONTEXT — the user's actual request follows]\n\n"
    )


class CodexAgent(AgentProcess):
    """Persistent `codex mcp-server` wrapper. Role-agnostic."""

    def __init__(
        self,
        *,
        role: str,
        display_name: str,
        cwd: str | None = None,
        model: str | None = None,
        write_access: bool = False,
        sibling_name: str = "the other pane",
        sibling_backend: str = "another model",
    ) -> None:
        super().__init__()
        if role not in ("big", "lil"):
            raise ValueError(f"role must be 'big' or 'lil', got {role!r}")
        self.role = role
        self.DISPLAY_NAME = display_name
        self.RESTART_KEY = role
        self.display_name = display_name
        self._cwd = str(cwd) if cwd else os.getcwd()
        self._configured_model = model or None
        self._write_access = write_access
        self._sibling_name = sibling_name
        self._sibling_backend = sibling_backend

        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._stderr_task: asyncio.Task | None = None

        self._request_id = 0
        self._pending: dict[int, asyncio.Future] = {}

        self._current_panel: "_BasePanel | None" = None
        self._turn_done = asyncio.Event()
        self._turn_done.set()

        self._session_id: str | None = None
        self._thread_id: str | None = None
        self._model: str | None = None
        self._server_name: str | None = None
        self._server_version: str | None = None

        self._announced_ready = False
        self._last_start_time: float = 0.0
        self._stopping = False
        self._crashed = False
        self._turn_id: int = 0
        self._cancelled_turns: set[int] = set()
        self._startup_stderr: list[str] = []
        self._restart_count: int = 0
        self._bg_tasks: set[asyncio.Task] = set()

    # -----------------------------------------------------------------
    # Public knobs
    # -----------------------------------------------------------------

    def set_write_access(self, enabled: bool) -> None:
        """Toggle write access. Takes effect on next restart()."""
        self._write_access = bool(enabled)

    def set_configured_model(self, model: str | None) -> None:
        self._configured_model = model or None

    def set_sibling(self, *, sibling_name: str, sibling_backend: str) -> None:
        self._sibling_name = sibling_name
        self._sibling_backend = sibling_backend

    def set_bros_log(self, path: Path) -> None:  # noqa: ARG002
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
        """No-op — CodexAgent builds its role briefing from sibling context
        on every subprocess restart. ``set_write_access`` already triggers
        a restart, so /bunkbed works without this."""
        return

    def set_slow_mode(self, delay_seconds: float) -> None:  # noqa: ARG002
        """No-op — Codex CLI doesn't have a controllable token delay."""
        return

    def set_quiet_mode(self, quiet: bool) -> None:  # noqa: ARG002
        """No-op — quiet mode is an Ollama-specific heartbeat toggle."""
        return

    def reset_thread(self) -> None:
        """Clear current thread so the next turn starts a fresh conversation."""
        self._thread_id = None

    def clear_history(self) -> None:
        """Parity with OllamaAgent — clears thread so context resets."""
        self.reset_thread()

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc is not None else None

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    @property
    def model(self) -> str | None:
        # ``_model`` is populated only after the CLI emits session_configured.
        # Before that — including at startup / intro time — surface the
        # configured model (or "codex" as a last resort) so the UI doesn't
        # render "model: None".
        return self._model or self._configured_model or "codex"

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
        codex_path = shutil.which("codex")
        if codex_path is None:
            raise RuntimeError(
                "`codex` CLI not found in PATH. Install the OpenAI Codex CLI "
                "and run `codex login`."
            )
        sandbox = "workspace-write" if self._write_access else "read-only"
        args = [
            codex_path,
            "mcp-server",
            "-c",
            f'sandbox_mode="{sandbox}"',
        ]
        if self._configured_model:
            args += ["-c", f'model="{self._configured_model}"']

        self._stopping = False
        self._crashed = False
        self._announced_ready = False
        self._thread_id = None
        self._last_start_time = time.monotonic()
        self._request_id = 0
        self._pending.clear()

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
            raise RuntimeError(f"failed to spawn codex mcp-server: {exc}") from exc

        self._reader_task = asyncio.create_task(
            self._reader_loop(), name=f"{self.role}-codex-reader"
        )
        self._stderr_task = asyncio.create_task(
            self._stderr_loop(), name=f"{self.role}-codex-stderr"
        )

        try:
            init_resp = await self._rpc(
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
                timeout=INIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError as exc:
            err = await self._drain_stderr()
            buffered = (
                "\n".join(self._startup_stderr[-20:])
                if self._startup_stderr else ""
            )
            details = (
                err or buffered
                or "Check that codex is logged in (`codex login`)."
            )
            raise RuntimeError(
                f"codex mcp-server did not respond to initialize within "
                f"{INIT_TIMEOUT_SECONDS:.0f}s. {details}"
            ) from exc

        result = (
            (init_resp or {}).get("result", {})
            if isinstance(init_resp, dict) else {}
        )
        server_info = result.get("serverInfo", {})
        self._server_name = server_info.get("name")
        self._server_version = server_info.get("version")

        await self._send_notification("notifications/initialized", {})

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
                    logger.exception("codex task crashed during stop()")
        self._reader_task = None
        self._stderr_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("codex mcp-server stopped"))
        self._pending.clear()
        self._session_id = None
        self._model = None
        self._thread_id = None
        self._announced_ready = False
        self._startup_stderr.clear()
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
        if panel is not None:
            panel.append_system(f"restarting {self.display_name} subprocess...")
        await self.stop()
        await self.start()
        self._restart_count += 1
        if panel is not None:
            panel.append_system(
                f"{self.display_name} restarted (#{self._restart_count})"
            )

    async def _drain_stderr(self) -> str:
        if self._proc is None or self._proc.stderr is None:
            return ""
        try:
            chunk = await asyncio.wait_for(
                self._proc.stderr.read(4096), timeout=0.5
            )
            return chunk.decode("utf-8", errors="replace").strip()
        except Exception:  # noqa: BLE001
            return ""

    # -----------------------------------------------------------------
    # Cancellation
    # -----------------------------------------------------------------

    def cancel_in_flight(self) -> bool:
        """Cancel the in-flight turn AND send MCP ``notifications/cancelled``.

        Base class cancel only stops us from reading new deltas, leaving
        codex happily generating tokens and burning rate-limit budget.
        The notification tells the server to abort too.
        """
        cancelled = super().cancel_in_flight()
        if not cancelled:
            return False
        if not self._pending:
            return True
        pending_id = max(self._pending)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return True
        task = loop.create_task(
            self._send_notification(
                "notifications/cancelled",
                {"requestId": pending_id, "reason": "user cancelled"},
            ),
            name=f"{self.role}-codex-cancel",
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return True

    # -----------------------------------------------------------------
    # Per-turn send
    # -----------------------------------------------------------------

    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        try:
            await self._stream_reply_inner(prompt, panel)
        except asyncio.CancelledError:
            self._cancelled_turns.add(self._turn_id)
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            self._current_panel = None
            try:
                self._turn_done.set()
            except Exception:  # noqa: BLE001
                pass
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("%s crashed on message", self.display_name)
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            panel.append_error(
                f"{self.display_name} crashed on this message: {exc}"
            )
            self._current_panel = None
            try:
                self._turn_done.set()
            except Exception:  # noqa: BLE001
                pass

    async def _stream_reply_inner(
        self, prompt: str, panel: "_BasePanel"
    ) -> None:
        if self._proc is None or self._proc.returncode is not None:
            if (
                self._crashed
                and time.monotonic() - self._last_start_time
                > RESTART_COOLDOWN_SECONDS
            ):
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
        self._turn_done.clear()
        try:
            panel.set_thinking(True)
        except Exception:  # noqa: BLE001
            pass

        if self._thread_id is None:
            tool_name = "codex"
            briefing = build_sibling_briefing(
                role=self.role,
                sibling_name=self._sibling_name,
                sibling_backend=self._sibling_backend,
                write_access=self._write_access,
            )
            sandbox = "workspace-write" if self._write_access else "read-only"
            arguments: dict[str, Any] = {
                "prompt": briefing + prompt,
                "sandbox": sandbox,
                "cwd": self._cwd,
            }
        else:
            tool_name = "codex-reply"
            arguments = {"prompt": prompt, "threadId": self._thread_id}

        try:
            resp = await self._rpc(
                "tools/call",
                {"name": tool_name, "arguments": arguments},
                timeout=TURN_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            panel.append_error(
                f"{self.display_name} did not respond within "
                f"{TURN_TIMEOUT_SECONDS:.0f}s — killing and restarting."
            )
            await self._kill_process()
            self._crashed = True
            self._current_panel = None
            self._turn_done.set()
            return
        except RuntimeError as exc:
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            panel.append_error(f"{self.display_name} error: {exc}")
            self._current_panel = None
            self._turn_done.set()
            return
        finally:
            try:
                panel.set_thinking(False)
            except Exception:  # noqa: BLE001
                pass
            self._turn_done.set()

        try:
            result = (resp or {}).get("result", {})
            structured = result.get("structuredContent", {}) or {}
            thread_id = structured.get("threadId")
            content = structured.get("content", "")
            if thread_id:
                self._thread_id = thread_id
            if content:
                panel.mark_assistant_complete(content)
            if content and not self._announced_ready:
                panel.append_agent_chunk(content)
        finally:
            self._current_panel = None

    # -----------------------------------------------------------------
    # Minimal JSON-RPC 2.0 client
    # -----------------------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("codex mcp-server is not running")

        rid = self._next_id()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        msg: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        try:
            await self._write_line(msg)
        except Exception:
            self._pending.pop(rid, None)
            raise
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

    async def _send_notification(
        self, method: str, params: dict[str, Any] | None = None
    ) -> None:
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._write_line(msg)

    async def _write_line(self, msg: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        try:
            self._proc.stdin.write(line)
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as exc:
            self._crashed = True
            raise RuntimeError(
                f"codex mcp-server write failed: {exc}"
            ) from exc

    # -----------------------------------------------------------------
    # Reader loops
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
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    if self._current_panel is not None:
                        self._current_panel.append_system(
                            f"(unparsed line) {line[:120]}"
                        )
                    continue
                self.note_activity()
                self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            if self._current_panel is not None:
                self._current_panel.append_error(f"reader crashed: {exc}")
        finally:
            if not self._stopping:
                self._crashed = True
                if self._current_panel is not None:
                    self._current_panel.append_error(
                        f"{self.display_name} subprocess exited unexpectedly."
                    )
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("codex mcp-server exited"))
            self._pending.clear()
            self._turn_done.set()

    _INTERNAL_NOISE: tuple[str, ...] = (
        "exec_approval",
        "execapprovalresponse",
        "codex_core::tools::router",
        "codex_mcp_server::exec_approval",
        "fullyqualifiederrorid",
        "propertysetternotsupported",
        "propertysetternotsupportedinconstrainedlanguage",
        "rg: regex parse error",
        "unclosed group",
        "turn.rs:",
        "rollout.rs:",
    )
    _ANSI_RE = _re.compile(r"\x1B\[[0-9;]*[A-Za-z]")

    async def _stderr_loop(self) -> None:
        assert self._proc is not None
        stderr = self._proc.stderr
        if stderr is None:
            return
        try:
            while True:
                raw = await stderr.readline()
                if not raw:
                    break
                text = self._ANSI_RE.sub(
                    "", raw.decode("utf-8", errors="replace")
                ).rstrip()
                if not text:
                    continue
                low = text.lower()
                if any(n in low for n in self._INTERNAL_NOISE):
                    continue
                clipped = f"(codex stderr) {text[:200]}"
                if self._current_panel is not None:
                    self._current_panel.append_system(clipped)
                else:
                    self._startup_stderr.append(clipped)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            logger.exception("%s stderr loop crashed", self.display_name)

    # -----------------------------------------------------------------
    # Dispatch
    # -----------------------------------------------------------------

    def _dispatch(self, msg: dict[str, Any]) -> None:
        if "id" in msg and ("result" in msg or "error" in msg):
            rid = msg["id"]
            fut = self._pending.get(rid)
            if fut is not None and not fut.done():
                if "error" in msg:
                    err = msg["error"]
                    err_msg = (
                        err.get("message", "rpc error")
                        if isinstance(err, dict) else str(err)
                    )
                    fut.set_exception(RuntimeError(err_msg))
                else:
                    fut.set_result(msg)
            return

        if "id" in msg and "method" in msg:
            self._handle_server_request(msg)
            return

        method = msg.get("method")
        if method == "codex/event":
            params = msg.get("params", {}) or {}
            self._handle_codex_event(params.get("msg", {}) or {})
            return
        if method and method.startswith("notifications/"):
            return
        if method and self._current_panel is not None:
            self._current_panel.append_system(f"(unknown notif: {method})")

    def _handle_server_request(self, msg: dict[str, Any]) -> None:
        """Reply to server-initiated requests.

        When ``write_access`` is False, elicitation / permission escalations
        are declined automatically to enforce the read-only contract. When
        True, we still auto-deny for now — Phase 1 doesn't wire up an
        interactive approval modal yet.
        """
        rid = msg["id"]
        method = msg.get("method", "")
        panel = self._current_panel

        reply: dict[str, Any]
        if method == "elicitation/create":
            params = msg.get("params", {}) or {}
            schema = params.get("requestedSchema", {}) or {}
            props = schema.get("properties", {}) or {}
            required = schema.get("required") or list(props.keys())
            content: dict[str, Any] = {}
            for field_name in required:
                prop = props.get(field_name, {}) or {}
                enum_vals = prop.get("enum")
                if enum_vals:
                    preferred = (
                        "d", "deny", "denied", "n", "no",
                        "r", "reject", "rejected", "cancel",
                    )
                    match = next(
                        (
                            v for v in enum_vals
                            if isinstance(v, str) and v.lower() in preferred
                        ),
                        None,
                    )
                    content[field_name] = (
                        match if match is not None else enum_vals[-1]
                    )
                elif prop.get("type") == "boolean":
                    content[field_name] = False
                elif prop.get("type") in ("integer", "number"):
                    content[field_name] = 0
                else:
                    content[field_name] = "deny"
            reply = {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"action": "accept", "content": content},
            }
            if panel is not None:
                panel.append_system(
                    "· declined permission escalation (auto-deny)"
                )
        elif method == "sampling/createMessage":
            reply = {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": "sampling not supported"},
            }
        elif method == "roots/list":
            reply = {
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "roots": [
                        {"uri": f"file:///{self._cwd}", "name": "cwd"}
                    ]
                },
            }
        else:
            reply = {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {
                    "code": -32601,
                    "message": f"method {method} not implemented",
                },
            }

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(
            self._safe_write(reply),
            name=f"{self.role}-codex-reply-{rid}",
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _safe_write(self, reply: dict[str, Any]) -> None:
        try:
            await self._write_line(reply)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "%s failed to write reply: %s", self.display_name, exc
            )
            self._crashed = True

    def _handle_codex_event(self, ev: dict[str, Any]) -> None:
        if self._turn_id in self._cancelled_turns:
            if ev.get("type") == "task_complete":
                self._cancelled_turns.discard(self._turn_id)
            return
        etype = ev.get("type")
        panel = self._current_panel

        if etype == "session_configured":
            self._session_id = ev.get("session_id")
            self._model = ev.get("model")
            if not self._announced_ready and panel is not None:
                sid = (self._session_id or "?")[:8]
                model = self._model or "?"
                sandbox = (ev.get("sandbox_policy") or {}).get("type", "?")
                panel.append_system(
                    f"· connected · model {model} · session {sid} · "
                    f"sandbox {sandbox}"
                )
                self._announced_ready = True
            return

        if etype == "agent_message_delta":
            delta = ev.get("delta", "")
            if delta and panel is not None:
                nbytes = len(delta.encode("utf-8", errors="replace"))
                if self.note_stream_bytes(panel, nbytes):
                    panel.append_agent_chunk(delta)
            return

        if etype == "task_complete":
            return

        if etype == "error":
            if panel is not None:
                message = ev.get("message") or ev.get("error") or "(error)"
                panel.append_error(f"{self.display_name}: {message}")
            return

        if etype == "token_count":
            rl = ev.get("rate_limits") or {}
            primary = rl.get("primary") or {}
            used = primary.get("used_percent")
            if used is not None and used >= 80.0 and panel is not None:
                panel.append_system(f"· rate limit {used:.0f}% used")
            return


async def check_codex_health() -> dict[str, Any]:
    """Check whether the `codex` CLI is installed and responsive.

    Returns a dict with: installed, path, version.
    """
    result: dict[str, Any] = {
        "installed": False,
        "path": None,
        "version": None,
    }
    codex_path = shutil.which("codex")
    if codex_path is None:
        return result
    result["installed"] = True
    result["path"] = codex_path
    try:
        proc = await asyncio.create_subprocess_exec(
            codex_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(), timeout=5.0
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass
            return result
        if proc.returncode == 0:
            result["version"] = stdout.decode(
                "utf-8", errors="replace"
            ).strip()
    except Exception:  # noqa: BLE001
        pass
    return result
