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
from dataclasses import dataclass, field
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


def dominates(a: Candidate, b: Candidate, dimensions: Sequence[str]) -> bool:
    """Whether `a` is at least as good everywhere and better somewhere.

    Returns False the moment any axis is unknown on either side: the claim
    "at least as good on every dimension" cannot be made about a dimension
    nobody has a value for, and a dominance rule that guessed would be
    deciding what the candidate never gets shown.
    """
    if a.salary_per_month is None or b.salary_per_month is None:
        return False
    if any(name in a.unknown or name in b.unknown for name in dimensions):
        return False

    pairs = [(a.salary_per_month, b.salary_per_month)] + [
        (a.scores[name], b.scores[name]) for name in dimensions
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

    Only a band in the ranking's currency is checked: one in another currency
    is deliberately incomparable here (no rate with a date and a source lives
    in this repository), so it constrains nothing and is not required to.
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
    for candidate in candidates:
        band = candidate.pay
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
    candidates: Sequence[Candidate], dimensions: Sequence[str]
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
            (other for other in candidates if dominates(other, mine, dimensions)),
            None,
        )
        if collapser is None:
            kept.append(mine.offer_id)
        else:
            dominated[mine.offer_id] = f"{DOMINATED_BY}{collapser.offer_id}"
    return kept, dominated


def priced_dimensions(weights: Mapping[str, Any] | None) -> dict[str, float]:
    """`{dimension: euros per month per unit of score}` from T10's `weights.json`.

    Read through one function rather than at each use, so the shape T10 writes
    has a single reader here. A file with no part-worths yields `{}`, which is
    what makes the ranking L1.
    """
    if not isinstance(weights, Mapping):
        return {}
    part_worths = weights.get("part_worths")
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
) -> dict[str, Any]:
    """`rankings/<run_id>.json` — spec §5.5, minus T19's `explanations`.

    `profile_revision` carries T6's whole `{rows, sha256}` rather than the
    spec example's bare digest, matching `annotation.Annotation`: the row
    count is what makes "behind the current revision" answerable without
    re-reading the log.
    """
    dimensions = tuple(dimensions)
    priced = priced_dimensions(weights)
    weights_currency = (weights or {}).get("currency") if priced else None
    if currency is not None and priced and weights_currency != currency:
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

    kept, dominated = frontier(candidates, dimensions)
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
    ordering = totals if level == "L2" else salaries
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

    return {
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
        "unknown_dimensions": {
            offer_id: sorted(by_id[offer_id].unknown & set(dimensions))
            for offer_id in ordered
            if by_id[offer_id].unknown & set(dimensions)
        },
    }


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


def dominance_violations(ranking: Mapping[str, Any], candidates: Sequence[Candidate]) -> int:
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
    published = list(ranking["pareto"])
    collapsed = dict(ranking["dominated"])
    violations = 0

    for offer_id in published:
        mine = by_id.get(offer_id)
        if mine is None:
            violations += 1
            continue
        violations += any(
            candidate.offer_id != offer_id and dominates(candidate, mine, dimensions)
            for candidate in candidates
        )

    for offer_id, note in collapsed.items():
        mine = by_id.get(offer_id)
        collapser = by_id.get(str(note).removeprefix(DOMINATED_BY))
        if mine is None or collapser is None or not dominates(collapser, mine, dimensions):
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
    violations = dominance_violations(ranking, candidates)

    # Put every offer on the frontier, including the one the fixture collapses,
    # and the audit has to notice. Without this the gate would certify a
    # frontier that never dropped anything at all.
    planted = dominance_violations(
        {**ranking, "pareto": [offer_id for offer_id, _, _ in _FIXTURE], "dominated": {}},
        candidates,
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
