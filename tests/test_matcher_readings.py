"""D-30: the two RFC 9309 matchers take one reading, and the gap is measured."""

from __future__ import annotations

import json
from itertools import islice
from typing import Any

import pytest

from integral import matcher_readings as mr
from integral import robots


@pytest.fixture(scope="module")
def measured() -> dict[str, Any]:
    return mr.measure()


def test_both_matchers_agree_over_the_generated_population(measured: dict[str, Any]) -> None:
    assert measured["gate_status"] == "measured"
    assert measured["matcher_reading_divergences_unrecorded"] == 0, measured["unrecorded_examples"]
    assert measured["matcher_reading_divergences"] == 0
    assert measured["triples_compared"] >= mr.MINIMUM_TRIPLES
    assert measured["contested_triples"] >= mr.MINIMUM_CONTESTED_TRIPLES


def test_the_floors_are_the_population_not_slack_under_it(measured: dict[str, Any]) -> None:
    """A floor under the population lets the generator shrink and still score clean."""
    assert measured["triples_compared"] == mr.MINIMUM_TRIPLES
    assert measured["contested_triples"] == mr.MINIMUM_CONTESTED_TRIPLES


def test_an_empty_generator_is_unmeasured_not_clean() -> None:
    result = mr.measure([])
    assert result["gate_status"] == "unmeasured"
    assert result["triples_compared"] == 0


def test_a_shrunken_generator_is_unmeasured_not_clean() -> None:
    result = mr.measure(list(islice(mr.generate(), 100)))
    assert result["matcher_reading_divergences_unrecorded"] == 0
    assert result["gate_status"] == "unmeasured"


def test_an_unrecorded_divergence_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """The counter is not a constant: a disagreeing matcher raises it."""
    population = list(islice(mr.generate(), 50))
    monkeypatch.setattr(mr, "_verdicts", lambda text, target: (True, False))
    result = mr.measure(population)
    assert result["matcher_reading_divergences_unrecorded"] == 50
    assert result["divergences_robots_more_permissive"] == 50


def test_a_recorded_divergence_is_not_counted_as_unrecorded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    population = list(islice(mr.generate(), 10))
    monkeypatch.setattr(mr, "_verdicts", lambda text, target: (True, False))
    monkeypatch.setattr(mr, "RECORDED_DIVERGENCES", frozenset(population[:4]))
    result = mr.measure(population)
    assert result["matcher_reading_divergences"] == 10
    assert result["matcher_reading_divergences_unrecorded"] == 6


def test_reverting_the_allow_narrowing_in_robots_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The measurement sees reading (c) come back, over the contested subset."""
    real = robots._normalize_rule
    monkeypatch.setattr(robots, "_normalize_rule", lambda pattern, *, widen=True: real(pattern))
    contested = [t for t in mr.generate() if mr.is_contested(mr._allow_of(t[0]))]
    result = mr.measure(contested)
    assert result["matcher_reading_divergences_unrecorded"] > 0
    assert result["divergences_robots_more_permissive"] > 0


def test_the_historic_divergences_are_inside_the_population() -> None:
    """The three rows D-30 closed are reachable by the generator, not a hand list."""
    population = set(mr.generate())
    assert (
        "User-agent: *\nDisallow: /a*\nAllow: /*/x\n",
        "/a?b=/x",
    ) in population
    assert (
        "User-agent: *\nDisallow: /a\nAllow: /*/x\n",
        "/a?b=%2Fx",
    ) in population
    assert (
        "User-agent: *\nDisallow: /a\nAllow: /*http://\n",
        "/a?u=http://x",
    ) in population


@pytest.mark.parametrize(
    ("allow", "contested"),
    [
        ("/", False),
        ("/*x", False),
        ("/*/x", True),
        ("/*?x", True),
        ("/a/b*x", False),  # the first run sits at octet 0: its region is not in doubt
        ("/*x*/", True),
        ("/*%2Fx", False),
        ("/*x$", False),
    ],
)
def test_contested_is_read_off_the_rfc_not_a_matcher(allow: str, contested: bool) -> None:
    assert mr.is_contested(allow) is contested


def test_the_pinned_refusals_are_refused_by_both_matchers() -> None:
    """The fail-open directions the review found stay closed — REFUSE is the pass state."""
    assert mr.PINNED_REFUSALS
    for text, target in mr.PINNED_REFUSALS:
        assert mr._verdicts(text, target) == (False, False), (text, target)
        # ... and the Disallow alone refuses, so the pin is not vacuous.
        alone = text.split("Allow:")[0]
        assert mr._verdicts(alone, target) == (False, False)


def test_a_permitting_matcher_breaks_the_pinned_refusal_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mr, "_verdicts", lambda text, target: (True, False))
    result = mr.measure(list(islice(mr.generate(), 5)))
    assert result["pinned_refusals_held"] is False


def test_the_population_exercises_contested_disallows() -> None:
    """F3: the widened-Disallow branch is in the population, and counted as contested."""
    population = set(mr.generate())
    assert (
        "User-agent: *\nDisallow: /*/x\nAllow: /*=\n",
        "/a?b=/x",
    ) in population
    assert mr.triple_is_contested("User-agent: *\nDisallow: /*/x/\nAllow: /a?b=\n")
    assert not mr.triple_is_contested("User-agent: *\nDisallow: /a\nAllow: /a?b=\n")


def test_a_disallow_is_widened_and_an_allow_is_not() -> None:
    """The one-directional rule, at the seam both matchers share."""
    path = robots._request_path("https://x.test/a?b=/x")
    assert robots._match_octets(*robots._normalize_rule("/*/x"), path) is not None
    assert robots._match_octets(*robots._normalize_rule("/*/x", widen=False), path) is None


def test_the_committed_evidence_matches_what_the_module_measures_now(
    measured: dict[str, Any],
) -> None:
    on_disk = json.loads(mr.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert on_disk == mr.record(measured)
    assert on_disk["matcher_reading_divergences_unrecorded"] == 0
    assert on_disk["gate_status"] == "measured"
    assert "triples_compared" not in on_disk, "the count of the day must not be committed"


def test_the_main_entry_point_exits_zero_on_a_clean_measurement(tmp_path: Any) -> None:
    out = tmp_path / "D-30.json"
    assert mr._main(["--write-evidence", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["gate_status"] == "measured"
