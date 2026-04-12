"""Ollama HTTP adapter for LIL BRO LOCAL.

Speaks to a locally-running Ollama daemon over its REST API at
http://127.0.0.1:11434. Streams chat completions via the /api/chat
endpoint with stream=true (NDJSON chunks).

Each agent instance maintains its own conversation history so context
carries across turns within a session. The agent supports:
- Streaming text deltas into a panel in real time
- Cancellation via cancel_in_flight()
- System prompt injection
- Multiple concurrent instances (one per pane)

No subprocess management needed — Ollama runs as a separate daemon
that the user starts independently (or LIL BRO detects + guides).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from src.ui.panels import _BasePanel

logger = logging.getLogger("lilbro-local.agent")


DEFAULT_SYSTEM_PROMPT = """\
You are a helpful coding assistant running locally via Ollama. You help with:
- Writing, explaining, and debugging Python code
- Answering programming questions
- Reviewing code and suggesting improvements

Be concise and practical. Show code when helpful. If you're unsure about \
something, say so rather than guessing.\
"""

CODER_SYSTEM_PROMPT = """\
You are a local coding agent. You write, edit, and debug code. \
You are direct and concise. When asked to write code, write it immediately \
without lengthy preamble. When asked to explain, be clear and brief. \
If you need to see a file to help, ask the user to paste it.\
"""

HELPER_SYSTEM_PROMPT = """\
You are a local helper agent. You explain code, debug issues, teach concepts, \
and answer programming questions. You never edit files directly — you advise \
and explain. Be clear and educational. Use examples when they help.\
"""


class OllamaAgent:
    """HTTP-based agent that talks to a local Ollama daemon.

    Each instance maintains its own chat history and can be configured
    with a different model, system prompt, and display name.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
        display_name: str = "Local Bro",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.1,
        context_window: int = 32768,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.display_name = display_name
        self.temperature = temperature
        self.context_window = context_window

        self._history: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._current_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._turn_started_at: float | None = None
        self._cancelled = False

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0),
        )

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def request(self, prompt: str, panel: "_BasePanel") -> None:
        """Fire-and-forget request. Serializes via asyncio.Lock."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.error("request called outside running event loop")
            return
        task = loop.create_task(
            self._request_locked(prompt, panel),
            name=f"{self.display_name}-turn",
        )
        self._tasks.add(task)
        self._current_task = task
        task.add_done_callback(self._tasks.discard)

    async def _request_locked(self, prompt: str, panel: "_BasePanel") -> None:
        async with self._lock:
            self._turn_started_at = time.monotonic()
            self._cancelled = False
            try:
                await self._stream_reply(prompt, panel)
            except asyncio.CancelledError:
                panel.append_system("(turn cancelled)")
                raise
            except httpx.ConnectError:
                panel.append_error(
                    f"Cannot connect to Ollama at {self.base_url}\n"
                    "Make sure Ollama is running: ollama serve"
                )
            except httpx.ReadTimeout:
                panel.append_error(
                    f"{self.display_name} timed out (120s). "
                    "The model may be too large for your hardware."
                )
            except Exception as exc:
                logger.exception("%s crashed during turn", self.display_name)
                panel.append_error(f"{self.display_name} error: {exc}")
            finally:
                self._turn_started_at = None

    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        """Send prompt to Ollama and stream the response into the panel."""
        if self._client is None:
            panel.append_error(f"{self.display_name} not started — call start() first")
            return

        # Add user message to history.
        self._history.append({"role": "user", "content": prompt})

        # Trim history if it's getting too long (keep system + last N turns).
        self._trim_history()

        payload = {
            "model": self.model,
            "messages": self._history,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }

        full_response = []
        panel.start_agent_stream()

        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload
            ) as response:
                if response.status_code != 200:
                    body = await response.aread()
                    error_text = body.decode("utf-8", errors="replace")
                    panel.append_error(
                        f"Ollama returned {response.status_code}: {error_text}"
                    )
                    return

                async for line in response.aiter_lines():
                    if self._cancelled:
                        break
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Extract text content from the chunk.
                    msg = chunk.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        full_response.append(content)
                        panel.append_agent_chunk(content)

                    # Check if this is the final chunk.
                    if chunk.get("done", False):
                        break

        finally:
            # Finalize the panel's streaming state.
            panel.mark_assistant_complete()

        # Add assistant response to history.
        assistant_text = "".join(full_response)
        if assistant_text:
            self._history.append({"role": "assistant", "content": assistant_text})

    def _trim_history(self) -> None:
        """Keep conversation history manageable.

        Preserves the system prompt (index 0) and the most recent
        turns. Aggressive trimming for small models that degrade
        with long contexts.
        """
        max_messages = 20  # system + 9 user/assistant pairs + current
        if len(self._history) <= max_messages:
            return
        system = self._history[0]
        recent = self._history[-(max_messages - 1):]
        self._history = [system] + recent

    def cancel_in_flight(self) -> bool:
        """Cancel the currently-running turn."""
        self._cancelled = True
        task = self._current_task
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def is_busy(self) -> bool:
        task = self._current_task
        return task is not None and not task.done()

    def busy_for(self) -> float | None:
        started = self._turn_started_at
        if started is None:
            return None
        return max(0.0, time.monotonic() - started)

    def clear_history(self) -> None:
        """Reset conversation history, keeping only the system prompt."""
        system = self._history[0] if self._history else {
            "role": "system", "content": DEFAULT_SYSTEM_PROMPT
        }
        self._history = [system]


async def check_ollama_health(base_url: str = "http://127.0.0.1:11434") -> dict:
    """Check if Ollama is running and what models are available.

    Returns a dict with:
      - running: bool
      - version: str | None
      - models: list[str]  (model names currently pulled)
    """
    result = {"running": False, "version": None, "models": []}
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(5.0)
        ) as client:
            # Check if Ollama responds.
            resp = await client.get(f"{base_url}/api/version")
            if resp.status_code == 200:
                result["running"] = True
                data = resp.json()
                result["version"] = data.get("version", "unknown")

            # List available models.
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("models", [])
                result["models"] = [m.get("name", "") for m in models]
    except (httpx.ConnectError, httpx.ReadTimeout, Exception):
        pass
    return result
