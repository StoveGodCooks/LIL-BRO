"""Tests for cloud-CLI detection and guided install.

No actual ``npm`` / ``claude`` / ``codex`` processes are spawned.
``shutil.which`` and the subprocess probe are both monkeypatched so
these tests run the same on a machine with or without the CLIs
installed.
"""

from __future__ import annotations

import pytest

from src_local.agents import cloud_install
from src_local.agents.cloud_install import (
    NPM_PACKAGES,
    PROVIDER_BINARIES,
    PROVIDER_DOC_URLS,
    ProviderStatus,
    detect_all,
    detect_provider,
    get_install_instructions,
    get_login_command,
    install_cli,
)


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_provider_tables_cover_both_phase_one_clouds() -> None:
    """Claude + Codex must appear in every lookup table."""
    expected = {"claude", "codex"}
    assert expected == set(NPM_PACKAGES)
    assert expected == set(PROVIDER_BINARIES)
    assert expected == set(PROVIDER_DOC_URLS)


def test_npm_package_names_match_official_scopes() -> None:
    assert NPM_PACKAGES["claude"] == "@anthropic-ai/claude-code"
    assert NPM_PACKAGES["codex"] == "@openai/codex"


def test_provider_binaries_are_bare_commands() -> None:
    """PATH lookup relies on bare names, not absolute paths."""
    assert PROVIDER_BINARIES["claude"] == "claude"
    assert PROVIDER_BINARIES["codex"] == "codex"


def test_provider_status_defaults() -> None:
    status = ProviderStatus(provider="claude")
    assert status.installed is False
    assert status.ready is False
    assert status.needs_install is True
    assert status.logged_in is None  # NOT False — we don't probe auth here


def test_provider_status_ready_requires_version() -> None:
    """``installed=True`` alone isn't ready — the version probe must also succeed."""
    status = ProviderStatus(provider="claude", installed=True, path="/x/claude")
    assert status.ready is False
    status.version = "2.1.91"
    assert status.ready is True


# ---------------------------------------------------------------------------
# detect_provider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_provider_missing(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: None)
    status = await detect_provider("claude")
    assert status.installed is False
    assert status.path is None
    assert status.version is None
    assert status.ready is False


@pytest.mark.asyncio
async def test_detect_provider_installed_with_version(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(
        cloud_install, "_probe_version_sync", lambda _path: "2.1.91"
    )
    status = await detect_provider("claude")
    assert status.installed is True
    assert status.path == "/fake/claude"
    assert status.version == "2.1.91"
    assert status.ready is True


@pytest.mark.asyncio
async def test_detect_provider_installed_but_probe_fails(monkeypatch) -> None:
    """Binary on PATH but ``--version`` fails — report installed, not ready."""
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: "/fake/codex")
    monkeypatch.setattr(cloud_install, "_probe_version_sync", lambda _p: None)
    status = await detect_provider("codex")
    assert status.installed is True
    assert status.version is None
    assert status.ready is False


@pytest.mark.asyncio
async def test_detect_provider_unknown_sets_error() -> None:
    status = await detect_provider("grok")
    assert status.error is not None
    assert "unknown provider" in status.error
    assert status.installed is False


@pytest.mark.asyncio
async def test_detect_provider_case_insensitive(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: "/fake/claude")
    monkeypatch.setattr(cloud_install, "_probe_version_sync", lambda _p: "x")
    status = await detect_provider("CLAUDE")
    assert status.provider == "claude"
    assert status.installed is True


@pytest.mark.asyncio
async def test_detect_all_returns_keyed_dict(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: None)
    results = await detect_all()
    assert set(results) == {"claude", "codex"}
    assert all(isinstance(v, ProviderStatus) for v in results.values())


@pytest.mark.asyncio
async def test_detect_all_respects_provider_filter(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: None)
    results = await detect_all(["claude"])
    assert set(results) == {"claude"}


# ---------------------------------------------------------------------------
# Install instructions
# ---------------------------------------------------------------------------


def test_install_instructions_mention_package(monkeypatch) -> None:
    monkeypatch.setattr(
        cloud_install.shutil, "which", lambda n: "/fake/npm" if n == "npm" else None
    )
    text = get_install_instructions("claude")
    assert "@anthropic-ai/claude-code" in text
    assert "claude login" in text


def test_install_instructions_unknown_provider() -> None:
    assert "Unknown" in get_install_instructions("grok")


def test_install_instructions_no_node(monkeypatch) -> None:
    """With neither npm nor node present, point at the official install pages."""
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: None)
    text = get_install_instructions("codex")
    assert "Node.js" in text
    assert "@openai/codex" in text
    assert PROVIDER_DOC_URLS["codex"] in text


def test_install_instructions_node_but_no_npm(monkeypatch) -> None:
    """Node without npm is a misconfiguration — tell the user to install npm."""
    monkeypatch.setattr(
        cloud_install.shutil,
        "which",
        lambda n: "/fake/node" if n == "node" else None,
    )
    text = get_install_instructions("codex")
    assert "npm" in text.lower()
    assert "@openai/codex" in text


# ---------------------------------------------------------------------------
# install_cli
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_install_cli_without_npm_reports_failure(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: None)
    ok, msg = await install_cli("claude")
    assert ok is False
    assert "npm" in msg.lower()


@pytest.mark.asyncio
async def test_install_cli_unknown_provider() -> None:
    ok, msg = await install_cli("grok")
    assert ok is False
    assert "unknown provider" in msg


@pytest.mark.asyncio
async def test_install_cli_success(monkeypatch) -> None:
    """Exercise the full happy path without actually shelling out."""
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: "/fake/npm")

    class _Result:
        returncode = 0
        stdout = "+ @anthropic-ai/claude-code@2.1.91"
        stderr = ""

    def _fake_run(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(cloud_install.subprocess, "run", _fake_run)

    messages: list[str] = []
    ok, msg = await install_cli("claude", on_status=messages.append)
    assert ok is True
    assert "claude login" in msg
    # on_status callback must have been invoked at least twice (start + end).
    assert any("Installing" in m for m in messages)
    assert any("authenticate" in m for m in messages)


@pytest.mark.asyncio
async def test_install_cli_handles_npm_failure(monkeypatch) -> None:
    monkeypatch.setattr(cloud_install.shutil, "which", lambda _n: "/fake/npm")

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "EACCES: permission denied\nsome other hint line"

    def _fake_run(*_args, **_kwargs):
        return _Result()

    monkeypatch.setattr(cloud_install.subprocess, "run", _fake_run)

    ok, msg = await install_cli("codex")
    assert ok is False
    assert "exit 1" in msg
    assert "EACCES" in msg or "permission" in msg.lower()


# ---------------------------------------------------------------------------
# Login hint
# ---------------------------------------------------------------------------


def test_get_login_command() -> None:
    assert get_login_command("claude") == "claude login"
    assert get_login_command("codex") == "codex login"
    assert get_login_command("CLAUDE") == "claude login"  # case-insensitive
    assert get_login_command("grok") is None
