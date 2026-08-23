"""T18 — the Pareto frontier, the salary-equivalent order, and the facet lists.

The two tests the task payload names, the one `status/plan.md` adds, and the
ones that keep `pareto_dominance_violations == 0` from being a number the
frontier hands itself. A count computed by the same pass that built the
frontier can only ever be zero; the audit here walks the *published* lists and
re-derives dominance from the candidates, so a frontier that kept a dominated
offer is caught by something that did not help build it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.identity import ProfileStore
from integral.profile import ProfileRevision
from integral.rank import (
    Candidate,
    RankingError,
    dominance_violations,
    dominates,
    frontier,
    measure,
    rank,
    salary_equivalent_total,
    write_evidence,
    write_ranking,
)
from integral.rank import (
    _main as main,
)

DIMENSIONS = ("remote", "commute", "mentoring")
WEIGHTS = {
    "currency": "EUR",
    "part_worths": {
        "remote": {"utility_per_unit": 0.9, "salary_equivalent_per_month": 600.0},
        "commute": {"utility_per_unit": 0.3, "salary_equivalent_per_month": 200.0},
        "mentoring": {"utility_per_unit": 0.15, "salary_equivalent_per_month": 100.0},
    },
    "negligible": [],
    "separated": False,
    "salary_utility_per_month": 0.0015,
}
REVISION = ProfileRevision(rows=12, sha256="a" * 64)


def _candidate(offer_id: str, salary: float | None = 3000.0, **scores: float) -> Candidate:
    return Candidate(
        offer_id=offer_id,
        salary_per_month=salary,
        scores={name: scores[name] for name in DIMENSIONS if name in scores},
        unknown=frozenset(name for name in DIMENSIONS if name not in scores),
    )


def test_dominated_offer_never_appears_in_frontier() -> None:
    """An offer worse on every axis is collapsed, and says who collapsed it."""
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)
    worse = _candidate("sha256:bb", 3000.0, remote=0.2, commute=-0.5, mentoring=0.0)
    other = _candidate("sha256:cc", 2500.0, remote=-1.0, commute=1.0, mentoring=0.8)

    kept, dominated = frontier([best, worse, other], DIMENSIONS)
    assert "sha256:bb" not in kept
    assert dominated["sha256:bb"] == "dominated_by:sha256:aa"
    assert set(kept) == {"sha256:aa", "sha256:cc"}
    assert dominates(best, worse, DIMENSIONS)
    assert not dominates(best, other, DIMENSIONS)


def test_unknown_dimension_is_not_treated_as_neutral() -> None:
    """An advert that does not say is not an advert that says "average".

    `worse` loses on every dimension the advert settled and pays less, so
    reading its unstated `mentoring` as 0.0 would collapse it. Nothing in the
    advert supports that reading, and a collapsed offer is one the candidate
    never sees.
    """
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.0)
    worse = _candidate("sha256:bb", 3000.0, remote=0.2, commute=-0.5)

    assert worse.unknown == frozenset({"mentoring"})
    assert not dominates(best, worse, DIMENSIONS)
    kept, dominated = frontier([best, worse], DIMENSIONS)
    assert set(kept) == {"sha256:aa", "sha256:bb"}
    assert dominated == {}


def test_an_unknown_salary_blocks_the_claim_as_firmly_as_an_unknown_dimension() -> None:
    """Money is an axis of the comparison, so silence about it is silence."""
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)
    quiet = _candidate("sha256:bb", None, remote=0.2, commute=-0.5, mentoring=0.0)
    assert not dominates(best, quiet, DIMENSIONS)


def test_ranking_records_its_revision_and_level() -> None:
    """A provisional ranking that is not labelled provisional is a defect."""
    ranking = rank(
        [_candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert ranking["level"] == "L2"
    assert ranking["profile_revision"] == {"rows": 12, "sha256": "a" * 64}
    assert ranking["run_id"] == "2026-08-24T09:00:00Z"
    assert ranking["currency"] == "EUR"

    provisional = rank(
        [_candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=None,
        at="2026-08-24T09:00:00Z",
    )
    assert provisional["level"] == "L1"
    assert provisional["salary_equivalent_total"] == {}
    assert "best_salary_equivalent" not in provisional["facets"]


def test_weights_with_no_part_worths_are_not_weights() -> None:
    """T10 writes `weights.json` even while empty, so its presence proves nothing."""
    ranking = rank(
        [_candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights={"currency": "EUR", "part_worths": {}, "negligible": ["remote"]},
        at="2026-08-24T09:00:00Z",
    )
    assert ranking["level"] == "L1"


def test_the_total_is_salary_plus_what_the_dimensions_are_worth() -> None:
    """METHODS 4.3's formula, and nothing added to it."""
    offer = _candidate("sha256:aa", 3000.0, remote=1.0, commute=-0.5, mentoring=0.0)
    assert salary_equivalent_total(offer, WEIGHTS) == pytest.approx(
        3000.0 + 600.0 * 1.0 + 200.0 * -0.5 + 100.0 * 0.0
    )


def test_an_offer_missing_a_priced_dimension_has_no_total_rather_than_a_short_one() -> None:
    """A sum over fewer terms is not the same quantity, and orders differently.

    Silently summing the known dimensions would rank an advert that says
    little above one that says something bad — the shorter sum is simply
    closer to the salary. The offer keeps its place on the frontier; what it
    does not get is a number pretending to be comparable.
    """
    quiet = _candidate("sha256:bb", 3000.0, remote=1.0)
    assert salary_equivalent_total(quiet, WEIGHTS) is None

    ranking = rank(
        [
            _candidate("sha256:aa", 3000.0, remote=0.1, commute=0.1, mentoring=0.1),
            quiet,
        ],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert "sha256:bb" in ranking["pareto"]
    assert "sha256:bb" not in ranking["salary_equivalent_total"]
    assert ranking["unknown_dimensions"]["sha256:bb"] == ["commute", "mentoring"]


def test_an_offer_with_no_total_sorts_after_the_ones_that_have_one() -> None:
    """A missing total is not a high one, and never a low one either.

    It sorts last because there is nothing to compare it on, and it is kept
    because dropping it would be the collapse this module refuses everywhere
    else. The candidate sees it below the comparable offers, labelled with
    what the advert did not say.
    """
    quiet = _candidate("sha256:aa", 9000.0, remote=1.0)
    modest = _candidate("sha256:bb", 3000.0, remote=0.0, commute=0.0, mentoring=0.0)
    ranking = rank(
        [quiet, modest],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert ranking["pareto"] == ["sha256:bb", "sha256:aa"]


def test_a_dimension_cannot_be_both_scored_and_unknown() -> None:
    """The two fields answer one question, so they must not answer it twice."""
    with pytest.raises(RankingError, match="both scored and unknown"):
        Candidate(
            offer_id="sha256:aa",
            salary_per_month=3000.0,
            scores={"remote": 1.0},
            unknown=frozenset({"remote"}),
        )


def test_the_frontier_is_ordered_by_the_total_and_the_facets_name_the_best() -> None:
    rich = _candidate("sha256:aa", 4000.0, remote=-1.0, commute=0.0, mentoring=0.0)
    remote = _candidate("sha256:bb", 3000.0, remote=1.0, commute=0.0, mentoring=0.0)
    ranking = rank(
        [rich, remote],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert ranking["pareto"] == ["sha256:bb", "sha256:aa"]  # 3600 then 3400
    assert ranking["facets"]["best_salary_equivalent"] == ["sha256:bb"]
    assert ranking["facets"]["remote"] == ["sha256:bb"]
    assert ranking["facets"]["commute"] == ["sha256:aa", "sha256:bb"]  # tied, both named


def test_weights_in_another_currency_are_not_silently_converted() -> None:
    """No rate source exists here, so the only honest answer is to refuse."""
    with pytest.raises(RankingError, match="not this module's guess"):
        rank(
            [_candidate("sha256:aa", 3000.0, remote=1.0, commute=0.0, mentoring=0.0)],
            dimensions=DIMENSIONS,
            revision=REVISION,
            weights={**WEIGHTS, "currency": "GBP"},
            at="2026-08-24T09:00:00Z",
            currency="EUR",
        )


def test_the_audit_reads_the_published_lists_not_the_pass_that_built_them() -> None:
    """Plant a dominated offer in `pareto` and the count has to notice."""
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)
    worse = _candidate("sha256:bb", 3000.0, remote=0.2, commute=-0.5, mentoring=0.0)
    candidates = [best, worse]

    honest = rank(
        candidates,
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert dominance_violations(honest, candidates) == 0

    planted = {**honest, "pareto": ["sha256:aa", "sha256:bb"], "dominated": {}}
    assert dominance_violations(planted, candidates) == 1

    misattributed = {**honest, "dominated": {"sha256:bb": "dominated_by:sha256:zz"}}
    assert dominance_violations(misattributed, candidates) == 1


def test_a_dimension_named_in_neither_field_is_refused() -> None:
    """`unknown` defaults empty, so silence about a dimension has to be caught.

    Absent from `scores` and absent from `unknown` is a third state this
    module exists to abolish, and it fails quietly: the total would sum a
    shorter list and `dominates` would raise `KeyError`. Checked where the
    dimension set is known.
    """
    partial = Candidate(offer_id="sha256:aa", salary_per_month=3000.0, scores={"remote": 1.0})
    assert partial.unknown == frozenset()
    with pytest.raises(RankingError, match="neither a score nor an unknown"):
        frontier([partial], DIMENSIONS)
    assert salary_equivalent_total(partial, WEIGHTS) is None


def test_l1_orders_by_salary_because_that_is_what_l1_is() -> None:
    """Without weights there is no total, and falling back to id order is not an order.

    The salaries here run opposite to the offer ids, so a sort that quietly
    kept its tie-breaker would come out backwards.
    """
    poorer = _candidate("sha256:aa", 3000.0, remote=1.0, commute=0.0, mentoring=0.0)
    richer = _candidate("sha256:bb", 4000.0, remote=-1.0, commute=0.0, mentoring=0.0)
    ranking = rank(
        [poorer, richer],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=None,
        at="2026-08-24T09:00:00Z",
    )
    assert ranking["level"] == "L1"
    assert ranking["pareto"] == ["sha256:bb", "sha256:aa"]


def test_the_audit_checks_the_frontier_against_every_candidate_not_only_its_peers() -> None:
    """Dropping the dominator from both lists must not make the claim audit clean."""
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)
    worse = _candidate("sha256:bb", 3000.0, remote=0.2, commute=-0.5, mentoring=0.0)
    candidates = [best, worse]
    honest = rank(
        candidates,
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )

    # `bb` alone on the frontier, `aa` nowhere: no published peer contradicts
    # it, and only the candidates can.
    vanished = {**honest, "pareto": ["sha256:bb"], "dominated": {}}
    assert dominance_violations(vanished, candidates) >= 1

    # The case the partition check cannot also catch. `aa` is filed as
    # collapsed — so the partition is complete — by a `cc` that does not in
    # fact dominate it. `aa` is therefore not a published peer of `bb`, yet it
    # dominates it. Peers-only sees one violation here; the candidates see two.
    other = _candidate("sha256:cc", 2500.0, remote=-1.0, commute=1.0, mentoring=0.8)
    three = [best, worse, other]
    misfiled = {
        **honest,
        "pareto": ["sha256:cc", "sha256:bb"],
        "dominated": {"sha256:aa": "dominated_by:sha256:cc"},
    }
    assert dominance_violations(misfiled, three) == 2


def test_the_published_lists_must_partition_the_candidates() -> None:
    """Every offer that went in comes out somewhere, once."""
    best = _candidate("sha256:aa", 3500.0, remote=1.0, commute=0.5, mentoring=0.5)
    worse = _candidate("sha256:bb", 3000.0, remote=0.2, commute=-0.5, mentoring=0.0)
    candidates = [best, worse]
    honest = rank(
        candidates,
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    assert dominance_violations(honest, candidates) == 0

    both = {**honest, "pareto": ["sha256:aa", "sha256:bb"], "dominated": honest["dominated"]}
    # `bb` is published as kept *and* as collapsed: one dominance violation
    # for keeping it, one for the overlap.
    assert dominance_violations(both, candidates) == 2

    neither = {**honest, "dominated": {}}
    assert dominance_violations(neither, candidates) == 1


def test_a_ranking_is_written_under_the_candidates_own_tree(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path, "perico")
    ranking = rank(
        [_candidate("sha256:aa", 3000.0, remote=1.0, commute=0.0, mentoring=0.0)],
        dimensions=DIMENSIONS,
        revision=REVISION,
        weights=WEIGHTS,
        at="2026-08-24T09:00:00Z",
    )
    path = write_ranking(store, ranking)
    assert path.parent.name == "rankings"
    assert "perico" in str(path)
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "2026-08-24T09:00:00Z"


def test_main_writes_the_evidence_and_the_probe_plants_its_own_violation(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "T18.json"
    assert main([str(evidence)]) == 0
    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written == measure()
    assert written["pareto_dominance_violations"] == 0
    assert written["violation_detected_when_planted"] == 1
    assert write_evidence(tmp_path / "nested" / "T18.json") == written
