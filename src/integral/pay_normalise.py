"""T246 — one dated conversion into the weights' currency, before pay reaches `rank()`.

`Candidate.salary_per_month` carries no currency, so a USD band reached the sort
as a bare number beside euro ones: the order compared two different units and
printed the result as a ranking. This module is the only place an offer's pay
becomes a `Candidate`'s, and it keeps three promises.

**Pay is converted, or the offer is refused — never compared as it came.** The
rule is closed, not a list of bad currencies: a figure is in the weights'
currency (factor 1, no rate needed) or a `DatedRate` for its currency was
passed in, and otherwise `PayNormaliseError` is raised. The same goes for a
figure whose period has no calendar factor to a month (a day or an hour needs a
working-hours assumption nobody here has made) or that names no currency. A
rate is a value passed in, never fetched: this repository's cloud sessions have
no network, and what to fetch is a connector question (`salary_recovery` makes
the same point for detail pages). `salary_recovery._UNITS_PER_EUR` is not a rate
table — it is undated and exists to bound plausible wages — and is deliberately
not consulted. A `DatedRate` cannot be built without a date and a source.

**A stated band the source left empty is read from the advert.** When
`offer.salary` carries no figure, `salary_recovery.band_in_text` re-reads the
body (its refusals — two readings mean none, no currency means none — are
inherited whole). The reading's `basis` says `read_from_text`, so a figure read
out of prose never looks like a connector's field.

**An offer with no published pay is ordered among the unpaid ones, and says so.**
Of the two things the task allows — an estimate with its source and range, or
placing the offer among the unpaid and saying that — this takes the second: an
estimate needs a source this repository does not hold, and the cheapest honest
statement is "no pay published". Only a *stated* figure ranks, so an offer
already carrying an estimate (`stated=False`) is unpaid here too, and
`annotate` writes the note beside the ranking rather than leaving the order to
read as a pay verdict.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Literal

from integral.extraction import OfferExtraction
from integral.offers import Offer, Salary, compute_offer_id, is_advert
from integral.profile import ProfileRevision
from integral.rank import Candidate, PayBand, RankingError, from_extraction, rank
from integral.salary_recovery import band_in_text

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T246.json"

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")

#: Months per period, for the periods whose calendar factor is not an opinion.
#: A day or an hour is absent on purpose: the factor would be a guess about
#: working time, and a guess compared against stated figures is the defect.
_PER_MONTH: dict[str, float] = {"year": 1 / 12, "month": 1.0, "week": 52 / 12}

Basis = Literal["stated", "read_from_text", "unpaid"]


class PayNormaliseError(Exception):
    """Pay that cannot be put in the weights' currency per month, so is not ranked."""


@dataclass(frozen=True)
class DatedRate:
    """`per_unit` units of the target currency for one `currency`, as of `as_of`."""

    currency: str
    per_unit: float
    as_of: str
    source: str

    def __post_init__(self) -> None:
        if not _CURRENCY_RE.match(self.currency):
            raise PayNormaliseError(f"{self.currency!r} is not an ISO 4217 code")
        if not math.isfinite(self.per_unit) or self.per_unit <= 0:
            raise PayNormaliseError(f"a rate must be positive and finite, not {self.per_unit}")
        try:
            date.fromisoformat(self.as_of)
        except ValueError as error:
            raise PayNormaliseError(f"a rate needs an ISO date, not {self.as_of!r}") from error
        if not self.source.strip():
            raise PayNormaliseError(f"a {self.currency} rate with no source is a bare number")


@dataclass(frozen=True)
class RateTable:
    """The weights' currency and the dated rates into it."""

    target: str
    rates: tuple[DatedRate, ...] = ()

    def __post_init__(self) -> None:
        if not _CURRENCY_RE.match(self.target):
            raise PayNormaliseError(f"{self.target!r} is not an ISO 4217 code")
        currencies = [rate.currency for rate in self.rates]
        if len(set(currencies)) != len(currencies):
            raise PayNormaliseError("two rates for one currency: which one is dated is a choice")

    def rate_for(self, currency: str) -> DatedRate | None:
        """`None` for the target itself; the dated rate otherwise, or a refusal."""
        if currency == self.target:
            return None
        for rate in self.rates:
            if rate.currency == currency:
                return rate
        raise PayNormaliseError(
            f"no dated rate from {currency} to {self.target}: pay is refused, not compared"
        )


@dataclass(frozen=True)
class PayReading:
    """How one offer's pay entered the ranking, and what to say about it."""

    offer_id: str
    basis: Basis
    per_month: float | None
    band: PayBand | None
    converted_from: str | None
    rate: DatedRate | None
    note: str

    def as_json(self) -> dict[str, Any]:
        return {
            "basis": self.basis,
            "per_month": self.per_month,
            "band": None
            if self.band is None
            else {"low": self.band.low, "high": self.band.high, "currency": self.band.currency},
            "converted_from": self.converted_from,
            "rate": None
            if self.rate is None
            else {
                "per_unit": self.rate.per_unit,
                "as_of": self.rate.as_of,
                "source": self.rate.source,
            },
            "note": self.note,
        }


def _has_figure(salary: Salary | None) -> bool:
    return salary is not None and (salary.min is not None or salary.max is not None)


def _published(offer: Offer) -> tuple[Salary | None, Basis]:
    """The figure to rank on, and where it came from. Only a stated one counts."""
    if _has_figure(offer.salary):
        assert offer.salary is not None
        return (offer.salary, "stated") if offer.salary.stated else (None, "unpaid")
    found = band_in_text(offer.text)
    if found is not None and found.stated:
        return found, "read_from_text"
    return None, "unpaid"


def read_pay(offer: Offer, table: RateTable) -> PayReading:
    """`offer`'s pay in `table.target` per month, or `PayNormaliseError`."""
    salary, basis = _published(offer)
    if salary is None:
        return PayReading(
            offer.id,
            "unpaid",
            None,
            None,
            None,
            None,
            "no published pay: ordered among the unpaid offers, not estimated",
        )
    if salary.currency is None:
        raise PayNormaliseError(f"{offer.id} states a figure with no currency")
    months = _PER_MONTH.get(salary.period or "")
    if months is None:
        raise PayNormaliseError(
            f"{offer.id} states pay per {salary.period!r}, which has no calendar factor to a month"
        )
    rate = table.rate_for(salary.currency)
    factor = months * (1.0 if rate is None else rate.per_unit)
    ends = [value for value in (salary.min, salary.max) if value is not None]
    if not all(math.isfinite(value) and value >= 0 for value in ends):
        raise PayNormaliseError(
            f"{offer.id} states a figure that is not a finite, non-negative wage"
        )
    low, high = min(ends) * factor, max(ends) * factor
    band = PayBand(low=low, high=high, currency=table.target)
    note = (
        f"{salary.currency} {salary.period}, no conversion"
        if rate is None
        else f"{salary.currency} to {table.target} at {rate.per_unit} as of {rate.as_of} "
        f"({rate.source})"
    )
    return PayReading(
        offer.id,
        basis,
        (low + high) / 2,
        band,
        None if rate is None else salary.currency,
        rate,
        note + (" — read from the advert text" if basis == "read_from_text" else ""),
    )


def candidate_for(
    offer: Offer,
    extraction: OfferExtraction,
    *,
    dimensions: Sequence[str],
    table: RateTable,
) -> tuple[Candidate, PayReading]:
    """The ranking's candidate for `offer`: the one door pay goes through.

    T255: only a vacancy has a place in a ranking. An open application is refused
    here, so nothing downstream (`rank`, `write_ranking`, a page) can order it."""
    if not is_advert(offer):
        raise PayNormaliseError(f"{offer.id}: an open application is not ranked")
    reading = read_pay(offer, table)
    candidate = from_extraction(extraction, dimensions=dimensions, salary_per_month=None)
    return replace(candidate, salary_per_month=reading.per_month, pay=reading.band), reading


def annotate(
    ranking: Mapping[str, Any], readings: Sequence[PayReading], table: RateTable
) -> dict[str, Any]:
    """The ranking with a `pay` entry per ranked offer, saying how its pay got there."""
    if ranking.get("currency") not in (None, table.target):
        raise PayNormaliseError(
            f"the ranking is in {ranking.get('currency')!r} and the pay was put in {table.target!r}"
        )
    shown = {*ranking["pareto"], *ranking["dominated"]}
    by_id = {reading.offer_id: reading for reading in readings}
    return {
        **ranking,
        "pay": {
            offer_id: by_id[offer_id].as_json() for offer_id in sorted(shown) if offer_id in by_id
        },
        "unpaid_offers": sorted(
            offer_id
            for offer_id in shown
            if offer_id in by_id and by_id[offer_id].basis == "unpaid"
        ),
    }


# ---------------------------------------------------------------------------
# The measurement

_RATE = DatedRate("USD", 0.9, "2026-10-01", "fixture: a rate passed in, not a market figure")
_TABLE = RateTable("EUR", (_RATE,))
_WEIGHTS = {
    "currency": "EUR",
    "part_worths": {
        "remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0},
    },
}
_DIMENSIONS = ("remote",)
_REVISION = ProfileRevision(rows=1, sha256="0" * 64)


def _offer(label: str, text: str, salary: Salary | None) -> Offer:
    body = f"{label}. {text}"
    return Offer(id=compute_offer_id(body), source="fixture", text=body, salary=salary)


def _extraction(offer_id: str) -> OfferExtraction:
    return OfferExtraction(offer_id=offer_id, language="en", scores=[], unsettled=list(_DIMENSIONS))


#: `(offer, the EUR per month the spec requires)`. Each figure is worked from the
#: task text and the rate above, not read off the code: 60000 USD a year is 5000
#: USD a month, and 5000 * 0.9 = 4500 EUR; 3000 EUR is already the weights'
#: currency; 800 USD a week is 800 * 52 / 12 * 0.9 = 3120 EUR; the third offer
#: states its band only in prose, "USD 72,000 gross per year" = 6000 USD * 0.9.
def _fixture() -> list[tuple[Offer, float | None]]:
    usd = Salary(min=60000, max=60000, currency="USD", period="year", stated=True)
    eur = Salary(min=3000, max=3000, currency="EUR", period="month", stated=True)
    week = Salary(min=800, max=800, currency="USD", period="week", stated=True)
    return [
        (_offer("usd-field", "A role. Remote.", usd), 4500.0),
        (_offer("eur-field", "A role. Remote.", eur), 3000.0),
        (_offer("usd-week", "A role. Remote.", week), 3120.0),
        (_offer("usd-text", "Salary: USD 72,000 gross per year. Remote.", None), 5400.0),
        (_offer("silent", "A role. Remote.", None), None),
    ]


def _audit(table: RateTable, *, settled: float | None = None) -> tuple[int, int]:
    """`(offers whose ranked pay is wrong, offers the audit compared)`.

    Compares every offer the ranking published, the frontier and the dominated
    alike: a mis-converted offer must not escape by being collapsed. `settled`
    gives every offer the same score on `remote`, which is what makes some of
    them dominated (the lower payers), so that population is exercised.
    """
    candidates: list[Candidate] = []
    expected: dict[str, float | None] = {}
    for offer, want in _fixture():
        candidate, _ = candidate_for(
            offer, _extraction(offer.id), dimensions=_DIMENSIONS, table=table
        )
        if settled is not None:
            candidate = replace(candidate, scores={"remote": settled}, unknown=frozenset())
        candidates.append(candidate)
        expected[offer.id] = want
    ranking = rank(
        candidates,
        dimensions=_DIMENSIONS,
        revision=_REVISION,
        weights=_WEIGHTS,
        at="T246",
        currency=table.target,
    )
    by_id = {c.offer_id: c for c in candidates}
    published = [*ranking["pareto"], *ranking["dominated"]]
    wrong = 0
    for offer_id in published:
        got, want = by_id[offer_id].salary_per_month, expected[offer_id]
        if (got is None) != (want is None) or (
            got is not None and want is not None and abs(got - want) > 1e-6
        ):
            wrong += 1
    return wrong, len(published)


def _unconverted(table: RateTable) -> int:
    return _audit(table)[0]


_NO_OP_USD = RateTable("EUR", (DatedRate("USD", 1.0, "2026-10-01", "planted: no-op"),))

#: How many states `_rank_refusals` evaluates. A committed floor, and the metric
#: carries any shortfall, so dropping a state from the list moves the number
#: instead of leaving a smaller audit reading as clean.
MINIMUM_REFUSAL_STATES = 8


def _planted_raw() -> int:
    """The same audit, fed what the old path produced: the USD figure unconverted."""
    return _unconverted(_NO_OP_USD)


def _read_refusals() -> int:
    """How many no-rate or no-calendar-factor states were read instead of refused."""
    unrefused = 0
    states = [
        _offer("a", "x", Salary(min=1, max=2, currency="USD", period="year", stated=True)),
        _offer("b", "x", Salary(min=1, max=2, currency="EUR", period="hour", stated=True)),
        _offer("c", "x", Salary(min=1, max=2, currency=None, period="year", stated=True)),
        _offer("d", "Salary: GBP 40,000 per year", None),
    ]
    for offer in states:
        try:
            read_pay(offer, RateTable("EUR"))
        except PayNormaliseError:
            continue
        unrefused += 1
    return unrefused


def _point(offer_id: str, salary: float, unit: str | None) -> Candidate:
    pay = None if unit is None else PayBand(salary, salary, unit)
    return Candidate(offer_id, salary, {}, frozenset(_DIMENSIONS), pay=pay)


#: What reaches `rank` itself, whatever door it came through, each of which must
#: be refused: `(candidates, weights, currency)`. A point with no band, or beside
#: a band in another currency, when the currency is known (L2 or `currency=`);
#: and with no currency at all (L1), a point with no band, a mix of bare and
#: banded points, and bands in two currencies.
def _rank_refusals() -> list[tuple[list[Candidate], dict[str, Any] | None, str | None]]:
    return [
        ([_point("f", 3000.0, None)], _WEIGHTS, "EUR"),
        ([_point("f", 3000.0, "USD")], _WEIGHTS, "EUR"),
        ([_point("f", 3000.0, None)], None, "EUR"),
        ([_point("f", 3000.0, "USD")], None, "EUR"),
        ([_point("f", 3000.0, None), _point("g", 3100.0, None)], None, None),
        ([_point("f", 3000.0, None), _point("g", 3100.0, "EUR")], None, None),
        ([_point("f", 3333.0, "USD"), _point("g", 3100.0, "EUR")], None, None),
        ([_point("f", 3333.0, None)], {"currency": "EUR", "part_worths": {}}, None),
    ]


def _refusals() -> dict[str, int]:
    accepted = 0
    states = _rank_refusals()
    for candidates, weights, currency in states:
        try:
            rank(
                candidates,
                dimensions=_DIMENSIONS,
                revision=_REVISION,
                weights=weights,
                at="T246",
                currency=currency,
            )
            accepted += 1
        except RankingError:
            pass
    return {
        "unrefused": _read_refusals(),
        "foreign_band_accepted": accepted,
        "states_checked": len(states),
    }


def measure() -> dict[str, Any]:
    refusals = _refusals()
    wrong, compared = _audit(_TABLE)
    wrong_settled, compared_settled = _audit(_TABLE, settled=0.5)
    shortfall = max(0, MINIMUM_REFUSAL_STATES - refusals["states_checked"])
    return {
        "unconverted_pay_reaching_rank": wrong
        + wrong_settled
        + refusals["unrefused"]
        + refusals["foreign_band_accepted"]
        + shortfall,
        # What the audit compared (frontier and dominated, both runs), not the
        # number of fixture rows.
        "offers_checked": compared + compared_settled,
        "refusal_states_checked": refusals["states_checked"],
        "unconverted_detected_when_planted": min(_planted_raw(), 1),
        "settled_run_detected_when_planted": min(_audit(_NO_OP_USD, settled=0.5)[0], 1),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure T246's pay normalisation.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)
    print(f"unconverted_pay_reaching_rank: {measured['unconverted_pay_reaching_rank']} (== 0)")
    print(f"unconverted_detected_when_planted: {measured['unconverted_detected_when_planted']}")
    print(f"settled_run_detected_when_planted: {measured['settled_run_detected_when_planted']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
