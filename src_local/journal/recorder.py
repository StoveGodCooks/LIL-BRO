"""Markdown journal writer for LIL BRO sessions.

One journal = one session. File lives at
  ~/.lilbro-local/journals/YYYY-MM-DD_HH-MM_<slug>.md

The file is re-written (not appended-to) on every call to `save()` so that
auto-save can happen after each turn without needing to track deltas. Size
stays tiny (a few KB per hour of use), so full rewrites are fine.

Sections rendered in order:
  1. Summary       — date/time, active goal, turn counts, rough cost
  2. Timeline      — every user/agent/command/system entry with timestamp
  3. Issues        — error-kind entries pulled out for quick scanning
  4. Decisions     — marked via journal.note_decision(...) from commands
  5. Concepts      — every /explain topic collected for review
  6. Files Changed — tool-use calls captured from Big Bro (best effort)
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from src_local.journal.session_log import SessionLogStreamer

EntryKind = Literal["user", "agent", "command", "system", "error", "tool", "explain"]


@dataclass
class JournalEntry:
    timestamp: datetime
    target: str  # "big" | "bro" | "system"
    kind: EntryKind
    text: str
    result: str | None = None


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def _slugify(text: str, max_len: int = 32) -> str:
    """Convert arbitrary text to a safe filename slug.

    Uses NFKD normalization to transliterate accented Latin characters
    (e.g. 'é' → 'e') before stripping non-ASCII so that a focus like
    '/focus café auth' produces 'cafe-auth' instead of just 'auth'.
    Emoji and other non-Latin codepoints are dropped gracefully.
    """
    import unicodedata
    nfkd = unicodedata.normalize("NFKD", text.strip().lower())
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c) and ord(c) < 128)
    slug = _SLUG_RE.sub("-", ascii_only).strip("-")
    return slug[:max_len] or "session"


def _escape(text: str) -> str:
    """Minimal escape so Markdown doesn't mis-render agent content."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class JournalRecorder:
    """Session journal — in-memory entries + Markdown writer."""

    entries: list[JournalEntry] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    concepts: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    directory: Path | None = None
    auto_save: bool = True
    focus: str | None = None
    session_started: datetime = field(default_factory=datetime.now)
    session_label: str = "session"
    _path: Path | None = None
    # Optional real-time SESSION.md streamer. When set, every record /
    # note_decision / note_file_changed / set_focus call ALSO appends one
    # line to SESSION.md so Lil Bro can see what's happening live.
    streamer: "SessionLogStreamer | None" = field(default=None, repr=False)

    def attach_streamer(self, streamer: "SessionLogStreamer") -> None:
        self.streamer = streamer

    # -----------------------------------------------------------------
    # Recording
    # -----------------------------------------------------------------

    def record(
        self,
        target: str,
        kind: EntryKind,
        text: str,
        result: str | None = None,
    ) -> None:
        self.entries.append(
            JournalEntry(
                timestamp=datetime.now(),
                target=target,
                kind=kind,
                text=text,
                result=result,
            )
        )
        if kind == "explain":
            topic = text.strip()
            if topic and topic not in self.concepts:
                self.concepts.append(topic)
        if self.streamer is not None:
            # Map journal kinds to SESSION.md kinds.
            session_kind = {
                "user": "USER",
                "agent": "AGENT",
                "command": "CMD",
                "system": "SYS",
                "error": "ERROR",
                "tool": "TOOL",
                "explain": "EXPLAIN",
            }.get(kind, kind.upper())
            self.streamer.log(session_kind, text, target)
        if self.auto_save and self.directory is not None:
            try:
                self.save()
            except OSError:
                pass  # filesystem hiccup — don't crash the UI

    def note_decision(self, text: str) -> None:
        if text and text not in self.decisions:
            self.decisions.append(text)
            if self.streamer is not None:
                self.streamer.log("DECISION", text)

    def note_file_changed(self, path: str) -> None:
        if path and path not in self.files_changed:
            self.files_changed.append(path)
            if self.streamer is not None:
                self.streamer.log("FILE", path, "big")

    def set_focus(self, goal: str | None) -> None:
        self.focus = goal or None
        if goal:
            self.note_decision(f"Focus set: {goal}")
        elif self.streamer is not None:
            self.streamer.log("FOCUS", "(cleared)")

    # -----------------------------------------------------------------
    # Counts / summary
    # -----------------------------------------------------------------

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.entries:
            key = f"{e.target}:{e.kind}"
            out[key] = out.get(key, 0) + 1
        return out

    def issues(self) -> list[JournalEntry]:
        return [e for e in self.entries if e.kind == "error"]

    # -----------------------------------------------------------------
    # Saving
    # -----------------------------------------------------------------

    def _resolve_path(self, name: str | None = None) -> Path:
        assert self.directory is not None, "journal directory not configured"
        if name:
            # User-provided /save <name> — keep the date prefix but swap the slug.
            slug = _slugify(name)
            stamp = self.session_started.strftime("%Y-%m-%d_%H-%M")
            return self.directory / f"{stamp}_{slug}.md"
        if self._path is not None:
            return self._path
        stamp = self.session_started.strftime("%Y-%m-%d_%H-%M")
        slug = _slugify(self.session_label)
        return self.directory / f"{stamp}_{slug}.md"

    def save(self, name: str | None = None) -> Path:
        """Write the journal atomically via tempfile + ``os.replace``.

        Auto-save runs after every recorded entry, so a crash (or Ctrl+C
        mid-write) could otherwise leave a truncated file on disk. The
        atomic-rename pattern guarantees the journal on disk is always
        either the previous fully-written version OR the new fully-written
        version — never a half-flushed one.
        """
        if self.directory is None:
            raise RuntimeError("journal directory not configured")
        self.directory.mkdir(parents=True, exist_ok=True)
        if name:
            self.session_label = name
        path = self._resolve_path(name)
        payload = self.render_markdown()
        # NamedTemporaryFile in the same directory so os.replace is atomic
        # (rename across filesystems would not be).
        tmp_fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp_path = Path(tmp_path_str)
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # fsync can fail on some filesystems (network / WSL)
                    # — the rename still provides atomicity.
                    pass
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup of the tempfile so we don't leak
            # .journal.*.tmp droppings next to the real file.
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            raise
        self._path = path
        return path

    @property
    def current_path(self) -> Path | None:
        return self._path

    # -----------------------------------------------------------------
    # Rendering
    # -----------------------------------------------------------------

    def render_markdown(self) -> str:
        lines: list[str] = []
        started = self.session_started.strftime("%Y-%m-%d %H:%M:%S")
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        duration = datetime.now() - self.session_started
        # round down to seconds for display
        dur_sec = int(duration.total_seconds())
        hh, rem = divmod(dur_sec, 3600)
        mm, ss = divmod(rem, 60)
        dur_str = f"{hh:d}h{mm:02d}m{ss:02d}s" if hh else f"{mm:d}m{ss:02d}s"

        c = self.counts()
        # Entry targets are recorded under the new "big" literal after
        # the Cheese→Big rename, but we fall back to "cheese" so journals
        # loaded from older sessions still render their summary correctly.
        big_bro_user = c.get("big:user", 0) or c.get("cheese:user", 0)
        bro_user = c.get("bro:user", 0)
        big_bro_agent = (
            c.get("big:agent", 0) + c.get("big:tool", 0)
            or c.get("cheese:agent", 0) + c.get("cheese:tool", 0)
        )
        bro_agent = c.get("bro:agent", 0)
        errors = len(self.issues())

        # ---- header / summary ----
        lines.append(f"# LIL BRO session — {started}")
        lines.append("")
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Started:** {started}")
        lines.append(f"- **Last saved:** {now}")
        lines.append(f"- **Duration:** {dur_str}")
        lines.append(f"- **Focus:** {self.focus or '_(none set)_'}")
        lines.append(
            f"- **Turns:** Big Bro {big_bro_user} · Lil Bro {bro_user}"
        )
        lines.append(
            f"- **Replies:** Big Bro {big_bro_agent} · Lil Bro {bro_agent}"
        )
        lines.append(f"- **Issues:** {errors}")
        lines.append(f"- **Concepts learned:** {len(self.concepts)}")
        lines.append(f"- **Files touched:** {len(self.files_changed)}")
        lines.append("")

        # ---- timeline ----
        lines.append("## Timeline")
        lines.append("")
        if not self.entries:
            lines.append("_(no entries yet)_")
            lines.append("")
        else:
            for e in self.entries:
                stamp = e.timestamp.strftime("%H:%M:%S")
                who = self._who(e)
                body = _escape(e.text).strip()
                if not body:
                    continue
                # Multi-line bodies rendered as blockquotes for readability.
                if "\n" in body:
                    quoted = "\n".join(f"> {ln}" for ln in body.split("\n"))
                    lines.append(f"**[{stamp}] {who}**")
                    lines.append("")
                    lines.append(quoted)
                    lines.append("")
                else:
                    lines.append(f"- **[{stamp}] {who}:** {body}")
            lines.append("")

        # ---- issues ----
        lines.append("## Issues")
        lines.append("")
        issues = self.issues()
        if not issues:
            lines.append("_(none)_")
        else:
            for e in issues:
                stamp = e.timestamp.strftime("%H:%M:%S")
                lines.append(f"- **[{stamp}] {e.target}:** {_escape(e.text)}")
        lines.append("")

        # ---- decisions ----
        lines.append("## Decisions")
        lines.append("")
        if not self.decisions:
            lines.append("_(none)_")
        else:
            for d in self.decisions:
                lines.append(f"- {d}")
        lines.append("")

        # ---- concepts ----
        lines.append("## Concepts")
        lines.append("")
        if not self.concepts:
            lines.append("_(none)_")
        else:
            for topic in self.concepts:
                lines.append(f"- {topic}")
        lines.append("")

        # ---- files changed ----
        lines.append("## Files Changed")
        lines.append("")
        if not self.files_changed:
            lines.append("_(none tracked)_")
        else:
            for fp in self.files_changed:
                lines.append(f"- `{fp}`")
        lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _who(entry: JournalEntry) -> str:
        pretty_target = {
            "big": "Big Bro",
            "bro": "Lil Bro",
            "system": "System",
        }.get(entry.target, entry.target)
        if entry.kind == "user":
            return f"you → {pretty_target}"
        if entry.kind == "command":
            return f"you (command) → {pretty_target}"
        if entry.kind == "agent":
            return pretty_target
        if entry.kind == "tool":
            return f"{pretty_target} [tool]"
        if entry.kind == "explain":
            return "/explain"
        if entry.kind == "error":
            return f"{pretty_target} [error]"
        if entry.kind == "system":
            return "system"
        return pretty_target

    # -----------------------------------------------------------------
    # Loading
    # -----------------------------------------------------------------

    def list_journals(self) -> list[Path]:
        if self.directory is None or not self.directory.exists():
            return []
        return sorted(
            self.directory.glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

    def prune_old_journals(self, keep: int) -> list[Path]:
        """Delete older journals, keeping the ``keep`` most recent.

        Called once from ``DualPaneScreen.on_mount`` so day-to-day
        sessions don't have to think about housekeeping. Returns the
        list of paths that were actually removed (for an optional
        system line in the panel).

        Safety:
        * ``keep <= 0`` returns ``[]`` without touching anything.
        * Only files matching ``*.md`` in the journal directory are
          ever considered — we never walk deeper, and we never delete
          the file currently being written to by ``self._path``.
        * Errors on individual unlinks are swallowed — this is
          best-effort cleanup, not a guarantee.
        """
        if keep <= 0 or self.directory is None or not self.directory.exists():
            return []
        all_journals = self.list_journals()
        if len(all_journals) <= keep:
            return []
        to_delete = all_journals[keep:]
        removed: list[Path] = []
        for path in to_delete:
            if self._path is not None and path.resolve() == self._path.resolve():
                # Never delete the active session's file, even if it's
                # somehow sorted into the "old" tail (e.g. clock skew).
                continue
            try:
                path.unlink()
                removed.append(path)
            except OSError:
                continue
        return removed
