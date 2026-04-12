"""XPBarWidget -- thin status-strip XP meter.

Gated behind the ``xp_bar_unlock`` perk (Lv 10+). Below the gate the
widget renders empty so it occupies zero visual space; above it the
widget renders a Rich-style bar::

    Lv 12  [================] 120/250 xp

The widget is intentionally tiny -- no state beyond the cached last
render string so we can short-circuit redraws when nothing changed.
It's a ``Static`` so it drops into any Textual ``Horizontal`` without
special layout fuss.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import Static

if TYPE_CHECKING:
    from src_local.rpg.player import PlayerProfile


BAR_WIDTH = 14
UNLOCK_PERK = "xp_bar_unlock"


def render_xp_line(profile: "PlayerProfile") -> str:
    """Return the one-line rendering of *profile*'s XP state.

    Empty string when the unlock perk is missing -- callers should
    treat empty as "don't show the widget at all".
    """
    if UNLOCK_PERK not in profile.active_perks():
        return ""
    level, into, needed = profile.level_progress()
    if needed <= 0:
        return f"Lv {level} MAX ({profile.xp} xp)"
    filled = int(round((into / needed) * BAR_WIDTH))
    filled = max(0, min(BAR_WIDTH, filled))
    bar = "\u2588" * filled + "\u2591" * (BAR_WIDTH - filled)
    return f"Lv {level} [{bar}] {into}/{needed} xp"


class XPBarWidget(Static):
    """Status-strip XP meter. Re-render cheap via ``update_from_profile``."""

    DEFAULT_CSS = """
    XPBarWidget {
        width: auto;
        height: 1;
        color: #A8D840;
        content-align: right middle;
        padding: 0 1;
    }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__("", id=id)
        self._profile: "PlayerProfile | None" = None
        self._last_text: str = ""

    def attach_profile(self, profile: "PlayerProfile") -> None:
        """Bind a profile so ``refresh_from_profile`` has a source."""
        self._profile = profile
        self.refresh_from_profile()

    def refresh_from_profile(self) -> None:
        """Recompute the line and update the widget if it changed.

        Hides the widget entirely (``display=False``) when the unlock
        perk is missing, so it occupies no space in the status strip.
        """
        if self._profile is None:
            return
        text = render_xp_line(self._profile)
        if text == "":
            if self.display:
                self.display = False
            return
        if not self.display:
            self.display = True
        if text != self._last_text:
            self.update(text)
            self._last_text = text
