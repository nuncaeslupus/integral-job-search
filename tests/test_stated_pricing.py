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
from itertools import permutations, product
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
    PayBand,
    RankingError,
    dominance_violations,
    priced_by,
    priced_dimensions,
    rank,
    rankable_dimensions,
    unpriced_trait_dimensions,
    weights_for_currency,
)
from integral.stated_pricing import (
    DEFAULT_EVIDENCE_PATH,
    SCENARIO_DIMENSIONS,
    StatedPricingError,
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


def test_a_statement_never_sets_a_currency() -> None:
    other = stated_part_worths([_stated("d", cur="USD")], FITTED)
    assert other["stated_skipped"] == {"d": "currency"} and "currency" not in other
    # No fit: every statement keeps its own currency and nothing top-level is written.
    free = stated_part_worths([_stated("a", cur="USD"), _stated("b", cur="EUR")], {})
    assert "currency" not in free and free["stated_skipped"] == {}
    assert {n: p["currency"] for n, p in free["stated_part_worths"].items()} == {
        "a": "USD",
        "b": "EUR",
    }


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
        "currency": "EUR",
        "part_worths": {"a": {"salary_equivalent_per_month": 10.0}},
        "stated_part_worths": {
            "a": {"salary_equivalent_per_month": -999.0, "currency": "EUR"},
            "b": {"salary_equivalent_per_month": -300.0, "currency": "EUR"},
            "c": {"salary_equivalent_per_month": -300.0, "currency": "USD"},
        },
    }
    assert priced_dimensions(weights) == {"a": 10.0, "b": -300.0}
    assert priced_by(weights) == {"fitted": ["a"], "stated": ["b"]}


def test_a_stated_figure_in_a_shape_the_ranker_cannot_read_is_refused() -> None:
    with pytest.raises(RankingError):
        priced_dimensions(
            {"currency": "EUR", "stated_part_worths": {"b": {"euros": 1, "currency": "EUR"}}}
        )


def test_unpriced_names_every_dimension_with_evidence_and_gives_the_reason() -> None:
    weights = {
        **FITTED,
        "stated_part_worths": {"said": {"salary_equivalent_per_month": -300.0, "currency": "EUR"}},
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
    weights = {"stated_part_worths": {"b": {"salary_equivalent_per_month": 1.0, "currency": "EUR"}}}
    offer = Candidate(offer_id="o", salary_per_month=1.0, scores={"a": 0.0, "b": 0.0})
    with pytest.raises(RankingError):
        rank([offer], dimensions=["a"], revision=REV, weights=weights, at="t", currency="EUR")
    dims = rankable_dimensions(["a"], weights, "EUR")
    assert dims == ["a", "b"]
    kw: dict[str, Any] = {"revision": REV, "weights": weights, "at": "t", "currency": "EUR"}
    assert rank([offer], dimensions=dims, **kw)["level"] == "L2"


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
        dimensions=rankable_dimensions(["english_demand"], weights, "EUR"),
        revision=REV,
        weights=weights,
        at="t",
        traits=traits,
        currency="EUR",
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
        dimensions=rankable_dimensions(["english_demand"], weights, "EUR"),
        revision=REV,
        weights=weights,
        at="t",
        traits=traits,
        currency="EUR",
    )
    favoured, worse = ("high", "low") if direction == "more" else ("low", "high")
    assert ranking["pareto"] == [favoured]
    assert ranking["dominated"] == {worse: f"dominated_by:{favoured}"}
    assert ranking["dimension_signs"] == {"english_demand": STATED_SIGNS[direction]}
    assert dominance_violations(ranking, offers, weights, "EUR") == 0
    # B2: the audit takes its signs from the weights, never from the ranking under
    # audit. A forged ranking that collapses the favoured offer is a violation whatever
    # `dimension_signs` it carries: removed, flipped, or honest.
    forged = {
        "pareto": [worse],
        "dominated": {favoured: f"dominated_by:{worse}"},
        "dimensions": ranking["dimensions"],
    }
    for signs in (None, {"english_demand": 1.0}, {"english_demand": -1.0}):
        claim = forged if signs is None else {**forged, "dimension_signs": signs}
        assert dominance_violations(claim, offers, weights, "EUR") > 0
    # And with no weights there is nothing priced, so the older reading stands.
    assert (dominance_violations(ranking, offers) > 0) == (direction == "less")


# -- B1: a statement never sets the ranking's currency -----------------------

_STATEMENTS = (
    _stated("x", cur="USD"),
    _stated("y", cur="EUR"),
    _stated("z", cur="EUR"),
)
_FIT_EUR = {
    "currency": "EUR",
    "part_worths": {"remote": {"salary_equivalent_per_month": 600.0}},
}


def _band_offers() -> list[Candidate]:
    """An EUR band with no point inside it: T138 refuses this in EUR."""
    return [
        Candidate(
            offer_id="paid-band-no-point",
            salary_per_month=None,
            scores={},
            pay=PayBand(low=2500.0, high=3500.0, currency="EUR"),
        ),
        Candidate(offer_id="point", salary_per_month=2800.0, scores={}),
    ]


def _outcome(weights: dict[str, Any] | None, currency: str | None) -> tuple[Any, ...]:
    dims = rankable_dimensions([], weights, currency)
    offers = [
        Candidate(
            offer_id=c.offer_id,
            salary_per_month=c.salary_per_month,
            scores={},
            unknown=frozenset(dims),
            pay=c.pay,
        )
        for c in _band_offers()
    ]
    try:
        ranking = rank(
            offers,
            dimensions=dims,
            revision=REV,
            weights=weights,
            at="t",
            currency=currency,
        )
    except RankingError as exc:
        return ("raised", type(exc).__name__)
    return ("ranked", ranking["currency"], ranking["pareto"])


@pytest.mark.parametrize("fit", [None, _FIT_EUR], ids=["no-fit", "fit-eur"])
@pytest.mark.parametrize("currency", [None, "EUR", "USD"])
def test_t138_behaves_exactly_as_without_statements_whatever_is_stated(
    fit: dict[str, Any] | None, currency: str | None
) -> None:
    base = {} if fit is None else fit
    bare = _outcome({**base} if fit else None, currency)
    for count in range(len(_STATEMENTS) + 1):
        for chosen in permutations(_STATEMENTS, count):
            weights = {**base, **stated_part_worths(list(chosen), base)}
            try:
                got = _outcome(weights, currency)
            except Exception as exc:  # a stated price must not add a new failure
                pytest.fail(f"{chosen!r} @ {currency!r}: {exc!r}")
            # A fit-in-USD request against EUR weights raises on main too; what must
            # hold is that the *statements* change neither the currency nor the verdict.
            assert got[:2] == bare[:2], (chosen, currency, got, bare)


def test_a_usd_statement_with_currency_eur_does_not_raise_and_is_skipped() -> None:
    weights = {**stated_part_worths([_stated("x", cur="USD")], {})}
    offer = Candidate(offer_id="o", salary_per_month=1.0, scores={"x": 0.5})
    ranking = rank(
        [offer],
        dimensions=["x"],
        revision=REV,
        weights=weights,
        at="t",
        currency="EUR",
        traits=_traits(x=1),
    )
    assert ranking["level"] == "L1" and ranking["currency"] == "EUR"
    assert ranking["priced_by"] == {"fitted": [], "stated": []}
    assert ranking["unpriced_trait_dimensions"]["reasons"] == {"x": UNPRICED_CURRENCY}


def test_with_no_fit_and_no_currency_nothing_stated_is_adopted() -> None:
    weights = {**stated_part_worths([_stated("x", cur="USD")], {})}
    resolved = weights_for_currency(weights, None)
    assert resolved is not None and "currency" not in resolved
    assert resolved["stated_part_worths"] == {} and resolved["stated_skipped"] == {"x": "currency"}
    offer = Candidate(offer_id="o", salary_per_month=1.0, scores={})
    ranking = rank([offer], dimensions=[], revision=REV, weights=weights, at="t")
    assert ranking["currency"] is None and ranking["level"] == "L1"


@pytest.mark.parametrize("currency", [None, "EUR", "USD"])
def test_statement_order_never_changes_which_dimensions_are_priced(currency: str | None) -> None:
    """Every ordering of a small set, not one hand-picked pair."""
    seen: set[tuple[str, ...]] = set()
    for chosen in permutations(_STATEMENTS):
        weights = {**stated_part_worths(list(chosen), {})}
        resolved = weights_for_currency(weights, currency)
        seen.add(tuple(sorted(priced_dimensions(resolved))))
    assert len(seen) == 1
    expected = {"EUR": ("y", "z"), "USD": ("x",), None: ()}[currency]
    assert seen == {expected}


# -- B3: the card says which figures were stated -----------------------------


def test_a_stated_driver_is_marked_stated_and_a_fitted_one_is_not() -> None:
    from integral.explain import drivers_for
    from integral.presentation import _phrase

    weights = {
        "currency": "EUR",
        "part_worths": {"f": {"salary_equivalent_per_month": 200.0}},
        "stated_part_worths": {"s": {"salary_equivalent_per_month": -800.0, "currency": "EUR"}},
    }
    offer = Candidate(
        offer_id="o",
        salary_per_month=1.0,
        scores={"f": 1.0, "s": 1.0},
        spans={"f": ("fitted words",), "s": ("stated words",)},
    )
    drivers = {d["dimension"]: d for d in drivers_for(offer, weights)}
    assert drivers["s"]["source"] == "stated" and drivers["f"]["source"] == "fitted"
    stated_line, fitted_line = _phrase(drivers["s"], "en"), _phrase(drivers["f"], "en")
    assert "stated: -800 EUR/mo" in stated_line
    assert "stated" not in fitted_line


# -- O1: only a real dimension can be priced ---------------------------------


def test_a_stated_price_on_an_id_outside_the_ontology_is_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(StatedPricingError):
        record_stated_price(
            store,
            dimension="spoken_english",
            direction="less",
            strength="strong",
            currency="EUR",
            text="said",
            at="t",
        )
    assert not EvidenceLog(store).exists()


def test_every_scenario_dimension_is_a_real_ontology_id() -> None:
    from integral.stated_pricing import ontology_ids

    assert set(SCENARIO_DIMENSIONS) <= ontology_ids()
