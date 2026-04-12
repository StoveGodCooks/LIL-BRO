"""Ollama detection and install-on-demand for LIL BRO LOCAL.

Detects whether Ollama is installed, running, and has models.
If not installed, guides the user through downloading and installing it.
If installed but no models, guides through pulling one.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

logger = logging.getLogger("lilbro-local.install")


# Known Ollama install locations on Windows.
_WIN_OLLAMA_PATHS = [
    Path.home() / "AppData" / "Local" / "Programs" / "Ollama" / "ollama.exe",
    Path("C:/Program Files/Ollama/ollama.exe"),
    Path("C:/Program Files (x86)/Ollama/ollama.exe"),
]


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
    # Check PATH first.
    path = shutil.which("ollama")
    if path:
        return path

    # Check known Windows locations.
    if platform.system() == "Windows":
        for p in _WIN_OLLAMA_PATHS:
            if p.exists():
                return str(p)

    return None


async def check_ollama_version(ollama_path: str) -> str | None:
    """Run `ollama --version` and return the version string."""
    try:
        proc = await asyncio.create_subprocess_exec(
            ollama_path, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        if proc.returncode == 0:
            text = stdout.decode("utf-8", errors="replace").strip()
            # Output is like "ollama version is 0.6.2"
            if "version" in text.lower():
                return text.split()[-1]
            return text
    except (asyncio.TimeoutError, OSError, Exception):
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
            # Version check.
            try:
                resp = await client.get(f"{base_url}/api/version")
                if resp.status_code == 200:
                    running = True
                    data = resp.json()
                    version = data.get("version")
            except Exception:
                # Try the root endpoint as fallback (older Ollama versions).
                try:
                    resp = await client.get(f"{base_url}/")
                    if resp.status_code == 200:
                        running = True
                        version = "unknown"
                except Exception:
                    pass

            if running:
                # List models.
                try:
                    resp = await client.get(f"{base_url}/api/tags")
                    if resp.status_code == 200:
                        data = resp.json()
                        for m in data.get("models", []):
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
        version = await check_ollama_version(path)
        if version:
            status.version = version

    # 2. Check the API.
    running, api_version, models = await check_ollama_api(base_url)
    if running:
        status.running = True
        status.installed = True  # If the API responds, it's installed.
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
        return (
            "Install Ollama for Windows:\n\n"
            "  Option 1: Download from https://ollama.com/download/windows\n"
            "            Run the installer, then restart LIL BRO LOCAL.\n\n"
            "  Option 2: Using winget:\n"
            "            winget install Ollama.Ollama\n\n"
            "After installing, Ollama should start automatically.\n"
            "If not, run: ollama serve"
        )
    elif system == "Darwin":
        return (
            "Install Ollama for macOS:\n\n"
            "  Option 1: Download from https://ollama.com/download/mac\n\n"
            "  Option 2: Using Homebrew:\n"
            "            brew install ollama\n\n"
            "After installing, run: ollama serve"
        )
    else:
        return (
            "Install Ollama for Linux:\n\n"
            "  curl -fsSL https://ollama.com/install.sh | sh\n\n"
            "After installing, run: ollama serve"
        )


def get_download_url() -> str:
    """Return the Ollama download URL for this platform."""
    system = platform.system()
    if system == "Windows":
        return "https://ollama.com/download/windows"
    elif system == "Darwin":
        return "https://ollama.com/download/mac"
    else:
        return "https://ollama.com/download/linux"


async def install_ollama(
    on_status: callable | None = None,
) -> tuple[bool, str]:
    """Attempt to install Ollama via the system package manager.

    Tries platform-specific install commands:
      - Windows: winget install Ollama.Ollama
      - macOS:   brew install ollama
      - Linux:   curl -fsSL https://ollama.com/install.sh | sh

    Returns (success, message).
    The on_status callback receives status strings for UI updates.
    """
    system = platform.system()

    def _status(msg: str) -> None:
        if on_status:
            on_status(msg)

    if system == "Windows":
        # Try winget first.
        winget = shutil.which("winget")
        if winget:
            _status("Installing via winget... (this may take a minute)")
            try:
                proc = await asyncio.create_subprocess_exec(
                    winget, "install", "--id", "Ollama.Ollama",
                    "--accept-source-agreements", "--accept-package-agreements",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300.0
                )
                output = stdout.decode("utf-8", errors="replace")
                if proc.returncode == 0:
                    _status("Ollama installed successfully via winget!")
                    return True, "Installed via winget. Ollama should start automatically."
                else:
                    err = stderr.decode("utf-8", errors="replace")
                    # winget returns non-zero if already installed.
                    if "already installed" in output.lower() or "already installed" in err.lower():
                        _status("Ollama is already installed!")
                        return True, "Ollama is already installed."
                    return False, f"winget install failed (exit {proc.returncode}): {err[:200]}"
            except asyncio.TimeoutError:
                return False, "winget install timed out (5 min). Try manually: winget install Ollama.Ollama"
            except Exception as exc:
                return False, f"winget error: {exc}"
        else:
            return False, (
                "winget not found. Install Ollama manually:\n"
                "  Download from https://ollama.com/download/windows"
            )

    elif system == "Darwin":
        brew = shutil.which("brew")
        if brew:
            _status("Installing via Homebrew...")
            try:
                proc = await asyncio.create_subprocess_exec(
                    brew, "install", "ollama",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300.0
                )
                if proc.returncode == 0:
                    _status("Ollama installed via Homebrew!")
                    return True, "Installed via Homebrew. Run: ollama serve"
                else:
                    err = stderr.decode("utf-8", errors="replace")
                    return False, f"brew install failed: {err[:200]}"
            except asyncio.TimeoutError:
                return False, "brew install timed out."
            except Exception as exc:
                return False, f"brew error: {exc}"
        else:
            return False, (
                "Homebrew not found. Install Ollama manually:\n"
                "  Download from https://ollama.com/download/mac"
            )

    else:
        # Linux — use the official install script.
        curl = shutil.which("curl")
        if curl:
            _status("Installing via official script...")
            try:
                proc = await asyncio.create_subprocess_shell(
                    "curl -fsSL https://ollama.com/install.sh | sh",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=300.0
                )
                if proc.returncode == 0:
                    _status("Ollama installed!")
                    return True, "Installed via official script. Run: ollama serve"
                else:
                    err = stderr.decode("utf-8", errors="replace")
                    return False, f"Install script failed: {err[:200]}"
            except asyncio.TimeoutError:
                return False, "Install timed out."
            except Exception as exc:
                return False, f"Install error: {exc}"
        else:
            return False, (
                "curl not found. Install Ollama manually:\n"
                "  https://ollama.com/download/linux"
            )


async def start_ollama_serve() -> tuple[bool, str]:
    """Attempt to start the Ollama daemon in the background.

    Returns (success, message).
    """
    ollama_path = find_ollama()
    if not ollama_path:
        return False, "Ollama binary not found."

    try:
        system = platform.system()
        if system == "Windows":
            # On Windows, start as a detached process.
            proc = await asyncio.create_subprocess_exec(
                ollama_path, "serve",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=0x00000008,  # DETACHED_PROCESS
            )
        else:
            proc = await asyncio.create_subprocess_exec(
                ollama_path, "serve",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )

        # Give it a moment to start, then check the API.
        await asyncio.sleep(3)
        running, _, _ = await check_ollama_api()
        if running:
            return True, "Ollama daemon started."
        else:
            # Give it more time — cold start can be slow.
            await asyncio.sleep(5)
            running, _, _ = await check_ollama_api()
            if running:
                return True, "Ollama daemon started."
            return False, "Ollama process started but API not responding yet. Wait a moment and retry."
    except Exception as exc:
        return False, f"Failed to start ollama serve: {exc}"


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
                    return False

                import json
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
                            return False
                    except Exception:
                        continue

        return True
    except Exception as exc:
        logger.error("Failed to pull model %s: %s", model_tag, exc)
        return False
