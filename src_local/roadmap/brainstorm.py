"""Guided brainstorm prompt helpers.

The brainstorm phase is deliberately LLM-driven: we compose a
structured prompt and let Lil Bro (or whichever backend is assigned
the teacher role) do the thinking. This module owns the prompt
shape, not the execution.

Workflow
~~~~~~~~

1. ``build_brainstorm_prompt(goal)`` returns a teaching-style prompt
   that asks the model to surface assumptions, unknowns, constraints,
   and 3-5 concrete milestone candidates.
2. The user reads the reply, picks one, and hits ``/milestone <title>``
   to lock it in.
"""

from __future__ import annotations


BRAINSTORM_TEMPLATE = """You are helping the user brainstorm a coding goal.
Do not start coding or write files. Output pure reasoning in six
short sections. Be concrete and brief.

GOAL: {goal}

1. Restate the goal in one sentence.
2. Assumptions you're making (bullets, max 4).
3. Unknowns the user needs to clarify (bullets, max 4).
4. Hard constraints (tech, time, scope — bullets, max 4).
5. 3-5 candidate milestones, each a one-line imperative phrase.
   Rank them roughly by value delivered per unit of effort.
6. Recommended first milestone and why.

Keep the whole reply under 300 words. No code."""


def build_brainstorm_prompt(goal: str) -> str:
    """Return a structured brainstorm prompt for *goal*.

    The goal string is stripped; blank goals fall back to a generic
    "what should we work on?" prompt so the command never produces
    an empty payload.
    """
    g = (goal or "").strip()
    if not g:
        g = "What should we work on next in this project?"
    return BRAINSTORM_TEMPLATE.format(goal=g)
