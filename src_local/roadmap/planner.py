"""Milestone -> tasks prompt helper.

Takes a milestone description and composes a prompt that asks the
planner (Big Bro) to break it into 3-8 concrete tasks. Also includes
a parser that pulls a newline/bullet task list out of a reply so the
executor can commit the tasks to the living map.
"""

from __future__ import annotations

import re

PLAN_TEMPLATE = """You are turning a milestone into a concrete task list.
Do not start coding. Output nothing except the task list.

MILESTONE: {title}
{extra}

Rules:
- 3 to 8 tasks.
- Each task is one imperative line, <= 90 characters.
- Order tasks by dependency (earliest first).
- Do NOT number; use a leading dash.
- No headers, no commentary, no code fences. Just dashes and text.

Example format:
- Draft the session schema
- Write the migration
- Wire the new column into the API

Now produce the task list for the milestone above."""


def build_plan_prompt(milestone_title: str, extra_context: str = "") -> str:
    title = (milestone_title or "").strip() or "(unspecified milestone)"
    extra = ""
    if extra_context.strip():
        extra = f"CONTEXT:\n{extra_context.strip()}\n"
    return PLAN_TEMPLATE.format(title=title, extra=extra)


_TASK_LINE_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(.+?)\s*$")


def parse_task_list(reply: str, *, max_tasks: int = 8) -> list[str]:
    """Extract task titles from a planner reply.

    Accepts dash-led, asterisk-led, numbered, or bullet lines. Strips
    trailing punctuation, collapses whitespace, de-dupes while
    preserving order, and caps at *max_tasks*.
    """
    if not reply:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for line in reply.splitlines():
        m = _TASK_LINE_RE.match(line)
        if not m:
            continue
        title = " ".join(m.group(1).split()).rstrip(".;,")
        if not title:
            continue
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(title)
        if len(out) >= max_tasks:
            break
    return out
