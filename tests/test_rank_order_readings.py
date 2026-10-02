"""T242 — an order when no total exists, ties reported as ties, a named set.

Each case is derived from the task text: order on the known part, on pay, or on
an interval over the unknowns, and say which; never present the id tie-break as
a preference; rank a named set.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from integral.profile import ProfileRevision
from integral.rank import (
    DEFAULT_T242_EVIDENCE_PATH,
    Candidate,
    RankingError,
    measure_order,
    ordering_defects,
    priced_dimensions,
    rank,
    rank_named,
    salary_interval,
)

DIMS = ("remote", "commute")
WEIGHTS = {
    "currency": "EUR",
    "part_worths": {
        "remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0},
        "commute": {"utility_per_unit": 0.3, "salary_equivalent_per_month": 200.0},
    },
}
REV = ProfileRevision(rows=1, sha256="0" * 64)


def cand(i: str, salary: float | None, **scores: float) -> Candidate:
    return Candidate(
        offer_id=i,
        salary_per_month=salary,
        scores=scores,
        unknown=frozenset(d for d in DIMS if d not in scores),
    )


def run(cands: list[Candidate]) -> dict[str, Any]:
    return rank(cands, dimensions=DIMS, revision=REV, weights=WEIGHTS, at="t")


def audit(ranking: dict[str, Any], cands: list[Candidate]) -> dict[str, int]:
    return ordering_defects(ranking, cands, priced_dimensions(WEIGHTS))


def test_unknown_everywhere_is_ordered_by_salary_not_hash() -> None:
    cands = [cand("a", 3000.0), cand("b", 4000.0), cand("c", 3500.0)]
    ranking = run(cands)
    assert ranking["salary_equivalent_total"] == {}  # unknown stays unknown
    assert ranking["pareto"] == ["b", "c", "a"]
    assert {v["reading"] for v in ranking["order_basis"].values()} == {"interval"}
    # each unknown dimension spans its full range: +-(600 + 200) around the salary
    assert ranking["order_basis"]["a"]["low"] == 2200.0
    assert ranking["order_basis"]["a"]["high"] == 3800.0
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0


def test_a_salary_only_offer_that_beats_a_total_under_every_resolution_ranks_above_it() -> None:
    """Reviewer B1. a: [8200, 9800] is above z's 2800 whatever the unknowns are."""
    z = cand("z", 2000.0, remote=1.0, commute=1.0)
    a = cand("a", 9000.0)
    b = cand("b", 5000.0)
    ranking = run([z, a, b])
    assert ranking["pareto"] == ["a", "b", "z"]
    assert ranking["order_basis"]["z"]["reading"] == "total"
    assert audit(ranking, [z, a, b])["inversions"] == 0


def test_the_partial_variant_of_that_case() -> None:
    """remote known at 1, commute unknown: [9400, 9800] against a total of 2000."""
    low = cand("a", 2000.0, remote=1.0, commute=0.0)
    partial = cand("b", 9000.0, remote=1.0)
    ranking = run([low, partial])
    assert ranking["pareto"] == ["b", "a"]


def test_the_audit_flags_a_total_printed_above_a_wholly_better_interval() -> None:
    z = cand("z", 2000.0, remote=1.0, commute=1.0)
    a = cand("a", 9000.0)
    ranking = run([z, a])
    wrong = {**ranking, "pareto": ["z", "a"]}
    assert audit(wrong, [z, a])["inversions"] == 2


def test_overlapping_intervals_are_reported_as_incomparable_not_as_a_preference() -> None:
    cands = [cand("a", 3000.0), cand("b", 3100.0)]
    ranking = run(cands)
    assert ranking["pareto"] == ["b", "a"]
    assert ranking["incomparable"] == [
        {"offer_ids": ["b", "a"], "reason": "incomparable: intervals overlap"}
    ]
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0
    stripped = {**ranking, "incomparable": []}
    assert audit(stripped, cands)["unreported"] == 2


def test_equal_known_parts_are_a_tie_whose_reason_names_the_reading_used() -> None:
    """Reviewer O1: a (2000, remote 1) and b (2600) share the known part 2600."""
    a = cand("a", 2000.0, remote=1.0)
    b = cand("b", 2600.0)
    ranking = run([a, b])
    (tie,) = ranking["ties"]
    assert tie["offer_ids"] == ["a", "b"]
    assert tie["reading"] == "interval"
    assert "published pay" in tie["reason"]
    assert "listed in id order" not in tie["reason"]


def test_a_single_offer_with_no_reading_is_consistent_between_ranking_and_audit() -> None:
    """Reviewer B2: one `none` offer, no tie group — producer and audit must agree."""
    cands = [cand("a", None), cand("b", 3000.0), cand("c", 4000.0)]
    ranking = run(cands)
    assert ranking["pareto"] == ["c", "b", "a"]
    assert ranking["unordered"] == ["a"]
    assert ranking["order_basis"]["a"]["reading"] == "none"
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0
    assert audit({**ranking, "incomparable": []}, cands)["unreported"] > 0


def test_silent_offers_with_no_known_part_are_one_reported_tie_group() -> None:
    cands = [cand("a", 3000.0), cand("b", 3000.0), cand("c", None), cand("d", None)]
    ranking = run(cands)
    by_reading = {tie["reading"]: tie["offer_ids"] for tie in ranking["ties"]}
    assert by_reading == {"interval": ["a", "b"], "none": ["c", "d"]}
    assert ranking["unordered"] == ["c", "d"]
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0


def test_no_salary_but_a_known_priced_dimension_still_has_a_reading() -> None:
    """Reviewer O2: not `none`; unbounded interval, ordered without sinking."""
    quiet = cand("a", None, remote=1.0, commute=1.0)
    paid = cand("b", 2000.0, remote=1.0, commute=1.0)
    ranking = run([quiet, paid])
    assert ranking["order_basis"]["a"]["reading"] == "known_part"
    assert ranking["order_basis"]["a"]["high"] is None
    assert ranking["unordered"] == []
    # T138: not a low salary — it keeps the alphabet's slot beside its twin
    assert ranking["pareto"] == ["a", "b"]
    assert ranking["incomparable"]


def test_the_interval_never_scores_an_unknown_as_zero() -> None:
    interval = salary_interval(cand("a", 3000.0), priced_dimensions(WEIGHTS))
    assert (interval.low, interval.mid, interval.high) == (2200.0, 3000.0, 3800.0)


def test_l1_has_no_priced_dimension_and_reads_the_salary() -> None:
    ranking = rank(
        [cand("a", 3000.0), cand("b", 4000.0)], dimensions=DIMS, revision=REV, weights=None, at="t"
    )
    assert ranking["pareto"] == ["b", "a"]
    assert {v["reading"] for v in ranking["order_basis"].values()} == {"salary"}


def test_rank_named_ranks_only_the_named_set_and_rejects_strangers() -> None:
    cands = [cand("a", 1000.0), cand("b", 2000.0), cand("c", 3000.0)]
    kw: dict[str, Any] = {"dimensions": DIMS, "revision": REV, "weights": WEIGHTS, "at": "t"}
    assert rank_named(cands, ["a", "b"], **kw)["pareto"] == ["b", "a"]
    with pytest.raises(RankingError, match="nope"):
        rank_named(cands, ["a", "nope"], **kw)


def test_the_measured_fraction_is_zero_and_the_audit_can_rise() -> None:
    measured = measure_order()
    assert measured["offers"] >= 12
    assert measured["offers_with_a_total"] == 0
    assert measured["fraction_ordered_by_id"] == 0
    assert measured["violation_detected_when_planted"] == 1
    assert set(measured["readings_used"]) >= {"interval", "known_part", "none"}


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    assert json.loads(DEFAULT_T242_EVIDENCE_PATH.read_text(encoding="utf-8")) == measure_order()
