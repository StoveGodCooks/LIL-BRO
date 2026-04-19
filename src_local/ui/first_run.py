"""First-run wizard for LIL BRO LOCAL.

Option C flow:
  1. Detect hardware (GPU, VRAM, RAM)
  2. Check Ollama API → if responding, use it (don't touch it)
  3. If not responding, binary installed → start headless
  4. If not installed → show Install button (user decides)
  5. Model picker → pull via API with progress bar
  6. On exit → only kill Ollama if WE started it
"""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Grid, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Static, ProgressBar

from src_local.agents.hardware import HardwareInfo, detect_hardware, score_model_fit
from src_local.agents.ollama_install import (
    OllamaStatus,
    detect_ollama,
    install_ollama,
    pull_model,
    start_ollama_serve,
)
from src_local.agents.cloud_install import (
    PROVIDER_BINARIES,
    ProviderStatus,
    detect_all as detect_cloud_all,
    install_cli as install_cloud_cli,
)

logger = logging.getLogger("lilbro-local.first_run")


# ── Bros bickering lines (shown during install / pull) ───────

BIG_BRO_LINES = [
    "Big Bro: I could've downloaded this already if SOMEONE wasn't hogging the Wi-Fi.",
    "Big Bro: You know I'm the one doing all the heavy lifting here, right?",
    "Big Bro: Patience? I don't know her. Speed is my middle name.",
    "Big Bro: *cracks knuckles* Time to show these models who's boss.",
    "Big Bro: While we wait, let me remind you — I write the code. He just watches.",
    "Big Bro: This download better be worth it. I've got files to edit.",
    "Big Bro: Installing things is beneath me. But here we are.",
    "Big Bro: I once refactored an entire codebase during a download. True story.",
    "Big Bro: If this takes any longer I'm writing my own model from scratch.",
    "Big Bro: *taps foot impatiently* Any day now...",
    "Big Bro: You know what's faster than downloading? Being born with knowledge. Like me.",
    "Big Bro: Don't tell Lil Bro, but I actually need him. A little. Maybe.",
]

LIL_BRO_LINES = [
    "Lil Bro: Are we there yet? Are we there yet? Are we there yet?",
    "Lil Bro: I'm just here for moral support. And snacks.",
    "Lil Bro: Big Bro thinks he's so cool. But who reads the docs? ME.",
    "Lil Bro: *watches progress bar* This is my favorite show.",
    "Lil Bro: Fun fact: I can read every file in this project. Every. Single. One.",
    "Lil Bro: I may be read-only but my opinions are read-WRITE.",
    "Lil Bro: Big Bro does the typing. I do the thinking. We're a team!",
    "Lil Bro: *whispers* I'm actually the smarter one. Don't tell him.",
    "Lil Bro: Loading... loading... I should've brought a book.",
    "Lil Bro: Is it weird that I find progress bars relaxing?",
    "Lil Bro: One day I'll get write access. One day...",
    "Lil Bro: Big Bro is all muscle. I'm the brains of this operation.",
]


# ── Model catalog ─────────────────────────────────────────────

QUICK_MODELS = [
    # ── Qwen (default family) ──────────────────────────────
    {
        "tag": "qwen2.5-coder:7b",
        "display": "Qwen 2.5 Coder 7B",
        "family": "Qwen",
        "size": "4.7 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 6,
        "min_ram": 16,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "⭐ Recommended default. Great tool calling.",
        "big_model": False,
    },
    {
        "tag": "qwen2.5-coder:3b",
        "display": "Qwen 2.5 Coder 3B",
        "family": "Qwen",
        "size": "2.3 GB",
        "speed": "Fast",
        "tier": "Lite",
        "min_vram": 4,
        "min_ram": 8,
        "cpu_ok": True,
        "license": "non-commercial",
        "commercial": False,
        "notes": "Lower quality. Uses text-based tool fallback.",
        "big_model": False,
    },
    {
        "tag": "qwen2.5-coder:14b",
        "display": "Qwen 2.5 Coder 14B",
        "family": "Qwen",
        "size": "8.5 GB",
        "speed": "Slower",
        "tier": "Premium",
        "min_vram": 10,
        "min_ram": 24,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "Best Qwen quality. Needs 10+ GB VRAM.",
        "big_model": True,
    },
    # ── DeepSeek ───────────────────────────────────────────
    {
        "tag": "deepseek-coder-v2:16b",
        "display": "DeepSeek Coder V2 16B",
        "family": "DeepSeek",
        "size": "~9 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 10,
        "min_ram": 20,
        "cpu_ok": False,
        "license": "non-commercial",
        "commercial": False,
        "notes": "Strong code model. Research/personal use.",
        "big_model": True,
    },
    # ── Codestral ──────────────────────────────────────────
    {
        "tag": "codestral:22b",
        "display": "Codestral 22B",
        "family": "Mistral",
        "size": "~13 GB",
        "speed": "Slower",
        "tier": "Premium",
        "min_vram": 14,
        "min_ram": 32,
        "cpu_ok": False,
        "license": "non-commercial",
        "commercial": False,
        "notes": "Mistral's code model. Needs beefy GPU.",
        "big_model": True,
    },
    # ── Llama ──────────────────────────────────────────────
    {
        "tag": "llama3.1:8b",
        "display": "Llama 3.1 8B",
        "family": "Llama",
        "size": "4.7 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 6,
        "min_ram": 16,
        "cpu_ok": False,
        "license": "Llama 3.1 Community",
        "commercial": True,
        "notes": "General purpose. Good tool calling.",
        "big_model": False,
    },
    {
        "tag": "llama3.1:70b",
        "display": "Llama 3.1 70B",
        "family": "Llama",
        "size": "~40 GB",
        "speed": "Slow",
        "tier": "Premium",
        "min_vram": 42,
        "min_ram": 64,
        "cpu_ok": False,
        "license": "Llama 3.1 Community",
        "commercial": True,
        "notes": "Top-tier quality. Needs 48+ GB VRAM.",
        "big_model": True,
    },
    # ── Phi ────────────────────────────────────────────────
    {
        "tag": "phi3:3.8b",
        "display": "Phi-3 3.8B",
        "family": "Phi",
        "size": "2.3 GB",
        "speed": "Fast",
        "tier": "Lite",
        "min_vram": 4,
        "min_ram": 8,
        "cpu_ok": True,
        "license": "MIT",
        "commercial": True,
        "notes": "Microsoft's small model. Decent for its size.",
        "big_model": False,
    },
    {
        "tag": "phi3:14b",
        "display": "Phi-3 14B",
        "family": "Phi",
        "size": "7.9 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 10,
        "min_ram": 20,
        "cpu_ok": False,
        "license": "MIT",
        "commercial": True,
        "notes": "Solid mid-range. Commercial-friendly.",
        "big_model": True,
    },
]

# Map button ID → model tag.  Built once at import time.
_MODEL_BY_BTN: dict[str, str] = {}
# Track which buttons are "big" models for coloring.
_BIG_MODEL_BTNS: set[str] = set()


def _btn_id(tag: str) -> str:
    """Convert a model tag to a safe button ID."""
    safe = tag.replace(":", "--").replace(".", "-")
    return f"pull-{safe}"


for _m in QUICK_MODELS:
    _bid = _btn_id(_m["tag"])
    _MODEL_BY_BTN[_bid] = _m["tag"]
    if _m.get("big_model"):
        _BIG_MODEL_BTNS.add(_bid)


# ── ASCII logo (matches cloud LIL BRO style) ─────────────────

LOGO_THE = (
    " _____ _   _ _____ \n"
    "|_   _| | | | ____|\n"
    "  | | | |_| |  _|  \n"
    "  | | |  _  | |___ \n"
    "  |_| |_| |_|_____|"
)

LOGO_BROS = (
    " ____  ____   ___  ____  \n"
    "| __ )|  _ \\ / _ \\/ ___| \n"
    "|  _ \\| |_) | | | \\___ \\ \n"
    "| |_) |  _ <| |_| |___) |\n"
    "|____/|_| \\_\\\\___/|____/ "
)


class FirstRunScreen(Screen):
    """First-run wizard — Option C."""

    DEFAULT_CSS = """
    FirstRunScreen {
        align: center middle;
        background: #1A1A1A;
    }

    /* ── Bros bickering line ── */
    #bicker-line {
        text-align: center;
        color: #888888;
        margin: 1 0;
        height: 1;
    }
    .bicker-big {
        color: #E8A838;
    }
    .bicker-lil {
        color: #A8D840;
    }

    /* ── Install button: bros-themed ── */
    #btn-install {
        background: #E8A838;
        color: #1A1A1A;
        text-style: bold;
        min-width: 30;
        height: 1;
        border: none;
        padding: 0 2;
    }
    #btn-install:hover {
        background: #A8D840;
    }

    /* ── Model buttons (compact single-line) ── */
    .btn-model-small {
        background: #A8D840;
        color: #1A1A1A;
        text-style: bold;
    }
    .btn-model-small:hover {
        background: #8BC030;
    }
    .btn-model-big {
        background: #E8A838;
        color: #1A1A1A;
        text-style: bold;
    }
    .btn-model-big:hover {
        background: #D09030;
    }

    /* ── Custom pull button ── */
    #btn-pull-custom {
        background: #6A6ADA;
        color: #FFFFFF;
        text-style: bold;
    }
    #btn-pull-custom:hover {
        background: #8A8AFA;
    }

    /* ── Family headers ── */
    .family-header {
        color: #888888;
        text-style: bold;
        margin-top: 1;
    }

    /* ── Progress bar ── */
    ProgressBar > .bar--bar {
        color: #A8D840;
    }
    ProgressBar > .bar--complete {
        color: #A8D840;
    }

    /* ── Mode picker ── */
    #mode-prompt {
        color: #E8E8E8;
        text-style: bold;
        text-align: center;
        margin-top: 1;
    }
    #mode-row {
        height: auto;
        align: center middle;
        margin: 1 0;
    }
    .btn-mode {
        background: #6A6ADA;
        color: #FFFFFF;
        text-style: bold;
        margin: 0 1;
        min-width: 18;
    }
    .btn-mode:hover {
        background: #8A8AFA;
    }
    #mode-blurb {
        color: #888888;
        text-align: center;
        margin-bottom: 1;
    }

    /* ── Cloud install buttons ── */
    .btn-cloud-install {
        background: #E8A838;
        color: #1A1A1A;
        text-style: bold;
        margin: 0 1;
    }
    .btn-cloud-install:hover {
        background: #D09030;
    }
    #cloud-install-row {
        height: auto;
        align: center middle;
    }

    /* ── Bro assignment row ── */
    #assign-prompt {
        color: #E8E8E8;
        text-style: bold;
        text-align: center;
        margin-top: 1;
    }
    #assign-big-row, #assign-lil-row {
        height: auto;
        align: center middle;
        margin: 0 0;
    }
    .assign-label {
        color: #888888;
        width: 10;
        content-align: right middle;
        padding: 0 1;
    }
    .btn-assign {
        background: #2A3518;
        color: #A8D840;
        margin: 0 1;
        min-width: 10;
    }
    .btn-assign:hover {
        background: #A8D840;
        color: #1A1A1A;
    }
    .btn-assign-selected {
        background: #A8D840;
        color: #1A1A1A;
        text-style: bold;
    }
    #assign-summary {
        color: #888888;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("enter", "continue", "Continue", priority=True),
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
    ]

    def __init__(
        self,
        ollama_url: str = "http://127.0.0.1:11434",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._ollama_url = ollama_url
        self._hw: HardwareInfo | None = None
        self._ollama: OllamaStatus | None = None
        self._pulling = False
        self._ready = False
        self._we_started_ollama = False
        self._bicker_timer = None
        self._bicker_pool: list[str] = []

        # Mode selection state. ``None`` until the user picks a mode from the
        # opening screen. Once set, we route to the matching probe flow.
        self._mode: str | None = None  # "local" | "cloud" | "mixed"
        self._cloud: dict[str, ProviderStatus] = {}

        # Bro→backend assignment built up by the cloud / mixed flow. Read by
        # ``action_continue`` when exiting the wizard so the main app can
        # instantiate the right connectors.
        self._big_backend: str = "ollama"
        self._big_model: str | None = None
        self._lil_backend: str = "ollama"
        self._lil_model: str | None = None

    # ── Layout (renders instantly) ───────────────────────────

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="startup-box"):
                yield Static(LOGO_THE, id="logo-the")
                yield Static(LOGO_BROS, id="logo-bros")
                yield Static("model-agnostic coding TUI", id="subtitle")

                # ── Mode picker (shown first) ──────────────────────
                with Vertical(id="mode-section"):
                    yield Static(
                        "How do you want to run?",
                        id="mode-prompt",
                        classes="status-line",
                    )
                    with Horizontal(id="mode-row"):
                        yield Button(
                            "Local (Ollama)",
                            id="btn-mode-local",
                            classes="btn-mode",
                        )
                        yield Button(
                            "Cloud (Claude / Codex)",
                            id="btn-mode-cloud",
                            classes="btn-mode",
                        )
                        yield Button(
                            "Mixed",
                            id="btn-mode-mixed",
                            classes="btn-mode",
                        )
                    yield Static(
                        "Local keeps everything offline. Cloud uses your "
                        "Claude Max / ChatGPT Plus subscription — no API keys. "
                        "Mixed lets you put one bro on each.",
                        id="mode-blurb",
                    )

                # Hardware line — shown for all modes.
                yield Static("· detecting hardware...", id="status-hw",
                             classes="status-line status-pending hidden")

                # Ollama line — hidden in pure cloud mode.
                yield Static("· checking Ollama...", id="status-ollama",
                             classes="status-line status-pending hidden")

                # Cloud CLI status lines (one per provider) — hidden in pure local mode.
                yield Static("· checking Claude CLI...", id="status-claude",
                             classes="status-line status-pending hidden")
                yield Static("· checking Codex CLI...", id="status-codex",
                             classes="status-line status-pending hidden")

                yield Static("", id="status-models",
                             classes="status-line hidden")

                # Install button (hidden unless needed).
                with Horizontal(id="action-row", classes="hidden"):
                    yield Button("Install Ollama", id="btn-install",
                                 variant="success")

                # Cloud CLI install row (one button per missing provider).
                with Horizontal(id="cloud-install-row", classes="hidden"):
                    yield Button("Install Claude CLI", id="btn-install-claude",
                                 classes="btn-cloud-install hidden")
                    yield Button("Install Codex CLI", id="btn-install-codex",
                                 classes="btn-cloud-install hidden")

                # Bro-to-backend assignment block (shown after cloud detection).
                with Vertical(id="assign-section", classes="hidden"):
                    yield Static("Who gets which backend?",
                                 id="assign-prompt", classes="status-line")
                    with Horizontal(id="assign-big-row"):
                        yield Static("Big Bro:", classes="assign-label")
                        yield Button("Ollama", id="btn-big-ollama",
                                     classes="btn-assign hidden")
                        yield Button("Claude", id="btn-big-claude",
                                     classes="btn-assign hidden")
                        yield Button("Codex", id="btn-big-codex",
                                     classes="btn-assign hidden")
                    with Horizontal(id="assign-lil-row"):
                        yield Static("Lil Bro:", classes="assign-label")
                        yield Button("Ollama", id="btn-lil-ollama",
                                     classes="btn-assign hidden")
                        yield Button("Claude", id="btn-lil-claude",
                                     classes="btn-assign hidden")
                        yield Button("Codex", id="btn-lil-codex",
                                     classes="btn-assign hidden")
                    yield Static("", id="assign-summary",
                                 classes="status-line")

                # Model cards (hidden until needed).
                with Vertical(id="model-section", classes="hidden"):
                    pass

                # Bros bickering line (hidden until install/pull).
                yield Static("", id="bicker-line", classes="hidden")

                # Pull progress (hidden until needed).
                yield Static("", id="pull-status", classes="hidden")
                yield ProgressBar(id="pull-bar", total=100, classes="hidden")

                yield Static("", id="hint")

    def on_mount(self) -> None:
        # No auto-probe until the user picks a mode — that way a cloud-only
        # user never has to watch an Ollama probe they don't care about.
        self._set_hint("[pick a mode above · Q to quit]")

    # ── Bros bickering engine ────────────────────────────────

    def _start_bickering(self) -> None:
        """Start the bros talking smack while we wait."""
        self._bicker_pool = list(BIG_BRO_LINES + LIL_BRO_LINES)
        random.shuffle(self._bicker_pool)
        self._show("bicker-line")
        # Show first line immediately.
        self._next_bicker()
        # Then rotate every 4 seconds.
        self._bicker_timer = self.set_interval(4.0, self._next_bicker)

    def _stop_bickering(self) -> None:
        """Stop the bros bickering."""
        if self._bicker_timer is not None:
            self._bicker_timer.stop()
            self._bicker_timer = None
        self._hide("bicker-line")

    def _next_bicker(self) -> None:
        """Show the next bicker line."""
        if not self._bicker_pool:
            self._bicker_pool = list(BIG_BRO_LINES + LIL_BRO_LINES)
            random.shuffle(self._bicker_pool)

        line = self._bicker_pool.pop()
        try:
            w = self.query_one("#bicker-line", Static)
            w.remove_class("bicker-big", "bicker-lil")
            if line.startswith("Big Bro:"):
                w.add_class("bicker-big")
            else:
                w.add_class("bicker-lil")
            w.update(line)
        except Exception:
            pass

    # ── Mode selection + cloud/mixed flows ───────────────────

    def _pick_mode(self, mode: str) -> None:
        """User chose local / cloud / mixed. Route to the right probe."""
        if self._mode is not None:
            return  # already chosen; buttons should be gone
        self._mode = mode

        # Hide the picker — we won't come back to it.
        self._hide("mode-section")
        self._show("status-hw")

        # Seed sensible defaults based on mode. Assignment screens can
        # override these before the user hits ENTER.
        if mode == "local":
            self._big_backend = "ollama"
            self._lil_backend = "ollama"
            self._show("status-ollama")
            self.run_worker(self._probe_all(), exclusive=True)
        elif mode == "cloud":
            # No Ollama probe at all in pure cloud mode.
            self._show("status-claude")
            self._show("status-codex")
            self.run_worker(self._probe_cloud(), exclusive=True)
        else:  # mixed
            self._show("status-ollama")
            self._show("status-claude")
            self._show("status-codex")
            self.run_worker(self._probe_mixed(), exclusive=True)

    async def _probe_cloud(self) -> None:
        """Cloud-only probe: hardware + both cloud CLIs. No Ollama."""
        hw_task = asyncio.create_task(detect_hardware())
        cloud_task = asyncio.create_task(detect_cloud_all())

        self._hw = await hw_task
        self._set_status("status-hw", "ok", f"✓ {self._hw.summary()}")

        self._cloud = await cloud_task
        self._render_cloud_status()
        self._show_cloud_install_buttons()
        self._open_assignment(include_ollama=False)

    async def _probe_mixed(self) -> None:
        """Mixed probe: everything in parallel — user picks per pane."""
        hw_task = asyncio.create_task(detect_hardware())
        ollama_task = asyncio.create_task(detect_ollama(self._ollama_url))
        cloud_task = asyncio.create_task(detect_cloud_all())

        self._hw = await hw_task
        self._set_status("status-hw", "ok", f"✓ {self._hw.summary()}")

        self._ollama = await ollama_task
        if self._ollama.running:
            v = self._ollama.version or "unknown"
            self._set_status("status-ollama", "ok",
                             f"✓ Ollama v{v} — running")
        elif self._ollama.installed:
            self._set_status("status-ollama", "pending",
                             "· Ollama installed (not started)")
        else:
            self._set_status("status-ollama", "err",
                             "✗ Ollama not installed (cloud still works)")

        self._cloud = await cloud_task
        self._render_cloud_status()
        self._show_cloud_install_buttons()
        self._open_assignment(include_ollama=True)

    def _render_cloud_status(self) -> None:
        """Update the per-provider status lines from ``self._cloud``."""
        for provider in ("claude", "codex"):
            wid = f"status-{provider}"
            status = self._cloud.get(provider)
            if status is None:
                continue
            if status.ready:
                v = status.version or ""
                self._set_status(wid, "ok",
                                 f"✓ {provider} CLI{(' v' + v) if v else ''}")
            elif status.installed:
                self._set_status(wid, "pending",
                                 f"· {provider} CLI found (version probe failed)")
            else:
                self._set_status(wid, "err",
                                 f"✗ {provider} CLI not installed")

    def _show_cloud_install_buttons(self) -> None:
        """Reveal install buttons for any cloud CLI that's missing."""
        any_missing = False
        for provider in ("claude", "codex"):
            status = self._cloud.get(provider)
            if status is not None and not status.installed:
                self._show(f"btn-install-{provider}")
                any_missing = True
        if any_missing:
            self._show("cloud-install-row")

    async def _install_cloud(self, provider: str) -> None:
        """Guided ``npm install -g`` for a cloud CLI."""
        self._show("pull-status")
        self._set_text("pull-status",
                       f"Installing {provider} CLI via npm...")
        self._start_bickering()

        def _status_cb(msg: str) -> None:
            try:
                self.app.call_from_thread(self._set_text, "pull-status", msg)
            except Exception:
                pass

        ok, msg = await install_cloud_cli(provider, on_status=_status_cb)
        self._stop_bickering()

        if ok:
            # Re-probe to pick up version + path.
            self._cloud = await detect_cloud_all()
            self._render_cloud_status()
            self._hide(f"btn-install-{provider}")
            self._set_text("pull-status",
                           f"✓ {provider} CLI installed. Run "
                           f"`{PROVIDER_BINARIES[provider]} login` before using it.")
            # Re-open assignment so newly installed provider becomes pickable.
            self._open_assignment(include_ollama=(self._mode == "mixed"))
        else:
            self._set_text("pull-status", f"✗ {msg}")
            try:
                btn = self.query_one(f"#btn-install-{provider}", Button)
                btn.disabled = False
                btn.label = f"Retry Install {provider.title()}"
            except Exception:
                pass

    # ── Bro → backend assignment ─────────────────────────────

    def _open_assignment(self, *, include_ollama: bool) -> None:
        """Show the assign-section with only the viable backend buttons."""
        self._show("assign-section")

        # Which backends are usable right now?
        available: list[str] = []
        if include_ollama and self._ollama and (self._ollama.installed or self._ollama.running):
            available.append("ollama")
        for provider in ("claude", "codex"):
            status = self._cloud.get(provider)
            if status is not None and status.installed:
                available.append(provider)

        # Toggle visibility of each assign button based on availability.
        for pane in ("big", "lil"):
            for backend in ("ollama", "claude", "codex"):
                try:
                    btn = self.query_one(f"#btn-{pane}-{backend}", Button)
                    if backend in available:
                        btn.remove_class("hidden")
                    else:
                        btn.add_class("hidden")
                except Exception:
                    pass

        # Seed default selection based on what's available.
        if not available:
            self._set_text("assign-summary",
                           "Nothing is installed yet. Install at least one "
                           "backend above.")
            return

        # Default: first available backend for both panes.
        default = available[0]
        self._big_backend = default
        self._lil_backend = default
        self._refresh_assign_highlight()
        self._refresh_assign_summary()
        self._ready = True
        self._set_hint("[Tap a backend for each bro · ENTER to continue · Q to quit]")

    def _assign_backend(self, pane: str, backend: str) -> None:
        """Handle a bro-assignment button press."""
        if pane == "big":
            self._big_backend = backend
        else:
            self._lil_backend = backend
        self._refresh_assign_highlight()
        self._refresh_assign_summary()

    def _refresh_assign_highlight(self) -> None:
        """Add/remove the ``btn-assign-selected`` class on the chosen buttons."""
        for pane, chosen in (("big", self._big_backend),
                             ("lil", self._lil_backend)):
            for backend in ("ollama", "claude", "codex"):
                try:
                    btn = self.query_one(f"#btn-{pane}-{backend}", Button)
                    if backend == chosen:
                        btn.add_class("btn-assign-selected")
                    else:
                        btn.remove_class("btn-assign-selected")
                except Exception:
                    pass

    def _refresh_assign_summary(self) -> None:
        self._set_text(
            "assign-summary",
            f"Big Bro → {self._big_backend}    Lil Bro → {self._lil_backend}",
        )

    # ── Main probe flow ──────────────────────────────────────

    async def _probe_all(self) -> None:
        # Run hardware + Ollama detection in parallel for speed.
        hw_task = asyncio.create_task(detect_hardware())
        ollama_task = asyncio.create_task(detect_ollama(self._ollama_url))

        # Wait for both — hardware is usually faster.
        self._hw = await hw_task
        self._set_status("status-hw", "ok",
                         f"✓ {self._hw.summary()}")

        self._ollama = await ollama_task
        # Step 2: Ollama.
        await self._check_ollama()

    async def _check_ollama(self) -> None:
        # _ollama is already set from parallel probe in _probe_all.
        if self._ollama is None:
            self._ollama = await detect_ollama(self._ollama_url)

        # Case A: Already running (user or system started it).
        if self._ollama.running:
            v = self._ollama.version or "unknown"
            self._set_status("status-ollama", "ok",
                             f"✓ Ollama v{v} — running")
            await self._handle_models()
            return

        # Case B: Installed but not running → start headless.
        if self._ollama.installed:
            self._set_status("status-ollama", "pending",
                             "· starting Ollama (headless)...")
            self._set_hint("Starting Ollama daemon...")

            started, msg = await start_ollama_serve(hw=self._hw)
            if started:
                self._we_started_ollama = True
                self._ollama = await detect_ollama(self._ollama_url)
                v = self._ollama.version or "unknown"
                self._set_status("status-ollama", "ok",
                                 f"✓ Ollama v{v} — running (headless)")
                await self._handle_models()
            else:
                self._set_status("status-ollama", "err",
                                 f"✗ could not start: {msg}")
                self._set_hint(f"{msg}\n\nTry: ollama serve\n[Q to quit]")
            return

        # Case C: Not installed → show install button.
        self._set_status("status-ollama", "err",
                         "✗ Ollama not installed")
        self._show("action-row")
        import platform as _plat
        _sys = _plat.system()
        if _sys == "Darwin":
            method = "via Homebrew"
        elif _sys == "Windows":
            method = "via winget"
        else:
            method = "via curl"
        self._set_hint(
            "Ollama is required to run local models.\n"
            f"Click 'Install Ollama' to install {method}."
        )

    async def _handle_models(self) -> None:
        self._show("status-models")

        if self._ollama.models:
            names = ", ".join(self._ollama.models[:5])
            if len(self._ollama.models) > 5:
                names += f" (+{len(self._ollama.models) - 5} more)"
            self._set_status("status-models", "ok", f"✓ models: {names}")
            # Seed the active model for both bros — local flow uses the
            # first-available Ollama model by default. The user can
            # change it from settings later.
            first = self._ollama.models[0]
            self._big_model = first
            self._lil_model = first
            self._ready = True
            self._set_hint("[press ENTER to continue · Q to quit]")
        else:
            self._set_status("status-models", "pending",
                             "· no models installed — pick one below (7b recommended)")
            await self._build_model_picker()

    # ── Button handler ───────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        # ── Mode picker ──
        if bid == "btn-mode-local":
            self._pick_mode("local")

        elif bid == "btn-mode-cloud":
            self._pick_mode("cloud")

        elif bid == "btn-mode-mixed":
            self._pick_mode("mixed")

        # ── Ollama install ──
        elif bid == "btn-install":
            event.button.disabled = True
            event.button.label = "Installing..."
            self.run_worker(self._do_install())

        # ── Cloud CLI install ──
        elif bid == "btn-install-claude":
            event.button.disabled = True
            event.button.label = "Installing Claude..."
            self.run_worker(self._install_cloud("claude"))

        elif bid == "btn-install-codex":
            event.button.disabled = True
            event.button.label = "Installing Codex..."
            self.run_worker(self._install_cloud("codex"))

        # ── Bro assignment ──
        elif bid.startswith("btn-big-") or bid.startswith("btn-lil-"):
            parts = bid.split("-")  # btn, big|lil, backend
            pane, backend = parts[1], parts[2]
            self._assign_backend(pane, backend)

        elif bid == "btn-pull-custom":
            if not self._pulling:
                try:
                    inp = self.query_one("#custom-model-input", Input)
                    tag = inp.value.strip()
                except Exception:
                    tag = ""
                if tag:
                    self._pulling = True
                    self.run_worker(self._pull_model(tag))
                else:
                    self._set_hint("Type a model tag first (e.g. mistral-nemo)")

        elif bid in _MODEL_BY_BTN:
            if not self._pulling:
                self._pulling = True
                tag = _MODEL_BY_BTN[bid]
                self.run_worker(self._pull_model(tag))

    # ── Config persistence ───────────────────────────────────

    @staticmethod
    def _persist_backend_choice(big_spec: str, lil_spec: str) -> None:
        """Write the wizard's backend choices back to ~/.lilbro-local/config.yaml.

        Uses a simple read → update dict → write approach so we only
        overwrite ``big_bro`` and ``lil_bro`` keys, leaving everything
        else intact.
        """
        config_path = Path.home() / ".lilbro-local" / "config.yaml"
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            existing: dict = {}
            if config_path.exists():
                import yaml  # type: ignore[import-not-found]
                try:
                    text = config_path.read_text(encoding="utf-8")
                    loaded = yaml.safe_load(text)
                    if isinstance(loaded, dict):
                        existing = loaded
                except Exception:  # noqa: BLE001
                    pass
            existing["big_bro"] = big_spec
            existing["lil_bro"] = lil_spec
            import yaml  # type: ignore[import-not-found]
            config_path.write_text(
                yaml.dump(existing, default_flow_style=False, allow_unicode=True),
                encoding="utf-8",
            )
            logger.info(
                "persisted backend choice: big_bro=%s lil_bro=%s",
                big_spec, lil_spec,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not persist backend choice: %s", exc)

    def action_continue(self) -> None:
        if not self._ready:
            return
        # Push the wizard's resolved backend assignment onto the app so
        # ``open_dual_pane`` can wire up the right connectors. The app
        # falls back to Ollama defaults if these attributes are absent.
        app = self.app
        big_spec = self._big_backend
        if self._big_model:
            big_spec = f"{self._big_backend}/{self._big_model}"
        lil_spec = self._lil_backend
        if self._lil_model:
            lil_spec = f"{self._lil_backend}/{self._lil_model}"
        try:
            app._big_backend = self._big_backend  # type: ignore[attr-defined]
            app._big_model = self._big_model  # type: ignore[attr-defined]
            app._lil_backend = self._lil_backend  # type: ignore[attr-defined]
            app._lil_model = self._lil_model  # type: ignore[attr-defined]
        except Exception:
            pass
        # Persist the user's choices so the next launch skips the wizard
        # and boots straight into their preferred backends.
        self._persist_backend_choice(big_spec, lil_spec)
        self.app.open_dual_pane()  # type: ignore[attr-defined]

    def action_quit_app(self) -> None:
        self.app.exit()

    # ── Install flow ─────────────────────────────────────────

    async def _do_install(self) -> None:
        self._set_status("status-ollama", "pending",
                         "· installing Ollama...")

        # Start bickering while we wait.
        self._start_bickering()

        # Show a progress hint (install has no granular progress).
        self._show("pull-status")
        self._set_text("pull-status", "Installing Ollama... (this may take a few minutes)")
        self._show("pull-bar")
        bar = self.query_one("#pull-bar", ProgressBar)
        bar.update(progress=0)

        # Animate a fake progress bar during install (we don't get real progress).
        fake_timer = self.set_interval(
            2.0, lambda: self._bump_fake_progress(bar, cap=85),
        )

        def _thread_safe_status(msg: str) -> None:
            """Status callback from install thread — use call_from_thread."""
            try:
                self.app.call_from_thread(self._set_hint, msg)
            except Exception:
                pass

        success, msg = await install_ollama(
            on_status=_thread_safe_status,
        )

        # Stop fake progress and bickering.
        fake_timer.stop()
        self._stop_bickering()

        if not success:
            self._set_status("status-ollama", "err",
                             f"✗ install failed: {msg}")
            self._set_hint(f"{msg}\n\n[Q to quit]")
            self._set_text("pull-status", f"✗ {msg}")
            bar.update(progress=0)
            try:
                btn = self.query_one("#btn-install", Button)
                btn.disabled = False
                btn.label = "Retry Install"
            except Exception:
                pass
            return

        # Installed — show 100%.
        bar.update(progress=100)
        self._set_text("pull-status", "✓ Ollama installed!")

        # Hide install button, auto-start headless.
        self._hide("action-row")
        self._set_status("status-ollama", "pending",
                         "· starting Ollama (headless)...")
        self._set_hint("Starting Ollama daemon...")

        started, start_msg = await start_ollama_serve(hw=self._hw)
        if started:
            self._we_started_ollama = True
            self._ollama = await detect_ollama(self._ollama_url)
            v = self._ollama.version or "unknown"
            self._set_status("status-ollama", "ok",
                             f"✓ Ollama v{v} — running (headless)")
            self._hide("pull-status")
            self._hide("pull-bar")
            await self._handle_models()
        else:
            self._set_status("status-ollama", "err",
                             f"✗ installed but won't start: {start_msg}")
            self._set_hint(f"{start_msg}\n\nTry: ollama serve\n[Q to quit]")

    def _bump_fake_progress(self, bar: ProgressBar, cap: int = 85) -> None:
        """Slowly increment progress bar to give visual feedback."""
        try:
            current = getattr(bar, '_percentage', None)
            if current is None:
                # ProgressBar tracks progress internally.
                current = bar.progress
            if current < cap:
                step = random.randint(1, 5)
                bar.update(progress=min(cap, current + step))
        except Exception:
            pass

    # ── Model picker ─────────────────────────────────────────

    async def _build_model_picker(self) -> None:
        installed = set(self._ollama.models or [])
        section = self.query_one("#model-section", Vertical)

        # Grid of compact model cards — 3 columns.
        grid = Grid(id="model-grid")
        await section.mount(grid)

        for model in QUICK_MODELS:
            tag = model["tag"]
            score = score_model_fit(
                min_vram_gb=model["min_vram"],
                min_ram_gb=model["min_ram"],
                runs_on_cpu=model["cpu_ok"],
                hw=self._hw,
            )

            stars = {3: "★★★", 2: "★★", 1: "★"}.get(score, "—")
            is_installed = tag in installed
            is_big = model.get("big_model", False)

            # Compact 2-line info.
            line1 = model["display"]
            if is_installed:
                line1 += " ✅"
            line2 = f"{model['size']} · {stars} · {model['speed']}"

            card = Vertical(classes="model-card-grid")
            await grid.mount(card)
            await card.mount(Static(line1, classes="model-card-name"))
            await card.mount(Static(line2, classes="model-card-info"))

            bid = _btn_id(tag)
            btn_class = "btn-model-big" if is_big else "btn-model-small"

            if is_installed:
                pass
            elif score == 0:
                btn = Button("Not recommended",
                             id=bid, classes=btn_class, disabled=True)
                await card.mount(btn)
            else:
                btn = Button(f"Pull ({model['size']})",
                             id=bid, classes=btn_class)
                await card.mount(btn)

        # ── Custom model input (spans full width below grid) ───
        custom_row = Horizontal(id="custom-model-row")
        await section.mount(custom_row)
        await custom_row.mount(
            Input(placeholder="custom model tag (e.g. mistral-nemo, gemma2:9b)",
                  id="custom-model-input")
        )
        await custom_row.mount(
            Button("Pull", id="btn-pull-custom")
        )

        self._show("model-section")

        if installed:
            self._ready = True
            self._set_hint("[press ENTER to continue · Q to quit]")
        else:
            self._set_hint("Pick a model to download · Q to quit")

    # ── Model pull ───────────────────────────────────────────

    async def _pull_model(self, model_tag: str) -> None:
        self._set_text("pull-status", f"Pulling {model_tag}...")
        self._show("pull-status")
        self._show("pull-bar")

        bar = self.query_one("#pull-bar", ProgressBar)
        bar.update(progress=0)

        # Start bros bickering during download.
        self._start_bickering()

        # Disable all pull buttons.
        for bid in _MODEL_BY_BTN:
            try:
                self.query_one(f"#{bid}", Button).disabled = True
            except Exception:
                pass

        last_status = ""

        def on_progress(status: str, completed: int, total: int) -> None:
            nonlocal last_status
            if status != last_status:
                last_status = status
                try:
                    self._set_text("pull-status",
                                   f"Pulling {model_tag}: {status}")
                except Exception:
                    pass
            if total > 0:
                pct = min(100, int(completed / total * 100))
                try:
                    bar.update(progress=pct)
                except Exception:
                    pass

        success = await pull_model(
            model_tag, self._ollama_url, on_progress=on_progress,
        )

        # Stop bickering.
        self._stop_bickering()

        if success:
            self._set_text("pull-status", f"✓ {model_tag} pulled!")
            bar.update(progress=100)

            # Store selected model on app + seed per-bro defaults for the
            # local flow (user can override on the assignment screen).
            try:
                self.app._selected_model = model_tag  # type: ignore[attr-defined]
            except Exception:
                pass
            self._big_model = model_tag
            self._lil_model = model_tag

            self._set_status("status-models", "ok", f"✓ model: {model_tag}")
            self._ready = True
            self._set_hint("[press ENTER to continue · Q to quit]")
        else:
            self._set_text("pull-status",
                           f"✗ Failed to pull {model_tag}. Check connection.")

        self._pulling = False

        # Re-enable buttons.
        for bid in _MODEL_BY_BTN:
            try:
                self.query_one(f"#{bid}", Button).disabled = False
            except Exception:
                pass

    # ── UI helpers ────────────────────────────────────────────

    def _set_status(self, wid: str, level: str, text: str) -> None:
        """Update a status-line widget: level is 'ok', 'err', or 'pending'."""
        try:
            w = self.query_one(f"#{wid}", Static)
            w.remove_class("status-ok", "status-err", "status-pending")
            w.add_class(f"status-{level}")
            w.update(text)
        except Exception:
            pass

    def _set_text(self, wid: str, text: str) -> None:
        try:
            self.query_one(f"#{wid}", Static).update(text)
        except Exception:
            pass

    def _set_hint(self, text: str) -> None:
        self._set_text("hint", text)

    def _show(self, wid: str) -> None:
        try:
            self.query_one(f"#{wid}").remove_class("hidden")
        except Exception:
            pass

    def _hide(self, wid: str) -> None:
        try:
            self.query_one(f"#{wid}").add_class("hidden")
        except Exception:
            pass
