"""Summarize completed sessions using a local Ollama model.

Calls Ollama's ``/api/generate`` endpoint (not chat) so this works
without any streaming scaffolding or tool support.
"""

from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger("lilbro-local.memory.summarizer")

_SUMMARY_PROMPT = """\
You are a concise session summarizer for a coding assistant tool.
Summarize the session text below in {max_words} words or fewer.
Focus on: what was worked on, key decisions made, files changed,
and problems solved. Output only the summary — no headings, no preamble.

Session:
{text}
"""


class SessionSummarizer:
    """Summarize a session transcript using a local Ollama model.

    Falls back gracefully when Ollama is unavailable — returns an empty
    string so callers never need to guard against exceptions.

    Usage::

        summarizer = SessionSummarizer()
        summary = await summarizer.summarize(session_text)
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model

    async def summarize(self, session_text: str, max_words: int = 150) -> str:
        """Call Ollama to summarize *session_text* into ≤ *max_words* words.

        Returns an empty string on any error.
        """
        if not session_text.strip():
            return ""

        prompt = _SUMMARY_PROMPT.format(
            max_words=max_words,
            text=session_text[:8000],  # cap input to avoid huge contexts
        )

        payload = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")

        url = f"{self._base_url}/api/generate"
        try:
            proc = await asyncio.create_subprocess_exec(
                "curl",
                "-s",
                "-X", "POST",
                url,
                "-H", "Content-Type: application/json",
                "-d", "@-",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _stderr = await asyncio.wait_for(
                proc.communicate(input=payload),
                timeout=60.0,
            )
            data = json.loads(stdout.decode("utf-8", errors="replace"))
            return str(data.get("response", "")).strip()
        except asyncio.TimeoutError:
            logger.warning("SessionSummarizer: Ollama timed out after 60s")
            return ""
        except FileNotFoundError:
            # curl not available — try pure Python
            return await self._summarize_python(url, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("SessionSummarizer failed: %s", exc)
            return ""

    async def _summarize_python(self, url: str, payload: bytes) -> str:
        """Pure-Python fallback using urllib (no curl required)."""
        try:
            import urllib.request as _req

            loop = asyncio.get_running_loop()
            response_bytes = await loop.run_in_executor(
                None,
                lambda: _req.urlopen(  # noqa: S310
                    _req.Request(
                        url,
                        data=payload,
                        headers={"Content-Type": "application/json"},
                    ),
                    timeout=60,
                ).read(),
            )
            data = json.loads(response_bytes.decode("utf-8", errors="replace"))
            return str(data.get("response", "")).strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("SessionSummarizer._summarize_python failed: %s", exc)
            return ""
