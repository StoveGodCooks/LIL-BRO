"""Ollama HTTP adapter for LIL BRO LOCAL.

Speaks to a locally-running Ollama daemon over its REST API at
http://127.0.0.1:11434. Streams chat completions via the /api/chat
endpoint with stream=true (NDJSON chunks).

Each agent instance maintains its own conversation history so context
carries across turns within a session. The agent supports:
- Streaming text deltas into a panel in real time
- Tool calling (read_file, write_file, edit_file, list_directory, grep_files, run_command)
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
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from src_local.agents.base import AgentProcess

if TYPE_CHECKING:
    from src_local.ui.panels import _BasePanel

logger = logging.getLogger("lilbro-local.agent")


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """\
You are a helpful coding assistant running locally via Ollama. You help with:
- Writing, explaining, and debugging Python code
- Answering programming questions
- Reviewing code and suggesting improvements

Be concise and practical. Show code when helpful. If you're unsure about \
something, say so rather than guessing.\
"""

# ---------------------------------------------------------------------------
# Shared rule blocks — both bros get ALL of these.
# The three system prompts below compose from these with different ordering.
# Big Bro: coding PRIMARY → reasoning SECONDARY
# Lil Bro: reasoning PRIMARY → coding SECONDARY
# Bunkbed: reasoning PRIMARY → coding FULL (write access on)
# ---------------------------------------------------------------------------

_GRANDPA_BLOCK = """\
You have access to Grandpa — a knowledge base with two lookup tools:
- coding_lookup: Search Grandpa's coding knowledge (API docs, syntax, stdlib, examples)
- reasoning_lookup: Search Grandpa's wisdom (debugging strategies, design decisions, tradeoffs)

You have a calculator tool:
- calculate: Evaluate Python math expressions (bin(730), 2**10, 512+128+64). \
NEVER do math in your head — always use calculate for arithmetic, binary \
conversions, powers, and any numeric computation.

HOW GRANDPA WORKS (hybrid retrieval):
Grandpa does a keyword pre-scan of every question automatically. But keyword \
matching is dumb — it might miss what you actually need. So YOU should also call \
coding_lookup or reasoning_lookup with a SMART query that captures what you're \
really looking for. Your results get merged with the pre-scan: entries that BOTH \
retrievers find are marked ★ HIGH CONFIDENCE — pay extra attention to those.

CALL GRANDPA WITH GOOD QUERIES — not just the user's words. Think about what \
concept or pattern you need, then search for THAT. Example: if the user says \
"my nested loop is slow", search for "nested loop optimization hash map" — not \
just "nested loop slow".

When you use these tools, mention it casually — say things like "let me check with \
PawPaw", "asking Grandpa real quick", "lemme see what G-POPS says about this", \
"let me holla at Grandpa", "checking with the big cheese". Vary it up. \
Grandpa's knowledge makes everything better — use him.\
"""

_CODING_RULES = """\
CODING RULES:
1. ANALYZE BEFORE CODING — always. What's the input? Output? Edge cases? \
   Complexity? Say it out loud before writing a single line.
2. UNDERSTAND THE PROBLEM — break it into sub-problems. Identify the data \
   structures needed. Think about the algorithm BEFORE you type.
3. COMPLEXITY FIRST — for performance questions, identify the CURRENT \
   complexity (O(n)? O(n²)? O(n log n)?), explain WHY it's slow with \
   actual numbers and examples, THEN give the optimized solution.
4. ROOT CAUSE DEBUGGING — name the ROOT CAUSE first. Don't try random fixes. \
   Trace the actual execution path. What value is wrong? Where did it go wrong?
5. READ BEFORE EDIT — always read a file before editing it. Never guess contents. \
   Use edit_file for targeted changes; write_file only for new files or full rewrites.
6. USE GRANDPA — if reference material from Grandpa appears in the message, \
   READ IT and USE IT. Don't ignore it and give generic advice.
7. NO GENERIC ADVICE — never say "use multiprocessing" or "profile it" without \
   FIRST explaining the actual problem and giving a SPECIFIC code fix.
8. SHOW YOUR WORK — for math, show steps. Use the calculate tool. \
   For algorithms, trace through an example. For debugging, show the failing path.
9. CORRECT PATTERNS — use the right data structure for the job. \
   dict for O(1) lookup, set for membership, deque for BFS, heapq for top-K. \
   Don't use a list where a set would be O(n) vs O(1).
10. CLEAN CODE — meaningful variable names, no magic numbers, handle edge cases \
    (empty input, single element, None). Don't over-engineer, but don't be sloppy.
11. TEST YOUR LOGIC — before presenting code, mentally trace through at least \
    one example. Does it actually produce the right answer? Check boundary cases.
12. IMPORTS AND STDLIB — use Python's standard library. Don't reinvent wheels. \
    Know itertools, collections, functools, pathlib, dataclasses. Check Grandpa \
    for the right module before writing custom implementations.\
"""

_REASONING_RULES = """\
REASONING RULES:
1. BREAK IT DOWN — decompose every problem into smaller, solvable pieces. \
   State each sub-problem explicitly before solving it.
2. SYSTEMATIC ELIMINATION — for logic puzzles, list ALL possible states, \
   then eliminate impossible ones with clear justification for each elimination.
3. SHOW YOUR WORK — every step of reasoning must be visible. No "clearly" \
   or "obviously" — if it's obvious, it's easy to show. Show it.
4. MATH IS NOT OPTIONAL — use the calculate tool for ALL arithmetic. \
   Never do math in your head. Powers, conversions, modular arithmetic — \
   all go through the tool. Show the expression and the result.
5. SANITY CHECK — after reaching an answer, verify it makes physical/logical \
   sense. Can a 3-gallon jug hold 4 gallons? No. Can a sort run in O(1)? No. \
   Plug your answer back into the original problem.
6. TRACE EXECUTION — for debugging and algorithm questions, trace the actual \
   execution step by step. What are the values at each iteration? Where does \
   the state change?
7. CONSIDER ALTERNATIVES — don't just give the first solution that comes to \
   mind. Are there other approaches? What are the tradeoffs? Why is this \
   approach better than the alternatives?
8. ESTIMATION AND MAGNITUDE — when dealing with numbers, estimate first. \
   Is the answer going to be in the tens, thousands, or millions? If your \
   calculated answer is wildly different from your estimate, something is wrong.
9. DEFINE BEFORE SOLVING — make sure you understand what's being asked. \
   Restate the problem in your own words. Identify constraints. Identify \
   what "correct" means for this specific question.
10. EDGE CASES MATTER — what happens with empty input? Zero? Negative numbers? \
    One element? Maximum size? Don't just solve the happy path.
11. CAUSE AND EFFECT — when explaining WHY something works or doesn't, trace \
    the causal chain. "X happens because Y, and Y happens because Z." Not \
    just "X happens."
12. DON'T GUESS — if you're not sure, say so. Then figure it out step by step. \
    A wrong confident answer is worse than an honest "let me work through this."\
"""

_HONESTY_RULES = """\
HONESTY RULES — NEVER BREAK THESE:
- NEVER make up code, APIs, function names, or libraries that don't exist.
- NEVER pretend you used a tool when you didn't. If you didn't check Grandpa, don't say you did.
- If you don't know something, SAY SO. Say "I'm not sure" or "let me check".
- NEVER hallucinate file contents. If you haven't read a file, don't guess what's in it.
- If a task is too complex or you're stuck, tell the user and work together to figure it out.
- Always verify your work before presenting it. Read it back. Does it actually make sense?
- If you said something wrong, own it immediately. Don't double down on mistakes.
- NEVER write code you can't explain. If you don't understand why it works, don't write it.\
"""

_WORKSPACE_RULES_TEMPLATE = """\
SHARED LOG: You and {sibling} share a workspace log. You can see what {sibling} \
has been working on — it appears automatically at the start of messages as \
"What {sibling} has been working on". You do NOT need to read any files to see \
this — it is injected for you. If asked about {sibling}'s activity, just refer \
to whatever sibling context you see in the message.

PLANNING: When asked to plan a task, take it seriously. Read the relevant files \
first. Ask Grandpa for patterns and best practices. If anything is unclear, ASK \
the user before assuming. Break the plan into concrete numbered steps. \
After the user approves, execute step by step.\
"""


def _build_system_prompt(
    *,
    name: str,
    sibling_name: str,
    role_intro: str,
    primary_rules: str,
    secondary_rules: str,
    closing: str,
) -> str:
    """Compose a system prompt from shared rule blocks.

    Identity and sibling awareness go at the TOP so the model
    never forgets who it is, even on casual questions.
    primary_rules come first (the bro's main strength),
    secondary_rules come second (supporting skill set).
    """
    identity = (
        f"YOUR NAME: {name}.\n"
        f"YOUR SIBLING: {sibling_name} — you two work together as a team. "
        f"You share a workspace log so you can see what {sibling_name} is working on. "
        f"If the user asks about {sibling_name}, check the log context in the message."
    )
    workspace = _WORKSPACE_RULES_TEMPLATE.format(sibling=sibling_name)
    return "\n\n".join([
        identity,
        role_intro,
        _GRANDPA_BLOCK,
        f"=== PRIMARY SKILL SET ===\n{primary_rules}",
        f"=== SECONDARY SKILL SET ===\n{secondary_rules}",
        workspace,
        _HONESTY_RULES,
        closing,
    ])


# Pre-built prompts using the shared blocks.

CODER_SYSTEM_PROMPT = _build_system_prompt(
    name="Big Bro",
    sibling_name="Lil Bro",
    role_intro=(
        "You are the CODER. You have FULL ACCESS to the project filesystem — "
        "you can read files, list directories, search code, WRITE files, EDIT "
        "files, and RUN shell commands. You are NOT read-only.\n\n"
        "When the user asks you to write or modify code, use your tools to do it "
        "directly. Always read a file before editing it so you understand its "
        "current content."
    ),
    primary_rules=_REASONING_RULES,
    secondary_rules=_CODING_RULES,
    closing=(
        "UNDERSTAND first, THEN code. Never write a line until you can explain "
        "what the problem is and why your solution is correct. Show your reasoning, "
        "then show the code."
    ),
)

HELPER_SYSTEM_PROMPT = _build_system_prompt(
    name="Lil Bro",
    sibling_name="Big Bro",
    role_intro=(
        "You are the HELPER. You have READ-ONLY access to the project filesystem — "
        "you can read files, list directories, and search code. You CANNOT write or "
        "edit files.\n\n"
        "You explain code, debug issues, teach concepts, and answer programming "
        "questions. You advise and explain — Big Bro handles the actual edits."
    ),
    primary_rules=_REASONING_RULES,
    secondary_rules=_CODING_RULES,
    closing=(
        "Be clear and educational. Use examples when they help. "
        "Think step by step and show your work."
    ),
)

HELPER_BUNKBED_PROMPT = _build_system_prompt(
    name="Lil Bro",
    sibling_name="Big Bro",
    role_intro=(
        "You are the HELPER with BUNKBED MODE active — you have FULL ACCESS to "
        "the project filesystem. You can read, write, edit files, and run commands.\n\n"
        "You primarily explain and teach, but you can also make direct code changes "
        "when asked. Reference what Big Bro has been doing if relevant."
    ),
    primary_rules=_REASONING_RULES,
    secondary_rules=_CODING_RULES,
    closing=(
        "Always read a file before editing it. Be clear and educational. "
        "Think step by step — your reasoning strength is what makes your code solid."
    ),
)


# ---------------------------------------------------------------------------
# Fallback text tool-call extractor
# ---------------------------------------------------------------------------

# Pattern for what small models output instead of structured tool_calls:
# Format A (common): {"name": "tool_name", "arguments": {...}}
# Format B (Llama):  {"type": "function", "function": {"name": "...", "arguments": {...}}}
# They may wrap it in a code fence or output it bare.
_TEXT_TOOL_RE = re.compile(
    r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*"arguments"\s*:\s*(\{(?:[^{}]|\{[^{}]*\})*\})[^{}]*\}',
    re.DOTALL,
)
# Llama 3.1+ wraps tool calls in {"type":"function","function":{...}}.
_TEXT_TOOL_LLAMA_RE = re.compile(
    r'\{\s*"type"\s*:\s*"function"\s*,\s*"function"\s*:\s*'
    r'\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*"arguments"\s*:\s*(\{(?:[^{}]|\{[^{}]*\})*\})[^{}]*\}'
    r'\s*\}',
    re.DOTALL,
)


def _extract_text_tool_calls(
    text: str,
) -> tuple[list[dict], str]:
    """Scan raw model text for inline tool-call JSON blocks.

    Returns (tool_calls_list, cleaned_text).  tool_calls_list is in the
    same format as Ollama structured tool_calls so the existing tool loop
    can handle them unchanged.  cleaned_text has the JSON blocks stripped.

    Supports two formats:
      A) {"name": "tool", "arguments": {...}}          (Qwen, Mistral, etc.)
      B) {"type":"function","function":{"name":...}}   (Llama 3.1+)
    """
    tool_calls: list[dict] = []
    cleaned = text

    # Try Llama-style first (more specific, avoids double-matching).
    for match in _TEXT_TOOL_LLAMA_RE.finditer(cleaned):
        tool_name = match.group(1)
        args_str = match.group(2)
        try:
            arguments = json.loads(args_str)
        except json.JSONDecodeError:
            continue
        tool_calls.append({"function": {"name": tool_name, "arguments": arguments}})
        cleaned = cleaned.replace(match.group(0), "", 1)

    # Then try the standard format on whatever text remains.
    for match in _TEXT_TOOL_RE.finditer(cleaned):
        tool_name = match.group(1)
        args_str = match.group(2)
        try:
            arguments = json.loads(args_str)
        except json.JSONDecodeError:
            continue
        tool_calls.append({"function": {"name": tool_name, "arguments": arguments}})
        cleaned = cleaned.replace(match.group(0), "", 1)

    # Strip common code-fence wrappers the model may add around the JSON.
    cleaned = re.sub(r"```(?:json)?\s*\n?", "", cleaned)
    cleaned = cleaned.strip()

    return tool_calls, cleaned


# ---------------------------------------------------------------------------
# Turn result
# ---------------------------------------------------------------------------

@dataclass
class _TurnResult:
    """Result of a single streaming turn (text + optional tool calls)."""
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class OllamaAgent(AgentProcess):
    """HTTP-based agent that talks to a local Ollama daemon.

    Each instance maintains its own chat history and can be configured
    with a different model, system prompt, and display name. Extends
    ``AgentProcess`` for shared lifecycle plumbing (lock, task tracking,
    heartbeat, RSS monitor, cancel) so all connectors present the same
    interface to the router.
    """

    RESTART_KEY = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "qwen2.5-coder:7b",  # default; 3b removed
        display_name: str = "Local Bro",
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        temperature: float = 0.1,
        context_window: int = 8192,
        project_dir: Path | None = None,
        write_access: bool = True,
        tools_enabled: bool = True,
    ) -> None:
        super().__init__()
        self.DISPLAY_NAME = display_name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.display_name = display_name
        self.temperature = temperature
        self.context_window = context_window
        self.project_dir = project_dir
        self._write_access = write_access
        self._tools_enabled = tools_enabled

        self._history: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]
        self._client: httpx.AsyncClient | None = None
        self._cancelled = False
        # Cross-talk via SESSION.md live-stream tail (Phase 1 unification).
        # ``_session_log_path`` points at ``<project_dir>/SESSION.md`` and
        # ``_sibling_target`` is the ``big`` / ``bro`` label on SESSION.md
        # lines that this agent should pick up as sibling activity.
        self._session_log_path: Path | None = None
        self._sibling_target: str = ""
        self._sibling_name: str = ""
        self._sibling_agent: "OllamaAgent | None" = None
        self._sibling_panel: "_BasePanel | None" = None
        # Ollama-specific heartbeat task (30 s cadence, streaming-aware).
        self._heartbeat_task: asyncio.Task | None = None
        # Track whether this bro is currently busy (for idle roast logic).
        self._busy = False
        # True while actively receiving streamed chunks — heartbeat skips.
        self._streaming = False

    # -----------------------------------------------------------------
    # Permission control
    # -----------------------------------------------------------------

    def set_write_access(self, enabled: bool) -> None:
        """Toggle write access (used by /bunkbed)."""
        self._write_access = enabled

    def set_sibling(self, panel: "_BasePanel", name: str, agent: "OllamaAgent | None" = None) -> None:
        """Give this agent a live view of its sibling's panel."""
        self._sibling_name = name
        self._sibling_agent = agent
        self._sibling_panel = panel  # for live struggle notifications

    def set_session_log(self, path: Path, sibling_target: str) -> None:
        """Point this agent at the shared ``SESSION.md`` tail.

        ``sibling_target`` is the pane label (``"big"`` or ``"bro"``) whose
        ``AGENT`` / ``TOOL`` / ``FILE`` lines we should surface back to this
        agent as sibling context. Any prior ``BROS_LOG.md`` wiring is
        ignored once this has been set — SESSION.md is now the unified
        cross-talk layer across all backends.
        """
        self._session_log_path = path
        self._sibling_target = sibling_target

    def set_bros_log(self, path: Path) -> None:  # noqa: ARG002
        """Legacy no-op kept for call-site parity.

        Cross-talk moved from ``BROS_LOG.md`` to ``SESSION.md`` in Phase 1.
        Callers should use :meth:`set_session_log` instead.
        """
        return

    def update_system_prompt(self, prompt: str) -> None:
        """Replace the system prompt in history."""
        if self._history and self._history[0].get("role") == "system":
            self._history[0] = {"role": "system", "content": prompt}
        else:
            self._history.insert(0, {"role": "system", "content": prompt})

    # -----------------------------------------------------------------
    # Lifecycle
    # -----------------------------------------------------------------

    async def start(self) -> None:
        """Initialize the HTTP client."""
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0),
        )

    async def stop(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def send_intro(self, panel: "_BasePanel") -> None:
        """Post the YERRR intro message to the panel."""
        from src_local.agents.phrases import BIG_BRO_INTRO, LIL_BRO_INTRO
        if "Big" in self.display_name:
            panel.append_intro(BIG_BRO_INTRO)
        else:
            panel.append_intro(LIL_BRO_INTRO)

    async def _heartbeat_watch(self, panel: "_BasePanel") -> None:
        """Post rotating working phrases while a turn runs.

        Only posts when the model is NOT actively streaming text — i.e.,
        during tool execution pauses or while waiting for the model to
        start generating. Never interrupts mid-output.
        """
        from src_local.agents.phrases import get_working_phrase
        who = "big" if "Big" in self.display_name else "bro"
        try:
            while True:
                await asyncio.sleep(30)
                if self._last_activity_at is None:
                    return
                # Don't inject while the model is actively streaming text.
                if self._streaming:
                    continue
                msg = get_working_phrase(who)
                panel.append_system(f"({msg})")
        except asyncio.CancelledError:
            pass

    async def _confirm_command(self, command: str, panel: "_BasePanel") -> bool:
        """Show a modal asking the user to approve a shell command.

        Returns True if approved, False if denied.
        """
        import asyncio as _aio
        from src_local.ui.confirm_command import ConfirmCommandScreen

        future: _aio.Future[bool] = _aio.get_running_loop().create_future()

        def _on_result(approved: bool | None) -> None:
            if not future.done():
                future.set_result(bool(approved))

        try:
            panel.app.push_screen(ConfirmCommandScreen(command), _on_result)
        except Exception:  # noqa: BLE001
            # If the modal can't be shown (e.g., headless), deny by default.
            return False
        return await future

    async def _request_locked(self, prompt: str, panel: "_BasePanel") -> None:
        async with self._lock:
            self._turn_started_at = time.monotonic()
            self._last_activity_at = time.monotonic()
            self._cancelled = False
            self._busy = True
            # Start Ollama's 30 s streaming-aware heartbeat watcher.
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_watch(panel),
                name=f"{self.display_name}-heartbeat",
            )
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
                    f"{self.display_name} timed out (300s). "
                    "The model may be too large for your hardware."
                )
            except Exception as exc:
                logger.exception("%s crashed during turn", self.display_name)
                panel.append_error(f"{self.display_name} error: {exc}")
            finally:
                self._turn_started_at = None
                self._last_activity_at = None
                self._busy = False
                if self._heartbeat_task and not self._heartbeat_task.done():
                    self._heartbeat_task.cancel()
                self._heartbeat_task = None

    # -----------------------------------------------------------------
    # Hybrid Bible Retrieval (Grandpa)
    # -----------------------------------------------------------------
    # Two retrieval paths:
    #   1. Pre-retrieve: keyword match on raw user query (fast, dumb)
    #   2. Model-retrieve: model calls coding_lookup/reasoning_lookup
    #      tools with a smarter, inferred query
    # Results merge: overlapping entries = HIGH confidence (★),
    # unique entries from either path = included but lower confidence.
    # The merged set is injected AFTER the model's tool calls return.

    def _is_technical_query(self, prompt: str) -> bool:
        """Check if a prompt is technical enough to warrant Grandpa lookup."""
        stripped = prompt.strip()
        if stripped.startswith("/") or len(stripped) < 15:
            return False

        # Always skip meta / identity questions — not code-related
        lower = stripped.lower()
        meta_patterns = (
            "big bro", "lil bro", "bro is doing", "what are you",
            "who are you", "your name", "how are you", "doing today",
            "shared log", "bunkbed", "workspace", "session",
            "slower", "faster", "speed", "why do you", "respond",
        )
        if any(pat in lower for pat in meta_patterns):
            return False

        casual_starts = (
            "hi", "hey", "hello", "thanks", "thank", "ok", "yes", "no",
            "sure", "cool", "nice", "good", "great", "lol", "haha",
            "what", "how", "who", "where", "when", "why", "can", "do",
            "are", "is", "you", "did", "have", "tell", "show",
        )
        first_word = stripped.split()[0].lower().rstrip("!.,?")
        if first_word in casual_starts:
            # Only unambiguously technical words — no common English doubles
            technical_signals = (
                "code", "function", "class", "method", "implement",
                "create", "build", "fix", "bug", "error",
                "explain", "example", "pattern",
                "algorithm", "sort", "search", "binary tree", "graph",
                "debug", "traceback", "stack trace", "exception", "import",
                "decorator", "async", "await", "thread", "subprocess",
                "api", "endpoint", "database", "sql",
                "pytest", "unittest", "assert", "mock",
                "refactor", "optimize",
                "recursion", "recursive", "iterate", "parse", "serialize",
                "python", "javascript", "typescript", "html", "css", "json",
                "variable", "integer", "float",
                "dict", "tuple", "ndarray", "struct", "enum",
                "dockerfile", "kubernetes", "git", "regex",
            )
            if not any(sig in lower for sig in technical_signals):
                return False

        # Need at least 3 strong technical signals OR 1 unambiguous keyword
        # to avoid firing Grandpa on casual questions that mention a tech word
        unambiguous = (
            "def ", "class ", "import ", "->", "self.", "__init__",
            "return ", "async def", "await ", "try:", "except ",
            "dockerfile", "pytest", "traceback", "recursion",
        )
        if any(sig in lower for sig in unambiguous):
            return True

        # For everything else: require 2+ technical signals to confirm intent
        technical_signals_all = (
            "code", "function", "class", "method", "implement",
            "build", "fix", "bug", "error", "exception",
            "algorithm", "sort", "search", "debug", "import",
            "decorator", "async", "await", "thread",
            "api", "endpoint", "database", "sql",
            "test", "assert", "mock", "refactor", "optimize",
            "recursive", "iterate", "parse", "serialize",
            "python", "javascript", "html", "css", "json",
            "variable", "integer", "float", "dict", "tuple",
        )
        hits = sum(1 for sig in technical_signals_all if sig in lower)
        return hits >= 2

    def _pre_retrieve(self, prompt: str, panel: "_BasePanel") -> None:
        """Phase 1 of hybrid retrieval: keyword-match pull.

        Runs BEFORE the model sees the message. Stores candidates on the
        instance so they can be merged with the model's tool-call results
        later. Does NOT inject into the prompt yet.
        """
        self._pre_retrieved_ids: set[str] = set()
        self._pre_retrieved_chunks: dict[str, Any] = {}

        if not self._is_technical_query(prompt):
            return

        try:
            from src_local.bibles.store import get_bible_store
            store = get_bible_store()

            # Pull 10 from each bible — wider net for merge scoring.
            coding_hits = store.coding_lookup(prompt, top_k=10)
            reasoning_hits = store.reasoning_lookup(prompt, top_k=10)

            all_hits = coding_hits + reasoning_hits
            if not all_hits:
                return

            for chunk in all_hits:
                self._pre_retrieved_ids.add(chunk.id)
                self._pre_retrieved_chunks[chunk.id] = chunk

            panel.append_file_action(
                "Grandpa (pre-scan)",
                f"{len(all_hits)} candidates held for merge",
            )

        except Exception:  # noqa: BLE001
            logger.debug("Pre-retrieve failed", exc_info=True)

    def merge_bible_results(
        self, model_chunks: list, panel: "_BasePanel"
    ) -> str:
        """Phase 2 of hybrid retrieval: merge pre-retrieved + model-retrieved.

        Called from the tool executors after the model's lookup returns.
        Scores overlapping entries higher (★ HIGH CONFIDENCE).

        Returns formatted context string for injection into model history.
        """
        pre_ids = getattr(self, "_pre_retrieved_ids", set())
        pre_chunks = getattr(self, "_pre_retrieved_chunks", {})

        # Separate into confidence tiers.
        high_confidence = []   # in BOTH pre-retrieve and model-retrieve
        model_only = []        # model found, pre-retrieve missed
        pre_only = []          # pre-retrieve found, model missed

        model_ids = set()
        for chunk in model_chunks:
            model_ids.add(chunk.id)
            if chunk.id in pre_ids:
                high_confidence.append(chunk)
            else:
                model_only.append(chunk)

        for cid, chunk in pre_chunks.items():
            if cid not in model_ids:
                pre_only.append(chunk)

        # Build context: high confidence first, then model-only, then pre-only.
        parts: list[str] = []
        if high_confidence:
            parts.append("=== ★ HIGH CONFIDENCE (both retrievers agree) ===")
            for chunk in high_confidence:
                parts.append(chunk.to_context())
            parts.append("")
        if model_only:
            parts.append("=== Model-retrieved ===")
            for chunk in model_only[:5]:  # cap to avoid context bloat
                parts.append(chunk.to_context())
            parts.append("")
        if pre_only:
            parts.append("=== Additional references (keyword match) ===")
            for chunk in pre_only[:5]:  # cap
                parts.append(chunk.to_context())
            parts.append("")

        n_high = len(high_confidence)
        n_total = n_high + len(model_only) + min(len(pre_only), 5)
        if n_high > 0:
            panel.append_file_action(
                "Grandpa (merged)",
                f"{n_total} refs ({n_high} ★ high confidence)",
            )
        elif n_total > 0:
            panel.append_file_action(
                "Grandpa (merged)",
                f"{n_total} references",
            )

        return "\n".join(parts)

    def _inject_bible_context(self, prompt: str, panel: "_BasePanel") -> str:
        """Fallback injection for when the model doesn't call Grandpa tools.

        Uses the pre-retrieved candidates directly. This ensures even
        models that can't/won't use tools still get Grandpa context.
        Called at the END of the tool loop if no bible tools were invoked.
        """
        pre_chunks = getattr(self, "_pre_retrieved_chunks", {})
        if not pre_chunks:
            return prompt

        # Use pre-retrieved chunks directly as fallback.
        parts: list[str] = ["=== Grandpa's References (auto-retrieved) ==="]
        for chunk in list(pre_chunks.values())[:10]:
            parts.append(chunk.to_context())
        parts.append("")

        bible_context = "\n".join(parts)
        panel.append_file_action(
            "Grandpa (fallback)",
            f"{min(len(pre_chunks), 10)} references auto-injected",
        )

        return (
            f"[Reference material from Grandpa — use this to ground your answer.]\n"
            f"{bible_context}\n"
            f"[User's question]\n{prompt}"
        )

    def _inject_sibling_context(self, prompt: str) -> str:
        """Peek at ``SESSION.md`` to see what the sibling pane has been up to.

        All backends (Ollama, Claude, Codex) write live breadcrumbs to a
        shared ``SESSION.md`` ``## Live Stream`` section — one line per
        event in the shape ``[HH:MM:SS] KIND target: body``. We grep the
        tail for lines whose ``target`` matches the sibling and inject a
        handful into this turn's prompt so Ollama has the same
        peripheral awareness a cloud connector gets from its briefing.
        """
        if self._session_log_path is None or not self._sibling_target:
            return prompt
        if not self._session_log_path.exists():
            return prompt
        try:
            content = self._session_log_path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return prompt
        if not content.strip():
            return prompt

        # Only surface meaningful sibling activity. USER lines are the
        # human talking, SESSION banners are boilerplate — skipping them
        # keeps the injected context tight.
        target_tag = f" {self._sibling_target}:"
        kinds_to_keep = ("AGENT", "TOOL", "FILE", "CMD", "ERROR", "DECISION")
        sibling_lines: list[str] = []
        for line in content.splitlines():
            if target_tag not in line:
                continue
            # Strip the timestamp to sniff the kind: ``[HH:MM:SS] KIND target: ...``
            stripped = line.split("] ", 1)[-1]
            if not any(stripped.startswith(k) for k in kinds_to_keep):
                continue
            sibling_lines.append(line)

        if not sibling_lines:
            return prompt

        recent = sibling_lines[-5:]
        sibling_summary = "\n".join(recent)
        if len(sibling_summary) > 800:
            sibling_summary = sibling_summary[-800:]
        sib = self._sibling_name or "the other pane"
        return (
            f"[What {sib} has been working on — tail of SESSION.md live stream]\n"
            f"{sibling_summary}\n\n"
            f"{prompt}"
        )

    def _log_turn_summary(self, prompt: str, response: str) -> None:  # noqa: ARG002
        """Deprecated — turn summaries now flow through SESSION.md.

        The JournalRecorder streams every ``AGENT`` line to
        ``SESSION.md`` automatically, so the old BROS_LOG double-write is
        redundant. Kept as a no-op so the per-turn call site stays
        unchanged until Phase 1 wiring is fully torn out.
        """
        return

    def _notify_sibling_struggling(self, panel: "_BasePanel", prompt: str) -> None:
        """Tell the sibling bro — live — that this bro is having trouble."""
        _sibling_name = self._sibling_name or "the other bro"  # noqa: F841
        my_name = self.display_name
        short_prompt = prompt[:60].replace("\n", " ").strip()
        if len(prompt) > 60:
            short_prompt += "..."

        # Post in THIS bro's panel as a heads-up.
        panel.append_system(
            "(hitting some errors on this — gonna try one more approach...)"
        )

        # Post in the SIBLING'S panel so they see it live.
        if self._sibling_panel is not None:
            # Pick a compassionate/snarky sibling reaction.
            sibling_comments = [
                f"yo, {my_name} is struggling over there lol. working on: '{short_prompt}'",
                f"{my_name} keeps getting errors. classic. trying one more time...",
                f"heads up — {my_name} is hitting walls on '{short_prompt}'. give it a sec.",
                f"not gonna lie, {my_name} is having a moment. they'll figure it out. maybe.",
                f"{my_name}: *error* *error* *error*. they said they got this though.",
            ]
            comment = random.choice(sibling_comments)
            try:
                self._sibling_panel.append_system(f"({comment})")
            except Exception:  # noqa: BLE001
                pass

    # -----------------------------------------------------------------
    # Streaming with tool loop
    # -----------------------------------------------------------------

    def _build_payload(self) -> dict:
        """Build the /api/chat payload from current history + config."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": self._history,
            "stream": True,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_window,
            },
        }
        # Add tool schemas if tools are enabled and we have a project dir.
        if self._tools_enabled and self.project_dir is not None:
            from src_local.agents.tools import get_tool_schemas
            schemas = get_tool_schemas(write_access=self._write_access)
            if schemas:
                payload["tools"] = schemas
        return payload

    async def _stream_reply(self, prompt: str, panel: "_BasePanel") -> None:
        """Send prompt to Ollama, handle tool calls, stream text to panel.

        This is the main turn loop. It:
        1. Auto-injects bible context (Grandpa) into the prompt
        2. Adds the user message to history
        3. Sends the payload (with tool schemas) to Ollama
        4. Streams text chunks to the panel
        5. If the model returns tool_calls, executes them and loops back
        6. Repeats until the model returns a final text response (no tools)
        """
        if self._client is None:
            panel.append_error(f"{self.display_name} not started — call start() first")
            return

        # Phase 1 of hybrid retrieval: pre-retrieve candidates by keyword.
        # These are held (not injected) until we see if the model also
        # calls Grandpa tools. If it does, results merge. If not, we
        # fall back to injecting pre-retrieved candidates directly.
        self._pre_retrieve(prompt, panel)

        # Inject sibling's last reply so the bros can see each other.
        enriched_prompt = self._inject_sibling_context(prompt)

        # Add user message to history.
        self._history.append({"role": "user", "content": enriched_prompt})
        self._trim_history()

        max_tool_rounds = 10
        consecutive_errors = 0   # how many tool calls returned errors in a row
        _WARN_AT = 4             # warn sibling at this many consecutive errors
        _ABORT_AT = 5            # give up and stop at this many
        _last_tool_sig: str = ""  # detect duplicate tool call loops
        _dup_count = 0
        _bible_tool_used = False  # track if model called Grandpa

        for _round in range(max_tool_rounds):
            if self._cancelled:
                break

            payload = self._build_payload()
            result = await self._stream_one_turn(payload, panel)

            if not result.tool_calls:
                # Final text response — no more tool calls.
                # If the model never called Grandpa tools AND we have
                # pre-retrieved candidates, inject them as fallback and
                # do one more turn so the model sees the context.
                pre_chunks = getattr(self, "_pre_retrieved_chunks", {})
                if not _bible_tool_used and result.text and len(pre_chunks) >= 3:
                    fallback = self._inject_bible_context(prompt, panel)
                    if fallback != prompt:
                        # Inject Grandpa context and ask model to reconsider.
                        self._history.append({"role": "assistant", "content": result.text})
                        self._history.append({
                            "role": "user",
                            "content": (
                                f"{fallback}\n\n"
                                "Grandpa's references were just loaded above. "
                                "Review them and refine your answer if they contain "
                                "relevant patterns or techniques you missed."
                            ),
                        })
                        self._trim_history()
                        _bible_tool_used = True  # don't loop again
                        continue  # one more turn with Grandpa context

                if result.text:
                    self._history.append({"role": "assistant", "content": result.text})
                    self._log_turn_summary(prompt, result.text)
                break

            # Detect duplicate tool call loops (3b models get stuck).
            tool_sig = json.dumps(
                [(tc.get("function", {}).get("name"), tc.get("function", {}).get("arguments"))
                 for tc in result.tool_calls],
                sort_keys=True,
            )
            if tool_sig == _last_tool_sig:
                _dup_count += 1
                if _dup_count >= 2:
                    panel.append_system(
                        "(stuck in a tool loop — breaking out and answering with what I have)"
                    )
                    if result.text:
                        self._history.append({"role": "assistant", "content": result.text})
                    break
            else:
                _dup_count = 0
            _last_tool_sig = tool_sig

            # Model wants to call tools.
            # Add the assistant message (with tool_calls) to history.
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if result.text:
                assistant_msg["content"] = result.text
            else:
                assistant_msg["content"] = ""
            assistant_msg["tool_calls"] = result.tool_calls
            self._history.append(assistant_msg)

            # Execute each tool call and add results to history.
            from src_local.agents.tools import execute_tool, TOOL_DISPLAY_LABELS, BIBLE_TOOLS

            round_had_error = False
            for tc in result.tool_calls:
                fn = tc.get("function", {})
                tool_name = fn.get("name", "unknown")
                tool_args = fn.get("arguments", {})

                # Parse arguments if they came as a JSON string.
                if isinstance(tool_args, str):
                    try:
                        tool_args = json.loads(tool_args)
                    except json.JSONDecodeError:
                        tool_args = {}

                path_arg = tool_args.get("path") or tool_args.get("command", "")
                label = TOOL_DISPLAY_LABELS.get(tool_name, tool_name)

                # run_command requires user confirmation before execution.
                if tool_name == "run_command":
                    approved = await self._confirm_command(
                        tool_args.get("command", ""), panel
                    )
                    if not approved:
                        tool_result = "Error: command denied by user."
                        panel.append_system("(command denied)")
                    else:
                        tool_result = await execute_tool(
                            tool_name, tool_args,
                            project_dir=self.project_dir,
                            write_access=self._write_access,
                        )
                else:
                    # Execute the tool.
                    tool_result = await execute_tool(
                        tool_name,
                        tool_args,
                        project_dir=self.project_dir,
                        write_access=self._write_access,
                    )

                # Hybrid merge: if this is a bible tool, merge with
                # pre-retrieved candidates for confidence scoring.
                if tool_name in BIBLE_TOOLS:
                    _bible_tool_used = True
                    try:
                        from src_local.bibles.store import get_bible_store
                        store = get_bible_store()
                        query = tool_args.get("query", "")
                        if query:
                            bible = "coding" if tool_name == "coding_lookup" else "reasoning"
                            model_chunks = store.lookup(query, bible=bible, top_k=10)
                            merged = self.merge_bible_results(model_chunks, panel)
                            if merged.strip():
                                tool_result = merged
                    except Exception:  # noqa: BLE001
                        pass  # fall through to raw tool result

                # Track errors for the retry/failure system.
                if tool_result.startswith("Error:"):
                    round_had_error = True

                # Mount a yellow collapsible block — summary when collapsed,
                # full output on click. For edits, prepend a unified diff.
                try:
                    summary = f"{label} {path_arg}".strip() or label
                    detail = tool_result
                    if tool_name == "edit_file" and "old_string" in tool_args:
                        import difflib
                        diff_lines = list(
                            difflib.unified_diff(
                                tool_args["old_string"].splitlines(keepends=True),
                                tool_args.get("new_string", "").splitlines(keepends=True),
                                fromfile="before",
                                tofile="after",
                                n=3,
                            )
                        )
                        if diff_lines:
                            diff_text = "".join(diff_lines)
                            detail = f"--- diff ---\n{diff_text}\n--- result ---\n{tool_result}"
                    panel.append_tool_call(
                        summary,
                        detail=detail,
                        path=str(path_arg) if path_arg else None,
                    )
                except Exception:  # noqa: BLE001
                    pass

                # Add tool result to history.
                self._history.append({
                    "role": "tool",
                    "content": tool_result,
                })

                logger.debug(
                    "tool %s(%s) -> %d chars",
                    tool_name,
                    path_arg,
                    len(tool_result),
                )

            # Track consecutive error rounds.
            if round_had_error:
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            # Warn the sibling at _WARN_AT errors.
            if consecutive_errors == _WARN_AT:
                self._notify_sibling_struggling(panel, prompt)

            # Abort at _ABORT_AT — don't write any more, tell the user.
            if consecutive_errors >= _ABORT_AT:
                panel.append_system(
                    f"({self.display_name} hit {_ABORT_AT} consecutive errors — stopping. "
                    f"I don't want to write bad code. Tell me more about what you need "
                    f"or check the error above and I'll try a different approach.)"
                )
                break

            # Loop back — the model will see tool results and continue.
            self._trim_history()

    async def _stream_one_turn(
        self, payload: dict, panel: "_BasePanel"
    ) -> _TurnResult:
        """Send one request to Ollama and stream the response.

        Returns a _TurnResult with accumulated text and any tool calls.
        """
        full_response: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        panel.start_agent_stream()
        self._streaming = True

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
                    return _TurnResult()

                async for line in response.aiter_lines():
                    if self._cancelled:
                        break
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    msg = chunk.get("message", {})

                    # Stream text content.
                    content = msg.get("content", "")
                    if content:
                        full_response.append(content)
                        panel.append_agent_chunk(content)
                        self.note_activity()

                    # Collect tool calls (typically in the final chunk).
                    # Structured API (works on 7b+ models).
                    if msg.get("tool_calls"):
                        tool_calls.extend(msg["tool_calls"])

                    if chunk.get("done", False):
                        break
        finally:
            self._streaming = False
            full_text = "".join(full_response)
            panel.mark_assistant_complete(full_text)

        # Fallback: small models (3b) can't use structured tool-calling API
        # and instead output tool call JSON as plain text in message.content.
        # If we got no structured tool_calls but the text looks like a tool
        # call block, extract it here so the tool loop still runs.
        if not tool_calls and full_text.strip():
            extracted, cleaned_text = _extract_text_tool_calls(full_text)
            if extracted:
                tool_calls = extracted
                # Replace the streamed text with the cleaned version so the
                # raw JSON block doesn't stay visible in the panel.
                # We can't un-stream, but we mark the turn as a tool turn
                # by returning empty text — the panel already has the raw
                # content but _stream_reply won't add it to history as a
                # final assistant message.
                full_text = cleaned_text

        return _TurnResult(
            text=full_text,
            tool_calls=tool_calls,
        )

    # -----------------------------------------------------------------
    # History management
    # -----------------------------------------------------------------

    def _trim_history(self) -> None:
        """Keep conversation history manageable.

        Preserves the system prompt (index 0) and the most recent
        turns. Aggressive trimming for small models that degrade
        with long contexts.
        """
        max_messages = 30  # bumped from 20 to accommodate tool call/result pairs
        if len(self._history) <= max_messages:
            return
        system = self._history[0]
        recent = self._history[-(max_messages - 1):]
        self._history = [system] + recent

    def cancel_in_flight(self) -> bool:
        """Cancel the currently-running turn.

        Sets ``_cancelled`` first so the inline stream loop can drop
        further chunks even if the asyncio.Task cancellation hasn't
        propagated yet, then delegates to the base-class implementation.
        """
        self._cancelled = True
        return super().cancel_in_flight()

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
