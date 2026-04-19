"""Tests for ``src_local.personas`` -- persona registry + classifier."""

from __future__ import annotations

import pytest

from src_local import personas
from src_local.personas import (
    DAD,
    GRANDMA,
    MOM,
    classify,
    detect_addressed,
    get,
    strip_address_prefix,
)


class TestRegistry:
    def test_get_by_name_case_insensitive(self) -> None:
        assert get("MOM") is MOM
        assert get("Dad") is DAD
        assert get("grandma") is GRANDMA

    def test_get_unknown_returns_none(self) -> None:
        assert get("uncle") is None
        assert get("") is None

    def test_personas_have_system_prefixes(self) -> None:
        for p in (MOM, DAD, GRANDMA):
            assert isinstance(p.system_prefix, str)
            assert len(p.system_prefix) > 20

    def test_all_personas_listed(self) -> None:
        assert set(personas.PERSONAS) == {"mom", "dad", "grandma"}


class TestAddressDetection:
    @pytest.mark.parametrize(
        "prompt, expected",
        [
            ("Mom, where are we on auth?", "mom"),
            ("Dad: is this efficient?", "dad"),
            ("Grandma what did we decide last week?", "grandma"),
            ("MOM, please check", "mom"),
            ("  Dad, ship it", "dad"),
        ],
    )
    def test_detect_positive(self, prompt: str, expected: str) -> None:
        assert detect_addressed(prompt) == expected

    def test_detect_none_when_not_addressed(self) -> None:
        assert detect_addressed("What is the plan?") is None
        assert detect_addressed("") is None

    def test_detect_requires_word_boundary(self) -> None:
        # "momentum" starts with "mom" but isn't an address.
        assert detect_addressed("momentum is key") is None

    def test_strip_address_prefix(self) -> None:
        assert strip_address_prefix("Dad, ship it") == "ship it"
        assert strip_address_prefix("Mom: check in") == "check in"
        assert strip_address_prefix("plain text") == "plain text"
        assert strip_address_prefix("") == ""


class TestClassifier:
    def test_explicit_address_beats_keywords(self) -> None:
        # "refactor" is Dad-coded; addressing Grandma wins.
        assert classify("Grandma, should we refactor?") == "grandma"

    def test_teaching_mode_forces_grandma(self) -> None:
        assert classify("fix this bug", teaching_mode=True) == "grandma"

    def test_roadmap_drift_forces_mom(self) -> None:
        assert classify("refactor now", roadmap_drift=True) == "mom"

    def test_mom_keywords(self) -> None:
        assert classify("where are we on the roadmap?") == "mom"
        assert classify("check in on progress please") == "mom"

    def test_dad_keywords(self) -> None:
        assert classify("just ship the simplest fix") == "dad"
        assert classify("this is overengineered bloat") == "dad"

    def test_grandma_keywords(self) -> None:
        assert classify("remember when we tried this pattern before?") == "grandma"
        assert classify("what's the big picture here") == "grandma"

    def test_default_bias_is_dad(self) -> None:
        # Nothing keyword-matches: fall back to Dad (execution bias).
        assert classify("hello") == "dad"

    def test_tie_break_order(self) -> None:
        # Equal scores across mom+dad+grandma all zero -> dad fallback.
        assert classify("asdfqwer") == "dad"

    def test_state_override_beats_address_when_address_absent(self) -> None:
        # No explicit address in the prompt, but state says teaching mode.
        assert classify("walk me through recursion", teaching_mode=True) == "grandma"

    def test_address_beats_state_override(self) -> None:
        # Explicit address wins even when teaching mode is on.
        assert classify(
            "Dad, just tell me the answer", teaching_mode=True
        ) == "dad"
