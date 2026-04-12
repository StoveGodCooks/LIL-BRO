"""ChallengeBlock -- Rich renderable that frames a quest presentation.

The ``ChallengeManager`` already knows how to append plain lines into a
panel via ``append_system``. ``ChallengeBlock`` is the prettier path:
it builds a single ``rich.panel.Panel`` the caller can hand off to a
``_BasePanel._write_log`` for a framed, colorized quest card.

Kept as a **pure renderable** (not a Textual ``Widget``) so the logic
is easy to unit-test without a running App and so the existing
``RichLog``-backed panels can embed it with zero plumbing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

if TYPE_CHECKING:
    from src_local.quests.models import Quest


# Accent colors match the existing app palette (see src_local/ui/app.tcss).
_ACCENT = "#A8D840"         # bro-lime
_ACCENT_DIM = "#5B7522"
_TITLE_COLOR = "#E8A838"    # gold for contrast
_TASK_COLOR = "#E8E8E8"


def build_challenge_block(quest: "Quest") -> Panel:
    """Return a framed ``rich.panel.Panel`` presenting *quest*.

    Sections rendered (in order):
      * title (bold gold)
      * metadata line -- area / xp / type / concept tags
      * optional story blurb
      * task body (the prompt the user must satisfy)
      * footer with slash hint
    """
    title = Text(quest.title, style=f"bold {_TITLE_COLOR}")

    meta_bits = [
        Text(f"area: {quest.area}", style=_ACCENT_DIM),
        Text(f"xp: {quest.xp}", style=_ACCENT),
        Text(f"type: {quest.type}", style=_ACCENT_DIM),
    ]
    if quest.concept_tags:
        meta_bits.append(
            Text(f"concepts: {', '.join(quest.concept_tags)}", style=_ACCENT_DIM)
        )
    meta = Text("   ").join(meta_bits)

    parts: list = [title, meta]

    if quest.story:
        parts.append(Text(""))
        parts.append(Text(quest.story.strip(), style="italic #B8B8B8"))

    parts.append(Text(""))
    parts.append(Text(quest.task.strip(), style=_TASK_COLOR))

    parts.append(Text(""))
    parts.append(
        Text("use /submit <text> / /hint / /skip", style="dim #888888")
    )

    body = Group(*parts)
    return Panel(
        body,
        title=f"[bold {_ACCENT}]-- QUEST --[/]",
        border_style=_ACCENT,
        padding=(0, 1),
    )


def render_challenge_lines(quest: "Quest") -> list[str]:
    """Flat plaintext fallback -- the same content as ``build_challenge_block``
    but as a list of strings for callers that only have ``append_system``.

    ``ChallengeManager._render_presentation`` uses this shape so tests can
    assert on exact text without dragging a Rich console into the fixture.
    """
    lines: list[str] = [
        f"-- QUEST: {quest.title} --",
        f"area: {quest.area}   xp: {quest.xp}   type: {quest.type}",
    ]
    if quest.concept_tags:
        lines.append(f"concepts: {', '.join(quest.concept_tags)}")
    if quest.story:
        lines.append("")
        lines.append(quest.story.strip())
    lines.append("")
    lines.append(quest.task.strip())
    lines.append("")
    lines.append("use /submit <text> / /hint / /skip")
    return lines
