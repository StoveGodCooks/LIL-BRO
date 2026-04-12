"""Cross-platform advisory file lock for ``SESSION.md``.

P12-6 — lets two or more LIL BRO instances share the same project
directory without clobbering each other's breadcrumb writes.

This module exposes a single context manager, ``file_lock(path)``,
that opens ``path`` in append mode for writing AND separately opens a
sidecar ``<path>.lock`` file in binary mode purely to hold an OS-level
advisory lock. The sidecar approach sidesteps a pile of Windows
awkwardness:

* ``msvcrt.locking`` is a mandatory byte-range lock (unlike fcntl's
  advisory mode), and text-mode file objects do not give us stable
  byte offsets because of newline translation. Locking a dedicated
  lock file in binary mode eliminates both concerns.
* Unix ``fcntl.flock`` works fine on any file descriptor, so the
  sidecar approach is also the simplest cross-platform code.

If another process is holding the sidecar lock we wait up to
``LOCK_WAIT_SECONDS`` seconds in ``LOCK_POLL_SECONDS`` increments,
then give up and proceed WITHOUT the lock. Better to briefly overlap
a write than to hang the TUI on a crashed-instance lock file.

Callers that care about whether the lock was acquired can read
``acquired`` off the yielded value; it's False when we fell through.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from pathlib import Path
from typing import IO, Iterator

# How long we're willing to wait for another instance to release the
# lock before proceeding anyway. Tuned for "two shells open in the
# same repo" — we want to serialize normal writes but never hang the
# UI. 250 ms is enough time for the other instance to finish a typical
# single-line append.
LOCK_WAIT_SECONDS = 0.25
LOCK_POLL_SECONDS = 0.01


class _LockResult:
    """What ``file_lock`` yields: the opened handle + whether we got the lock."""

    __slots__ = ("handle", "acquired")

    def __init__(self, handle: IO[str], acquired: bool) -> None:
        self.handle = handle
        self.acquired = acquired


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _try_lock_fd(fh) -> bool:
    """Non-blocking exclusive lock on a binary file descriptor."""
    if sys.platform == "win32":
        try:
            import msvcrt  # type: ignore[import-not-found]

            # Sidecar file is opened in binary mode at position 0;
            # locking 1 byte at the current (zero) position is
            # straightforward and doesn't interfere with any writes
            # (we never write to the sidecar).
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        try:
            import fcntl  # type: ignore[import-not-found]

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ImportError):
            return False


def _unlock_fd(fh) -> None:
    if sys.platform == "win32":
        try:
            import msvcrt  # type: ignore[import-not-found]

            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        try:
            import fcntl  # type: ignore[import-not-found]

            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except (OSError, ImportError):
            pass


@contextlib.contextmanager
def file_lock(path: Path, mode: str = "a") -> Iterator[_LockResult]:
    """Open ``path`` in ``mode`` and try to acquire an exclusive lock
    on the sibling ``<path>.lock`` sidecar.

    The yielded ``_LockResult`` holds the TEXT file handle for the
    target file (ready for ``.write(str)``) and an ``acquired`` flag
    that tells the caller whether the sidecar lock was actually taken.
    On context exit the lock is released (if held) and both handles
    are closed.

    Example::

        with file_lock(session_md) as lock:
            lock.handle.write(line)
            lock.handle.flush()
            if not lock.acquired:
                logger.debug("session lock contention — writing unsynced")
    """
    sidecar = _sidecar_path(path)
    lock_fh = None
    text_fh = None
    try:
        # Sidecar must exist before we can lock it; touch it in binary
        # append mode so concurrent instances don't race on its
        # creation.
        try:
            lock_fh = open(sidecar, "ab+")
        except OSError:
            # Can't even create the sidecar (read-only dir, etc.).
            # Fall through to acquired=False and just open the real
            # file for writing.
            lock_fh = None

        acquired = False
        if lock_fh is not None:
            deadline = time.monotonic() + LOCK_WAIT_SECONDS
            acquired = _try_lock_fd(lock_fh)
            while not acquired and time.monotonic() < deadline:
                time.sleep(LOCK_POLL_SECONDS)
                acquired = _try_lock_fd(lock_fh)

        text_fh = open(path, mode, encoding="utf-8")
        try:
            yield _LockResult(text_fh, acquired)
        finally:
            if lock_fh is not None and acquired:
                _unlock_fd(lock_fh)
    finally:
        for fh in (text_fh, lock_fh):
            if fh is not None:
                try:
                    fh.close()
                except OSError:
                    pass


def instance_id() -> str:
    """Stable per-process instance id for contention headers.

    Uses ``os.getpid()`` — unique per OS process, stable for the whole
    run. The streamer prepends this to the first write after a
    contention-detected event so the SESSION.md tail can be visually
    segmented by instance.
    """
    return f"pid-{os.getpid()}"
