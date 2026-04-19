"""Progressive Web App server + phone notifications.

A tiny stdlib-only HTTP server serves a small single-page PWA that
renders the living roadmap, recent memories, and preference patterns.
Intended to be reachable from a phone over the user's existing
Tailscale / LAN connection -- there is no cloud component.

Push notifications use ntfy.sh, which requires no account.
"""
