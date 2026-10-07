"""T18 — the Pareto frontier, the salary-equivalent order, and the facet lists.

`docs/METHODS.md` §4.3 in two moves. Offer A **dominates** B when A is at least
as good on every axis and strictly better on at least one; dominated offers
collapse, and what is left — the non-dominated set — is what gets shown,
because within it there is no objectively correct order, only trade-offs that
are the candidate's to make. Ordering *within* the frontier uses the
salary-equivalent total, `salary + sum_d weight(d) * score(d)`, which orders a
list and is never shown alone.

Four decisions worth stating.

**Unknown is not neutral, and that governs dominance.** An advert that does not
mention mentoring has not said mentoring is average; it has said nothing. So a
dimension that either side leaves unsettled makes the comparison
*incomparable*, and no dominance is claimed. Scoring an unknown as 0.0 would be
the opposite: it would collapse the quieter advert, and a collapsed offer is
one the candidate never sees. That is what
`test_unknown_dimension_is_not_treated_as_neutral` pins, and it is why
`Candidate` carries `unknown` as its own field rather than leaving a gap in
`scores` for a reader to interpret.

**Money is one of the axes.** Not only the numeraire the weights convert into:
without salary in the comparison an advert paying a third as much for the same
work would sit on the frontier untouched. An unstated salary blocks a dominance
claim exactly as an unstated dimension does.

**An offer missing a priced dimension gets no total, not a shorter one.** A sum
over fewer terms is a different quantity and orders differently — it sits
closer to the bare salary, so an advert that says little would outrank one that
says something bad. The offer keeps its place on the frontier; what it does not
get is a number pretending to be comparable with the others.

**The level is computed, never asserted.** L2 needs weights that actually carry
part-worths — T10 writes `weights.json` even while empty, so the file's
existence proves nothing (`step_runtime._weights_fitted` reads it the same
way). Without them the ranking is L1 and says so, ordered by salary alone.
"A provisional ranking that is not labelled provisional is a defect, not a
shortcut."

**Paying more is a rule, not a weight (T138).** Two offers alike on every other
ranked dimension used to come back in either order whenever neither had a
salary-equivalent total — a priced dimension unknown on both leaves both totals
`None`, both fall into the same bucket, and the tie broke on `offer_id`. So the
2000 of an otherwise identical pair could be printed above the 5000. The order
now breaks that tie on the salary itself, which makes "where two offers are
equal on every other ranked dimension, the higher-paying one is never below the
lower-paying one" a property of the sort rather than an accident of the
alphabet. It costs no coefficient: nothing here decides what pay is worth
against a commute, which is a preference and lives in T10's weights.
`integral.pay_dominance` audits the published order against that rule from the
outside, and `require_pay_coherence` is what makes the two agree — a published
band has to carry a point reading inside it, or the number the sort uses would
contradict the band the rule reads. `require_priced_dimensions_ranked` closes
the other side of the same joint: a dimension the weights price but the ranking
does not rank moves the order while the rule cannot see it, so the two disagree
about the same list. The tiebreak reorders only the offers that published a
salary (`_pay_before_the_alphabet`); a silent one keeps its place, because the
rule makes no claim about it and neither may the order.

Scope: `explanations` — the per-driver €/month contributions and their verbatim
spans — belong to T19 (`integral.explain`), and the offer card to T44. This
module produces the `rankings/<run_id>.json` those read, and carries each
score's spans on `Candidate` so T19 has the advert's wording to cite.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations, product
from pathlib import Path
from typing import Any

from integral.eligibility import Reading
from integral.extraction import OfferExtraction
from integral.identity import ProfileStore
from integral.profile import ProfileRevision
from integral.session import Sufficiency

# §4.3's site: the dominance test, the frontier, and the salary-equivalent order.
METHODS_REF = "METHODS.md#43-offer-comparison--pareto-dominance-then-salary-equivalent-total"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T18.json"
DEFAULT_T79_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T79.json"
DEFAULT_T242_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T242.json"
DEFAULT_T233_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T233.json"

#: How `rankings/<run_id>.json` names an offer's collapser (spec §5.5).
DOMINATED_BY = "dominated_by:"


class RankingError(Exception):
    """The inputs do not support the ranking that was asked for."""


#: A currency is an ISO 4217 code, matching `pay.CURRENCY_PATTERN`. Written out
#: here rather than imported so this module keeps its one-way dependency on
#: nothing but the extraction and profile types.
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


@dataclass(frozen=True)
class PayBand:
    """What the advert published, as T133's `range_low`/`range_high`/`currency`.

    A point salary is the band whose ends coincide, so "a range against a
    point" is not a second kind of comparison — it is this one with
    `low == high` on one side. The third state is `Candidate.pay is None`: the
    advert published no band at all, which is the common case (97 of 561
    offers measured 2026-09-06 carried one) and is **not** a band of zero.
    Reading it as zero would put every offer from a board that does not
    publish below every offer from a board that does.
    """

    low: float
    high: float
    currency: str

    def __post_init__(self) -> None:
        if self.high < self.low:
            raise RankingError(f"a band cannot end below where it starts: {self.low}-{self.high}")
        if not _CURRENCY_RE.match(self.currency):
            raise RankingError(f"{self.currency!r} is not an ISO 4217 code")


@dataclass(frozen=True)
class Candidate:
    """One offer as the ranker sees it: money, settled scores, and the gaps.

    `unknown` is carried rather than inferred from a missing key in `scores`,
    so "the advert does not say" is a fact this type states and not one every
    reader has to reconstruct. `OfferExtraction.unsettled` is where it comes
    from, and that field exists for the same reason.
    """

    offer_id: str
    salary_per_month: float | None
    scores: Mapping[str, float]
    unknown: frozenset[str] = field(default_factory=frozenset)
    # The advert's own words for each score, carried here rather than fetched
    # later because T19's explanation has to cite the text the score was read
    # from — and after the ranking, the advert is gone. Empty is allowed and is
    # not silently fine: `explained_fraction` is the measurement of how often it
    # happens, so a score with no wording behind it shows up as a number instead
    # of being rejected at a point where nothing could yet be done about it.
    spans: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    # T138. The band the advert published, when it published one. `None` is not
    # "zero" and not "unknown to us" — it is "the advert gave no band", and
    # `pay_dominance.comparable_band` then falls back to `salary_per_month` as
    # a point publication in the ranking's own numeraire. Carried beside
    # `salary_per_month` rather than replacing it because the two answer
    # different questions: this one is what was published, that one is the
    # figure every other comparison in this module is denominated in.
    pay: PayBand | None = None

    def __post_init__(self) -> None:
        overlap = set(self.scores) & self.unknown
        if overlap:
            raise RankingError(f"{sorted(overlap)} are both scored and unknown on {self.offer_id}")


def point_band(salary: float | None, currency: str) -> PayBand | None:
    """A point reading as the band whose ends coincide, in `currency` (T246).

    **It asserts that the figure is already in `currency`; it converts nothing.**
    A figure read from an advert goes through `integral.pay_normalise.candidate_for`.
    This is for callers that hold a number they already know the unit of.

    `salary_per_month` has no unit of its own, so a point enters a ranking with
    a known currency only beside a band in that currency; this is the band a
    point salary *is* (`PayBand`'s docstring), for callers that hold one figure.
    """
    return None if salary is None else PayBand(salary, salary, currency)


def from_extraction(
    extraction: OfferExtraction,
    *,
    dimensions: Sequence[str],
    salary_per_month: float | None,
) -> Candidate:
    """Read T15's extraction as a ranking candidate.

    Every dimension the ranking considers and this extraction did not settle
    is unknown — including one it never looked at. An extraction that simply
    omitted a dimension would otherwise reach the frontier as a gap nobody
    named, which is the same silence `unsettled` exists to break.
    """
    scored = {
        score.dimension: score.value
        for score in extraction.scores
        if score.dimension in set(dimensions)
    }
    return Candidate(
        offer_id=extraction.offer_id,
        salary_per_month=salary_per_month,
        scores=scored,
        unknown=frozenset(name for name in dimensions if name not in scored),
        spans={
            score.dimension: tuple(span.quote for span in score.spans)
            for score in extraction.scores
            if score.dimension in scored
        },
    )


#: T244: the three fit components `integral.fit` carries, one dimension each.
#: `integral.fit` asserts at import that these are `FitReading`'s fields.
FIT_DIMENSIONS = ("fit_stack", "fit_seniority", "fit_english")
_PAIRWISE = frozenset(FIT_DIMENSIONS)


def dominates(
    a: Candidate,
    b: Candidate,
    dimensions: Sequence[str],
    signs: Mapping[str, float] | None = None,
) -> bool:
    """Whether `a` is at least as good everywhere and better somewhere.

    `signs` (T243) says which way is better on a dimension: `-1` where the
    candidate's price on it is negative ("spoken English costs me"), so the
    offer asking for less English is the better one on that axis. A score is
    the advert's level on a dimension, not a verdict, and treating a higher
    level as better everywhere collapsed the very offer a priced dislike
    prefers. A dimension absent from `signs` keeps the older reading (higher
    is better) — the direction of an unpriced dimension is not known.

    Returns False the moment any axis is unknown on either side: the claim
    "at least as good on every dimension" cannot be made about a dimension
    nobody has a value for, and a dominance rule that guessed would be
    deciding what the candidate never gets shown.
    """
    if a.salary_per_month is None or b.salary_per_month is None:
        return False
    # T244: a fit component silent on exactly one side blocks the claim like any
    # other axis — A's silence is not "no worse than" B's statement. It is skipped
    # only when both sides are silent: nothing is said on either, so nothing is
    # compared, and the components both state still are.
    if any(
        (name in a.unknown) != (name in b.unknown)
        if name in _PAIRWISE
        else (name in a.unknown or name in b.unknown)
        for name in dimensions
    ):
        return False
    compared = [name for name in dimensions if name not in a.unknown]
    way = signs or {}
    pairs = [(a.salary_per_month, b.salary_per_month)] + [
        (way.get(name, 1.0) * a.scores[name], way.get(name, 1.0) * b.scores[name])
        for name in compared
    ]
    return all(mine >= theirs for mine, theirs in pairs) and any(
        mine > theirs for mine, theirs in pairs
    )


def require_coverage(candidates: Sequence[Candidate], dimensions: Sequence[str]) -> None:
    """Every candidate must account for every dimension the ranking considers.

    `unknown` defaults to empty, so a dimension can otherwise be absent from
    both fields — neither a score nor an admission that the advert was silent.
    That is the third state this module exists to abolish, and it fails
    quietly: `salary_equivalent_total` would sum the shorter list, and
    `dominates` would raise `KeyError` on the missing key. Checked once here,
    where the dimension set is known, rather than at each use.
    """
    for candidate in candidates:
        missing = [
            name
            for name in dimensions
            if name not in candidate.scores and name not in candidate.unknown
        ]
        if missing:
            raise RankingError(
                f"{candidate.offer_id} accounts for neither a score nor an unknown on "
                f"{missing} — a dimension nobody looked at is still an unknown, and "
                "has to be named as one"
            )


def require_priced_dimensions_ranked(
    dimensions: Sequence[str], priced: Mapping[str, float]
) -> None:
    """Every dimension the weights price has to be one the ranking ranks.

    T138's rule reads "equal on every other **ranked** dimension" off
    `dimensions`, and the order is `salary_equivalent_total`, which sums over
    the **priced** ones. A dimension priced but not ranked drives the order
    while being invisible to the rule, so two offers the rule calls alike can
    have totals hundreds of euros apart: measured 2026-09-08, a 2000 priced at
    `perks: 1.0` was printed above an otherwise identical 5000, and
    `pay_dominance.violations` then reported `1` against a ranking this
    function's caller had just produced. Neither half was wrong on its own —
    nothing tied the two sets together, so the module contradicted itself.

    Checked here rather than in `priced_dimensions` or `salary_equivalent_total`
    because neither of those is told the ranked set; `rank` is the one place
    that holds both, and it holds them before anything reads either. The
    opposite inclusion is deliberately free: a ranked dimension with no price
    is what makes a total `None`, which the level and the tiebreak already
    handle.
    """
    unranked = sorted(name for name in priced if name not in set(dimensions))
    if unranked:
        raise RankingError(
            f"the weights price {', '.join(unranked)}, which the ranking does not rank — "
            "the order would move on a dimension the pay rule cannot see, so a lower-paying "
            "offer could be printed above an otherwise identical one and read as alike"
        )


def require_pay_coherence(candidates: Sequence[Candidate], currency: str | None) -> None:
    """A band published in the ranking's own currency must carry a point inside it.

    T138's rule is read off the *band* (`pay_dominance.pays_more`) and enforced
    by the *sort*, which orders on `salary_per_month`. The two agree only while
    the point lies inside the band: given `a.low > b.high` and each point
    inside its own band, `a.salary >= a.low > b.high >= b.salary`, so the sort
    cannot place the higher-paying offer below. Drop either half of that and
    the guarantee goes with it — a band with no point would sort last however
    much it pays, and a point outside its band would order by a number the
    advert contradicts.

    **A point reading must carry the ranking's currency (T246).** When the
    currency is known, a candidate with a `salary_per_month` and no band in that
    currency is refused: the number has no unit of its own, so a bare point or a
    point beside a foreign band would be sorted as if it were this one. A band
    with no point is silent to the sort, so it stays incomparable and is let
    through. This is a rule on what reaches the sort, not on one entry path.
    With no currency at all the points must still agree: see the first block.
    Checked once, here, where the currency is known — `require_coverage`'s
    reason, one axis over.

    **A ranking with no currency at all checks every band** (T138, second
    reader, 2026-09-08). An L1 ranking with no weights and no `currency=`
    argument has `None` here, and skipping on `None` used to switch the whole
    guard off — a `4000-4200 EUR` band with no point reading sorted last,
    beneath a published `3000`, and `pay_dominance` reported nothing because
    its rule was off for the same reason. `None` is not a currency that
    disagrees with the band; it is the absence of one to disagree with, and the
    argument above never mentions the currency: the sort orders on the point,
    so a band with no point is ranked as if unpaid whatever it is denominated
    in.
    """
    if currency is None:
        # T246: a ranking that names no currency takes the single one every
        # point's band agrees on, and refuses a point with no band or bands in
        # two currencies — L1 orders on the point alone, so a mixed or unlabelled
        # set is exactly the comparison of unconverted pay this module refuses.
        units = {
            candidate.pay.currency if candidate.pay is not None else None
            for candidate in candidates
            if candidate.salary_per_month is not None
        }
        if None in units or len(units) > 1:
            raise RankingError(
                "the ranking names no currency and its pay points do not agree on one "
                f"({sorted(unit or 'no band' for unit in units)}) — convert them first "
                "(`integral.pay_normalise.candidate_for`), never compare them as they are"
            )
    for candidate in candidates:
        band = candidate.pay
        # T246: when the ranking's currency is known, a point reading must
        # arrive with its unit — a band in that currency. `salary_per_month`
        # carries none, so a bare point (or one beside a band in another
        # currency) would be compared as if it were this one. A band with no
        # point is silent to the sort and stays incomparable (T138).
        if (
            currency is not None
            and candidate.salary_per_month is not None
            and (band is None or band.currency != currency)
        ):
            raise RankingError(
                f"{candidate.offer_id} is ranked at {candidate.salary_per_month} with "
                f"{'no band' if band is None else f'a {band.currency} band'} in a {currency} "
                "ranking — convert it first (`integral.pay_normalise.candidate_for`), "
                "never compare it as is"
            )
        if band is None or (currency is not None and band.currency != currency):
            continue
        salary = candidate.salary_per_month
        if salary is None:
            raise RankingError(
                f"{candidate.offer_id} publishes a {band.currency} band and no point reading "
                "of it — the ranking orders on the point, so the band would be ranked as if "
                "unpaid"
            )
        if not band.low <= salary <= band.high:
            raise RankingError(
                f"{candidate.offer_id} is ranked at {salary} against a published band of "
                f"{band.low}-{band.high} {band.currency} — the order would contradict the advert"
            )


def frontier(
    candidates: Sequence[Candidate],
    dimensions: Sequence[str],
    signs: Mapping[str, float] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """`(non-dominated ids, {dominated id: "dominated_by:<id>"})`.

    The collapser is named rather than counted: "this one is out" is not an
    answer a candidate can argue with, and T19's explanation needs somewhere
    to start.
    """
    require_coverage(candidates, dimensions)
    kept: list[str] = []
    dominated: dict[str, str] = {}
    for mine in candidates:
        collapser = next(
            (other for other in candidates if dominates(other, mine, dimensions, signs)),
            None,
        )
        if collapser is None:
            kept.append(mine.offer_id)
        else:
            dominated[mine.offer_id] = f"{DOMINATED_BY}{collapser.offer_id}"
    return kept, dominated


def _read_part_worths(weights: Mapping[str, Any] | None, key: str) -> dict[str, float]:
    if not isinstance(weights, Mapping):
        return {}
    part_worths = weights.get(key)
    if not isinstance(part_worths, Mapping):
        return {}
    priced: dict[str, float] = {}
    for name, part in part_worths.items():
        if not isinstance(part, Mapping) or "salary_equivalent_per_month" not in part:
            raise RankingError(
                f"weights.json prices {name!r} in a shape this cannot read — expected "
                "T10's {'salary_equivalent_per_month': ...}"
            )
        priced[name] = float(part["salary_equivalent_per_month"])
    return priced


def _stated_in_force(weights: Mapping[str, Any] | None) -> dict[str, float]:
    """Stated figures whose own currency is the weights' currency, and no others.

    A statement's currency never sets the currency of anything: with no
    top-level `currency` on the weights nothing stated is in force.
    """
    if not isinstance(weights, Mapping):
        return {}
    currency = weights.get("currency")
    entries = weights.get("stated_part_worths")
    if not isinstance(currency, str) or not isinstance(entries, Mapping):
        return {}
    in_force = {
        name: part
        for name, part in entries.items()
        if isinstance(part, Mapping) and part.get("currency") == currency
    }
    return _read_part_worths({"stated_part_worths": in_force}, "stated_part_worths")


def weights_for_currency(
    weights: Mapping[str, Any] | None, currency: str | None
) -> dict[str, Any] | None:
    """B1: the weights as the ranking in `currency` may use them.

    The ranking's currency is the fit's (when the choices priced anything) or the
    caller's `currency=`, exactly as before stated prices existed. A stated price
    whose currency differs — or any stated price when neither names a currency —
    is moved to `stated_skipped` as `currency`; it is never priced and never
    converted. When stated figures survive and no fit fixed a currency, the
    result carries the caller's as `currency`, which `priced_dimensions` then
    matches each figure against. Idempotent.
    """
    if not isinstance(weights, Mapping):
        return None
    fitted_priced = bool(_read_part_worths(weights, "part_worths"))
    base = weights.get("currency") if fitted_priced else currency
    base = base if isinstance(base, str) else None
    entries = weights.get("stated_part_worths")
    if not isinstance(entries, Mapping) or not entries:
        return dict(weights)
    keep = {n: p for n, p in entries.items() if base is not None and p.get("currency") == base}
    skipped = dict(weights.get("stated_skipped") or {})
    # Two different facts, two reasons: a figure in the wrong currency, and a
    # ranking that has no currency for any figure to be in.
    skipped.update(
        {n: ("currency" if base is not None else "no_currency") for n in entries if n not in keep}
    )
    resolved = {**weights, "stated_part_worths": keep, "stated_skipped": skipped}
    if not fitted_priced and keep:
        resolved["currency"] = base
    return resolved


def priced_dimensions(weights: Mapping[str, Any] | None) -> dict[str, float]:
    """`{dimension: euros per month per unit of score}` from `weights.json`.

    Read through one function rather than at each use, so the shape the weights
    step writes has a single reader here. A file with no part-worths yields
    `{}`, which is what makes the ranking L1.

    T243: two sources, one reading. `part_worths` are T10's fitted figures;
    `stated_part_worths` are the coarse figures a candidate's own statements
    produce (`integral.weights.stated_part_worths`). A dimension in both is
    priced by the fitted one — measured beats said — which the weights file
    already enforces and this repeats, so a hand-built file cannot reverse it.
    """
    return {**_stated_in_force(weights), **_read_part_worths(weights, "part_worths")}


def dimension_signs(weights: Mapping[str, Any] | None) -> dict[str, float]:
    """T243: `-1.0` on each dimension the weights price negatively, `+1.0` on the rest priced.

    Published on the ranking as `dimension_signs` for a reader's benefit only.
    `dominance_violations` never reads that copy: it derives the signs again
    from the weights it is handed.
    """
    return {
        name: (-1.0 if euros < 0 else 1.0) for name, euros in priced_dimensions(weights).items()
    }


def priced_by(weights: Mapping[str, Any] | None) -> dict[str, list[str]]:
    """T243: which dimensions are priced by choices and which by statements."""
    fitted = _read_part_worths(weights, "part_worths")
    stated = _stated_in_force(weights)
    return {
        "fitted": sorted(fitted),
        "stated": sorted(name for name in stated if name not in fitted),
    }


def rankable_dimensions(
    dimensions: Sequence[str], weights: Mapping[str, Any] | None, currency: str | None = None
) -> list[str]:
    """T243: the ranked dimensions plus every dimension the weights price.

    `require_priced_dimensions_ranked` refuses a priced dimension the ranking
    does not rank, so a caller that built its dimension list before a candidate
    said something would otherwise fail on the first statement. Build the
    candidates and call `rank` with this list.
    """
    priced = priced_dimensions(weights_for_currency(weights, currency))
    return [*dimensions, *sorted(set(priced) - set(dimensions))]


UNPRICED_NO_CHOICE = "no_choice_and_no_statement"
UNPRICED_NEGLIGIBLE = "negligible_in_choices"
UNPRICED_CURRENCY = "stated_in_another_currency"
UNPRICED_NO_CURRENCY = "stated_with_no_currency_known"


def unpriced_trait_dimensions(
    traits: Mapping[str, Any] | None, weights: Mapping[str, Any] | None
) -> dict[str, Any]:
    """T243: every trait dimension with evidence that the order cannot move on, by name.

    `traits` is `traits.json`. A dimension is **unpriced** when the candidate
    has evidence on it (`evidence_count > 0`) and `priced_dimensions` does not
    hold it — whatever the reason, and the reason is named: no choice and no
    statement, found negligible by the choices (a figure that could not be
    separated is not a figure), or stated in a currency the weights are not in.
    Before this, those dimensions were dropped without a word: a candidate whose
    traits carried evidence on thirty dimensions was ranked on two, and the
    ranking read as if it had used what they said.

    `checked` is `False` when no `traits` was handed over, which says "nobody
    looked" rather than reading as an empty list, i.e. as "nothing is missing".
    """
    if not isinstance(traits, Mapping):
        return {"checked": False, "dimensions": [], "reasons": {}}
    entries = traits.get("dimensions")
    entries = entries if isinstance(entries, Mapping) else {}
    priced = priced_dimensions(weights)
    skipped = (weights or {}).get("stated_skipped") or {}
    negligible = set((weights or {}).get("negligible") or ())
    reasons: dict[str, str] = {}
    for name, entry in sorted(entries.items()):
        count = entry.get("evidence_count") if isinstance(entry, Mapping) else None
        if not isinstance(count, int) or count <= 0 or name in priced:
            continue
        if skipped.get(name) == "no_currency":
            reasons[name] = UNPRICED_NO_CURRENCY
        elif skipped.get(name) == "currency":
            reasons[name] = UNPRICED_CURRENCY
        elif name in negligible:
            reasons[name] = UNPRICED_NEGLIGIBLE
        else:
            reasons[name] = UNPRICED_NO_CHOICE
    return {"checked": True, "dimensions": sorted(reasons), "reasons": reasons}


def salary_equivalent_total(
    candidate: Candidate, weights: Mapping[str, Any] | None
) -> float | None:
    """§4.3's total, or `None` when a priced dimension is unknown on this offer."""
    priced = priced_dimensions(weights)
    if not priced or candidate.salary_per_month is None:
        return None
    # `not in scores` rather than `in unknown`: a dimension declared unknown and
    # one simply absent are the same absence here, and only the first would be
    # caught by asking about `unknown`.
    if any(name not in candidate.scores for name in priced):
        return None
    return candidate.salary_per_month + sum(
        euros * candidate.scores[name] for name, euros in priced.items()
    )


def rank(
    candidates: Sequence[Candidate],
    *,
    dimensions: Sequence[str],
    revision: ProfileRevision,
    weights: Mapping[str, Any] | None,
    at: str,
    currency: str | None = None,
    readings: Sequence[Reading] = (),
    stack: Mapping[str, Mapping[str, Any]] | None = None,
    traits: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`rankings/<run_id>.json` — spec §5.5, minus T19's `explanations`.

    `traits` is `traits.json` (T243). The ranking names, under
    `unpriced_trait_dimensions`, every dimension the candidate has evidence on
    that the order cannot move on, and under `priced_by` which dimensions were
    priced by choices and which by the candidate's own statements. Omitting it
    is allowed and is recorded as `checked: false`, never as an empty list.

    `stack` is T219's `integral.stack_fit.fits_for_store`: the candidate's CV
    and stated skills against each offer's named technologies. It is carried
    under `stack_fit` for the offers shown. It does not move the order here; step 9
    also hands it to `integral.fit.fit_candidates` (T244), which turns it, the
    advert's stated seniority and English, and the CV into the `FIT_DIMENSIONS`
    axes. Pass `dimensions=[*dims, *FIT_DIMENSIONS]` for those to be read.

    `profile_revision` carries T6's whole `{rows, sha256}` rather than the
    spec example's bare digest, matching `annotation.Annotation`: the row
    count is what makes "behind the current revision" answerable without
    re-reading the log.
    """
    dimensions = tuple(dimensions)
    weights = weights_for_currency(weights, currency)
    priced = priced_dimensions(weights)
    fitted_priced = bool(_read_part_worths(weights, "part_worths"))
    weights_currency = (weights or {}).get("currency") if fitted_priced else None
    # Exactly main's guard: only a *fitted* price has a currency of its own to
    # disagree with the caller's. A stated one is skipped upstream, never raised on.
    if currency is not None and fitted_priced and weights_currency != currency:
        raise RankingError(
            f"the weights are in {weights_currency!r} and the ranking was asked for "
            f"{currency!r} — converting between them is not this module's guess to make"
        )
    level: Sufficiency = "L2" if priced else "L1"
    ranking_currency = weights_currency or currency
    require_priced_dimensions_ranked(dimensions, priced)
    require_pay_coherence(candidates, ranking_currency)

    # T79. A FAIL is removed *before* the frontier, not scored badly inside it:
    # dominance over a barred offer is meaningless, and an exclusion that
    # arrives as a very low total is one the candidate can still be shown. A
    # FLAG is the opposite — spec §5.4 keeps it ranked, marked, and lets the
    # human be the tiebreaker.
    excluded = exclusions(readings)
    barred = {entry["offer_id"] for entry in excluded}
    candidates = [candidate for candidate in candidates if candidate.offer_id not in barred]
    flagged = sorted({reading.offer_id for reading in readings if reading.verdict == "FLAG"})

    signs = dimension_signs(weights)
    kept, dominated = frontier(candidates, dimensions, signs)
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    totals = {
        offer_id: total
        for offer_id in kept
        if (total := salary_equivalent_total(by_id[offer_id], weights)) is not None
    }
    # At L2 the order is the salary-equivalent total; at L1 there is no such
    # quantity, so it is the salary itself — which is what "hard filters plus
    # salary" means and what the level was documented to be. Offers with
    # neither sort last, in id order: a missing number is not a low one, and
    # the alternative — dropping them — is the collapse this module refuses
    # everywhere else.
    salaries = _salaries(kept, by_id)
    # T242: every offer is read as a salary-equivalent interval over its unknown
    # priced dimensions and ordered by the known part (the midpoint), so an offer
    # whose total does not exist still has an order — see `SalaryInterval`. At L1
    # nothing is priced and the midpoint is the salary itself.
    intervals = {offer_id: salary_interval(by_id[offer_id], priced) for offer_id in kept}
    ordering = _ordering_key(kept, by_id, intervals, priced)
    # T138: the salary breaks the tie, before the id does. Two offers alike on
    # every other ranked dimension share a bucket here by construction — the
    # same unknown set means either both have a total or neither does — so
    # falling through to `offer_id` was the alphabet deciding which of them the
    # candidate reads first. It is a tiebreak, not a weight: it never moves an
    # offer past one the primary quantity ranks above it, so nothing here
    # decides what pay is worth against a commute.
    ordered = _pay_before_the_alphabet(
        sorted(kept, key=lambda offer_id: (-ordering.get(offer_id, float("-inf")), offer_id)),
        ordering,
        salaries,
    )
    # T244: of two offers alike on pay and on everything the order read, the one
    # the candidate can better do is not below the other. A tiebreak, not a price.
    ordered = _fit_before_the_alphabet(ordered, ordering, salaries, by_id)

    ranking: dict[str, Any] = {
        "run_id": at,
        "profile_revision": revision.as_json(),
        "level": level,
        "currency": ranking_currency,
        "dimensions": list(dimensions),
        "pareto": ordered,
        "dominated": dominated,
        "excluded": excluded,
        "flagged": flagged,
        "facets": _facets(ordered, by_id, dimensions, totals),
        "salary_equivalent_total": totals,
        # T243: what moved the order, by source, and what said-but-unpriced did not.
        "priced_by": priced_by(weights),
        "dimension_signs": signs,
        "unpriced_trait_dimensions": unpriced_trait_dimensions(traits, weights),
        # T242: which reading put each offer where it is, and which offers the
        # ranker could not tell apart. See `order_readings`.
        **order_readings(ordered, intervals),
        "unknown_dimensions": {
            offer_id: sorted(by_id[offer_id].unknown & set(dimensions))
            for offer_id in ordered
            if by_id[offer_id].unknown & set(dimensions)
        },
    }
    if stack is not None:
        ranking["stack_fit"] = {
            offer_id: dict(stack[offer_id]) for offer_id in ordered if offer_id in stack
        }
    return ranking


#: A score is bounded by `extraction.Score.value` (`ge=-1.0, le=1.0`). An unknown
#: priced dimension can therefore contribute anywhere in `[-e, +e]` euros, and
#: no tighter claim is made about it.
SCORE_BOUND = 1.0

_INF = float("inf")


@dataclass(frozen=True)
class SalaryInterval:
    """T242: the salary-equivalent total as an interval over the unknowns.

    Salary and every known priced dimension are fixed; each unknown priced
    dimension spans its whole score range. `mid` is the known part (salary plus
    known contributions) and is what orders offers; `low`/`high` say how far the
    unknowns could move it, so two offers whose intervals overlap are not
    ordered by any preference. An offer with no published salary has the
    interval [known lower part, +inf) — the salary is itself unknown, so there
    is no upper bound — and keeps a `known_part` reading when a priced dimension
    is known. It is never scored as if the salary were zero, and it overlaps
    every offer whose interval reaches above its lower bound.
    """

    reading: str
    mid: float
    low: float
    high: float

    def overlaps(self, other: SalaryInterval) -> bool:
        return self.low <= other.high and other.low <= self.high


NO_READING = SalaryInterval("none", 0.0, -_INF, _INF)


def salary_interval(candidate: Candidate, priced: Mapping[str, float]) -> SalaryInterval:
    """The interval, or `NO_READING` for an offer with nothing known to order on."""
    known = sum(
        euros * candidate.scores[name] for name, euros in priced.items() if name in candidate.scores
    )
    span = SCORE_BOUND * sum(
        abs(euros) for name, euros in priced.items() if name not in candidate.scores
    )
    if candidate.salary_per_month is None:
        if any(name in candidate.scores for name in priced):
            # [known lower part, +inf): the unpublished salary has no upper bound,
            # so this interval is never read as one.
            return SalaryInterval("known_part", known, known - span, _INF)
        return NO_READING
    mid = candidate.salary_per_month + known
    reading = "salary" if not priced else ("total" if span == 0 else "interval")
    return SalaryInterval(reading, mid, mid - span, mid + span)


def _ordering_key(
    kept: Sequence[str],
    by_id: Mapping[str, Candidate],
    intervals: Mapping[str, SalaryInterval],
    priced: Mapping[str, float],
) -> dict[str, float]:
    """The number each offer is sorted on; an offer with no reading has none.

    An offer that published no salary does not sink below the ones that did —
    T138's decision, kept: an unpublished salary is not a low one. It takes the
    key of the best-keyed offer that is alike on every priced reading (same
    known scores, same unknown set) and differs only in having published pay,
    and failing any such offer, its own known part. Its interval is unbounded
    either way, so it is reported `incomparable` with its neighbours rather than
    ordered by that key.
    """

    def signature(offer_id: str) -> tuple[Any, ...]:
        scores = by_id[offer_id].scores
        return (
            tuple(sorted((name, scores[name]) for name in priced if name in scores)),
            tuple(sorted(name for name in priced if name not in scores)),
        )

    best: dict[tuple[Any, ...], float] = {}
    for offer_id in kept:
        if by_id[offer_id].salary_per_month is not None:
            key = signature(offer_id)
            best[key] = max(best.get(key, -_INF), intervals[offer_id].mid)
    ordering: dict[str, float] = {}
    for offer_id in kept:
        interval = intervals[offer_id]
        if interval.reading == "none":
            continue
        if interval.reading == "known_part":
            ordering[offer_id] = best.get(signature(offer_id), interval.mid)
        else:
            ordering[offer_id] = interval.mid
    return ordering


def _json_bound(value: float) -> float | None:
    return None if value in (_INF, -_INF) else value


def order_readings(
    ordered: Sequence[str], intervals: Mapping[str, SalaryInterval]
) -> dict[str, Any]:
    """T242: name the reading behind each position, and report what is not ordered.

    `order_basis` gives every offer's reading and its interval. `ties` are
    offers with an equal known part; `incomparable` lists, per offer, every other
    offer (any pair, not only neighbours) whose interval overlaps its own, so the
    printed order between them is not a preference.
    The final `offer_id` sort is a tie-break for a stable page and is never one
    either. `unordered` are the offers with no reading at all.
    """
    basis: dict[str, dict[str, Any]] = {
        offer_id: {
            "reading": intervals[offer_id].reading,
            "value": None if intervals[offer_id].reading == "none" else intervals[offer_id].mid,
            "low": _json_bound(intervals[offer_id].low),
            "high": _json_bound(intervals[offer_id].high),
        }
        for offer_id in ordered
    }
    groups: dict[float | None, list[str]] = {}
    for offer_id in ordered:
        groups.setdefault(basis[offer_id]["value"], []).append(offer_id)
    ties: list[dict[str, Any]] = []
    for value, ids in groups.items():
        if len(ids) < 2:
            continue
        readings = sorted({basis[o]["reading"] for o in ids})
        if value is None:
            reason = "no total and no published salary; the ranker cannot order these"
        else:
            reason = (
                f"equal known part {value:g} on reading {'/'.join(readings)}; listed by "
                "published pay where given, then id — not a preference"
            )
        ties.append({"offer_ids": sorted(ids), "reading": "/".join(readings), "reason": reason})
    in_group = {o: frozenset(tie["offer_ids"]) for tie in ties for o in tie["offer_ids"]}
    against: dict[str, list[str]] = {o: [] for o in ordered}
    for first, second in combinations(ordered, 2):
        if intervals[first].overlaps(intervals[second]) and not (
            first in in_group and in_group[first] == in_group.get(second)
        ):
            against[first].append(second)
            against[second].append(first)
    incomparable = [
        {
            "offer_id": offer_id,
            "cannot_be_ordered_against": others,
            "reason": "incomparable: intervals overlap",
        }
        for offer_id, others in against.items()
        if others
    ]
    unordered = sorted(o for o in ordered if intervals[o].reading == "none")
    return {
        "order_basis": basis,
        "ties": ties,
        "incomparable": incomparable,
        "unordered": unordered,
    }


#: T233. The fields `order_readings` publishes that say offers are NOT ordered.
#: `unseparated_units` reads every one of them through `_UNIT_READERS`, so a field
#: listed here without a reader is a KeyError, and `order_readings` publishing one
#: that is not listed here fails `tests/test_rank_missing_inputs.py`.
NON_ORDERING_FIELDS = ("ties", "incomparable", "unordered")

_UNIT_READERS: dict[str, Any] = {
    "ties": lambda tied: [
        frozenset(pair) for tie in tied for pair in combinations(tie["offer_ids"], 2)
    ],
    "incomparable": lambda marks: [
        frozenset((m["offer_id"], other)) for m in marks for other in m["cannot_be_ordered_against"]
    ],
    "unordered": lambda ids: [frozenset((offer_id,)) for offer_id in ids],
}


def unseparated_units(ranking: Mapping[str, Any]) -> set[frozenset[str]]:
    """T233: every pair (or lone unordered offer) the ranking does not put in an order."""
    return {unit for f in NON_ORDERING_FIELDS for unit in _UNIT_READERS[f](ranking[f])}


#: An advert's silence is the employer's to break, so it is never put to the
#: candidate as a question; a price is the candidate's own to give.
ASKS_EMPLOYER = "advert_silent_ask_employer_ranked_apart_until_then"


def missing_inputs(
    ranking: Mapping[str, Any], candidates: Sequence[Candidate]
) -> list[dict[str, Any]]:
    """T233: the inputs that would change how unseparated offers sit, and who can give them.

    `unseparated_units` says which offers the ranking does not order. An input
    is named only when it bears on at least one of them. `salary` (an offer in a
    unit published none) and `unknown:<dim>` (a priced dimension the advert is
    silent on) are the advert's to give. `weights` (L1), `preference:<dim>` and
    `weight:<dim>` (L2) are the candidate's, and only when the offers in a unit
    differ on that ranked dimension, so pricing it could move them. Entries are
    `{"input", "offers", "answer_would", "asked_of"}`, most offers first, where
    `offers` is how many unseparated offers that input bears on. `[]` beside a
    non-empty `unseparated_units` means the offers are level on everything
    asked: nothing is missing, and the session says they are level.
    """
    by_id = {c.offer_id: c for c in candidates}
    priced = {name for names in ranking["priced_by"].values() for name in names}
    traits = set(ranking["unpriced_trait_dimensions"]["dimensions"])
    ranked = [d for d in ranking["dimensions"] if d not in FIT_DIMENSIONS]
    bears: dict[str, set[str]] = {}
    for unit in unseparated_units(ranking):
        members = sorted(unit)
        if any(ranking["order_basis"][o]["reading"] in ("known_part", "none") for o in members):
            bears.setdefault("salary", set()).update(members)
        silent = {d for o in members for d in ranking["unknown_dimensions"].get(o, ())}
        for name in priced & silent:
            bears.setdefault(f"unknown:{name}", set()).update(members)
        if len(members) < 2:
            continue
        for name in ranked:
            if name in priced or len({by_id[o].scores.get(name) for o in members}) < 2:
                continue
            if ranking["level"] == "L1":
                bears.setdefault("weights", set()).update(members)
            else:
                kind = "weight" if name in traits else "preference"
                bears.setdefault(f"{kind}:{name}", set()).update(members)
    entries = []
    for name, offers in bears.items():
        advert = name == "salary" or name.startswith("unknown:")
        entries.append(
            {
                "input": name,
                "offers": len(offers),
                "answer_would": ASKS_EMPLOYER if advert else "price_dimensions",
                "asked_of": "employer" if advert else "candidate",
            }
        )
    return sorted(entries, key=lambda e: (-e["offers"], e["input"]))


def _reference_interval(candidate: Candidate, priced: Mapping[str, float]) -> tuple[float, float]:
    """The audit's own reading of a candidate's interval, independent of `salary_interval`.

    Built from the raw salary and scores by enumerating every resolution of the
    unknown priced dimensions at its extremes (each score at -SCORE_BOUND or
    +SCORE_BOUND) and taking the least and greatest total, rather than by
    summing absolute spans as the producer does. No published salary leaves the
    upper bound open and the lower bound at the least total with salary 0.
    """
    unknown = [name for name in priced if name not in candidate.scores]
    base = sum(euros * candidate.scores[n] for n, euros in priced.items() if n in candidate.scores)
    totals = [
        base + sum(priced[n] * sign for n, sign in zip(unknown, signs, strict=True))
        for signs in product((-SCORE_BOUND, SCORE_BOUND), repeat=len(unknown))
    ]
    salary = candidate.salary_per_month
    if salary is None:
        if not any(name in candidate.scores for name in priced):
            return (-_INF, _INF)
        return (min(totals), _INF)
    return (salary + min(totals), salary + max(totals))


def ordering_defects(
    ranking: Mapping[str, Any],
    candidates: Sequence[Candidate] | None = None,
    priced: Mapping[str, float] | None = None,
) -> dict[str, int]:
    """Audit a published ranking's order, across readings.

    With `candidates` and `priced` the intervals are re-derived from the
    candidates and compared with the published ones (`mismatched`); otherwise the
    published ones are read. Over the published `pareto`:

    - `inversions`: any pair (upper, lower) where the lower offer's interval lies wholly
      above the upper's — the order contradicts what every resolution of the
      unknowns says. Audited across readings, so a `total` printed above a
      `salary`-only offer that is better under every resolution is caught.
    - `unreported`: any pair whose intervals overlap and which is neither
      in one tie group nor listed under `incomparable`, so its id-order reads as
      a preference.
    - `unlabelled`: an offer with no published reading.

    `offers_ordered_by_id` is the number of offers touched by any of them.
    """
    pareto = list(ranking["pareto"])
    basis = ranking.get("order_basis", {})
    unlabelled = {o for o in pareto if o not in basis}
    spans: dict[str, tuple[float, float]] = {}
    mismatched: set[str] = set()
    derived = (
        {c.offer_id: _reference_interval(c, priced or {}) for c in candidates}
        if candidates is not None
        else {}
    )
    for offer_id in pareto:
        if offer_id in unlabelled:
            continue
        low = basis[offer_id]["low"]
        high = basis[offer_id]["high"]
        published = (-_INF if low is None else low, _INF if high is None else high)
        if offer_id in derived:
            mine = derived[offer_id]
            if mine != published:
                mismatched.add(offer_id)
            published = mine
        spans[offer_id] = published
    groups = [set(tie["offer_ids"]) for tie in ranking.get("ties", ())]
    pairs = {
        frozenset((entry["offer_id"], other))
        for entry in ranking.get("incomparable", ())
        for other in entry["cannot_be_ordered_against"]
    }
    inversions: set[str] = set()
    unreported: set[str] = set()
    for first, second in combinations(pareto, 2):
        if first not in spans or second not in spans:
            continue
        if spans[second][0] > spans[first][1]:
            inversions |= {first, second}
        elif (
            spans[first][0] <= spans[second][1]
            and spans[second][0] <= spans[first][1]
            and not any({first, second} <= group for group in groups)
            and frozenset((first, second)) not in pairs
        ):
            unreported |= {first, second}
    bad = unlabelled | inversions | unreported | mismatched
    return {
        "offers": len(pareto),
        "unlabelled": len(unlabelled),
        "unreported": len(unreported),
        "inversions": len(inversions),
        "mismatched": len(mismatched),
        "offers_ordered_by_id": len(bad),
    }


def rank_named(
    candidates: Sequence[Candidate], offer_ids: Sequence[str], **kwargs: Any
) -> dict[str, Any]:
    """T242: rank exactly the offers named (say, those already applied to).

    A name that matches no candidate is an error rather than a silent omission:
    a ranking of ten when eleven were asked for would read as complete.
    """
    wanted = list(dict.fromkeys(offer_ids))
    known = {candidate.offer_id: candidate for candidate in candidates}
    missing = [offer_id for offer_id in wanted if offer_id not in known]
    if missing:
        raise RankingError(f"no candidate for the named offers: {missing}")
    return rank([known[offer_id] for offer_id in wanted], **kwargs)


def _pay_before_the_alphabet(
    ordered: Sequence[str],
    ordering: Mapping[str, float],
    salaries: Mapping[str, float],
) -> list[str]:
    """Reorder each tie of the primary quantity by pay, leaving silent offers put.

    T138's tiebreak, and the decided shape of it (second reader, 2026-09-08).
    Inside one bucket of the primary quantity the offers that **published a
    salary** take the same slots back in descending order of it, so the higher
    paying of two alike offers is never printed below the lower — the property
    the task asks for. An offer that published nothing keeps the slot the
    alphabet gave it and is not moved at all.

    That second half is the decision. A plain `-salary` key reads a missing
    number as `-inf`, which is "an unpublished salary is a low one" — the
    reading this package refuses in `pay_dominance.comparable_band`, where a
    silent side is incomparable in *both* directions rather than cheap. At the
    scale it runs at the two are not close: 97 of 561 offers measured
    2026-09-06 published a band at all, so a tiebreak that sank the silent side
    would put four offers in five beneath every tied offer from a board that
    publishes, on the strength of a number nobody wrote down. The rule makes no
    claim between a silent offer and a publishing one; the order it drives must
    make none either, and the alphabet — which claims nothing about pay — is
    what is left.
    """
    result = list(ordered)
    start = 0
    while start < len(result):
        bucket = ordering.get(result[start], float("-inf"))
        stop = start + 1
        while stop < len(result) and ordering.get(result[stop], float("-inf")) == bucket:
            stop += 1
        slots = [index for index in range(start, stop) if result[index] in salaries]
        by_pay = sorted((result[index] for index in slots), key=lambda o: (-salaries[o], o))
        for index, offer_id in zip(slots, by_pay, strict=True):
            result[index] = offer_id
        start = stop
    return result


def _fit_before_the_alphabet(
    ordered: Sequence[str],
    ordering: Mapping[str, float],
    salaries: Mapping[str, float],
    by_id: Mapping[str, Candidate],
) -> list[str]:
    """T244: inside one (primary bucket, pay, stated components) tie, offers
    take the same slots back in descending order of their fit.

    Same shape as `_pay_before_the_alphabet`, and for its reason: an offer whose
    fit is unknown keeps the slot it had. Offers are compared only when they state
    the *same* fit components, so two adverts silent on English still order by the
    stack and level they both state, and no offer is ordered by a component the
    other left unsaid. Slots are permuted only inside the group, so the pay rule
    is never undone.
    """
    result = list(ordered)
    groups: dict[tuple[float, float | None, frozenset[str]], list[int]] = {}
    for index, offer_id in enumerate(result):
        stated = frozenset(n for n in FIT_DIMENSIONS if n in by_id[offer_id].scores)
        if stated:
            key = (ordering.get(offer_id, float("-inf")), salaries.get(offer_id), stated)
            groups.setdefault(key, []).append(index)

    def fit(offer_id: str) -> float:
        scores = by_id[offer_id].scores
        return sum(scores[n] for n in FIT_DIMENSIONS if n in scores)

    for slots in groups.values():
        by_fit = sorted((result[i] for i in slots), key=lambda o: (-fit(o), o))
        for index, offer_id in zip(slots, by_fit, strict=True):
            result[index] = offer_id
    return result


def _salaries(kept: Sequence[str], by_id: Mapping[str, Candidate]) -> dict[str, float]:
    return {
        offer_id: salary
        for offer_id in kept
        if (salary := by_id[offer_id].salary_per_month) is not None
    }


def _facets(
    ordered: Sequence[str],
    by_id: Mapping[str, Candidate],
    dimensions: Sequence[str],
    totals: Mapping[str, float],
) -> dict[str, list[str]]:
    """The named lists: what tops each dimension, and the total when there is one.

    Ties name every offer that ties. Picking one would make the list read as a
    ranking of its own, which is the single-number presentation §4.3 forbids.
    """
    facets: dict[str, list[str]] = {}
    if totals:
        best = max(totals.values())
        facets["best_salary_equivalent"] = sorted(
            offer_id for offer_id, total in totals.items() if total == best
        )
    for name in dimensions:
        scored = {
            offer_id: by_id[offer_id].scores[name]
            for offer_id in ordered
            if name in by_id[offer_id].scores
        }
        if scored:
            best_score = max(scored.values())
            facets[name] = sorted(
                offer_id for offer_id, value in scored.items() if value == best_score
            )
    return facets


def exclusions(readings: Sequence[Reading]) -> list[dict[str, Any]]:
    """The **Excluded** section — one entry per FAIL, carrying the advert's own
    sentence.

    Rendered from the reading, never assembled: D-17's lesson for the card
    applies here too. The list is always emitted, empty or not, because a
    withheld offer that is silently dropped looks identical to an offer that
    was never found — D-18's rule, one layer on.
    """
    return [
        {"offer_id": reading.offer_id, "reason": reading.reason, "quote": reading.quote}
        for reading in readings
        if reading.verdict == "FAIL"
    ]


def excluded_offers_without_a_reason(ranking: Mapping[str, Any]) -> int:
    """T79's gate: an exclusion shown without the wording it was excluded for.

    A verdict the candidate cannot trace to a sentence in the advert is one
    they cannot dispute, which is exactly how a false FAIL stays invisible.
    """
    return sum(
        1
        for entry in ranking.get("excluded", ())
        if not entry.get("reason") or not (entry.get("quote") or "").strip()
    )


class _Unset:
    """Sentinel: the audit's `currency` was not given (None is a real answer)."""


_UNSET = _Unset()


def dominance_violations(
    ranking: Mapping[str, Any],
    candidates: Sequence[Candidate],
    weights: Mapping[str, Any] | None = None,
    currency: str | _Unset | None = _UNSET,
) -> int:
    """Audit the published lists against the candidates that produced them.

    Deliberately not a by-product of `frontier`: a count the construction hands
    itself can only ever be zero, whatever the construction did. This walks
    `pareto` and `dominated` as written and re-derives dominance from the
    candidates, so it can disagree — and
    `test_the_audit_reads_the_published_lists_not_the_pass_that_built_them`
    shows it doing so.

    Three things count as a violation:

    1. An offer on the frontier that **any candidate** dominates — not merely
       any other published one. Dominance is transitive, so on a *well-formed*
       ranking the two scans agree: every dominator chain bottoms out at a
       frontier member. They part company exactly where it matters, on a
       ranking that is not well-formed — a dominator filed as collapsed under
       a collapser that does not dominate it is no longer a published peer,
       and only the candidates still contradict it. The candidates are the
       ground truth; the published lists are the claim being checked.
    2. A collapsed offer whose named collapser does not in fact dominate it.
    3. A published set that is not a partition of the candidates — an offer in
       both lists, or in neither. Every offer that went in has to come out
       somewhere, or the frontier is a claim about a different market than the
       one it was given.
    """
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    dimensions = tuple(ranking["dimensions"])
    # B2: the signs come from the weights the ranking was made with (and the
    # `currency=` it was asked for), never from the ranking under audit — a ranker
    # that published wrong signs and built its frontier from them would otherwise
    # pass its own audit. With no weights nothing is priced and there are none.
    if currency is _UNSET:
        if isinstance(weights, Mapping) and weights.get("stated_part_worths"):
            raise RankingError(
                "the weights hold stated prices and no `currency=` was given to the audit — "
                "which of them were in force depends on the ranking's currency, and guessing "
                "it (or reading it off the ranking under audit) would let a forged ranking "
                "choose its own signs; pass the currency the ranking was asked for, "
                "None if it was asked for none"
            )
        currency = None
    signs = dimension_signs(weights_for_currency(weights, currency))  # type: ignore[arg-type]
    published = list(ranking["pareto"])
    collapsed = dict(ranking["dominated"])
    violations = 0

    for offer_id in published:
        mine = by_id.get(offer_id)
        if mine is None:
            violations += 1
            continue
        violations += any(
            candidate.offer_id != offer_id and dominates(candidate, mine, dimensions, signs)
            for candidate in candidates
        )

    for offer_id, note in collapsed.items():
        mine = by_id.get(offer_id)
        collapser = by_id.get(str(note).removeprefix(DOMINATED_BY))
        if mine is None or collapser is None or not dominates(collapser, mine, dimensions, signs):
            violations += 1

    violations += len(set(published) & set(collapsed))
    violations += len(set(by_id) - set(published) - set(collapsed))

    return violations


def write_ranking(store: ProfileStore, ranking: Mapping[str, Any]) -> Path:
    """Under the candidate's own tree, named by the run — never a shared path."""
    return store.write_json(dict(ranking), "rankings", f"{ranking['run_id']}.json")


# One market's worth of offers, written out so the measurement is the same on
# any machine. The scores are the sort of spread real adverts give: two clear
# trade-offs, one advert that is worse at everything, and one that stays quiet
# about a dimension the others settle.
_FIXTURE: tuple[tuple[str, float | None, dict[str, float]], ...] = (
    ("sha256:" + "1" * 64, 3600.0, {"remote": 1.0, "commute": -0.5, "mentoring": 0.2}),
    ("sha256:" + "2" * 64, 4200.0, {"remote": -1.0, "commute": 0.8, "mentoring": -0.4}),
    ("sha256:" + "3" * 64, 3100.0, {"remote": 0.4, "commute": 0.4, "mentoring": 1.0}),
    ("sha256:" + "4" * 64, 2900.0, {"remote": -1.0, "commute": -0.6, "mentoring": -0.6}),
    ("sha256:" + "5" * 64, 3300.0, {"remote": 0.6, "commute": 0.0}),
    ("sha256:" + "6" * 64, None, {"remote": 1.0, "commute": 1.0, "mentoring": 1.0}),
)
_FIXTURE_DIMENSIONS = ("commute", "mentoring", "remote")

#: T79's fixture verdicts. The FAIL is on offer 2 — the highest-paid one, which
#: the frontier would otherwise keep — so the gate measures an exclusion that
#: had somewhere to be excluded *from*. Excluding a collapsed offer would prove
#: nothing.
_FIXTURE_READINGS: tuple[Reading, ...] = (
    Reading(
        offer_id="sha256:" + "2" * 64,
        verdict="FAIL",
        reason="citizenship",
        quote="must hold German citizenship",
        requirements=(),
    ),
    Reading(
        offer_id="sha256:" + "3" * 64,
        verdict="FLAG",
        reason="clearance",
        quote="An active security clearance is a plus",
        requirements=(),
    ),
)
_FIXTURE_WEIGHTS: dict[str, Any] = {
    "currency": "EUR",
    "part_worths": {
        "commute": {"utility_per_unit": 0.30, "salary_equivalent_per_month": 200.0},
        "mentoring": {"utility_per_unit": 0.15, "salary_equivalent_per_month": 100.0},
        "remote": {"utility_per_unit": 0.90, "salary_equivalent_per_month": 600.0},
    },
    "negligible": [],
    "separated": False,
    "salary_utility_per_month": 0.0015,
}


def _fixture_candidates() -> list[Candidate]:
    return [
        Candidate(
            offer_id=offer_id,
            salary_per_month=salary,
            scores=scores,
            unknown=frozenset(name for name in _FIXTURE_DIMENSIONS if name not in scores),
            pay=point_band(salary, "EUR"),
        )
        for offer_id, salary, scores in _FIXTURE
    ]


def measure() -> dict[str, Any]:
    """The gate's numbers: the audited violation count, and proof it can rise."""
    candidates = _fixture_candidates()
    ranking = rank(
        candidates,
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=len(_FIXTURE), sha256="0" * 64),
        weights=_FIXTURE_WEIGHTS,
        at="2026-08-24T00:00:00Z",
    )
    violations = dominance_violations(ranking, candidates, _FIXTURE_WEIGHTS)

    # Put every offer on the frontier, including the one the fixture collapses,
    # and the audit has to notice. Without this the gate would certify a
    # frontier that never dropped anything at all.
    planted = dominance_violations(
        {**ranking, "pareto": [offer_id for offer_id, _, _ in _FIXTURE], "dominated": {}},
        candidates,
        _FIXTURE_WEIGHTS,
    )

    provisional = rank(
        candidates,
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=len(_FIXTURE), sha256="0" * 64),
        weights=None,
        at="2026-08-24T00:00:00Z",
    )

    return {
        "pareto_dominance_violations": violations,
        "violation_detected_when_planted": int(planted > 0),
        "offers_ranked": len(candidates),
        "frontier_size": len(ranking["pareto"]),
        "collapsed": len(ranking["dominated"]),
        "offers_without_a_total": len(ranking["pareto"]) - len(ranking["salary_equivalent_total"]),
        "level": ranking["level"],
        "level_without_weights": provisional["level"],
    }


def measure_exclusions() -> dict[str, Any]:
    """T79's numbers: exclusions rendered, how many arrived without a reason,
    and proof the count can rise."""
    candidates = _fixture_candidates()
    ranking = rank(
        candidates,
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=len(_FIXTURE), sha256="0" * 64),
        weights=_FIXTURE_WEIGHTS,
        at="2026-08-24T00:00:00Z",
        readings=_FIXTURE_READINGS,
    )
    shown: list[dict[str, Any]] = list(ranking["excluded"])
    if not shown:
        # Nothing was excluded, so nothing can be scored. A zero here would be
        # a violation count over an empty set — the exact silent success this
        # increment exists to refuse.
        return {
            "excluded_offers_shown_without_a_reason": -1,
            "excluded_offers_shown_without_a_reason_evaluated": 0,
            "excluded_offers_evaluated": len(_FIXTURE_READINGS),
            "gate_status": "unmeasured",
            "reason": "no offer was excluded, so the Excluded section rendered nothing to score",
            "excluded": [],
        }

    without = excluded_offers_without_a_reason(ranking)
    # Strip one entry's quote and the audit has to notice. Without this the
    # gate would certify a section that never carried a reason at all.
    planted = excluded_offers_without_a_reason(
        {**ranking, "excluded": [{**shown[0], "quote": None}, *shown[1:]]}
    )

    return {
        "excluded_offers_shown_without_a_reason": without,
        "excluded_offers_shown_without_a_reason_evaluated": len(shown),
        "excluded_offers_evaluated": len(_FIXTURE_READINGS),
        "violation_detected_when_planted": int(planted > without),
        "excluded_offers_reaching_the_frontier": sum(
            1 for entry in shown if entry["offer_id"] in ranking["pareto"]
        ),
        # A FLAG is kept, so its denominator is the FLAGs the fixture states
        # and the two must be equal. Recording only the retained count would
        # let a regression that drops every FLAG report a clean `0` — the
        # violation-count-over-an-empty-set failure this gate exists to refuse,
        # reproduced one field along.
        "flagged_offers_evaluated": sum(
            1 for reading in _FIXTURE_READINGS if reading.verdict == "FLAG"
        ),
        # `pareto` *and* `dominated`: a FLAG is kept, and being kept means
        # entering the comparison — which a dominated offer did. Counting only
        # the frontier would report a correctly-retained FLAG as dropped the
        # moment another offer dominated it, failing the gate over the one
        # behaviour it is checking.
        "flagged_offers_still_ranked": sum(
            1
            for offer_id in ranking["flagged"]
            if offer_id in ranking["pareto"] or offer_id in ranking["dominated"]
        ),
        "gate_status": "measured",
        "excluded": shown,
    }


def write_exclusion_evidence(evidence: Path = DEFAULT_T79_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_exclusions()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _unknown_everywhere_candidates() -> list[Candidate]:
    """T242's realistic set: the repo fixture's salaries and scores, with the
    priced `commute` dimension unknown on every offer.

    The six `_FIXTURE` offers are repeated in three variants — as written, with
    `mentoring` also unknown, and with the salary withheld — plus an equal-pay
    pair and a bare offer, so the set holds the situations a real batch does:
    full intervals, partial ones, no salary, nothing known, and equal readings.
    """
    out: list[Candidate] = []
    for variant in range(3):
        for offer_id, salary, scores in _FIXTURE:
            kept = {k: v for k, v in scores.items() if k != "commute"}
            if variant == 1:
                kept.pop("mentoring", None)
            out.append(
                Candidate(
                    offer_id=f"{offer_id}:v{variant}",
                    salary_per_month=None if variant == 2 and salary is not None else salary,
                    scores=kept,
                    unknown=frozenset(n for n in _FIXTURE_DIMENSIONS if n not in kept),
                    pay=None if variant == 2 else point_band(salary, "EUR"),
                )
            )
    for letter in "ab":
        out.append(
            Candidate(
                "sha256:" + letter * 64,
                3000.0,
                {},
                frozenset(_FIXTURE_DIMENSIONS),
                pay=point_band(3000.0, "EUR"),
            )
        )
    out.append(Candidate("sha256:" + "c" * 64, None, {}, frozenset(_FIXTURE_DIMENSIONS)))
    return out


def _mixed_candidates() -> list[Candidate]:
    """The unknown-everywhere set plus the fixture offers with every score known,
    so the audit also reads offers that have a salary-equivalent total."""
    full = [
        Candidate(
            offer_id=f"full:{offer_id}",
            salary_per_month=salary,
            scores=dict(scores),
            unknown=frozenset(n for n in _FIXTURE_DIMENSIONS if n not in scores),
            pay=point_band(salary, "EUR"),
        )
        for offer_id, salary, scores in _FIXTURE
    ]
    return _unknown_everywhere_candidates() + full


def _planted_violations(
    ranking: Mapping[str, Any], candidates: Sequence[Candidate], priced: Mapping[str, float]
) -> dict[str, int]:
    """Plant each kind of defect in a copy of `ranking`; 1 where the audit rose.

    - `stripped_tie`: every published tie group removed;
    - `stripped_incomparable`: every incomparable mark removed;
    - `inversion`: the first two offers whose published order contradicts their
      wholly-separated intervals swapped back (found with `_reference_interval`);
    - `unknown_as_zero`: every interval collapsed onto its known part, as if each
      unknown priced dimension scored 0.
    """
    reference = {c.offer_id: _reference_interval(c, priced) for c in candidates}
    pareto = list(ranking["pareto"])
    swapped = list(pareto)
    for i, j in combinations(range(len(pareto)), 2):
        if reference[pareto[i]][0] > reference[pareto[j]][1]:
            swapped[i], swapped[j] = swapped[j], swapped[i]
            break
    zeroed = {
        offer_id: {**entry, "low": entry["value"], "high": entry["value"]}
        if entry["value"] is not None and entry["high"] is not None
        else dict(entry)
        for offer_id, entry in ranking["order_basis"].items()
    }
    plants = {
        "stripped_tie": {**ranking, "ties": []},
        "stripped_incomparable": {**ranking, "incomparable": []},
        "inversion": {**ranking, "pareto": swapped},
        "unknown_as_zero": {**ranking, "order_basis": zeroed},
    }
    return {
        kind: int(ordering_defects(planted, candidates, priced)["offers_ordered_by_id"] > 0)
        for kind, planted in plants.items()
    }


def measure_order() -> dict[str, Any]:
    """T242's numbers: the fraction of offers ordered by id rather than by a reading.

    Two sets are audited. The unknown-everywhere set has no total on any offer
    (the task's case). The mixed set adds offers that do have totals, so the
    audit also reads totals beside salary-only, partial and no-salary offers.
    The audit re-derives each interval from the candidates with
    `_reference_interval`, which shares no code with the producer's
    `salary_interval`. `planted` records one planted violation per kind — a
    stripped tie, a stripped incomparable mark, a swapped pair of wholly
    separated offers, an unknown scored as 0 — each of which must raise the
    count on the mixed set, or the zero proves nothing.
    """
    priced = priced_dimensions(_FIXTURE_WEIGHTS)

    def run(candidates: list[Candidate]) -> dict[str, Any]:
        return rank(
            candidates,
            dimensions=_FIXTURE_DIMENSIONS,
            revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
            weights=_FIXTURE_WEIGHTS,
            at="2026-08-24T00:00:00Z",
        )

    candidates = _unknown_everywhere_candidates()
    ranking = run(candidates)
    audit = ordering_defects(ranking, candidates, priced)
    mixed = _mixed_candidates()
    mixed_ranking = run(mixed)
    mixed_audit = ordering_defects(mixed_ranking, mixed, priced)
    planted = _planted_violations(mixed_ranking, mixed, priced)
    readings = [entry["reading"] for entry in ranking["order_basis"].values()]
    mixed_readings = [entry["reading"] for entry in mixed_ranking["order_basis"].values()]
    return {
        "offers": audit["offers"],
        "offers_with_a_total": len(ranking["salary_equivalent_total"]),
        "offers_ordered_by_id": audit["offers_ordered_by_id"],
        "fraction_ordered_by_id": audit["offers_ordered_by_id"] / audit["offers"],
        "inversions": audit["inversions"],
        "readings_used": sorted(set(readings)),
        "offers_with_incomparable_marks": len(
            [e for e in ranking["incomparable"] if e["cannot_be_ordered_against"]]
        ),
        "mixed_offers": mixed_audit["offers"],
        "mixed_offers_with_a_total": len(mixed_ranking["salary_equivalent_total"]),
        "mixed_fraction_ordered_by_id": mixed_audit["offers_ordered_by_id"] / mixed_audit["offers"],
        "mixed_inversions": mixed_audit["inversions"],
        "mixed_readings_used": sorted(set(mixed_readings)),
        "planted": planted,
        "violation_detected_when_planted": int(all(planted.values())),
    }


def write_order_evidence(evidence: Path = DEFAULT_T242_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_order()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


#: T233's floor on constructed rankings that leave offers unseparated: the gate's
#: zero means nothing over fewer than these. All ten constructed cases of
#: `_t233_cases` are unseparated, four of them with nothing missing (the controls
#: that catch an input named for no reason), so the margin is nil by design:
#: dropping one is a refusal, not a slack.
#: arsenal-floor-margin: MINIMUM_UNSEPARATED_RANKINGS value=10
MINIMUM_UNSEPARATED_RANKINGS = 10


def _t233_cases() -> list[dict[str, Any]]:
    """Constructed rankings: each left unseparated, by a different input or by none."""

    def offers(*specs: tuple[str, float | None, dict[str, float]]) -> list[Candidate]:
        return [
            Candidate(
                offer_id=f"sha256:{name * 64}",
                salary_per_month=salary,
                scores=scores,
                unknown=frozenset(_FIXTURE_DIMENSIONS) - set(scores),
                pay=point_band(salary, "EUR"),
            )
            for name, salary, scores in specs
        ]

    same = {"remote": 0.5, "commute": 0.5, "mentoring": 0.5}
    # Same salary-equivalent total as `same` (450) by a different mix, so neither dominates.
    mix = {"remote": 0.75, "commute": -0.25, "mentoring": 0.5}
    lean = {"remote": 1.0, "commute": 0.0, "mentoring": 0.5}
    traits = {"dimensions": {"company_kind": {"evidence_count": 3}}}
    fixed = _FIXTURE_WEIGHTS
    return [
        # Nothing separates them and nothing could: identical offers, no weights.
        {"candidates": offers(("a", 3000.0, same), ("b", 3000.0, same)), "weights": None},
        # Weights would: the same pay, a different mix.
        {"candidates": offers(("a", 3000.0, same), ("b", 3000.0, lean)), "weights": None},
        # Only the salary is missing, on one of three.
        {
            "candidates": offers(("a", 3000.0, same), ("b", 3500.0, same), ("c", None, same)),
            "weights": None,
        },
        # An unknown priced dimension overlaps the interval of the other offer.
        {
            "candidates": offers(
                ("a", 3000.0, same), ("b", 3100.0, {"commute": 0.5, "mentoring": 0.5})
            ),
            "weights": fixed,
        },
        # An unpublished salary beside a published one.
        {
            "candidates": offers(
                ("a", 3000.0, same),
                ("b", None, {"remote": 1.0, "commute": 0.0, "mentoring": 0.2}),
            ),
            "weights": fixed,
        },
        # A ranked dimension the offers differ on and nothing prices.
        {
            "candidates": offers(
                ("a", 3000.0, {**same, "company_kind": 1.0}),
                ("b", 3000.0, {**mix, "company_kind": -1.0}),
            ),
            "weights": fixed,
            "extra_dimensions": ("company_kind",),
        },
        # The same, but the candidate has said something about it: a weight, not a preference.
        {
            "candidates": offers(
                ("a", 3000.0, {**same, "company_kind": 1.0}),
                ("b", 3000.0, {**mix, "company_kind": -1.0}),
            ),
            "weights": fixed,
            "traits": traits,
            "extra_dimensions": ("company_kind",),
        },
        # CONTROL: a trait with evidence that neither offer scores. Nothing is missing.
        {
            "candidates": offers(("a", 3000.0, same), ("b", 3000.0, same)),
            "weights": fixed,
            "traits": traits,
            "extra_dimensions": ("company_kind",),
        },
        # CONTROL: a real tie on equal totals, every dimension priced and known.
        {
            "candidates": offers(
                ("a", 3000.0, {"remote": 1.0, "commute": 0.5, "mentoring": 0.5}),
                ("b", 3600.0, {"remote": 0.0, "commute": 0.5, "mentoring": 0.5}),
            ),
            "weights": fixed,
        },
        # CONTROL: they differ only on an axis read from the CV, never asked.
        {
            "candidates": offers(
                ("a", 3000.0, {**same, "fit_stack": 1.0}), ("b", 3000.0, {**mix, "fit_stack": 0.0})
            ),
            "weights": fixed,
            "extra_dimensions": ("fit_stack",),
        },
    ]


def _t233_candidates(case: Mapping[str, Any]) -> list[Candidate]:
    extra = frozenset(case.get("extra_dimensions", ()))
    return [replace(c, unknown=c.unknown | (extra - set(c.scores))) for c in case["candidates"]]


def _t233_rank(case: Mapping[str, Any]) -> dict[str, Any]:
    candidates = _t233_candidates(case)
    return rank(
        candidates,
        dimensions=(*_FIXTURE_DIMENSIONS, *case.get("extra_dimensions", ())),
        revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
        weights=case["weights"],
        traits=case.get("traits"),
        at="2026-10-06T00:00:00Z",
    )


def _t233_answers(case: Mapping[str, Any], ranking: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every single answer that could be given, each as the case with that answer in.

    Derived from the case and the ranking's dimensions, not from `missing_inputs`:
    this is the ground truth the reporter is measured against. Keys: `weights`
    (L1), `price:<dim>`, `unknown:<dim>`, `salary`.
    """
    candidates = _t233_candidates(case)
    out: dict[str, dict[str, Any]] = {}
    priced = {n for names in ranking["priced_by"].values() for n in names}
    if ranking["level"] == "L1":
        out["weights"] = {**case, "weights": _FIXTURE_WEIGHTS}
    else:
        for name in ranking["dimensions"]:
            if name not in priced and name not in FIT_DIMENSIONS:
                worths = {
                    **case["weights"]["part_worths"],
                    name: {"utility_per_unit": 0.2, "salary_equivalent_per_month": 300.0},
                }
                out[f"price:{name}"] = {
                    **case,
                    "weights": {**case["weights"], "part_worths": worths},
                }
    for name in priced:
        lacking = [c for c in candidates if name not in c.scores]
        if lacking:
            given = {c.offer_id: (1.0 if i % 2 == 0 else -1.0) for i, c in enumerate(lacking)}
            out[f"unknown:{name}"] = {
                **case,
                "candidates": [
                    replace(
                        c, scores={**c.scores, name: given[c.offer_id]}, unknown=c.unknown - {name}
                    )
                    if c.offer_id in given
                    else c
                    for c in candidates
                ],
            }
    if any(c.salary_per_month is None for c in candidates):
        out["salary"] = {
            **case,
            "candidates": [
                c
                if c.salary_per_month is not None
                else replace(
                    c, salary_per_month=2000.0 + 100 * i, pay=point_band(2000.0 + 100 * i, "EUR")
                )
                for i, c in enumerate(candidates)
            ],
        }
    return out


def _t233_key(name: str) -> str:
    return "price:" + name.split(":", 1)[1] if name.startswith(("preference:", "weight:")) else name


def _t233_effective(case: Mapping[str, Any]) -> set[str]:
    """The answers that, actually given, leave fewer pairs unordered."""

    def pairs(ranking: Mapping[str, Any]) -> int:
        return sum(1 for unit in unseparated_units(ranking) if len(unit) == 2)

    ranking = _t233_rank(case)
    before = pairs(ranking)
    return {
        key
        for key, answered in _t233_answers(case, ranking).items()
        if pairs(_t233_rank(answered)) < before
    }


def t233_discrepancies(
    cases: Sequence[Mapping[str, Any]], reporter: Any = missing_inputs
) -> dict[str, int]:
    """Both directions, per ranking left unseparated.

    `silent`: an answer exists that would separate some offers and the reporter
    does not name it. `spurious`: the reporter names an input whose answer, given,
    separates nothing.
    """
    silent = spurious = controls = 0
    for case in cases:
        ranking = _t233_rank(case)
        if not unseparated_units(ranking):
            continue
        truth = _t233_effective(case)
        named = {_t233_key(e["input"]) for e in reporter(ranking, _t233_candidates(case))}
        silent += bool(truth - named)
        spurious += bool(named - truth)
        controls += not truth
    return {"silent": silent, "spurious": spurious, "nothing_missing_controls": controls}


def measure_missing_inputs() -> dict[str, Any]:
    cases = _t233_cases()
    rankings = [_t233_rank(case) for case in cases]
    found = t233_discrepancies(cases)
    out: dict[str, Any] = {
        "rankings_with_unordered_ties_and_no_named_missing_input": found["silent"],
        "inputs_named_that_bear_on_no_unseparated_offer": found["spurious"],
        "unseparated_rankings": sum(1 for r in rankings if unseparated_units(r)),
        "unseparated_rankings_at_least": MINIMUM_UNSEPARATED_RANKINGS,
        "nothing_missing_controls": found["nothing_missing_controls"],
        "silent_when_reporter_is_empty": t233_discrepancies(cases, lambda _r, _c: [])["silent"],
        "spurious_when_reporter_always_names_weights": t233_discrepancies(
            cases, lambda _r, _c: [{"input": "weights"}]
        )["spurious"],
        "inputs_named": sorted(
            {
                e["input"]
                for r, c in zip(rankings, cases, strict=True)
                for e in missing_inputs(r, _t233_candidates(c))
            }
        ),
    }
    out["unseparated_rankings_ok"] = int(
        out["unseparated_rankings"] >= MINIMUM_UNSEPARATED_RANKINGS
    )
    return out


def write_missing_inputs_evidence(evidence: Path = DEFAULT_T233_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure_missing_inputs()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T18's Pareto frontier.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)
    print(f"pareto_dominance_violations: {measured['pareto_dominance_violations']} (== 0)")
    print(f"violation_detected_when_planted: {measured['violation_detected_when_planted']}")
    if measured["pareto_dominance_violations"] != 0:
        return 1
    if not measured["violation_detected_when_planted"]:
        print("the audit did not rise when a dominated offer was planted", file=sys.stderr)
        return 1

    # T79 rides beside T18 rather than replacing it — one module, two gates,
    # two evidence files, as the task requires.
    ordered = write_order_evidence(args.evidence.parent / "T242.json")
    print(f"fraction_ordered_by_id: {ordered['fraction_ordered_by_id']} (== 0)")
    if (
        ordered["fraction_ordered_by_id"] != 0
        or ordered["mixed_fraction_ordered_by_id"] != 0
        or not ordered["violation_detected_when_planted"]
    ):
        print("an offer was ordered by id, or the audit could not rise", file=sys.stderr)
        return 1

    missing = write_missing_inputs_evidence(args.evidence.parent / "T233.json")
    if (
        missing["rankings_with_unordered_ties_and_no_named_missing_input"] != 0
        or missing["inputs_named_that_bear_on_no_unseparated_offer"] != 0
        or not missing["unseparated_rankings_ok"]
        or not missing["nothing_missing_controls"]
        or not missing["silent_when_reporter_is_empty"]
        or not missing["spurious_when_reporter_always_names_weights"]
    ):
        print(
            "an unseparated ranking named a wrong or no missing input, or the audit could not rise",
            file=sys.stderr,
        )
        return 1

    shown = write_exclusion_evidence(args.evidence.parent / "T79.json")
    print(
        "excluded_offers_shown_without_a_reason: "
        f"{shown['excluded_offers_shown_without_a_reason']} (== 0)"
    )
    if shown["gate_status"] != "measured":
        print(f"T79 cannot be scored: {shown['reason']}", file=sys.stderr)
        return 1
    if shown["excluded_offers_shown_without_a_reason"] != 0:
        return 1
    if not shown["violation_detected_when_planted"]:
        print("the audit did not rise when a reason was stripped", file=sys.stderr)
        return 1
    if shown["excluded_offers_reaching_the_frontier"]:
        print("an excluded offer reached the frontier", file=sys.stderr)
        return 1
    if shown["flagged_offers_still_ranked"] != shown["flagged_offers_evaluated"]:
        print("a flagged offer was dropped from the ranking instead of marked", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
