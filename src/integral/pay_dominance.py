"""T138 — paying more is a rule, not a weight.

From the owner, 2026-09-06: *"any user will prefer a job that pays more between
two similar jobs."* It was not a rule anywhere. Pay reached the ranking as one
signal among the others, so two offers alike in every respect but the salary
came back in either order and nothing caught it — measured on the ranker of
2026-09-07, an offer at 2000 was printed above an otherwise identical one at
5000, because a priced dimension unknown on both left both without a
salary-equivalent total and the tie broke on `offer_id`.

The rule is stated as **dominance**, not as a coefficient:

> where two offers are equal on every other ranked dimension, the higher-paying
> one is never ranked below the lower-paying one.

That is checkable without deciding what pay is worth against a commute — which
is a preference, and lives in T10's weights. `rank` satisfies it by breaking
the tie on the salary before the id; this module audits the published lists
from the outside and re-derives the rule from the candidates, so it can
disagree with the pass that produced them. `rank.dominance_violations` is the
same discipline for §4.3's Pareto rule and says why: a count the construction
hands itself can only ever be zero.

Three definitions carry the whole thing, and the last two are the decisions the
task refused to let fall out of the arithmetic.

**"Equal on every other ranked dimension"** means the same settled score on
every dimension *and* the same set of unknowns. Not because unknowns are
convenient to compare, but because this package holds that unknown is not
neutral: an advert that scores mentoring 0.5 and one that says nothing about
mentoring are not equal, they are incomparable, and a rule that treated them as
alike would be claiming exactly the thing `rank.dominates` refuses to claim.

**One of the two publishes no band.** Incomparable, in both directions. The
rule does not fire — and in particular it never concludes that the silent side
pays *less*. An unpublished salary is not a low one; 97 of 561 offers measured
2026-09-06 carried a band at all, so reading an absent number as zero would put
every offer from every board that does not publish beneath every offer from a
board that does. `comparable_band` returns `None` there, and
`absent_bands_read_as_zero` is the measured count of times that answer was
anything else.

**Different currencies, or a range against a point.** A point salary *is* a
band, the one whose ends coincide, so `€50.000-65.000` against `€60.000` is not
a second kind of comparison: it is `[50000, 65000]` against `[60000, 60000]`.
A claim is made only when the two bands are **disjoint** — `a.low > b.high`,
A's worst reading above B's best. Overlapping bands are incomparable, because
there is a reading of each under which the other pays more, and picking an end
would invent the figure the advert declined to give. Across currencies the
answer is also incomparable: converting needs a rate with a date and a source,
none lives in this repository, and `rank` already refuses to convert between
the weights' currency and the ranking's rather than guess one.

**Where the rule is silent, the order must be too** (second reader, 2026-09-08).
The tiebreak `rank` applies is this rule and nothing more, so between an offer
that published a salary and one that published none — a pair the rule refuses
in both directions — it may not fire. Sorting the silent side last is that
refusal thrown away at the last step: it is "an unpublished salary is a low
one", spelled as a sort key rather than as a comparison, and at 97 bands in 561
offers it would sink four offers in five beneath every tied offer from a board
that publishes. The alphabet decides there, because the alphabet claims nothing
about pay. `absent_salaries_demoted_in_a_tie` counts the departures.

**A contradiction is refused, not ordered.** Two inputs made the ranking and
this audit disagree about the same list, both fail-open, and `rank` now raises
on each rather than publishing an order neither can defend: a dimension the
weights price that the ranking does not rank (invisible to
`alike_apart_from_pay`, so a 2000 was published above an identical 5000 and
`violations` reported it), and a published band with no point reading in a
ranking that names no currency (the sort ranked it as unpaid; the audit could
not see it, because `comparable_band` used to read `None` as a currency that
disagreed with every band). `contradictions_refused` counts both refusals.

Scope: this module decides *order*, never inclusion. Nothing here collapses an
offer, and a pair the rule cannot compare keeps whatever place the rest of the
ranking gave it.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from integral.profile import ProfileRevision
from integral.rank import DOMINATED_BY, Candidate, PayBand, RankingError, rank

# §4.3's site: the pay rule is a constraint on the order §4.3 defines, so it is
# read at the same section rather than given one of its own.
METHODS_REF = "METHODS.md#43-offer-comparison--pareto-dominance-then-salary-equivalent-total"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T138.json"


def comparable_band(
    candidate: Candidate, currency: str | None
) -> tuple[float, float, str | None] | None:
    """`(low, high, numeraire)`, or `None` when there is nothing to compare.

    Three sources, in order: the published band, when the ranking's currency is
    the band's or the ranking names no currency at all; otherwise the point
    reading `salary_per_month`, which is denominated in whatever the ranking is
    denominated in; otherwise nothing. The numeraire travels with the reading so
    `pays_more` can refuse a pair whose two readings are not in the same money —
    the answer that used to be reached by returning `None` here.

    `None` is returned for a band in another currency and for an offer that
    published nothing — the two decided cases — and it is the *same* `None` on
    purpose. Both mean "this module has no comparison to make here", which is
    the only honest answer in either, and neither is a zero.

    **A ranking with no currency does not silence every band** (second reader,
    2026-09-08). `currency is None` used to return `None` for any band at all,
    which switched the rule off for exactly the ranking — L1, no weights — where
    `rank.require_pay_coherence` was switched off too: 27 of 70 comparable pairs
    came back inverted and the audit reported none of them, because the guard
    and the rule failed open together. A ranking that names no currency is not a
    ranking in some *other* currency; two bands that agree on theirs are as
    comparable there as anywhere.
    """
    band = candidate.pay
    if band is not None:
        if currency is not None and band.currency != currency:
            return None
        return (band.low, band.high, band.currency)
    salary = candidate.salary_per_month
    if salary is None:
        return None
    return (salary, salary, currency)


def pays_more(a: Candidate, b: Candidate, currency: str | None) -> bool:
    """Whether `a` pays more than `b` under every reading of both bands.

    Disjoint or nothing: `a.low > b.high`. An overlap leaves a reading under
    which `b` pays more, and a rule that resolved it would be choosing an end
    of a range the advert deliberately left open. And nothing at all unless the
    two readings are in the same money — across currencies converting needs a
    rate with a date and a source, and none lives in this repository.
    """
    mine = comparable_band(a, currency)
    theirs = comparable_band(b, currency)
    if mine is None or theirs is None:
        return False
    if mine[2] != theirs[2]:
        return False
    return mine[0] > theirs[1]


def alike_apart_from_pay(a: Candidate, b: Candidate, dimensions: Sequence[str]) -> bool:
    """Same settled score on every ranked dimension, and the same unknowns.

    The unknown sets have to match for the reason `rank.dominates` refuses a
    comparison touching one: a scored dimension and a silent one are not equal,
    so a pair that differed there would not be "alike apart from the pay" — it
    would be a pair this rule has no business ordering.
    """
    names = tuple(dimensions)
    if {name for name in a.unknown if name in names} != {
        name for name in b.unknown if name in names
    }:
        return False
    return all(
        a.scores[name] == b.scores[name] for name in names if name in a.scores and name in b.scores
    ) and all((name in a.scores) == (name in b.scores) for name in names)


def violations(ranking: Mapping[str, Any], candidates: Sequence[Candidate]) -> list[dict[str, Any]]:
    """Every place the published ranking puts the higher-paying offer lower.

    Read off `pareto` and `dominated` **as written**, with the rule re-derived
    from the candidates — the audit has to be able to contradict the pass that
    built the lists, or it is measuring its own construction.

    Two shapes count. An inversion inside the published order is the one the
    task names. A higher-paying offer collapsed *under* an alike one is the
    same failure at its worst: not printed lower, but not printed at all.
    """
    dimensions = tuple(ranking["dimensions"])
    currency = ranking.get("currency")
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    published = [by_id[offer_id] for offer_id in ranking["pareto"] if offer_id in by_id]

    found: list[dict[str, Any]] = []
    for index, above in enumerate(published):
        for below in published[index + 1 :]:
            if alike_apart_from_pay(above, below, dimensions) and pays_more(below, above, currency):
                found.append(
                    {
                        "kind": "printed_below",
                        "higher_paying": below.offer_id,
                        "placed_above_it": above.offer_id,
                    }
                )

    for offer_id, note in dict(ranking["dominated"]).items():
        mine = by_id.get(offer_id)
        collapser = by_id.get(str(note).removeprefix(DOMINATED_BY))
        if mine is None or collapser is None:
            continue
        if alike_apart_from_pay(mine, collapser, dimensions) and pays_more(
            mine, collapser, currency
        ):
            found.append(
                {
                    "kind": "collapsed_under",
                    "higher_paying": mine.offer_id,
                    "placed_above_it": collapser.offer_id,
                }
            )
    return found


# --------------------------------------------------------------------------
# The measurement.
#
# Every pair is one offer held fixed and the pay varied — the same scores, the
# same unknowns, the same ids — so a violation cannot be argued away as some
# other signal having moved. `mentoring` is unknown on both sides of every
# pair, which is deliberate and is the case the defect lived in: a priced
# dimension nobody settled leaves both offers without a salary-equivalent
# total, so the pay is the only thing left to order them by.
# --------------------------------------------------------------------------

_DIMENSIONS = ("commute", "mentoring", "remote")
_SCORES: dict[str, float] = {"commute": 0.2, "remote": 0.6}
_UNKNOWN = frozenset({"mentoring"})
_WEIGHTS: dict[str, Any] = {
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

#: `(case, decided_row, id_first, salary, band, id_second, salary, band, weighted)`.
#:
#: The ids are chosen so that **alphabetical order puts the poorer offer
#: first** in every claiming pair. An id-ordered tie is precisely the defect,
#: so a fixture whose ids happened to agree with the pay would go green over
#: it.
#:
#: `weighted` is the ranking the pair is measured under: `True` for T10's
#: weights in EUR (L2), `False` for no weights and no `currency=` argument at
#: all (L1). The second is not a variation for its own sake — it is the
#: ranking whose currency is `None`, where the guard and the rule were both
#: found switched off on 2026-09-08, so a fixture set that only ever ranked
#: under `_WEIGHTS` could not have seen it.
_PAIRS: tuple[
    tuple[
        str,
        str,
        str,
        float | None,
        PayBand | None,
        str,
        float | None,
        PayBand | None,
        bool,
    ],
    ...,
] = (
    (
        "two_published_bands_disjoint",
        "",
        "z-band-4100",
        4100.0,
        PayBand(4000.0, 4200.0, "EUR"),
        "a-band-3100",
        3100.0,
        PayBand(3000.0, 3200.0, "EUR"),
        True,
    ),
    (
        "two_point_salaries",
        "",
        "z-point-3800",
        3800.0,
        None,
        "a-point-3100",
        3100.0,
        None,
        True,
    ),
    (
        "a_range_against_a_point_disjoint",
        "different_currencies_or_a_range_against_a_point",
        "z-range-4200",
        4200.0,
        PayBand(4000.0, 4500.0, "EUR"),
        "a-point-3000",
        3000.0,
        PayBand(3000.0, 3000.0, "EUR"),
        True,
    ),
    (
        "a_range_against_a_point_overlapping",
        "different_currencies_or_a_range_against_a_point",
        "z-range-3400",
        3400.0,
        PayBand(3000.0, 3900.0, "EUR"),
        "a-point-3500",
        3500.0,
        PayBand(3500.0, 3500.0, "EUR"),
        True,
    ),
    (
        "different_currencies",
        "different_currencies_or_a_range_against_a_point",
        "z-usd-4100",
        None,
        PayBand(4000.0, 4200.0, "USD"),
        "a-eur-3100",
        3100.0,
        PayBand(3000.0, 3200.0, "EUR"),
        True,
    ),
    (
        "one_side_publishes_no_band",
        "one_side_publishes_no_band",
        "z-silent",
        None,
        None,
        "a-point-3000",
        3000.0,
        PayBand(3000.0, 3000.0, "EUR"),
        True,
    ),
    (
        "no_ranking_currency_two_published_bands",
        "a_ranking_that_names_no_currency",
        "z-noc-band-4100",
        4100.0,
        PayBand(4000.0, 4200.0, "EUR"),
        "a-noc-band-3100",
        3100.0,
        PayBand(3000.0, 3200.0, "EUR"),
        False,
    ),
    (
        "no_ranking_currency_overlapping_bands",
        "a_ranking_that_names_no_currency",
        "z-noc-span-3400",
        3400.0,
        PayBand(3000.0, 3900.0, "EUR"),
        "a-noc-point-3500",
        3500.0,
        PayBand(3500.0, 3500.0, "EUR"),
        False,
    ),
    (
        "a_silent_salary_against_a_published_one_in_one_tie_bucket",
        "an_absent_salary_keeps_the_place_the_alphabet_gave_it",
        "a-silent-tied",
        None,
        None,
        "z-point-2000",
        2000.0,
        None,
        True,
    ),
)

_DECIDED_BECAUSE = {
    "one_side_publishes_no_band": (
        "an unpublished salary is not a low one — 97 of 561 offers measured 2026-09-06 "
        "carried a band at all, so reading the absence as zero buries every board that "
        "does not publish"
    ),
    "different_currencies_or_a_range_against_a_point": (
        "a point is the band whose ends coincide, so a claim is made only when the two "
        "bands are disjoint; across currencies there is no claim at all, because "
        "converting needs a rate with a date and a source and none lives in this repository"
    ),
    "a_ranking_that_names_no_currency": (
        "a ranking with no currency is not a ranking in some other currency — two bands "
        "that agree on theirs compare there as anywhere, and reading `None` as a "
        "disagreement switched the rule off for exactly the L1 ranking where "
        "`rank.require_pay_coherence` was off too, so the guard and the rule failed open "
        "together"
    ),
    "an_absent_salary_keeps_the_place_the_alphabet_gave_it": (
        "the rule makes no claim between an offer that published a salary and one that "
        "did not, so the tiebreak the rule drives may make none either; sorting the "
        "silent side last reads the absence as a low number, and at 97 bands in 561 "
        "offers that buries four offers in five beneath every tied offer from a board "
        "that publishes"
    ),
}


def _row(case: str) -> tuple[Any, ...]:
    return next(entry for entry in _PAIRS if entry[0] == case)


def _pair(case: str) -> tuple[Candidate, Candidate]:
    """The two candidates of one fixture pair — richer first, by construction.

    "Richer" is by construction only where the pair claims. The silent-salary
    row has no richer side at all: it is the pair where one advert published a
    figure and the other published none, so what it fixes is the *place* the
    silent one keeps, not an order between two numbers.
    """
    _, _, rich_id, rich_salary, rich_band, poor_id, poor_salary, poor_band, _ = _row(case)
    return (
        Candidate(
            offer_id=rich_id,
            salary_per_month=rich_salary,
            scores=dict(_SCORES),
            unknown=_UNKNOWN,
            pay=rich_band,
        ),
        Candidate(
            offer_id=poor_id,
            salary_per_month=poor_salary,
            scores=dict(_SCORES),
            unknown=_UNKNOWN,
            pay=poor_band,
        ),
    )


def _rank_pair(pair: Sequence[Candidate], *, weighted: bool = True) -> dict[str, Any]:
    """The pair as `rank` publishes it, under T10's weights or under none.

    `weighted=False` is the L1 ranking with no `currency=` argument either, so
    `ranking["currency"]` is `None` — the configuration in which the pay guard
    and the pay rule were both found inert on 2026-09-08. Measuring only the
    weighted one is what let that hole sit behind a green gate.
    """
    return rank(
        list(pair),
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=len(_PAIRS), sha256="0" * 64),
        weights=_WEIGHTS if weighted else None,
        at="2026-09-07T00:00:00Z",
    )


def _swapped(ranking: Mapping[str, Any]) -> dict[str, Any]:
    """The same ranking with its published order reversed — nothing else moved."""
    return {**ranking, "pareto": list(reversed(list(ranking["pareto"])))}


def measure_pair(case: str) -> dict[str, Any]:
    """One pair's whole reading: what the rule said, and what the order did."""
    rich, poor = _pair(case)
    ranking = _rank_pair((rich, poor), weighted=bool(_row(case)[8]))
    currency = ranking["currency"]
    claimed = pays_more(rich, poor, currency) or pays_more(poor, rich, currency)
    return {
        "case": case,
        "alike_apart_from_pay": alike_apart_from_pay(rich, poor, _DIMENSIONS),
        "pay_dominance_claimed": int(claimed),
        "violations": len(violations(ranking, [rich, poor])),
        # Reverse the published order and audit again. On a claiming pair the
        # count must rise — a rule that cannot be broken is not being checked.
        # On an incomparable pair it must stay at zero in *both* orders, which
        # is what "incomparable" has to mean if it means anything.
        "violations_when_the_order_is_reversed": len(violations(_swapped(ranking), [rich, poor])),
        "published_order": list(ranking["pareto"]),
        "salary_equivalent_totals": len(ranking["salary_equivalent_total"]),
        "level": ranking["level"],
        "ranking_currency": ranking["currency"],
    }


def _decided_row(name: str, readings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [reading for reading, entry in zip(readings, _PAIRS, strict=True) if entry[1] == name]
    claims = sum(int(row["pay_dominance_claimed"]) for row in rows)
    return {
        "case": name,
        "because": _DECIDED_BECAUSE[name],
        "pairs": len(rows),
        "pay_dominance_claimed": claims,
        "violations": sum(int(row["violations"]) for row in rows),
        # The claiming pairs must each break when reversed, and the
        # incomparable ones must not break in either direction. Both halves are
        # counted so neither can be satisfied by the rule simply never firing.
        "claiming_pairs_broken_when_reversed": sum(
            1
            for row in rows
            if row["pay_dominance_claimed"] and row["violations_when_the_order_is_reversed"]
        ),
        "incomparable_pairs_clean_in_either_order": sum(
            1
            for row in rows
            if not row["pay_dominance_claimed"]
            and not row["violations"]
            and not row["violations_when_the_order_is_reversed"]
        ),
    }


def absent_bands_read_as_zero(readings: Sequence[Mapping[str, Any]]) -> int:
    """How often a side that published nothing was compared as if it were zero.

    Asked of the rule directly rather than inferred from the order: a `0` that
    only ever meant "the pair happened to sort the right way" would say nothing
    about whether the absence was read as a number.

    Asked under **both** rankings — the one denominated in EUR and the one that
    names no currency at all — since `comparable_band` now reads a band under
    either, and a widening is exactly the kind of change that could start
    reading an absence as a figure in the case nobody measured.
    """
    count = 0
    for currency in ("EUR", None):
        for entry in _PAIRS:
            rich, poor = _pair(entry[0])
            for mine, theirs in ((rich, poor), (poor, rich)):
                if comparable_band(mine, currency) is not None:
                    continue
                if pays_more(mine, theirs, currency) or pays_more(theirs, mine, currency):
                    count += 1
    return count


def absent_salaries_demoted_in_a_tie(readings: Sequence[Mapping[str, Any]]) -> int:
    """How often an offer that published no salary was moved down a tie it shares.

    The decided case, and the one this module had left to the sort (second
    reader, 2026-09-08). Counted only where the primary quantity ties the two —
    an L2 bucket in which neither side has a salary-equivalent total — because
    that is the only place the pay tiebreak, rather than the ranking proper,
    decides the order. There the rule makes no claim in either direction, so
    the order it drives may make none either: what is left is the alphabet,
    which claims nothing about pay, and a departure from it is this count.

    The opposite reading is what a plain `-salary` sort key does, and it is the
    same mistake `absent_bands_read_as_zero` counts one layer up: it sinks the
    silent side, which is "an unpublished salary is a low one" spelled as a
    sort. 97 of 561 offers measured 2026-09-06 published a band at all.
    """
    count = 0
    for entry, reading in zip(_PAIRS, readings, strict=True):
        if reading["level"] != "L2" or reading["salary_equivalent_totals"]:
            continue
        first, second = _pair(entry[0])
        for silent, other in ((first, second), (second, first)):
            if silent.salary_per_month is not None or silent.pay is not None:
                continue
            order = list(reading["published_order"])
            alphabet_puts_it_first = silent.offer_id < other.offer_id
            printed_below = order.index(silent.offer_id) > order.index(other.offer_id)
            if alphabet_puts_it_first and printed_below:
                count += 1
    return count


#: T10's weights with one part-worth `_DIMENSIONS` does not name. Priced and
#: unranked is the shape `rank.require_priced_dimensions_ranked` refuses: it
#: drives the order while `alike_apart_from_pay` cannot see it, so the ranking
#: and its own audit end up disagreeing about the same list.
_WEIGHTS_PRICING_AN_UNRANKED_DIMENSION: dict[str, Any] = {
    **_WEIGHTS,
    "part_worths": {
        **_WEIGHTS["part_worths"],
        "perks": {"utility_per_unit": 0.5, "salary_equivalent_per_month": 5000.0},
    },
}


def _refuses(candidates: Sequence[Candidate], *, weights: Mapping[str, Any] | None) -> int:
    """1 when `rank` refuses these inputs, 0 when it publishes a ranking of them."""
    try:
        rank(
            list(candidates),
            dimensions=_DIMENSIONS,
            revision=ProfileRevision(rows=len(_PAIRS), sha256="0" * 64),
            weights=weights,
            at="2026-09-07T00:00:00Z",
        )
    except RankingError:
        return 1
    return 0


def contradictions_refused() -> dict[str, int]:
    """The two inputs on which the ranking and this audit used to disagree.

    Both were fail-open, and both were found by a second reader on 2026-09-08
    rather than by this module — which is why they are committed here as
    numbers instead of answered in prose.

    `a_dimension_priced_but_not_ranked` — the weights price `perks`, the
    ranking ranks `_DIMENSIONS`, and nothing tied the two sets together. A 2000
    scoring `perks: 1.0` was published above an otherwise identical 5000, and
    `violations` then reported `1` against that very list: the module
    contradicting itself, in the fail-open direction, over a ranking a
    candidate would have read.

    `a_published_band_with_no_point_where_the_ranking_names_no_currency` — a
    `4000-4200 EUR` band with no point reading, in an L1 ranking with no
    weights. `require_pay_coherence` skipped it because the ranking's currency
    was `None`, so it sorted last, beneath a published `3000`, while the audit
    stayed silent because its own rule was off for the same `None`. A guard
    that is right and never reached is not a guard.

    A refusal, not a repair: neither input has an order this module could
    publish honestly, and inventing one is the thing every decision above says
    not to do.
    """
    priced_but_unranked = (
        Candidate(
            offer_id="a-unranked-2000",
            salary_per_month=2000.0,
            scores={**_SCORES, "perks": 1.0},
            unknown=_UNKNOWN,
        ),
        Candidate(
            offer_id="z-unranked-5000",
            salary_per_month=5000.0,
            scores={**_SCORES, "perks": 0.0},
            unknown=_UNKNOWN,
        ),
    )
    band_without_a_point = (
        Candidate(
            offer_id="z-band-with-no-point",
            salary_per_month=None,
            scores=dict(_SCORES),
            unknown=_UNKNOWN,
            pay=PayBand(4000.0, 4200.0, "EUR"),
        ),
        Candidate(
            offer_id="a-point-3000-again",
            salary_per_month=3000.0,
            scores=dict(_SCORES),
            unknown=_UNKNOWN,
            pay=PayBand(3000.0, 3000.0, "EUR"),
        ),
    )
    return {
        "a_dimension_priced_but_not_ranked": _refuses(
            priced_but_unranked, weights=_WEIGHTS_PRICING_AN_UNRANKED_DIMENSION
        ),
        "a_published_band_with_no_point_where_the_ranking_names_no_currency": _refuses(
            band_without_a_point, weights=None
        ),
    }


def measure() -> dict[str, Any]:
    """The gate's numbers: the violation count, and the proof it can rise."""
    readings = [measure_pair(entry[0]) for entry in _PAIRS]
    claiming = [row for row in readings if row["pay_dominance_claimed"]]
    return {
        "pay_dominance_violations": sum(int(row["violations"]) for row in readings),
        "pairs_compared": len(readings),
        # A rule that never fires is satisfied by any ranking at all, so the
        # denominator is committed beside the count. `_main` fails on a zero
        # here exactly as it fails on a violation.
        "pairs_where_pay_dominance_is_claimed": len(claiming),
        "claiming_pairs_broken_when_reversed": sum(
            1 for row in claiming if row["violations_when_the_order_is_reversed"]
        ),
        "absent_bands_read_as_zero": absent_bands_read_as_zero(readings),
        "absent_salaries_demoted_in_a_tie": absent_salaries_demoted_in_a_tie(readings),
        "contradictions_refused": contradictions_refused(),
        "decided_cases": [_decided_row(name, readings) for name in sorted(_DECIDED_BECAUSE)],
        "pairs": readings,
        "gate_status": "measured",
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T138's pay-dominance rule.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    print(f"pay_dominance_violations: {measured['pay_dominance_violations']} (== 0)")
    print(
        f"pairs_where_pay_dominance_is_claimed: {measured['pairs_where_pay_dominance_is_claimed']}"
    )
    print(f"absent_bands_read_as_zero: {measured['absent_bands_read_as_zero']} (== 0)")
    print(
        f"absent_salaries_demoted_in_a_tie: {measured['absent_salaries_demoted_in_a_tie']} (== 0)"
    )
    for name, refused in sorted(measured["contradictions_refused"].items()):
        print(f"refused {name}: {refused} (== 1)")

    if measured["pay_dominance_violations"] != 0:
        return 1
    if not measured["pairs_where_pay_dominance_is_claimed"]:
        print(
            "the rule fired on no pair at all — a zero over an empty set is not a pass",
            file=sys.stderr,
        )
        return 1
    if (
        measured["claiming_pairs_broken_when_reversed"]
        != measured["pairs_where_pay_dominance_is_claimed"]
    ):
        print(
            "reversing a claiming pair did not raise the count — the audit is not reading "
            "the published order",
            file=sys.stderr,
        )
        return 1
    if measured["absent_bands_read_as_zero"]:
        print("a side that published no band was compared as a number", file=sys.stderr)
        return 1
    if measured["absent_salaries_demoted_in_a_tie"]:
        print(
            "an offer that published no salary was sorted below one that did, inside a tie "
            "the rule makes no claim about — that is the absence read as a low number",
            file=sys.stderr,
        )
        return 1
    for name, refused in sorted(measured["contradictions_refused"].items()):
        if not refused:
            print(
                f"{name}: rank published a ranking this audit would contradict, instead of "
                "refusing the input",
                file=sys.stderr,
            )
            return 1
    for row in measured["decided_cases"]:
        if row["violations"]:
            print(f"{row['case']}: {row['violations']} violation(s)", file=sys.stderr)
            return 1
        if (
            row["incomparable_pairs_clean_in_either_order"]
            != row["pairs"] - row["pay_dominance_claimed"]
        ):
            print(
                f"{row['case']}: an incomparable pair was scored in one order and not the other",
                file=sys.stderr,
            )
            return 1
    return 0


def main() -> int:  # pragma: no cover - thin argv shim
    return _main(sys.argv[1:])


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
