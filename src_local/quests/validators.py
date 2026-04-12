"""Quest submission validators.

Every validator takes the user's raw text submission and the quest
(or chunk) to compare against, and returns a ``ValidationResult``:

* ``ok``          — pass/fail flag
* ``similarity``  — 0.0..1.0 match ratio (retype only; 1.0 otherwise)
* ``missing``     — list of key_lines / trail entries the user left out

The top-level ``validate(quest, submission)`` function dispatches on
``quest.type``. Boss quests are NOT handled here — use
``validate_boss_chunk(chunk, submission)`` to evaluate the current
chunk; the boss controller decides when to advance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from src_local.quests.models import Quest, QuestChunk


# Retype threshold — whitespace-normalized similarity must meet this
# for a pass. 0.85 is permissive enough to tolerate minor typos but
# tight enough that blatantly wrong answers fail.
RETYPE_THRESHOLD = 0.85


@dataclass
class ValidationResult:
    ok: bool = False
    similarity: float = 0.0
    missing: list[str] = field(default_factory=list)
    message: str = ""


# -------------------------------------------------------------------
# Low-level helpers
# -------------------------------------------------------------------

def _normalize_ws(text: str) -> str:
    """Collapse all runs of whitespace to single spaces + strip.

    This lets ``retype`` tolerate indentation drift and trailing
    newlines that aren't semantically meaningful in most languages.
    """
    return " ".join(text.split())


def _stripped_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


# -------------------------------------------------------------------
# Individual validators
# -------------------------------------------------------------------

def validate_retype(submission: str, solution: str) -> tuple[bool, float]:
    """True iff SequenceMatcher(submission, solution).ratio() >= 0.85
    after whitespace normalization. Returns the actual ratio too so
    the UI can show a "you're 92% there" hint."""
    if not solution:
        return (False, 0.0)
    a = _normalize_ws(submission)
    b = _normalize_ws(solution)
    if not a:
        return (False, 0.0)
    ratio = SequenceMatcher(None, a, b).ratio()
    return (ratio >= RETYPE_THRESHOLD, ratio)


def validate_key_lines(
    submission: str, key_lines: tuple[str, ...]
) -> tuple[bool, list[str]]:
    """Every entry in ``key_lines`` must appear as a trimmed line in the
    submission. Returns (ok, missing_lines)."""
    if not key_lines:
        return (True, [])
    present = set(_stripped_lines(submission))
    missing = [k for k in key_lines if k.strip() not in present]
    return (not missing, missing)


def validate_debug_trail(
    submission: str, expected: tuple[str, ...]
) -> tuple[bool, list[str]]:
    """The user lists bugs in order — submission stripped-lines must
    equal the expected tuple exactly. Returns (ok, missing) where
    ``missing`` is the expected tail when the user's list is too short
    or wrong."""
    if not expected:
        return (True, [])
    user_lines = tuple(_stripped_lines(submission))
    if user_lines == tuple(expected):
        return (True, [])
    # Figure out the first divergence so the UI can point at it.
    missing: list[str] = []
    for i, e in enumerate(expected):
        if i >= len(user_lines) or user_lines[i] != e:
            missing.append(e)
    return (False, missing)


def validate_boss_chunk(
    chunk: QuestChunk, submission: str
) -> ValidationResult:
    """Dispatch one boss chunk to the right validator."""
    return _dispatch(chunk.type, submission, chunk.solution, chunk.key_lines, chunk.expected_trail)


# -------------------------------------------------------------------
# Top-level dispatch
# -------------------------------------------------------------------

def validate(quest: Quest, submission: str) -> ValidationResult:
    """Evaluate a non-boss quest submission.

    Raises ``ValueError`` if called with a boss quest — boss fights
    are driven chunk-by-chunk through ``validate_boss_chunk``.
    """
    if quest.is_boss():
        raise ValueError(
            "validate() does not handle boss quests — use "
            "validate_boss_chunk() for each chunk."
        )
    return _dispatch(
        quest.type,
        submission,
        quest.solution,
        quest.key_lines,
        quest.expected_trail,
    )


def _dispatch(
    qtype: str,
    submission: str,
    solution: str,
    key_lines: tuple[str, ...],
    expected_trail: tuple[str, ...],
) -> ValidationResult:
    if qtype == "retype":
        ok, ratio = validate_retype(submission, solution)
        return ValidationResult(
            ok=ok,
            similarity=ratio,
            message=f"similarity {ratio:.0%} (needs {RETYPE_THRESHOLD:.0%})",
        )
    if qtype in ("key_lines", "explain"):
        ok, missing = validate_key_lines(submission, key_lines)
        return ValidationResult(
            ok=ok,
            similarity=1.0 if ok else 0.0,
            missing=missing,
            message="all key lines present" if ok else f"missing {len(missing)} key line(s)",
        )
    if qtype == "debug_trail":
        ok, missing = validate_debug_trail(submission, expected_trail)
        return ValidationResult(
            ok=ok,
            similarity=1.0 if ok else 0.0,
            missing=missing,
            message="trail matches" if ok else "trail mismatch",
        )
    return ValidationResult(ok=False, message=f"unknown quest type: {qtype}")
