"""Real-time SESSION.md streamer — 'what's happening right now' for Lil Bro.

Unlike `JournalRecorder` (which rewrites a full Markdown journal file in
`~/.lilbro-local/journals/` on every save), this streamer append-only writes
one-line breadcrumbs to `<project_dir>/SESSION.md` as events happen.

Design goals:
  * **Live**: flush on every call, no buffering. Lil Bro can `tail -f`
    or just re-read the file at any moment and see the last N events.
  * **One line per event**: easy to grep, easy for Lil Bro to scan.
  * **Safe**: filesystem errors are swallowed so a flaky disk can't
    crash the TUI. Thread-locked so async tasks can't interleave writes.
  * **Non-destructive**: only appends to a dedicated `## Live Stream`
    section. Leaves any existing human-written content alone.
  * **Truncated bodies**: multi-line agent replies are collapsed to a
    single line and capped at 240 chars so a 5KB reply doesn't flood
    the file.

Format::

    [HH:MM:SS] KIND[ target]: body

The target is optional — if present it is separated from the kind by a
single space. ``log(kind, body, target)`` produces these exact lines.

Examples::

    [14:32:10] SESSION: project=C:\\Users\\beebo\\code\\foo big=opus bro=default
    [14:32:14] USER big: /plan add a login screen
    [14:32:14] CMD big: /plan add a login screen
    [14:32:22] AGENT big: I'll outline the steps first. **Goal** Ship a login...
    [14:32:41] TOOL big: Write src/ui/login.py
    [14:32:55] AGENT bro: **Correctness** This looks mostly right but the bcrypt...
    [14:33:02] ERROR big: turn timed out
    [14:33:05] DECISION: switched Big Bro model → claude-opus-4-5

Note: ``src/ui/panels.py::ingest_session_dump_for_port`` parses agent
replies out of this file using the ``AGENT <target>: <body>`` shape —
any change to the kind name for agent replies MUST be mirrored there
or the port-from-replay feature will silently stop working.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src_local.journal.session_lock import file_lock, instance_id


LIVE_MARKER = "## Live Stream"
LIVE_HEADER = (
    "\n\n---\n\n"
    "## Live Stream\n"
    "<!-- append-only real-time breadcrumbs written by LIL BRO; newest at bottom -->\n"
    "<!-- Lil Bro: read this section to see what Big Bro is doing right now -->\n"
    "\n"
)

# Max length of the truncated body per line.
MAX_BODY = 240


@dataclass
class SessionLogStreamer:
    """Append-only streamer for `<project_dir>/SESSION.md`.

    Use `log(kind, body, target)` for single events and `session_start`
    / `session_end` for banner lines.
    """

    path: Path
    enabled: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_error: str | None = field(default=None, repr=False)
    # P12-6 — multi-instance coordination. Set to True on the first
    # write after we detect that another LIL BRO instance is holding
    # the OS-level lock on the file; the next write emits an
    # ``[pid-N] instance N joined`` header so a human reading
    # ``SESSION.md`` can see the interleave boundary. Reset on process
    # exit via ``session_end``.
    _contention_announced: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self._ensure_marker()

    # -----------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------

    def _ensure_marker(self) -> None:
        """Create SESSION.md or append the Live Stream section if missing."""
        if not self.enabled:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self.path.exists():
                self.path.write_text(
                    "# SESSION LOG\n\n"
                    "> Real-time breadcrumbs. Updated as work progresses.\n"
                    "> Lil Bro reads this to see what's happening right now.\n"
                    + LIVE_HEADER,
                    encoding="utf-8",
                )
                return
            text = self.path.read_text(encoding="utf-8")
            if LIVE_MARKER not in text:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(LIVE_HEADER)
        except OSError as exc:
            self._last_error = str(exc)
            self.enabled = False  # stop trying to write

    @staticmethod
    def _clean(text: str) -> str:
        if not text:
            return ""
        # Collapse whitespace + newlines so every event is a single line.
        flat = " ".join((text or "").split())
        if len(flat) > MAX_BODY:
            flat = flat[: MAX_BODY - 3] + "..."
        return flat

    def _write(self, line: str) -> None:
        if not self.enabled:
            return
        # Double-locking: a thread lock to serialize writes inside this
        # process, and an OS-level advisory file lock (``file_lock``)
        # to serialize writes across sibling LIL BRO processes pointed
        # at the same project directory. The file lock is best-effort
        # — if another instance is holding it for longer than
        # ``LOCK_WAIT_SECONDS``, we proceed without it rather than
        # hanging the UI. A one-shot header line marks the contention
        # boundary so ``SESSION.md`` still reads cleanly.
        with self._lock:
            try:
                with file_lock(self.path) as lock:
                    if not lock.acquired and not self._contention_announced:
                        try:
                            stamp = datetime.now().strftime("%H:%M:%S")
                            lock.handle.write(
                                f"[{stamp}] INSTANCE: {instance_id()} joined "
                                f"(another LIL BRO is writing here too)\n"
                            )
                        except OSError:
                            pass
                        self._contention_announced = True
                    lock.handle.write(line)
                    lock.handle.flush()
            except OSError as exc:
                self._last_error = str(exc)
                self.enabled = False

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def log(self, kind: str, body: str = "", target: str | None = None) -> None:
        """Append one breadcrumb line. Safe to call from any thread."""
        stamp = datetime.now().strftime("%H:%M:%S")
        tgt = f" {target}" if target else ""
        line = f"[{stamp}] {kind}{tgt}: {self._clean(body)}\n"
        self._write(line)

    def session_start(
        self,
        project_dir: Path,
        big_bro_model: str | None,
        bro_model: str | None,
    ) -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        banner = (
            f"\n[{stamp}] ---- LIL BRO session start ----\n"
            f"[{stamp}] SESSION: project={project_dir} "
            f"big={big_bro_model or '(default)'} "
            f"bro={bro_model or '(default)'}\n"
        )
        self._write(banner)

    def session_end(self, reason: str = "clean exit") -> None:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._write(f"[{stamp}] SESSION: end — {reason}\n\n")
