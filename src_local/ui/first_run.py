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

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Static, ProgressBar

from src_local.agents.hardware import HardwareInfo, detect_hardware, score_model_fit
from src_local.agents.ollama_install import (
    OllamaStatus,
    detect_ollama,
    install_ollama,
    pull_model,
    start_ollama_serve,
)


# ── Model catalog ─────────────────────────────────────────────

QUICK_MODELS = [
    {
        "tag": "qwen2.5-coder:7b",
        "display": "Qwen 2.5 Coder 7B",
        "size": "4.7 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 6,
        "min_ram": 16,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "Recommended. Commercial-clean.",
    },
    {
        "tag": "qwen2.5-coder:3b",
        "display": "Qwen 2.5 Coder 3B",
        "size": "2.3 GB",
        "speed": "Fast",
        "tier": "Lite",
        "min_vram": 4,
        "min_ram": 8,
        "cpu_ok": True,
        "license": "non-commercial",
        "commercial": False,
        "notes": "Lower quality. Personal/learning use only.",
    },
    {
        "tag": "qwen2.5-coder:14b",
        "display": "Qwen 2.5 Coder 14B",
        "size": "8.5 GB",
        "speed": "Slower",
        "tier": "Premium",
        "min_vram": 10,
        "min_ram": 24,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "Best quality. Needs 10+ GB VRAM.",
    },
]

# Map button ID → model tag.  Built once at import time.
_MODEL_BY_BTN: dict[str, str] = {}

def _btn_id(tag: str) -> str:
    """Convert a model tag to a safe button ID."""
    safe = tag.replace(":", "--").replace(".", "-")
    return f"pull-{safe}"


for _m in QUICK_MODELS:
    _MODEL_BY_BTN[_btn_id(_m["tag"])] = _m["tag"]


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

    # ── Layout (renders instantly) ───────────────────────────

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="startup-box"):
                yield Static(LOGO_THE, id="logo-the")
                yield Static(LOGO_BROS, id="logo-bros")
                yield Static("local-model coding TUI", id="subtitle")

                yield Static("· detecting hardware...", id="status-hw",
                             classes="status-line status-pending")
                yield Static("· checking Ollama...", id="status-ollama",
                             classes="status-line status-pending")
                yield Static("", id="status-models",
                             classes="status-line hidden")

                # Install button (hidden unless needed).
                with Horizontal(id="action-row", classes="hidden"):
                    yield Button("Install Ollama", id="btn-install",
                                 variant="success")

                # Model cards (hidden until needed).
                with Vertical(id="model-section", classes="hidden"):
                    pass

                # Pull progress (hidden until needed).
                yield Static("", id="pull-status", classes="hidden")
                yield ProgressBar(id="pull-bar", total=100, classes="hidden")

                yield Static("", id="hint")

    def on_mount(self) -> None:
        self.run_worker(self._probe_all(), exclusive=True)

    # ── Main probe flow ──────────────────────────────────────

    async def _probe_all(self) -> None:
        # Step 1: Hardware.
        self._hw = await detect_hardware()
        self._set_status("status-hw", "ok",
                         f"✓ {self._hw.summary()}")

        # Step 2: Ollama.
        await self._check_ollama()

        # User always sees the landing page and presses Enter to launch.

    async def _check_ollama(self) -> None:
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
        self._set_hint(
            "Ollama is required to run local models.\n"
            "Click 'Install Ollama' to install via winget."
        )

    # Default model to auto-pull on fresh install.
    _DEFAULT_MODEL = "qwen2.5-coder:7b"

    async def _handle_models(self) -> None:
        self._show("status-models")

        if self._ollama.models:
            names = ", ".join(self._ollama.models[:5])
            if len(self._ollama.models) > 5:
                names += f" (+{len(self._ollama.models) - 5} more)"
            self._set_status("status-models", "ok", f"✓ models: {names}")

            # If 7b is installed, auto-select it.
            if self._DEFAULT_MODEL in self._ollama.models:
                try:
                    self.app._selected_model = self._DEFAULT_MODEL  # type: ignore[attr-defined]
                except Exception:
                    pass

            self._ready = True
            self._set_hint("[press ENTER to continue · Q to quit]")
        else:
            # No models at all — auto-pull the default 7b.
            self._set_status("status-models", "pending",
                             f"· no models found — pulling {self._DEFAULT_MODEL} (recommended)...")
            await self._pull_model(self._DEFAULT_MODEL)

    # ── Button handler ───────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid == "btn-install":
            event.button.disabled = True
            event.button.label = "Installing..."
            self.run_worker(self._do_install())

        elif bid in _MODEL_BY_BTN:
            if not self._pulling:
                self._pulling = True
                tag = _MODEL_BY_BTN[bid]
                self.run_worker(self._pull_model(tag))

    def action_continue(self) -> None:
        if self._ready:
            self.app.open_dual_pane()  # type: ignore[attr-defined]

    def action_quit_app(self) -> None:
        self.app.exit()

    # ── Install flow ─────────────────────────────────────────

    async def _do_install(self) -> None:
        self._set_status("status-ollama", "pending",
                         "· installing Ollama...")

        success, msg = await install_ollama(
            on_status=lambda m: self._set_hint(m),
        )

        if not success:
            self._set_status("status-ollama", "err",
                             f"✗ install failed: {msg}")
            self._set_hint(f"{msg}\n\n[Q to quit]")
            try:
                btn = self.query_one("#btn-install", Button)
                btn.disabled = False
                btn.label = "Retry Install"
            except Exception:
                pass
            return

        # Installed — hide button, auto-start headless.
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
            await self._handle_models()
        else:
            self._set_status("status-ollama", "err",
                             f"✗ installed but won't start: {start_msg}")
            self._set_hint(f"{start_msg}\n\nTry: ollama serve\n[Q to quit]")

    # ── Model picker ─────────────────────────────────────────

    async def _build_model_picker(self) -> None:
        installed = set(self._ollama.models or [])
        section = self.query_one("#model-section", Vertical)

        for model in QUICK_MODELS:
            tag = model["tag"]
            score = score_model_fit(
                min_vram_gb=model["min_vram"],
                min_ram_gb=model["min_ram"],
                runs_on_cpu=model["cpu_ok"],
                hw=self._hw,
            )

            stars = {3: "★★★", 2: "★★", 1: "★"}.get(score, "—")
            lic = f"✓ {model['license']}" if model["commercial"] else f"⚠ {model['license']}"
            is_installed = tag in installed

            # Info text.
            info_text = (
                f"{model['display']}"
                + ("  ✅ INSTALLED" if is_installed else "")
                + f"\n  {model['size']} · {model['speed']} · {model['tier']} tier"
                + f"\n  {stars} fit · {lic}"
                + f"\n  {model['notes']}"
            )

            card = Vertical(classes="model-card")
            await section.mount(card)
            await card.mount(Static(info_text))

            bid = _btn_id(tag)

            if is_installed:
                # Already pulled — no button needed, can just continue.
                pass
            elif score == 0:
                btn = Button(f"Pull {model['display']} (not recommended)",
                             id=bid, variant="warning", disabled=True)
                await card.mount(btn)
            else:
                btn = Button(f"Pull {model['display']} ({model['size']})",
                             id=bid, variant="primary")
                await card.mount(btn)

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

        if success:
            self._set_text("pull-status", f"✓ {model_tag} pulled!")
            bar.update(progress=100)

            # Store selected model on app.
            try:
                self.app._selected_model = model_tag  # type: ignore[attr-defined]
            except Exception:
                pass

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
