"""Slash command dispatcher for LIL BRO LOCAL.

Ported from the cloud LIL BRO handler with local-specific adaptations:
- Ollama agents instead of Claude/Codex CLI subprocesses
- ~/.lilbro-local/ paths instead of ~/.lilbro/
- Big Bro / Lil Bro naming (coder / helper)
- Local-specific commands: /model, /models, /status, /history
- Removed: /restart, /slow-mode, /quiet (subprocess-specific)

Commands:
- /quit, /exit           -- clean shutdown
- /explain <topic>       -- structured teaching prompt, forced to Lil Bro
- /plan                  -- forces Big Bro to outline steps before coding
- /focus <task> / /focus -- pin or clear a current goal
- /save [name]           -- write the journal to disk
- /load [name]           -- list recent journals, open the latest or a match
- /journal               -- show where the journal is saved
- /reset                 -- clear Lil Bro's thread (fresh conversation, same process)
- /review                -- structured code review of Big Bro's last message, routed to Lil Bro
- /debug <error>         -- structured debug walkthrough routed to Lil Bro
- /review-file <path>    -- structured file review routed to Lil Bro
- /compare <a> | <b>     -- compare/contrast two topics
- /explain-diff          -- teach through Big Bro's last change
- /trace <symbol>        -- walk a call graph around a symbol
- /wrap                  -- toggle soft word-wrap
- /find <query>          -- grep across saved journals
- /debug-dump            -- bundle diagnostic artifacts into a zip
- /session               -- show SESSION.md tail
- /session-save <name>   -- bookmark the current project dir
- /session-open <name>   -- show info for a saved session
- /sessions              -- list all saved sessions
- /export-html           -- convert the current journal to HTML
- /skills                -- list installed skills
- /player                -- RPG progression card
- /campaign              -- campaign map / status
- /quest <id>            -- start a quest
- /teach                 -- toggle teach mode
- /submit <text>         -- validate against active quest
- /hint                  -- quest hint
- /skip                  -- skip active quest
- /model [a|b] <name>    -- show/switch Ollama model
- /models                -- list available Ollama models
- /status                -- show current config + agent state
- /history clear         -- clear conversation history
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from typing import TYPE_CHECKING, Awaitable, Callable

from src_local.router import Target  # noqa: TC002
from src_local.skills import find_skill, list_skills, read_md_skill, run_py_skill

if TYPE_CHECKING:
    from src_local.agents.ollama_agent import OllamaAgent
    from src_local.journal.recorder import JournalRecorder
    from src_local.ui.panels import _BasePanel
    from src_local.ui.status_bar import StatusBar


@dataclass
class CommandResult:
    bypass_agent: bool = True
    message: str = ""
    forced_target: Target | None = None
    rewritten_prompt: str | None = None
    quit: bool = False
    show_help: bool = False
    show_settings: bool = False
    clear_panel: bool = False
    toggle_wrap: bool = False
    # Set to True by /session so the router knows to scan the dumped
    # SESSION.md tail for the most recent ``AGENT <role>:`` line and
    # populate the active panel's ``_last_assistant_message`` -- without
    # this, content replayed into the panel is visible but un-portable.
    ingest_session_dump: bool = False
    # Optional coroutine factory run by the router AFTER the message is
    # shown. Used by commands that need to do async work like switching
    # an agent's model.
    async_work: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    # Used by .md skills: the prompt text to forward to the active agent.
    prompt: str | None = None
    # Used by .py skills when called inside the running event loop: a
    # coroutine that resolves to a CommandResult with the final output.
    skill_coro: "Awaitable[CommandResult] | None" = field(default=None, repr=False)
    # RPG banners -- level-up / skill-up / badge-unlock lines emitted by
    # ``SkillTracker.tag`` + ``check_badges``. The router drains these
    # into the active panel as ``append_system`` lines after the command
    # executes, so XP feedback shows up next to the command that earned
    # it. Empty on commands that don't award XP.
    banners: list[str] = field(default_factory=list)
    # Phase 20 -- set by /campaign so the router pushes the
    # CampaignMapScreen modal. Kept here (not in bypass plumbing) so
    # every command path can opt in uniformly.
    show_campaign_map: bool = False


EXPLAIN_TEMPLATE = """\
You are Lil Bro, a patient teacher pairing with a developer who's learning. \
Explain the topic below with a compact, structured breakdown. Use exactly \
these six sections in this order, with the headers verbatim (one blank line \
between sections, no extra preamble, no closing summary):

**What**
One or two sentences, plain English, no jargon. Define the topic as if the \
reader has never seen it before.

**Why**
What problem does it solve? Why was it invented, or why does it exist in \
the language / framework / system?

**Analogy**
A concrete real-world analogy that maps cleanly to the mechanics. Keep it \
short -- two or three sentences.

**How**
The mechanics. A tiny code snippet is fine if it clarifies, but keep prose \
tight. Walk through what actually happens step by step.

**Pattern**
When you should reach for this, and how to recognize the situation in your \
own code. Include one "if you see X, consider Y" rule of thumb.

**Tip**
One common mistake, gotcha, or pro tip that trips people up. Keep it to one \
or two sentences.

Topic: {topic}
"""


PLAN_TEMPLATE = """\
Before writing any code, plan this task carefully. Follow this process:

1. UNDERSTAND: Read the task. If anything is unclear or ambiguous, list what \
you need clarified BEFORE planning. Ask the user.

2. RESEARCH: Use your tools to examine the current codebase. Read relevant \
files. Check with Grandpa (coding_lookup and reasoning_lookup) for best \
practices and patterns that apply. Do NOT skip this step.

3. PLAN: Only after steps 1-2, write the plan using these sections:

**Goal**
One sentence: what "done" looks like.

**Steps**
A numbered list (3-7 items) of the concrete steps you'll take, in order. \
Each step should name specific files and what changes to make.

**Files to touch**
Bullet list of file paths you expect to create or modify. If unknown, say so.

**Grandpa says**
What relevant patterns, best practices, or warnings Grandpa's knowledge \
surfaced for this task.

**Risks**
One or two bullets on what could go wrong or trip this up.

**Check-in**
One sentence describing what you'll verify after implementing, before moving on.

IMPORTANT: Do NOT make up file paths or code patterns you haven't verified. \
If you're unsure about the codebase structure, read it first. \
After this outline, wait for my confirmation before writing any code.

Task: {task}
"""


REVIEW_TEMPLATE = """\
You are Lil Bro, a thoughtful code reviewer. Review the code or response below \
from Big Bro. Be concise and specific. Use exactly these four \
sections in order:

**Correctness**
Any bugs, logic errors, edge cases, or incorrect assumptions. If none, say "Looks correct."

**Edge cases**
Inputs or states that could break this. If well-handled, say so briefly.

**Style / clarity**
Anything that's hard to read, poorly named, or would confuse a future reader. \
Keep it short -- one or two bullets max.

**Suggestion**
The single most impactful improvement you'd make, with a concrete example if \
useful. If it's already solid, say so.

Code / response to review:
{content}
"""


DEBUG_TEMPLATE = """\
You are Lil Bro, a debugging partner. Walk through the error below step by step. \
Use exactly these four sections in order:

**What failed**
One sentence: what the error is saying in plain English.

**Where**
The file, line, or call site most likely responsible. If a stack trace is \
included, point to the relevant frame.

**Why**
The root cause -- what condition triggered this error.

**Fix**
The concrete change needed to resolve it. If there are multiple possible causes, \
list them in order of likelihood.

Error / stack trace:
{error}
"""


REVIEW_FILE_TEMPLATE = """\
You are Lil Bro, a thoughtful code reviewer. Read the file at the path below \
using your read-only tools, then review it end-to-end. Be concise and specific -- \
this is a focused review, not a design doc. Use exactly these five sections in \
order, with the headers verbatim:

**Purpose**
One or two sentences: what this file is for, in plain English.

**Correctness**
Any bugs, logic errors, edge cases, or incorrect assumptions you found while \
reading. If none, say "Looks correct." Reference line numbers when useful.

**Edge cases**
Inputs, states, or environments that could break this file. If well-handled, \
say so briefly.

**Style / clarity**
Anything that's hard to read, poorly named, or would confuse a future reader. \
Keep it short -- two bullets max.

**Top suggestion**
The single most impactful improvement you'd make, with a concrete example if \
useful. If it's already solid, say so and stop.

File to review: {path}
"""


COMPARE_TEMPLATE = """\
You are Lil Bro, a patient teacher. Compare and contrast the two topics below. \
Use exactly these four sections in this order, with the headers verbatim (one \
blank line between sections, no extra preamble, no closing summary):

**What each is**
Two short paragraphs -- one per topic -- defining each in plain English for \
someone who hasn't seen them before.

**How they're similar**
A tight bullet list of the genuine overlaps. Don't reach -- if they barely \
overlap, say so in one sentence.

**How they differ**
A side-by-side bullet list of the real differences. Include a small concrete \
example or snippet if it clarifies.

**When to pick which**
A one-sentence rule of thumb for each ("use A when ...", "use B when ..."). \
If one is almost always the right choice, say so.

Topic A: {topic_a}
Topic B: {topic_b}
"""


TRACE_TEMPLATE = """\
You are Lil Bro, a code navigation helper. Use your read-only tools \
(grep / ripgrep / file reads) to walk the call graph around the symbol \
below in the current project. Be concise -- this is a navigation aid, not \
a design review.

Project directory: {project}
Symbol: {symbol}

Do the following, in order:

1. **Locate the definition.** Grep the project for where `{symbol}` is \
defined (a `def`, `class`, `function`, `fn`, `func`, or similar declaration). \
Report the file and line number. If there are multiple definitions, list \
them all, then pick the most likely primary one and mark it with "->".

2. **Find the callers.** Grep for references to `{symbol}` that are NOT \
the definition. Exclude comments and docstrings if you can. List up to 10 \
caller sites as `path:line` bullets. If there are more than 10, say so and \
pick the ten you think are most important to read first.

3. **List the callees.** Inside the body of `{symbol}`, identify every \
other function or method it calls (first-order only, no recursion). List \
them as bullets with a one-word category: `internal` (same file), `local` \
(same package), `stdlib`, `external`, or `unknown`.

4. **Render a tree.** Draw a compact ASCII tree in this exact shape:

    callers
    +-- caller_one  (path:line)
    +-- caller_two  (path:line)
    |
    +-- {symbol}  (def at path:line)
         +-- callee_one  [internal]
         +-- callee_two  [stdlib]
         +-- callee_three  [external]

5. **One-line summary.** Finish with a single sentence: "`{symbol}` is \
called from N places and delegates to M helpers -- primary role is ___." \
Fill in N, M, and the role.

Do NOT open anything outside the project directory. Do NOT attempt to \
edit anything -- you are read-only. If the symbol does not exist in the \
project, say so in one line and stop.
"""


EXPLAIN_DIFF_TEMPLATE = """\
You are Lil Bro, a patient teacher paired with a developer who's learning by \
watching Big Bro make changes. Explain the change below the \
way a senior reviewing a junior's PR would -- but teaching, not grading.

Use exactly these four sections in this order, with the headers verbatim:

**What changed**
One or two sentences: what Big Bro actually did, in plain English. Skip the \
literal diff -- describe the effect.

**Why this approach**
The reasoning behind the approach. What tradeoff or constraint made Big Bro \
pick this path over obvious alternatives?

**What to look for in the code**
Two or three concrete things the reader should notice when they read the \
changed files themselves -- names, patterns, idioms, structural moves.

**Concept worth stealing**
One takeaway the reader can apply to their own code in the future. Keep it to \
one or two sentences.

Change from Big Bro:
{content}
"""


class CommandHandler:
    """Dispatcher for LIL BRO LOCAL slash commands.

    Dependencies (``journal``, ``status_bar``, ``big_bro``, ``lil_bro``) are
    injected so commands can mutate session state cleanly. All are optional
    at construction time so tests that instantiate a bare handler keep working.
    """

    def __init__(
        self,
        journal: "JournalRecorder | None" = None,
        status_bar: "StatusBar | None" = None,
        big_bro: "OllamaAgent | None" = None,
        lil_bro: "OllamaAgent | None" = None,
        big_bro_panel: "_BasePanel | None" = None,
        lil_bro_panel: "_BasePanel | None" = None,
        project_dir: "Path | None" = None,
        player_profile: "object | None" = None,
        skill_tracker: "object | None" = None,
        challenge_manager: "object | None" = None,
        teach_mode: "object | None" = None,
        world: "object | None" = None,
        campaign_state: "object | None" = None,
        config: "object | None" = None,
    ) -> None:
        self.journal = journal
        self.status_bar = status_bar
        self.big_bro = big_bro
        self.lil_bro = lil_bro
        self.big_bro_panel = big_bro_panel
        self.lil_bro_panel = lil_bro_panel
        self.project_dir = project_dir
        self.player_profile = player_profile
        self.skill_tracker = skill_tracker
        self.challenge_manager = challenge_manager
        self.teach_mode = teach_mode
        self.world = world
        self.campaign_state = campaign_state
        self.config = config
        self._bunkbed: bool = False

    # -----------------------------------------------------------------
    # RPG award helper
    # -----------------------------------------------------------------

    def _award(self, action: str, *, concept: str | None = None) -> list[str]:
        """Award XP for *action* and return any level-up / badge banners.

        Never raises -- RPG failures must not break a command. Returns
        an empty list when the handler was constructed without a
        tracker (test path) or the action is unknown.
        """
        if self.skill_tracker is None or self.player_profile is None:
            return []
        try:
            report = self.skill_tracker.tag(action, concept=concept)
            banners = list(report.banners()) if report is not None else []
            try:
                from src_local.rpg.badges import check_badges
                for name in check_badges(self.player_profile, action):
                    banners.append(f"Badge unlocked: {name}")
            except Exception:  # noqa: BLE001
                pass
            return banners
        except Exception:  # noqa: BLE001
            return []

    # -----------------------------------------------------------------
    # Entry point
    # -----------------------------------------------------------------

    def handle(self, raw: str) -> CommandResult:
        parts = raw.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Baseline XP for every slash command.
        self._award("slash_command")

        if cmd in ("/quit", "/exit"):
            return CommandResult(bypass_agent=True, message="goodbye.", quit=True)

        if cmd in ("/help", "/?"):
            return CommandResult(bypass_agent=True, show_help=True)

        if cmd in ("/settings", "/config", "/prefs"):
            return CommandResult(bypass_agent=True, show_settings=True)

        if cmd in ("/clear", "/cls"):
            return CommandResult(bypass_agent=True, clear_panel=True)

        if cmd == "/explain":
            return self._cmd_explain(arg)

        if cmd == "/plan":
            return self._cmd_plan(arg)

        if cmd == "/focus":
            return self._cmd_focus(arg)

        if cmd == "/save":
            return self._cmd_save(arg)

        if cmd == "/load":
            return self._cmd_load(arg)

        if cmd == "/journal":
            return self._cmd_journal_info()

        if cmd in ("/cwd", "/pwd"):
            return self._cmd_cwd()

        if cmd == "/reset":
            return self._cmd_reset()

        if cmd == "/review":
            return self._cmd_review(arg)

        if cmd == "/debug":
            return self._cmd_debug(arg)

        if cmd == "/model":
            return self._cmd_model(arg)

        if cmd == "/models":
            return self._cmd_models()

        if cmd == "/status":
            return self._cmd_status()

        if cmd == "/history":
            return self._cmd_history(arg)

        if cmd == "/session":
            return self._cmd_session()

        if cmd == "/state":
            return self._cmd_state()

        if cmd in ("/review-file", "/reviewfile"):
            return self._cmd_review_file(arg)

        if cmd == "/compare":
            return self._cmd_compare(arg)

        if cmd in ("/explain-diff", "/explaindiff"):
            return self._cmd_explain_diff(arg)

        if cmd == "/trace":
            return self._cmd_trace(arg)

        if cmd == "/wrap":
            return self._cmd_wrap()

        if cmd == "/find":
            return self._cmd_find(arg)

        if cmd in ("/debug-dump", "/debugdump"):
            return self._cmd_debug_dump()

        if cmd in ("/session-save", "/sessionsave"):
            return self._cmd_session_save(arg)

        if cmd in ("/session-open", "/sessionopen"):
            return self._cmd_session_open(arg)

        if cmd == "/sessions":
            return self._cmd_sessions_list()

        if cmd in ("/export-html", "/exporthtml"):
            return self._cmd_export_html(arg)

        if cmd == "/skills":
            return self._cmd_skills_list()

        if cmd == "/player":
            return self._cmd_player()

        if cmd == "/campaign":
            return self._cmd_campaign(arg)

        if cmd == "/quest":
            return self._cmd_quest(arg)

        if cmd == "/teach":
            return self._cmd_teach(arg)

        if cmd == "/submit":
            return self._cmd_submit(arg)

        if cmd == "/hint":
            return self._cmd_hint()

        if cmd == "/skip":
            return self._cmd_skip()
        if cmd == "/bunkbed":
            return self._cmd_bunkbed()

        # Dynamic skill lookup -- /skill-name maps to ~/.lilbro-local/skills/skill_name.*
        skill_name = cmd.lstrip("/")
        skill_path = find_skill(skill_name)
        if skill_path is not None:
            return self._cmd_run_skill(skill_name, skill_path, arg)

        return CommandResult(bypass_agent=True, message=f"unknown command: {cmd}")

    # -----------------------------------------------------------------
    # Individual commands
    # -----------------------------------------------------------------

    def _cmd_explain(self, arg: str) -> CommandResult:
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="usage: /explain <topic>  (e.g. /explain list comprehensions)",
            )
        if self.journal is not None:
            self.journal.record("bro", "explain", arg)
        banners = self._award("explain_used", concept=arg.strip().split()[0].lower() if arg.strip() else None)
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=EXPLAIN_TEMPLATE.format(topic=arg),
            banners=banners,
        )

    def _cmd_plan(self, arg: str) -> CommandResult:
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="usage: /plan <task>  (Big Bro will outline steps first)",
            )
        if self.journal is not None:
            self.journal.note_decision(f"Plan requested: {arg}")
        banners = self._award("plan_before_code")
        return CommandResult(
            bypass_agent=False,
            forced_target="big",
            rewritten_prompt=PLAN_TEMPLATE.format(task=arg),
            banners=banners,
        )

    def _cmd_focus(self, arg: str) -> CommandResult:
        if not arg:
            if self.journal is not None:
                self.journal.set_focus(None)
            if self.status_bar is not None:
                self.status_bar.set_focus(None)
            return CommandResult(bypass_agent=True, message="focus cleared.")
        if self.journal is not None:
            self.journal.set_focus(arg)
        if self.status_bar is not None:
            self.status_bar.set_focus(arg)
        banners = self._award("focus_set")
        return CommandResult(
            bypass_agent=True,
            message=f"focus set: {arg}",
            banners=banners,
        )

    def _cmd_save(self, arg: str) -> CommandResult:
        if self.journal is None:
            return CommandResult(bypass_agent=True, message="journal not available.")
        try:
            path = self.journal.save(arg or None)
        except Exception as exc:  # noqa: BLE001
            return CommandResult(bypass_agent=True, message=f"save failed: {exc}")
        banners = self._award("journal_save")
        return CommandResult(
            bypass_agent=True,
            message=f"journal saved -> {path}",
            banners=banners,
        )

    def _cmd_load(self, arg: str) -> CommandResult:
        if self.journal is None:
            return CommandResult(bypass_agent=True, message="journal not available.")
        journals = self.journal.list_journals()
        if not journals:
            return CommandResult(bypass_agent=True, message="no saved journals.")
        if not arg:
            # List the 10 most recent.
            lines = ["recent journals:"]
            for p in journals[:10]:
                lines.append(f"  . {p.name}")
            lines.append("use /load <substring> to open one.")
            return CommandResult(bypass_agent=True, message="\n".join(lines))
        arg_lower = arg.lower()
        match = next((p for p in journals if arg_lower in p.name.lower()), None)
        if match is None:
            return CommandResult(
                bypass_agent=True, message=f"no journal matching '{arg}'."
            )
        return CommandResult(
            bypass_agent=True,
            message=f"journal at {match} -- open it in your editor to review.",
        )

    def _cmd_cwd(self) -> CommandResult:
        if self.project_dir is None:
            return CommandResult(
                bypass_agent=True,
                message="project directory not set (both agents inherit the shell cwd).",
            )
        return CommandResult(
            bypass_agent=True,
            message=f"project: {self.project_dir}",
        )

    def _cmd_reset(self) -> CommandResult:
        if self.lil_bro is None:
            return CommandResult(bypass_agent=True, message="Lil Bro agent not available.")
        self.lil_bro.clear_history()
        return CommandResult(
            bypass_agent=True,
            message="Lil Bro history reset -- next message starts a fresh conversation.",
        )

    def _cmd_review(self, arg: str) -> CommandResult:
        content = arg
        if not content and self.big_bro_panel is not None:
            content = self.big_bro_panel.last_assistant_message
        if not content:
            return CommandResult(
                bypass_agent=True,
                message="nothing to review. Pass code as an argument or use after Big Bro has replied.",
            )
        banners = self._award("review_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=REVIEW_TEMPLATE.format(content=content),
            banners=banners,
        )

    def _cmd_debug(self, arg: str) -> CommandResult:
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="usage: /debug <error or stack trace>",
            )
        banners = self._award("debug_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=DEBUG_TEMPLATE.format(error=arg),
            banners=banners,
        )

    # -----------------------------------------------------------------
    # Local-specific: /model, /models, /status, /history
    # -----------------------------------------------------------------

    def _cmd_model(self, arg: str) -> CommandResult:
        """`/model` -- show both; `/model [a|b] <name>` -- switch model.

        Targets: `a` / `broa` or `b` / `brob`. Switching changes the
        model tag on the OllamaAgent directly -- no subprocess restart needed.
        """
        parts = arg.split(maxsplit=1)

        # Bare /model -> report current settings.
        if not parts:
            big_model = self._describe_agent_model(self.big_bro)
            lil_model = self._describe_agent_model(self.lil_bro)
            return CommandResult(
                bypass_agent=True,
                message=(
                    f"models:\n"
                    f"  . Big Bro: {big_model}\n"
                    f"  . Lil Bro: {lil_model}\n"
                    f"usage: /model <big|lil> <model-name>   (switches the model)\n"
                    f"       /model <name>                   (switches both)"
                ),
            )

        # Single arg -- switch both agents to that model.
        if len(parts) == 1:
            new_model = parts[0].strip()
            # Check if it's a target keyword with no model name.
            if new_model.lower() in ("big", "bigbro", "big_bro", "lil", "lilbro", "lil_bro"):
                return CommandResult(
                    bypass_agent=True,
                    message=f"usage: /model {new_model} <model-name>",
                )
            for agent in (self.big_bro, self.lil_bro):
                if agent is not None:
                    agent.model = new_model
            self._persist_model(new_model)
            return CommandResult(
                bypass_agent=True,
                message=f"Switched both agents to model: {new_model}",
            )

        raw_target = parts[0].lower()
        new_model = parts[1].strip()

        if raw_target in ("big", "bigbro", "big_bro"):
            agent = self.big_bro
            label = "Big Bro"
        elif raw_target in ("lil", "lilbro", "lil_bro"):
            agent = self.lil_bro
            label = "Lil Bro"
        else:
            return CommandResult(
                bypass_agent=True,
                message=f"unknown target '{raw_target}' -- use 'big' or 'lil'.",
            )

        if agent is None:
            return CommandResult(
                bypass_agent=True,
                message=f"{label} agent is not available in this session.",
            )

        agent.model = new_model
        if self.journal is not None:
            self.journal.note_decision(f"switched {label} model -> {new_model}")
        self._persist_model(new_model)

        return CommandResult(
            bypass_agent=True,
            message=f"{label} -> model '{new_model}' (conversation history preserved)",
        )

    @staticmethod
    def _persist_model(model: str) -> None:
        """Save the active model to the state file so it persists across restarts."""
        try:
            from src_local.app import STATE_FILE, _load_state, _save_state
            state = _load_state()
            state["active_model"] = model
            _save_state(state)
        except Exception:  # noqa: BLE001
            pass

    def _describe_agent_model(self, agent: "OllamaAgent | None") -> str:
        if agent is None:
            return "(unavailable)"
        model = getattr(agent, "model", None)
        return model or "(not set)"

    def _cmd_models(self) -> CommandResult:
        return CommandResult(
            bypass_agent=True,
            message=(
                "To see available models, run in a terminal:\n"
                "  ollama list\n\n"
                "To pull a new model:\n"
                "  ollama pull qwen2.5-coder:7b"
            ),
        )

    def _cmd_status(self) -> CommandResult:
        lines = [
            "LIL BRO LOCAL -- Status",
            "───────────────────────",
        ]
        if self.config is not None:
            ollama_cfg = getattr(self.config, "ollama", None)
            if ollama_cfg is not None:
                lines.append(f"Ollama URL: {getattr(ollama_cfg, 'base_url', '?')}")
                lines.append(f"Model: {getattr(ollama_cfg, 'model', '?')}")
                cfg_big = getattr(ollama_cfg, 'context_window_big', '?')
                cfg_lil = getattr(ollama_cfg, 'context_window_lil', '?')
                # Show actual resolved values from agents
                actual_big = getattr(self.big_bro, 'context_window', '?') if self.big_bro else '?'
                actual_lil = getattr(self.lil_bro, 'context_window', '?') if self.lil_bro else '?'
                if cfg_big == "auto" or cfg_lil == "auto":
                    lines.append(f"Context window: Big Bro {actual_big} / Lil Bro {actual_lil} (auto-detected from VRAM)")
                else:
                    lines.append(f"Context window: Big Bro {actual_big} / Lil Bro {actual_lil} (user-configured)")
                lines.append(f"Temperature: {getattr(ollama_cfg, 'temperature', '?')}")
        for label, agent in [("Big Bro", self.big_bro), ("Lil Bro", self.lil_bro)]:
            if agent is not None:
                busy = "thinking" if getattr(agent, "is_busy", lambda: False)() else "idle"
                history_len = len(getattr(agent, "_history", []))
                lines.append(f"{label}: {busy}, {history_len} messages in history")
        return CommandResult(bypass_agent=True, message="\n".join(lines))

    def _cmd_history(self, arg: str) -> CommandResult:
        if arg.lower() == "clear":
            for agent in (self.big_bro, self.lil_bro):
                if agent is not None:
                    agent.clear_history()
            return CommandResult(
                bypass_agent=True,
                message="Conversation history cleared for both agents.",
            )
        return CommandResult(
            bypass_agent=True,
            message="Usage: /history clear",
        )

    # -----------------------------------------------------------------
    # Session / state
    # -----------------------------------------------------------------

    def _cmd_session(self) -> CommandResult:
        if self.project_dir is None:
            return CommandResult(bypass_agent=True, message="project directory not set.")
        path = self.project_dir / "SESSION.md"
        if not path.exists():
            return CommandResult(bypass_agent=True, message=f"SESSION.md not found at {path}")
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception as exc:  # noqa: BLE001
            return CommandResult(bypass_agent=True, message=f"could not read SESSION.md: {exc}")
        tail = lines[-80:] if len(lines) > 80 else lines
        content = "\n".join(tail)
        header = f"-- SESSION.md (last {len(tail)} of {len(lines)} lines) --\n"
        return CommandResult(
            bypass_agent=True,
            message=header + content,
            ingest_session_dump=True,
        )

    def _cmd_state(self) -> CommandResult:
        """`/state` -- dump a human-readable diagnostic snapshot."""
        import sys as _sys

        lines: list[str] = ["-- LIL BRO LOCAL state --"]
        lines.append(f"python: {_sys.version.split()[0]}  platform: {_sys.platform}")
        try:
            import textual  # noqa: WPS433

            lines.append(f"textual: {getattr(textual, '__version__', '?')}")
        except Exception:  # noqa: BLE001
            lines.append("textual: (import failed)")

        lines.append("")
        lines.append("Big Bro:")
        if self.big_bro is None:
            lines.append("  . (agent not attached)")
        else:
            model = getattr(self.big_bro, "model", "?")
            history_len = len(getattr(self.big_bro, "_history", []))
            busy = getattr(self.big_bro, "is_busy", lambda: False)()
            lines.append(f"  . model: {model}")
            lines.append(f"  . history: {history_len} messages")
            lines.append(f"  . status: {'thinking' if busy else 'idle'}")

        lines.append("")
        lines.append("Lil Bro:")
        if self.lil_bro is None:
            lines.append("  . (agent not attached)")
        else:
            model = getattr(self.lil_bro, "model", "?")
            history_len = len(getattr(self.lil_bro, "_history", []))
            busy = getattr(self.lil_bro, "is_busy", lambda: False)()
            lines.append(f"  . model: {model}")
            lines.append(f"  . history: {history_len} messages")
            lines.append(f"  . status: {'thinking' if busy else 'idle'}")

        lines.append("")
        if self.project_dir is not None:
            lines.append(f"project:    {self.project_dir}")
            lines.append(f"SESSION.md: {self.project_dir / 'SESSION.md'}")
        if self.journal is not None:
            lines.append(
                f"journal:    {self.journal.current_path or '(not saved yet)'}"
            )
            lines.append(f"journal dir: {self.journal.directory}")

        import os as _os

        lines.append(
            f"LILBRO_DEBUG: {'on' if _os.environ.get('LILBRO_DEBUG') else 'off'}"
        )
        return CommandResult(bypass_agent=True, message="\n".join(lines))

    # -----------------------------------------------------------------
    # Review / diff / trace / compare
    # -----------------------------------------------------------------

    def _cmd_review_file(self, arg: str) -> CommandResult:
        """`/review-file <path>` -- structured file review routed to Lil Bro."""
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="usage: /review-file <path>  (Lil Bro reads the file and reviews it)",
            )
        from pathlib import Path as _Path

        raw = arg.strip().strip('"').strip("'")
        candidate = _Path(raw).expanduser()
        if not candidate.is_absolute() and self.project_dir is not None:
            candidate = (self.project_dir / raw).resolve()
        if not candidate.exists():
            return CommandResult(
                bypass_agent=True,
                message=f"file not found: {candidate}",
            )
        if candidate.is_dir():
            return CommandResult(
                bypass_agent=True,
                message=f"{candidate} is a directory -- /review-file wants a single file.",
            )
        if self.journal is not None:
            self.journal.record("bro", "command", f"/review-file {candidate}")
        banners = self._award("review_file_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=REVIEW_FILE_TEMPLATE.format(path=str(candidate)),
            banners=banners,
        )

    def _cmd_compare(self, arg: str) -> CommandResult:
        """`/compare <a> | <b>` -- structured compare/contrast teaching."""
        if not arg:
            return CommandResult(
                bypass_agent=True,
                message="usage: /compare <topic a> | <topic b>  (or 'vs' as separator)",
            )
        topic_a, topic_b = self._split_compare(arg)
        if not topic_a or not topic_b:
            return CommandResult(
                bypass_agent=True,
                message="usage: /compare <topic a> | <topic b>  -- need two topics separated by | or vs",
            )
        if self.journal is not None:
            self.journal.record("bro", "explain", f"compare: {topic_a} vs {topic_b}")
        banners = self._award("compare_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=COMPARE_TEMPLATE.format(
                topic_a=topic_a, topic_b=topic_b
            ),
            banners=banners,
        )

    @staticmethod
    def _split_compare(arg: str) -> tuple[str, str]:
        """Split on ``|`` first, fall back to whitespace-delimited ``vs``."""
        if "|" in arg:
            a, _, b = arg.partition("|")
            return a.strip(), b.strip()
        tokens = arg.split()
        for i, tok in enumerate(tokens):
            if tok.lower() in ("vs", "vs.", "versus"):
                return " ".join(tokens[:i]).strip(), " ".join(tokens[i + 1 :]).strip()
        return "", ""

    def _cmd_explain_diff(self, arg: str) -> CommandResult:
        """`/explain-diff` -- Lil Bro teaches through Big Bro's last change."""
        content = arg.strip()
        if not content and self.big_bro_panel is not None:
            content = self.big_bro_panel.last_assistant_message
        if not content and self.journal is not None and self.journal.files_changed:
            files = "\n".join(f"- {fp}" for fp in self.journal.files_changed[-10:])
            content = (
                "Big Bro recently touched these files (no text content "
                "captured -- read them if needed):\n" + files
            )
        if not content:
            return CommandResult(
                bypass_agent=True,
                message="nothing to explain yet. Use after Big Bro has replied or made a change.",
            )
        banners = self._award("explain_diff_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=EXPLAIN_DIFF_TEMPLATE.format(content=content),
            banners=banners,
        )

    def _cmd_trace(self, arg: str) -> CommandResult:
        """`/trace <symbol>` -- Lil Bro walks a call graph around a symbol."""
        symbol = arg.strip().strip('"').strip("'")
        if not symbol:
            return CommandResult(
                bypass_agent=True,
                message="usage: /trace <symbol>  (function, class, or method name)",
            )
        if any(ch in symbol for ch in "|;&<>$`\n\r"):
            return CommandResult(
                bypass_agent=True,
                message="/trace: symbol contains shell metacharacters -- pass just a name.",
            )
        project = str(self.project_dir) if self.project_dir is not None else "(current)"
        if self.journal is not None:
            self.journal.record("bro", "command", f"/trace {symbol}")
        banners = self._award("trace_used")
        return CommandResult(
            bypass_agent=False,
            forced_target="bro",
            rewritten_prompt=TRACE_TEMPLATE.format(symbol=symbol, project=project),
            banners=banners,
        )

    def _cmd_wrap(self) -> CommandResult:
        """`/wrap` -- toggle soft word-wrap on the active panel."""
        return CommandResult(bypass_agent=True, toggle_wrap=True)

    # -----------------------------------------------------------------
    # Journal search
    # -----------------------------------------------------------------

    def _cmd_find(self, arg: str) -> CommandResult:
        """`/find <query>` -- case-insensitive substring grep across saved journals."""
        query = (arg or "").strip()
        if not query:
            return CommandResult(
                bypass_agent=True,
                message="usage: /find <query>  (case-insensitive substring across ~/.lilbro-local/journals/)",
            )
        if self.journal is None or self.journal.directory is None:
            return CommandResult(
                bypass_agent=True,
                message="journal directory not configured.",
            )

        MAX_HITS = 40
        MAX_FILES = 200
        PREVIEW_LEN = 140

        journals = self.journal.list_journals()[:MAX_FILES]
        if not journals:
            return CommandResult(bypass_agent=True, message="no saved journals to search.")

        q = query.lower()
        hits: list[str] = []
        scanned = 0
        for path in journals:
            if len(hits) >= MAX_HITS:
                break
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for lineno, raw_line in enumerate(fh, start=1):
                        if q not in raw_line.lower():
                            continue
                        preview = raw_line.strip()
                        if len(preview) > PREVIEW_LEN:
                            preview = preview[:PREVIEW_LEN] + "..."
                        hits.append(f"  {path.name}:{lineno}: {preview}")
                        if len(hits) >= MAX_HITS:
                            break
            except OSError:
                continue
            scanned += 1

        if not hits:
            return CommandResult(
                bypass_agent=True,
                message=f"no matches for '{query}' in {scanned} journals.",
            )
        header = (
            f"-- /find '{query}' -- {len(hits)} hit(s) across "
            f"{scanned} journal(s) --"
        )
        if len(hits) >= MAX_HITS:
            header += f"  (capped at {MAX_HITS})"
        return CommandResult(
            bypass_agent=True,
            message=header + "\n" + "\n".join(hits),
        )

    # -----------------------------------------------------------------
    # Debug dump
    # -----------------------------------------------------------------

    def _cmd_debug_dump(self) -> CommandResult:
        """`/debug-dump` -- bundle diagnostic artifacts into a timestamped zip."""
        import zipfile
        from datetime import datetime as _dt
        from pathlib import Path as _Path

        dumps_dir = _Path.home() / ".lilbro-local" / "dumps"
        try:
            dumps_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return CommandResult(
                bypass_agent=True,
                message=f"/debug-dump: could not create {dumps_dir}: {exc}",
            )

        stamp = _dt.now().strftime("%Y-%m-%d_%H-%M-%S")
        zip_path = dumps_dir / f"lilbro-local-dump-{stamp}.zip"

        included: list[str] = []
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                # 1. Rotating debug log.
                debug_log = _Path.home() / ".lilbro-local" / "debug.log"
                if debug_log.is_file():
                    zf.write(debug_log, arcname="debug.log")
                    included.append("debug.log")

                # 2. SESSION.md from the project dir.
                if self.project_dir is not None:
                    session_md = self.project_dir / "SESSION.md"
                    if session_md.is_file():
                        zf.write(session_md, arcname="SESSION.md")
                        included.append("SESSION.md")

                # 3. Current journal.
                if self.journal is not None:
                    try:
                        md = self.journal.render_markdown()
                        zf.writestr("journal.md", md)
                        included.append("journal.md")
                    except Exception:  # noqa: BLE001
                        pass

                # 4. /state snapshot.
                try:
                    state_result = self._cmd_state()
                    zf.writestr("state.txt", state_result.message)
                    included.append("state.txt")
                except Exception:  # noqa: BLE001
                    pass
        except OSError as exc:
            return CommandResult(
                bypass_agent=True,
                message=f"/debug-dump: zip write failed: {exc}",
            )

        if not included:
            try:
                zip_path.unlink()
            except OSError:
                pass
            return CommandResult(
                bypass_agent=True,
                message="/debug-dump: nothing to bundle (no debug.log, SESSION.md, or journal found).",
            )

        contents = ", ".join(included)
        if self.journal is not None:
            self.journal.note_decision(f"/debug-dump -> {zip_path.name}")
        return CommandResult(
            bypass_agent=True,
            message=(
                f"/debug-dump -> {zip_path}\n"
                f"  contents: {contents}\n"
                f"  attach this zip when filing a bug report."
            ),
        )

    # -----------------------------------------------------------------
    # Journal info
    # -----------------------------------------------------------------

    def _cmd_journal_info(self) -> CommandResult:
        if self.journal is None:
            return CommandResult(bypass_agent=True, message="journal not available.")
        cur = self.journal.current_path
        if cur is None:
            return CommandResult(
                bypass_agent=True,
                message=f"journal not yet saved. dir: {self.journal.directory}",
            )
        return CommandResult(bypass_agent=True, message=f"journal: {cur}")

    # -----------------------------------------------------------------
    # Named sessions
    # -----------------------------------------------------------------

    @staticmethod
    def _sessions_dir() -> Path:
        p = Path.home() / ".lilbro-local" / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _cmd_session_save(self, arg: str) -> CommandResult:
        """/session-save <name> -- bookmark the current project dir."""
        name = arg.strip()
        if not name:
            return CommandResult(
                bypass_agent=True,
                message="usage: /session-save <name>  (e.g. /session-save myproject)",
            )
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        dest = self._sessions_dir() / f"{safe}.json"
        project_dir = str(self.project_dir or Path.cwd())
        journal_path = str(
            self.journal.current_path if self.journal else None or ""
        )
        data = {
            "name": name,
            "project_dir": project_dir,
            "journal": journal_path,
            "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        try:
            dest.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError as exc:
            return CommandResult(
                bypass_agent=True, message=f"session save failed: {exc}"
            )
        return CommandResult(
            bypass_agent=True,
            message=f"session saved: {name}  ({project_dir})",
        )

    def _cmd_session_open(self, arg: str) -> CommandResult:
        """/session-open <name> -- show info for a saved session."""
        name = arg.strip()
        if not name:
            return CommandResult(
                bypass_agent=True,
                message="usage: /session-open <name>  (use /sessions to list)",
            )
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        dest = self._sessions_dir() / f"{safe}.json"
        if not dest.exists():
            return CommandResult(
                bypass_agent=True,
                message=f"no session named '{name}'. use /sessions to list.",
            )
        try:
            data = json.loads(dest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return CommandResult(
                bypass_agent=True, message=f"session load failed: {exc}"
            )
        project_dir = data.get("project_dir", "unknown")
        saved_at = data.get("saved_at", "unknown")
        journal = data.get("journal", "")
        lines = [
            f"session: {data.get('name', name)}",
            f"  project : {project_dir}",
            f"  saved   : {saved_at}",
        ]
        if journal:
            lines.append(f"  journal : {journal}")
        lines.append(f"  -> use: lilbro-local {project_dir}  to reopen this project")
        return CommandResult(bypass_agent=True, message="\n".join(lines))

    def _cmd_sessions_list(self) -> CommandResult:
        """/sessions -- list all saved sessions."""
        sessions_dir = self._sessions_dir()
        files = sorted(sessions_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if not files:
            return CommandResult(
                bypass_agent=True,
                message="no saved sessions yet. use /session-save <name> to create one.",
            )
        lines = ["saved sessions:"]
        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                name = data.get("name", f.stem)
                project = data.get("project_dir", "?")
                saved = data.get("saved_at", "?")
                lines.append(f"  {name:<20}  {project}  ({saved})")
            except (OSError, json.JSONDecodeError):
                lines.append(f"  {f.stem}  (unreadable)")
        return CommandResult(bypass_agent=True, message="\n".join(lines))

    # -----------------------------------------------------------------
    # Skills / plugins
    # -----------------------------------------------------------------

    def _cmd_player(self) -> CommandResult:
        """/player -- show the RPG progression card."""
        profile = self.player_profile
        if profile is None:
            try:
                from src_local.rpg.player import PlayerProfile
                profile = PlayerProfile.load()
            except Exception as exc:  # noqa: BLE001
                return CommandResult(
                    bypass_agent=True,
                    message=f"player profile unavailable: {exc}",
                )
        try:
            from src_local.rpg.badges import badge_name
            from src_local.rpg.xp import SKILLS
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                bypass_agent=True, message=f"rpg import failed: {exc}"
            )

        lvl, into, needed = profile.level_progress()
        if needed > 0:
            bar_width = 20
            filled = int(round((into / needed) * bar_width))
            bar = "#" * filled + "-" * (bar_width - filled)
            xp_line = f"Lv {lvl}  [{bar}]  {into}/{needed} xp  (total: {profile.xp})"
        else:
            xp_line = f"Lv {lvl}  [MAX]  total: {profile.xp} xp"

        lines: list[str] = [
            f"-- {profile.display_name} --",
            xp_line,
            "",
            "Skills:",
        ]
        for skill in SKILLS:
            sl = profile.skill_level(skill)
            sxp = profile.skills.get(skill, 0)
            lines.append(f"  {skill:<10} Lv {sl:>2}   ({sxp} xp)")

        badges = list(profile.badges)
        if badges:
            lines.append("")
            lines.append(f"Badges ({len(badges)}):")
            recent = badges[-5:]
            for key in recent:
                lines.append(f"  [*] {badge_name(key)}")
        else:
            lines.append("")
            lines.append("Badges: (none yet -- try /explain or /plan)")

        perks = profile.active_perks()
        if perks:
            lines.append("")
            lines.append("Active perks:")
            for p in perks:
                lines.append(f"  * {p}")

        concepts = list(profile.discovered_concepts)
        if concepts:
            lines.append("")
            lines.append(f"Concepts discovered: {len(concepts)}")

        return CommandResult(bypass_agent=True, message="\n".join(lines))

    # -----------------------------------------------------------------
    # Campaign commands
    # -----------------------------------------------------------------

    def _cmd_campaign(self, arg: str) -> CommandResult:
        """/campaign -- open the map modal, or show status."""
        sub = arg.strip().lower()
        state = self.campaign_state
        world = self.world
        if sub in ("", "map"):
            if world is None or state is None:
                return CommandResult(
                    bypass_agent=True,
                    message="campaign not loaded (no world.yaml found).",
                )
            return CommandResult(bypass_agent=True, show_campaign_map=True)
        if sub == "status":
            if world is None or state is None:
                return CommandResult(
                    bypass_agent=True, message="campaign not loaded."
                )
            try:
                pct = state.completion_percent(world)
            except Exception:  # noqa: BLE001
                pct = 0.0
            lines = [
                f"area: {state.current_area or '---'}",
                f"current quest: {state.current_quest_id or '---'}",
                f"completion: {pct:.0f}%",
                f"completed quests: {len(state.completed_quests)}",
            ]
            return CommandResult(bypass_agent=True, message="\n".join(lines))
        if sub == "quit":
            if state is not None:
                state.current_quest_id = ""
                try:
                    state.save()
                except Exception:  # noqa: BLE001
                    pass
            if self.challenge_manager is not None:
                try:
                    self.challenge_manager.skip()
                except Exception:  # noqa: BLE001
                    pass
            return CommandResult(bypass_agent=True, message="quest abandoned.")
        return CommandResult(
            bypass_agent=True,
            message="usage: /campaign [map|status|quit]",
        )

    def _cmd_quest(self, arg: str) -> CommandResult:
        """/quest <id> -- start a quest by id in the active panel."""
        qid = arg.strip()
        if not qid:
            return CommandResult(
                bypass_agent=True,
                message="usage: /quest <quest_id>  (see /campaign)",
            )
        if self.challenge_manager is None or self.world is None:
            return CommandResult(
                bypass_agent=True, message="campaign not loaded."
            )
        quest = self._lookup_quest(qid)
        if quest is None:
            return CommandResult(
                bypass_agent=True, message=f"no quest with id '{qid}'."
            )
        panel = self.big_bro_panel or self.lil_bro_panel
        if panel is None:
            return CommandResult(
                bypass_agent=True, message="no active panel to present quest."
            )
        try:
            self.challenge_manager.start(quest, panel)
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                bypass_agent=True, message=f"failed to start quest: {exc}"
            )
        return CommandResult(
            bypass_agent=True, message=f"quest '{qid}' started."
        )

    def _lookup_quest(self, qid: str):
        """Find a Quest by id using teach_mode.quest_lookup if present."""
        tm = self.teach_mode
        if tm is not None and getattr(tm, "quest_lookup", None) is not None:
            try:
                return tm.quest_lookup(qid)
            except Exception:  # noqa: BLE001
                return None
        return None

    def _cmd_teach(self, arg: str) -> CommandResult:
        """/teach -- toggle inline teach mode, or delegate to the manager."""
        tm = self.teach_mode
        if tm is None:
            return CommandResult(
                bypass_agent=True, message="teach mode not available."
            )
        sub = arg.strip().lower()
        if sub in ("", "toggle"):
            now_on = tm.toggle()
            return CommandResult(
                bypass_agent=True,
                message=f"teach mode: {'on' if now_on else 'off'}",
            )
        if sub == "on":
            tm.turn_on()
            return CommandResult(bypass_agent=True, message="teach mode: on")
        if sub == "off":
            tm.turn_off()
            return CommandResult(bypass_agent=True, message="teach mode: off")
        if sub == "hint":
            mgr = self.challenge_manager
            if mgr is None:
                return CommandResult(
                    bypass_agent=True, message="no active challenge."
                )
            text = mgr.hint()
            if text is None:
                return CommandResult(
                    bypass_agent=True, message="no hints available."
                )
            return CommandResult(bypass_agent=True, message=f"hint: {text}")
        if sub == "skip":
            mgr = self.challenge_manager
            if mgr is None:
                return CommandResult(
                    bypass_agent=True, message="no active challenge."
                )
            mgr.skip()
            return CommandResult(bypass_agent=True, message="quest skipped.")
        if sub == "replay":
            mgr = self.challenge_manager
            if mgr is None or mgr.active_quest is None:
                return CommandResult(
                    bypass_agent=True, message="no active challenge."
                )
            try:
                mgr._render_presentation()
            except Exception:  # noqa: BLE001
                pass
            return CommandResult(bypass_agent=True, message="")
        if sub == "stats":
            return CommandResult(
                bypass_agent=True,
                message=f"teach triggers this session: {tm.session_triggers}",
            )
        return CommandResult(
            bypass_agent=True,
            message="usage: /teach [on|off|toggle|hint|skip|replay|stats]",
        )

    def _cmd_submit(self, arg: str) -> CommandResult:
        """/submit <text> -- validate text against the active quest."""
        mgr = self.challenge_manager
        if mgr is None or mgr.active_quest is None:
            return CommandResult(
                bypass_agent=True, message="no active quest -- try /quest <id>."
            )
        outcome = mgr.submit(arg)
        banners = list(outcome.banners)
        msg = "correct!" if outcome.ok else f"X {outcome.result.message}"
        return CommandResult(
            bypass_agent=True, message=msg, banners=banners
        )

    def _cmd_hint(self) -> CommandResult:
        mgr = self.challenge_manager
        if mgr is None or mgr.active_quest is None:
            return CommandResult(
                bypass_agent=True, message="no active quest."
            )
        text = mgr.hint()
        if text is None:
            return CommandResult(
                bypass_agent=True, message="no hints available."
            )
        return CommandResult(bypass_agent=True, message=f"hint: {text}")

    def _cmd_skip(self) -> CommandResult:
        mgr = self.challenge_manager
        if mgr is None or mgr.active_quest is None:
            return CommandResult(
                bypass_agent=True, message="no active quest."
            )
        mgr.skip()
        return CommandResult(bypass_agent=True, message="quest skipped.")

    def _cmd_bunkbed(self) -> CommandResult:
        """/bunkbed -- toggle Lil Bro's write access."""
        from src_local.agents.ollama_agent import HELPER_BUNKBED_PROMPT, HELPER_SYSTEM_PROMPT

        self._bunkbed = not self._bunkbed

        if self.lil_bro is not None:
            self.lil_bro.set_write_access(self._bunkbed)
            prompt = HELPER_BUNKBED_PROMPT if self._bunkbed else HELPER_SYSTEM_PROMPT
            self.lil_bro.update_system_prompt(prompt)

        if self.status_bar is not None:
            self.status_bar.set_bunkbed(self._bunkbed)

        if self._bunkbed:
            msg = "bunkbed ON -- Lil Bro can now read AND write files"
        else:
            msg = "bunkbed OFF -- Lil Bro is read-only again"
        return CommandResult(bypass_agent=True, message=msg)

    def _cmd_skills_list(self) -> CommandResult:
        """/skills -- list installed skills in ~/.lilbro-local/skills/."""
        from src_local.skills import SKILLS_DIR
        rows = list_skills()
        if not rows:
            return CommandResult(
                bypass_agent=True,
                message=(
                    f"no skills installed.\n"
                    f"drop a .py or .md file into {SKILLS_DIR}\n"
                    f"then invoke it with /skill-name"
                ),
            )
        lines = [f"skills  ({SKILLS_DIR})"]
        cmd_w = max(len(r[0]) for r in rows) + 2
        for cmd, kind, desc in rows:
            lines.append(f"  {cmd.ljust(cmd_w)}  [{kind}]  {desc}")
        return CommandResult(bypass_agent=True, message="\n".join(lines))

    def _cmd_run_skill(self, name: str, path: "Path", args: str) -> CommandResult:
        """Dispatch a skill -- .py runs as subprocess, .md sends as prompt."""
        if name.lower().startswith("test"):
            self._award("tests_run")
        if path.suffix == ".md":
            prompt = read_md_skill(path)
            if args:
                prompt = f"{args}\n\n{prompt}"
            return CommandResult(bypass_agent=False, prompt=prompt)

        # .py skill -- run async and display output.
        import asyncio as _asyncio

        async def _run() -> CommandResult:
            output, ok = await run_py_skill(path, args)
            return CommandResult(
                bypass_agent=True,
                message=f"[skill: {name}]\n{output}",
            )

        try:
            loop = _asyncio.get_event_loop()
            if loop.is_running():
                return CommandResult(
                    bypass_agent=True,
                    message=f"running skill '{name}'...",
                    skill_coro=_run(),
                )
            return loop.run_until_complete(_run())
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                bypass_agent=True, message=f"skill error: {exc}"
            )

    # -----------------------------------------------------------------
    # HTML export
    # -----------------------------------------------------------------

    def _cmd_export_html(self, arg: str) -> CommandResult:
        """/export-html -- convert the current journal to a styled HTML file."""
        from src_local.journal.html_export import export_journal_to_html

        if self.journal is None:
            return CommandResult(bypass_agent=True, message="no journal available.")

        journal_path = self.journal.current_path
        if journal_path is None:
            try:
                self.journal.save()
                journal_path = self.journal.current_path
            except Exception:  # noqa: BLE001
                pass
        if journal_path is None:
            return CommandResult(
                bypass_agent=True,
                message="journal has not been saved yet. use /save first.",
            )

        try:
            out_path = export_journal_to_html(Path(journal_path))
        except Exception as exc:  # noqa: BLE001
            return CommandResult(
                bypass_agent=True, message=f"export failed: {exc}"
            )
        return CommandResult(
            bypass_agent=True,
            message=f"exported -> {out_path}",
        )
