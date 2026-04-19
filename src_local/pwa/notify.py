"""ntfy.sh push notifications.

Minimal wrapper: POST the message body to
``https://ntfy.sh/<topic>``.  Topic is read from
``~/.lilbro-local/config.yaml`` under ``notify.topic``, with env-var
``LILBRO_NTFY_TOPIC`` as an override.

No account required.  The user is responsible for picking a topic
that's not easily guessed (ntfy topics are public).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("lilbro-local.pwa.notify")


_DEFAULT_SERVER = "https://ntfy.sh"


def _load_topic() -> str | None:
    # Env var wins.
    env = os.environ.get("LILBRO_NTFY_TOPIC")
    if env:
        return env.strip()
    cfg = Path.home() / ".lilbro-local" / "config.yaml"
    if not cfg.exists():
        return None
    try:
        import yaml  # type: ignore[import-not-found]
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify: failed to parse config.yaml: %s", exc)
        return None
    section = data.get("notify") if isinstance(data, dict) else None
    if isinstance(section, dict):
        topic = section.get("topic")
        if isinstance(topic, str) and topic.strip():
            return topic.strip()
    return None


def _load_server() -> str:
    env = os.environ.get("LILBRO_NTFY_SERVER")
    if env:
        return env.rstrip("/")
    cfg = Path.home() / ".lilbro-local" / "config.yaml"
    if cfg.exists():
        try:
            import yaml  # type: ignore[import-not-found]
            data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
            section = data.get("notify") if isinstance(data, dict) else None
            if isinstance(section, dict):
                srv = section.get("server")
                if isinstance(srv, str) and srv.strip():
                    return srv.rstrip("/")
        except Exception:  # noqa: BLE001
            pass
    return _DEFAULT_SERVER


def send_notification(
    message: str,
    *,
    title: str | None = None,
    topic: str | None = None,
) -> tuple[bool, str]:
    """POST *message* to ntfy.  Returns ``(ok, detail)``.

    ``detail`` is a human-readable status string: the target URL on
    success or an error explanation on failure.
    """
    msg = (message or "").strip()
    if not msg:
        return False, "empty message"
    tpc = (topic or _load_topic() or "").strip()
    if not tpc:
        return False, (
            "no ntfy topic configured "
            "(set LILBRO_NTFY_TOPIC or notify.topic in config.yaml)"
        )
    url = f"{_load_server()}/{tpc}"
    headers: dict[str, str] = {}
    if title:
        headers["Title"] = title
    try:
        import httpx  # type: ignore[import-not-found]
        resp = httpx.post(url, content=msg.encode("utf-8"), headers=headers, timeout=5.0)
        if resp.status_code < 400:
            return True, url
        return False, f"ntfy returned {resp.status_code}: {resp.text[:120]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"ntfy request failed: {exc}"
