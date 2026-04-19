"""Tests for FlexAgent classifier heuristics.

These tests are pure-logic -- no subprocess required.
"""

from __future__ import annotations

import pytest

from src_local.agents.flex_agent import _classify_prompt


# ── Teaching keyword tests ─────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "/explain list comprehensions",
    "Explain how async works in Python",
    "teach me about decorators",
    "What is a generator?",
    "How does the GIL work?",
    "Why does mutable default cause bugs?",
    "Walk me through this error",
    "help me understand closures",
    "/trace my_function",
    "/compare asyncio vs threading",
    "/debug the error below",
    "/review the code above",
])
def test_classify_teaching(prompt: str) -> None:
    assert _classify_prompt(prompt) == "teaching"


# ── Coding keyword tests ───────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "Write a function that parses CSV",
    "Create a FastAPI endpoint for user registration",
    "Build a REST client for the Ollama API",
    "Implement a retry decorator",
    "Refactor this class to use dataclasses",
    "Edit the router to handle /backend command",
    "Fix the off-by-one error in the loop",
    "Add a test for the session summarizer",
    "Update the config loader to support TOML",
    "/plan add memory persistence",
    "Generate a requirements.txt from imports",
    "make a new module for project tracking",
])
def test_classify_coding(prompt: str) -> None:
    assert _classify_prompt(prompt) == "coding"


# ── Fallback tests ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("prompt", [
    "Hello",
    "What time is it?",
    "List all files",
    "status",
    "show me the latest changes",
])
def test_classify_fallback(prompt: str) -> None:
    assert _classify_prompt(prompt) == "fallback"


# ── Case-insensitivity ─────────────────────────────────────────────────────

def test_classify_case_insensitive() -> None:
    assert _classify_prompt("EXPLAIN how Python GC works") == "teaching"
    assert _classify_prompt("WRITE a parser for this format") == "coding"


# ── Teaching wins over coding when both match ──────────────────────────────

def test_explain_beats_write() -> None:
    # "explain ... write" — teaching keywords appear first in check order.
    assert _classify_prompt("explain how to write a decorator") == "teaching"


# ── FlexAgent.classify wraps _classify_prompt ─────────────────────────────

def test_flex_agent_classify_method() -> None:
    from src_local.agents.flex_agent import FlexAgent

    assert FlexAgent.classify("/explain generators") == "teaching"
    assert FlexAgent.classify("write a class") == "coding"
    assert FlexAgent.classify("hello") == "fallback"
