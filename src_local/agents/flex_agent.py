"""FLEX mode agent for LIL BRO LOCAL.

Routes each turn to the best available backend based on heuristic
prompt classification. No ML — just keyword matching.

Priority:
- Teaching/explain prompts → teaching_backend (codex or claude)
- Code gen/edit prompts    → coding_backend   (claude or codex)
- Fallback                 → fallback_backend  (ollama)

All AgentProcess lifecycle calls are delegated to the active sub-agent.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src_local.agents.base import AgentProcess

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel

logger = logging.getLogger("lilbro-local.flex")


# ── Classifier keyword sets ────────────────────────────────────────────────

_TEACHING_KEYWORDS: frozenset[str] = frozenset(
    {
        "/explain",
        "/trace",
        "/compare",
        "/debug",
        "/review",
        "explain",
        "teach",
        "what is",
        "how does",
        "why does",
        "walk me through",
        "help me understand",
        "can you describe",
        "what does",
        "how do",
    }
)

_CODING_KEYWORDS: frozenset[str] = frozenset(
    {
        "/plan",
        "write",
        "create",
        "build",
        "implement",
        "refactor",
        "edit",
        "fix",
        "add a",
        "update the",
        "generate",
        "scaffold",
        "make a",
        "make the",
        "rename",
        "delete",
        "remove the",
    }
)


def _classify_prompt(prompt: str) -> str:
    """Classify a prompt as ``'teaching'``, ``'coding'``, or ``'fallback'``.

    This is the pure function the test suite exercises.  Matching is
    case-insensitive; the first matching category wins.
    """
    low = prompt.lower()
    for kw in _TEACHING_KEYWORDS:
        if kw in low:
            return "teaching"
    for kw in _CODING_KEYWORDS:
        if kw in low:
            return "coding"
    return "fallback"


class FlexAgent(AgentProcess):
    """Routes each turn to the best available backend.

    Construct with three sub-agents (any may be the same object):

    * ``teaching_backend`` — used for explain / teach / review turns
    * ``coding_backend``   — used for code-gen / edit turns
    * ``fallback_backend`` — used when the above are unavailable or
      the prompt doesn't match either category
    """

    DISPLAY_NAME: str = "Flex"
    RESTART_KEY: str = "lil"

    def __init__(
        self,
        *,
        teaching_backend: AgentProcess,
        coding_backend: AgentProcess,
        fallback_backend: AgentProcess,
    ) -> None:
        super().__init__()
        self.teaching_backend = teaching_backend
        self.coding_backend = coding_backend
        self.fallback_backend = fallback_backend
        self._active_backend: AgentProcess = fallback_backend

    # ------------------------------------------------------------------
    # Classification helper (exposed so tests can call it directly)
    # ------------------------------------------------------------------

    @staticmethod
    def classify(prompt: str) -> str:
        """Classify *prompt* → ``'teaching'`` | ``'coding'`` | ``'fallback'``."""
        return _classify_prompt(prompt)

    # ------------------------------------------------------------------
    # AgentProcess lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start all sub-agents in parallel."""
        import asyncio as _asyncio

        backends = {self.teaching_backend, self.coding_backend, self.fallback_backend}
        await _asyncio.gather(*(b.start() for b in backends), return_exceptions=True)

    async def stop(self) -> None:
        """Stop all sub-agents."""
        import asyncio as _asyncio

        backends = {self.teaching_backend, self.coding_backend, self.fallback_backend}
        await _asyncio.gather(*(b.stop() for b in backends), return_exceptions=True)

    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        """Classify, pick backend, delegate."""
        category = _classify_prompt(prompt)
        if category == "teaching":
            backend = self.teaching_backend
        elif category == "coding":
            backend = self.coding_backend
        else:
            backend = self.fallback_backend

        self._active_backend = backend
        provider = type(backend).__name__.replace("Agent", "").lower()
        try:
            panel.append_system(
                f"[FLEX] routing to {provider} ({category})"
            )
        except Exception:  # noqa: BLE001
            pass

        await backend._stream_reply(prompt, panel)

    # ------------------------------------------------------------------
    # Properties delegated to the active backend
    # ------------------------------------------------------------------

    @property
    def model(self) -> str | None:
        active_model = getattr(self._active_backend, "model", None)
        return f"flex ({active_model or '?'})"

    @model.setter
    def model(self, value: str | None) -> None:
        """Setting model on FlexAgent sets it on all backends."""
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            try:
                b.model = value  # type: ignore[assignment]
            except Exception:  # noqa: BLE001
                pass

    @property
    def display_name(self) -> str:
        return getattr(self._active_backend, "display_name", "Flex")

    def is_busy(self) -> bool:
        return any(
            b.is_busy()
            for b in (self.teaching_backend, self.coding_backend, self.fallback_backend)
        )

    def busy_for(self) -> float | None:
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            t = b.busy_for()
            if t is not None:
                return t
        return None

    def cancel_in_flight(self) -> bool:
        cancelled = False
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            if b.cancel_in_flight():
                cancelled = True
        return cancelled

    def clear_history(self) -> None:
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            try:
                b.clear_history()  # type: ignore[attr-defined]
            except AttributeError:
                pass

    def send_intro(self, panel: "_BasePanel") -> None:
        try:
            self.fallback_backend.send_intro(panel)  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def update_system_prompt(self, prompt: str) -> None:
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            try:
                b.update_system_prompt(prompt)  # type: ignore[attr-defined]
            except AttributeError:
                pass

    def set_write_access(self, enabled: bool) -> None:
        for b in (self.teaching_backend, self.coding_backend, self.fallback_backend):
            try:
                b.set_write_access(enabled)  # type: ignore[attr-defined]
            except AttributeError:
                pass
