"""`integral.language_set` — the seven declarations of the supported language set.

The mutation half of this (widen each site, watch the checker go red) is a shell
harness run by hand: 7 of 7 caught, recorded on #360. What is asserted here is
the half a mutation cannot reach — what the checker does when a declaration
**stops existing**, which is the direction it could fail open in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral import language_set


def test_the_committed_declarations_agree() -> None:
    record = language_set.measure()
    assert record["disagreeing"] == []
    assert record["language_set_declarations_disagreeing"] == 0


def test_the_measurement_is_over_every_known_site() -> None:
    record = language_set.measure()
    assert record["gate_status"] == "measured"
    assert (
        record["language_set_declarations_resolved"] >= language_set.MINIMUM_LANGUAGE_DECLARATIONS
    )


def test_every_declaration_is_read_from_the_live_object_not_a_copy() -> None:
    """No entry may be a literal set written into this module.

    A table of expected values here would be an eighth restatement, and it would
    agree with itself for ever — the check would pass because it was comparing a
    copy to a copy, which is the whole failure it exists to catch.
    """
    record = language_set.measure()
    names = set(record["declarations"])
    assert language_set.REFERENCE in names
    for name in names:
        assert not name.startswith("language_set."), f"{name} is this module quoting itself"


def test_a_site_that_raises_is_a_disagreement_not_a_skipped_row(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A deleted declaration must not make the count *smaller*.

    The tempting implementation drops an unreadable site, which turns a removed
    declaration into one fewer disagreement — a check that gets greener as the
    thing it checks disappears.
    """

    def explode() -> frozenset[str]:
        raise AttributeError("LANGUAGES is gone")

    monkeypatch.setattr(
        language_set,
        "DECLARATIONS",
        (*language_set.DECLARATIONS[:-1], ("a_removed_site", explode)),
    )
    record = language_set.measure()
    assert "a_removed_site" in record["disagreeing"]
    assert record["unreadable"] == ["a_removed_site"]
    assert record["language_set_declarations_disagreeing"] >= 1


def test_too_few_sites_reports_unmeasured_rather_than_a_clean_zero(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(language_set, "DECLARATIONS", language_set.DECLARATIONS[:3])
    record = language_set.measure()
    assert record["language_set_declarations_disagreeing"] == 0
    assert record["gate_status"] == "unmeasured"


def test_an_unreadable_reference_fails_every_site_rather_than_passing_them(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """With nothing to compare against, zero disagreements would be a lie."""

    def explode() -> frozenset[str]:
        raise ImportError("corpus is gone")

    monkeypatch.setattr(
        language_set,
        "DECLARATIONS",
        ((language_set.REFERENCE, explode), *language_set.DECLARATIONS[1:]),
    )
    record = language_set.measure()
    assert record["reference_value"] is None
    assert len(record["disagreeing"]) == len(language_set.DECLARATIONS)


def test_check_exits_three_when_the_run_measured_nothing(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(language_set, "DECLARATIONS", language_set.DECLARATIONS[:3])
    monkeypatch.setattr(language_set, "write_evidence", lambda: language_set.measure())
    assert language_set._main(["--check"]) == 3


def test_check_exits_one_on_a_disagreement(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        language_set,
        "DECLARATIONS",
        (*language_set.DECLARATIONS, ("a_wrong_site", lambda: frozenset({"en", "es", "ca", "pt"}))),
    )
    monkeypatch.setattr(language_set, "write_evidence", lambda: language_set.measure())
    assert language_set._main(["--check"]) == 1


def test_check_exits_zero_on_the_committed_tree(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(language_set, "write_evidence", lambda: language_set.measure())
    assert language_set._main(["--check"]) == 0


def test_the_catalogue_is_read_from_the_file(tmp_path: Path) -> None:
    catalogue = tmp_path / "catalogue.json"
    catalogue.write_text(json.dumps({"languages": ["en", "pt"]}), encoding="utf-8")
    assert language_set._catalogue_languages(catalogue) == frozenset({"en", "pt"})


def test_a_missing_catalogue_raises_rather_than_returning_empty(tmp_path: Path) -> None:
    """An empty set would compare unequal and so still be caught — but it would be
    caught for the wrong reason, and reported as a disagreement rather than as a
    missing file."""
    with pytest.raises(OSError):
        language_set._catalogue_languages(tmp_path / "nope.json")


def test_write_evidence_records_the_floor_not_the_count_of_the_day(tmp_path: Path) -> None:
    """T100: a denominator committed as an exact value drifts; a floor does not."""
    record = language_set.write_evidence(tmp_path / "T129.json")
    assert (
        record["language_set_declarations_compared_at_least"]
        == language_set.MINIMUM_LANGUAGE_DECLARATIONS
    )
    written = json.loads((tmp_path / "T129.json").read_text(encoding="utf-8"))
    assert written == record


def test_interview_no_longer_restates_the_language_set() -> None:
    """#360 deleted the eighth site; this is what stops it coming back."""
    source = Path("src/integral/interview.py").read_text(encoding="utf-8")
    assert '("en", "es", "ca")' not in source
