"""T243 — what a candidate said is priced, or the ranking says it is not.

Cases derive from the task text: every trait dimension with evidence either
reaches the weights or is reported as unpriced at ranking time, by name; a
stated trait ("spoken English costs me") reaches a coarse part-worth without a
round of choices; the gate is
`trait_dimensions_with_evidence_never_priced_and_never_reported == 0`.
Rules are closed (derived from the `Literal`s and tables, not listed) so a rung
or kind added later is covered without anyone remembering to.
"""

from __future__ import annotations

import json
from itertools import product
from pathlib import Path
from typing import Any, get_args

import pytest
from pydantic import ValidationError

from integral.feedback import traceability
from integral.identity import ProfileStore, create_profile
from integral.profile import (
    EvidenceLog,
    Kind,
    ProfileRevision,
    StatedDirection,
    StatedPrice,
    StatedStrength,
)
from integral.rank import (
    UNPRICED_CURRENCY,
    UNPRICED_NEGLIGIBLE,
    UNPRICED_NO_CHOICE,
    Candidate,
    RankingError,
    dominance_violations,
    priced_by,
    priced_dimensions,
    rank,
    rankable_dimensions,
    unpriced_trait_dimensions,
)
from integral.stated_pricing import (
    DEFAULT_EVIDENCE_PATH,
    SCENARIO_DIMENSIONS,
    _scenario,
    audit,
    measure,
    moves_order,
    pricing_inputs,
    record_stated_price,
)
from integral.weights import STATED_SIGNS, STATED_TIERS, Stated, stated_part_worths

REV = ProfileRevision(rows=1, sha256="0" * 64)
FITTED = {
    "currency": "EUR",
    "part_worths": {"remote": {"salary_equivalent_per_month": 600.0}},
    "negligible": ["flat"],
}


def _stated(dim: str, direction: str = "less", strength: str = "clear", cur: str = "EUR") -> Stated:
    return Stated(
        dimension=dim, direction=direction, strength=strength, currency=cur, row_id="ev-1"
    )


def _traits(**counts: int) -> dict[str, Any]:
    return {"dimensions": {name: {"evidence_count": n} for name, n in counts.items()}}


def _store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path, "Pricing test", handle="pricing-test")
    return ProfileStore(tmp_path, identity.handle)


# -- the tables are closed over the vocabulary ------------------------------


def test_every_strength_and_direction_has_a_figure_and_nothing_else_does() -> None:
    assert set(STATED_TIERS) == set(get_args(StatedStrength))
    assert set(STATED_SIGNS) == set(get_args(StatedDirection))


def test_tiers_ascend_so_a_stronger_statement_is_never_worth_less() -> None:
    order = list(get_args(StatedStrength))
    figures = [STATED_TIERS[name] for name in order]
    assert figures == sorted(figures) and len(set(figures)) == len(figures)


@pytest.mark.parametrize(("direction", "strength"), list(product(STATED_SIGNS, STATED_TIERS)))
def test_a_stated_figure_is_the_signed_rung(direction: str, strength: str) -> None:
    out = stated_part_worths([_stated("d", direction, strength)], {})
    figure = out["stated_part_worths"]["d"]["salary_equivalent_per_month"]
    # Sign from the words, not from the table under test: `less` is a cost.
    assert (figure < 0) == (direction == "less")
    assert abs(figure) == STATED_TIERS[strength]


# -- which number to trust ---------------------------------------------------


def test_nothing_stated_adds_no_key() -> None:
    assert stated_part_worths([], FITTED) == {}


def test_measured_beats_said_and_the_skip_is_named() -> None:
    out = stated_part_worths([_stated("remote", "less", "strong"), _stated("flat")], FITTED)
    assert out["stated_part_worths"] == {}
    assert out["stated_skipped"] == {"remote": "fitted", "flat": "negligible"}


def test_a_later_statement_replaces_an_earlier_one() -> None:
    out = stated_part_worths([_stated("d", "less", "strong"), _stated("d", "more", "slight")], {})
    assert out["stated_part_worths"]["d"]["salary_equivalent_per_month"] == STATED_TIERS["slight"]


def test_currency_is_the_fitted_one_else_the_first_statement() -> None:
    other = stated_part_worths([_stated("d", cur="USD")], FITTED)
    assert other["stated_skipped"] == {"d": "currency"} and "currency" not in other
    first = stated_part_worths([_stated("a", cur="USD"), _stated("b", cur="EUR")], {})
    assert first["currency"] == "USD" and first["stated_skipped"] == {"b": "currency"}


# -- the row is one dimension, on a statement --------------------------------


@pytest.mark.parametrize("kind", [k for k in get_args(Kind) if k != "statement"])
def test_only_a_statement_may_carry_a_price(kind: str, tmp_path: Path) -> None:
    log = EvidenceLog(_store(tmp_path))
    extra: dict[str, Any] = {"retracts": "ev-000001"} if kind == "retraction" else {}
    if kind == "retraction":
        log.append(recorded_at="t", step="s", kind="episode", text="x", source="conversation")
    with pytest.raises(ValidationError):
        log.append(
            recorded_at="t",
            step="s",
            kind=kind,  # type: ignore[arg-type]
            text="x",
            source="conversation",
            dimensions=("english_demand",),
            price=StatedPrice(direction="less", strength="clear", currency="EUR"),
            **extra,
        )


@pytest.mark.parametrize("dims", [(), ("a_dim", "b_dim")])
def test_a_price_names_exactly_one_dimension(dims: tuple[str, ...], tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        EvidenceLog(_store(tmp_path)).append(
            recorded_at="t",
            step="s",
            kind="statement",
            text="x",
            source="conversation",
            dimensions=dims,
            price=StatedPrice(direction="less", strength="clear", currency="EUR"),
        )


# -- the ranker reads both sources and reports what neither priced ----------


def test_priced_dimensions_reads_stated_beside_fitted_and_fitted_wins() -> None:
    weights = {
        "part_worths": {"a": {"salary_equivalent_per_month": 10.0}},
        "stated_part_worths": {
            "a": {"salary_equivalent_per_month": -999.0},
            "b": {"salary_equivalent_per_month": -300.0},
        },
    }
    assert priced_dimensions(weights) == {"a": 10.0, "b": -300.0}
    assert priced_by(weights) == {"fitted": ["a"], "stated": ["b"]}


def test_a_stated_figure_in_a_shape_the_ranker_cannot_read_is_refused() -> None:
    with pytest.raises(RankingError):
        priced_dimensions({"stated_part_worths": {"b": {"euros": 1}}})


def test_unpriced_names_every_dimension_with_evidence_and_gives_the_reason() -> None:
    weights = {
        **FITTED,
        "stated_part_worths": {"said": {"salary_equivalent_per_month": -300.0}},
        "stated_skipped": {"abroad": "currency"},
    }
    traits = _traits(remote=1, said=2, flat=1, abroad=1, silent=3, no_evidence=0)
    report = unpriced_trait_dimensions(traits, weights)
    assert report["checked"] is True
    assert report["reasons"] == {
        "abroad": UNPRICED_CURRENCY,
        "flat": UNPRICED_NEGLIGIBLE,
        "silent": UNPRICED_NO_CHOICE,
    }
    assert report["dimensions"] == sorted(report["reasons"])


def test_not_handing_over_the_traits_is_not_an_empty_report() -> None:
    assert unpriced_trait_dimensions(None, FITTED) == {
        "checked": False,
        "dimensions": [],
        "reasons": {},
    }


def test_rank_carries_the_report_and_the_sources() -> None:
    offer = Candidate(offer_id="o", salary_per_month=3000.0, scores={"remote": 1.0})
    ranking = rank(
        [offer],
        dimensions=["remote"],
        revision=REV,
        weights=FITTED,
        at="t",
        traits=_traits(remote=1, silent=1),
    )
    assert ranking["priced_by"] == {"fitted": ["remote"], "stated": []}
    assert ranking["unpriced_trait_dimensions"]["dimensions"] == ["silent"]
    bare = rank([offer], dimensions=["remote"], revision=REV, weights=FITTED, at="t")
    assert bare["unpriced_trait_dimensions"]["checked"] is False


def test_a_stated_price_on_an_unranked_dimension_needs_rankable_dimensions() -> None:
    weights = {"currency": "EUR", "stated_part_worths": {"b": {"salary_equivalent_per_month": 1.0}}}
    offer = Candidate(offer_id="o", salary_per_month=1.0, scores={"a": 0.0, "b": 0.0})
    with pytest.raises(RankingError):
        rank([offer], dimensions=["a"], revision=REV, weights=weights, at="t")
    dims = rankable_dimensions(["a"], weights)
    assert dims == ["a", "b"]
    assert rank([offer], dimensions=dims, revision=REV, weights=weights, at="t")["level"] == "L2"


# -- the property: a stated trait moves the order, in its direction ---------


def _two_offers(dim: str) -> list[Candidate]:
    return [
        Candidate(offer_id="high", salary_per_month=3000.0, scores={dim: 1.0}),
        Candidate(offer_id="low", salary_per_month=3000.0, scores={dim: -1.0}),
    ]


@pytest.mark.parametrize("direction", sorted(STATED_SIGNS))
def test_the_order_follows_the_stated_direction(direction: str, tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_stated_price(
        store,
        dimension="english_demand",
        direction=direction,  # type: ignore[arg-type]
        strength="clear",
        currency="EUR",
        text="said",
        at="2026-10-01T10:00:00Z",
    )
    traits, weights = pricing_inputs(store)
    ranking = rank(
        _two_offers("english_demand"),
        dimensions=rankable_dimensions(["english_demand"], weights),
        revision=REV,
        weights=weights,
        at="t",
        traits=traits,
    )
    first = "high" if direction == "more" else "low"
    assert ranking["pareto"][0] == first
    assert ranking["unpriced_trait_dimensions"]["dimensions"] == []


def test_a_retracted_statement_prices_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    row = record_stated_price(
        store,
        dimension="english_demand",
        direction="less",
        strength="strong",
        currency="EUR",
        text="said",
        at="t",
    )
    EvidenceLog(store).append(
        recorded_at="t2",
        step="s",
        kind="retraction",
        text="no",
        source="conversation",
        retracts=row,
    )
    _, weights = pricing_inputs(store)
    assert "stated_part_worths" not in weights
    assert not moves_order("english_demand", weights)


def test_a_stated_price_cites_its_row_for_feedback_traceability(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record_stated_price(
        store,
        dimension="english_demand",
        direction="less",
        strength="clear",
        currency="EUR",
        text="said",
        at="t",
    )
    pricing_inputs(store)
    assert traceability(store)["feedback_traceability"] == 1.0
    # ...and the claim exists: point it at a row the log does not have and it is untraced.
    path = store.path("profile", "weights.json")
    body = json.loads(path.read_text(encoding="utf-8"))
    body["stated_part_worths"]["english_demand"]["evidence"] = "ev-999999"
    path.write_text(json.dumps(body), encoding="utf-8")
    assert traceability(store)["feedback_traceability"] < 1.0


# -- the audit is read off the ranker, and can be seen to fail --------------


def test_the_audit_flags_an_unreported_unpriced_dimension_and_a_wrong_report() -> None:
    weights = {"currency": "EUR", "part_worths": {"remote": {"salary_equivalent_per_month": 5.0}}}
    traits = _traits(remote=1, silent=1)
    assert audit(traits, weights, ["silent"])["never_priced_and_never_reported"] == []
    assert audit(traits, weights, [])["never_priced_and_never_reported"] == ["silent"]
    assert audit(traits, weights, None)["never_priced_and_never_reported"] == ["silent"]
    wrong = audit(traits, weights, ["silent", "remote", "ghost"])
    assert wrong["reported_but_priced"] == ["remote"]
    assert wrong["reported_without_evidence"] == ["ghost"]


def test_moves_order_agrees_with_the_weights_for_every_dimension_in_the_scenario(
    tmp_path: Path,
) -> None:
    _, _, weights = _scenario(tmp_path)
    priced = set(priced_dimensions(weights))
    assert {d for d in SCENARIO_DIMENSIONS if moves_order(d, weights)} == priced


# -- the scenario and its committed measurement -----------------------------


def test_the_scenario_has_the_gates_numbers_and_every_planted_fault_is_seen() -> None:
    measured = measure()
    assert measured["trait_dimensions_with_evidence_never_priced_and_never_reported"] == 0
    assert measured["trait_dimensions_with_evidence"] >= 30
    assert measured["reported_unpriced_that_move_the_order"] == 0
    assert measured["reported_unpriced_without_evidence"] == 0
    assert measured["stated_figure_overrode_a_fitted_one"] == 0
    assert measured["retracted_statement_priced"] == 0
    assert measured["stated_trait_moves_the_order"] == 1
    assert measured["planted"] == {
        "name_dropped": 1,
        "report_absent": 1,
        "stated_figures_stripped": 1,
    }


def test_the_committed_evidence_is_what_the_code_measures() -> None:
    committed = json.loads(DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == measure()


# -- dominance follows the price's sign (a score is a level, not a verdict) --


@pytest.mark.parametrize("direction", sorted(STATED_SIGNS))
def test_the_offer_a_priced_preference_favours_is_never_the_one_collapsed(
    direction: str, tmp_path: Path
) -> None:
    store = _store(tmp_path)
    record_stated_price(
        store,
        dimension="english_demand",
        direction=direction,  # type: ignore[arg-type]
        strength="clear",
        currency="EUR",
        text="said",
        at="t",
    )
    traits, weights = pricing_inputs(store)
    offers = _two_offers("english_demand")
    ranking = rank(
        offers,
        dimensions=rankable_dimensions(["english_demand"], weights),
        revision=REV,
        weights=weights,
        at="t",
        traits=traits,
    )
    favoured, worse = ("high", "low") if direction == "more" else ("low", "high")
    assert ranking["pareto"] == [favoured]
    assert ranking["dominated"] == {worse: f"dominated_by:{favoured}"}
    assert ranking["dimension_signs"] == {"english_demand": STATED_SIGNS[direction]}
    assert dominance_violations(ranking, offers) == 0
    # The audit reads the published signs: strip them and the same lists are wrong.
    unsigned = {k: v for k, v in ranking.items() if k != "dimension_signs"}
    assert (dominance_violations(unsigned, offers) > 0) == (direction == "less")
