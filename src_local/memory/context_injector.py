"""Inject relevant memories into prompts before sending to an agent.

Only injects when:
- MemoryStore is available (chromadb installed, store initialised)
- The prompt is longer than 20 characters
- At least one matching memory is found

Injection is best-effort: any failure returns the original prompt
unchanged.  Never blocks or raises.

Usage::

    injector = ContextInjector(store, max_memories=3)
    enriched = await injector.inject(prompt, project=str(Path.cwd()))
"""

from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src_local.memory.chroma_store import MemoryStore

logger = logging.getLogger("lilbro-local.memory.injector")

_MIN_PROMPT_LEN = 20


class ContextInjector:
    """Prepend relevant past memories to a prompt.

    Parameters
    ----------
    store:
        A :class:`~src_local.memory.chroma_store.MemoryStore` instance.
    max_memories:
        Maximum number of memories to inject.
    """

    def __init__(self, store: "MemoryStore", max_memories: int = 3) -> None:
        self._store = store
        self._max = max_memories

    async def inject(self, prompt: str, project: str = "") -> str:
        """Return prompt with relevant memories prepended, or original if none.

        Memories are formatted as::

            [Memory: 2026-04-18 14:30 — <summary text>]
            ---
            <original prompt>
        """
        if len(prompt) <= _MIN_PROMPT_LEN:
            return prompt
        try:
            query = prompt[:500]
            results = self._store.search(query, n=self._max)
            if not results:
                return prompt
            lines: list[str] = []
            for r in results:
                text = r.get("text", "").strip()
                if not text:
                    continue
                ts = r.get("metadata", {}).get("timestamp")
                if ts:
                    try:
                        when = datetime.datetime.fromtimestamp(float(ts)).strftime(
                            "%Y-%m-%d %H:%M"
                        )
                    except Exception:  # noqa: BLE001
                        when = "?"
                else:
                    when = "?"
                lines.append(f"[Memory: {when} — {text[:200]}]")
            if not lines:
                return prompt
            header = "\n".join(lines) + "\n---\n"
            return header + prompt
        except Exception as exc:  # noqa: BLE001
            logger.debug("ContextInjector.inject failed: %s", exc)
            return prompt
