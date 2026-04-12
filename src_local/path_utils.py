"""Project-directory normalization for the ``lilbro`` CLI.

The ``lilbro`` positional argument arrives from whatever shell the user
is running in: cmd.exe, PowerShell, Windows Terminal, WSL bash, macOS
zsh, Linux bash, plus the occasional ``xargs``-ish pipeline. Each one
mangles paths slightly differently, and a mangled path passed through
to both agents produces subtle bugs hours later (wrong cwd, broken file
lookups, MCP cwd mismatch). Normalize once at the edge.

Handles:

- ``~`` and ``~user`` — expanded via ``os.path.expanduser``.
- Mixed / backwards slashes — collapsed to the OS-native separator.
- Wrapping quotes — stripped (``"C:\\foo"`` → ``C:\\foo``).
- Leading / trailing whitespace — stripped (copy-paste hazard).
- ``file://`` URI scheme — stripped; the path portion is used.
- UNC paths (``\\\\server\\share``) — preserved on Windows. ``Path.resolve``
  handles these correctly as long as the double-leading-backslash
  survives the slash-collapsing pass.
- Relative paths — anchored to ``Path.cwd()`` via ``Path.resolve``.
- Symlinks — resolved by ``Path.resolve(strict=False)`` (strict=False so
  a missing target returns a resolved absolute path and error surfaces
  at the ``is_dir()`` check in the caller, not inside resolve).

Returns a ``Path`` so the caller can feed it straight to the CLI
subprocesses; stringify with ``str(path)`` before passing to a
subprocess ``cwd=`` kwarg.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


logger = logging.getLogger("lilbro.path")

# Accepts the common shell copy-paste wrappings: ASCII straight quotes,
# plus Unicode smart quote PAIRS from macOS Finder / Windows Explorer
# "copy as path" which wrap paths in ``\u201c ... \u201d``. Each tuple
# is ``(opening, closing)``; same-char entries cover straight quotes.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ('"', '"'),
    ("'", "'"),
    ("`", "`"),
    ("\u201c", "\u201d"),  # " "
    ("\u2018", "\u2019"),  # ' '
)


def normalize_project_dir(raw: str | None) -> Path:
    """Turn a raw CLI argument into a resolved absolute ``Path``.

    ``raw`` is whatever the user typed after ``lilbro`` (or ``None`` if
    they didn't type anything — in that case we fall back to
    ``Path.cwd()``). The return value is always an *absolute* path, but
    it may not exist yet — the caller is responsible for the
    ``is_dir()`` check + error message.

    The function never raises. Malformed input falls back to
    ``Path.cwd()`` so the app can still boot with a warning instead of
    dying at argparse time.
    """
    if raw is None:
        return Path.cwd()
    try:
        candidate = _normalize(raw)
        if candidate is None:
            return Path.cwd()
        return candidate
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to normalize %r; falling back to cwd: %s", raw, exc)
        return Path.cwd()


def _normalize(raw: str) -> Path | None:
    text = raw.strip()
    if not text:
        return None

    # Strip wrapping quotes. Only strip if both ends match the same
    # pair so we don't mangle a path that legitimately contains a
    # quote character in the middle. Smart-quote pairs are handled
    # explicitly (opening + closing are distinct codepoints).
    for opener, closer in _QUOTE_PAIRS:
        if len(text) >= 2 and text.startswith(opener) and text.endswith(closer):
            text = text[len(opener):-len(closer)].strip()
            break

    # Strip ``file://`` scheme if present. Browsers and some GUI file
    # managers hand out ``file:///C:/Users/alice`` — urlparse + unquote
    # give us back a regular filesystem path.
    if text.lower().startswith("file://"):
        parsed = urlparse(text)
        path_part = unquote(parsed.path)
        # On Windows, urlparse leaves a leading slash before the drive
        # letter: ``/C:/Users/alice``. Strip it so Path() interprets
        # the drive correctly.
        if re.match(r"^/[A-Za-z]:", path_part):
            path_part = path_part[1:]
        text = path_part.strip() or text

    # Preserve a leading UNC marker so we don't turn ``\\server\share``
    # into ``/server/share``. We temporarily swap the marker for a
    # sentinel, collapse the rest of the slashes, then restore it.
    unc_prefix = ""
    if os.name == "nt" and (text.startswith("\\\\") or text.startswith("//")):
        unc_prefix = "\\\\"
        text = text[2:]

    # Collapse any remaining backslashes to forward slashes so Path()
    # gets a consistent input on every platform. Path itself is
    # perfectly happy with forward slashes even on Windows.
    text = text.replace("\\", "/")

    # Expand ~ / ~user before Path(), since Path.expanduser is a no-op
    # on already-constructed absolute paths and it's cleaner to do it
    # once on the string.
    text = os.path.expanduser(text)

    full = unc_prefix + text
    # Strict=False so a non-existent path returns a valid absolute
    # Path and the caller can emit a friendly "not a directory" error
    # instead of the stdlib's FileNotFoundError.
    return Path(full).resolve(strict=False)
