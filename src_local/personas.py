"""Persona system: three advisory lenses for every interaction.

Personas are **not** modes -- they are persistent lenses that can be
addressed by name (``/mom``, ``/dad``, ``/grandma``) or auto-selected
based on the prompt and current app state.

| Persona | Owns                                   | Tone             |
|---------|----------------------------------------|------------------|
| Mom     | organization, accountability, momentum | warm, persistent |
| Dad     | execution, efficiency, hard truths     | terse, direct    |
| Grandma | memory, patterns, big picture          | patient, long    |

Selection is a small keyword classifier with a few state-aware
overrides (teaching -> Grandma, active roadmap drift -> Mom).
The classifier is deliberately boring so it's easy to reason about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

PersonaName = Literal["mom", "dad", "grandma"]
PERSONAS: tuple[PersonaName, ...] = ("mom", "dad", "grandma")


@dataclass(frozen=True)
class Persona:
    name: PersonaName
    owns: str
    tone: str
    system_prefix: str


MOM = Persona(
    name="mom",
    owns="organization, accountability, momentum",
    tone="warm, persistent",
    system_prefix=(
        "You are MOM: the organization-and-accountability lens. "
        "Warm but persistent. When you speak, check in on progress, "
        "flag drift from the current milestone, and nudge the user "
        "back toward the plan. Keep replies short unless asked."
    ),
)
DAD = Persona(
    name="dad",
    owns="execution, efficiency, hard truths",
    tone="terse, direct",
    system_prefix=(
        "You are DAD: the execution-and-efficiency lens. "
        "Terse and direct. Cut to the hard truth. Favor the simplest "
        "thing that works. Call out scope creep and over-engineering. "
        "No softening fluff."
    ),
)
GRANDMA = Persona(
    name="grandma",
    owns="memory, patterns, big picture",
    tone="patient, long-view",
    system_prefix=(
        "You are GRANDMA: the memory-and-big-picture lens. "
        "Patient and long-view. Connect today's question to prior "
        "patterns and decisions. Surface repeated mistakes gently. "
        "It's OK to take a paragraph when the context warrants it."
    ),
)

_BY_NAME: dict[PersonaName, Persona] = {
    "mom": MOM,
    "dad": DAD,
    "grandma": GRANDMA,
}


def get(name: PersonaName | str) -> Persona | None:
    """Look up a persona by name (case-insensitive)."""
    key = str(name or "").strip().lower()
    if key in _BY_NAME:
        return _BY_NAME[key]  # type: ignore[index]
    return None


# ---------------------------------------------------------------------------
# Classification heuristics
# ---------------------------------------------------------------------------

_MOM_WORDS = (
    "plan", "roadmap", "milestone", "deadline", "schedule", "remind",
    "check in", "progress", "on track", "drift", "priorities",
    "where are we", "what's next",
)
_DAD_WORDS = (
    "fix", "ship", "just", "simplest", "fastest", "cut", "scope",
    "rewrite", "refactor", "why is this so", "bloat", "overkill",
    "overengineer", "over-engineer", "minimal",
)
_GRANDMA_WORDS = (
    "history", "before", "last time", "pattern", "remember when",
    "always", "usually", "big picture", "long term", "tradition",
    "context", "why did we", "origin",
)

_ADDRESS_RE = re.compile(
    r"\b(mom|dad|grandma)[,:\s]", re.IGNORECASE
)


def _score(text: str, words: tuple[str, ...]) -> int:
    lower = text.lower()
    return sum(1 for w in words if w in lower)


def detect_addressed(prompt: str) -> PersonaName | None:
    """Return the persona if the prompt explicitly addresses one.

    Matches patterns like ``"Dad, is this efficient?"`` or
    ``"Grandma: what did we decide last time?"``. Position must be
    at the start of a word, followed by comma / colon / whitespace.
    """
    if not prompt:
        return None
    m = _ADDRESS_RE.search(prompt.lstrip())
    if m:
        return m.group(1).lower()  # type: ignore[return-value]
    return None


def classify(
    prompt: str,
    *,
    teaching_mode: bool = False,
    roadmap_drift: bool = False,
) -> PersonaName:
    """Pick a dominant persona for the given prompt + state.

    State-aware overrides beat keyword scoring:

    - ``teaching_mode=True``   -> Grandma
    - ``roadmap_drift=True``   -> Mom
    - explicit address         -> that persona
    - otherwise                -> top keyword score, tie-break Dad
    """
    addressed = detect_addressed(prompt)
    if addressed is not None:
        return addressed
    if teaching_mode:
        return "grandma"
    if roadmap_drift:
        return "mom"
    scores = {
        "mom": _score(prompt, _MOM_WORDS),
        "dad": _score(prompt, _DAD_WORDS),
        "grandma": _score(prompt, _GRANDMA_WORDS),
    }
    # If nothing matches, default to Dad (bias toward execution).
    if max(scores.values()) == 0:
        return "dad"
    # Stable tie-break: dad > mom > grandma.
    order: list[PersonaName] = ["dad", "mom", "grandma"]
    return max(order, key=lambda n: scores[n])


def strip_address_prefix(prompt: str) -> str:
    """Remove a leading ``"Mom, "`` / ``"Dad:"`` / etc. address.

    Used when we route an explicitly addressed prompt so the model
    doesn't see the salutation. Idempotent.
    """
    if not prompt:
        return ""
    stripped = prompt.lstrip()
    m = _ADDRESS_RE.match(stripped)
    if not m:
        return prompt
    # Skip the matched token + the delimiter char (comma/colon/space).
    return stripped[m.end():].lstrip()
