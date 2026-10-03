"""T246 — pay is converted into the weights' currency before the sort, or refused.

Each case is derived from the task text: one dated conversion, refusal when no
rate exists, a band left out of `salary` re-read from the advert, and an offer
with no published pay ordered among the unpaid and said to be. Expected figures
are worked by hand beside each case, never read off the code.
"""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, get_args

import pytest

from integral.extraction import OfferExtraction
from integral.offers import Offer, Salary, SalaryPeriod, compute_offer_id
from integral.pay_normalise import (
    _PER_MONTH,
    DEFAULT_EVIDENCE_PATH,
    DatedRate,
    PayNormaliseError,
    RateTable,
    annotate,
    candidate_for,
    measure,
    read_pay,
    write_evidence,
)
from integral.profile import ProfileRevision
from integral.rank import Candidate, PayBand, RankingError, rank, require_pay_coherence

DIMS = ("remote",)
WEIGHTS = {
    "currency": "EUR",
    "part_worths": {"remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0}},
}
REV = ProfileRevision(rows=1, sha256="0" * 64)
USD = DatedRate("USD", 0.9, "2026-10-01", "a rate passed in by the test")
TABLE = RateTable("EUR", (USD,))


def offer(label: str, salary: Salary | None, text: str = "A role.") -> Offer:
    body = f"{label}. {text}"
    return Offer(id=compute_offer_id(body), source="t", text=body, salary=salary)


def sal(low: float, high: float, currency: str | None, period: Any) -> Salary:
    return Salary(min=low, max=high, currency=currency, period=period, stated=True)


def extraction(o: Offer) -> OfferExtraction:
    return OfferExtraction(offer_id=o.id, language="en", unsettled=list(DIMS))


def ranked(
    offers: list[Offer], table: RateTable = TABLE
) -> tuple[dict[str, Any], list[Candidate], list[Any]]:
    pairs = [candidate_for(o, extraction(o), dimensions=DIMS, table=table) for o in offers]
    candidates = [c for c, _ in pairs]
    result = rank(
        candidates, dimensions=DIMS, revision=REV, weights=WEIGHTS, at="t", currency=table.target
    )
    return result, candidates, [r for _, r in pairs]


def test_a_usd_band_is_converted_before_it_orders() -> None:
    """40000 USD/yr is 3333.33 USD/month; at 0.9 that is 3000 EUR, below 3100.

    Unconverted, 3333.33 would outrank 3100 — the defect the task reports.
    """
    usd = offer("usd", sal(40000, 40000, "USD", "year"))
    eur = offer("eur", sal(3100, 3100, "EUR", "month"))
    result, candidates, _ = ranked([usd, eur])
    by_id = {c.offer_id: c for c in candidates}
    assert by_id[usd.id].salary_per_month == pytest.approx(3000.0)
    band = by_id[usd.id].pay
    assert band is not None and band.currency == "EUR"
    assert band.low == pytest.approx(3000.0)
    assert result["pareto"] == [eur.id, usd.id]


def test_the_conversion_is_dated_and_says_so() -> None:
    reading = read_pay(offer("usd", sal(40000, 40000, "USD", "year")), TABLE)
    assert reading.rate == USD
    assert "2026-10-01" in reading.note and "a rate passed in by the test" in reading.note


def test_a_band_is_converted_end_to_end_and_its_point_lies_inside_it() -> None:
    reading = read_pay(offer("band", sal(60000, 84000, "USD", "year")), TABLE)
    assert reading.band is not None and reading.per_month is not None
    assert reading.band.low == pytest.approx(4500.0)
    assert reading.band.high == pytest.approx(6300.0)
    assert reading.band.low <= reading.per_month <= reading.band.high


def test_every_three_letter_code_is_refused_unless_it_is_the_target_or_has_a_dated_rate() -> None:
    """The rule, closed: no list of bad currencies; every code over ten letters is tried."""
    base = offer("any", None)
    accepted = set()
    for letters in itertools.product("ERUSDGBPXZ", repeat=3):
        code = "".join(letters)
        o = base.model_copy(update={"salary": sal(1000, 1000, code, "month")})
        try:
            read_pay(o, TABLE)
        except PayNormaliseError:
            continue
        accepted.add(code)
    assert accepted == {TABLE.target} | {rate.currency for rate in TABLE.rates}


def test_a_rate_must_carry_a_date_a_source_and_a_positive_figure() -> None:
    bad_rates = (
        ("USD", 0.9, "", "src"),
        ("USD", 0.9, "yesterday", "src"),
        ("USD", 0.9, "2026-10-01", "  "),
        ("USD", 0.0, "2026-10-01", "src"),
        ("USD", float("nan"), "2026-10-01", "src"),
        ("usd", 0.9, "2026-10-01", "src"),
    )
    for args in bad_rates:
        with pytest.raises(PayNormaliseError):
            DatedRate(*args)
    with pytest.raises(PayNormaliseError):
        RateTable("EUR", (USD, USD))


def test_a_period_converts_only_where_it_has_a_calendar_factor() -> None:
    periods = get_args(SalaryPeriod)
    for period in periods:
        o = offer("p", sal(1200, 1200, "EUR", period))
        if period in _PER_MONTH:
            assert read_pay(o, TABLE).per_month == pytest.approx(1200 * _PER_MONTH[period])
        else:
            with pytest.raises(PayNormaliseError):
                read_pay(o, TABLE)
    assert {"year", "month", "week"} <= set(_PER_MONTH) <= set(periods)
    with pytest.raises(PayNormaliseError):
        read_pay(offer("n", sal(1200, 1200, "EUR", None)), TABLE)


def test_a_figure_with_no_currency_is_refused() -> None:
    with pytest.raises(PayNormaliseError):
        read_pay(offer("c", sal(1200, 1200, None, "month")), TABLE)


def test_a_week_is_52_over_12_months() -> None:
    assert read_pay(offer("w", sal(600, 600, "EUR", "week")), TABLE).per_month == pytest.approx(
        2600.0
    )


def test_a_band_the_source_left_empty_is_read_from_the_advert() -> None:
    """72,000 USD a year is 6000 USD a month, 5400 EUR at 0.9."""
    o = offer("text", None, "Salary: USD 72,000 gross per year. Remote.")
    reading = read_pay(o, TABLE)
    assert reading.basis == "read_from_text"
    assert reading.per_month == pytest.approx(5400.0)
    assert "advert text" in reading.note


def test_a_currency_only_salary_is_still_silence_and_the_text_is_read() -> None:
    o = offer("cur", Salary(currency="USD", stated=True), "Salary: USD 72,000 per year.")
    assert read_pay(o, TABLE).basis == "read_from_text"


def test_a_text_band_in_a_currency_with_no_rate_is_refused_not_dropped() -> None:
    o = offer("gbp", None, "Salary: GBP 40,000 gross per year.")
    with pytest.raises(PayNormaliseError):
        read_pay(o, TABLE)


def test_an_advert_with_no_band_is_unpaid_and_says_so() -> None:
    reading = read_pay(offer("silent", None, "We are a friendly team."), TABLE)
    assert (reading.basis, reading.per_month, reading.band) == ("unpaid", None, None)
    assert "unpaid" in reading.note and "not estimated" in reading.note


def test_an_estimate_is_never_ranked_as_a_published_figure() -> None:
    estimated = Salary(min=3000, max=4000, currency="EUR", period="month", stated=False)
    assert read_pay(offer("est", estimated), TABLE).basis == "unpaid"


def test_the_ranking_names_its_unpaid_offers_and_how_each_pay_arrived() -> None:
    paid = offer("paid", sal(40000, 40000, "USD", "year"))
    silent = offer("silent", None, "Nothing about money.")
    result, _, readings = ranked([paid, silent])
    shown = annotate(result, readings, TABLE)
    assert shown["unpaid_offers"] == [silent.id]
    assert shown["pay"][paid.id]["converted_from"] == "USD"
    assert shown["pay"][paid.id]["rate"]["as_of"] == "2026-10-01"
    assert shown["pay"][silent.id]["basis"] == "unpaid"


def test_annotate_refuses_a_ranking_in_another_currency() -> None:
    with pytest.raises(PayNormaliseError):
        annotate({"currency": "USD", "pareto": [], "dominated": {}}, [], TABLE)


def test_rank_refuses_a_point_beside_a_band_in_another_currency() -> None:
    bare = Candidate("a", 3000.0, {}, frozenset(DIMS), pay=PayBand(3000, 3000, "USD"))
    with pytest.raises(RankingError, match="convert it first"):
        require_pay_coherence([bare], "EUR")
    # A foreign band with no point is silent to the sort: left alone, as before.
    require_pay_coherence([Candidate("b", None, {}, frozenset(DIMS), pay=bare.pay)], "EUR")


def test_the_measurement_is_zero_and_rises_when_conversion_is_planted_away() -> None:
    measured = measure()
    assert measured["unconverted_pay_reaching_rank"] == 0
    assert measured["offers_checked"] >= 5
    assert measured["unconverted_detected_when_planted"] == 1


def test_the_committed_evidence_is_what_the_code_measures_now(tmp_path: Path) -> None:
    written = write_evidence(tmp_path / "T246.json")
    committed = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == written == measure()


def test_rank_refuses_a_bare_point_whatever_door_it_came_through() -> None:
    """The rule is on what reaches `rank`: with a known currency, a point needs its unit."""
    bare = Candidate("a", 3333.0, {}, frozenset(DIMS))
    for pay in (None, PayBand(3333.0, 3333.0, "USD")):
        with pytest.raises(RankingError, match="convert it first"):
            rank(
                [replace(bare, pay=pay)],
                dimensions=DIMS,
                revision=REV,
                weights=WEIGHTS,
                at="t",
                currency="EUR",
            )
    # The same point beside a band in the ranking's currency is accepted.
    rank(
        [replace(bare, pay=PayBand(3333.0, 3333.0, "EUR"))],
        dimensions=DIMS,
        revision=REV,
        weights=WEIGHTS,
        at="t",
        currency="EUR",
    )


def test_a_non_finite_or_negative_stated_figure_is_refused() -> None:
    for bad in (float("nan"), float("inf"), float("-inf"), -5.0):
        with pytest.raises(PayNormaliseError):
            read_pay(offer("bad", sal(bad, bad, "EUR", "month")), TABLE)
        with pytest.raises(PayNormaliseError):
            read_pay(offer("bad", sal(1000, bad, "EUR", "month")), TABLE)


def test_the_point_of_a_band_is_its_midpoint() -> None:
    """60000-84000 USD a year is 4500-6300 EUR a month, whose midpoint is 5400."""
    reading = read_pay(offer("mid", sal(60000, 84000, "USD", "year")), TABLE)
    assert reading.per_month == pytest.approx(5400.0)


def test_the_audit_compares_the_dominated_as_well_as_the_frontier() -> None:
    from integral.pay_normalise import _audit

    wrong, compared = _audit(TABLE, settled=0.5)
    assert (wrong, compared) == (0, 5)
    # A wrong rate is caught across both populations, not only the frontier.
    bad = RateTable("EUR", (DatedRate("USD", 0.5, "2026-10-01", "planted"),))
    wrong_bad, compared_bad = _audit(bad, settled=0.5)
    assert compared_bad == 5 and wrong_bad == 3
    measured = measure()
    assert measured["offers_checked"] == 10
