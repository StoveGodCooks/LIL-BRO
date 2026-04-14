"""Tests for config loading — defaults, overrides, backwards compat."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch



class TestConfigDefaults:
    """Built-in defaults load when no config file exists."""

    def test_defaults_load(self):
        from src_local.config import load_config

        # Patch _find_config_file to return a non-existent path.
        with patch("src_local.config._find_config_file", return_value=None):
            cfg = load_config()
        assert cfg.ollama.model == "qwen2.5-coder:7b"
        assert cfg.ollama.base_url == "http://127.0.0.1:11434"
        assert cfg.ollama.temperature == 0.1
        assert cfg.colors.primary == "#A8D840"

    def test_default_context_windows_are_auto(self):
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=None):
            cfg = load_config()
        assert cfg.ollama.context_window_big == "auto"
        assert cfg.ollama.context_window_lil == "auto"


class TestConfigBackwardsCompat:
    """Old `context_window` key still works as fallback for both agents."""

    def test_old_key_applies_to_both(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "ollama:\n"
            "  context_window: 16384\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        # Old key should apply to both when new keys aren't set.
        assert cfg.ollama.context_window_big == 16384
        assert cfg.ollama.context_window_lil == 16384

    def test_new_keys_override_old(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "ollama:\n"
            "  context_window: 16384\n"
            "  context_window_big: 32768\n"
            "  context_window_lil: 8192\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.ollama.context_window_big == 32768
        assert cfg.ollama.context_window_lil == 8192


class TestConfigOverrides:
    """User config overrides defaults."""

    def test_model_override(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "ollama:\n"
            "  model: 'llama3.1:8b'\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.ollama.model == "llama3.1:8b"

    def test_color_override(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "ui:\n"
            "  colors:\n"
            "    primary: '#FF0000'\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.colors.primary == "#FF0000"
        # Others remain default.
        assert cfg.colors.secondary == "#6EC8E8"
