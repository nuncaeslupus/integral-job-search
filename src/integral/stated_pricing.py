"""T243 — what the candidate said is priced, or the ranking says it is not.

A candidate session (test-mode 658fcce2) had traits carrying evidence on thirty
of 41 dimensions and weights pricing two. The ranker adds priced dimensions and
nothing else, so what they said about being comfortable in the job, about
spoken English being harder than written, about the sectors they dislike could
not move an offer by a euro — and the ranking never said so. This module is the
join between the three things that were separate: `traits.json` (what the
candidate has said), `weights.json` (what is priced) and the ranking (what
moved).

Three decisions worth stating.

**Said and measured are different numbers, and the file keeps them apart.** The
route from "spoken English costs me" to a part-worth is a statement row with a
`StatedPrice` — a direction and one of three strengths, no euro figure, because
the candidate cannot give one. `integral.weights.STATED_TIERS` converts the rung
into a coarse figure that lands under `stated_part_worths`, never inside
`part_worths`: a fitted figure outranks a stated one, and
`step_runtime._weights_fitted` must not read a sentence as a round of choices.
The ranking says which dimensions each source priced (`priced_by`).

**An unpriced dimension with evidence is named, not dropped.** `rank(traits=...)`
carries `unpriced_trait_dimensions`: every dimension the traits hold evidence on
that the order cannot move on, with the reason. A dimension is never absent
from both lists, which is what the gate counts. `checked: false` is the answer
when nobody passed the traits — "not looked" is stated, never an empty list.

**The audit asks the ranker, not the report.** `moves_order` takes a dimension
and two offers alike but for their score on it, ranks them, and asks whether
their positions' basis value differs. That is the property — *this dimension
moves the order* — read off `rank`'s own output; it shares nothing with
`priced_by` or the report, so the count cannot be made zero by the two agreeing
with each other. A dimension that moves nothing and is reported is fine; one
that moves nothing and is not reported is the defect. The reverse is audited
too: a dimension reported as unpriced that does move the order, or one with no
evidence at all, is a wrong report.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from integral.identity import ProfileStore, create_profile
from integral.profile import (
    EvidenceLog,
    ProfileRevision,
    StatedDirection,
    StatedPrice,
    StatedStrength,
    rebuild,
)
from integral.rank import Candidate, priced_dimensions, rank, rankable_dimensions
from integral.weights import Choice, Package, encode_choice

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T243.json"

#: Thirty ontology ids, as many as the real session's traits carried evidence
#: on. Named rather than read from `dimensions/` so a dimension added later
#: cannot move the count. The task gate asserts the *measured*
#: `trait_dimensions_with_evidence >= 30` read back from `traits.json`, not
#: `len()` of this tuple, so a renamed id that stopped carrying evidence fails
#: there instead of passing against its own list.
SCENARIO_DIMENSIONS: tuple[str, ...] = (
    "ai_in_the_work",
    "ambition",
    "career_progression",
    "collaboration_mode",
    "commute_burden",
    "company_stage",
    "compensation_transparency",
    "contract_stability",
    "contracted_hours",
    "creativity",
    "domain_knowledge",
    "english_demand",
    "hiring_process_burden",
    "inclusion_commitment",
    "leadership",
    "learning_orientation",
    "local_language_demand",
    "mentoring_culture",
    "mission_alignment",
    "on_call_load",
    "process_formality",
    "product_vs_services",
    "remote_arrangement",
    "role_breadth",
    "schedule_flexibility",
    "social_intensity",
    "stack_modernity",
    "talking_clients",
    "team_autonomy",
    "work_intensity",
)

#: Dimensions the scenario prices by forced choice.
_FITTED = {
    "remote": "remote_arrangement",
    "commute": "commute_burden",
    "mentoring": "mentoring_culture",
}
_AT = "2026-10-01T10:00:00Z"
_PROBE_AXIS = "__probe__"


def record_stated_price(
    store: ProfileStore,
    *,
    dimension: str,
    direction: StatedDirection,
    strength: StatedStrength,
    currency: str,
    text: str,
    at: str,
    step: str = "ranking",
) -> str:
    """Write the candidate's stated trait down as a priced statement; return the row id.

    The route the step-09 skill uses when someone says "spoken English costs me"
    or "I want a mentor": their words go in `text`, what they mean in `price`.
    """
    row = EvidenceLog(store).append(
        recorded_at=at,
        step=step,
        kind="statement",
        text=text,
        source="conversation",
        dimensions=(dimension,),
        price=StatedPrice(direction=direction, strength=strength, currency=currency),
    )
    return row.id


def pricing_inputs(store: ProfileStore) -> tuple[dict[str, Any], dict[str, Any]]:
    """`(traits.json, weights.json)` rebuilt from the log, for `rank(traits=..., weights=...)`."""
    written = rebuild(store)
    return json.loads(written["traits.json"]), json.loads(written["weights.json"])


def _probe_offers(dimension: str, priced: Mapping[str, float]) -> list[Candidate]:
    # `__probe__` is a ranked axis both offers leave unknown, so neither
    # dominates the other and both survive to be read: the question is about the
    # order's reading, not about the frontier.
    unknown = (frozenset(priced) | {_PROBE_AXIS}) - {dimension}
    return [
        Candidate(
            offer_id=f"probe-{name}",
            salary_per_month=3000.0,
            scores={dimension: score},
            unknown=unknown,
        )
        for name, score in (("high", 1.0), ("low", -1.0))
    ]


def moves_order(dimension: str, weights: Mapping[str, Any] | None) -> bool:
    """Does the ranker order two offers apart that differ only on `dimension`?

    Read off `rank`'s own `order_basis`, never off `priced_by` or the report.
    Both probes carry the same salary and every other priced dimension unknown,
    so the known parts differ exactly when this dimension carries a price.
    """
    priced = priced_dimensions(weights)
    probes = _probe_offers(dimension, priced)
    ranking = rank(
        probes,
        dimensions=rankable_dimensions([dimension, _PROBE_AXIS], weights),
        revision=ProfileRevision.of_nothing(),
        weights=weights,
        at=_AT,
    )
    basis = ranking["order_basis"]
    return bool(basis["probe-high"]["value"] != basis["probe-low"]["value"])


def audit(
    traits: Mapping[str, Any],
    weights: Mapping[str, Any] | None,
    reported: Sequence[str] | None,
) -> dict[str, Any]:
    """Count the ways a ranking's report of unpriced traits is wrong.

    `reported` is the ranking's own `unpriced_trait_dimensions.dimensions`, or
    `None` when the ranking made no report.
    """
    evidence = sorted(
        name
        for name, entry in (traits.get("dimensions") or {}).items()
        if isinstance(entry, Mapping) and (entry.get("evidence_count") or 0) > 0
    )
    said = set(reported or ())
    moving = {name for name in evidence if moves_order(name, weights)}
    never_priced_never_reported = [n for n in evidence if n not in moving and n not in said]
    reported_but_priced = sorted(name for name in said if moves_order(name, weights))
    reported_without_evidence = sorted(name for name in said if name not in set(evidence))
    return {
        "dimensions_with_evidence": len(evidence),
        "dimensions_that_move_the_order": len(moving),
        "never_priced_and_never_reported": never_priced_never_reported,
        "reported_but_priced": reported_but_priced,
        "reported_without_evidence": reported_without_evidence,
    }


def _choices(store: ProfileStore, currency: str) -> None:
    """Step 6's forced choices, on three real dimensions, as reaction rows."""
    from integral import weights as w

    log = EvidenceLog(store)
    for choice in w._fixture_choices().choices:
        renamed = Choice(
            a=Package(
                salary_per_month=choice.a.salary_per_month,
                dimensions={_FITTED[k]: v for k, v in choice.a.dimensions.items()},
            ),
            b=Package(
                salary_per_month=choice.b.salary_per_month,
                dimensions={_FITTED[k]: v for k, v in choice.b.dimensions.items()},
            ),
            chosen=choice.chosen,
        )
        log.append(
            recorded_at=_AT,
            step="preferences",
            kind="reaction",
            text=encode_choice(renamed, currency=currency),
            source="conversation",
        )


def _scenario(root: Path) -> tuple[ProfileStore, dict[str, Any], dict[str, Any]]:
    """A candidate like the real one: evidence on thirty dimensions, choices on three.

    Statements price three more in the candidate's currency and one in another;
    one priced statement is retracted; one tries to override a fitted figure.
    """
    identity = create_profile(root, "Pricing scenario", handle="pricing-scenario")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    for dimension in SCENARIO_DIMENSIONS:
        log.append(
            recorded_at=_AT,
            step="history",
            kind="episode",
            text=f"an episode about {dimension}",
            source="conversation",
            dimensions=(dimension,),
        )
    _choices(store, "EUR")
    for dimension, direction, strength, currency in (
        ("english_demand", "less", "strong", "EUR"),
        ("mission_alignment", "less", "clear", "EUR"),
        ("stack_modernity", "more", "slight", "EUR"),
        ("on_call_load", "less", "clear", "USD"),
        ("remote_arrangement", "less", "strong", "EUR"),
    ):
        record_stated_price(
            store,
            dimension=dimension,
            direction=direction,  # type: ignore[arg-type]
            strength=strength,  # type: ignore[arg-type]
            currency=currency,
            text=f"stated: {direction} {dimension}",
            at=_AT,
        )
    withdrawn = record_stated_price(
        store,
        dimension="leadership",
        direction="more",
        strength="strong",
        currency="EUR",
        text="stated, then withdrawn",
        at=_AT,
    )
    log.append(
        recorded_at=_AT,
        step="ranking",
        kind="retraction",
        text="forget that",
        source="conversation",
        retracts=withdrawn,
    )
    traits, weights = pricing_inputs(store)
    return store, traits, weights


def _offers() -> list[Candidate]:
    return [
        Candidate(
            offer_id=f"offer-{index}",
            salary_per_month=3300.0 - 100.0 * index,
            scores={"english_demand": score},
        )
        for index, score in enumerate((1.0, 0.0, -1.0))
    ]


def _ranking(weights: Mapping[str, Any], traits: Mapping[str, Any] | None) -> dict[str, Any]:
    dimensions = rankable_dimensions(["english_demand"], weights)
    offers = [
        Candidate(
            offer_id=c.offer_id,
            salary_per_month=c.salary_per_month,
            scores=c.scores,
            unknown=frozenset(d for d in dimensions if d != "english_demand"),
        )
        for c in _offers()
    ]
    return rank(
        offers,
        dimensions=dimensions,
        revision=ProfileRevision.of_nothing(),
        weights=weights,
        at=_AT,
        traits=traits,
    )


def measure() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        _, traits, weights = _scenario(Path(tmp))
    ranking = _ranking(weights, traits)
    report = ranking["unpriced_trait_dimensions"]
    honest = audit(traits, weights, report["dimensions"])

    # Planted faults, each of which must raise the count or the zero proves
    # nothing: no report at all, one name dropped from it, and weights with the
    # statements' figures stripped but the report left as the ranker wrote it.
    unchecked = _ranking(weights, None)["unpriced_trait_dimensions"]["dimensions"]
    no_report = audit(traits, weights, unchecked)
    dropped = audit(traits, weights, report["dimensions"][1:])
    stripped_weights = {k: v for k, v in weights.items() if k != "stated_part_worths"}
    stripped = audit(traits, stripped_weights, report["dimensions"])
    planted = {
        "report_absent": int(bool(no_report["never_priced_and_never_reported"])),
        "name_dropped": int(bool(dropped["never_priced_and_never_reported"])),
        "stated_figures_stripped": int(bool(stripped["never_priced_and_never_reported"])),
    }

    stated = sorted(weights.get("stated_part_worths", {}))
    fitted_wins = weights["part_worths"]["remote_arrangement"]["salary_equivalent_per_month"]
    stated_overrode_fitted = int(
        priced_dimensions(weights)["remote_arrangement"] != fitted_wins
        or "remote_arrangement" in stated
    )
    positions = ranking["pareto"]
    return {
        "trait_dimensions_with_evidence_never_priced_and_never_reported": len(
            honest["never_priced_and_never_reported"]
        ),
        "trait_dimensions_with_evidence": honest["dimensions_with_evidence"],
        "dimensions_that_move_the_order": honest["dimensions_that_move_the_order"],
        "reported_unpriced_that_move_the_order": len(honest["reported_but_priced"]),
        "reported_unpriced_without_evidence": len(honest["reported_without_evidence"]),
        "stated_dimensions_priced": len(stated),
        "stated_figure_overrode_a_fitted_one": stated_overrode_fitted,
        "retracted_statement_priced": int("leadership" in stated),
        "stated_skipped": dict(sorted(weights.get("stated_skipped", {}).items())),
        "stated_trait_moves_the_order": int(positions == ["offer-2", "offer-1", "offer-0"]),
        "unpriced_reasons": sorted(set(report["reasons"].values())),
        "planted": planted,
        "violation_detected_when_planted": int(all(planted.values())),
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T243's priced stated preferences.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)
    name = "trait_dimensions_with_evidence_never_priced_and_never_reported"
    print(f"{name}: {measured[name]} (== 0)")
    print(f"violation_detected_when_planted: {measured['violation_detected_when_planted']}")
    bad = (
        measured[name]
        or measured["reported_unpriced_that_move_the_order"]
        or measured["reported_unpriced_without_evidence"]
        or measured["stated_figure_overrode_a_fitted_one"]
        or measured["retracted_statement_priced"]
        or not measured["stated_trait_moves_the_order"]
        or not measured["violation_detected_when_planted"]
    )
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
