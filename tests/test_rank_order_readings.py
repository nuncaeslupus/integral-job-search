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
    _reference_interval,
    measure_order,
    ordering_defects,
    point_band,
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
        pay=point_band(salary, "EUR"),
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
        {
            "offer_id": "b",
            "cannot_be_ordered_against": ["a"],
            "reason": "incomparable: intervals overlap",
        },
        {
            "offer_id": "a",
            "cannot_be_ordered_against": ["b"],
            "reason": "incomparable: intervals overlap",
        },
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
    assert ranking["order_basis"]["a"]["high"] is None  # no upper bound, ever
    assert ranking["order_basis"]["a"]["low"] == 800.0  # the known lower part
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


def pairs_of(ranking: dict[str, Any]) -> set[frozenset[str]]:
    return {
        frozenset((e["offer_id"], o))
        for e in ranking["incomparable"]
        for o in e["cannot_be_ordered_against"]
    }


def test_n2_overlap_is_reported_for_every_pair_not_only_neighbours() -> None:
    """Chain a 2200-3800, b 1700-3300, c 1200-2800, d 700-2300: a/c and b/d overlap too."""
    cands = [cand("a", 3000.0), cand("b", 2500.0), cand("c", 2000.0), cand("d", 1500.0)]
    ranking = run(cands)
    assert ranking["pareto"] == ["a", "b", "c", "d"]
    pairs = pairs_of(ranking)
    assert frozenset("ac") in pairs
    assert frozenset("bd") in pairs
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0
    stripped = {**ranking, "incomparable": []}
    assert audit(stripped, cands)["unreported"] == 4


def test_n2_an_inversion_across_an_unbounded_offer_is_caught() -> None:
    """x 1200-2800 printed above z 4200-5800, an unbounded k between: not adjacent."""
    x = cand("x", 2000.0)
    z = cand("z", 5000.0)
    k = cand("k", None, remote=1.0, commute=1.0)
    ranking = run([x, z, k])
    wrong = {**ranking, "pareto": ["x", "k", "z"]}
    assert audit(wrong, [x, z, k])["inversions"] >= 1


def test_n1_an_offer_with_no_salary_and_no_twin_is_incomparable_with_every_neighbour() -> None:
    k = cand("k", None, remote=1.0, commute=1.0)
    cands = [cand("a", 3000.0), cand("b", 4000.0), cand("c", 5000.0), k]
    ranking = run(cands)
    (entry,) = [e for e in ranking["incomparable"] if e["offer_id"] == "k"]
    assert sorted(entry["cannot_be_ordered_against"]) == ["a", "b", "c"]
    assert ranking["order_basis"]["k"]["high"] is None
    assert audit(ranking, cands)["offers_ordered_by_id"] == 0
    # stripping k's marks makes the audit rise: they are what keeps k's slot honest
    kept = [
        {**e, "cannot_be_ordered_against": [o for o in e["cannot_be_ordered_against"] if o != "k"]}
        for e in ranking["incomparable"]
        if e["offer_id"] != "k"
    ]
    assert audit({**ranking, "incomparable": kept}, cands)["unreported"] > 0


def test_reference_interval_is_independent_and_agrees_with_the_producer_on_cases() -> None:
    priced = priced_dimensions(WEIGHTS)
    for c in (
        cand("a", 3000.0),
        cand("b", 2000.0, remote=1.0),
        cand("c", 2000.0, remote=1.0, commute=1.0),
    ):
        i = salary_interval(c, priced)
        assert _reference_interval(c, priced) == (i.low, i.high)
    k = cand("k", None, remote=1.0)
    assert _reference_interval(k, priced) == (400.0, float("inf"))
    assert _reference_interval(cand("n", None), priced) == (-float("inf"), float("inf"))


def test_the_audit_flags_an_interval_that_scored_an_unknown_as_zero() -> None:
    cands = [cand("a", 3000.0), cand("b", 4000.0)]
    ranking = run(cands)
    basis = {
        k: {**v, "low": v["value"], "high": v["value"]} for k, v in ranking["order_basis"].items()
    }
    assert audit({**ranking, "order_basis": basis}, cands)["mismatched"] == 2


def test_each_planted_violation_moves_the_evidence() -> None:
    measured = measure_order()
    assert measured["mixed_offers_with_a_total"] > 0
    assert measured["mixed_fraction_ordered_by_id"] == 0
    assert measured["planted"] == {
        "stripped_tie": 1,
        "stripped_incomparable": 1,
        "inversion": 1,
        "unknown_as_zero": 1,
    }
