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
from integral.rank import DOMINATED_BY, Candidate, PayBand, rank

# §4.3's site: the pay rule is a constraint on the order §4.3 defines, so it is
# read at the same section rather than given one of its own.
METHODS_REF = "METHODS.md#43-offer-comparison--pareto-dominance-then-salary-equivalent-total"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T138.json"


def comparable_band(candidate: Candidate, currency: str | None) -> tuple[float, float] | None:
    """`(low, high)` in the ranking's numeraire, or `None` when nothing compares.

    Three sources, in order: the published band when it is in the ranking's own
    currency; otherwise the point reading `salary_per_month`, which the rest of
    the module already denominates in that currency; otherwise nothing.

    `None` is returned for a band in another currency and for an offer that
    published nothing — the two decided cases — and it is the *same* `None` on
    purpose. Both mean "this module has no comparison to make here", which is
    the only honest answer in either, and neither is a zero.
    """
    band = candidate.pay
    if band is not None:
        if currency is None or band.currency != currency:
            return None
        return (band.low, band.high)
    salary = candidate.salary_per_month
    if salary is None:
        return None
    return (salary, salary)


def pays_more(a: Candidate, b: Candidate, currency: str | None) -> bool:
    """Whether `a` pays more than `b` under every reading of both bands.

    Disjoint or nothing: `a.low > b.high`. An overlap leaves a reading under
    which `b` pays more, and a rule that resolved it would be choosing an end
    of a range the advert deliberately left open.
    """
    mine = comparable_band(a, currency)
    theirs = comparable_band(b, currency)
    if mine is None or theirs is None:
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

#: `(case, decided_row, id_of_the_richer, salary, band, id_of_the_poorer, salary, band)`.
#:
#: The ids are chosen so that **alphabetical order puts the poorer offer
#: first** in every claiming pair. An id-ordered tie is precisely the defect,
#: so a fixture whose ids happened to agree with the pay would go green over
#: it.
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
}


def _pair(case: str) -> tuple[Candidate, Candidate]:
    """The two candidates of one fixture pair — richer first, by construction."""
    row = next(entry for entry in _PAIRS if entry[0] == case)
    _, _, rich_id, rich_salary, rich_band, poor_id, poor_salary, poor_band = row
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


def _rank_pair(pair: Sequence[Candidate]) -> dict[str, Any]:
    return rank(
        list(pair),
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=len(_PAIRS), sha256="0" * 64),
        weights=_WEIGHTS,
        at="2026-09-07T00:00:00Z",
    )


def _swapped(ranking: Mapping[str, Any]) -> dict[str, Any]:
    """The same ranking with its published order reversed — nothing else moved."""
    return {**ranking, "pareto": list(reversed(list(ranking["pareto"])))}


def measure_pair(case: str) -> dict[str, Any]:
    """One pair's whole reading: what the rule said, and what the order did."""
    rich, poor = _pair(case)
    ranking = _rank_pair((rich, poor))
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
    """
    count = 0
    for entry in _PAIRS:
        rich, poor = _pair(entry[0])
        for mine, theirs in ((rich, poor), (poor, rich)):
            if comparable_band(mine, "EUR") is not None:
                continue
            if pays_more(mine, theirs, "EUR") or pays_more(theirs, mine, "EUR"):
                count += 1
    return count


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
