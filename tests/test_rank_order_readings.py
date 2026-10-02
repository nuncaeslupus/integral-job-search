"""T242 — an order when no total exists, ties reported as ties, a named set."""

from __future__ import annotations

from typing import Any

import pytest

from integral.profile import ProfileRevision
from integral.rank import Candidate, RankingError, ordering_defects, rank, rank_named

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


def test_unknown_everywhere_is_ordered_by_salary_not_hash() -> None:
    # ids chosen so the alphabet order is the opposite of the pay order
    ranking = run([cand("a", 3000.0), cand("b", 4000.0), cand("c", 3500.0)])
    assert ranking["salary_equivalent_total"] == {}  # unknown stays unknown
    assert ranking["pareto"] == ["b", "c", "a"]
    assert {o: v["reading"] for o, v in ranking["order_basis"].items()} == {
        "a": "salary",
        "b": "salary",
        "c": "salary",
    }
    assert ranking["order_basis"]["a"]["unknown"] == ["commute", "remote"]
    assert ranking["ties"] == []
    assert ordering_defects(ranking)["offers_ordered_by_id"] == 0


def test_equal_salaries_and_silent_offers_are_reported_as_ties() -> None:
    ranking = run([cand("a", 3000.0), cand("b", 3000.0), cand("c", None), cand("d", None)])
    ties = {tie["reading"]: tie["offer_ids"] for tie in ranking["ties"]}
    assert ties == {"salary": ["a", "b"], "none": ["c", "d"]}
    assert ranking["unordered"] == ["c", "d"]
    assert ordering_defects(ranking)["offers_ordered_by_id"] == 0


def test_a_total_is_labelled_total_and_precedes_salary_only_offers() -> None:
    full = cand("z", 2000.0, remote=1.0, commute=0.0)
    ranking = run([cand("a", 9000.0), full])
    assert ranking["pareto"][0] == "z"
    assert ranking["order_basis"]["z"]["reading"] == "total"
    assert ranking["order_basis"]["a"]["reading"] == "salary"


def test_audit_rises_on_an_unreported_tie_and_an_inversion() -> None:
    ranking = run([cand("a", 3000.0), cand("b", 3000.0), cand("c", 1000.0)])
    assert ordering_defects({**ranking, "ties": []})["unreported_ties"] == 2
    swapped = {**ranking, "pareto": ["c", "a", "b"]}
    assert ordering_defects(swapped)["inversions"] == 3


def test_rank_named_ranks_only_the_named_set_and_rejects_strangers() -> None:
    cands = [cand("a", 1000.0), cand("b", 2000.0), cand("c", 3000.0)]
    kw: dict[str, Any] = {"dimensions": DIMS, "revision": REV, "weights": WEIGHTS, "at": "t"}
    assert rank_named(cands, ["a", "b"], **kw)["pareto"] == ["b", "a"]
    with pytest.raises(RankingError, match="nope"):
        rank_named(cands, ["a", "nope"], **kw)
