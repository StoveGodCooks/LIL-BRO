"""Simple journal recorder for LIL BRO LOCAL.

Appends timestamped entries to a markdown file so sessions can be
reviewed later.
"""

from __future__ import annotations

import time
from pathlib import Path


class JournalRecorder:
    """Writes session transcripts to disk."""

    def __init__(self, journal_dir: Path, auto_save: bool = True) -> None:
        self._dir = journal_dir
        self._auto_save = auto_save
        self._entries: list[str] = []
        self._path: Path | None = None

        if auto_save:
            self._dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y-%m-%d_%H%M%S")
            self._path = self._dir / f"{stamp}_local_session.md"
            self._write_header()

    @property
    def current_path(self) -> Path | None:
        return self._path

    def _write_header(self) -> None:
        if self._path is None:
            return
        header = (
            f"# LIL BRO LOCAL Session — {time.strftime('%Y-%m-%d %H:%M')}\n\n"
            "---\n\n"
        )
        try:
            self._path.write_text(header, encoding="utf-8")
        except OSError:
            pass

    def record(
        self,
        target: str,
        kind: str,
        user_text: str,
        response: str | None,
    ) -> None:
        stamp = time.strftime("%H:%M:%S")
        entry = f"### [{stamp}] {target} ({kind})\n\n{user_text}\n\n"
        if response:
            entry += f"**Response:**\n\n{response}\n\n"
        entry += "---\n\n"
        self._entries.append(entry)

        if self._auto_save and self._path is not None:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(entry)
            except OSError:
                pass
