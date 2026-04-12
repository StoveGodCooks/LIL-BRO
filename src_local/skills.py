"""Plugin/skill loader for LIL BRO.

Drop a file into ``~/.lilbro-local/skills/`` and it becomes a slash command.

Two skill types
---------------
*.py
    Executed as a subprocess: ``python <skill.py> [args]``.
    stdout is captured and displayed in the active panel.
    stderr is captured and shown as an error if the process exits non-zero.

*.md
    Treated as a prompt template.  The file contents are sent verbatim to
    the currently active agent (Cheese or Bro, whichever is focused).
    Useful for reusable prompt recipes you invoke frequently.

Naming convention
-----------------
``my_skill.py``  →  ``/my_skill`` or ``/my-skill`` (underscores and
hyphens are interchangeable in the command name).

Listing
-------
``/skills``  lists every installed skill with its type and first docstring
line (for .py files) or first non-blank line (for .md files).

Security note
-------------
Skills are arbitrary code run by the user who launched the app.
Only files in ``~/.lilbro-local/skills/`` are eligible — no PATH search,
no relative paths.  The user owns those files.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

SKILLS_DIR = Path.home() / ".lilbro-local" / "skills"

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """``my_skill`` and ``my-skill`` both resolve to the same key."""
    return name.lower().replace("-", "_")


def load_skills() -> dict[str, Path]:
    """Return ``{normalized_name: path}`` for all installed skills."""
    skills: dict[str, Path] = {}
    if not SKILLS_DIR.is_dir():
        return skills
    for path in SKILLS_DIR.iterdir():
        if path.suffix in (".py", ".md") and path.is_file():
            key = _normalize(path.stem)
            skills[key] = path
    return skills


def find_skill(name: str) -> Path | None:
    """Return the skill path for *name*, or None if not installed."""
    return load_skills().get(_normalize(name))


def list_skills() -> list[tuple[str, str, str]]:
    """Return ``[(command, type, description)]`` sorted by command."""
    rows = []
    for key, path in sorted(load_skills().items()):
        cmd = f"/{key.replace('_', '-')}"
        kind = path.suffix.lstrip(".")
        try:
            first = next(
                (
                    ln.strip().lstrip("#").lstrip('"""').strip()
                    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines()
                    if ln.strip() and not ln.strip().startswith("#!")
                ),
                "",
            )
            desc = first[:72]
        except OSError:
            desc = "(unreadable)"
        rows.append((cmd, kind, desc))
    return rows


# ---------------------------------------------------------------------------
# Execution helpers (called from CommandHandler)
# ---------------------------------------------------------------------------

async def run_py_skill(path: Path, args: str, timeout: float = 30.0) -> tuple[str, bool]:
    """Run a .py skill file as a subprocess.

    Returns ``(output, success)``.  *output* is stdout on success,
    stderr on failure.  Never raises.
    """
    argv = [sys.executable, str(path)]
    if args:
        argv += args.split()
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            return f"skill timed out after {timeout:.0f}s", False
        out = stdout_b.decode("utf-8", errors="replace").strip()
        err = stderr_b.decode("utf-8", errors="replace").strip()
        if proc.returncode == 0:
            return out or "(skill produced no output)", True
        return err or f"skill exited with code {proc.returncode}", False
    except OSError as exc:
        return f"skill launch failed: {exc}", False


def read_md_skill(path: Path) -> str:
    """Return the prompt template text from a .md skill file."""
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        return f"(could not read skill: {exc})"
