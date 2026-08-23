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

Scope: `explanations` — the per-driver €/month contributions and their verbatim
spans — belong to T19, and the offer card to T44. This module produces the
`rankings/<run_id>.json` those read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from integral.extraction import OfferExtraction
from integral.identity import ProfileStore
from integral.profile import ProfileRevision
from integral.session import Sufficiency

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T18.json"

#: How `rankings/<run_id>.json` names an offer's collapser (spec §5.5).
DOMINATED_BY = "dominated_by:"


class RankingError(Exception):
    """The inputs do not support the ranking that was asked for."""


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


def frontier(
    candidates: Sequence[Candidate], dimensions: Sequence[str]
) -> tuple[list[str], dict[str, str]]:
    """`(non-dominated ids, {dominated id: "dominated_by:<id>"})`.

    The collapser is named rather than counted: "this one is out" is not an
    answer a candidate can argue with, and T19's explanation needs somewhere
    to start.
    """
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
    if any(name in candidate.unknown for name in priced):
        return None
    return candidate.salary_per_month + sum(
        euros * candidate.scores[name] for name, euros in priced.items() if name in candidate.scores
    )


def rank(
    candidates: Sequence[Candidate],
    *,
    dimensions: Sequence[str],
    revision: ProfileRevision,
    weights: Mapping[str, Any] | None,
    at: str,
    currency: str | None = None,
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

    kept, dominated = frontier(candidates, dimensions)
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    totals = {
        offer_id: total
        for offer_id in kept
        if (total := salary_equivalent_total(by_id[offer_id], weights)) is not None
    }
    # Offers with no total sort last, in id order: a missing total is not a low
    # one, and the alternative — dropping them — is the collapse this module
    # refuses everywhere else.
    ordered = sorted(kept, key=lambda offer_id: (-totals.get(offer_id, float("-inf")), offer_id))

    return {
        "run_id": at,
        "profile_revision": revision.as_json(),
        "level": level,
        "currency": weights_currency or currency,
        "dimensions": list(dimensions),
        "pareto": ordered,
        "dominated": dominated,
        "facets": _facets(ordered, by_id, dimensions, totals),
        "salary_equivalent_total": totals,
        "unknown_dimensions": {
            offer_id: sorted(by_id[offer_id].unknown & set(dimensions))
            for offer_id in ordered
            if by_id[offer_id].unknown & set(dimensions)
        },
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


def dominance_violations(ranking: Mapping[str, Any], candidates: Sequence[Candidate]) -> int:
    """Audit the published lists against the candidates that produced them.

    Deliberately not a by-product of `frontier`: a count the construction hands
    itself can only ever be zero, whatever the construction did. This walks
    `pareto` and `dominated` as written and re-derives dominance from the
    candidates, so it can disagree — and
    `test_the_audit_reads_the_published_lists_not_the_pass_that_built_them`
    shows it doing so.

    Two things count as a violation: an offer on the frontier that another
    frontier member dominates, and a collapsed offer whose named collapser
    does not in fact dominate it.
    """
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    dimensions = tuple(ranking["dimensions"])
    published = list(ranking["pareto"])
    violations = 0

    for offer_id in published:
        mine = by_id.get(offer_id)
        if mine is None:
            violations += 1
            continue
        violations += any(
            other != offer_id and other in by_id and dominates(by_id[other], mine, dimensions)
            for other in published
        )

    for offer_id, note in ranking["dominated"].items():
        mine = by_id.get(offer_id)
        collapser = by_id.get(str(note).removeprefix(DOMINATED_BY))
        if mine is None or collapser is None or not dominates(collapser, mine, dimensions):
            violations += 1

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
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
