"""T214 — the annual bound knows the currency, and nofluffjobs' hourly bands have a period.

Every expectation is derived from the task statement and the cards' own text, not
from what the code returns: `INR 1500K-2800K` is a real annual band (about
fifteen to twenty-eight thousand euros), and `105 - 115 PLN / h` is an hourly
one.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from integral import connector_salary_audit, connectors
from integral.connector_salary_audit import RowVerdict, _refused_for_bound_or_period, measure
from integral.connectors import (
    _outside_annual_bound,
    _take,
    build_offer,
    load_connector,
    parse_list_page,
)
from integral.salary_recovery import _band_defect, bounds_for

_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _ROOT / "connectors"
_BODY = "A body long enough to be an advert. " * 3


def _salary(currency: str | None, low: float, high: float, period: str | None = None) -> Any:
    connector = load_connector(_CONNECTORS / "foorilla_en" / "connector.yaml")
    fields = {
        "text": _BODY,
        "salary_min": str(int(low)),
        "salary_max": str(int(high)),
    }
    if currency is not None:
        fields["salary_currency"] = currency
    if period is not None:
        fields["salary_period"] = period
    return build_offer(connector, list_fields=fields, url="https://x.test/1").salary


# --- the bound is the currency's own ---


@pytest.mark.parametrize(
    ("low", "high"),
    [(1_500_000, 2_800_000), (3_700_000, 5_876_000)],
)
def test_an_inr_annual_band_is_read(low: float, high: float) -> None:
    salary = _salary("INR", low, high)
    assert salary is not None
    assert (salary.min, salary.max, salary.currency) == (low, high, "INR")


@pytest.mark.parametrize("currency", ["EUR", "USD", "GBP", "CAD", "PLN"])
def test_a_band_in_a_unit_currency_keeps_the_base_ceiling(currency: str) -> None:
    """The bound moved for a rupee, not for everyone: five million euros is still
    a misparse, and widening the global ceiling is the shortcut this refuses."""
    assert _salary(currency, 5_000_000, 6_000_000) is None
    assert _salary(currency, 50_000, 60_000) is not None


def test_an_inr_band_is_still_bounded_at_both_ends() -> None:
    assert _salary("INR", 1_500, 2_800) is None  # a monthly-looking figure with no period
    assert _salary("INR", 150_000_000, 250_000_000) is None


def test_a_currency_with_no_recorded_scale_is_refused() -> None:
    """Fail closed: a figure in a currency nobody wrote the scale of is not
    shown on the euro scale, whatever its size."""
    assert _salary("JPY", 60_000, 70_000) is None
    assert _salary("XYZ", 60_000, 70_000) is None


def test_a_band_naming_no_currency_keeps_the_base_scale() -> None:
    """`usajobs_en` maps a band and declares no currency field. Unchanged."""
    assert not _outside_annual_bound(None, None, 50_000.0, 60_000.0)
    assert _outside_annual_bound(None, None, 5_000_000.0)


def test_a_declared_period_is_not_bounded_here() -> None:
    assert not _outside_annual_bound("hour", "JPY", 105.0)


def test_the_recovery_route_bounds_by_currency_too() -> None:
    from integral.offers import Salary

    inr = Salary(min=1_500_000, max=2_800_000, currency="INR", period="year", stated=False)
    assert _band_defect(inr) is None
    eur = Salary(min=1_500_000, max=2_800_000, currency="EUR", period="year", stated=False)
    assert _band_defect(eur) is not None
    monthly = Salary(min=150_000, max=250_000, currency="INR", period="month", stated=False)
    assert _band_defect(monthly) is None
    unknown = Salary(min=60_000, max=70_000, currency="JPY", period="year", stated=False)
    assert _band_defect(unknown) is not None
    assert bounds_for("year", "INR") == (5_000.0 * 95.0, 1_000_000.0 * 95.0)
    assert bounds_for("year", "JPY") is None
    assert bounds_for("fortnight", "EUR") is None  # type: ignore[arg-type]


# --- `take: period` ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("105 \u2013 115 PLN / h", "h"),
        ("35 \u2013 43 USD / h", "h"),
        ("33 000 \u2013 45 000 PLN / month", "month"),
        ("50 EUR per hour", "hour"),
        ("50 EUR / HOUR", "hour"),
        ("105 \u2013 115 PLN", None),  # states none
        ("105 PLN / h or 4000 PLN / month", None),  # two readings
        ("105 PLN / fortnight", None),  # a word the vocabulary refuses
        ("105 PLN / hrs", None),  # not in the closed table
        ("Hourly rate 105 PLN", None),  # no `/` or `per`
    ],
)
def test_take_period_cuts_one_known_word_or_nothing(text: str, expected: str | None) -> None:
    assert _take("period", text) == expected


# --- nofluffjobs, end to end ---


def test_nofluffjobs_hourly_bands_read_as_hour_and_the_monthly_one_stays_refused() -> None:
    package = _CONNECTORS / "nofluffjobs_en"
    connector = load_connector(package / "connector.yaml")
    rows = parse_list_page(
        connector, (package / "fixture" / "list.html").read_text(encoding="utf-8")
    )
    read = []
    for row in rows:
        offer = build_offer(connector, list_fields=row, url="https://fixture.invalid/x")
        read.append(
            None
            if offer.salary is None
            else (
                offer.salary.min,
                offer.salary.max,
                offer.salary.currency,
                offer.salary.period,
            )
        )
    assert read[0] == (105.0, 115.0, "PLN", "hour")
    assert read[1] is None  # `33 000 - 45 000 PLN / month`: four numbers, still refused
    assert read[2] == (35.0, 43.0, "USD", "hour")


# --- the audit ---


def test_the_audit_counts_no_refusal_for_the_bound_or_a_period_today() -> None:
    measured = measure()
    assert measured["salary_rows_refused_for_bound_or_period"] == 0, measured
    assert measured["salary_expectation_mismatches"] == 0, measured["mismatches"]


def _row(mentions_period: bool = False) -> RowVerdict:
    return RowVerdict(
        index=0, route="list", publishes=(), salary=None, card_mentions_period=mentions_period
    )


@pytest.mark.parametrize(
    "why",
    [
        "`build_offer` refuses it: outside `salary_recovery._BOUNDS['year']`.",
        "A band with no period is bounded as annual, so it is refused.",
        "`h` is not a word `salary_period.normalize_period` accepts.",
        "The grammar has no period `take`; a period `take` is the follow-up.",
    ],
)
def test_a_refusal_naming_the_bound_or_a_missing_period_is_counted(why: str) -> None:
    assert _refused_for_bound_or_period({"verdict": "refused", "why": why}, _row())


def test_a_refusal_for_another_cause_is_not_counted() -> None:
    why = "A single figure, not a band: `range_low` needs exactly two numbers."
    assert not _refused_for_bound_or_period({"verdict": "refused", "why": why}, _row())


def test_the_no_period_waiver_stands_only_while_the_card_states_none() -> None:
    declared = {
        "verdict": "refused",
        "why": "The card states no period at all, so it is bounded as annual.",
        "card_states_no_period": True,
    }
    assert not _refused_for_bound_or_period(declared, _row(mentions_period=False))
    assert _refused_for_bound_or_period(declared, _row(mentions_period=True))
    undeclared = {k: v for k, v in declared.items() if k != "card_states_no_period"}
    assert _refused_for_bound_or_period(undeclared, _row(mentions_period=False))


def test_a_card_that_starts_printing_a_period_turns_the_waiver_into_a_counted_refusal(
    tmp_path: Path,
) -> None:
    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    fixture = tmp_path / "connectors" / "trabajos_es" / "fixture"
    html = (fixture / "list.html").read_text(encoding="utf-8")
    assert html.count("9 € - 13 €") == 1
    (fixture / "list.html").write_text(
        html.replace("9 € - 13 €", "9 € - 13 € / h"), encoding="utf-8"
    )
    measured = measure(tmp_path / "connectors")
    assert measured["salary_rows_refused_for_bound_or_period"] == 1, measured


def test_the_audit_holds_an_inr_card_against_the_currency_aware_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """foorilla's INR rows are read through one shared CAD detail page, so the
    engine's read says nothing about them. Put the old currency-blind bound back
    and the audit must name them."""

    def blind(period: str | None, currency: str | None, *figures: float | None) -> bool:
        return period is None and any(
            f is not None and not 5_000 <= f <= 1_000_000 for f in figures
        )

    monkeypatch.setattr(connector_salary_audit, "_outside_annual_bound", blind)
    measured = measure()
    inr = [m for m in measured["mismatches"] if m.startswith("foorilla_en") and "bound" in m]
    assert len(inr) >= 11, measured["mismatches"]
    assert connectors._outside_annual_bound is not blind


# --- second-reader round (#659) ---

#: Units per euro, written here independently of the table under test, and
#: deliberately a little off it (about +-15%): the bound only needs the order of
#: magnitude, and a test that copied the table would agree with it by
#: construction.
_RATES = {
    "EUR": 1.0,
    "USD": 1.15,
    "GBP": 0.87,
    "CHF": 0.93,
    "CAD": 1.6,
    "AUD": 1.7,
    "PLN": 4.25,
    "SEK": 10.9,
    "NOK": 11.8,
    "DKK": 7.46,
    "BRL": 6.3,
    "RON": 4.97,
    "INR": 98.0,
}


def test_the_rate_table_covers_every_currency_the_connectors_can_name() -> None:
    from integral.salary_recovery import _UNITS_PER_EUR

    named = set(connectors._CURRENCIES.values())
    assert set(_UNITS_PER_EUR) == named == set(_RATES)


@pytest.mark.parametrize("currency", sorted(_RATES))
def test_every_currency_separates_a_monthly_band_from_an_annual_one(currency: str) -> None:
    """A monthly EUR 2,500-3,500 wage in this currency, with no period on the
    card, is NOT an annual wage; EUR 40,000-60,000 is. One wrong scale in the
    table (SEK at 1, PLN at 4 against a 10 table) fails exactly one case."""
    rate = _RATES[currency]
    monthly = (2_500 * rate, 3_500 * rate)
    annual = (40_000 * rate, 60_000 * rate)
    assert _salary(currency, round(monthly[0]), round(monthly[1])) is None, currency
    assert _salary(currency, round(annual[0]), round(annual[1])) is not None, currency


@pytest.mark.parametrize("phrase", ["por hora", "la hora", "al mes", "/ mes", "per hour"])
def test_the_no_period_waiver_does_not_stand_over_a_spanish_period_word(
    tmp_path: Path, phrase: str
) -> None:
    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    fixture = tmp_path / "connectors" / "trabajos_es" / "fixture"
    html = (fixture / "list.html").read_text(encoding="utf-8")
    card = "9 € - 13 €"
    (fixture / "list.html").write_text(html.replace(card, f"{card} {phrase}"), encoding="utf-8")
    measured = measure(tmp_path / "connectors")
    assert measured["salary_rows_refused_for_bound_or_period"] == 1, (phrase, measured)


def test_a_non_zero_key_fails_the_audit_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    real = measure()
    # `_main` records T200.json; keep that off the committed file (#671).
    write_real = connector_salary_audit.write_evidence
    monkeypatch.setattr(
        connector_salary_audit, "write_evidence", lambda: write_real(tmp_path / "T200.json")
    )
    assert connector_salary_audit._main(["audit"]) == 0
    monkeypatch.setattr(
        connector_salary_audit,
        "measure",
        lambda *a, **k: {**real, "salary_rows_refused_for_bound_or_period": 1},
    )
    assert connector_salary_audit._main(["audit"]) == 1


def test_reverting_the_period_take_and_rewording_the_refusal_is_still_counted(
    tmp_path: Path,
) -> None:
    """The key measures the property (the row reads once the bound is off), not
    the wording of the declared reason (#659 F4)."""
    shutil.copytree(_CONNECTORS, tmp_path / "connectors")
    package = tmp_path / "connectors" / "nofluffjobs_en"
    yaml = (package / "connector.yaml").read_text(encoding="utf-8")
    block = '    salary_period:\n      css: "nfj-posting-item-salary"\n      take: period\n'
    assert block in yaml
    (package / "connector.yaml").write_text(yaml.replace(block, ""), encoding="utf-8")
    salary = package / "fixture" / "salary.json"
    data = json.loads(salary.read_text(encoding="utf-8"))
    for row in ("0", "2"):
        data["rows"][row] = {
            "verdict": "refused",
            "why": "The card prints an hourly unit that this connector declines to interpret.",
        }
    salary.write_text(json.dumps(data), encoding="utf-8")
    measured = measure(tmp_path / "connectors")
    assert measured["salary_rows_refused_for_bound_or_period"] == 2, measured


@pytest.mark.parametrize(
    "text",
    [
        "4 000 PLN brutto, 40 h/week",
        "2 days per week in office",
        "days per week",
        "4 000 PLN, 40 horas por semana",
    ],
)
def test_take_period_does_not_read_working_time(text: str) -> None:
    assert _take("period", text) is None


def test_take_period_still_reads_pay_beside_working_time() -> None:
    assert _take("period", "105 PLN / h, 40 h/week") == "h"
