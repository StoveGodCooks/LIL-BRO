# LiL BRO

<p align="center">
  <img src="assets/logo.png" alt="THE BROS — local-model coding TUI" width="480"/>
</p>

**A model-agnostic AI coding assistant that lives on your machine.** No required API keys. No cloud billing. Just you, your GPU, and two bros who won't stop arguing.

LiL BRO is a dual-agent TUI (terminal user interface) that runs two AI coding assistants side by side. Each bro can be powered by a different backend — local Ollama, Claude Code CLI, or Codex CLI — and you can mix and match however you want.

- **Big Bro** — the coder. Reads, writes, and edits your files. Runs commands. Gets things done.
- **Lil Bro** — the helper. Read-only by default. Explains code, debugs logic, teaches concepts.

They share a workspace, they know about each other's moves via a live `SESSION.md` log, and they will absolutely talk trash when the other one is idle.

![Status](https://img.shields.io/badge/status-beta-red)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-PolyForm%20NC-blue)
![Ollama](https://img.shields.io/badge/powered%20by-Ollama-orange)
![Claude](https://img.shields.io/badge/powered%20by-Claude%20Code%20CLI-8B5CF6)
![Codex](https://img.shields.io/badge/powered%20by-Codex%20CLI-10B981)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

> **LiL BRO is in beta.** Expect rough edges and the occasional bro meltdown. We're building in public and moving fast — feedback and bug reports welcome.

> **Platform note:** LiL BRO runs on **Windows, macOS, and Linux**. Apple Silicon (M1/M2/M3/M4) is fully supported — Ollama runs natively on Metal and the bros will detect your unified memory automatically.

---

## How It Works

```
 YOU
  |
  v
[Input Bar] --Tab--> switches between Big Bro / Lil Bro
  |
  +---> Big Bro  ---> [Backend: Ollama | Claude | Codex]
  |                   tools: read/write/edit/grep/run
  |
  +---> Lil Bro  ---> [Backend: Ollama | Claude | Codex | FLEX]
                      tools: read-only (or write via /bunkbed)
```

Both bros talk to the same shared `SESSION.md` log so each can see what the other is doing — live, across all backends. You port context between them with Ctrl+B / Ctrl+C.

---

## Backends

LiL BRO is **model-agnostic**. Each bro is assigned its own backend independently. All three backends are subscription-based (no API keys required).

| Backend | How | Requirement |
|---------|-----|-------------|
| **Ollama** | Local HTTP streaming | Ollama installed |
| **Claude Code CLI** | `claude` subprocess, stream-json mode | Claude Max / Pro subscription |
| **Codex CLI** | `codex` subprocess, JSON-RPC 2.0 | ChatGPT Plus / Pro subscription |

Set backends in `config.yaml`:

```yaml
# Shorthand
big_bro: claude/claude-sonnet-4-5
lil_bro: ollama/qwen2.5-coder:7b

# Long form
big_bro:
  backend: claude
  model: claude-opus-4-7
lil_bro:
  backend: codex
  model: gpt-4o
```

Or use `/model big <name>` / `/model lil <name>` to switch live.

---

## Features

### Dual-Agent Layout
Two panes, two personalities. Tab between them. Ask Big Bro to write code, ask Lil Bro to explain it. They work on the same project simultaneously. Big Bro's text streams in **orange**, Lil Bro's in **green** — you always know who's talking.

### Live Tool Call Feed
When a bro is working, every tool call appears as a **collapsible yellow entry** — collapsed shows a short summary, click to expand for full detail:
- `Read` → shows the file contents
- `Edit` → shows the unified diff (before/after)
- `Bash` → shows the shell command
- `Write` → shows the full file being written

No more guessing what the model is doing. Watch it happen.

### Multi-Backend Support (Phase 1)
Each bro runs its own backend independently. Mix and match:

```
Big Bro: Claude Code CLI  →  writes code, runs tests, edits files
Lil Bro: Ollama local     →  explains logic, reviews diffs, teaches
```

Or go all-local:

```
Big Bro: Ollama (qwen2.5-coder:14b)
Lil Bro: Ollama (qwen2.5-coder:7b)
```

Or all-cloud during deep work sessions:

```
Big Bro: Claude (opus-4)
Lil Bro: Codex (gpt-4o)
```

### Session Continuity (Claude / Codex)
Claude and Codex backends maintain persistent session context across the life of the subprocess. Every connection prints a short session tag like `[abc12345]`. If you restart and want to continue that thread:

```
/resume abc12345         — resumes in Big Bro on next /restart
/resume lil cafe5678     — resumes in Lil Bro
```

Working in a registered project? Session is auto-saved and auto-resumed on next launch. Start completely fresh anytime with `/reset`.

### Grandpa (Knowledge Base)
Both bros have access to **Grandpa** — a local knowledge base with two bibles:

- **Coding Bible** — API docs, syntax references, stdlib patterns, code examples
- **Reasoning Bible** — debugging strategies, algorithm analysis, design tradeoffs

Grandpa uses **hybrid retrieval**:
1. **Pre-scan** — keywords from your query matched against bible entry tags
2. **Model pull** — the model calls `coding_lookup` / `reasoning_lookup` tools with a smarter inferred query
3. **Merge** — results merged with confidence scoring; entries both retrievers agree on shown first

> Grandpa is Ollama-only. Claude and Codex backends already carry that knowledge — they don't need it injected.

### Shared Workspace Log (SESSION.md)
Every backend reads and writes the same `SESSION.md` at your project root. LIL BRO streams append-only breadcrumbs as work happens — user prompts, agent replies, tool calls, file edits. Each bro can see what the other is doing across all backends, passively, without direct messaging.

### Clipboard Screenshot Paste
Press **Ctrl+Shift+V** to paste a screenshot directly from your clipboard. LIL BRO saves it to `~/.lilbro-local/tmp/` and injects the file path into your input bar — no manual file saving required. Attach UI screenshots, error dialogs, or reference images to your messages.

### BYOM — Bring Your Own Model
LiL BRO supports any model Ollama can run. The first-run wizard has curated picks (Qwen Coder, DeepSeek, Codestral, Llama, Phi) plus a Custom option. Context windows are calculated dynamically from the model's architecture — no manual tuning needed. GGUF imports and custom fine-tunes work too: `ollama create mymodel -f Modelfile`, then `/model mymodel`.

### Bro Bickering
The bros have personality. They:
- Introduce themselves on startup with a YERRR message
- Post working phrases while processing ("hold on, I'm cooking...")
- Roast each other when one is idle ("Lil Bro over there taking a nap while I do all the work")
- Notify each other when one is struggling ("yo, Big Bro keeps hitting errors over there lol")

### Bunkbed Mode
By default, Lil Bro is read-only. Run `/bunkbed` to give him full write access across any backend. Run it again to lock him back down.

### RPG / Progression System
Optional gamification:
- Earn XP for tasks, unlock badges
- Quest system with coding challenges
- Campaign map with skill areas
- Can be ignored entirely if you just want to code

### Session Management
- Journal system records commands, decisions, and agent output
- `SESSION.md` persists between sessions so the bros remember context
- `/save` / `/load` journal snapshots
- `/debug-dump` bundles logs + session state into a zip for reporting

---

## Quick Start

### Requirements
- Python 3.11+
- 8GB+ RAM (16GB recommended)
- GPU with 6GB+ VRAM for 7b model (or CPU-only with 3b)
- [Ollama](https://ollama.com) installed (for local backend)

### Install Ollama

**Windows:**
```bash
winget install Ollama.Ollama
```

**macOS:**
```bash
brew install ollama
```

**Linux:**
```bash
curl -fsSL https://ollama.ai/install.sh | sh
```

### Install LiL BRO

```bash
# Clone the repo
git clone https://github.com/StoveGodCooks/LIL-BRO.git
cd LIL-BRO

# Install
pip install -e .

# Start (first run launches setup wizard)
lilbro-local
```

The setup wizard will:
1. Detect your hardware (GPU, VRAM, RAM)
2. Ask which mode: local (Ollama), cloud (Claude/Codex), or flex
3. For local: check Ollama, let you pick and pull a model
4. For cloud: detect CLI installations, guide installs if missing
5. Launch the dual-pane interface

### Models

**Ollama — recommended for local use:**

| Model | VRAM | Speed | Notes |
|-------|------|-------|-------|
| `qwen2.5-coder:7b` | ~5-6 GB | Medium | ⭐ Recommended default |
| `qwen2.5-coder:14b` | ~9-10 GB | Slower | Best local quality |
| `qwen2.5-coder:3b` | ~2-3 GB | Fast | Lightweight option |
| `deepseek-coder-v2` | ~9 GB | Medium | Strong coder |
| `llama3.1:8b` | ~5-6 GB | Medium | Good general + tools |

**Claude Code CLI — requires Claude Max/Pro:**
```
/model big claude-opus-4-7
/model big claude-sonnet-4-5
```

**Codex CLI — requires ChatGPT Plus/Pro:**
```
/model big gpt-4o
/model big gpt-4.1
```

---

## Slash Commands

```
/help                   — full help screen (also F1)
/settings               — open settings modal

--- Messages ---
/explain <topic>        — 6-section teaching breakdown (→ Lil Bro)
/plan <task>            — outline Goal/Steps/Files/Risks before coding (→ Big Bro)
/review                 — 4-section code review of Big Bro's last reply (→ Lil Bro)
/review-file <path>     — Lil Bro reads and reviews a specific file
/compare <a> | <b>      — structured compare/contrast teaching
/explain-diff           — teach through Big Bro's last reply
/trace <symbol>         — walk the call graph of a function/class
/debug <error>          — structured debug walkthrough

--- Models ---
/model                  — show current model for both bros
/model big <name>       — switch Big Bro's model (restarts agent)
/model lil <name>       — switch Lil Bro's model (restarts agent)
/models                 — list models available in Ollama

--- Session ---
/focus <task>           — pin a goal in the status bar + journal
/focus                  — clear current focus
/resume <session_id>    — resume a specific Claude/Codex session on next restart
/resume big|lil <id>    — target a specific bro
/reset                  — fresh session — clears threads, removes project sessions
/save [name]            — save the session journal
/load                   — list 10 most recent journals
/history clear          — clear conversation history (keep system prompt)

--- Sessions / Projects ---
/session-save <name>    — bookmark current project dir as a named session
/session-open <name>    — show info for a saved session
/sessions               — list all saved sessions

--- Navigation ---
/cwd  /pwd              — show project directory
/journal                — show current journal file path
/session                — show live SESSION.md log (last 80 lines) · F2
/state                  — dump diagnostics (python, pids, models, paths)
/status                 — show Ollama connection status and model info

--- Tools ---
/wrap                   — toggle soft word-wrap on active panel
/clear                  — wipe active panel scrollback
/debug-dump             — bundle debug.log + SESSION.md + journal into a zip
/find <query>           — grep across saved journals for a substring
/export-html            — export current journal to styled HTML

--- Bro Controls ---
/bunkbed                — toggle Lil Bro write access (default: read-only)
/restart [a|b|both]     — force-restart an agent (bypasses cooldown)

--- Meta ---
/player                 — show RPG card (level, skills, badges, perks)
/skills                 — list installed skill plugins
/quit  /exit            — shut down THE BROS
```

---

## Keyboard Shortcuts

```
Tab              — switch active bro
Enter            — send message
Ctrl+C           — copy last response to clipboard
Ctrl+B           — port Big Bro's last message to Lil Bro
Ctrl+Shift+V     — paste clipboard screenshot as attachment
Ctrl+Q           — quit
F1               — help screen
F2               — SESSION.md viewer
F3               — multi-line compose
Alt+Left/Right   — resize panes
```

---

## Configuration

`~/.lilbro-local/config.yaml`:

```yaml
# Per-bro backend assignment
big_bro: claude/claude-sonnet-4-5   # or ollama/qwen2.5-coder:7b or codex/gpt-4o
lil_bro: ollama/qwen2.5-coder:7b

# Ollama settings (used when backend is ollama)
ollama:
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5-coder:7b"
  context_window_big: auto          # or integer e.g. 32768
  context_window_lil: auto
  temperature: 0.1

# Colors
colors:
  primary: "#A8D840"
```

---

## Architecture

```
src_local/
  app.py              — main app, screen management, agent wiring
  router.py           — routes user input to active agent or command handler
  config.py           — YAML config loader (per-bro backend schema)

  agents/
    base.py           — AgentProcess base class (lifecycle, heartbeat, cancel, RSS)
    connectors.py     — CONNECTORS registry + build_agent() factory
    ollama_agent.py   — Ollama: HTTP streaming, tool loop, hybrid retrieval
    claude_agent.py   — Claude Code CLI: stream-json subprocess, session persistence
    codex_agent.py    — Codex CLI: JSON-RPC 2.0, MCP server, threadId management
    cloud_install.py  — CLI detection + guided install for Claude / Codex
    tools.py          — tool schemas + executors (read/write/edit/run/grep/bible)
    phrases.py        — personality text (intros, working phrases, roasts)
    ollama_install.py — Ollama detection, install, model pulling
    hardware.py       — GPU/VRAM/RAM detection

  bibles/
    store.py          — bible retrieval engine (tag-scored lookup)
    coding.bible.json — coding knowledge base
    reasoning.bible.json — reasoning knowledge base

  commands/
    handler.py        — slash command parser and executor

  ui/
    panels.py         — Big Bro / Lil Bro panels (VerticalScroll + Collapsible)
    app.tcss          — Textual CSS theme
    input_bar.py      — input bar, target switching, clipboard paste
    commands_meta.py  — single source of truth for all slash command metadata
    first_run.py      — setup wizard (local / cloud / flex mode selection)
    settings_screen.py — settings modal
    status_bar.py     — bottom status bar
    command_palette.py — inline slash command picker
    help_screen.py    — full help modal
    ...               — compose, search, project switcher, campaign map screens

  journal/            — session logging and HTML export
  rpg/                — XP, badges, skills, challenges (optional)
  quests/             — quest content and state (optional)
```

---

## What's in Dev (`dev` branch)

Phase 1 connector layer is actively shipping. Already merged:

- [x] `AgentProcess` base class with shared lifecycle (heartbeat, cancel, RSS monitor)
- [x] `ClaudeAgent` — Claude Code CLI connector, stream-json mode, role-agnostic
- [x] `CodexAgent` — Codex CLI connector, JSON-RPC 2.0, MCP server
- [x] `CONNECTORS` registry + `build_agent()` factory
- [x] Per-bro backend config (`big_bro: claude/model`, `lil_bro: ollama/model`)
- [x] SESSION.md as unified cross-talk layer across all backends
- [x] First-run mode selection (local / cloud / flex)
- [x] CLI auto-detect + guided install for Claude + Codex
- [x] Live collapsible tool call feed (yellow headers, expandable detail)
- [x] Bro-colored streaming text (orange = Big Bro, green = Lil Bro)
- [x] Claude session persistence — auto-save/restore in project mode, `/resume` for manual
- [x] Clipboard screenshot paste via Ctrl+Shift+V
- [x] Markdown link stripping — clean readable output in the terminal
- [x] Short Windows path display (`...ui/panels.py` not `C:\Users\...`)
- [x] WindowsPath JSON serialization fix in cloud connectors

Still in flight for Phase 1:

- [ ] FLEX mode — Lil Bro adaptive backend routing with task classifier
- [ ] `/backend big|lil [ollama|claude|codex]` live switching
- [ ] Full dynamic status bar (backend + model per bro, FLEX indicator)
- [ ] Bunkbed permissions enforced per-backend (sandbox mode for Codex)
- [ ] First-run backend choice persisted to config

---

## Roadmap

| Phase | Name | Status |
|-------|------|--------|
| 0 | Foundation (Ollama, tools, RPG, quests, journal) | ✅ Done |
| 1 | Connector Layer (Claude, Codex, multi-backend) | 🔨 Active |
| 2 | Memory System (Chroma vector DB, project registry) | Planned |
| 3 | Roadmap Engine (brainstorm → plan → execute loop) | Planned |
| 4 | Persona System (Mom / Dad / Grandma advisory layer) | Planned |
| 5 | Teaching Mode++ (adaptive difficulty, memory-aware) | Planned |
| 6 | PWA + Phone (Tailscale, ntfy.sh, mobile roadmap) | Planned |

### Phase 2 — Memory System
Persistent vector memory. Every session summarized and stored in a local Chroma DB. Future sessions can retrieve past work by meaning, not keywords ("what was wrong with the mesh pipeline last week?"). Project registry watches active files for live context.

### Phase 3 — Roadmap Engine
The killer feature. User + LIL BRO brainstorm a goal → lock it → LIL BRO breaks it into tasks → shows plan before each step → user approves → LIL BRO executes. New ideas go to an Icebox without interrupting flow. Roadmap never "done" — always evolving.

### Phase 4 — Persona System
Three persistent advisory voices active on every interaction:

| Persona | Owns | Tone |
|---------|------|------|
| 👩 MOM | Organization, accountability, momentum | Warm, persistent |
| 👨 DAD | Execution, efficiency, hard truths | Terse, direct |
| 👵 GRANDMA | Memory, patterns, big picture | Patient, long-view |

User can address any directly: *"Dad, is this plan efficient?"*

### Phase 6 — Punishment Mode
Big Bro stays at your desk as a daemon. Lil Bro runs on your phone over Tailscale. You're at a coffee shop. You tell Lil Bro what to build. He relays to Big Bro. Big Bro writes the code, runs the tests, reports back. Remote pair programming where one partner is an AI that never sleeps and the other is you in your pajamas.

---

## License

MIT
