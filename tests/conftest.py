"""Shared fixtures for LIL BRO LOCAL test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a minimal project directory for tool tests."""
    (tmp_path / "main.py").write_text("print('hello')\n", encoding="utf-8")
    (tmp_path / "utils.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested file\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    """Write a minimal config.yaml and return its path."""
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "ollama:\n"
        "  base_url: 'http://127.0.0.1:11434'\n"
        "  model: 'qwen2.5-coder:7b'\n"
        "  context_window_big: auto\n"
        "  context_window_lil: auto\n"
        "  temperature: 0.1\n"
        "ui:\n"
        "  colors:\n"
        "    primary: '#A8D840'\n"
        "    secondary: '#6EC8E8'\n"
        "    user: '#E8E8E8'\n"
        "    primary_dim: '#2A3518'\n"
        "    secondary_dim: '#1A2E38'\n"
        "    bg: '#1A1A1A'\n"
        "    border: '#333333'\n"
        "journal:\n"
        "  auto_save: true\n"
        "  directory: '~/.lilbro-local/journals/'\n"
        "  keep: 100\n",
        encoding="utf-8",
    )
    return cfg
