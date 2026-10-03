"""T244 — fit moves the order, and only fit does.

Pairs are built by holding one offer and varying a single input, so a violation
cannot be argued away as some other signal having moved. The fields varied are
derived from the dataclasses (`fields`), and a guard asserts the variation table
covers exactly those fields, so a field added later fails here until it is varied.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

import pytest

from integral.fit import (
    FIT,
    CandidateAbility,
    FitReading,
    OfferDemand,
    read_fit,
    with_fit,
)
from integral.profile import ProfileRevision
from integral.rank import Candidate, RankingError, rank

REV = ProfileRevision(rows=1, sha256="0" * 64)
DIMS = ("remote", FIT)

ME = CandidateAbility(seniority=0.5, spoken="professional", written="professional")
_EMPTY: dict[str, Any] = {"match": [], "missing": [], "used": [], "weak": [], "averse": []}
STACK_OK = {**_EMPTY, "verdict": "match", "match": ["python"]}
STACK_BAD = {**_EMPTY, "verdict": "partial", "match": ["python"], "missing": ["rust", "go"]}
GOOD = OfferDemand(stack=STACK_OK, seniority=0.5, english=0.6)
#: the worse value for each OfferDemand field, keyed by field name
WORSE: dict[str, Any] = {"stack": STACK_BAD, "seniority": 0.8, "english": 1.0}
#: and for each CandidateAbility field
WEAKER: dict[str, Any] = {"seniority": 0.2, "spoken": "basic", "written": "basic"}
STRONG = CandidateAbility(seniority=0.8, spoken="native", written="native")


def cand(
    offer_id: str,
    reading: FitReading,
    salary: float | None = 3000.0,
    unknown: frozenset[str] = frozenset(),
) -> Candidate:
    base = Candidate(
        offer_id=offer_id,
        salary_per_month=salary,
        scores={"remote": 0.5},
        unknown=unknown,
    )
    return with_fit(base, reading)


def order(cands: list[Candidate], dims: tuple[str, ...] = DIMS) -> dict[str, Any]:
    return rank(cands, dimensions=dims, revision=REV, weights=None, at="t")


def position(ranking: dict[str, Any], offer_id: str) -> float:
    """Dominated offers sit below everything shown."""
    pareto = ranking["pareto"]
    return pareto.index(offer_id) if offer_id in pareto else float("inf")


def test_the_variation_tables_cover_every_field() -> None:
    assert set(WORSE) == {f.name for f in fields(OfferDemand)}
    assert set(WEAKER) == {f.name for f in fields(CandidateAbility)}


@pytest.mark.parametrize("name", [f.name for f in fields(OfferDemand)])
@pytest.mark.parametrize("flip", [False, True])
def test_the_better_fitting_offer_never_ranks_below(name: str, flip: bool) -> None:
    better = read_fit(GOOD, ME)
    worse = read_fit(replace(GOOD, **{name: WORSE[name]}), ME)
    assert better.score is not None and worse.score is not None
    assert better.score > worse.score
    pair = [cand("b", better), cand("w", worse)]
    ranking = order(pair[::-1] if flip else pair)
    assert position(ranking, "b") < position(ranking, "w")


@pytest.mark.parametrize("name", [f.name for f in fields(OfferDemand)])
def test_the_tiebreak_alone_orders_when_dominance_cannot_act(name: str) -> None:
    # `commute` unknown on both sides blocks dominance, so only the sort can act.
    better = read_fit(GOOD, ME)
    worse = read_fit(replace(GOOD, **{name: WORSE[name]}), ME)
    unknown = frozenset({"commute"})
    a = cand("a", worse, unknown=unknown)
    z = cand("z", better, unknown=unknown)
    ranking = order([a, z], (*DIMS, "commute"))
    assert ranking["pareto"] == ["z", "a"]  # the alphabet would say a, z


@pytest.mark.parametrize("name", [f.name for f in fields(CandidateAbility)])
def test_every_candidate_field_moves_the_reading(name: str) -> None:
    demand = OfferDemand(stack=STACK_OK, seniority=0.8, english=1.0)
    base = read_fit(demand, STRONG)
    low = read_fit(demand, replace(STRONG, **{name: WEAKER[name]}))
    assert base.score is not None and low.score is not None
    assert low.score < base.score


def test_surplus_earns_nothing() -> None:
    assert read_fit(GOOD, STRONG) == read_fit(GOOD, ME)


def test_english_is_limited_by_the_weaker_mode() -> None:
    demand = OfferDemand(stack=STACK_OK, seniority=0.5, english=1.0)
    spoken_only = CandidateAbility(0.5, "native", "basic")
    written_only = CandidateAbility(0.5, "basic", "native")
    assert read_fit(demand, spoken_only) == read_fit(demand, written_only)
    assert (read_fit(demand, spoken_only).english or 0) < 0


@pytest.mark.parametrize("name", [f.name for f in fields(OfferDemand)])
def test_a_silent_advert_is_unknown_not_a_match(name: str) -> None:
    silent = read_fit(replace(GOOD, **{name: None}), ME)
    assert getattr(silent, name) is None
    assert silent.score is None
    c = cand("s", silent)
    assert FIT in c.unknown and FIT not in c.scores


@pytest.mark.parametrize("name", [f.name for f in fields(CandidateAbility)])
def test_a_silent_profile_is_unknown_not_a_match(name: str) -> None:
    assert read_fit(GOOD, replace(ME, **{name: None})).score is None


def test_an_empty_stack_reading_is_unknown() -> None:
    nothing = {**_EMPTY, "verdict": "unknown"}
    assert read_fit(replace(GOOD, stack=nothing), ME).stack is None


def test_an_unknown_fit_is_neither_moved_nor_collapsed() -> None:
    perfect = cand("p", read_fit(GOOD, ME))
    silent = cand("a", read_fit(replace(GOOD, seniority=None), ME))
    bad = cand("b", read_fit(replace(GOOD, stack=STACK_BAD), ME))
    ranking = order([silent, perfect, bad])
    assert "a" in ranking["pareto"]  # incomparable, so not dominated by `p`
    assert ranking["unknown_dimensions"]["a"] == [FIT]
    assert ranking["pareto"][0] == "a"  # keeps the slot the alphabet gave it


def test_pay_still_outranks_fit() -> None:
    paid = cand("paid", read_fit(replace(GOOD, stack=STACK_BAD), ME), salary=5000.0)
    fit = cand("fit", read_fit(GOOD, ME), salary=2000.0)
    ranking = order([fit, paid])
    assert ranking["pareto"] == ["paid", "fit"]  # a trade-off: the candidate's call


def test_fit_is_accounted_exactly_once() -> None:
    c = cand("x", read_fit(GOOD, ME))
    with pytest.raises(RankingError):
        with_fit(c, read_fit(GOOD, ME))


def test_the_reading_is_a_shortfall_in_unit_range() -> None:
    worst = read_fit(
        OfferDemand(stack={**STACK_BAD, "match": []}, seniority=0.8, english=1.0),
        CandidateAbility(0.2, "none", "none"),
    )
    assert worst.score == -1.0
    assert read_fit(GOOD, ME).score == 0.0


@pytest.mark.parametrize("name", [f.name for f in fields(OfferDemand)])
def test_improving_one_component_helps_whatever_the_others_are(name: str) -> None:
    # A `min` would tie these: the weakest component is some other one.
    all_worse = OfferDemand(**WORSE)
    worse = read_fit(all_worse, ME)
    better = read_fit(replace(all_worse, **{name: getattr(GOOD, name)}), ME)
    assert better.score is not None and worse.score is not None
    assert better.score > worse.score
