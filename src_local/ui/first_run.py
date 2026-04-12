"""First-run wizard for LIL BRO LOCAL.

A multi-step flow that walks new users through:
1. Hardware detection (GPU, VRAM, RAM)
2. Ollama detection + install guidance
3. Model selection with quick-pull buttons (3B / 7B / 14B)
4. Model download with progress bar
5. Launch into the main dual-pane screen

This replaces the simple StartupScreen for first-time users.
"""

from __future__ import annotations

import asyncio
import webbrowser
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Label, Static, ProgressBar

from src_local.agents.hardware import HardwareInfo, detect_hardware, score_model_fit
from src_local.agents.ollama_install import (
    OllamaStatus,
    detect_ollama,
    get_download_url,
    get_install_instructions,
    pull_model,
)


# ── Model catalog (quick-pick entries) ─────────────────────────
# These are the models shown as one-click buttons. Full catalog
# lives in catalog.yaml; this is the curated subset for first-run.

QUICK_MODELS = [
    {
        "id": "qwen2.5-coder:3b",
        "display": "Qwen 2.5 Coder 3B",
        "size": "2.3 GB",
        "speed": "Fast",
        "tier": "Mid",
        "min_vram": 4,
        "min_ram": 8,
        "cpu_ok": True,
        "license": "Qwen Research (non-commercial)",
        "commercial": False,
        "notes": "Best quality at small size. Personal/learning use only.",
    },
    {
        "id": "qwen2.5-coder:7b",
        "display": "Qwen 2.5 Coder 7B",
        "size": "4.7 GB",
        "speed": "Medium",
        "tier": "Main",
        "min_vram": 6,
        "min_ram": 16,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "Recommended main driver. Commercial-clean.",
    },
    {
        "id": "qwen2.5-coder:14b",
        "display": "Qwen 2.5 Coder 14B",
        "size": "8.5 GB",
        "speed": "Medium",
        "tier": "Premium",
        "min_vram": 10,
        "min_ram": 24,
        "cpu_ok": False,
        "license": "Apache 2.0",
        "commercial": True,
        "notes": "Best quality for serious work. Needs 10+ GB VRAM.",
    },
]


LOGO = r"""
  _     ___ _       ____  ____   ___
 | |   |_ _| |     | __ )|  _ \ / _ \
 | |    | || |     |  _ \| |_) | | | |
 | |___ | || |___  | |_) |  _ <| |_| |
 |_____|___|_____| |____/|_| \_\\___/
           L O C A L   M O D E
"""


class FirstRunScreen(Screen):
    """Multi-step first-run wizard."""

    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("ctrl+q", "quit_app", "Quit", show=False),
    ]

    def __init__(self, ollama_url: str = "http://127.0.0.1:11434", **kwargs):
        super().__init__(**kwargs)
        self._ollama_url = ollama_url
        self._hw: HardwareInfo | None = None
        self._ollama: OllamaStatus | None = None
        self._pulling = False

    def compose(self) -> ComposeResult:
        with Center():
            with Vertical(id="wizard-box"):
                yield Static(LOGO, id="wizard-logo")
                yield Static("", id="wizard-step")
                yield Static("", id="wizard-hw")
                yield Static("", id="wizard-ollama-status")
                yield Static("", id="wizard-instructions")

                # Ollama install buttons.
                with Horizontal(id="ollama-buttons", classes="button-row hidden"):
                    yield Button(
                        "Download Ollama", id="btn-download-ollama", variant="success"
                    )
                    yield Button(
                        "I already installed it — Retry", id="btn-retry-ollama"
                    )
                    yield Button(
                        "Skip (offline mode)", id="btn-skip-ollama", variant="warning"
                    )

                # Model pick buttons.
                yield Static("", id="wizard-model-header", classes="hidden")
                with Vertical(id="model-buttons", classes="hidden"):
                    pass  # Populated dynamically.

                # Progress bar for model pull.
                yield Static("", id="pull-status", classes="hidden")
                yield ProgressBar(id="pull-progress", total=100, classes="hidden")

                # Final continue.
                yield Button(
                    "Continue", id="btn-continue", variant="success", classes="hidden"
                )

    async def on_mount(self) -> None:
        self._update("wizard-step", "Step 1/3 — Detecting hardware...")
        await self._detect_hardware()

    async def _detect_hardware(self) -> None:
        self._hw = await detect_hardware()
        self._update("wizard-hw", f"Hardware detected:\n{self._hw.summary()}")
        self._update("wizard-step", "Step 2/3 — Checking Ollama...")
        await self._check_ollama()

    async def _check_ollama(self) -> None:
        self._ollama = await detect_ollama(self._ollama_url)

        if self._ollama.needs_install:
            self._update(
                "wizard-ollama-status",
                "Ollama is NOT installed.\n"
                "LIL BRO LOCAL needs Ollama to run local AI models.",
            )
            self._update(
                "wizard-instructions",
                get_install_instructions(),
            )
            self._show("ollama-buttons")
            return

        if self._ollama.needs_start:
            self._update(
                "wizard-ollama-status",
                f"Ollama found at: {self._ollama.path}\n"
                "But the Ollama service is NOT running.",
            )
            self._update(
                "wizard-instructions",
                "Start Ollama by running:\n\n"
                "  ollama serve\n\n"
                "in a separate terminal, then click Retry.",
            )
            self._show("ollama-buttons")
            # Change download button text.
            try:
                self.query_one("#btn-download-ollama", Button).label = "Start Ollama"
            except Exception:
                pass
            return

        # Ollama is running.
        version = self._ollama.version or "unknown"
        model_count = len(self._ollama.models or [])
        self._update(
            "wizard-ollama-status",
            f"Ollama v{version} — running\n"
            f"Models installed: {model_count}",
        )

        if self._ollama.models:
            model_list = ", ".join(self._ollama.models[:5])
            if len(self._ollama.models) > 5:
                model_list += f" (+{len(self._ollama.models) - 5} more)"
            self._update("wizard-instructions", f"Available: {model_list}")

        # Move to model selection.
        await self._show_model_picker()

    async def _show_model_picker(self) -> None:
        self._update("wizard-step", "Step 3/3 — Choose a model")
        self._hide("ollama-buttons")

        installed = set(self._ollama.models or [])

        # Build model buttons dynamically.
        container = self.query_one("#model-buttons", Vertical)

        for model in QUICK_MODELS:
            score = score_model_fit(
                min_vram_gb=model["min_vram"],
                min_ram_gb=model["min_ram"],
                runs_on_cpu=model["cpu_ok"],
                hw=self._hw,
            )

            # Star rating.
            if score >= 3:
                stars = "★★★"
            elif score >= 2:
                stars = "★★"
            elif score >= 1:
                stars = "★"
            else:
                stars = "—"

            # License badge.
            if model["commercial"]:
                license_badge = f"✓ {model['license']}"
            else:
                license_badge = f"⚠ {model['license']}"

            # Already installed?
            is_installed = model["id"] in installed

            label_parts = [
                f"{model['display']}",
                f"  {model['size']} · {model['speed']} · {model['tier']} tier",
                f"  {stars} fit · {license_badge}",
                f"  {model['notes']}",
            ]
            if is_installed:
                label_parts[0] += "  ✅ INSTALLED"

            info = Static("\n".join(label_parts), classes="model-info")
            await container.mount(info)

            if is_installed:
                btn = Button(
                    f"Use {model['display']}",
                    id=f"btn-use-{model['id'].replace(':', '-').replace('.', '-')}",
                    variant="success",
                    classes="model-btn",
                )
                btn.model_tag = model["id"]
                btn.action = "use"
            elif score == 0:
                btn = Button(
                    f"Pull {model['display']} (not recommended)",
                    id=f"btn-pull-{model['id'].replace(':', '-').replace('.', '-')}",
                    variant="warning",
                    classes="model-btn",
                    disabled=True,
                )
                btn.model_tag = model["id"]
                btn.action = "pull"
            else:
                btn = Button(
                    f"Pull {model['display']} ({model['size']})",
                    id=f"btn-pull-{model['id'].replace(':', '-').replace('.', '-')}",
                    variant="primary",
                    classes="model-btn",
                )
                btn.model_tag = model["id"]
                btn.action = "pull"

            await container.mount(btn)

        # Show the container.
        self._show("model-buttons")

        # If any model is already installed, also show Continue.
        if installed:
            self._show("btn-continue")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button

        if btn.id == "btn-download-ollama":
            url = get_download_url()
            try:
                webbrowser.open(url)
            except Exception:
                pass
            self._update(
                "wizard-instructions",
                f"Opening {url} in your browser...\n\n"
                "After installing, click 'Retry' to continue.",
            )

        elif btn.id == "btn-retry-ollama":
            self._update("wizard-ollama-status", "Rechecking Ollama...")
            self._update("wizard-instructions", "")
            self._hide("ollama-buttons")
            self.run_worker(self._check_ollama())

        elif btn.id == "btn-skip-ollama":
            self._update(
                "wizard-instructions",
                "Entering offline mode. You can install Ollama later.",
            )
            self._hide("ollama-buttons")
            self._show("btn-continue")

        elif btn.id == "btn-continue":
            self.app.pop_screen()

        elif hasattr(btn, "model_tag"):
            if getattr(btn, "action", "") == "use":
                # Already installed — set as active and continue.
                self._set_active_model(btn.model_tag)
                self.app.pop_screen()
            elif getattr(btn, "action", "") == "pull":
                if not self._pulling:
                    self._pulling = True
                    self.run_worker(self._pull_model(btn.model_tag))

    async def _pull_model(self, model_tag: str) -> None:
        """Pull a model with progress display."""
        self._update("pull-status", f"Pulling {model_tag}...")
        self._show("pull-status")
        self._show("pull-progress")

        progress = self.query_one("#pull-progress", ProgressBar)
        progress.update(progress=0)

        # Disable all model buttons during pull.
        for btn in self.query(".model-btn"):
            btn.disabled = True

        last_status = ""

        def on_progress(status: str, completed: int, total: int) -> None:
            nonlocal last_status
            if status != last_status:
                last_status = status
                try:
                    self._update("pull-status", f"Pulling {model_tag}: {status}")
                except Exception:
                    pass
            if total > 0:
                pct = min(100, int(completed / total * 100))
                try:
                    progress.update(progress=pct)
                except Exception:
                    pass

        success = await pull_model(
            model_tag, self._ollama_url, on_progress=on_progress
        )

        if success:
            self._update("pull-status", f"✓ {model_tag} installed successfully!")
            progress.update(progress=100)
            self._set_active_model(model_tag)
            self._show("btn-continue")
        else:
            self._update("pull-status", f"✗ Failed to pull {model_tag}. Try manually: ollama pull {model_tag}")

        self._pulling = False

        # Re-enable buttons.
        for btn in self.query(".model-btn"):
            btn.disabled = False

    def _set_active_model(self, model_tag: str) -> None:
        """Store the selected model so the app uses it."""
        try:
            self.app._selected_model = model_tag  # type: ignore[attr-defined]
        except Exception:
            pass

    def _update(self, widget_id: str, text: str) -> None:
        try:
            w = self.query_one(f"#{widget_id}")
            if isinstance(w, (Static, Label)):
                w.update(text)
        except Exception:
            pass

    def _show(self, widget_id: str) -> None:
        try:
            self.query_one(f"#{widget_id}").remove_class("hidden")
        except Exception:
            pass

    def _hide(self, widget_id: str) -> None:
        try:
            self.query_one(f"#{widget_id}").add_class("hidden")
        except Exception:
            pass

    def action_quit_app(self) -> None:
        self.app.exit()
