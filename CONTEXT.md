# LIL BRO — Full Context Document

> **Purpose:** Single source of truth for auditing work on LIL BRO.
> Captures the **current released version** (what users download today)
> and the **end game version** (what LIL BRO becomes when all 6 phases ship).
> Use this as the anchor when building — every change should move one
> closer to the other without breaking what's already shipped.

---

## Part 1 — Current Released Version (v0.x beta)

What's on GitHub right now. Users clone this, run it, and get a working local AI coding assistant.

### 1.1 What it is

A dual-agent local coding TUI. Two Ollama-backed "bros" share a workspace on your machine.

- **Big Bro** — coder, full write access (read/write/edit/grep/run_command)
- **Lil Bro** — helper, read-only by default (read/grep + Grandpa + calculate)
- Both run on local Ollama models — no API keys, no cloud, no billing

### 1.2 Architecture (current)

```
┌───────────────────── LIL BRO TUI ─────────────────────┐
│                                                       │
│  ┌─ Lil Bro pane ──┐   ┌─ Big Bro pane ───┐           │
│  │  helper          │   │  coder            │           │
│  │  read-only       │   │  write access     │           │
│  │  /explain        │   │  /plan /edit      │           │
│  └──────────────────┘   └───────────────────┘           │
│         ↑                         ↑                     │
│         │                         │                     │
│    [OllamaAgent]             [OllamaAgent]              │
│         │                         │                     │
│         └──────────┬──────────────┘                     │
│                    │                                     │
│                 Ollama daemon (http://127.0.0.1:11434)  │
│                    │                                     │
│                 Local model (e.g. qwen2.5-coder:7b)     │
│                                                         │
│  Cross-talk: SESSION.md (both bros read sibling lines)  │
│  Bible retrieval: Grandpa (hybrid keyword + model)      │
│  Session state: SESSION.md (append-only breadcrumbs)    │
└─────────────────────────────────────────────────────────┘
```

### 1.3 Shipped systems

| System | Files | Status |
|---|---|---|
| **Ollama agent** | `src_local/agents/ollama_agent.py` | ✅ Working |
| **Tool calling** | `src_local/agents/tools.py` | ✅ 8 tools + fallback text extraction |
| **Grandpa (bibles)** | `src_local/bibles/` | ✅ Compiled JSON + hybrid retrieval |
| **Router** | `src_local/router.py` | ✅ Active-target dispatch + cross-talk port |
| **Hardware detection** | `src_local/agents/hardware.py` | ✅ GPU, VRAM, RAM |
| **VRAM management** | `src_local/vram.py` | ✅ Auto context window per model |
| **Ollama install** | `src_local/agents/ollama_install.py` | ✅ Guided setup |
| **RPG system** | `src_local/rpg/` | ✅ Player, XP, skills, badges, challenges, boss fights |
| **Quest system** | `src_local/quests/` | ✅ 48 quests across 6 areas |
| **Journal** | `src_local/journal/` | ✅ Session recording, HTML export, session lock |
| **Commands** | `src_local/commands/` | ✅ Slash command handler |
| **UI (Textual)** | `src_local/ui/` | ✅ Panels, input bar, status bar, XP bar, screens |
| **Teach mode** | `src_local/rpg/teach_mode.py` | ✅ Toggle + state, basic challenges |
| **Config** | `config.yaml` | ✅ Ollama-only schema |

### 1.4 What a daily session looks like

1. User runs `lilbro-local`
2. First run wizard detects hardware, offers model pulls (Qwen Coder family)
3. Dual-pane TUI loads — Big Bro left, Lil Bro right (or Tab-switchable)
4. User types into active pane, Ollama streams response
5. Big Bro reads/writes files; Lil Bro explains and teaches
6. Bros see each other's work via SESSION.md (unified across all backends)
7. Grandpa auto-injects reference material for technical questions
8. XP and badges accumulate; quests unlock as skills grow
9. Session logs save to `~/.lilbro-local/journals/`

### 1.5 Known limitations (v0.x)

- **Ollama only** — no cloud model support (Claude, Codex, Gemini unavailable)
- **Single-machine** — both bros run on same host, no remote/mobile access
- **No persistent memory** — each session starts fresh, no cross-session learning
- **No roadmap/planning engine** — LIL BRO responds to prompts, doesn't drive projects
- **No persona system** — only two bros, no Mom/Dad/Grandma advisory layer
- **Cross-talk is passive** — SESSION.md is read/written, but bros don't initiate conversation
- **Teaching mode basic** — foundation exists, adaptive difficulty not yet wired

### 1.6 Test coverage today

| Test file | Covers |
|---|---|
| `test_config.py` | YAML loader, defaults, overrides |
| `test_hardware.py` | GPU/VRAM/RAM detection across platforms |
| `test_tool_regex.py` | Fallback text-based tool call extraction |
| `test_tools.py` | All 8 tool functions (read/write/edit/grep/run/lookup/calculate) |
| `test_vram.py` | Auto context window sizing |

**Missing coverage:** agent lifecycle, router dispatch, bible store retrieval, RPG state transitions, quest loading, journal write/read, UI rendering, session recovery.

### 1.7 CI today

- **Lint** — ruff on `src_local/` and `tests/`
- **Typecheck** — mypy (non-blocking)
- **Test matrix** — pytest on ubuntu + macos + windows, Python 3.11 + 3.12
- **Build check** — wheel builds and installs

---

## Part 2 — End Game Version (v2 + beyond)

What LIL BRO becomes when all 6 phases ship. This is the target state.

### 2.1 What it is

A self-improving, model-agnostic personal AI operating system. Not a chatbot, not a wrapper. A persistent co-pilot that learns who you are, how you work, and what you're building — then acts across every area of your life and work.

**Core promise:** LIL BRO gets smarter the longer you use it. Not because the model changes — because it knows YOU.

### 2.2 Architecture (end game)

```
┌─────────────────────────────────────────────────────────┐
│                     ACCESS LAYER                         │
│   CLI · TUI (Textual) · PWA (mobile) · Tailscale        │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                     CORE ENGINE                          │
│        Task Classifier → Connector Router               │
│                         ↓                                │
│    Ollama · Claude · Codex · Gemini (when avail.)       │
│                    (Connector Layer)                     │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   PERSONA COUNCIL                        │
│          👩 Mom · 👨 Dad · 👵 Grandma                   │
│                 (always running)                         │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                    MEMORY SYSTEM                         │
│   Chroma Vector DB · Project Registry · File Watcher     │
│   Preference Log · Context Injector                      │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   ROADMAP ENGINE                         │
│   Brainstorm → Plan → Execute Loop                       │
│   Living Roadmap · Icebox · Milestone Gates             │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│   EXISTING SYSTEMS (already built — Phase 0)             │
│   RPG · Quests · Journal · Bibles (Grandpa)             │
│   Teaching Mode · TUI Screens                            │
└─────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────┐
│                   NOTIFICATIONS                          │
│   ntfy.sh · Punishment Mode · Accountability            │
└─────────────────────────────────────────────────────────┘
```

### 2.3 Phase-by-phase target state

#### Phase 1 — Connector Layer (NEXT)
**Deliverable:** `AgentProcess` base class, OllamaAgent refactored to extend it, BigBroAgent (Claude CLI) and LilBroAgent (Codex CLI) ported from cloud, SESSION.md as unified cross-talk layer, per-bro backend assignment, FLEX mode, CLI detect + install, live `/backend` switching, dynamic status bar.

**Result:** User can mix backends — e.g. Big Bro on Claude for coding, Lil Bro on Ollama for quick explanations. No API keys — subscription-based CLI only. Gemini pinned for later.

#### Phase 2 — Memory System
**Deliverable:** `src_local/memory/` — Chroma vector DB, project registry, file watcher, preference log, context injector.

**Result:** LIL BRO remembers past sessions. "What was wrong with the mesh pipeline last week?" finds the right session by meaning, not keywords. Gets more useful over time.

#### Phase 3 — Roadmap Engine
**Deliverable:** `src_local/roadmap/` — brainstorm, planner, executor, living map, icebox.

**Result:** LIL BRO transforms from chat tool to autonomous executor. User locks a goal; LIL BRO breaks it into tasks, shows plan before each, user approves, LIL BRO executes and verifies. New ideas hit the Icebox, never interrupt flow.

#### Phase 4 — Persona System
**Deliverable:** `src_local/personas.py` — Mom, Dad, Grandma as concurrent advisory voices.

**Result:** Every interaction has three lenses. Mom keeps momentum, Dad challenges efficiency, Grandma remembers patterns. User can address any directly ("Dad, is this plan lean enough?").

#### Phase 5 — Teaching Mode++
**Deliverable:** Adaptive difficulty using memory, connector-aware lesson delivery, Grandma auto-leads teach mode, XP reflects connector usage.

**Result:** Teaching mode adapts to what you already know. Quest XP weighted by connector used (building an API connector earns both Python XP and API XP).

#### Phase 6 — PWA + Phone (Punishment Mode)
**Deliverable:** `src_local/pwa/` — Progressive Web App over Tailscale, ntfy.sh push notifications, mobile roadmap view.

**Result:** Big Bro stays at your dev machine as a daemon. You run Lil Bro on your phone from a coffee shop. Remote pair programming with your AI doing the typing.

### 2.4 The persona council (end state detail)

| Persona | Owns | Tone | Trigger |
|---|---|---|---|
| 👩 MOM | Organization, accountability, momentum, wellbeing | Warm, encouraging, persistent | Planning, drift from roadmap, long sessions, missed deadlines |
| 👨 DAD | Execution, efficiency, hard truths, scope discipline | Terse, direct, practical | Task execution, bloated plans, tech calls, scope creep |
| 👵 GRANDMA | Memory, patterns, big picture, wisdom from history | Patient, philosophical, long-view | Brainstorm, learning, big decisions, repeated mistakes |

All three evaluate every context. The dominant one surfaces, but user can address any directly. Grandma auto-leads teaching. Mom monitors roadmap. Dad drives execution.

### 2.5 The living roadmap (end state detail)

```
🎯 MILESTONE   — major goal agreed in brainstorm
⬜ TASK         — specific build step
✅ COMPLETED    — done, logged to memory
🔄 IN PROGRESS  — executing now
💡 ICEBOX       — idea captured, not yet planned
📋 BACKLOG      — planned but not scheduled
```

Brainstorm → Goal Lock → Plan → Execute → Living Roadmap. Never "done" — always evolving.

### 2.6 Success criteria

LIL BRO v2 is complete when:

- [ ] User can assign any supported backend to either bro independently
- [ ] Mixed-backend sessions work seamlessly (cross-talk, permissions, status)
- [ ] FLEX mode for Lil Bro picks the right backend per task without manual intervention
- [ ] Every session contributes to memory that future sessions can retrieve
- [ ] User can brainstorm a goal, approve a plan, and watch LIL BRO execute it task by task
- [ ] All three personas active and surfacing at the right moments
- [ ] Teaching mode adapts difficulty based on memory of what user has learned
- [ ] PWA available on mobile over Tailscale, accountability notifications via ntfy.sh
- [ ] Every phase has daily-use validation for at least one week before next phase begins

---

## Part 3 — Audit Framework (use while building)

### 3.1 What to check on every change

- [ ] Does this break anything in the current released version?
- [ ] Is the existing Ollama path still working?
- [ ] Does the change move us closer to the end game architecture?
- [ ] Is `ROADMAP.md` updated to reflect the new state?
- [ ] Is `README.md` updated if user-facing behavior changed?
- [ ] Are tests added/updated for new code paths?
- [ ] Does CI still pass on all three platforms?

### 3.2 Test coverage targets for Phase 1

| Area | Test file (new or existing) |
|---|---|
| AgentProcess base class | `tests/test_agent_base.py` (NEW) |
| OllamaAgent refactor | Extend `tests/test_tools.py` + add agent lifecycle tests |
| BigBroAgent (Claude CLI wrapper) | `tests/test_big_bro.py` (NEW, mocked subprocess) |
| LilBroAgent (Codex CLI wrapper) | `tests/test_lil_bro_codex.py` (NEW, mocked subprocess) |
| SESSION.md cross-talk | `tests/test_cross_talk.py` (NEW) |
| Per-bro backend config | Extend `tests/test_config.py` |
| CLI detection | `tests/test_cli_detect.py` (NEW) |
| FLEX mode task classifier | `tests/test_flex.py` (NEW) |
| Backend switch command | Extend command tests |

### 3.3 Documentation update rules

- **ROADMAP.md** — check off each `[ ]` as it lands. Move completed phases from "NEXT" to "DONE".
- **README.md** — update the "Features" section when user-visible features ship. Update "How It Works" when architecture changes. Don't mention in-flight features.
- **CONTEXT.md** (this file) — Part 1 grows as features ship. Part 2 shrinks as phases complete. Part 3 stays as the audit framework.
- **CHANGELOG** — none yet, add one if release process needs it.

### 3.4 Invariants that must hold

These never change regardless of phase:

1. **Local-first:** Every feature must work fully offline on Ollama. Cloud backends are additive.
2. **No required API keys:** Subscription-based CLI tools only, or Ollama.
3. **Lil Bro read-only by default:** Only `/bunkbed` or explicit user action unlocks write access.
4. **Grandpa is Ollama-only:** Cloud models don't need bible injection; they already have that capability.
5. **Cross-platform:** Windows, macOS, Linux must all stay working — no platform-specific blockers.
6. **No regressions:** Daily use flow must stay unbroken between phases.

---

*This document is the anchor. Update Part 1 as features ship. Update Part 2 as phases complete. Use Part 3 to audit every change.*
