"""T138 — paying more is a rule, not a weight.

The rule under test, in the task's own words: *where two offers are equal on
every other ranked dimension, the higher-paying one is never ranked below the
lower-paying one.* These tests are written against that sentence, not against
what `rank` happens to do — the regression at the top reproduces the ordering
measured on 2026-09-07, where an offer at 2000 was printed above an otherwise
identical one at 5000.

The audit is deliberately separable from the sort, so most of what follows asks
it about rankings it did not produce: a published order handed to it by name.
A count the construction hands itself can only ever be zero.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.pay_dominance import (
    DEFAULT_EVIDENCE_PATH,
    alike_apart_from_pay,
    comparable_band,
    measure,
    pays_more,
    violations,
    write_evidence,
)
from integral.pay_dominance import (
    _main as main,
)
from integral.profile import ProfileRevision
from integral.rank import Candidate, PayBand, RankingError, rank, require_pay_coherence

DIMENSIONS = ("commute", "mentoring", "remote")
WEIGHTS = {
    "currency": "EUR",
    "part_worths": {
        "commute": {"utility_per_unit": 0.3, "salary_equivalent_per_month": 200.0},
        "mentoring": {"utility_per_unit": 0.15, "salary_equivalent_per_month": 100.0},
        "remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0},
    },
    "negligible": [],
    "separated": False,
    "salary_utility_per_month": 0.0015,
}
REVISION = ProfileRevision(rows=4, sha256="b" * 64)


def _offer(
    offer_id: str,
    salary: float | None,
    *,
    pay: PayBand | None = None,
    silent: str = "mentoring",
    **scores: float,
) -> Candidate:
    """One offer. `silent` is the dimension the advert says nothing about."""
    settled = {name: scores[name] for name in DIMENSIONS if name in scores}
    return Candidate(
        offer_id=offer_id,
        salary_per_month=salary,
        scores=settled,
        unknown=frozenset(name for name in DIMENSIONS if name not in settled),
        pay=pay,
    )


def _rank(*candidates: Candidate, weights: object = WEIGHTS) -> dict[str, object]:
    return rank(
        list(candidates),
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=weights,  # type: ignore[arg-type]
        at="2026-09-07T00:00:00Z",
    )


# --------------------------------------------------------------------------
# The rule itself.
# --------------------------------------------------------------------------


def test_the_higher_paying_of_two_alike_offers_is_not_ranked_below() -> None:
    """The measured defect: both totals absent, and the tie broke on the id.

    `mentoring` is priced and unsettled on both, so neither offer gets a
    salary-equivalent total; before T138 the sort fell through to `offer_id`
    and printed `aa-poor` first.
    """
    rich = _offer("zz-rich", 5000.0, commute=0.2, remote=0.6)
    poor = _offer("aa-poor", 2000.0, commute=0.2, remote=0.6)

    ranking = _rank(rich, poor)

    assert ranking["salary_equivalent_total"] == {}, "the case only bites without totals"
    assert ranking["pareto"] == ["zz-rich", "aa-poor"]
    assert violations(ranking, [rich, poor]) == []


def test_the_audit_reads_the_published_order_and_can_contradict_it() -> None:
    """Hand it the inversion by name and it has to say so."""
    rich = _offer("zz-rich", 5000.0, commute=0.2, remote=0.6)
    poor = _offer("aa-poor", 2000.0, commute=0.2, remote=0.6)
    ranking = _rank(rich, poor)

    inverted = {**ranking, "pareto": ["aa-poor", "zz-rich"]}
    found = violations(inverted, [rich, poor])

    assert [entry["kind"] for entry in found] == ["printed_below"]
    assert found[0]["higher_paying"] == "zz-rich"


def test_a_higher_paying_offer_collapsed_under_an_alike_one_is_a_violation() -> None:
    """Not printed lower — not printed at all. The same failure, at its worst."""
    rich = _offer("zz-rich", 5000.0, commute=0.2, remote=0.6)
    poor = _offer("aa-poor", 2000.0, commute=0.2, remote=0.6)
    ranking = _rank(rich, poor)

    buried = {
        **ranking,
        "pareto": ["aa-poor"],
        "dominated": {"zz-rich": "dominated_by:aa-poor"},
    }

    assert [entry["kind"] for entry in violations(buried, [rich, poor])] == ["collapsed_under"]


def test_offers_differing_on_another_dimension_are_not_this_rule_s_business() -> None:
    """Paying more does not license overruling a dimension the candidate priced."""
    rich = _offer("zz-rich", 5000.0, commute=0.2, remote=-1.0)
    poor = _offer("aa-poor", 2000.0, commute=0.2, remote=0.6)
    inverted = {**_rank(rich, poor), "pareto": ["aa-poor", "zz-rich"]}

    assert not alike_apart_from_pay(rich, poor, DIMENSIONS)
    assert violations(inverted, [rich, poor]) == []


def test_a_scored_dimension_and_a_silent_one_are_not_alike() -> None:
    """Unknown is not neutral, so the rule declines the pair rather than guess."""
    scored = _offer("zz-scored", 5000.0, commute=0.2, remote=0.6, mentoring=0.5)
    silent = _offer("aa-silent", 2000.0, commute=0.2, remote=0.6)

    assert not alike_apart_from_pay(scored, silent, DIMENSIONS)


# --------------------------------------------------------------------------
# Decided case 1 — one side publishes no band.
# --------------------------------------------------------------------------


def test_an_unpublished_salary_is_never_read_as_a_low_one() -> None:
    """No claim in either direction, and specifically not "the silent one pays less"."""
    silent = _offer("zz-silent", None, commute=0.2, remote=0.6)
    published = _offer("aa-3000", 3000.0, commute=0.2, remote=0.6)

    assert comparable_band(silent, "EUR") is None
    assert not pays_more(published, silent, "EUR")
    assert not pays_more(silent, published, "EUR")


def test_a_pair_with_an_unpublished_side_is_clean_in_either_order() -> None:
    """Which is what "incomparable" has to mean if it means anything."""
    silent = _offer("zz-silent", None, commute=0.2, remote=0.6)
    published = _offer("aa-3000", 3000.0, commute=0.2, remote=0.6)
    ranking = _rank(silent, published)

    for order in (["aa-3000", "zz-silent"], ["zz-silent", "aa-3000"]):
        assert violations({**ranking, "pareto": order}, [silent, published]) == []


# --------------------------------------------------------------------------
# Decided case 2 — different currencies, or a range against a point.
# --------------------------------------------------------------------------


def test_bands_in_different_currencies_are_incomparable() -> None:
    """No rate with a date and a source lives in this repository."""
    dollars = _offer("zz-usd", None, pay=PayBand(4000.0, 4200.0, "USD"), commute=0.2, remote=0.6)
    euros = _offer("aa-eur", 3100.0, pay=PayBand(3000.0, 3200.0, "EUR"), commute=0.2, remote=0.6)

    assert comparable_band(dollars, "EUR") is None
    assert not pays_more(dollars, euros, "EUR")
    assert not pays_more(euros, dollars, "EUR")


def test_a_point_is_the_band_whose_ends_coincide() -> None:
    """So a range against a point is the ordinary comparison, not a special one."""
    point = _offer("aa-point", 3000.0, commute=0.2, remote=0.6)

    assert comparable_band(point, "EUR") == (3000.0, 3000.0)


def test_overlapping_bands_make_no_claim_in_either_direction() -> None:
    """€3.000-3.900 against €3.500: each pays more under some reading of the other."""
    span = _offer("zz-span", 3400.0, pay=PayBand(3000.0, 3900.0, "EUR"), commute=0.2, remote=0.6)
    point = _offer("aa-point", 3500.0, pay=PayBand(3500.0, 3500.0, "EUR"), commute=0.2, remote=0.6)

    assert not pays_more(span, point, "EUR")
    assert not pays_more(point, span, "EUR")


def test_disjoint_bands_do_make_a_claim() -> None:
    """Otherwise "incomparable" would be a way of never deciding anything."""
    high = _offer("zz-high", 4200.0, pay=PayBand(4000.0, 4500.0, "EUR"), commute=0.2, remote=0.6)
    low = _offer("aa-low", 3100.0, pay=PayBand(3000.0, 3200.0, "EUR"), commute=0.2, remote=0.6)

    assert pays_more(high, low, "EUR")
    assert not pays_more(low, high, "EUR")
    assert _rank(high, low)["pareto"] == ["zz-high", "aa-low"]


def test_a_band_touching_another_at_one_end_is_not_a_claim() -> None:
    """`a.low == b.high` leaves a reading in which they pay the same."""
    upper = _offer("zz-upper", 3500.0, pay=PayBand(3200.0, 3800.0, "EUR"), commute=0.2, remote=0.6)
    lower = _offer("aa-lower", 3000.0, pay=PayBand(2800.0, 3200.0, "EUR"), commute=0.2, remote=0.6)

    assert not pays_more(upper, lower, "EUR")


# --------------------------------------------------------------------------
# What keeps the rule and the sort agreeing.
# --------------------------------------------------------------------------


def test_a_band_in_the_ranking_currency_must_carry_a_point_reading() -> None:
    """Without one the sort would rank a published band as if it were unpaid."""
    banded = _offer("zz-banded", None, pay=PayBand(4000.0, 4200.0, "EUR"), commute=0.2, remote=0.6)

    with pytest.raises(RankingError, match="no point reading"):
        _rank(banded)


def test_a_point_outside_its_own_band_is_refused() -> None:
    """The order would otherwise run on a number the advert contradicts."""
    crooked = _offer(
        "zz-crooked", 9000.0, pay=PayBand(3000.0, 3200.0, "EUR"), commute=0.2, remote=0.6
    )

    with pytest.raises(RankingError, match="contradict the advert"):
        _rank(crooked)


def test_a_foreign_band_is_left_alone_by_the_coherence_check() -> None:
    """It constrains nothing here, so it is not required to carry a point."""
    foreign = _offer("zz-usd", None, pay=PayBand(4000.0, 4200.0, "USD"), commute=0.2, remote=0.6)

    require_pay_coherence([foreign], "EUR")


def test_a_band_that_ends_below_where_it_starts_is_refused() -> None:
    with pytest.raises(RankingError, match="cannot end below"):
        PayBand(4000.0, 3000.0, "EUR")


def test_a_currency_that_is_not_an_iso_code_is_refused() -> None:
    with pytest.raises(RankingError, match="ISO 4217"):
        PayBand(3000.0, 4000.0, "eur")


def test_the_rule_holds_without_weights_too() -> None:
    """At L1 the order is the salary, so the rule is already the primary key."""
    rich = _offer("zz-rich", 5000.0, commute=0.2, remote=0.6)
    poor = _offer("aa-poor", 2000.0, commute=0.2, remote=0.6)
    ranking = _rank(rich, poor, weights=None)

    assert ranking["level"] == "L1"
    assert ranking["pareto"] == ["zz-rich", "aa-poor"]


# --------------------------------------------------------------------------
# The gate.
# --------------------------------------------------------------------------


def test_the_measurement_reports_no_violation_and_a_rule_that_fired() -> None:
    measured = measure()

    assert measured["pay_dominance_violations"] == 0
    assert measured["pairs_where_pay_dominance_is_claimed"] > 0
    assert (
        measured["claiming_pairs_broken_when_reversed"]
        == measured["pairs_where_pay_dominance_is_claimed"]
    ), "a rule that cannot be broken is not being checked"
    assert measured["absent_bands_read_as_zero"] == 0
    assert {row["case"] for row in measured["decided_cases"]} == {
        "one_side_publishes_no_band",
        "different_currencies_or_a_range_against_a_point",
    }


def test_every_incomparable_pair_is_clean_in_both_orders() -> None:
    for row in measure()["pairs"]:
        if row["pay_dominance_claimed"]:
            continue
        assert row["violations"] == 0
        assert row["violations_when_the_order_is_reversed"] == 0, row["case"]


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    assert json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")) == measure()


def test_main_writes_the_evidence_and_passes(tmp_path: Path) -> None:
    evidence = tmp_path / "T138.json"

    assert main([str(evidence)]) == 0

    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written["pay_dominance_violations"] == 0
    assert written["gate_status"] == "measured"


def test_write_evidence_returns_what_it_wrote(tmp_path: Path) -> None:
    evidence = tmp_path / "T138.json"
    measured = write_evidence(evidence)

    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
