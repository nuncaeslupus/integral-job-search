"""T244 — fit moves the order, and only fit does.

Pairs are built by holding one offer and varying a single input, so a violation
cannot be argued away as some other signal having moved. The fields varied are
derived from the dataclasses (`fields`), and a guard asserts the variation table
covers exactly those fields, so a field added later fails here until it is varied.
The last section drives the same property through step 9's path, from a store.
"""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path
from typing import Any

import pytest

from integral.cv_store import CVMaster, write_master
from integral.fit import (
    CandidateAbility,
    FitReading,
    OfferDemand,
    _held_seniority,
    abilities_from_store,
    fit_candidates,
    read_fit,
    with_fit,
)
from integral.identity import ProfileStore, create_profile
from integral.profile import ProfileRevision
from integral.rank import FIT_DIMENSIONS, Candidate, RankingError, rank

REV = ProfileRevision(rows=1, sha256="0" * 64)
DIMS = ("remote", *FIT_DIMENSIONS)

ME = CandidateAbility(seniority=0.5, spoken="conversational", written="conversational")
_EMPTY: dict[str, Any] = {"match": [], "missing": [], "used": [], "weak": [], "averse": []}
STACK_OK = {**_EMPTY, "verdict": "match", "match": ["python"]}
STACK_BAD = {**_EMPTY, "verdict": "partial", "match": ["python"], "missing": ["rust", "go"]}
GOOD = OfferDemand(stack=STACK_OK, seniority=0.5, english=0.6)
#: the worse value for each OfferDemand field, keyed by field name
WORSE: dict[str, Any] = {"stack": STACK_BAD, "seniority": 0.8, "english": 1.0}
#: and for each CandidateAbility field
WEAKER: dict[str, Any] = {"seniority": 0.2, "spoken": "basic", "written": "basic"}
STRONG = CandidateAbility(seniority=0.8, spoken="native", written="native")
OFFER_FIELDS = [f.name for f in fields(OfferDemand)]


def cand(
    offer_id: str,
    reading: FitReading,
    salary: float | None = 3000.0,
    unknown: frozenset[str] = frozenset(),
    remote: float = 0.5,
) -> Candidate:
    base = Candidate(
        offer_id=offer_id, salary_per_month=salary, scores={"remote": remote}, unknown=unknown
    )
    return with_fit(base, reading)


def order(
    cands: list[Candidate], dims: tuple[str, ...] = DIMS, weights: Any = None
) -> dict[str, Any]:
    return rank(cands, dimensions=dims, revision=REV, weights=weights, at="t")


def position(ranking: dict[str, Any], offer_id: str) -> float:
    """Dominated offers sit below everything shown."""
    pareto = ranking["pareto"]
    return pareto.index(offer_id) if offer_id in pareto else float("inf")


def silent(demand: OfferDemand, names: tuple[str, ...]) -> OfferDemand:
    return replace(demand, **{n: None for n in names})


def test_the_variation_tables_cover_every_field() -> None:
    assert set(WORSE) == set(OFFER_FIELDS)
    assert set(WEAKER) == {f.name for f in fields(CandidateAbility)}
    assert tuple(f"fit_{f.name}" for f in fields(FitReading)) == FIT_DIMENSIONS


# -- the property, all components known --------------------------------------


@pytest.mark.parametrize("name", OFFER_FIELDS)
@pytest.mark.parametrize("flip", [False, True])
def test_the_better_fitting_offer_never_ranks_below(name: str, flip: bool) -> None:
    better = read_fit(GOOD, ME)
    worse = read_fit(replace(GOOD, **{name: WORSE[name]}), ME)
    pair = [cand("b", better), cand("w", worse)]
    ranking = order(pair[::-1] if flip else pair)
    assert position(ranking, "b") < position(ranking, "w")


@pytest.mark.parametrize("name", OFFER_FIELDS)
def test_the_tiebreak_alone_orders_when_dominance_cannot_act(name: str) -> None:
    # `commute` unknown on both sides blocks dominance, so only the sort can act.
    better = read_fit(GOOD, ME)
    worse = read_fit(replace(GOOD, **{name: WORSE[name]}), ME)
    unknown = frozenset({"commute"})
    a = cand("a", worse, unknown=unknown)
    z = cand("z", better, unknown=unknown)
    ranking = order([a, z], (*DIMS, "commute"))
    assert ranking["pareto"] == ["z", "a"]  # the alphabet would say a, z


# -- the same property when components are silent (F2) -----------------------


DEAD_SETS = [(), ("seniority",), ("english",), ("seniority", "english")]


@pytest.mark.parametrize(
    ("name", "dead"), [(n, d) for n in OFFER_FIELDS for d in DEAD_SETS if n not in d]
)
def test_silence_on_a_shared_component_does_not_hide_the_ones_both_state(
    name: str, dead: tuple[str, ...]
) -> None:
    better = read_fit(silent(GOOD, dead), ME)
    worse = read_fit(silent(replace(GOOD, **{name: WORSE[name]}), dead), ME)
    for flip in (False, True):
        pair = [cand("a-worse", worse), cand("z-better", better)]
        ranking = order(pair[::-1] if flip else pair)
        assert position(ranking, "z-better") < position(ranking, "a-worse")


@pytest.mark.parametrize("name", OFFER_FIELDS)
def test_the_tiebreak_alone_orders_offers_that_share_a_silent_component(name: str) -> None:
    dead = tuple(n for n in OFFER_FIELDS if n != name)[:1]
    better = read_fit(silent(GOOD, dead), ME)
    worse = read_fit(silent(replace(GOOD, **{name: WORSE[name]}), dead), ME)
    unknown = frozenset({"commute"})
    ranking = order(
        [cand("a", worse, unknown=unknown), cand("z", better, unknown=unknown)],
        (*DIMS, "commute"),
    )
    assert ranking["pareto"] == ["z", "a"]


def test_the_motivating_pair_with_english_silent_on_both() -> None:
    """A Staff role naming missing technologies against a mid role the CV covers."""
    staff = read_fit(OfferDemand(stack=STACK_BAD, seniority=0.8), ME)
    mid = read_fit(OfferDemand(stack=STACK_OK, seniority=0.5), ME)
    ranking = order([cand("a-staff", staff), cand("z-mid", mid)])
    assert position(ranking, "z-mid") < position(ranking, "a-staff")


def test_a_profile_missing_one_english_mode_still_compares_stack_and_level() -> None:
    me = replace(ME, written=None)
    better = read_fit(GOOD, me)
    worse = read_fit(replace(GOOD, stack=STACK_BAD, seniority=0.8), me)
    assert better.english is None and worse.english is None
    ranking = order([cand("a-worse", worse), cand("z-better", better)])
    assert position(ranking, "z-better") < position(ranking, "a-worse")


def test_an_offer_worse_on_every_component_both_state_stays_off_the_frontier() -> None:
    # A: pays more, more remote, stack held, silent on seniority. B: Staff, missing stack.
    a = cand("A", read_fit(OfferDemand(stack=STACK_OK, english=0.6), ME), 5000.0, remote=0.9)
    b = cand(
        "B",
        read_fit(OfferDemand(stack=STACK_BAD, seniority=0.8, english=0.6), ME),
        2000.0,
        remote=0.1,
    )
    ranking = order([a, b])
    assert ranking["pareto"] == ["A"]
    assert ranking["dominated"] == {"B": "dominated_by:A"}


def test_a_component_silent_on_one_side_never_creates_a_dominance() -> None:
    # A pays more but is worse on the stack both state; B is silent on seniority.
    a = cand("A", read_fit(OfferDemand(stack=STACK_BAD, seniority=0.5), ME), 5000.0)
    b = cand("B", read_fit(OfferDemand(stack=STACK_OK), ME), 2000.0)
    assert sorted(order([a, b])["pareto"]) == ["A", "B"]


def test_a_known_gap_on_a_component_the_other_side_leaves_silent_is_not_a_win() -> None:
    # A states a seniority gap; B is silent on seniority. B must not be moved above A by it,
    # nor A below: an unknown is neither a match nor a penalty.
    a = cand("a", read_fit(replace(GOOD, seniority=0.8), ME))
    b = cand("b", read_fit(silent(GOOD, ("seniority",)), ME))
    ranking = order([a, b])
    assert ranking["pareto"] == ["a", "b"]


# -- pay is never undone by fit (F4) ------------------------------------------

L2 = {
    "currency": "EUR",
    "part_worths": {"remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0}},
}


def test_pay_still_outranks_fit() -> None:
    paid = cand("paid", read_fit(replace(GOOD, stack=STACK_BAD), ME), salary=5000.0)
    fit = cand("fit", read_fit(GOOD, ME), salary=2000.0)
    assert order([fit, paid])["pareto"] == ["paid", "fit"]  # a trade-off: the candidate's call


def test_pay_outranks_fit_when_totals_tie_at_l2() -> None:
    # Equal totals (3000 + 600*1.0 == 3600 + 600*0.0), different salaries; fit points the other way.
    lower_paid_better_fit = cand("a", read_fit(GOOD, ME), 3000.0, remote=1.0)
    higher_paid_worse_fit = cand(
        "b", read_fit(replace(GOOD, stack=STACK_BAD), ME), 3600.0, remote=0.0
    )
    ranking = order([lower_paid_better_fit, higher_paid_worse_fit], weights=L2)
    assert ranking["level"] == "L2"
    assert ranking["salary_equivalent_total"] == {"a": 3600.0, "b": 3600.0}
    assert ranking["pareto"] == ["b", "a"]


# -- unknown stays unknown ----------------------------------------------------


@pytest.mark.parametrize("name", OFFER_FIELDS)
def test_a_silent_advert_is_unknown_not_a_match(name: str) -> None:
    reading = read_fit(silent(GOOD, (name,)), ME)
    assert getattr(reading, name) is None
    c = cand("s", reading)
    assert f"fit_{name}" in c.unknown and f"fit_{name}" not in c.scores
    # the other two are still read
    assert all(f"fit_{n}" in c.scores for n in OFFER_FIELDS if n != name)


@pytest.mark.parametrize("name", [f.name for f in fields(CandidateAbility)])
def test_a_silent_profile_is_unknown_not_a_match(name: str) -> None:
    reading = read_fit(GOOD, replace(ME, **{name: None}))
    assert None in reading.components().values()


def test_an_empty_stack_reading_is_unknown() -> None:
    nothing = {**_EMPTY, "verdict": "unknown"}
    assert read_fit(replace(GOOD, stack=nothing), ME).stack is None


def test_an_unknown_fit_is_neither_moved_nor_collapsed() -> None:
    perfect = cand("p", read_fit(GOOD, ME))
    quiet = cand("a", read_fit(OfferDemand(), ME))  # silent everywhere
    bad = cand("b", read_fit(replace(GOOD, stack=STACK_BAD), ME))
    ranking = order([quiet, perfect, bad])
    assert ranking["pareto"][0] == "a"  # keeps the slot the alphabet gave it
    assert ranking["unknown_dimensions"]["a"] == sorted(FIT_DIMENSIONS)


def test_fit_is_accounted_exactly_once() -> None:
    c = cand("x", read_fit(GOOD, ME))
    with pytest.raises(RankingError):
        with_fit(c, read_fit(GOOD, ME))


# -- the reading itself -------------------------------------------------------


@pytest.mark.parametrize("name", [f.name for f in fields(CandidateAbility)])
def test_every_candidate_field_moves_the_reading(name: str) -> None:
    demand = OfferDemand(stack=STACK_OK, seniority=0.8, english=1.0)
    base = read_fit(demand, STRONG).components()
    low = read_fit(demand, replace(STRONG, **{name: WEAKER[name]})).components()
    assert sum(v for v in low.values() if v is not None) < sum(
        v for v in base.values() if v is not None
    )


def test_surplus_earns_nothing() -> None:
    assert read_fit(GOOD, STRONG) == read_fit(GOOD, ME)


def test_english_is_limited_by_the_weaker_mode() -> None:
    demand = OfferDemand(stack=STACK_OK, seniority=0.5, english=1.0)
    spoken_only = CandidateAbility(0.5, "native", "basic")
    written_only = CandidateAbility(0.5, "basic", "native")
    assert read_fit(demand, spoken_only) == read_fit(demand, written_only)
    assert (read_fit(demand, spoken_only).english or 0) < 0


def test_a_c1_candidate_meets_the_job_runs_in_english() -> None:
    # `english_demand`'s 1.0 rung is "C1/fluent/native"; `professional` satisfies it.
    assert (
        read_fit(
            replace(GOOD, english=1.0), CandidateAbility(0.5, "professional", "professional")
        ).english
        == 0.0
    )
    assert (
        read_fit(
            replace(GOOD, english=0.6), CandidateAbility(0.5, "conversational", "conversational")
        ).english
        == 0.0
    )
    assert (
        read_fit(replace(GOOD, english=0.6), CandidateAbility(0.5, "basic", "basic")).english or 0
    ) < 0


def test_a_demand_of_none_is_met_by_anyone() -> None:
    assert (
        read_fit(replace(GOOD, english=0.0), CandidateAbility(0.5, "none", "none")).english == 0.0
    )


def _bucketed(**buckets: list[str]) -> dict[str, Any]:
    return {**_EMPTY, "verdict": "partial", **buckets}


def test_which_stack_buckets_count_as_a_shortfall() -> None:
    def stack(**b: list[str]) -> float | None:
        return read_fit(OfferDemand(stack=_bucketed(match=["python"], **b)), ME).stack

    assert stack() == 0.0
    assert stack(missing=["go"]) == -0.5
    assert stack(weak=["go"]) == -0.5  # named, and held too thinly to do the work
    assert stack(used=["go"]) == 0.0  # in the CV without a level: not a gap
    assert stack(averse=["go"]) == 0.0  # a preference, which T10's weights hold, not a lack


def test_the_reading_is_a_shortfall_in_unit_range() -> None:
    worst = read_fit(
        OfferDemand(stack={**STACK_BAD, "match": []}, seniority=0.8, english=1.0),
        CandidateAbility(0.2, "none", "none"),
    ).components()
    assert all(v == -1.0 for v in worst.values())
    assert all(v == 0.0 for v in read_fit(GOOD, ME).components().values())


# -- step 9's path: the store in, a ranking out (F1, F3, F6) ------------------


def _store(tmp_path: Path, master: dict[str, Any]) -> ProfileStore:
    identity = create_profile(tmp_path, "Fit Test", handle="fit-test")
    store = ProfileStore(tmp_path, identity.handle)
    write_master(store, CVMaster.model_validate(master))
    return store


def _offer(
    store: ProfileStore, offer_id: str, title: str, text: str, scores: list[dict[str, Any]]
) -> Candidate:
    store.write_json({"id": offer_id, "title": title, "text": text}, "offers", f"{offer_id}.json")
    store.write_json({"offer_id": offer_id, "scores": scores}, "extractions", f"{offer_id}.json")
    return Candidate(
        offer_id=offer_id, salary_per_month=3000.0, scores={"remote": 0.5}, unknown=frozenset()
    )


def _score(dimension: str, value: float, provenance: str = "rules") -> dict[str, Any]:
    return {
        "dimension": dimension,
        "value": value,
        "spans": [{"start": 0, "end": 1, "quote": "x"}],
        "provenance": provenance,
    }


MASTER = {
    "skills": [{"name": "Python", "level": "expert"}],
    "experience": [
        {"title": "Developer", "organisation": "Old", "start": "2015", "end": "2020"},
        {"title": "Mid-level Engineer", "organisation": "Now", "start": "2020"},
    ],
    "languages": [{"language": "en", "level": "professional"}],
}


def _run(store: ProfileStore, cands: list[Candidate]) -> dict[str, Any]:
    return rank(
        fit_candidates(store, cands),
        dimensions=DIMS,
        revision=REV,
        weights=None,
        at="t",
    )


def test_step_nine_ranks_a_staff_role_with_missing_stack_below_the_mid_role(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        {
            **MASTER,
            "experience": [{"title": "Senior Engineer", "organisation": "X", "start": "2019"}],
        },
    )
    staff = _offer(
        store,
        "a-staff",
        "Staff Engineer",
        "Rust, Go, Kafka, Kubernetes, Terraform.",
        [_score("seniority_expectation", 0.8)],
    )
    mid = _offer(
        store, "z-mid", "Engineer", "We use Python.", [_score("seniority_expectation", 0.5)]
    )
    # last held is senior (0.8): the Staff role is no level gap, so the stack decides
    ranking = _run(store, [staff, mid])
    assert abilities_from_store(store).seniority == 0.8
    assert position(ranking, "z-mid") < position(ranking, "a-staff")
    assert "stack_fit" not in ranking  # fit rode in as axes, not through `stack=`


def test_step_nine_reads_the_level_gap_from_the_last_role_held(tmp_path: Path) -> None:
    store = _store(
        tmp_path,
        {
            **MASTER,
            "experience": [{"title": "Junior Developer", "organisation": "X", "start": "2024"}],
        },
    )
    reach = _offer(store, "a-reach", "Senior", "Python.", [_score("seniority_expectation", 0.8)])
    fits = _offer(store, "z-fits", "Junior", "Python.", [_score("seniority_expectation", 0.2)])
    ranking = _run(store, [reach, fits])
    assert position(ranking, "z-fits") < position(ranking, "a-reach")


def test_step_nine_reads_english_against_the_profile(tmp_path: Path) -> None:
    store = _store(tmp_path, {**MASTER, "languages": [{"language": "en", "level": "basic"}]})
    heavy = _offer(store, "a-heavy", "Dev", "Python.", [_score("english_demand", 1.0)])
    light = _offer(store, "z-light", "Dev", "Python.", [_score("english_demand", 0.0)])
    ranking = _run(store, [heavy, light])
    assert position(ranking, "z-light") < position(ranking, "a-heavy")


def test_step_nine_leaves_a_silent_advert_unknown(tmp_path: Path) -> None:
    store = _store(tmp_path, MASTER)
    quiet = _offer(store, "q", "Dev", "no technology named here", [])
    (fitted,) = fit_candidates(store, [quiet])
    assert fitted.unknown == frozenset(FIT_DIMENSIONS)


def test_a_model_stage_level_is_not_a_statement(tmp_path: Path) -> None:
    """`seniority_expectation`'s own tell reads a plain title as 0.5; that is silence."""
    store = _store(tmp_path, MASTER)
    guessed = _offer(
        store,
        "g",
        "Developer",
        "Python.",
        [_score("seniority_expectation", 0.5, "model"), _score("english_demand", 0.6, "model")],
    )
    (fitted,) = fit_candidates(store, [guessed])
    assert {"fit_seniority", "fit_english"} <= fitted.unknown


def test_an_advert_that_says_english_is_not_required_is_a_demand_of_zero(tmp_path: Path) -> None:
    store = _store(tmp_path, {**MASTER, "languages": [{"language": "en", "level": "none"}]})
    c = _offer(store, "n", "Dev", "Python.", [_score("english_demand", 0.0)])
    (fitted,) = fit_candidates(store, [c])
    assert fitted.scores["fit_english"] == 0.0


def test_a_plain_title_states_no_level() -> None:
    assert _held_seniority("Developer") is None
    assert _held_seniority("Senior Developer") == 0.8
    assert _held_seniority("Desarrollador junior") == 0.2


def test_a_candidate_with_no_dated_history_has_no_held_level(tmp_path: Path) -> None:
    store = _store(tmp_path, {"languages": []})
    assert abilities_from_store(store) == CandidateAbility()
