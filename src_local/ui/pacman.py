"""PacManTrack -- animated Pac-Man row at the bottom of each panel.

Pac-Man bounces left and right across a dot-filled track.  Power-up dots
live at each end; when Pac-Man reaches a corner and eats the dot he gets
a 2-second speed boost.  The dot respawns after 8 seconds.
"""

from __future__ import annotations

from rich.text import Text
from textual.timer import Timer
from textual.widget import Widget


# Pac-Man glyphs (Unified Canadian Aboriginal Syllabics block).
# Fall back to plain ASCII if the terminal can't render them.
_PAC_RIGHT = "\u15E7"
_PAC_LEFT  = "\u15E4"

_POWER_DOT  = "\u25CF"
_EATEN_DOT  = " "
_TRACK_DOT  = "\u00B7"

_NORMAL_INTERVAL = 0.12   # seconds between steps at normal speed
_BOOST_INTERVAL  = 0.04   # seconds between steps while boosted
_BOOST_DURATION  = 2.0    # seconds the speed boost lasts
_DOT_RESPAWN     = 8.0    # seconds until an eaten power-dot comes back


class PacManTrack(Widget):
    """A 1-row animated Pac-Man track sized to the panel width."""

    DEFAULT_CSS = """
    PacManTrack {
        height: 1;
        width: 100%;
        background: #0A0A0A;
    }
    """

    def __init__(self, color: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._color = color
        self._pos: int = 1            # current column (0-indexed)
        self._dir: int = 1            # +1 = rightward, -1 = leftward
        self._track_width: int = 40   # updated on first resize
        self._boosted: bool = False
        self._boost_ticks_left: int = 0
        # Which corner indices currently have their dot eaten.
        self._eaten: set[int] = set()
        self._timer: Timer | None = None

    # ------------------------------------------------------------------ mount

    def on_mount(self) -> None:
        self._track_width = max(10, self.size.width)
        self._pos = 1
        self._start_timer(_NORMAL_INTERVAL)

    # ------------------------------------------------------------------ resize

    def on_resize(self, event) -> None:  # type: ignore[override]
        w = max(10, event.size.width)
        if w != self._track_width:
            # Clamp position into the new track.
            self._track_width = w
            self._pos = min(self._pos, w - 2)

    # ------------------------------------------------------------------ timer

    def _start_timer(self, interval: float) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_interval(interval, self._step)

    def _step(self) -> None:
        self._pos += self._dir

        # Bounce off ends and try to eat a power-dot.
        if self._pos >= self._track_width - 1:
            self._pos = self._track_width - 1
            self._dir = -1
            self._try_eat(self._track_width - 1)
        elif self._pos <= 0:
            self._pos = 0
            self._dir = 1
            self._try_eat(0)

        # Tick down the boost.
        if self._boosted:
            self._boost_ticks_left -= 1
            if self._boost_ticks_left <= 0:
                self._boosted = False
                self._start_timer(_NORMAL_INTERVAL)

        self.refresh()

    def _try_eat(self, corner: int) -> None:
        if corner in self._eaten:
            return
        # Eat the dot -> boost.
        self._eaten.add(corner)
        self._boosted = True
        self._boost_ticks_left = int(_BOOST_DURATION / _BOOST_INTERVAL)
        self._start_timer(_BOOST_INTERVAL)
        # Schedule respawn.
        self.set_timer(_DOT_RESPAWN, lambda c=corner: self._respawn(c))

    def _respawn(self, corner: int) -> None:
        self._eaten.discard(corner)
        self.refresh()

    # ------------------------------------------------------------------ render

    def render(self) -> Text:
        w = self._track_width
        if w < 3:
            return Text("")

        pac = _PAC_RIGHT if self._dir == 1 else _PAC_LEFT
        color = self._color
        boost_color = "#FFFFFF" if self._boosted else color

        # Build character array for the track row.
        chars: list[str] = []
        for i in range(w):
            if i == self._pos:
                chars.append(pac)
            elif i == 0:
                chars.append(_EATEN_DOT if 0 in self._eaten else _POWER_DOT)
            elif i == w - 1:
                chars.append(_EATEN_DOT if (w - 1) in self._eaten else _POWER_DOT)
            else:
                chars.append(_TRACK_DOT)

        line = Text("".join(chars), no_wrap=True, overflow="crop")

        # Style: Pac-Man in boost/normal color, power-dots in panel color,
        # track dots in a dim neutral.
        line.stylize("dim #333333", 0, w)  # base: all dim
        # Power-dot corners (only if uneaten).
        if 0 not in self._eaten:
            line.stylize(f"bold {color}", 0, 1)
        if (w - 1) not in self._eaten:
            line.stylize(f"bold {color}", w - 1, w)
        # Pac-Man.
        line.stylize(f"bold {boost_color}", self._pos, self._pos + 1)

        return line
