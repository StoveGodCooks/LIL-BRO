# LIL BRO LOCAL — Roadmap

Local-first personal AI OS. Model-agnostic. Gets smarter the longer you use it.

---

## Status at a glance

| Phase | Name | Status |
|---|---|---|
| 0 | Foundation | ✅ DONE |
| 1 | Connector Layer | ✅ DONE |
| 2 | Memory System | ✅ DONE |
| 3 | Roadmap Engine | ✅ DONE |
| 4 | Persona System | ✅ DONE |
| 5 | Teaching Mode++ | ✅ DONE |
| 6 | PWA + Phone | ✅ DONE |

---

## ✅ Phase 0 — Foundation (DONE)

Everything already built and in daily use.

### Core
- [x] Textual TUI — dual-pane layout, Big Bro / Lil Bro
- [x] OllamaAgent — HTTP streaming, tool calling (read/write/edit/grep/run), cancel, heartbeat
- [x] Grandpa (hybrid bible retrieval) — keyword pre-scan + model lookup, confidence merge
- [x] Router — active-target dispatch, slash command handling, cross-talk port
- [x] VRAM detection — auto context window sizing per model, RTX 3070 aware
- [x] Hardware detection — GPU, VRAM, RAM
- [x] Ollama auto-detect + guided install

### RPG System
- [x] Player profile — level, XP, skills
- [x] XP engine + leveling logic
- [x] Domain skill tree (Python, Game Dev, etc.)
- [x] Badge / achievement system
- [x] Challenge runner + boss fights
- [x] Teaching mode state

### Quest System
- [x] YAML quest loader + models + state + validators
- [x] World map — OOP, loop, cave, marsh, async, boss areas (48 quests)

### Journal
- [x] Session recorder + log management
- [x] Session lock (no concurrent sessions)
- [x] HTML export

### Bibles
- [x] Compiled coding + reasoning knowledge bases (JSON)
- [x] Search indexes
- [x] Bible store (lookup + retrieval)

### UI Screens
- [x] Main app, input bar, status bar, XP bar, panels
- [x] Campaign map, challenge block, command palette
- [x] Settings screen, help screen, notes screen, search screen
- [x] First run wizard, project switcher, compose screen
- [x] Slash command autocomplete, debug overlay, Pac-Man loader
- [x] Model picker (grid UI, fast startup)

---

## 🔨 Phase 1 — Connector Layer (IN PROGRESS)

Pluggable backend architecture. Each bro gets its own backend. Keeps Ollama as default, adds Claude Code CLI and Codex CLI via user subscriptions. No API keys.

**Rule:** Phase 2 does not start until Phase 1 is in daily use for at least one week.

### Base class
- [x] Port `AgentProcess` from cloud → `src_local/agents/base.py`
  - Shared lifecycle: lock, task tracking, heartbeat, cancel, RSS monitor, backpressure
  - Fix imports: `src.*` → `src_local.*`
- [x] Refactor `OllamaAgent` to extend `AgentProcess`

### Cloud connectors (subscription-based CLI, no API keys)
Connectors are backend-named, not role-named. The user assigns any
connector to either bro — there's no "this one is Big Bro, this one is
Lil Bro" at the connector layer.

- [x] Port Claude connector → `src_local/agents/claude_agent.py`
  - `ClaudeAgent(AgentProcess)` — wraps `claude` CLI in stream-json mode
  - Uses Claude Max / Pro subscription
- [x] Port Codex connector → `src_local/agents/codex_agent.py`
  - `CodexAgent(AgentProcess)` — wraps `codex mcp-server` via JSON-RPC 2.0
  - Uses ChatGPT Plus / Pro subscription
- [x] Role-agnostic interface: every connector accepts a `display_name`
  and `role` (big | lil) at construction so the same class can power
  either pane

### CLI detection + install
- [x] On startup, detect if `claude` / `codex` CLIs are installed
  - `src_local/agents/cloud_install.py` — unified `detect_provider` / `detect_all`
- [x] If missing: propose guided install (same flow as Ollama detection)
  - `install_cli()` runs `npm install -g @anthropic-ai/claude-code` or `@openai/codex`
  - Platform-aware fallback messaging when `npm` / `node` is absent
- [ ] Auth health check — re-prompt if login expired *(deferred — auth failures surface at first-turn runtime; interactive `claude login` / `codex login` flow is out of scope for Phase 1)*

### Cross-talk unification
- [x] Replace BROS_LOG with SESSION.md as unified cross-talk layer
- [x] All backends read/write to SESSION.md regardless of backend type
- [x] OllamaAgent sibling context injection switches from BROS_LOG → SESSION.md
- [x] Cloud agents already use SESSION.md via sibling briefing

### Per-bro backend assignment
- [x] Each bro assigned independently: `ollama | claude | codex`
- [x] User can assign same backend to both or different backends
- [x] Config shape (both long and shorthand accepted):
  ```yaml
  # Long form
  big_bro:
    backend: ollama        # ollama | claude | codex
    model: qwen2.5-coder:7b

  lil_bro:
    backend: flex          # ollama | claude | codex | flex
    adaptive_fallback: ollama

  # Shorthand
  big_bro: claude/sonnet-4
  lil_bro: codex/gpt-5-codex
  ```

### FLEX mode (Lil Bro adaptive routing)
- [x] `/flex` — toggle Lil Bro FLEX mode on/off inline
- [x] Task classifier — heuristics-based, picks best available backend:
  - `/explain`, `/teach`, concept questions → Codex
  - Code gen, file edits, refactors → Claude
  - Quick questions, offline → Ollama
  - Complex reasoning → Claude or Codex
- [x] Falls back to Ollama if preferred backend unavailable

### Permissions
- [x] Lil Bro read-only on all backends by default
- [x] `/bunkbed` unlocks Lil Bro write access regardless of backend
- [x] Codex: enforce via `sandbox_mode="read-only"` on spawn *(Claude already enforces via permission-mode=plan)*

### UI changes shipped alongside connectors
- [x] Live collapsible tool call feed — yellow headers, expand for Read/Edit/Bash/Write detail
- [x] Bro-colored streaming text — orange for Big Bro, green for Lil Bro
- [x] Claude session persistence — auto-save/restore in project mode; `/resume` for manual
- [x] `/reset` clears both agents + deletes project session files
- [x] Clipboard screenshot paste — Ctrl+Shift+V, no manual file save required
- [x] Markdown link stripping — `[label](url)` → `label` for clean terminal output
- [x] Short path display — `...ui/panels.py` not `C:\Users\...`
- [x] Auto-scroll only when already at bottom (no forced pinning mid-read)

### Setup flow (first_run.py extension)
- [x] Mode selection: local (Ollama) / cloud (Claude/Codex) / flex
- [x] Cloud path: detect CLI, guided install if missing
- [x] Choice persisted to config (first-run result written back to config.yaml)

### Live switching
- [x] `/backend big [ollama|claude|codex]` — swap Big Bro backend mid-session
- [x] `/backend lil [ollama|claude|codex|flex]` — swap Lil Bro backend mid-session
- [x] Restarts the relevant agent subprocess cleanly

### Status bar (full dynamic)
- [x] Shows backend + model per bro at all times
  - e.g. `Big Bro · claude · sonnet-4   Lil Bro · ollama · qwen2.5:7b`
- [x] `[FLEX]` indicator when Lil Bro is in FLEX mode
- [x] Updates live when backend switched

---

> *️⃣ **Gemini CLI** — architecture designed, subprocess wrapper approach ready.
> Gemini CLI is one-shot only (no persistent mode). Watching
> [github.com/google-gemini/gemini-cli/issues/15338](https://github.com/google-gemini/gemini-cli/issues/15338)
> for daemon mode. When it lands, Gemini becomes a drop-in connector.
> API key path also deferred to the same phase.

---

## ✅ Phase 2 — Memory System (DONE)

Persistent vector memory. Accumulates knowledge about you, your projects, and your patterns. Gets more useful the longer you run it.

**Depends on:** Phase 1

### New: `src_local/memory/`
- [x] `chroma_store.py` — local Chroma vector DB wrapper (optional dep, graceful no-op)
- [x] `project_registry.py` — register and track projects (JSON, no file watcher yet)
- [x] `session_summarizer.py` — summarize sessions via local Ollama model
- [x] `context_injector.py` — inject relevant memory into prompts
- [x] `preference_log.py` — log user preferences and patterns over time

### Commands
- [x] `/remember <note>` — store a manual memory entry
- [x] `/recall <query>` — semantic search over memories
- [x] `/memories [n]` — list the n most recent memory entries
- [x] `/forget <query>` — remove memories and preferences matching a query
- [x] `/prefs [n]` — show top observed preference patterns

### Behavior
- [x] Project registry registers and counts sessions on startup
- [x] Session summarized and stored in ChromaDB on shutdown (fire-and-forget)
- [x] Semantic search over past sessions via `/recall`
- [x] ContextInjector prepends relevant memories to prompts (when chromadb present)
- [x] Preference log surfaces patterns via `/prefs` ("you always use dataclasses for this")

---

## ✅ Phase 3 — Roadmap Engine (DONE)

The killer feature. Transforms LIL BRO from a chat tool into an autonomous project executor.

**Depends on:** Phases 1 + 2

### New: `src_local/roadmap/`
- [x] `living_map.py` — milestones + tasks + states, JSON persisted at `~/.lilbro-local/roadmap.json`
- [x] `icebox.py` — append-only idea capture with promote/drop lifecycle
- [x] `brainstorm.py` — structured 6-section brainstorm prompt builder
- [x] `planner.py` — milestone → tasks prompt + bullet-list parser
- [x] `executor.py` — task-by-task walker with user-approval briefings (not autonomous)

### Commands
- [x] `/roadmap` — render the living roadmap
- [x] `/brainstorm <goal>` — structured brainstorm routed to Lil Bro
- [x] `/milestone <title>` / `start <id>` / `done <id>` / `delete <id>`
- [x] `/plan-tasks <milestone_id>` — Big Bro breaks milestone into tasks
- [x] `/task list | add <mid> <title> | start | done | block | delete`
- [x] `/execute [milestone_id]` — prep next BACKLOG task with scope brief
- [x] `/icebox <idea> | list | drop <id> | promote <id> <milestone>`

### Workflow
```
BRAINSTORM → GOAL LOCK → PLAN → EXECUTE → LIVING ROADMAP
```
- User + LIL BRO brainstorm the goal together
- Goal locked as a milestone
- LIL BRO breaks it into features → tasks
- User hits Go — LIL BRO works task by task, shows plan before each, user approves
- New ideas go to Icebox, never interrupt execution
- Roadmap never "done" — it evolves

### Roadmap states
```
🎯 MILESTONE   — major goal agreed in brainstorm
⬜ TASK        — specific build step
✅ COMPLETED   — done, logged to memory
🔄 IN PROGRESS — executing now
💡 ICEBOX      — captured, not yet planned
📋 BACKLOG     — planned but not scheduled
```

---

## ✅ Phase 4 — Persona System (DONE)

Three concurrent advisory voices. Not modes — persistent lenses on every interaction.

**Depends on:** Phase 2

### New: `src_local/personas.py`

| Persona | Owns | Tone | Speaks when |
|---|---|---|---|
| 👩 MOM | Organization, accountability, momentum | Warm, persistent | Planning, roadmap drift, long sessions |
| 👨 DAD | Execution, efficiency, hard truths | Terse, direct | Task execution, scope creep, tech calls |
| 👵 GRANDMA | Memory, patterns, big picture | Patient, long-view | Brainstorm, big decisions, repeated mistakes |

- [x] Keyword classifier scores every prompt; dominant persona surfaces
- [x] User can address any directly: `/mom`, `/dad`, `/grandma`
- [x] `/persona [mom|dad|grandma|auto]` — lock dominant persona
- [x] Teaching mode forces Grandma
- [x] Roadmap-drift signal forces Mom
- [x] Default bias is Dad (execution)

---

## ✅ Phase 5 — Teaching Mode++ (DONE)

Adaptive difficulty wired to the connector layer and memory.

**Depends on:** Phases 1 + 2 + 4

### New: `src_local/teaching/`
- [x] `adaptive.py` — `DifficultyEngine` scores topic familiarity from PreferenceLog + MemoryStore + skill levels, emits novice/intermediate/advanced tier
- [x] `delivery.py` — backend router prefers Claude > Codex > Ollama for concepts, honors user-pinned backend, always falls back to Ollama offline
- [x] `character_sheet.py` — compact level/XP/skills/badges render

### Commands
- [x] `/sheet` — surface the character sheet from any screen
- [x] `/lesson <topic>` — adaptive lesson, connector-aware, Grandma-prefixed

---

## ✅ Phase 6 — PWA + Phone (DONE)

Mobile browser access over Tailscale. No App Store.

**Depends on:** Phase 3

### New: `src_local/pwa/`
- [x] Stdlib `http.server` in a background thread — zero extra deps
- [x] Single-page PWA (index + css + js) — mobile-optimized roadmap/memories/prefs/icebox views
- [x] Service worker for offline shell, network-first for `/api/*`
- [x] Manifest + icon — installable to home screen
- [x] JSON endpoints: `/api/roadmap`, `/api/memories`, `/api/prefs`, `/api/icebox`, `/api/health`
- [x] `notify.py` — ntfy.sh wrapper (topic from `notify.topic` in config.yaml or `$LILBRO_NTFY_TOPIC`)

### Commands
- [x] `/pwa start [port]` — start the server (default 8765)
- [x] `/pwa stop` — stop cleanly
- [x] `/pwa url` — show the current URL
- [x] `/notify <message>` — push to configured ntfy topic

---

## Out of scope (explicitly deferred)

| Feature | Target |
|---|---|
| Direct API keys (Claude, OpenAI, Gemini) | After Phase 1 ships |
| Gemini CLI connector | When #15338 lands |
| Cloud hosting / server | v3 |
| Native mobile app | v4+ |
| Voice input | v3+ |
| Multi-user support | v3+ |
| Fine-tuning models | v4+ |

---

*LIL BRO LOCAL — local-first, model-agnostic, gets smarter the longer you use it.*
