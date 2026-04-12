"""Textual `Suggester` that renders ghost-text autocompletion for slash
commands inside the input bar.

When the user is typing something that starts with ``/`` (and has NOT
yet hit the first space), we look up the canonical command triggers
defined in :mod:`src_local.ui.commands_meta` and propose the shortest one
whose prefix matches what they've typed so far. Textual's Input widget
will render the remainder of the suggestion as faded ghost text and the
user can accept it with the right arrow key.

Non-slash input gets no suggestion -- for free-form chat we don't want
the Input flashing stale ghosts at the user.
"""

from __future__ import annotations

from textual.suggester import Suggester

from src_local.ui.commands_meta import all_triggers


class SlashSuggester(Suggester):
    """Ghost-text completer for slash commands.

    Textual's `Suggester.get_suggestion` is called on every Input change
    and must return either a string that STARTS WITH the current value
    (the widget renders the tail as ghost text) or ``None``.
    """

    def __init__(self) -> None:
        # `use_cache=False` so we always reflect the live command list
        # even if it were mutated at runtime (it isn't today, but cheap).
        super().__init__(use_cache=False, case_sensitive=False)
        self._triggers = all_triggers()

    async def get_suggestion(self, value: str) -> str | None:
        if not value or not value.startswith("/"):
            return None
        # Once the user has typed a space, they're writing arguments; get
        # out of the way so the ghost doesn't flicker past the command.
        if " " in value:
            return None
        low = value.lower()
        # Pick the shortest trigger whose prefix matches; shortest wins
        # so ``"/s"`` suggests ``"/save"`` rather than ``"/slow-mode"``.
        candidates = [t for t in self._triggers if t.lower().startswith(low)]
        if not candidates:
            return None
        # Don't suggest the same thing the user has already fully typed.
        candidates = [t for t in candidates if t.lower() != low]
        if not candidates:
            return None
        return min(candidates, key=len)
