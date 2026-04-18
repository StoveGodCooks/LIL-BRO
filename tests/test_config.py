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


class TestPerBroBackend:
    """Phase 1 — ``big_bro:`` / ``lil_bro:`` blocks drive backend assignment."""

    def test_defaults_are_ollama(self):
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=None):
            cfg = load_config()
        assert cfg.big_bro.backend == "ollama"
        assert cfg.lil_bro.backend == "ollama"
        # Unset model tracks ``ollama.model`` so Phase 0 configs keep working.
        assert cfg.big_bro.model == "qwen2.5-coder:7b"
        assert cfg.lil_bro.model == "qwen2.5-coder:7b"
        assert cfg.big_bro.context_window == "auto"

    def test_dict_form_with_claude(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro:\n"
            "  backend: claude\n"
            "  model: sonnet-4\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "claude"
        assert cfg.big_bro.model == "sonnet-4"
        # Lil Bro untouched — still Ollama.
        assert cfg.lil_bro.backend == "ollama"

    def test_shorthand_provider_slash_model(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro: claude/sonnet-4\n"
            "lil_bro: codex/gpt-5-codex\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "claude"
        assert cfg.big_bro.model == "sonnet-4"
        assert cfg.lil_bro.backend == "codex"
        assert cfg.lil_bro.model == "gpt-5-codex"

    def test_flex_mode_preserves_fallback(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "lil_bro:\n"
            "  backend: flex\n"
            "  adaptive_fallback: ollama\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.lil_bro.backend == "flex"
        assert cfg.lil_bro.adaptive_fallback == "ollama"

    def test_flex_rejects_flex_as_fallback(self, tmp_path: Path):
        """``adaptive_fallback: flex`` is nonsense — must fall back to ollama."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "lil_bro:\n"
            "  backend: flex\n"
            "  adaptive_fallback: flex\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.lil_bro.adaptive_fallback == "ollama"

    def test_unknown_backend_falls_back_to_ollama(self, tmp_path: Path):
        """Typos in the backend field shouldn't crash the whole config load."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro:\n"
            "  backend: claudee\n"  # typo
            "  model: sonnet-4\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "ollama"

    def test_per_bro_context_window_override(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro:\n"
            "  backend: ollama\n"
            "  model: qwen2.5-coder:7b\n"
            "  context_window: 32768\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.context_window == 32768

    def test_bare_shorthand_resolves_to_default_model(self, tmp_path: Path):
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro: claude\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "claude"
        # No model given — None means the provider picks its own default.
        assert cfg.big_bro.model is None

    def test_unknown_shorthand_provider_keeps_defaults(self, tmp_path: Path):
        """``big_bro: grok/beta`` — unknown provider falls back to ollama."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "big_bro: grok/beta\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "ollama"

    def test_ollama_model_fills_in_when_missing(self, tmp_path: Path):
        """If ``big_bro.backend == ollama`` and no model given, inherit ``ollama.model``."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "ollama:\n"
            "  model: 'llama3.1:8b'\n"
            "big_bro:\n"
            "  backend: ollama\n",
            encoding="utf-8",
        )
        from src_local.config import load_config

        with patch("src_local.config._find_config_file", return_value=cfg_file):
            cfg = load_config()
        assert cfg.big_bro.backend == "ollama"
        assert cfg.big_bro.model == "llama3.1:8b"
