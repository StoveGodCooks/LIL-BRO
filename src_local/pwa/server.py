"""Stdlib HTTP server for the LIL BRO PWA.

Runs in a daemon background thread. Zero extra dependencies --
everything is ``http.server``. Not intended for public internet
exposure: the deployment model is a phone on the same LAN or
Tailscale network.

Endpoints
---------

``GET /``                  index.html
``GET /manifest.webmanifest`` PWA manifest
``GET /service-worker.js`` SW for offline shell
``GET /static/<file>``     any file in ``static/``
``GET /api/roadmap``       roadmap.json contents
``GET /api/memories``      most recent memories
``GET /api/prefs``         top preference patterns
``GET /api/icebox``        open icebox items
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger("lilbro-local.pwa.server")


_STATIC_DIR = Path(__file__).parent / "static"


class _State:
    lock: ClassVar[threading.Lock] = threading.Lock()
    server: HTTPServer | None = None
    thread: threading.Thread | None = None
    port: int | None = None


def _lan_ip() -> str:
    """Best-effort local LAN address for logging / display."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Doesn't actually connect; used to pick a routable iface.
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("PWA: failed reading %s: %s", path, exc)
    return default


class _Handler(BaseHTTPRequestHandler):
    # Silence default access logging -- the TUI shouldn't get spam.
    def log_message(self, format: str, *args) -> None:  # noqa: A002, ARG002
        return

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: object, status: int = 200) -> None:
        self._send(
            status,
            json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
        )

    def _send_static(self, name: str) -> None:
        path = _STATIC_DIR / name
        if not path.exists() or not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = _guess_content_type(path.suffix)
        self._send(200, path.read_bytes(), ctype)

    # --------------------------------------------------------------
    # Routing
    # --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        raw = self.path.split("?", 1)[0]
        route = raw.rstrip("/") or "/"
        home = Path.home() / ".lilbro-local"

        if route == "/" or route == "/index.html":
            self._send_static("index.html")
            return
        if route == "/manifest.webmanifest":
            self._send_static("manifest.webmanifest")
            return
        if route == "/service-worker.js":
            self._send_static("service-worker.js")
            return
        if route.startswith("/static/"):
            self._send_static(route[len("/static/"):])
            return
        if route == "/api/roadmap":
            data = _read_json(home / "roadmap.json", {"milestones": []})
            self._send_json(data)
            return
        if route == "/api/icebox":
            data = _read_json(home / "icebox.json", {"items": []})
            self._send_json(data)
            return
        if route == "/api/memories":
            # Pull recent memories via MemoryStore when chromadb is present.
            try:
                from src_local.memory.chroma_store import MemoryStore
                store = MemoryStore(home / "memory")
                out = store.recent(n=20) if hasattr(store, "recent") else []
                self._send_json({"items": out})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"items": [], "error": str(exc)})
            return
        if route == "/api/prefs":
            try:
                from src_local.memory.preference_log import PreferenceLog
                plog = PreferenceLog(home / "preferences.json")
                self._send_json({"top": plog.top_patterns(n=10)})
            except Exception as exc:  # noqa: BLE001
                self._send_json({"top": [], "error": str(exc)})
            return
        if route == "/api/health":
            self._send_json({"ok": True})
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")


def _guess_content_type(suffix: str) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".webmanifest": "application/manifest+json; charset=utf-8",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }.get(suffix.lower(), "application/octet-stream")


# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


def start(*, host: str = "0.0.0.0", port: int = 8765) -> str:
    """Start the server in a daemon thread. Returns the public URL.

    Raises if the port is already bound or the server is already
    running.  Idempotent-ish: if ``start`` is called twice without
    ``stop`` in between, we raise to surface the programming error.
    """
    with _State.lock:
        if _State.server is not None:
            raise RuntimeError(f"PWA already running on port {_State.port}")
        server = HTTPServer((host, port), _Handler)
        bound_port = server.server_address[1]
        thread = threading.Thread(
            target=server.serve_forever, name="lilbro-pwa", daemon=True
        )
        thread.start()
        _State.server = server
        _State.thread = thread
        _State.port = bound_port
    return f"http://{_lan_ip()}:{bound_port}/"


def stop() -> None:
    """Stop the server if running. Safe to call when nothing is up."""
    with _State.lock:
        server = _State.server
        thread = _State.thread
        _State.server = None
        _State.thread = None
        _State.port = None
    if server is not None:
        try:
            server.shutdown()
            server.server_close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PWA stop: %s", exc)
    if thread is not None:
        try:
            thread.join(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass


def current_url() -> str | None:
    with _State.lock:
        if _State.server is None or _State.port is None:
            return None
        return f"http://{_lan_ip()}:{_State.port}/"


def is_running() -> bool:
    with _State.lock:
        return _State.server is not None
