# LiL BRO

<p align="center">
  <img src="assets/logo.png" alt="THE BROS — local-model coding TUI" width="480"/>
</p>

**A local AI coding assistant that runs entirely on your machine.** No API keys, no cloud, no billing. Just you, your GPU, and two bros who won't stop arguing.

LiL BRO is a dual-agent TUI (terminal user interface) that wraps [Ollama](https://ollama.com) to give you two AI coding assistants working side by side:

- **Big Bro** (right pane) — the coder. Reads, writes, and edits your files. Runs commands. Gets things done.
- **Lil Bro** (left pane) — the helper. Read-only. Explains code, debugs logic, teaches concepts. The brains.

They share a workspace, they know about each other, and they will absolutely talk trash when the other one is idle.

![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Ollama](https://img.shields.io/badge/powered%20by-Ollama-orange)

---

## How It Works

LiL BRO runs a local Ollama model (default: `qwen2.5-coder:7b`) and gives it real tools — file reading, code search, file editing, shell commands, and a knowledge base called Grandpa. Everything stays on your machine.

```
 YOU
  |
  v
[Input Bar] --Tab--> switches between Big Bro / Lil Bro
  |
  +---> Big Bro (coder) ---> Ollama 7b ---> tools (read/write/edit/run)
  |                                    \--> Grandpa (knowledge base)
  |
  +---> Lil Bro (helper) ---> Ollama 7b ---> tools (read-only)
                                         \--> Grandpa (knowledge base)
```

Both bros talk to the same local model. The difference is their **system prompt** (personality, rules, role) and their **tool access** (Big Bro can write, Lil Bro can't — unless you turn on Bunkbed mode).

---

## Features

### Dual-Agent Layout
Two panes, two personalities. Tab between them. Ask Big Bro to write code, ask Lil Bro to explain it. They work on the same project simultaneously.

### Grandpa (Knowledge Base)
Both bros have access to **Grandpa** — a local knowledge base with two bibles:

- **Coding Bible** — API docs, syntax references, stdlib patterns, code examples, data structure guides
- **Reasoning Bible** — debugging strategies, algorithm analysis, design tradeoffs, estimation techniques

Grandpa uses **hybrid retrieval**:
1. **Pre-scan**: When you ask a question, keywords from your query are matched against bible entry tags to pull candidate references
2. **Model pull**: The model also calls `coding_lookup` / `reasoning_lookup` tools with a smarter, inferred query
3. **Merge**: Results from both retrievers are merged with confidence scoring — entries that both retrievers agree on are marked as high confidence and shown first

This means even if the model writes a bad search query, the keyword pre-scan catches relevant entries. And even if keywords miss the right entry, the model's semantic understanding fills the gap.

### Shared Workspace Log (BROS_LOG)
Both bros write summaries of what they're working on to a shared log file. Each bro can see what the other has been doing — it gets injected into their context automatically. This is passive cross-talk: they don't message each other directly, but they're aware of each other's work.

### Bro Bickering
The bros have personality. They:
- **Introduce themselves** on startup with a YERRR message
- **Post working phrases** while processing ("hold on, I'm cooking...", "lemme think about this one...")
- **Roast each other** when one is idle and the other is working ("Lil Bro over there taking a nap while I do all the work")
- **Notify each other** when one is struggling with errors ("yo, Big Bro keeps getting errors over there lol")

### Bunkbed Mode
By default, Lil Bro is read-only — he can look at your code but can't touch it. Run `/bunkbed` to give him full write access. Now both bros can edit files, run commands, and make changes. Run `/bunkbed` again to lock him back down.

### Tool Calling
Big Bro has access to:
- `read_file` — read any file in the project
- `list_directory` — browse the file tree
- `grep_files` — search code with regex
- `write_file` — create new files or full rewrites
- `edit_file` — targeted find-and-replace edits
- `run_command` — execute shell commands
- `coding_lookup` / `reasoning_lookup` — ask Grandpa
- `calculate` — safe math evaluation (never does math in its head)

Lil Bro gets the read-only subset plus Grandpa and calculator.

### Unified Rule System
Both bros share the same coding rules and reasoning rules. The difference is **weighting**: reasoning rules come first (primary skill set) for both, with coding rules as secondary. Big Bro's role intro tells him to write code directly; Lil Bro's tells him to advise and explain.

This architecture means:
- Both bros think before they act (reasoning-first)
- Big Bro executes after thinking; Lil Bro teaches after thinking
- In bunkbed mode, Lil Bro can code too — and his reasoning-first approach makes his code solid

### Retry and Failure System
If a bro hits consecutive tool errors:
- At 4 errors: warns the sibling bro ("Big Bro is struggling over there...")
- At 5 errors: stops completely and tells the user honestly ("I don't want to write bad code. Tell me more about what you need.")

No hallucinated fixes. No pretending it worked. If it's stuck, it says so.

### Honesty Rules
Both bros follow strict anti-hallucination rules:
- Never make up code, APIs, or libraries that don't exist
- Never pretend to use a tool without actually using it
- Never hallucinate file contents — read first, then talk
- If stuck, say so and work with the user
- If wrong, own it immediately

### RPG / Progression System
Optional gamification layer:
- Earn XP for tasks, unlock badges
- Quest system with coding challenges
- Campaign map with skill areas
- Can be ignored entirely if you just want to code

### Session Management
- Session logs track everything across restarts
- Journal system records commands, decisions, and agent output
- BROS_LOG persists between sessions so the bros remember context

---

## Quick Start

### Requirements
- Python 3.11+
- 8GB+ RAM (16GB recommended)
- GPU with 6GB+ VRAM for 7b model (or CPU-only with 3b)
- [Ollama](https://ollama.com) installed

### Install

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/LiL-BRO.git
cd LiL-BRO

# Install
pip install -e .

# Start (first run launches setup wizard)
lilbro-local
```

The setup wizard will:
1. Check if Ollama is installed
2. Start the Ollama daemon if needed
3. Let you pick and pull a model (7b recommended)
4. Launch the dual-pane interface

### Models

| Model | VRAM | Speed | Quality |
|-------|------|-------|---------|
| `qwen2.5-coder:7b` | ~5-6 GB | Medium | Recommended |
| `qwen2.5-coder:3b` | ~2-3 GB | Fast | Lower quality |
| `qwen2.5-coder:14b` | ~9-10 GB | Slower | Best quality |

Switch models anytime with `/model qwen2.5-coder:14b`.

---

## Usage

### Basic
```
Tab          — switch between Big Bro and Lil Bro
Enter        — send message to active bro
Ctrl+C       — copy last response to clipboard
Ctrl+Q       — quit
F1           — help screen
F3           — multi-line compose
Alt+Left/Right — resize panes
```

### Slash Commands
```
/plan <task>     — plan a task step by step (examines files, consults Grandpa)
/bunkbed         — toggle Lil Bro's write access
/model <name>    — switch model
/settings        — open settings modal
/status          — show system status
/history         — view conversation history
/clear           — clear panel
/help            — show all commands
```

---

## Configuration

Copy `config.yaml` to `~/.lilbro-local/config.yaml` to customize:

```yaml
ollama:
  base_url: "http://127.0.0.1:11434"
  model: "qwen2.5-coder:7b"
  context_window: 32768
  temperature: 0.1
```

---

## Architecture

```
src_local/
  app.py              — main app, screen management, agent wiring
  router.py            — routes user input to active agent or command handler
  config.py            — YAML config loader
  skills.py            — skill/plugin loader
  path_utils.py        — path sandboxing

  agents/
    ollama_agent.py    — core agent: streaming, tool loop, hybrid retrieval,
                         system prompts, heartbeat, sibling awareness
    tools.py           — tool schemas + executors (read/write/edit/run/grep/bible)
    phrases.py         — personality text (intros, working phrases, roasts)
    ollama_install.py  — Ollama detection, install, model pulling
    hardware.py        — GPU/VRAM/RAM detection

  bibles/
    store.py           — bible retrieval engine (tag-scored lookup)
    coding.bible.json  — coding knowledge base
    reasoning.bible.json — reasoning knowledge base
    *.index.json       — precompiled tag indexes
    expand_bible.py    — bible expansion script

  commands/
    handler.py         — slash command parser and executor

  ui/
    app.tcss           — Textual CSS theme
    panels.py          — Big Bro / Lil Bro panel widgets
    input_bar.py       — input bar with target switching
    first_run.py       — setup wizard
    settings_screen.py — settings modal
    status_bar.py      — bottom status bar
    command_palette.py — inline slash command picker
    ...                — help, compose, search, campaign map screens

  journal/             — session logging and HTML export
  rpg/                 — XP, badges, skills, challenges (optional)
  quests/              — quest content and state (optional)
```

---

## The Process

LiL BRO was built iteratively with a specific philosophy:

1. **Build for the smallest model first.** If it works on 3b, it flies on 7b and dominates on 14b. Every feature is designed to compensate for small model limitations — hybrid retrieval, strict rules, tool loop guards.

2. **Reasoning before coding.** Both bros get reasoning rules as their primary skill set. Stress testing proved that reasoning-first produces better code than coding-first, even for the coding agent.

3. **Grandpa fills knowledge gaps.** Small models hallucinate when they don't know something. Grandpa's bible system grounds every answer in authoritative reference material, automatically injected before the model even sees the question.

4. **Honest failure over confident garbage.** The retry system, honesty rules, and sibling notifications all exist because a wrong answer that looks right is worse than no answer at all.

5. **Personality makes it usable.** The bickering, the YERRR intros, the roasts — they're not just fun. They give you feedback. Working phrases tell you it's thinking. Roasts tell you one bro is idle. Struggle notifications tell you something went wrong. Personality IS the UX.

---

## What's Coming: Punishment Mode

**Punishment** is the next major feature in development. The idea: split the bros across machines.

Right now both bros run on the same machine, talking to the same local Ollama instance. Punishment mode changes that:

- **Big Bro stays home** — on your main dev machine with the GPU, the codebase, and the tools. He's the one with write access. He does the work.
- **Lil Bro goes mobile** — runs on your laptop, tablet, or phone as a lightweight remote client. He connects to Big Bro over the network.

The workflow: you're on the couch, on a train, at a coffee shop. You open Lil Bro on your phone. You tell him what to build. He relays instructions to Big Bro back at your desk. Big Bro writes the code, runs the tests, reports back. Lil Bro reviews the results and tells you what happened.

It's remote pair programming where one partner is an AI that never sleeps and the other is you in your pajamas.

**Architecture (planned):**
```
[Your phone / laptop]          [Your dev machine]
  Lil Bro (client)  <--WS-->  Big Bro (server daemon)
    - read-only view              - full filesystem access
    - sends instructions          - executes code changes
    - reviews results             - runs commands & tests
    - asks Grandpa                - asks Grandpa
```

Why "Punishment"? Because Big Bro has to sit at the desk and work while Lil Bro gets to go outside. That's the punishment.

---

## License

MIT
