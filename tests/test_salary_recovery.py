"""T92 — a silent advert is not dropped until somebody has looked for the figure."""

from __future__ import annotations

import pytest

from integral.offers import Offer, Salary, compute_offer_id
from integral.presentation import ESTIMATED_MARKER, _salary
from integral.salary_recovery import (
    _IMPOSSIBLE_BANDS,
    MINIMUM_CORPUS_ADS,
    MINIMUM_WORDING_CASES,
    ROUTES,
    WORDING_CASES,
    Recovered,
    SalaryRecoveryError,
    applied,
    band_in_text,
    house_estimate_bands,
    measure,
    recover,
    recover_all,
)

# The same advert, near-identically worded, as two boards publish it. Long
# enough for `dedup.find_duplicates` to score them as the same ad.
_BODY = (
    "Data engineer in Barcelona. You will own the ingestion pipeline that feeds "
    "our analytics platform, working in Python and dbt against a Postgres "
    "warehouse. We are looking for someone comfortable with schema design, with "
    "orchestration, and with the parts of the job nobody puts in an advert. "
    "Hybrid, two days a week in the office near Plaça Catalunya."
)


def _offer(source: str, text: str, salary: Salary | None = None) -> Offer:
    return Offer(id=compute_offer_id(text), source=source, text=text, salary=salary)


def test_a_duplicate_that_states_a_band_supplies_the_silent_copy() -> None:
    stated = Salary(min=42000, max=52000, currency="EUR", period="year", stated=True)
    donor = _offer("employerboard", _BODY + " Salary: 42.000 € - 52.000 € brutos anuales.", stated)
    silent = _offer("aggregator", _BODY + " Apply through our portal for more information.")

    report = recover_all([donor, silent])

    found = report.recovered[silent.id]
    assert found.route == "duplicate"
    assert found.donor_id == donor.id
    assert found.salary == stated
    # The employer stated it; republishing it on another board does not make it
    # an estimate, and demoting it would hide a real figure behind a caveat.
    assert found.salary.stated is True
    assert "employerboard" in found.basis
    assert silent.id not in report.dropped


def test_a_detail_route_is_read_before_a_silent_offer_is_dropped() -> None:
    silent = _offer("board", _BODY + " See the full listing for the conditions.")
    read: list[str] = []

    def detail(offer: Offer) -> str:
        read.append(offer.id)
        return "Otros detalles. Salario: 30.000 € - 36.000 € Bruto/año. Contrato indefinido."

    found, attempted = recover(silent, detail_reader=detail)

    assert read == [silent.id], "the detail route was never read"
    assert attempted == ("advert_text", "duplicate", "detail_page")
    assert found is not None
    assert found.route == "detail_page"
    assert found.salary == Salary(min=30000, max=36000, currency="EUR", period="year", stated=True)


def test_an_estimate_never_reads_as_stated() -> None:
    """The fabrication guard: an estimator that claims the employer said it is
    overruled, and the card marks the figure."""
    silent = _offer("board", _BODY + " Compensation is discussed at the first interview.")

    def liar(_: Offer) -> tuple[Salary, str]:
        return (
            Salary(min=48000, max=58000, currency="EUR", period="year", stated=True),
            "from the range this role and level pays on comparable adverts",
        )

    found, attempted = recover(silent, estimator=liar)

    assert found is not None
    assert found.route == "estimate"
    assert found.salary.stated is False
    assert attempted == (*ROUTES[:2], "estimate")
    assert ESTIMATED_MARKER in _salary(applied(silent, found))

    # And it cannot be constructed the other way round either.
    with pytest.raises(SalaryRecoveryError):
        Recovered(
            Salary(min=48000, currency="EUR", period="year", stated=True), "estimate", "a guess"
        )


def test_an_estimate_carries_its_basis() -> None:
    silent = _offer("board", _BODY + " Pay is competitive for the market.")

    def estimator(_: Offer) -> tuple[Salary, str]:
        return (
            Salary(min=45000, currency="EUR", period="year", stated=False),
            "Ejemplo SL's three other adverts this year pay 44-47k for this level",
        )

    found, _attempted = recover(silent, estimator=estimator)

    assert found is not None
    assert "Ejemplo SL" in found.basis
    assert found.salary.stated is False

    with pytest.raises(SalaryRecoveryError):
        Recovered(Salary(min=45000, currency="EUR", stated=False), "estimate", "   ")


def test_a_still_silent_offer_is_dropped_only_after_both_lookups() -> None:
    silent = _offer("board", _BODY + " Nothing here says what the job pays.")
    other = _offer("board", "An unrelated warehouse operative role in Manresa, nights.")
    detail_reads: list[str] = []

    def detail(offer: Offer) -> str | None:
        detail_reads.append(offer.id)
        return "Otros detalles. Contrato indefinido. Experiencia: 3 años."

    report = recover_all([silent, other], detail_reader=detail)

    assert silent.id in report.dropped
    assert report.attempted[silent.id] == ("advert_text", "duplicate", "detail_page")
    assert detail_reads == [silent.id, other.id]
    # No route that existed went untried — the accusation, refuted.
    assert report.routes_missed(("advert_text", "duplicate", "detail_page")) == {}


def test_a_house_estimate_is_never_donated() -> None:
    """`connectors/ruled-out.yaml`, test 4: one band on 48 of 50 adverts."""
    house = Salary(min=80000, max=150000, currency="USD", period="year", stated=True)
    stamped = [
        _offer("houseboard", f"Remote engineering role {index}, platform team.", house)
        for index in range(6)
    ]
    detected = house_estimate_bands(stamped)
    assert detected, "the spread was not read"

    silent = _offer("aggregator", _BODY)
    found, _attempted = recover(silent, donors=[stamped[0]], house_bands=detected)
    assert found is None

    # A single advert carrying that band is indistinguishable from an honest
    # one — which is exactly why the check is a spread and not a spot check.
    assert house_estimate_bands(stamped[:1]) == frozenset()


def test_a_duplicate_whose_band_is_only_in_its_text_still_donates() -> None:
    """The task's case exactly: neither copy has a `salary` field, because the
    connector left it unmapped on both — and one of them prints the band in its
    body. Reading only the field leaves that figure one join away and unjoined.
    """
    donor = _offer("tecnoempleo", _BODY + " Salario: 30.000 € - 36.000 € b/a.")
    silent = _offer("aggregator", _BODY + " Consulta las condiciones en el portal.")
    assert donor.salary is None

    report = recover_all([donor, silent])

    assert report.recovered[donor.id].route == "advert_text"
    joined = report.recovered[silent.id]
    assert joined.route == "duplicate"
    assert joined.salary == Salary(min=30000, max=36000, currency="EUR", period="year", stated=True)
    assert report.dropped == ()


def test_a_present_but_zero_figure_is_not_a_wage() -> None:
    sentinel = _offer("manfred", _BODY, Salary(min=0, currency="EUR", period="year", stated=True))
    silent = _offer("aggregator", _BODY + " Ask us about the package.")
    found, _attempted = recover(silent, donors=[sentinel])
    assert found is None


def test_two_duplicates_that_disagree_donate_nothing() -> None:
    """Returning the first usable donor made the answer a function of list
    order: the same job at EUR 45-55k or at USD 150-190k depending on which copy
    `find_duplicates` happened to yield first. Two readings mean no reading."""
    silent = _offer("aggregator", _BODY + " Ask us about the package.")
    euros = _offer(
        "boardone",
        _BODY + " One.",
        Salary(min=45000, max=55000, currency="EUR", period="year", stated=True),
    )
    dollars = _offer(
        "boardtwo",
        _BODY + " Two.",
        Salary(min=150000, max=190000, currency="USD", period="year", stated=True),
    )
    for order in ([euros, dollars], [dollars, euros]):
        found, _attempted = recover(silent, donors=order)
        assert found is None, [donor.source for donor in order]

    # And a donor band in a currency the recipient contradicts is not this
    # job's figure, however well the join scored.
    in_euros = _offer("aggregator", _BODY + " Ask us.", Salary(currency="EUR", stated=False))
    found, _attempted = recover(in_euros, donors=[dollars])
    assert found is None


def test_no_route_may_produce_a_figure_no_wage_could_be() -> None:
    """`__post_init__` validated the `stated` flag and nothing else, so `nan`,
    `inf`, a negative, an inverted band and 1e12 all reached the card — the
    estimate route rendering `nan EUR/year (estimated — the advert did not
    say)`. `_BOUNDS` and RO4's "zero is not a wage" apply on every route."""
    for band in _IMPOSSIBLE_BANDS:
        with pytest.raises(SalaryRecoveryError):
            Recovered(band, "estimate", "from comparable adverts")
        with pytest.raises(SalaryRecoveryError):
            Recovered(band.model_copy(update={"stated": True}), "duplicate", "another board")


def test_one_misparse_does_not_become_the_stated_band_on_every_copy() -> None:
    """Blast radius. `recover_all` writes each advert's parsed band back into
    the donor pool as `Salary(stated=True)`, so a misparse does not stay in the
    advert that caused it: it becomes the *stated* band on every near-duplicate,
    under a basis claiming another board's employer said it."""
    poison = " Salary package: we offer $250,000 in equity."
    poisoned = _offer("poisonboard", _BODY + poison)
    twin = _offer("mirrorboard", _BODY + " Apply on our portal for the conditions.")

    report = recover_all([poisoned, twin])

    assert report.recovered == {}
    assert set(report.dropped) == {poisoned.id, twin.id}


@pytest.mark.parametrize(("language", "text", "expected"), WORDING_CASES)
def test_the_wording_reads_as_the_spec_requires(
    language: str, text: str, expected: Salary | None
) -> None:
    assert band_in_text(text) == expected, language


def test_all_three_languages_are_covered_by_the_wording_cases() -> None:
    """ES/CA/EN parity is the requirement (issue #294). An English-only money
    parser is a silent partial feature, so the cases must span all three and
    each must contain both a recovery and a refusal."""
    for language in ("es", "ca", "en"):
        cases = [case for case in WORDING_CASES if case[0] == language]
        assert len(cases) >= 10, language
        assert any(case[2] is not None for case in cases), f"{language}: nothing recovered"
        assert any(case[2] is None for case in cases), f"{language}: nothing refused"


def test_the_gate_is_measured_over_a_real_denominator() -> None:
    """The plan's metric is one number; a green one over a parser that reads
    money wrongly is the failure this increment exists to catch, so every other
    defect count is asserted here beside it."""
    measured = measure()
    assert measured["gate_status"] == "measured"
    assert measured["salary_silent_offers_dropped_without_a_lookup"] == 0, measured["defects"]
    assert measured["salary_silent_offers_dropped_without_a_lookup_evaluated"] > 0
    assert measured["other_defects_total"] == 0, measured["defects"]
    assert measured["defects"] == []
    assert measured["wording_cases_evaluated"] >= MINIMUM_WORDING_CASES
    assert measured["corpus_ads_evaluated"] >= MINIMUM_CORPUS_ADS
    # The lookups ran and found things: a route that never succeeds is the
    # accusation restated, not answered.
    assert measured["corpus_recovered_by_route"]["advert_text"] > 0
    assert measured["corpus_recovered_by_route"]["duplicate"] > 0


def test_every_supported_language_recovers_something_from_the_real_corpus() -> None:
    """Not a fixture: the committed adverts. A parser that reads only English
    would pass every test above and still be the partial feature #294 names."""
    census = measure()["corpus_recovery_by_language"]
    for language in ("es", "ca", "en"):
        assert census[language]["read"] > 0, language
        assert census[language]["recovered"] > 0, f"{language}: nothing recovered from real adverts"
