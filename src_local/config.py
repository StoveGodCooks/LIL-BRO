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
    # Per-bro backend assignment (Phase 1). When unset, both bros fall
    # back to the ``ollama`` block above so existing configs keep
    # working. The ``backend`` field is one of the providers registered
    # in ``src_local.agents.connectors`` (``ollama`` / ``claude`` /
    # ``codex``), plus ``flex`` (lil bro only) for adaptive routing.
    "big_bro": {
        "backend": "ollama",
        "model": None,  # None → inherit from the matching ollama/claude/codex block
        "context_window": "auto",
    },
    "lil_bro": {
        "backend": "ollama",
        "model": None,
        "context_window": "auto",
        "adaptive_fallback": "ollama",  # only consulted when backend == "flex"
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


#: Every backend value accepted in a ``big_bro.backend`` /
#: ``lil_bro.backend`` field. Kept in sync with the CONNECTORS registry
#: plus the special ``flex`` adaptive-routing marker for Lil Bro.
VALID_BACKENDS: tuple[str, ...] = ("ollama", "claude", "codex", "flex")


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
class BroConfig:
    """Per-pane backend assignment.

    ``backend`` names a provider in the connector registry (or ``flex``
    for Lil Bro adaptive routing). ``model`` is forwarded to that
    provider's CLI / daemon; ``None`` means "use whatever the OllamaConfig
    / provider default is". ``context_window`` only matters for the
    ``ollama`` backend today; cloud connectors ignore it.
    """

    backend: str = "ollama"
    model: str | None = None
    context_window: int | str = "auto"
    #: Only consulted when ``backend == "flex"``. Names the provider to
    #: fall back on when no cloud backend is reachable for a given turn.
    adaptive_fallback: str = "ollama"


@dataclass(frozen=True)
class Config:
    colors: Colors
    ollama: OllamaConfig
    big_bro: BroConfig
    lil_bro: BroConfig
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


def _parse_bro_config(
    raw: Any,
    *,
    pane: str,
    ollama_default_model: str,
    ollama_default_ctx: int | str,
) -> BroConfig:
    """Resolve a ``big_bro`` / ``lil_bro`` section into a :class:`BroConfig`.

    Accepts two shapes so configs can be terse or explicit:

    * **Dict** — the canonical long form::

        big_bro:
          backend: claude
          model: sonnet-4
          context_window: auto

    * **String** — OpenCode-style ``provider/model`` shorthand::

        big_bro: claude/sonnet-4
        lil_bro: ollama/qwen2.5-coder:7b

    Missing keys inherit from the ``ollama:`` block so Phase 0 configs
    that only set ``ollama.model`` keep working unchanged.
    """
    # Import here to avoid pulling agents.* into import-time dependencies of
    # callers that only want config values.
    from src_local.agents.connectors import parse_model_string

    backend = "ollama"
    model: str | None = None
    ctx: int | str = ollama_default_ctx
    fallback = "ollama"

    if isinstance(raw, str) and raw.strip():
        try:
            provider, parsed_model = parse_model_string(raw)
            backend = provider
            model = parsed_model
        except ValueError:
            # Unknown provider in the shorthand → keep defaults rather than
            # crashing the whole config load.
            pass
    elif isinstance(raw, dict):
        backend_raw = str(raw.get("backend", "ollama")).strip().lower()
        if backend_raw in VALID_BACKENDS:
            backend = backend_raw
        model_raw = raw.get("model")
        model = str(model_raw) if model_raw else None
        if "context_window" in raw:
            ctx = _parse_ctx(raw.get("context_window"))
        if pane == "lil":
            fb = str(raw.get("adaptive_fallback", "ollama")).strip().lower()
            if fb in VALID_BACKENDS and fb != "flex":
                fallback = fb

    # For the ollama backend, an unset model should track whatever the
    # shared ``ollama.model`` setting is so the two stay consistent.
    if backend == "ollama" and model is None:
        model = ollama_default_model

    return BroConfig(
        backend=backend,
        model=model,
        context_window=ctx,
        adaptive_fallback=fallback,
    )


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

    # Per-bro backend assignment. When the pane-specific block is missing,
    # default to Ollama with the shared model so Phase 0 configs keep
    # working without any edits.
    big_bro_cfg = _parse_bro_config(
        data.get("big_bro"),
        pane="big",
        ollama_default_model=ollama.model,
        ollama_default_ctx=ollama.context_window_big,
    )
    lil_bro_cfg = _parse_bro_config(
        data.get("lil_bro"),
        pane="lil",
        ollama_default_model=ollama.model,
        ollama_default_ctx=ollama.context_window_lil,
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
        big_bro=big_bro_cfg,
        lil_bro=lil_bro_cfg,
        journal_dir=journal_dir,
        journal_auto_save=auto_save,
        journal_keep=journal_keep,
        lilbro_home=lilbro_home,
    )
