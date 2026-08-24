"""T19 — `explained_fraction == 1.0`: a ranked offer says why, in the ad's words.

§1's criterion is *"every ranked offer cites ≥1 verbatim evidence span per
contributing dimension"*, and §5.5 fixes the shape: per offer, a
`salary_equivalent_delta_eur_month` and a list of `drivers`, each naming its
dimension, its `contribution_eur_month` and the `evidence_span` it rests on.

Two properties carry the criterion, and they are not the same property:

* **arithmetic** — the drivers account for the delta exactly. An explanation
  whose parts do not sum to the number it explains is a plausible story told
  beside a ranking rather than about it.
* **provenance** — every driver's span is text really in the advert. §2.6's
  whole claim is that the wording is the signal; a paraphrase is the tool's
  words dressed as the employer's.

The denominator is offers **with at least one contributing dimension**. An L1
ranking prices nothing, so every offer would be vacuously explained and a 1.0
would report that the check never ran — the failure the fenced-gate rule exists
to prevent, arrived at through a metric instead of a missing command.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from integral.explain import (
    ExplanationError,
    explain,
    explained_fraction,
    measure,
    write_evidence,
)
from integral.extraction import (
    DimensionScore,
    EvidenceSpan,
    OfferExtraction,
    normalise,
)
from integral.offers import Offer, compute_offer_id
from integral.profile import ProfileRevision
from integral.rank import Candidate, from_extraction, rank

_DIMENSIONS = ("commute", "mentoring", "remote")
_WEIGHTS: dict[str, Any] = {
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


def _candidate(
    offer_id: str,
    salary: float | None,
    scores: dict[str, float],
    spans: dict[str, tuple[str, ...]] | None = None,
) -> Candidate:
    return Candidate(
        offer_id=offer_id,
        salary_per_month=salary,
        scores=scores,
        unknown=frozenset(name for name in _DIMENSIONS if name not in scores),
        spans=spans if spans is not None else {name: (f"cue for {name}",) for name in scores},
    )


def _ranking(candidates: list[Candidate], weights: dict[str, Any] | None = _WEIGHTS) -> Any:
    return rank(
        candidates,
        dimensions=_DIMENSIONS,
        revision=ProfileRevision(rows=len(candidates), sha256="0" * 64),
        weights=weights,
        at="2026-08-24T00:00:00Z",
    )


def _market() -> list[Candidate]:
    return [
        _candidate(
            "sha256:" + "1" * 64, 3600.0, {"remote": 1.0, "commute": -0.5, "mentoring": 0.2}
        ),
        _candidate(
            "sha256:" + "2" * 64, 4200.0, {"remote": -1.0, "commute": 0.8, "mentoring": -0.4}
        ),
        _candidate("sha256:" + "3" * 64, 3100.0, {"remote": 0.4, "commute": 0.4, "mentoring": 1.0}),
    ]


def test_every_ranked_offer_cites_evidence() -> None:
    """The named gate test: ≥1 verbatim span per contributing dimension."""
    candidates = _market()
    explanations = explain(_ranking(candidates), candidates, _WEIGHTS)

    assert explanations
    for offer_id, explanation in explanations.items():
        assert explanation["drivers"], offer_id
        for driver in explanation["drivers"]:
            assert driver["evidence_span"], (offer_id, driver["dimension"])


def test_the_fraction_is_one_when_every_driver_is_cited() -> None:
    candidates = _market()
    assert (
        explained_fraction(_ranking(candidates), candidates, _WEIGHTS)["explained_fraction"] == 1.0
    )


def test_a_driver_with_no_span_drops_the_fraction() -> None:
    """The measurement has to be able to fail, or it certifies nothing."""
    candidates = _market()
    stripped = [
        _candidate(candidates[0].offer_id, 3600.0, dict(candidates[0].scores), spans={}),
        *candidates[1:],
    ]
    measured = explained_fraction(_ranking(stripped), stripped, _WEIGHTS)

    assert measured["explained_fraction"] < 1.0
    assert candidates[0].offer_id in measured["unexplained"]


def test_the_drivers_account_for_the_delta_exactly() -> None:
    candidates = _market()
    explanations = explain(_ranking(candidates), candidates, _WEIGHTS)

    for explanation in explanations.values():
        total = sum(driver["contribution_eur_month"] for driver in explanation["drivers"])
        assert explanation["salary_equivalent_delta_eur_month"] is not None
        assert total == pytest.approx(explanation["salary_equivalent_delta_eur_month"])


def test_the_delta_is_the_total_minus_the_salary() -> None:
    """The delta explains the ordering quantity, not a number of its own."""
    candidates = _market()
    ranking = _ranking(candidates)
    explanations = explain(ranking, candidates, _WEIGHTS)

    for offer_id, explanation in explanations.items():
        salary = next(c.salary_per_month for c in candidates if c.offer_id == offer_id)
        assert salary is not None
        total = ranking["salary_equivalent_total"][offer_id]
        assert explanation["salary_equivalent_delta_eur_month"] == pytest.approx(total - salary)


def test_an_unpriced_dimension_is_not_a_driver() -> None:
    """A dimension T10 never priced contributes nothing, so it explains nothing."""
    candidates = _market()
    weights = {**_WEIGHTS, "part_worths": {"remote": _WEIGHTS["part_worths"]["remote"]}}
    explanations = explain(_ranking(candidates, weights), candidates, weights)

    named = {driver["dimension"] for e in explanations.values() for driver in e["drivers"]}
    assert named == {"remote"}


def test_a_zero_contribution_is_not_a_driver() -> None:
    """A dimension scored at exactly neutral moved the total by nothing."""
    candidates = [
        _candidate("sha256:" + "7" * 64, 3000.0, {"remote": 0.0, "commute": 0.5, "mentoring": 0.5})
    ]
    explanations = explain(_ranking(candidates), candidates, _WEIGHTS)

    named = {driver["dimension"] for driver in explanations[candidates[0].offer_id]["drivers"]}
    assert "remote" not in named


def test_an_l1_ranking_is_unmeasured_not_perfect() -> None:
    """Nothing is priced, so no offer has a contribution to cite. A 1.0 here
    would report that the check never ran (D-2: not a pass and not a fail)."""
    candidates = _market()
    measured = explained_fraction(_ranking(candidates, None), candidates, None)

    assert measured["explained_fraction"] is None
    assert measured["explanation_status"] == "unmeasured"
    assert measured["offers_with_drivers"] == 0


def test_an_offer_with_no_settled_priced_dimension_is_out_of_the_denominator() -> None:
    """It carries no claim to cite — but it is counted where it can be seen."""
    quiet = _candidate("sha256:" + "8" * 64, 3000.0, {})
    candidates = [*_market(), quiet]
    measured = explained_fraction(_ranking(candidates), candidates, _WEIGHTS)

    assert measured["explained_fraction"] == 1.0
    assert measured["offers_without_drivers"] == 1
    assert quiet.offer_id not in measured["unexplained"]


def test_a_blank_span_is_refused_rather_than_counted_as_a_citation() -> None:
    """`EvidenceSpan` refuses an empty quote, so one arriving here bypassed the
    extraction that builds spans from the ad. Reporting it as a merely
    uncited driver would file a malformed input as a measurement."""
    candidates = [
        _candidate("sha256:" + "9" * 64, 3000.0, {"remote": 1.0}, spans={"remote": ("",)})
    ]
    with pytest.raises(ExplanationError):
        explain(_ranking(candidates), candidates, _WEIGHTS)


def test_a_span_reaching_an_explanation_is_byte_identical_to_the_advert() -> None:
    """End to end through the real extraction path — no hand-built span.

    §2.6's claim is about the employer's wording, so the text a candidate reads
    in an explanation has to be a slice of the advert and not a paraphrase of it.
    """
    text = "Trabajo 100% en remoto y con mentoring semanal para el equipo."
    ad = normalise(
        Offer(
            id=compute_offer_id(text),
            source="fixture",
            source_ref="1",
            title="Dev",
            text=text,
            url="https://example.invalid/1",
            language="es",
        )
    )
    start = text.index("100% en remoto")
    extraction = OfferExtraction(
        offer_id=ad.offer_id,
        language="es",
        scores=[
            DimensionScore(
                dimension="remote",
                value=1.0,
                spans=[
                    EvidenceSpan(
                        start=start,
                        end=start + len("100% en remoto"),
                        quote=ad.slice(start, start + len("100% en remoto")),
                    )
                ],
                provenance="rules",
            )
        ],
        unsettled=["commute", "mentoring"],
    )
    candidate = from_extraction(extraction, dimensions=_DIMENSIONS, salary_per_month=3000.0)
    weights = {**_WEIGHTS, "part_worths": {"remote": _WEIGHTS["part_worths"]["remote"]}}
    explanations = explain(_ranking([candidate], weights), [candidate], weights)

    span = explanations[candidate.offer_id]["drivers"][0]["evidence_span"]
    assert span in text
    assert span == "100% en remoto"


def test_measure_proves_the_fraction_can_fall() -> None:
    """A gate that only ever saw a passing input certifies the input, not the code."""
    measured = measure()
    assert measured["explained_fraction"] == 1.0
    assert measured["fraction_falls_when_a_span_is_removed"] == 1


def test_write_evidence_records_the_gate_key(tmp_path: Path) -> None:
    evidence = tmp_path / "T19.json"
    write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8"))["explained_fraction"] == 1.0


# ---------------------------------------------------------------------------
# An offer that reached the frontier with no salary-equivalent total.
# `rank` withholds one when the salary is missing or a priced dimension is
# unset, and the offer still ranks — so `explain` is handed exactly the case
# where the drivers it can compute do not add up to anything.


def test_an_offer_with_no_total_gets_no_delta() -> None:
    """A partial sum published as "the delta" is a number for a quantity that
    does not exist."""
    partial = _candidate("sha256:" + "b" * 64, 3600.0, {"remote": 1.0})  # commute unset
    explanations = explain(_ranking([partial]), [partial], _WEIGHTS)
    explanation = explanations[partial.offer_id]

    assert explanation["salary_equivalent_delta_eur_month"] is None
    assert "commute" in explanation["delta_unavailable"]
    assert explanation["drivers"], "the contributions it does have are still true"


def test_an_offer_with_no_salary_gets_no_delta() -> None:
    unpaid = _candidate(
        "sha256:" + "c" * 64, None, {"remote": 1.0, "commute": 0.5, "mentoring": 0.0}
    )
    explanations = explain(_ranking([unpaid]), [unpaid], _WEIGHTS)
    explanation = explanations[unpaid.offer_id]

    assert explanation["salary_equivalent_delta_eur_month"] is None
    assert "no salary" in explanation["delta_unavailable"]


def test_an_offer_with_a_total_still_carries_its_reason_for_having_one() -> None:
    """`delta_unavailable` is absent-as-None, not omitted: a reader checking the
    key must not have to tell "no reason" from "the key was not written"."""
    whole = _market()[0]
    explanation = explain(_ranking([whole]), [whole], _WEIGHTS)[whole.offer_id]

    assert explanation["delta_unavailable"] is None
    assert explanation["salary_equivalent_delta_eur_month"] is not None


def test_the_uncited_count_is_unaffected_by_a_missing_total() -> None:
    """Citation and arithmetic are separate properties — a driver with a span is
    cited whether or not its offer's total exists."""
    partial = _candidate("sha256:" + "d" * 64, 3600.0, {"remote": 1.0})
    measured = explained_fraction(_ranking([partial]), [partial], _WEIGHTS)

    assert measured["explained_fraction"] == 1.0


def test_an_l1_offer_with_a_salary_does_not_blame_the_advert() -> None:
    """Nothing is priced, so there is no total — an omission on the candidate's
    side of the process, not the employer's. The earlier wording produced "the
    advert does not settle , so…" and attributed it to the ad."""
    whole = _market()[0]
    explanation = explain(_ranking([whole], None), [whole], None)[whole.offer_id]

    assert explanation["salary_equivalent_delta_eur_month"] is None
    assert "no preference weights" in explanation["delta_unavailable"]
    assert "does not settle ," not in explanation["delta_unavailable"]
