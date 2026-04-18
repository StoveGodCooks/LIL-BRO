"""Cloud-CLI detection and guided install for LIL BRO LOCAL.

Parallels :mod:`src_local.agents.ollama_install`, but targets the
subscription-auth CLIs used by the Phase 1 cloud connectors:

* ``claude``  — Anthropic's Claude Code CLI (``@anthropic-ai/claude-code``)
* ``codex``   — OpenAI's Codex CLI          (``@openai/codex``)

Design goals:

* One uniform API regardless of which cloud provider we're probing, so
  the first-run wizard and the ``/backend`` command can both call the
  same functions without branching on provider strings.
* No silent install. Both CLIs ship as npm global packages — we attempt
  ``npm install -g`` when Node is available and otherwise surface a
  platform-appropriate pointer to the official install docs.
* Auth (``claude login`` / ``codex login``) is **not** probed here.
  The subscription login flow is interactive and out of scope for a
  non-interactive detection pass; auth failures are discovered at
  runtime when the connector actually tries to stream a turn.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger("lilbro-local.cloud_install")

# Windows: suppress the flash-of-console when spawning helpers.
_CREATE_NO_WINDOW = 0x08000000


#: Mapping from provider name → npm package that ships its CLI. Used by
#: :func:`install_cli` when Node is available on the system.
NPM_PACKAGES: dict[str, str] = {
    "claude": "@anthropic-ai/claude-code",
    "codex": "@openai/codex",
}

#: Provider → bare command name we expect to find on PATH after install.
PROVIDER_BINARIES: dict[str, str] = {
    "claude": "claude",
    "codex": "codex",
}

#: Provider → URL where the user can read the official install / login docs
#: if the guided install path fails (e.g. no Node, corporate proxy, etc.).
PROVIDER_DOC_URLS: dict[str, str] = {
    "claude": "https://docs.anthropic.com/en/docs/claude-code/quickstart",
    "codex": "https://github.com/openai/codex",
}


@dataclass
class ProviderStatus:
    """Result of a single cloud-CLI detection probe.

    ``logged_in`` is intentionally ``None`` rather than ``False`` — we
    don't probe auth here, and conflating "unknown" with "not logged in"
    would mislead the first-run wizard.
    """

    provider: str
    installed: bool = False
    path: str | None = None
    version: str | None = None
    logged_in: bool | None = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        """Best-effort readiness check — binary is on PATH and responded."""
        return self.installed and self.version is not None

    @property
    def needs_install(self) -> bool:
        return not self.installed


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _find_binary(provider: str) -> str | None:
    binary = PROVIDER_BINARIES.get(provider)
    if not binary:
        return None
    return shutil.which(binary)


def _probe_version_sync(path: str) -> str | None:
    """Run ``<cli> --version`` and return the trimmed first line."""
    flags = _CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("version probe for %s failed: %s", path, exc)
        return None
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


async def detect_provider(provider: str) -> ProviderStatus:
    """Check whether ``provider``'s CLI is installed and responsive.

    Returns a :class:`ProviderStatus` — the caller decides what to do
    when ``ready`` is False. Unknown providers surface as an error
    rather than raising so the first-run wizard can enumerate them in
    a single pass without wrapping each call in try/except.
    """
    key = provider.strip().lower()
    status = ProviderStatus(provider=key)
    if key not in PROVIDER_BINARIES:
        status.error = f"unknown provider {provider!r}"
        return status

    path = _find_binary(key)
    if path is None:
        return status  # installed=False, path=None

    status.installed = True
    status.path = path

    loop = asyncio.get_running_loop()
    version = await loop.run_in_executor(None, _probe_version_sync, path)
    status.version = version
    return status


async def detect_all(
    providers: "list[str] | tuple[str, ...] | None" = None,
) -> dict[str, ProviderStatus]:
    """Probe every requested provider in parallel.

    With ``providers=None`` (the default), checks all cloud providers
    LIL BRO knows how to talk to. The result dict is keyed by provider
    name so callers can look up a specific one without iterating.
    """
    names = tuple(providers) if providers else tuple(PROVIDER_BINARIES)
    results = await asyncio.gather(
        *(detect_provider(p) for p in names),
        return_exceptions=False,
    )
    return {name: result for name, result in zip(names, results)}


# ---------------------------------------------------------------------------
# Install guidance
# ---------------------------------------------------------------------------

def get_install_instructions(provider: str) -> str:
    """Platform-specific install hint for first-run / `/backend` errors.

    When Node is available, we offer the automatic path; otherwise we
    point the user at the official docs so they don't get stuck on
    missing prerequisites.
    """
    key = provider.strip().lower()
    if key not in NPM_PACKAGES:
        return f"Unknown cloud provider: {provider}"

    pkg = NPM_PACKAGES[key]
    docs = PROVIDER_DOC_URLS[key]
    login_cmd = f"{PROVIDER_BINARIES[key]} login"

    if shutil.which("npm"):
        return (
            f"{key} CLI not found. Run:\n"
            f"  npm install -g {pkg}\n"
            f"Then authenticate with your subscription:\n"
            f"  {login_cmd}\n"
            f"(or press the install button; LIL BRO will run the npm command for you.)"
        )
    if shutil.which("node"):
        return (
            f"{key} CLI not found. Node is installed but `npm` is missing.\n"
            f"Install npm (comes with Node.js) and then run:\n"
            f"  npm install -g {pkg}\n"
            f"Docs: {docs}"
        )
    return (
        f"{key} CLI not found, and Node.js is not installed.\n"
        f"Install Node.js first (https://nodejs.org), then run:\n"
        f"  npm install -g {pkg}\n"
        f"  {login_cmd}\n"
        f"Docs: {docs}"
    )


# ---------------------------------------------------------------------------
# Guided install
# ---------------------------------------------------------------------------

def _install_cli_sync(
    provider: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Attempt ``npm install -g <package>`` for ``provider`` (sync).

    Runs hidden on Windows so the user doesn't see a flashing console
    window during first-run. Returns ``(success, message)`` — callers
    fall back to :func:`get_install_instructions` on failure.
    """
    def _status(msg: str) -> None:
        if on_status:
            on_status(msg)

    key = provider.strip().lower()
    if key not in NPM_PACKAGES:
        return False, f"unknown provider {provider!r}"

    pkg = NPM_PACKAGES[key]
    npm = shutil.which("npm")
    if npm is None:
        return False, (
            "npm not found. Install Node.js (https://nodejs.org) first, "
            f"then run: npm install -g {pkg}"
        )

    _status(f"Installing {pkg} via npm... (this may take a minute)")
    flags = _CREATE_NO_WINDOW if platform.system() == "Windows" else 0
    try:
        result = subprocess.run(
            [npm, "install", "-g", pkg],
            capture_output=True,
            text=True,
            timeout=300,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return False, "npm install timed out (5 min)."
    except OSError as exc:
        return False, f"npm install error: {exc}"

    if result.returncode == 0:
        login_cmd = f"{PROVIDER_BINARIES[key]} login"
        _status(f"{key} installed. Run `{login_cmd}` to authenticate.")
        return True, (
            f"Installed {pkg}. Authenticate with your subscription by running: "
            f"{login_cmd}"
        )

    # Scrub the tail so a multi-page npm error doesn't flood the TUI.
    err_tail = (result.stderr or result.stdout or "").strip().splitlines()
    msg = " / ".join(err_tail[-3:])[:300] if err_tail else "unknown npm error"
    return False, f"npm install failed (exit {result.returncode}): {msg}"


async def install_cli(
    provider: str,
    on_status: Callable[[str], None] | None = None,
) -> tuple[bool, str]:
    """Async wrapper around :func:`_install_cli_sync`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _install_cli_sync, provider, on_status)


# ---------------------------------------------------------------------------
# Login hint (not a real auth probe — just a canned command)
# ---------------------------------------------------------------------------

def get_login_command(provider: str) -> str | None:
    """Return ``<cli> login`` for ``provider``, or ``None`` if unknown.

    Used by the UI to render a clickable hint when a cloud connector
    fails at runtime with what looks like an auth error. We don't try
    to detect auth state proactively — both CLIs handle that
    interactively on first use.
    """
    key = provider.strip().lower()
    binary = PROVIDER_BINARIES.get(key)
    if binary is None:
        return None
    return f"{binary} login"
