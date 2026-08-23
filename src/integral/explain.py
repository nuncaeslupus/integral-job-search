"""T19 — why an offer ranks where it does, in €/month and in the advert's words.

Specification §1: *"`explained_fraction == 1.0` — every ranked offer cites ≥1
verbatim evidence span per contributing dimension"*; §5.5 fixes the shape, one
entry per frontier offer:

```json
"sha256:9f2c…": {
  "salary_equivalent_delta_eur_month": 450,
  "drivers": [
    {"dimension": "social_intensity", "contribution_eur_month": 210,
     "evidence_span": "team offsites every quarter"}
  ]
}
```

T18 produces the ordering; this produces the account of it. The two are separate
because they can disagree, and a reader has to be able to see that they do: the
drivers are re-derived from the candidates and the weights, not read back out of
the number they are supposed to explain.

**The delta is the total minus the salary.** §4.3's ordering quantity is
`salary + sum_d weight(d) * score(d)`, so what the dimensions contributed is the
second term — and every driver is one of its addends. That makes the explanation
checkable by arithmetic rather than by reading: the drivers sum to the delta, or
the explanation is a story told beside the ranking instead of about it.

**Unpriced and neutral dimensions are not drivers.** A dimension T10 never priced
moved the total by nothing, and so did one scored at exactly neutral. Listing
either would pad the account with lines that explain no part of the number.

**The denominator is offers with at least one contributing dimension.** An L1
ranking prices nothing, so no offer has a contribution to cite and every offer
would be *vacuously* explained. A 1.0 there would report that the check never
ran — the same failure as a gate whose fenced block executes nothing, reached
through a metric instead of a missing command. With no priced dimension settled
anywhere, the fraction is `None` and `explanation_status` is `unmeasured`: not a
pass and not a fail (D-2).

**Stated ceiling — the span is verbatim by construction, not by re-checking.**
`EvidenceSpan` stores its quote beside offsets that `accept_model_scores` checks
against the advert, so a span that reaches a `Candidate` has already been proved
to be the ad's own text. This module never sees the advert and so cannot repeat
that proof; what it refuses is a *blank* quote, which is the one malformed span
`EvidenceSpan` would also have refused and which no amount of downstream counting
should launder into "a driver that happens to be uncited".
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from integral.profile import ProfileRevision
from integral.rank import Candidate, priced_dimensions, rank

# §4.3's site is `integral.rank`; this module explains that formula's second
# term rather than implementing a formula of its own, so it declares no
# METHODS_REF — see `integral.methods_links` on what the register requires.

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T19.json"


class ExplanationError(Exception):
    """An explanation cannot be built from what was handed in."""


def drivers_for(candidate: Candidate, weights: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """This offer's §4.3 addends, each with the ad's own words for it.

    Sorted by the size of the contribution, largest first, then by name: the
    line that moved the total most is the one a reader is looking for, and ties
    resolve by something stable rather than by dict order.
    """
    priced = priced_dimensions(weights)
    found: list[dict[str, Any]] = []
    for name in sorted(priced):
        if name not in candidate.scores:
            continue
        contribution = priced[name] * candidate.scores[name]
        if contribution == 0:
            continue
        spans = tuple(candidate.spans.get(name, ()))
        if any(not span.strip() for span in spans):
            raise ExplanationError(
                f"{candidate.offer_id}: {name} carries a blank evidence span — a quote "
                "that is not the advert's text is not a citation of it"
            )
        found.append(
            {
                "dimension": name,
                "contribution_eur_month": contribution,
                "evidence_span": spans[0] if spans else None,
            }
        )
    return sorted(found, key=lambda d: (-abs(d["contribution_eur_month"]), d["dimension"]))


def explain(
    ranking: Mapping[str, Any],
    candidates: Sequence[Candidate],
    weights: Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """§5.5's `explanations`, one entry per offer on the frontier.

    Collapsed offers are not here: `dominated` already names the offer that
    collapsed each of them, which is the whole of what there is to say about an
    offer that is not being shown. The card that says it to a person is T44.
    """
    by_id = {candidate.offer_id: candidate for candidate in candidates}
    explanations: dict[str, dict[str, Any]] = {}
    for offer_id in ranking["pareto"]:
        candidate = by_id.get(offer_id)
        if candidate is None:
            raise ExplanationError(
                f"{offer_id} is on the frontier and is not among the candidates — the "
                "ranking and the offers it was built from do not agree"
            )
        found = drivers_for(candidate, weights)
        explanations[offer_id] = {
            "salary_equivalent_delta_eur_month": sum(
                driver["contribution_eur_month"] for driver in found
            ),
            "drivers": found,
        }
    return explanations


def explained_fraction(
    ranking: Mapping[str, Any],
    candidates: Sequence[Candidate],
    weights: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """T19's gate: the fraction of driven offers whose every driver is cited."""
    explanations = explain(ranking, candidates, weights)
    driven = {
        offer_id: explanation
        for offer_id, explanation in explanations.items()
        if explanation["drivers"]
    }
    unexplained = sorted(
        offer_id
        for offer_id, explanation in driven.items()
        if any(driver["evidence_span"] is None for driver in explanation["drivers"])
    )
    return {
        "explained_fraction": (
            None if not driven else (len(driven) - len(unexplained)) / len(driven)
        ),
        "explanation_status": "unmeasured" if not driven else "measured",
        "offers_ranked": len(explanations),
        "offers_with_drivers": len(driven),
        "offers_without_drivers": len(explanations) - len(driven),
        "drivers": sum(len(e["drivers"]) for e in explanations.values()),
        "unexplained": unexplained,
    }


# The same market `integral.rank` measures T18 on, plus the advert wording each
# score was read from — so the two gates are answering about one ranking rather
# than about two fixtures that drifted apart.
_FIXTURE: tuple[tuple[str, float | None, dict[str, float], dict[str, tuple[str, ...]]], ...] = (
    (
        "sha256:" + "1" * 64,
        3600.0,
        {"remote": 1.0, "commute": -0.5, "mentoring": 0.2},
        {
            "remote": ("100% remote, no office",),
            "commute": ("two days a week on site",),
            "mentoring": ("a buddy for your first month",),
        },
    ),
    (
        "sha256:" + "2" * 64,
        4200.0,
        {"remote": -1.0, "commute": 0.8, "mentoring": -0.4},
        {
            "remote": ("presencial en nuestras oficinas",),
            "commute": ("junto a la estación de Sants",),
            "mentoring": ("buscamos un perfil autónomo",),
        },
    ),
    (
        "sha256:" + "3" * 64,
        3100.0,
        {"remote": 0.4, "commute": 0.4, "mentoring": 1.0},
        {
            "remote": ("teletreball dos dies per setmana",),
            "commute": ("oficina al centre",),
            "mentoring": ("pla de carrera amb mentor assignat",),
        },
    ),
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


def _fixture_candidates(strip: str | None = None) -> list[Candidate]:
    return [
        Candidate(
            offer_id=offer_id,
            salary_per_month=salary,
            scores=scores,
            unknown=frozenset(name for name in _FIXTURE_DIMENSIONS if name not in scores),
            spans={} if offer_id == strip else spans,
        )
        for offer_id, salary, scores, spans in _FIXTURE
    ]


def _rank(candidates: Sequence[Candidate]) -> dict[str, Any]:
    return rank(
        candidates,
        dimensions=_FIXTURE_DIMENSIONS,
        revision=ProfileRevision(rows=len(_FIXTURE), sha256="0" * 64),
        weights=_FIXTURE_WEIGHTS,
        at="2026-08-24T00:00:00Z",
    )


def measure() -> dict[str, Any]:
    """The gate's number, and proof it can fall."""
    candidates = _fixture_candidates()
    measured = explained_fraction(_rank(candidates), candidates, _FIXTURE_WEIGHTS)

    # Take one offer's spans away. If the fraction does not move, it is not
    # reading the spans at all and a 1.0 certifies the fixture, not the code.
    stripped = _fixture_candidates(strip=_FIXTURE[0][0])
    planted = explained_fraction(_rank(stripped), stripped, _FIXTURE_WEIGHTS)
    fell = planted["explained_fraction"] is not None and planted["explained_fraction"] < 1.0

    return {**measured, "fraction_falls_when_a_span_is_removed": int(fell)}


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T19's explanation coverage.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)

    print(f"explained_fraction: {measured['explained_fraction']} (== 1.0)")
    if measured["explanation_status"] == "unmeasured":
        print(
            "explained_fraction: UNMEASURED — no offer carries a priced dimension, so "
            "there is no contribution to cite. Not a pass and not a fail (D-2).",
            file=sys.stderr,
        )
        return 0
    if measured["explained_fraction"] != 1.0:
        print(f"uncited drivers on: {', '.join(measured['unexplained'])}", file=sys.stderr)
        return 1
    if not measured["fraction_falls_when_a_span_is_removed"]:
        print("the fraction did not fall when a span was removed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
