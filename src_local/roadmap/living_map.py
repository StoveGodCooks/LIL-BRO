"""Living roadmap: milestones and tasks with plain-JSON persistence.

Data model
----------

A ``LivingMap`` owns a list of ``Milestone``s; each ``Milestone`` owns
a list of ``Task``s. Everything has a short human-readable id prefix
(``M-xxxx`` / ``T-xxxx``) to make addressing easy from slash commands.

States
~~~~~~

- ``ICEBOX``      -- captured, not yet planned into a milestone
- ``BACKLOG``     -- planned but not in progress
- ``IN_PROGRESS`` -- executing now (at most one per milestone)
- ``COMPLETED``   -- finished; kept around for memory/history
- ``BLOCKED``     -- paused awaiting info / decision

Persistence
~~~~~~~~~~~

Plain JSON at ``~/.lilbro-local/roadmap.json`` (or a path supplied to
``LivingMap.__init__``). Writes are atomic-ish: write-then-rename via
the standard pathlib pattern is overkill for our scale; we simply
write the full doc on each mutation. Load is tolerant of missing /
corrupt files.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger("lilbro-local.roadmap.map")


TaskState = Literal["ICEBOX", "BACKLOG", "IN_PROGRESS", "COMPLETED", "BLOCKED"]
MilestoneState = Literal["BACKLOG", "IN_PROGRESS", "COMPLETED", "BLOCKED"]

_TASK_STATES: tuple[TaskState, ...] = (
    "ICEBOX",
    "BACKLOG",
    "IN_PROGRESS",
    "COMPLETED",
    "BLOCKED",
)
_MILESTONE_STATES: tuple[MilestoneState, ...] = (
    "BACKLOG",
    "IN_PROGRESS",
    "COMPLETED",
    "BLOCKED",
)


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


@dataclass
class Task:
    id: str
    title: str
    state: TaskState = "BACKLOG"
    notes: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()


@dataclass
class Milestone:
    id: str
    title: str
    state: MilestoneState = "BACKLOG"
    description: str = ""
    tasks: list[Task] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def find_task(self, task_id: str) -> Task | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None


class LivingMap:
    """The living roadmap persisted to JSON.

    Example::

        rm = LivingMap(Path.home() / ".lilbro-local" / "roadmap.json")
        m = rm.add_milestone("Ship auth rewrite")
        t = rm.add_task(m.id, "Draft session schema")
        rm.set_task_state(t.id, "IN_PROGRESS")
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self.milestones: list[Milestone] = []
        self._load()

    # ------------------------------------------------------------------
    # Milestones
    # ------------------------------------------------------------------

    def add_milestone(self, title: str, description: str = "") -> Milestone:
        m = Milestone(id=_short_id("M"), title=title, description=description)
        self.milestones.append(m)
        self._save()
        return m

    def find_milestone(self, milestone_id: str) -> Milestone | None:
        for m in self.milestones:
            if m.id == milestone_id:
                return m
        return None

    def set_milestone_state(
        self, milestone_id: str, state: MilestoneState
    ) -> Milestone | None:
        if state not in _MILESTONE_STATES:
            raise ValueError(f"invalid milestone state: {state}")
        m = self.find_milestone(milestone_id)
        if m is None:
            return None
        # A milestone can only have one IN_PROGRESS at a time across the
        # map. Demote others to BACKLOG when promoting a new one.
        if state == "IN_PROGRESS":
            for other in self.milestones:
                if other.id != m.id and other.state == "IN_PROGRESS":
                    other.state = "BACKLOG"
                    other.touch()
        m.state = state
        m.touch()
        self._save()
        return m

    def delete_milestone(self, milestone_id: str) -> bool:
        before = len(self.milestones)
        self.milestones = [m for m in self.milestones if m.id != milestone_id]
        if len(self.milestones) != before:
            self._save()
            return True
        return False

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def add_task(
        self,
        milestone_id: str,
        title: str,
        *,
        state: TaskState = "BACKLOG",
        notes: str = "",
    ) -> Task | None:
        if state not in _TASK_STATES:
            raise ValueError(f"invalid task state: {state}")
        m = self.find_milestone(milestone_id)
        if m is None:
            return None
        t = Task(id=_short_id("T"), title=title, state=state, notes=notes)
        m.tasks.append(t)
        m.touch()
        self._save()
        return t

    def find_task(self, task_id: str) -> tuple[Milestone, Task] | None:
        for m in self.milestones:
            t = m.find_task(task_id)
            if t is not None:
                return (m, t)
        return None

    def set_task_state(self, task_id: str, state: TaskState) -> Task | None:
        if state not in _TASK_STATES:
            raise ValueError(f"invalid task state: {state}")
        hit = self.find_task(task_id)
        if hit is None:
            return None
        m, t = hit
        # Only one IN_PROGRESS task per milestone.
        if state == "IN_PROGRESS":
            for other in m.tasks:
                if other.id != t.id and other.state == "IN_PROGRESS":
                    other.state = "BACKLOG"
                    other.touch()
        t.state = state
        t.touch()
        m.touch()
        self._save()
        return t

    def delete_task(self, task_id: str) -> bool:
        hit = self.find_task(task_id)
        if hit is None:
            return False
        m, t = hit
        m.tasks = [x for x in m.tasks if x.id != t.id]
        m.touch()
        self._save()
        return True

    # ------------------------------------------------------------------
    # Views
    # ------------------------------------------------------------------

    def active_milestone(self) -> Milestone | None:
        for m in self.milestones:
            if m.state == "IN_PROGRESS":
                return m
        return None

    def active_task(self) -> Task | None:
        m = self.active_milestone()
        if m is None:
            return None
        for t in m.tasks:
            if t.state == "IN_PROGRESS":
                return t
        return None

    def next_backlog_task(self, milestone_id: str | None = None) -> Task | None:
        """Return the first BACKLOG task in the (active) milestone."""
        m = (
            self.find_milestone(milestone_id)
            if milestone_id
            else self.active_milestone()
        )
        if m is None:
            return None
        for t in m.tasks:
            if t.state == "BACKLOG":
                return t
        return None

    def render_summary(self) -> str:
        """One-shot text render of the whole roadmap for display."""
        if not self.milestones:
            return "(roadmap empty — try /brainstorm <goal> or /milestone <title>)"
        lines: list[str] = []
        state_icon = {
            "BACKLOG": "[ ]",
            "IN_PROGRESS": "[>]",
            "COMPLETED": "[x]",
            "BLOCKED": "[!]",
            "ICEBOX": "[~]",
        }
        for m in self.milestones:
            icon = state_icon.get(m.state, "[?]")
            lines.append(f"{icon} {m.id} {m.title}  ({m.state})")
            for t in m.tasks:
                ticon = state_icon.get(t.state, "[?]")
                lines.append(f"   {ticon} {t.id}  {t.title}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "milestones": [
                {
                    **{
                        k: v for k, v in asdict(m).items() if k != "tasks"
                    },
                    "tasks": [asdict(t) for t in m.tasks],
                }
                for m in self.milestones
            ]
        }

    def _load(self) -> None:
        try:
            if not self._path.exists():
                return
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                return
            mlist = data.get("milestones") or []
            parsed: list[Milestone] = []
            for m in mlist:
                tasks_raw = m.get("tasks") or []
                tasks = [
                    Task(
                        id=str(t.get("id") or _short_id("T")),
                        title=str(t.get("title") or ""),
                        state=_coerce_task_state(t.get("state")),
                        notes=str(t.get("notes") or ""),
                        created_at=float(t.get("created_at") or time.time()),
                        updated_at=float(t.get("updated_at") or time.time()),
                    )
                    for t in tasks_raw
                    if isinstance(t, dict)
                ]
                parsed.append(
                    Milestone(
                        id=str(m.get("id") or _short_id("M")),
                        title=str(m.get("title") or ""),
                        state=_coerce_milestone_state(m.get("state")),
                        description=str(m.get("description") or ""),
                        tasks=tasks,
                        created_at=float(m.get("created_at") or time.time()),
                        updated_at=float(m.get("updated_at") or time.time()),
                    )
                )
            self.milestones = parsed
        except Exception as exc:  # noqa: BLE001
            logger.warning("LivingMap: failed to load %s: %s", self._path, exc)
            self.milestones = []

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("LivingMap: failed to save: %s", exc)


def _coerce_task_state(raw: object) -> TaskState:
    s = str(raw or "BACKLOG").upper()
    if s not in _TASK_STATES:
        return "BACKLOG"
    return s  # type: ignore[return-value]


def _coerce_milestone_state(raw: object) -> MilestoneState:
    s = str(raw or "BACKLOG").upper()
    if s not in _MILESTONE_STATES:
        return "BACKLOG"
    return s  # type: ignore[return-value]
