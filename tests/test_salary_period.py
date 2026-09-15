"""T170 — one pay-period vocabulary, and the floor it finally applies to.

`bulk_filter._below_pay_floor` compares `offer.salary.period == floor.period`,
and a floor names `year` or `month` (`candidate.Salary.period`). Every
connector wrote its board's own word instead — Lever's `per-year-salary`,
Himalayas' `annual`, schema.org's `MONTH` — so the comparison never matched
and the floor dropped nothing a connector built (#454, second-reader finding
F13 on #445/T144).

Five tests, in the order the task payload names them. The first is the
adversarial contract table (`integral.salary_period.CONTRACT_CASES`), derived
from each board's own documented or directly-captured vocabulary rather than
from `normalize_period`'s implementation — see that module's docstring for the
citations. The rest pin the fail-open end to end: a connector-built offer with
a board's own period word must now actually get compared against, and dropped
by, the candidate's floor.
"""

from __future__ import annotations

from typing import get_args

import pytest

import integral.strings as strings
from integral.bulk_filter import HardConstraints, PayFloor, reduce
from integral.candidate import Salary as CandidateSalary
from integral.connectors import (
    Connector,
    build_offer,
    connector_packages,
    load_connector,
    parse_connector,
)
from integral.offers import Salary, SalaryPeriod, compute_offer_id
from integral.salary_period import (
    _TABLE,
    CONTRACT_CASES,
    MINIMUM_PERIOD_CONTRACTS,
    PeriodContract,
    normalize_period,
)

#: A minimal, valid connector — `build_offer` never reads `list`/`detail`
#: beyond what `Connector` itself validates at parse time, so this exists only
#: to produce a `Connector` object; every field an offer carries is passed to
#: `build_offer` directly, with no HTML or JSON page in between.
_CONNECTOR_YAML = """
site: periodtest
locale: en
version: "1.0.0"
last_verified: "2026-09-10"
list:
  url_pattern: "https://periodtest.example/jobs"
  from_json:
    items: "$"
    fields:
      text: text
      salary_min: salary_min
      salary_max: salary_max
      salary_currency: salary_currency
      salary_period: salary_period
"""


def _connector() -> Connector:
    return parse_connector(_CONNECTOR_YAML)


# --- test_period_contracts: the second session's table -----------------------


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: f"{c.board}:{c.raw!r}")
def test_period_contracts(case: PeriodContract) -> None:
    """Every row of `CONTRACT_CASES`, checked against `normalize_period`.

    The table is written from each board's own documentation or dated capture
    (see `salary_period.py`'s module docstring and each row's `citation`), not
    from what `normalize_period` happens to return — the whole point of an
    adversarial fixture is that it can fail.
    """
    assert normalize_period(case.raw) == case.expected, case.citation


def test_the_contract_table_meets_its_floor() -> None:
    """A count of zero over an empty table is not a pass (T100/T122)."""
    assert len(CONTRACT_CASES) >= MINIMUM_PERIOD_CONTRACTS


def test_the_table_has_both_positive_and_negative_rows() -> None:
    """A table of only matches could not catch a normaliser that matches
    everything; a table of only refusals could not catch one that matches
    nothing. Both shapes are real defects this task was filed over."""
    positive = sum(1 for case in CONTRACT_CASES if case.expected is not None)
    negative = sum(1 for case in CONTRACT_CASES if case.expected is None)
    assert positive >= 10
    assert negative >= 8


def _maps_salary_period(connector: Connector) -> bool:
    """True if `salary_period` is a key this connector's own field map
    names, on either page, markup or JSON route.

    Mirrors `Connector._something_produces_the_offer_text`'s idiom (same
    module) rather than duplicating a different check — "does this connector
    produce field X" is one question asked of two different fields.
    """
    list_has_it = "salary_period" in connector.list.fields or (
        connector.list.from_json is not None and "salary_period" in connector.list.from_json.fields
    )
    detail_has_it = connector.detail is not None and (
        "salary_period" in connector.detail.fields
        or (
            connector.detail.from_json is not None
            and "salary_period" in connector.detail.from_json.fields
        )
    )
    return list_has_it or detail_has_it


#: The floor for `mapping`'s own population — F7, second-reader report on
#: #487: the old `assert mapping` only required a non-empty set, so blinding
#: one of `_maps_salary_period`'s four enumerated routes (e.g. dropping the
#: `list.from_json.fields` half) silently dropped the real population from 4
#: to 2 — losing `himalayas_en` and `lever_en`, the exact two boards F1/F2
#: were about — while `missing = mapping - covered` still read empty and
#: every test in this file still passed. Four connectors map `salary_period`
#: today (`himalayas_en`, `jobfluent_es`, `justjoin_en`, `lever_en`); a fifth
#: only ever raises `len(mapping)` above this, so the floor never needs
#: bumping on its own (T100's convention). This is a literal floor, not
#: `len(mapping)` itself — a bound derived from the thing it bounds could
#: never fire (T150's "bound derived from the thing it bounds").
MINIMUM_CONNECTORS_MAPPING_SALARY_PERIOD = 4


def test_every_connector_that_maps_salary_period_has_contract_coverage() -> None:
    """F3, second-reader report on #487: `MINIMUM_PERIOD_CONTRACTS` is a row
    count, and a row count can be cleared by deleting a whole board's rows as
    long as enough others remain — measured there by deleting every Lever row
    from both `_TABLE` and `CONTRACT_CASES` and finding the floor (and the
    gate) still green.

    This check cannot be cleared that way, because it is not a count: it
    reads the real `connectors/` tree, finds every package whose own field
    map actually names `salary_period` today, and requires each to be named
    by at least one *positive* `CONTRACT_CASES` row via `PeriodContract.
    connector`. Deleting a board's positive rows now fails this directly;
    a fifth connector mapping the field grows the requirement by itself, with
    nobody needing to remember to raise a number.

    Two more ways this check itself could go quietly blind (F7, second-reader
    report on #487): `mapping`'s own population was unpinned, so a mutation to
    `_maps_salary_period` that blinded one of its four routes shrank `mapping`
    and made `missing` easier, not harder, to keep empty — caught below by
    `MINIMUM_CONNECTORS_MAPPING_SALARY_PERIOD`. And `missing = mapping -
    covered` alone never reads `covered - mapping`, so a `CONTRACT_CASES` row
    naming a connector package that does not exist, or no longer maps the
    field, would go uncaught — caught below by `unknown`.
    """
    covered = {
        case.connector for case in CONTRACT_CASES if case.expected is not None and case.connector
    }
    mapping = {
        package.name
        for package in connector_packages()
        if _maps_salary_period(load_connector(package))
    }
    assert len(mapping) >= MINIMUM_CONNECTORS_MAPPING_SALARY_PERIOD, (
        f"expected at least {MINIMUM_CONNECTORS_MAPPING_SALARY_PERIOD} connectors mapping "
        f"salary_period, found {len(mapping)}: {sorted(mapping)}"
    )
    missing = mapping - covered
    assert not missing, f"connectors mapping salary_period with no positive contract row: {missing}"
    unknown = covered - mapping
    assert not unknown, (
        "CONTRACT_CASES names a connector that does not map salary_period (typo, or a "
        f"stale row for a connector that no longer maps it): {unknown}"
    )


def test_table_values_are_offer_periods() -> None:
    """Closed, not restated: every value `_TABLE` maps to is a member of
    `offers.SalaryPeriod`, derived from the `Literal` rather than a second
    hand-written list that could drift from it."""
    vocabulary = set(get_args(SalaryPeriod))
    assert set(_TABLE.values()) <= vocabulary


# --- test_a_connector_salary_below_the_floor_is_dropped -----------------------


@pytest.mark.parametrize("period", get_args(CandidateSalary.model_fields["period"].annotation))
def test_a_connector_salary_below_the_floor_is_dropped(period: str) -> None:
    """The fail-open this task exists to close, pinned end to end.

    Every period a candidate's floor can name — read from
    `candidate.Salary.period` itself via `typing.get_args`, never restated as a
    list — must, once a connector states an offer below it in that same
    period, actually get dropped by `bulk_filter.reduce`. Before T170 this
    never fired for any connector-stated period: `offer.salary.period` held a
    board's raw word and `floor.period` held `"year"`/`"month"`, and the two
    were never equal.
    """
    text = f"An offer paid below the floor, {period} period."
    connector = _connector()
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "1",
            "salary_max": "10",
            "salary_currency": "EUR",
            # The vocabulary's own canonical spelling is also a valid raw
            # value (schema.org sends it upper case, but the table folds
            # case) — using it here keeps this test about the floor
            # comparison, not about any one board's label.
            "salary_period": period,
        },
        url="https://periodtest.example/jobs/1",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is not None
    assert offer.salary.period == period

    floor = PayFloor(amount=1_000_000, currency="EUR", period=period)
    reduction = reduce([offer], HardConstraints(pay_floor=floor))

    assert reduction.kept == ()
    assert len(reduction.dropped) == 1
    assert reduction.dropped[0].rule == "below_pay_floor"


def test_a_raw_board_period_below_the_floor_is_also_dropped() -> None:
    """F1, second-reader report on #487: the test above pins the floor
    comparison using the *canonical* spelling (`"month"`), which was never
    where the fail-open lived. Before `_TABLE` mapped Himalayas' own word,
    `"monthly"` fell to `None` in `normalize_period`, `build_offer` dropped
    the whole salary as a stated-but-unrepresentable period, and the offer
    reached `reduce` with no salary at all — which `_below_pay_floor` cannot
    drop, so a real monthly-paid offer below the floor was *admitted*
    instead of refused. Pinned here with the board's actual raw label,
    `"monthly"`, not the vocabulary it now maps to, so a regression that
    un-maps a real board word (as `main` shipped, and as F1 found still true
    of `weekly`/`monthly` before this commit) fails this test even though
    `test_a_connector_salary_below_the_floor_is_dropped` above — which never
    passes a raw board label — would not.
    """
    text = "An offer paid below the floor, Himalayas' own 'monthly' word."
    connector = _connector()
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "1",
            "salary_max": "10",
            "salary_currency": "EUR",
            "salary_period": "monthly",
        },
        url="https://periodtest.example/jobs/5",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is not None
    assert offer.salary.period == "month"

    floor = PayFloor(amount=1_000_000, currency="EUR", period="month")
    reduction = reduce([offer], HardConstraints(pay_floor=floor))

    assert reduction.kept == ()
    assert len(reduction.dropped) == 1
    assert reduction.dropped[0].rule == "below_pay_floor"


# --- test_floor_periods_are_offer_periods -------------------------------------


def test_floor_periods_are_offer_periods() -> None:
    """Every period a floor can name is in the offer vocabulary, so the two
    `Literal`s cannot silently drift apart — a floor naming a period no offer
    could ever carry would be a comparison that can never match, the same
    failure shape this task closes, one level up."""
    floor_periods = set(get_args(CandidateSalary.model_fields["period"].annotation))
    offer_periods = set(get_args(SalaryPeriod))
    assert floor_periods <= offer_periods


# --- test_every_period_has_a_catalogue_entry_in_every_language ---------------


def test_every_period_has_a_catalogue_entry_in_every_language() -> None:
    """Derived from the `Literal`, never from a hand-kept list of which
    periods happen to be translated today."""
    catalogue = strings.load()
    languages = [lang for lang in catalogue["languages"] if lang != catalogue["source_language"]]
    assert languages, "the catalogue must declare at least one translated language"

    stale = set(strings.stale(catalogue))
    missing = set(strings.missing(catalogue))

    for period in get_args(SalaryPeriod):
        key = f"period_{period}"
        assert key in catalogue["entries"], f"no catalogue entry for {key!r}"
        assert catalogue["entries"][key].get(catalogue["source_language"]) == period
        for language in languages:
            handle = f"{language}:{key}"
            assert handle not in missing, f"{handle} has no translation"
            assert handle not in stale, f"{handle} was translated from stale English"


# --- test_an_unrepresentable_period_states_no_salary --------------------------


def test_an_unrepresentable_period_states_no_salary() -> None:
    """`one-time` with figures gives `salary is None` — a period the board
    stated but this vocabulary cannot represent drops the whole salary, not
    just the period (see `connectors.build_offer` and `salary_period.py`).
    Reading it as "no period" and keeping the figures would let a lump sum
    through comparisons built for a wage, which is the fail-open shape this
    task exists to close one level up from the table itself."""
    connector = _connector()
    text = "A one-time signing bonus, not a wage."
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "5000",
            "salary_max": "5000",
            "salary_currency": "USD",
            "salary_period": "one-time",
        },
        url="https://periodtest.example/jobs/2",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is None


def test_an_absent_period_is_unaffected() -> None:
    """No `salary_period` field at all is not "a period stated and refused" —
    it is today's ordinary "no period stated", and the figures survive exactly
    as they did before this table existed."""
    connector = _connector()
    text = "A salary with no period stated at all."
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "40000",
            "salary_max": "50000",
            "salary_currency": "EUR",
        },
        url="https://periodtest.example/jobs/3",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is not None
    assert offer.salary.period is None
    assert (offer.salary.min, offer.salary.max) == (40000.0, 50000.0)


@pytest.mark.parametrize("raw_period", ["", " "])
def test_a_blank_period_is_unaffected_like_an_absent_one(raw_period: str) -> None:
    """F4, second-reader report on #487: `build_offer`'s guard used to read
    `if raw_period and period is None:` — Python truthiness, not this
    repository's own definition of "the field was actually stated"
    (`connectors._present`, already written once so its two existing
    consumers treat an empty string and a run of whitespace identically).
    `""` is falsy, so it happened to take the safe branch; `" "` is truthy,
    so it took the *other* one, and a real salary was dropped where the
    empty string leaves it intact — even though `_TABLE.get` folds both to
    the same lookup miss. Parametrized so `""` and `" "` are asserted to
    behave identically, the way every other `_present` consumer already
    guarantees.
    """
    connector = _connector()
    text = f"A salary with a blank period ({raw_period!r})."
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "40000",
            "salary_max": "50000",
            "salary_currency": "EUR",
            "salary_period": raw_period,
        },
        url="https://periodtest.example/jobs/6",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is not None
    assert offer.salary.period is None
    assert (offer.salary.min, offer.salary.max) == (40000.0, 50000.0)


def test_an_unrecognised_but_stated_period_also_states_no_salary() -> None:
    """A near-miss like `"yearly-bonus"` is not `"year"` — it is a stated,
    unrepresentable period, and follows `one-time`'s rule rather than being
    coerced into the period it merely resembles."""
    connector = _connector()
    text = "Paid yearly-bonus style, whatever that means."
    offer = build_offer(
        connector,
        list_fields={
            "text": text,
            "salary_min": "1000",
            "salary_max": "2000",
            "salary_currency": "EUR",
            "salary_period": "yearly-bonus",
        },
        url="https://periodtest.example/jobs/4",
        source_ref=compute_offer_id(text),
    )
    assert offer.salary is None


def test_salary_rejects_a_period_outside_the_vocabulary() -> None:
    """`Salary` itself, not just `build_offer`, refuses a period outside the
    closed vocabulary — the type is the enforcement point, not a convention
    every caller has to remember (T170's design: "No route can then build a
    salary with a period outside it: not a connector, not `salary_recovery`,
    not a future producer")."""
    with pytest.raises(ValueError):
        Salary(min=1.0, period="MONTH", stated=True)  # type: ignore[arg-type]
