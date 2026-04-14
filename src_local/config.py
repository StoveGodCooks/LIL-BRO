"""Config loader for LIL BRO LOCAL.

Resolves config from (in priority order):
1. ~/.lilbro-local/config.yaml
2. ./config.yaml in the project root
3. Built-in defaults

Also ensures ~/.lilbro-local/ and ~/.lilbro-local/journals/ exist on first run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULTS: dict[str, Any] = {
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen2.5-coder:7b",
        "context_window_big": "auto",
        "context_window_lil": "auto",
        "temperature": 0.1,
    },
    "ui": {
        "colors": {
            "primary": "#A8D840",
            "secondary": "#6EC8E8",
            "user": "#E8E8E8",
            "primary_dim": "#2A3518",
            "secondary_dim": "#1A2E38",
            "bg": "#1A1A1A",
            "border": "#333333",
        },
    },
    "journal": {
        "auto_save": True,
        "directory": "~/.lilbro-local/journals/",
        "keep": 100,
    },
}


@dataclass(frozen=True)
class Colors:
    primary: str
    secondary: str
    user: str
    primary_dim: str
    secondary_dim: str
    bg: str
    border: str


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5-coder:7b"
    context_window_big: int | str = "auto"   # "auto" = detect from VRAM
    context_window_lil: int | str = "auto"   # or explicit int (e.g. 16384)
    temperature: float = 0.1


@dataclass(frozen=True)
class Config:
    colors: Colors
    ollama: OllamaConfig
    journal_dir: Path
    journal_auto_save: bool
    journal_keep: int = 100
    lilbro_home: Path = field(default_factory=lambda: Path.home() / ".lilbro-local")


def _parse_ctx(value: Any) -> int | str:
    """Parse a context_window value: 'auto' stays as str, anything else → int."""
    if isinstance(value, str) and value.strip().lower() == "auto":
        return "auto"
    try:
        return int(value)
    except (TypeError, ValueError):
        return "auto"


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _find_config_file() -> Path | None:
    home_cfg = Path.home() / ".lilbro-local" / "config.yaml"
    if home_cfg.is_file():
        return home_cfg
    project_cfg = Path(__file__).resolve().parent.parent / "config.yaml"
    if project_cfg.is_file():
        return project_cfg
    return None


def load_config() -> Config:
    data = dict(DEFAULTS)
    cfg_path = _find_config_file()
    if cfg_path is not None:
        try:
            loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            data = _deep_merge(data, loaded)
        except (yaml.YAMLError, OSError):
            pass

    colors_data = data.get("ui", {}).get("colors", {})
    dcolors = DEFAULTS["ui"]["colors"]
    colors = Colors(
        primary=colors_data.get("primary", dcolors["primary"]),
        secondary=colors_data.get("secondary", dcolors["secondary"]),
        user=colors_data.get("user", dcolors["user"]),
        primary_dim=colors_data.get("primary_dim", dcolors["primary_dim"]),
        secondary_dim=colors_data.get("secondary_dim", dcolors["secondary_dim"]),
        bg=colors_data.get("bg", dcolors["bg"]),
        border=colors_data.get("border", dcolors["border"]),
    )

    # Read the raw user-provided ollama section (before merge with defaults)
    # so we can tell which keys the user actually set vs inherited.
    _raw_ollama = {}
    if cfg_path is not None:
        try:
            _raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            _raw_ollama = _raw.get("ollama", {})
        except (yaml.YAMLError, OSError):
            pass

    ollama_data = data.get("ollama", {})
    doll = DEFAULTS["ollama"]
    # Backwards compat: if old "context_window" key is set but the new
    # per-agent keys aren't, use the old value as fallback for both.
    _ctx_fallback = _raw_ollama.get("context_window")
    _user_set_big = "context_window_big" in _raw_ollama
    _user_set_lil = "context_window_lil" in _raw_ollama
    if _ctx_fallback and not _user_set_big:
        _ctx_big = _ctx_fallback
    else:
        _ctx_big = ollama_data.get("context_window_big", doll["context_window_big"])
    if _ctx_fallback and not _user_set_lil:
        _ctx_lil = _ctx_fallback
    else:
        _ctx_lil = ollama_data.get("context_window_lil", doll["context_window_lil"])
    ollama = OllamaConfig(
        base_url=str(ollama_data.get("base_url", doll["base_url"])),
        model=str(ollama_data.get("model", doll["model"])),
        context_window_big=_parse_ctx(_ctx_big),
        context_window_lil=_parse_ctx(_ctx_lil),
        temperature=float(ollama_data.get("temperature", doll["temperature"])),
    )

    journal_cfg = data.get("journal", {})
    journal_dir = Path(journal_cfg.get("directory", "~/.lilbro-local/journals/")).expanduser()
    auto_save = bool(journal_cfg.get("auto_save", True))
    try:
        journal_keep = int(journal_cfg.get("keep", DEFAULTS["journal"]["keep"]))
    except (TypeError, ValueError):
        journal_keep = DEFAULTS["journal"]["keep"]
    if journal_keep < 0:
        journal_keep = 0

    lilbro_home = Path.home() / ".lilbro-local"
    lilbro_home.mkdir(parents=True, exist_ok=True)
    journal_dir.mkdir(parents=True, exist_ok=True)

    return Config(
        colors=colors,
        ollama=ollama,
        journal_dir=journal_dir,
        journal_auto_save=auto_save,
        journal_keep=journal_keep,
        lilbro_home=lilbro_home,
    )
