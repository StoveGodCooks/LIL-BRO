"""Compact character-sheet renderer.

Pulls from any object with a duck-typed shape so tests stay trivial:

- ``profile.level: int``
- ``profile.xp: int``
- ``profile.xp_to_next: int``
- ``profile.skills: dict[str, int]``
- ``profile.badges: list[str]``  (optional)

All fields are optional; missing ones are skipped rather than
raising.  Returns a multi-line string ready to dump into any panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Sheet:
    level: int
    xp: int
    xp_to_next: int
    skills: dict[str, int]
    badges: list[str]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    return getattr(obj, name, default)


def collect(profile: Any) -> Sheet:
    return Sheet(
        level=int(_get(profile, "level", 1) or 1),
        xp=int(_get(profile, "xp", 0) or 0),
        xp_to_next=int(_get(profile, "xp_to_next", 100) or 100),
        skills=dict(_get(profile, "skills", {}) or {}),
        badges=list(_get(profile, "badges", []) or []),
    )


def render(profile: Any, *, persona: str = "auto") -> str:
    """Render a plain-text character sheet."""
    s = collect(profile)
    lines = [
        "CHARACTER SHEET",
        f"  Level {s.level}  ({s.xp}/{s.xp_to_next} XP)",
        f"  Persona: {persona}",
    ]
    if s.skills:
        lines.append("  Skills:")
        # Sort by level desc, then name.
        ordered = sorted(s.skills.items(), key=lambda kv: (-kv[1], kv[0]))
        for name, level in ordered[:12]:
            lines.append(f"    - {name:<18} {level}")
        if len(s.skills) > 12:
            lines.append(f"    ... +{len(s.skills) - 12} more")
    if s.badges:
        lines.append(f"  Badges: {', '.join(s.badges[:8])}")
        if len(s.badges) > 8:
            lines[-1] += f"  (+{len(s.badges) - 8} more)"
    return "\n".join(lines)
