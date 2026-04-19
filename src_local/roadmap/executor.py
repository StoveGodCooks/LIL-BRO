"""Task executor: walks the living map with explicit user gates.

This is deliberately **not** an autonomous loop. Each step waits for
the user to approve before the coder agent is invoked. The goal is
deterministic progress over dazzling automation.

Usage pattern (wired from the command handler)::

    ex = Executor(living_map)
    plan = ex.prepare_next()        # returns the next task + a plan prompt
    ex.start(plan.task_id)          # marks task IN_PROGRESS on user "go"
    ex.complete(plan.task_id)       # marks task COMPLETED on user "done"

The ``prepare_next`` step also builds a short "here's what I'm about
to do" briefing from the task title so the user can sanity-check
scope before code gets written.
"""

from __future__ import annotations

from dataclasses import dataclass

from .living_map import LivingMap, Milestone, Task


BRIEF_TEMPLATE = """Before I start task {task_id} I want to confirm scope.

MILESTONE: {milestone_title}
TASK:      {task_title}
{notes_block}
Reply in 4 short bullets:
- Files you plan to touch
- Approach (one sentence)
- What's explicitly out of scope for this task
- A done-check the user can verify

No code yet. Wait for user approval."""


@dataclass
class NextStep:
    milestone: Milestone
    task: Task
    task_id: str
    brief_prompt: str


class Executor:
    """Thin state machine over the living map."""

    def __init__(self, living_map: LivingMap) -> None:
        self._map = living_map

    # ------------------------------------------------------------------
    # Queueing
    # ------------------------------------------------------------------

    def prepare_next(self, milestone_id: str | None = None) -> NextStep | None:
        """Find the next BACKLOG task and build a briefing prompt.

        Returns ``None`` when there's no milestone or no work left.
        Does **not** change any state -- the caller decides whether to
        actually start the task after showing the user the brief.
        """
        m = (
            self._map.find_milestone(milestone_id)
            if milestone_id
            else self._map.active_milestone()
        )
        if m is None:
            return None
        task = None
        for t in m.tasks:
            if t.state == "BACKLOG":
                task = t
                break
        if task is None:
            return None
        notes_block = ""
        if task.notes:
            notes_block = f"NOTES:\n{task.notes.strip()}\n"
        brief = BRIEF_TEMPLATE.format(
            task_id=task.id,
            milestone_title=m.title,
            task_title=task.title,
            notes_block=notes_block,
        )
        return NextStep(
            milestone=m, task=task, task_id=task.id, brief_prompt=brief
        )

    # ------------------------------------------------------------------
    # State transitions (thin wrappers so the command handler has a
    # single place to import).
    # ------------------------------------------------------------------

    def start(self, task_id: str) -> Task | None:
        return self._map.set_task_state(task_id, "IN_PROGRESS")

    def complete(self, task_id: str) -> Task | None:
        return self._map.set_task_state(task_id, "COMPLETED")

    def block(self, task_id: str, reason: str = "") -> Task | None:
        hit = self._map.find_task(task_id)
        if hit is None:
            return None
        _m, t = hit
        if reason:
            t.notes = (t.notes + "\n" if t.notes else "") + f"blocked: {reason}"
        return self._map.set_task_state(task_id, "BLOCKED")
