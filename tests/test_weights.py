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
import random
from pathlib import Path

import pytest

from integral.weights import (
    NEGLIGIBLE_PER_MONTH,
    ROUNDTRIP_THRESHOLD,
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
    choices = []
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


def test_the_fit_recovers_a_known_preference() -> None:
    """Without this, a fit returning all zeros would roundtrip perfectly."""
    fitted = fit(_synthetic(400))
    equivalents = {
        name: part["salary_equivalent_per_month"]
        for name, part in as_payload(fitted)["part_worths"].items()
    }
    for name, utility in TRUE.items():
        truth = utility / TRUE_SALARY
        assert abs(equivalents[name] - truth) <= 0.35 * truth, (name, equivalents[name], truth)
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
    with pytest.raises(WeightsError, match="more money"):
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
    payload = build_weights_payload([*encoded, "loved the tone of this ad", "{}", "[1, 2]"])
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
    assert main(["weights", str(evidence)]) == 0
    written = json.loads(evidence.read_text(encoding="utf-8"))
    assert written == measure()
    assert written["weight_salary_equivalent_roundtrip_error"] <= ROUNDTRIP_THRESHOLD
    assert written["roundtrip_error_detected_when_coarsened"] == 1
    assert main([]) == 2

    assert write_evidence(tmp_path / "nested" / "T10.json") == written
