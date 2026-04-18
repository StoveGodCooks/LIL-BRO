"""Tests for display helpers in `src_local.ui.panels`.

Focus: pure regex helpers that do not require a running Textual app.
"""

from __future__ import annotations

from src_local.ui.panels import _MD_LINK_RE


class TestMarkdownLinkStrip:
    """`[label](url)` → `label` so the terminal shows readable text."""

    def test_basic_link_is_stripped(self) -> None:
        assert _MD_LINK_RE.sub(r"\1", "See [docs](http://x.y)") == "See docs"

    def test_multiple_links_in_line(self) -> None:
        line = "Check [one](a) and [two](b)"
        assert _MD_LINK_RE.sub(r"\1", line) == "Check one and two"

    def test_empty_label(self) -> None:
        # [](url) collapses to empty string.
        assert _MD_LINK_RE.sub(r"\1", "prefix [](http://x)") == "prefix "

    def test_no_link_is_unchanged(self) -> None:
        assert _MD_LINK_RE.sub(r"\1", "plain text") == "plain text"

    def test_does_not_touch_bare_brackets(self) -> None:
        # Brackets without a trailing `(url)` must stay put.
        assert _MD_LINK_RE.sub(r"\1", "list [item] end") == "list [item] end"

    def test_preserves_code_fences(self) -> None:
        # Links inside backticks aren't special-cased — current regex strips
        # regardless. This test locks that in so we notice if behavior changes.
        out = _MD_LINK_RE.sub(r"\1", "`[label](url)`")
        assert out == "`label`"


class TestCommandsMetaHasResume:
    """The palette / help screen both read from commands_meta."""

    def test_resume_is_registered(self) -> None:
        from src_local.ui.commands_meta import COMMANDS, canonical_trigger

        triggers = [canonical_trigger(name) for name, _, _ in COMMANDS]
        assert "/resume" in triggers

    def test_resume_description_mentions_session(self) -> None:
        from src_local.ui.commands_meta import COMMANDS

        resume_entries = [
            entry for entry in COMMANDS if entry[0].startswith("/resume")
        ]
        assert resume_entries, "expected /resume entry in COMMANDS"
        name, _target, desc = resume_entries[0]
        assert "session" in desc.lower() or "session" in name.lower()

    def test_reset_description_reflects_fresh_semantics(self) -> None:
        from src_local.ui.commands_meta import COMMANDS

        reset_entries = [
            entry for entry in COMMANDS if entry[0] == "/reset"
        ]
        assert reset_entries, "expected /reset entry in COMMANDS"
        _name, _target, desc = reset_entries[0]
        # The description should signal that state is cleared, not preserved.
        assert any(
            word in desc.lower() for word in ("fresh", "clear", "remove")
        )
