"""Central connector registry for LIL BRO LOCAL.

The registry maps a **provider name** (``ollama``, ``claude``, ``codex``)
to a small factory that builds the matching ``AgentProcess`` subclass.
Everything downstream — config, first-run wizard, ``/backend`` live
switching, FLEX routing — goes through this module so there is exactly
one place to register new backends.

Design follows the OpenCode pattern (one class per provider, not per
model). A model is just a string argument the provider forwards to its
underlying CLI / daemon, which means adding, say, ``gpt-5-codex`` or
``claude-opus-4-7`` is a config change — no code change required.

Two accepted input shapes, both resolved by :func:`parse_model_string`:

* ``"<provider>/<model>"`` — OpenCode-style shorthand. Example:
  ``"claude/sonnet-4"``, ``"ollama/qwen2.5-coder:7b"``.
* ``("<provider>", "<model>")`` — the already-parsed tuple form used by
  :func:`build_agent` directly.

The plain bare string ``"qwen2.5-coder:7b"`` (no slash) is treated as
an Ollama model for backwards compatibility with the Phase 0 config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from src_local.agents.base import AgentProcess


#: Tuple of every provider name recognised by the registry. Order is the
#: preferred display / fallback order (Ollama first = always available
#: default; cloud providers after).
AVAILABLE_PROVIDERS: tuple[str, ...] = ("ollama", "claude", "codex", "flex")

#: Providers that require a logged-in subscription (no API key path).
#: Used by the first-run wizard and health checks to decide whether to
#: walk the user through ``claude login`` / ``codex login``.
SUBSCRIPTION_PROVIDERS: frozenset[str] = frozenset({"claude", "codex"})


ConnectorFactory = Callable[..., "AgentProcess"]


def _build_ollama(
    *,
    role: str,  # noqa: ARG001 — OllamaAgent is role-agnostic today
    display_name: str,
    model: str | None = None,
    write_access: bool = True,
    sibling_name: str = "the other pane",  # noqa: ARG001
    sibling_backend: str = "another model",  # noqa: ARG001
    **extra: Any,
) -> "AgentProcess":
    from src_local.agents.ollama_agent import OllamaAgent

    kwargs: dict[str, Any] = {
        "display_name": display_name,
        "write_access": write_access,
    }
    if model:
        kwargs["model"] = model
    # Pass through any explicitly-allowed Ollama knobs — others are
    # dropped so accidental typos don't crash the constructor.
    for passthrough in (
        "base_url", "temperature", "context_window", "project_dir",
        "system_prompt", "tools_enabled",
    ):
        if passthrough in extra:
            kwargs[passthrough] = extra[passthrough]
    return OllamaAgent(**kwargs)


def _build_claude(
    *,
    role: str,
    display_name: str,
    model: str | None = None,
    write_access: bool = True,
    sibling_name: str = "the other pane",
    sibling_backend: str = "another model",
    **extra: Any,
) -> "AgentProcess":
    from src_local.agents.claude_agent import ClaudeAgent

    return ClaudeAgent(
        role=role,
        display_name=display_name,
        cwd=extra.get("cwd"),
        model=model,
        write_access=write_access,
        sibling_name=sibling_name,
        sibling_backend=sibling_backend,
    )


def _build_codex(
    *,
    role: str,
    display_name: str,
    model: str | None = None,
    write_access: bool = False,
    sibling_name: str = "the other pane",
    sibling_backend: str = "another model",
    **extra: Any,
) -> "AgentProcess":
    from src_local.agents.codex_agent import CodexAgent

    return CodexAgent(
        role=role,
        display_name=display_name,
        cwd=extra.get("cwd"),
        model=model,
        write_access=write_access,
        sibling_name=sibling_name,
        sibling_backend=sibling_backend,
    )


def _build_flex(
    *,
    role: str,
    display_name: str,
    model: str | None = None,  # noqa: ARG001
    write_access: bool = False,
    sibling_name: str = "the other pane",
    sibling_backend: str = "another model",
    **extra: Any,
) -> "AgentProcess":
    """Build a FlexAgent whose sub-agents are auto-selected from available providers.

    Fallback chain:
    - teaching_backend: codex → claude → ollama (first available)
    - coding_backend:   claude → codex → ollama
    - fallback_backend: always ollama
    """
    from src_local.agents.flex_agent import FlexAgent

    # Build the three sub-agents.  Cloud sub-agents may be unavailable
    # at runtime (e.g. CLI not installed) but that is surfaced at the
    # first turn, not at construction time — matches how the non-flex
    # path works.
    fallback = _build_ollama(
        role=role,
        display_name=display_name,
        write_access=write_access,
        sibling_name=sibling_name,
        sibling_backend=sibling_backend,
        **extra,
    )

    try:
        teaching = _build_codex(
            role=role,
            display_name=display_name,
            write_access=False,
            sibling_name=sibling_name,
            sibling_backend=sibling_backend,
            **extra,
        )
    except Exception:  # noqa: BLE001
        teaching = fallback

    try:
        coding = _build_claude(
            role=role,
            display_name=display_name,
            write_access=write_access,
            sibling_name=sibling_name,
            sibling_backend=sibling_backend,
            **extra,
        )
    except Exception:  # noqa: BLE001
        coding = fallback

    return FlexAgent(
        teaching_backend=teaching,
        coding_backend=coding,
        fallback_backend=fallback,
    )


#: The registry itself. Keys are lowercase provider names as they appear
#: in user-facing config. ``CONNECTORS["claude"]`` is the factory — call
#: it via :func:`build_agent` rather than directly so provider validation
#: and friendly error messages are applied consistently.
CONNECTORS: dict[str, ConnectorFactory] = {
    "ollama": _build_ollama,
    "claude": _build_claude,
    "codex": _build_codex,
    "flex": _build_flex,
}


def list_providers() -> tuple[str, ...]:
    """Return every registered provider name in display order."""
    return AVAILABLE_PROVIDERS


def is_subscription_provider(provider: str) -> bool:
    """Providers that authenticate via subscription CLI (not API keys)."""
    return provider.strip().lower() in SUBSCRIPTION_PROVIDERS


def parse_model_string(spec: str | tuple[str, str | None]) -> tuple[str, str | None]:
    """Normalise a ``provider/model`` string (or tuple) to ``(provider, model)``.

    Accepted shapes::

        "claude/sonnet-4"          → ("claude", "sonnet-4")
        "ollama/qwen2.5-coder:7b"  → ("ollama", "qwen2.5-coder:7b")
        "qwen2.5-coder:7b"         → ("ollama", "qwen2.5-coder:7b")  # legacy
        "claude"                   → ("claude", None)
        ("codex", "gpt-5-codex")   → ("codex", "gpt-5-codex")
        ("codex", None)            → ("codex", None)

    Raises ``ValueError`` for unknown providers or empty strings.
    """
    if isinstance(spec, tuple):
        if len(spec) != 2:
            raise ValueError(
                f"expected (provider, model) tuple, got {spec!r}"
            )
        provider, model = spec
        provider = str(provider).strip().lower()
        if provider not in CONNECTORS:
            raise ValueError(
                f"unknown provider {provider!r} (known: {', '.join(AVAILABLE_PROVIDERS)})"
            )
        return provider, (str(model) if model else None)

    if not isinstance(spec, str) or not spec.strip():
        raise ValueError("model spec must be a non-empty string or tuple")

    raw = spec.strip()
    if "/" in raw:
        provider, _, model = raw.partition("/")
        provider = provider.strip().lower()
        model = model.strip() or None
    else:
        # No slash — either a bare provider name or a legacy Ollama model.
        low = raw.lower()
        if low in CONNECTORS:
            provider, model = low, None
        else:
            # Phase 0 config shipped ``model: qwen2.5-coder:7b`` without a
            # provider prefix — preserve that behaviour by defaulting to
            # Ollama so existing configs keep working.
            provider, model = "ollama", raw

    if provider not in CONNECTORS:
        raise ValueError(
            f"unknown provider {provider!r} (known: {', '.join(AVAILABLE_PROVIDERS)})"
        )
    return provider, model


def build_agent(
    spec: str | tuple[str, str | None],
    *,
    role: str,
    display_name: str,
    write_access: bool = True,
    sibling_name: str = "the other pane",
    sibling_backend: str = "another model",
    **extra: Any,
) -> "AgentProcess":
    """Instantiate the right ``AgentProcess`` for ``spec``.

    ``spec`` may be a ``provider/model`` string, a bare provider name, a
    legacy Ollama model string, or an already-parsed ``(provider, model)``
    tuple. The ``role``, ``display_name``, and sibling metadata are
    forwarded to every connector; provider-specific knobs (``base_url``,
    ``cwd``, etc.) go through ``**extra``.
    """
    provider, model = parse_model_string(spec)
    factory = CONNECTORS[provider]
    return factory(
        role=role,
        display_name=display_name,
        model=model,
        write_access=write_access,
        sibling_name=sibling_name,
        sibling_backend=sibling_backend,
        **extra,
    )
