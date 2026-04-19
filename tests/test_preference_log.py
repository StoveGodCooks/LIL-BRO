"""Tests for ``src_local.memory.preference_log.PreferenceLog``.

PreferenceLog is a plain-JSON persistence layer for small observed
user-behavior events.  The tests cover the record/query/top/forget
round-trip plus a few edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src_local.memory.preference_log import PreferenceLog


@pytest.fixture
def log_path(tmp_path: Path) -> Path:
    return tmp_path / "prefs.json"


class TestRecordAndPersist:
    def test_record_creates_file_on_first_write(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("naming_style", "snake_case")
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["events"][0]["type"] == "naming_style"
        assert data["events"][0]["value"] == "snake_case"
        assert "timestamp" in data["events"][0]

    def test_record_survives_reload(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("test_style", "pytest")
        log2 = PreferenceLog(log_path)
        assert len(log2.all_events()) == 1
        assert log2.all_events()[0]["value"] == "pytest"

    def test_record_stores_project_and_extra(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record(
            "dep_choice",
            "requests",
            project="/tmp/proj",
            extra={"reason": "simpler than httpx"},
        )
        ev = log.all_events()[0]
        assert ev["project"] == "/tmp/proj"
        assert ev["extra"]["reason"] == "simpler than httpx"


class TestQuery:
    def test_query_filters_by_type(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("naming_style", "snake_case")
        log.record("test_style", "pytest")
        log.record("naming_style", "snake_case")
        hits = log.query(event_type="naming_style")
        assert len(hits) == 2
        assert all(e["type"] == "naming_style" for e in hits)

    def test_query_returns_most_recent_first(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("t", "first")
        log.record("t", "second")
        log.record("t", "third")
        hits = log.query()
        assert [e["value"] for e in hits] == ["third", "second", "first"]

    def test_query_empty_when_no_match(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("a", "b")
        assert log.query(event_type="nope") == []


class TestTopPatterns:
    def test_top_patterns_counts_occurrences(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        for _ in range(3):
            log.record("naming_style", "snake_case")
        for _ in range(1):
            log.record("naming_style", "camelCase")
        top = log.top_patterns(n=5)
        assert top[0]["value"] == "snake_case"
        assert top[0]["count"] == 3
        assert top[1]["value"] == "camelCase"
        assert top[1]["count"] == 1

    def test_top_patterns_respects_limit(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        for v in ("a", "b", "c", "d", "e"):
            log.record("t", v)
        assert len(log.top_patterns(n=3)) == 3

    def test_top_patterns_empty_log(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        assert log.top_patterns() == []


class TestForget:
    def test_forget_removes_matching_events(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("naming", "snake_case")
        log.record("naming", "camelCase")
        log.record("test", "pytest")
        removed = log.forget("camel")
        assert removed == 1
        remaining = [e["value"] for e in log.all_events()]
        assert "camelCase" not in remaining
        assert "snake_case" in remaining

    def test_forget_matches_type_too(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("naming_style", "snake_case")
        log.record("test_style", "pytest")
        removed = log.forget("naming")
        assert removed == 1

    def test_forget_is_case_insensitive(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("style", "Snake_Case")
        assert log.forget("SNAKE") == 1

    def test_forget_empty_query_is_noop(self, log_path: Path) -> None:
        log = PreferenceLog(log_path)
        log.record("a", "b")
        assert log.forget("") == 0
        assert len(log.all_events()) == 1


class TestGrowthCap:
    def test_events_capped_to_max(self, log_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(PreferenceLog, "MAX_EVENTS", 5)
        log = PreferenceLog(log_path)
        for i in range(10):
            log.record("t", f"v{i}")
        events = log.all_events()
        assert len(events) == 5
        # Oldest are dropped — newest survive.
        assert events[-1]["value"] == "v9"
        assert events[0]["value"] == "v5"


class TestIOResilience:
    def test_corrupt_file_treated_as_empty(self, log_path: Path) -> None:
        log_path.write_text("not json", encoding="utf-8")
        log = PreferenceLog(log_path)
        assert log.all_events() == []
        log.record("t", "v")  # still usable after corrupt load
        assert len(log.all_events()) == 1
