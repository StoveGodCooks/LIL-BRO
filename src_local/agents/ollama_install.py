"""Ollama detection, install, and headless management for LIL BRO LOCAL.

Ollama runs as a hidden background process owned by our app:
  - detect_ollama()    → find binary + check API
  - install_ollama()   → winget/brew/curl install (no visible window)
  - start_ollama_serve() → headless daemon, no tray icon, GPU-configured
  - stop_ollama_serve()  → kill the daemon we started
  - pull_model()       → download model via API with progress callback
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src_local.agents.hardware import HardwareInfo

import httpx

logger = logging.getLogger("lilbro-local.install")

# Windows process creation flags.
_CREATE_NO_WINDOW = 0x08000000
_DETACHED_PROCESS = 0x00000008

# Known Ollama install locations on Windows.
_WIN_OLLAMA_PATHS = [
    Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    Path("C:/Program Files/Ollama/ollama.exe"),
    Path("C:/Program Files (x86)/Ollama/ollama.exe"),
]

# Track the Ollama process we started so we can kill it on app exit.
_managed_ollama_proc: subprocess.Popen | None = None


@dataclass
class OllamaStatus:
    """Result of Ollama detection probe."""
    installed: bool = False
    path: str | None = None
    running: bool = False
    version: str | None = None
    models: list[str] | None = None

    @property
    def ready(self) -> bool:
        """Ollama is installed, running, and has at least one model."""
        return self.installed and self.running and bool(self.models)

    @property
    def needs_install(self) -> bool:
        return not self.installed

    @property
    def needs_start(self) -> bool:
        return self.installed and not self.running

    @property
    def needs_model(self) -> bool:
        return self.installed and self.running and not self.models


def find_ollama() -> str | None:
    """Find the ollama binary on this system."""
    path = shutil.which("ollama")
    if path:
        return path

    if platform.system() == "Windows":
        for p in _WIN_OLLAMA_PATHS:
            if p.exists():
                return str(p)

    return None


def check_ollama_version(ollama_path: str) -> str | None:
    """Run `ollama --version` and return the version string (sync)."""
    try:
        flags = _CREATE_NO_WINDOW if platform.system() == "Windows" else 0
        result = subprocess.run(
            [ollama_path, "--version"],
            capture_output=True, text=True, timeout=10,
            creationflags=flags,
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            if "version" in text.lower():
                return text.split()[-1]
            return text
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


async def check_ollama_api(
    base_url: str = "http://127.0.0.1:11434",
) -> tuple[bool, str | None, list[str]]:
    """Check the Ollama HTTP API. Returns (running, version, models)."""
    running = False
    version = None
    models: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            try:
                resp = await client.get(f"{base_url}/api/version")
                if resp.status_code == 200:
                    running = True
                    version = resp.json().get("version")
            except Exception:
                try:
                    resp = await client.get(f"{base_url}/")
                    if resp.status_code == 200:
                        running = True
                        version = "unknown"
                except Exception:
                    pass

            if running:
                try:
                    resp = await client.get(f"{base_url}/api/tags")
                    if resp.status_code == 200:
                        for m in resp.json().get("models", []):
                            name = m.get("name", "")
                            if name:
                                models.append(name)
                except Exception:
                    pass
    except Exception:
        pass

    return running, version, models


async def detect_ollama(
    base_url: str = "http://127.0.0.1:11434",
) -> OllamaStatus:
    """Full Ollama detection: binary + API + models."""
    status = OllamaStatus()

    # 1. Find the binary.
    path = find_ollama()
    if path:
        status.installed = True
        status.path = path
        version = check_ollama_version(path)
        if version:
            status.version = version

    # 2. Check the API.
    running, api_version, models = await check_ollama_api(base_url)
    if running:
        status.running = True
        status.installed = True
        if api_version and not status.version:
            status.version = api_version
        status.models = models
    elif not status.models:
        status.models = []

    return status


def get_install_instructions() -> str:
    """Return platform-specific Ollama install instructions."""
    system = platform.system()
    if system == "Windows":
        return "Click 'Install Ollama Now' to install automatically via winget."
    elif system == "Darwin":
        return "Click 'Install Ollama Now' to install via Homebrew."
    else:
        return "Click 'Install Ollama Now' to install via the official script."


def _gpu_env(hw: "HardwareInfo | None" = None) -> dict[str, str]:
    """Build environment with GPU settings for Ollama.

    If we detected an NVIDIA GPU, set CUDA_VISIBLE_DEVICES=0 and
    OLLAMA_GPU_LAYERS=-1 (offload all layers) so Ollama uses the
    GPU without the user needing to configure anything.
    """
    env = dict(os.environ)
    if hw is not None and hw.has_gpu:
        env.setdefault("CUDA_VISIBLE_DEVICES", "0")
        env["OLLAMA_GPU_LAYERS"] = "-1"
        logger.info("GPU detected (%s, %.1f GB VRAM) — forcing GPU offload",
                     hw.gpu_name, hw.vram_gb)
    return env


def install_ollama_sync(
    on_status: callable | None = None,
) -> tuple[bool, str]:
    """Install Ollama via system package manager (sync, no visible window).

    Returns (success, message).
    """
    system = platform.system()

    def _status(msg: str) -> None:
        if on_status:
            on_status(msg)

    flags = _CREATE_NO_WINDOW if system == "Windows" else 0

    if system == "Windows":
        winget = shutil.which("winget")
        if winget:
            _status("Installing via winget... (this may take a minute)")
            try:
                result = subprocess.run(
                    [winget, "install", "--id", "Ollama.Ollama",
                     "--accept-source-agreements", "--accept-package-agreements"],
                    capture_output=True, text=True, timeout=300,
                    creationflags=flags,
                )
                output = result.stdout + result.stderr
                if result.returncode == 0:
                    _status("Ollama installed!")
                    return True, "Installed via winget."
                elif "already installed" in output.lower():
                    _status("Ollama is already installed!")
                    return True, "Ollama is already installed."
                else:
                    return False, f"winget failed (exit {result.returncode}): {result.stderr[:200]}"
            except subprocess.TimeoutExpired:
                return False, "winget timed out (5 min)."
            except Exception as exc:
                return False, f"winget error: {exc}"
        else:
            return False, "winget not found. Install winget or download Ollama manually."

    elif system == "Darwin":
        brew = shutil.which("brew")
        if brew:
            _status("Installing via Homebrew...")
            try:
                result = subprocess.run(
                    [brew, "install", "ollama"],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    _status("Ollama installed via Homebrew!")
                    return True, "Installed via Homebrew."
                else:
                    return False, f"brew failed: {result.stderr[:200]}"
            except subprocess.TimeoutExpired:
                return False, "brew timed out."
            except Exception as exc:
                return False, f"brew error: {exc}"
        else:
            return False, "Homebrew not found."

    else:
        curl = shutil.which("curl")
        if curl:
            _status("Installing via official script...")
            try:
                result = subprocess.run(
                    ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode == 0:
                    _status("Ollama installed!")
                    return True, "Installed via official script."
                else:
                    return False, f"Install failed: {result.stderr[:200]}"
            except subprocess.TimeoutExpired:
                return False, "Install timed out."
            except Exception as exc:
                return False, f"Install error: {exc}"
        else:
            return False, "curl not found."


async def install_ollama(
    on_status: callable | None = None,
) -> tuple[bool, str]:
    """Async wrapper — runs install_ollama_sync in a thread."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, install_ollama_sync, on_status)


def start_ollama_serve_sync(
    hw: "HardwareInfo | None" = None,
) -> tuple[bool, str]:
    """Start Ollama daemon as a hidden background process (sync).

    No visible window, no tray icon. The process is tracked so we
    can kill it on app exit via stop_ollama_serve().

    Returns (success, message).
    """
    global _managed_ollama_proc

    ollama_path = find_ollama()
    if not ollama_path:
        return False, "Ollama binary not found."

    env = _gpu_env(hw)
    system = platform.system()

    try:
        if system == "Windows":
            # CREATE_NO_WINDOW + DETACHED_PROCESS = fully hidden, no tray.
            # We also set OLLAMA_NOPRUNE=1 to prevent cleanup popups.
            env["OLLAMA_NOPRUNE"] = "1"
            proc = subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=_CREATE_NO_WINDOW | _DETACHED_PROCESS,
            )
        else:
            proc = subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )

        _managed_ollama_proc = proc
        logger.info("Started ollama serve (PID %d)", proc.pid)
        return True, f"Ollama daemon started (PID {proc.pid})."

    except Exception as exc:
        return False, f"Failed to start ollama serve: {exc}"


async def start_ollama_serve(
    hw: "HardwareInfo | None" = None,
) -> tuple[bool, str]:
    """Start Ollama headless and wait for the API to respond.

    Returns (success, message).
    """
    loop = asyncio.get_event_loop()
    ok, msg = await loop.run_in_executor(None, start_ollama_serve_sync, hw)
    if not ok:
        return False, msg

    # Wait for API to come up (poll every second, up to 15s).
    for _ in range(15):
        await asyncio.sleep(1)
        running, _, _ = await check_ollama_api()
        if running:
            return True, "Ollama daemon started (headless)."

    return False, "Ollama process started but API not responding. Try again."


def stop_ollama_serve() -> None:
    """Kill the Ollama daemon we started (if any)."""
    global _managed_ollama_proc
    if _managed_ollama_proc is not None:
        try:
            _managed_ollama_proc.terminate()
            try:
                _managed_ollama_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _managed_ollama_proc.kill()
            logger.info("Stopped managed ollama process (PID %d)", _managed_ollama_proc.pid)
        except Exception as exc:
            logger.warning("Failed to stop ollama: %s", exc)
        _managed_ollama_proc = None


def is_managed_ollama_running() -> bool:
    """Check if we have a managed Ollama process that's still alive."""
    if _managed_ollama_proc is None:
        return False
    return _managed_ollama_proc.poll() is None


async def pull_model(
    model_tag: str,
    base_url: str = "http://127.0.0.1:11434",
    on_progress: callable | None = None,
) -> bool:
    """Pull a model via Ollama's API. Returns True on success.

    The on_progress callback receives (status, completed, total) tuples
    so the UI can show a progress bar.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=600.0, write=10.0, pool=10.0),
        ) as client:
            async with client.stream(
                "POST",
                f"{base_url}/api/pull",
                json={"name": model_tag, "stream": True},
            ) as response:
                if response.status_code != 200:
                    logger.error("Pull API returned %d", response.status_code)
                    return False

                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        completed = data.get("completed", 0)
                        total = data.get("total", 0)
                        if on_progress:
                            on_progress(status, completed, total)
                        if data.get("error"):
                            logger.error("Pull error: %s", data["error"])
                            return False
                    except Exception:
                        continue

        return True
    except Exception as exc:
        logger.error("Failed to pull model %s: %s", model_tag, exc)
        return False
