"""T10 — forced pairwise choices → part-worths → a salary-equivalent scale.

The test the task payload names, plus the ones that stop its number from
being free. A roundtrip that divides by a number and multiplies it back is
exact in floating point and measures nothing; what makes
`weight_salary_equivalent_roundtrip_error` worth reading is that the trip
goes through the **written artefact**, at the precision the candidate is
shown — the skill's own gotcha, that "the number the candidate is shown has
to be the number the ranking actually uses".
"""

from __future__ import annotations

import dataclasses
import json
import math
import random
from pathlib import Path

import pytest

from integral.weights import (
    DEFAULT_EVIDENCE_PATH,
    NEGLIGIBLE_PER_MONTH,
    RIDGE,
    ROUNDTRIP_THRESHOLD,
    SALARY_SCALE,
    Choice,
    ChoiceSet,
    Package,
    WeightsError,
    as_payload,
    build_weights_payload,
    encode_choice,
    fit,
    measure,
    roundtrip_error,
    write_evidence,
)
from integral.weights import (
    _main as main,
)

# One candidate's true tastes, in utility per unit. Salary is per euro per
# month, so `remote` at 0.90 is worth 0.90 / 0.0015 ≈ €600/month to them.
TRUE = {"remote": 0.90, "commute": 0.30, "mentoring": 0.15}
TRUE_SALARY = 0.0015


def _package(salary: float, **dimensions: float) -> Package:
    return Package(salary_per_month=salary, dimensions=dimensions)


def _synthetic(count: int, *, seed: int = 7) -> ChoiceSet:
    """Choices drawn from the model's own data-generating process.

    Probabilistic rather than perfectly rational: a candidate who always picks
    the higher utility separates the data completely, and a separated logit
    has no finite maximum — the ridge would then be choosing the magnitude,
    not the answers.
    """
    rng = random.Random(seed)
    choices: list[Choice] = []
    for _ in range(count):
        pair = []
        for _ in range(2):
            pair.append(
                _package(
                    round(rng.uniform(2000, 4000), 2),
                    **{name: round(rng.uniform(-1, 1), 3) for name in TRUE},
                )
            )
        a, b = pair
        delta = TRUE_SALARY * (a.salary_per_month - b.salary_per_month) + sum(
            TRUE[name] * (a.dimensions[name] - b.dimensions[name]) for name in TRUE
        )
        probability = 1.0 / (1.0 + pow(2.718281828459045, -delta))
        choices.append(Choice(a=a, b=b, chosen="a" if rng.random() < probability else "b"))
    return ChoiceSet(currency="EUR", choices=tuple(choices))


def _rational(count: int, *, seed: int = 11) -> ChoiceSet:
    """The same design, answered without a single mistake."""
    noisy = _synthetic(count, seed=seed)
    return ChoiceSet(
        currency="EUR",
        choices=tuple(
            Choice(
                a=choice.a,
                b=choice.b,
                chosen="a"
                if TRUE_SALARY * (choice.a.salary_per_month - choice.b.salary_per_month)
                + sum(
                    TRUE[name] * (choice.a.dimensions[name] - choice.b.dimensions[name])
                    for name in TRUE
                )
                > 0
                else "b",
            )
            for choice in noisy.choices
        ),
    )


def test_partworth_to_salary_equivalent_roundtrips() -> None:
    """The named test: to €/month and back, within 1%.

    The trip is not `x / k * k`. It goes out through `as_payload`, which
    writes the euro figure at the precision a candidate is shown, and comes
    back through that written figure — so any coarsening of what is shown
    lands in this number.
    """
    fitted = fit(_synthetic(14))
    payload = as_payload(fitted)
    assert payload["part_worths"], "a fit with no part-worths measures nothing"
    for name, part in payload["part_worths"].items():
        recovered = part["salary_equivalent_per_month"] * payload["salary_utility_per_month"]
        assert abs(recovered - fitted.utility_per_unit[name]) <= 0.01 * abs(
            fitted.utility_per_unit[name]
        ), name
    assert roundtrip_error(fitted, payload) <= ROUNDTRIP_THRESHOLD


def test_the_roundtrip_error_rises_when_the_shown_number_is_coarsened() -> None:
    """The counter-check: the measure must be able to fail.

    Round the euro figure to the nearest fifty and the number the candidate
    reads stops being the number the ranking uses. If this still passed, the
    gate would be certifying arithmetic rather than a design decision.
    """
    fitted = fit(_synthetic(14))
    coarse = as_payload(fitted, quantum=250.0)
    assert roundtrip_error(fitted, coarse) > ROUNDTRIP_THRESHOLD


def _replicated(points: int, repeats: int, *, seed: int = 7) -> ChoiceSet:
    """The same design, answered `repeats` times in the true proportion.

    A single stochastic sample measures sampling noise as much as the
    estimator: a coefficient of 0.15 carries a standard error near 30% at
    four hundred choices, so a tolerance loose enough to pass would also pass
    a fit that was wrong. Replicating each design point in the model's own
    proportion drives that noise out and leaves the estimator itself as the
    only thing the tolerance is about.
    """
    rng = random.Random(seed)
    choices: list[Choice] = []
    for _ in range(points):
        a, b = (
            _package(
                round(rng.uniform(2000, 4000), 2),
                **{name: round(rng.uniform(-1, 1), 3) for name in TRUE},
            )
            for _ in range(2)
        )
        delta = TRUE_SALARY * (a.salary_per_month - b.salary_per_month) + sum(
            TRUE[name] * (a.dimensions[name] - b.dimensions[name]) for name in TRUE
        )
        wins = round(repeats / (1.0 + math.exp(-delta)))
        choices.extend(
            Choice(a=a, b=b, chosen="a" if index < wins else "b") for index in range(repeats)
        )
    return ChoiceSet(currency="EUR", choices=tuple(choices))


def test_the_fit_recovers_a_known_preference() -> None:
    """Without this, a fit returning all zeros would roundtrip perfectly."""
    fitted = fit(_replicated(150, 40))
    equivalents = {
        name: part["salary_equivalent_per_month"]
        for name, part in as_payload(fitted)["part_worths"].items()
    }
    for name, utility in TRUE.items():
        truth = utility / TRUE_SALARY
        assert abs(equivalents[name] - truth) <= 0.05 * truth, (name, equivalents[name], truth)
    assert equivalents["remote"] > equivalents["commute"] > equivalents["mentoring"]


def test_a_choice_set_where_salary_never_varies_has_no_salary_scale() -> None:
    """No money in the trade-off, no salary-equivalent units. Refused, not zeroed."""
    pairs = tuple(
        Choice(
            a=_package(3000, remote=value, commute=-value),
            b=_package(3000, remote=-value, commute=value),
            chosen="a",
        )
        for value in (0.2, 0.4, 0.6, 0.8, 1.0)
    )
    with pytest.raises(WeightsError, match="salary"):
        fit(ChoiceSet(currency="EUR", choices=pairs))


def test_a_fit_that_prefers_less_money_is_refused() -> None:
    """A negative salary utility inverts every explanation it is divided into."""
    pairs = tuple(
        Choice(
            a=_package(2000 + index * 10, remote=0.0),
            b=_package(4000 + index * 10, remote=0.0),
            chosen="a",
        )
        for index in range(8)
    )
    with pytest.raises(WeightsError, match="less money"):
        fit(ChoiceSet(currency="EUR", choices=pairs))


def test_packages_must_carry_the_same_dimensions() -> None:
    """Two packages differing in which dimensions exist is a missing answer, not a level."""
    with pytest.raises(WeightsError, match="same dimensions"):
        fit(
            ChoiceSet(
                currency="EUR",
                choices=(
                    Choice(a=_package(3000, remote=1.0), b=_package(3200, commute=1.0), chosen="a"),
                ),
            )
        )


def test_a_dimension_worth_less_than_a_euro_is_negligible_not_a_part_worth() -> None:
    """Below the resolution of money there is no honest euro figure to show.

    Reported by name rather than dropped: "we could not separate this" and
    "this does not matter to you" are different claims, and the file has to
    keep them apart.
    """
    fitted = fit(_synthetic(14))
    flattened = dataclasses.replace(
        fitted,
        utility_per_unit={
            **fitted.utility_per_unit,
            "mentoring": fitted.salary_utility_per_month * 0.4,
        },
    )
    payload = as_payload(flattened)
    assert "mentoring" in payload["negligible"]
    assert "mentoring" not in payload["part_worths"]
    assert NEGLIGIBLE_PER_MONTH == 1.0


def test_the_fit_is_a_stationary_point_of_the_penalised_likelihood() -> None:
    """The coefficients returned actually maximise the objective claimed.

    The gradient is recomputed here from the definition in the module
    docstring — the difference between the two packages, money in thousands,
    the ridge — and checked against what Newton returned. Two different
    computations agreeing is worth something; the solver checking its own
    convergence flag would not be.
    """
    choices = _synthetic(14)
    fitted = fit(choices)
    beta = [
        fitted.salary_utility_per_month * SALARY_SCALE,
        *(fitted.utility_per_unit[name] for name in sorted(fitted.utility_per_unit)),
    ]
    gradient = [-2.0 * RIDGE * value for value in beta]
    for choice in choices.choices:
        row = [
            (choice.a.salary_per_month - choice.b.salary_per_month) / SALARY_SCALE,
            *(
                choice.a.dimensions[name] - choice.b.dimensions[name]
                for name in sorted(fitted.utility_per_unit)
            ),
        ]
        eta = sum(b * x for b, x in zip(beta, row, strict=True))
        residual = (1.0 if choice.chosen == "a" else 0.0) - 1.0 / (1.0 + math.exp(-eta))
        gradient = [g + residual * x for g, x in zip(gradient, row, strict=True)]
    assert max(abs(value) for value in gradient) < 1e-8, gradient


def test_a_separated_answer_sheet_is_finite_and_says_so() -> None:
    """A candidate who never contradicts themselves has no finite MLE.

    Perfect consistency separates the data: every coefficient can grow without
    bound and the likelihood keeps rising, so an unpenalised fit is decided by
    where the optimiser stopped rather than by the answers. The ridge makes
    the optimum exist — and the fit says `separated`, because what it exists
    at is a magnitude the penalty chose. The euro figures here really are
    wrong: `commute` comes back near €566 against a truth of €200. Nothing
    downstream can be careful about that unless the file admits it.
    """
    fitted = fit(_rational(30))
    equivalents = {name: fitted.salary_equivalent(name) for name in TRUE}
    assert all(math.isfinite(value) for value in equivalents.values()), equivalents
    assert max(abs(value) for value in equivalents.values()) < 10_000
    assert fitted.salary_utility_per_month > 0
    assert fitted.separated is True
    assert as_payload(fitted)["separated"] is True

    assert fit(_synthetic(14)).separated is False


def test_as_many_choices_as_coefficients_is_not_enough_to_identify_them() -> None:
    """The boundary itself, so a rule loosened by one is caught here.

    Asserted on the message rather than on the mere fact of a refusal: with
    four answers and four coefficients the fit can also fall over for its own
    reasons, and a test that accepted any `WeightsError` would pass while the
    identifiability rule was gone.
    """
    choices = _synthetic(14).choices
    with pytest.raises(WeightsError, match="cannot identify"):
        fit(ChoiceSet(currency="EUR", choices=choices[:4]))
    fit(ChoiceSet(currency="EUR", choices=choices[:5]))


def test_a_fit_with_nothing_left_to_measure_raises_rather_than_reporting_zero() -> None:
    """An unmeasurable roundtrip must not read as a clean pass."""
    fitted = fit(_synthetic(14))
    with pytest.raises(WeightsError):
        roundtrip_error(fitted, as_payload(fitted, quantum=1_000_000.0))


def test_weights_are_built_from_the_log_and_a_stray_row_is_skipped() -> None:
    """The wire format is JSON in the row text — T41's encoding, replayed.

    A reaction row that is not a choice (step 5 writes plenty) must be passed
    over, not crash the rebuild: "cannot interpret it, cannot replay it".
    """
    encoded = [encode_choice(choice, currency="EUR") for choice in _synthetic(14).choices]
    payload = build_weights_payload(
        [
            *encoded,
            "loved the tone of this ad",  # step 5's own rows: a sentence
            "{}",  # an object, but not a choice
            "[1, 2]",  # JSON, but not an object
            '{"currency": "EUR", "chosen": "c"}',  # a choice shape it cannot validate
        ]
    )
    assert payload["choices"] == 14
    assert payload["part_worths"]

    assert build_weights_payload(["not a choice"]) == {}


def test_choices_in_two_currencies_are_not_one_fit() -> None:
    """Two scales added together is a number in neither of them."""
    choices = _synthetic(14).choices
    texts = [encode_choice(choice, currency="EUR") for choice in choices[:-1]]
    texts.append(encode_choice(choices[-1], currency="GBP"))
    with pytest.raises(WeightsError, match="currency"):
        build_weights_payload(texts)


def test_main_writes_the_evidence_and_the_probe_plants_its_own_failure(tmp_path: Path) -> None:
    evidence = tmp_path / "T10.json"
    assert main([str(evidence)]) == 0
    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written == measure()
    assert written["weight_salary_equivalent_roundtrip_error"] <= ROUNDTRIP_THRESHOLD
    assert written["roundtrip_error_detected_when_coarsened"] == 1
    assert DEFAULT_EVIDENCE_PATH.name == "T10.json"

    assert write_evidence(tmp_path / "nested" / "T10.json") == written
