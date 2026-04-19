"""Lesson delivery — pick the best backend for explanations.

The heuristic is simple and auditable:

1. If the user has explicitly pinned a teaching backend in config,
   honor it.
2. Otherwise prefer Claude > Codex > Ollama for concept-style
   lessons. Both Claude and Codex tend to produce sharper teaching
   prose than a 7B local model, and we route to whichever is
   available.
3. Fall back to Ollama when no cloud backend is live, so teach
   mode never breaks offline.

The caller supplies the set of available backends; this module does
no subprocess / network calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Backend = Literal["ollama", "claude", "codex"]

_DEFAULT_PREFERENCE: tuple[Backend, ...] = ("claude", "codex", "ollama")


@dataclass(frozen=True)
class LessonPlan:
    topic: str
    backend: Backend
    prompt: str


def pick_backend(
    available: set[str] | list[str] | tuple[str, ...],
    *,
    pinned: str | None = None,
    preference: tuple[Backend, ...] = _DEFAULT_PREFERENCE,
) -> Backend:
    """Select the lesson backend from *available*.

    - ``pinned``, when provided and available, wins.
    - Otherwise walks *preference* and returns the first hit.
    - If nothing matches, returns ``"ollama"`` (always the offline
      fallback) so callers never get a null.
    """
    avail = {str(x).lower() for x in available}
    if pinned and pinned.lower() in avail:
        return pinned.lower()  # type: ignore[return-value]
    for name in preference:
        if name in avail:
            return name
    return "ollama"


LESSON_TEMPLATE = """You are teaching one topic to a developer.
{difficulty_note}

TOPIC: {topic}

Produce exactly these sections with the headers verbatim, one blank
line between them. No preamble, no closing summary.

**What**
One or two sentences of plain English. Define the term.

**Why**
What problem it solves. Motivation.

**How**
Mechanics. A short snippet is fine if it clarifies.

**Gotcha**
One common mistake or surprise, one or two sentences.

**Next**
One concrete next step the user can try in their own code.

Keep the whole reply under 350 words."""


def build_lesson_prompt(topic: str, difficulty_note: str) -> str:
    t = (topic or "").strip() or "(unspecified)"
    return LESSON_TEMPLATE.format(topic=t, difficulty_note=difficulty_note)


def plan_lesson(
    topic: str,
    available: set[str] | list[str] | tuple[str, ...],
    difficulty_note: str,
    *,
    pinned: str | None = None,
) -> LessonPlan:
    backend = pick_backend(available, pinned=pinned)
    prompt = build_lesson_prompt(topic, difficulty_note)
    return LessonPlan(topic=topic, backend=backend, prompt=prompt)
