"""T10 — forced pairwise choices → part-worths → a salary-equivalent scale.

Preference weights come from choices between whole packages, never from
sliders or "rate autonomy out of ten" (`docs/METHODS.md` §2.3): the first
measures what someone would take, the second what they believe about
themselves. Each choice is one observation in a binary logit over the
*difference* between the two packages, which is the conditional logit for
pairs; the fitted coefficient on money turns every other coefficient into
€/month (§4.2), and that is the only reason the trade-offs are explainable.

Three decisions are worth stating, because each is the sort of thing a later
reader would otherwise assume was an oversight.

**Part-worths are linear in a dimension's score, not one per named level.**
`docs/METHODS.md` §4.2 speaks of a part-worth per level, and `dimensions.py`
gives every dimension two to five named rungs. Estimating a free coefficient
per rung is seven dimensions * three rungs ≈ fourteen parameters, against a
stop rule that caps the conversation at twenty choices — unidentifiable, and
`step-06-preferences` asks for "enough choices for the part-worths to be
identifiable". Linear-in-score is one parameter per dimension, and it is not
a lesser model than the ranker wants: §4.3's total is
`salary + Σ_d weight(d) * score(d)`, which is linear in score already. The
part-worth of a level is then `utility_per_unit * level.value`.
`# ponytail: per-level coefficients need more choices than the cap allows.`

**The fit is ridge-penalised.** A candidate who always picks the better
package separates the data, and a separated logit has no finite maximum
likelihood — the coefficients run to infinity and the salary ratio is decided
by where the optimiser was stopped. A small ridge makes the optimum finite
and unique, so the same answers always give the same number.

**What is written is what the candidate was shown.** `as_payload` rounds each
salary-equivalent to the cent, and that rounded figure is what
`roundtrip_error` reads back. So the gate,
`weight_salary_equivalent_roundtrip_error <= 0.01`, measures a design
decision rather than arithmetic: coarsen the shown figure and the number
rises, which is what `roundtrip_error_detected_when_coarsened` demonstrates
on every run. A dimension whose euro figure would round to less than
`NEGLIGIBLE_PER_MONTH` has no honest figure to show and is named in
`negligible` instead — "we could not separate this" and "this does not matter
to you" are different claims (§4.1), and collapsing them is how a file starts
lying quietly.

This module imports nothing from `integral`. `profile.py` is imported by
nearly every other module and depends on none of them; `_build_weights` calls
in here, so the traffic has to run one way only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# §4.2's site: part-worths from forced choices, rescaled by the money coefficient.
METHODS_REF = "METHODS.md#42-preference-weights--part-worth-utilities"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T10.json"

#: The step's own stop rule (`step-06-preferences`). Not enforced by `fit`:
#: how long a conversation runs is the step's business, and a rule about
#: talking has no place inside an estimator.
MAX_CHOICES = 20

#: Ridge strength on the scaled features — enough to make a separated fit
#: finite, weak enough that it does not move an identified one.
RIDGE = 1e-3

#: Money enters the design matrix in thousands, so its column sits on the
#: same order as the -1..1 dimension columns and Newton conditions well.
SALARY_SCALE = 1000.0

#: What the candidate is shown, and therefore what the ranking must use.
EQUIVALENT_QUANTUM = 0.01

#: Below one unit of currency a month there is no figure worth quoting.
NEGLIGIBLE_PER_MONTH = 1.0

#: The task's threshold, kept here so the gate and the tests read one number.
ROUNDTRIP_THRESHOLD = 0.01

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_DIMENSION_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class WeightsError(Exception):
    """The choices do not support a salary-equivalent scale."""


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Package(Strict):
    """One side of a forced choice — a whole alternative, priced.

    `dimensions` carries the same -1..1 scale the ontology's levels are
    defined on (`dimensions.Level`), so a package is describable by clicking
    named rungs rather than by typing floats.
    """

    salary_per_month: float = Field(gt=0)
    dimensions: Mapping[str, float]

    @model_validator(mode="after")
    def _dimensions_are_named_and_in_range(self) -> Package:
        if not self.dimensions:
            raise ValueError("a package with no dimensions is a salary, not a choice")
        for name, value in self.dimensions.items():
            if not _DIMENSION_ID.match(name):
                raise ValueError(f"{name!r} is not a dimension id")
            if not -1.0 <= value <= 1.0:
                raise ValueError(f"{name}={value} is off the -1..1 dimension scale")
        return self


class Choice(Strict):
    """One forced pairwise choice, and which side won it."""

    a: Package
    b: Package
    chosen: Literal["a", "b"]


class ChoiceSet(Strict):
    """Every choice one candidate made, on one currency."""

    currency: str = Field(pattern=_CURRENCY.pattern)
    choices: tuple[Choice, ...] = Field(min_length=1)


@dataclass(frozen=True)
class Fit:
    """The estimated part-worths, before anything is rounded for display."""

    currency: str
    choices: int
    #: Utility per one unit of currency per month — the divisor that turns
    #: every other coefficient into money.
    salary_utility_per_month: float
    #: Utility per one unit of a dimension's -1..1 score.
    utility_per_unit: Mapping[str, float]
    #: True when no answer contradicts the fit — the candidate was perfectly
    #: consistent. Reported rather than refused: consistency is what a good
    #: respondent looks like, and telling one their answers were too tidy
    #: would be absurd. But separated data has no finite maximum likelihood,
    #: so the ridge, not the answers, is deciding how large the coefficients
    #: are. The *ordering* of the dimensions still means something; the euro
    #: figures are an upper bound on confidence, and whatever reads
    #: `weights.json` needs to be able to see that.
    separated: bool = False

    def salary_equivalent(self, dimension: str) -> float:
        """What one unit of `dimension` is worth per month, unrounded."""
        return self.utility_per_unit[dimension] / self.salary_utility_per_month


def fit(choices: ChoiceSet) -> Fit:
    """Estimate part-worths from the choices, in salary-equivalent terms."""
    names = _shared_dimensions(choices)
    rows: list[list[float]] = []
    outcomes: list[float] = []
    for choice in choices.choices:
        difference = [
            (choice.a.salary_per_month - choice.b.salary_per_month) / SALARY_SCALE,
            *(choice.a.dimensions[name] - choice.b.dimensions[name] for name in names),
        ]
        rows.append(difference)
        outcomes.append(1.0 if choice.chosen == "a" else 0.0)

    if all(abs(row[0]) < 1e-9 for row in rows):
        raise WeightsError(
            "no choice traded salary against anything, so there is no salary scale to "
            "express the other dimensions in"
        )
    if len(rows) <= len(names) + 1:
        raise WeightsError(
            f"{len(rows)} choice(s) cannot identify {len(names) + 1} coefficients — "
            "ask for more before fitting"
        )
    flat = [
        name
        for index, name in enumerate(names, start=1)
        if all(abs(row[index]) < 1e-9 for row in rows)
    ]
    if flat:
        raise WeightsError(
            f"{flat} took the same value in every package, so no answer says anything "
            "about them — offer a pair that moves them"
        )
    pivots = _pivot_columns(rows)
    if len(pivots) < len(rows[0]):
        features = ("salary", *names)
        dependent = [features[index] for index in range(len(features)) if index not in pivots]
        raise WeightsError(
            f"the choices never separate {dependent} from what they moved with — every "
            "pair varied them together, so splitting the effect between them would be "
            "the penalty's guess rather than an answer. Ask a pair that moves one "
            "without the other"
        )

    beta = _logit(rows, outcomes)
    salary_per_month = beta[0] / SALARY_SCALE
    if salary_per_month <= 0:
        raise WeightsError(
            "the fit says this candidate prefers less money, which is not a scale "
            "anything can be divided by — check the choices before trusting them"
        )
    return Fit(
        currency=choices.currency,
        choices=len(rows),
        salary_utility_per_month=salary_per_month,
        utility_per_unit=dict(zip(names, beta[1:], strict=True)),
        separated=_separates(rows, outcomes, beta),
    )


def _separates(
    rows: Sequence[Sequence[float]], outcomes: Sequence[float], beta: Sequence[float]
) -> bool:
    """Whether the fitted direction predicts every answer without exception."""
    return all(
        (sum(b * x for b, x in zip(beta, row, strict=True)) > 0) == (outcome > 0.5)
        for row, outcome in zip(rows, outcomes, strict=True)
    )


def _shared_dimensions(choices: ChoiceSet) -> tuple[str, ...]:
    names: tuple[str, ...] | None = None
    for choice in choices.choices:
        for package in (choice.a, choice.b):
            here = tuple(sorted(package.dimensions))
            if names is None:
                names = here
            elif here != names:
                raise WeightsError(
                    "every package must describe the same dimensions — "
                    f"{list(names)} then {list(here)}"
                )
    assert names is not None  # ChoiceSet requires at least one choice
    return names


def _logit(rows: Sequence[Sequence[float]], outcomes: Sequence[float]) -> list[float]:
    """Ridge-penalised binary logit through the origin, by Newton's method.

    No intercept: the observation is a *difference* between two packages, and
    a constant would say the candidate favours whichever one was printed on
    the left. Concave plus ridge means one maximum, reached from zero in a
    handful of steps, so the answer does not depend on where we started.
    """
    width = len(rows[0])
    beta = [0.0] * width
    for _ in range(64):
        gradient = [-2.0 * RIDGE * value for value in beta]
        hessian = [[2.0 * RIDGE if i == j else 0.0 for j in range(width)] for i in range(width)]
        for row, outcome in zip(rows, outcomes, strict=True):
            eta = sum(b * x for b, x in zip(beta, row, strict=True))
            mu = 1.0 / (1.0 + math.exp(-max(-500.0, min(500.0, eta))))
            weight = mu * (1.0 - mu)
            for i in range(width):
                gradient[i] += (outcome - mu) * row[i]
                for j in range(width):
                    hessian[i][j] += weight * row[i] * row[j]
        step = _solve(hessian, gradient)
        beta = [b + s for b, s in zip(beta, step, strict=True)]
        if max(abs(s) for s in step) < 1e-12:
            break
    return beta


def _pivot_columns(rows: Sequence[Sequence[float]]) -> frozenset[int]:
    """Which columns of the design matrix are linearly independent.

    The ridge makes the Hessian invertible whatever the answers were, so a
    rank-deficient design does not fail loudly — it fits, and hands back a
    split between the dependent columns that the penalty chose. Two
    dimensions that moved together in every pair then get separate euro
    figures, each of which is an artefact. This is checked on the design
    itself, before the penalty is anywhere near it.
    """
    matrix = [list(row) for row in rows]
    width = len(matrix[0])
    largest = max((abs(value) for row in matrix for value in row), default=0.0)
    tolerance = 1e-9 * max(largest, 1.0)
    pivots: list[int] = []
    row_index = 0
    for column in range(width):
        if row_index >= len(matrix):
            break
        pivot = max(range(row_index, len(matrix)), key=lambda r: abs(matrix[r][column]))
        if abs(matrix[pivot][column]) <= tolerance:
            continue
        matrix[row_index], matrix[pivot] = matrix[pivot], matrix[row_index]
        for below in range(row_index + 1, len(matrix)):
            factor = matrix[below][column] / matrix[row_index][column]
            for col in range(column, width):
                matrix[below][col] -= factor * matrix[row_index][col]
        pivots.append(column)
        row_index += 1
    return frozenset(pivots)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """`matrix @ x = vector`, by Gaussian elimination with partial pivoting."""
    size = len(vector)
    augmented = [[*row, value] for row, value in zip(matrix, vector, strict=True)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot][column]) < 1e-15:
            # Unreachable while the ridge is positive: `2 * RIDGE * I` alone
            # makes this matrix positive definite, and `_pivot_columns` has
            # already refused the design this used to claim to catch. Kept as a
            # numerical backstop with an honest message rather than one naming
            # a cause it can no longer be the detector of.
            raise WeightsError(
                "the Newton step is singular — the fit cannot be solved at these coefficients"
            )
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column] / augmented[column][column]
            for col in range(column, size + 1):
                augmented[row][col] -= factor * augmented[column][col]
    return [augmented[i][size] / augmented[i][i] for i in range(size)]


def as_payload(fitted: Fit, *, quantum: float = EQUIVALENT_QUANTUM) -> dict[str, Any]:
    """The `profile/weights.json` body — the euro figures as they are shown.

    `quantum` is the display resolution. It is a parameter so the probe can
    coarsen it and watch the roundtrip error rise; nothing in the product
    passes anything but the default.
    """
    part_worths: dict[str, dict[str, float]] = {}
    negligible: list[str] = []
    for name in sorted(fitted.utility_per_unit):
        shown = round(fitted.salary_equivalent(name) / quantum) * quantum
        if abs(shown) < NEGLIGIBLE_PER_MONTH:
            negligible.append(name)
            continue
        part_worths[name] = {
            "utility_per_unit": fitted.utility_per_unit[name],
            "salary_equivalent_per_month": shown,
        }
    return {
        "currency": fitted.currency,
        "choices": fitted.choices,
        "salary_utility_per_month": fitted.salary_utility_per_month,
        "part_worths": part_worths,
        "negligible": negligible,
        "separated": fitted.separated,
    }


def roundtrip_error(fitted: Fit, payload: Mapping[str, Any]) -> float:
    """Largest relative loss from converting to money and back.

    The trip goes through the payload's own figures, so the answer is about
    what was written, not about float division.
    """
    part_worths: Mapping[str, Mapping[str, float]] = payload["part_worths"]
    if not part_worths:
        raise WeightsError(
            "no part-worth survived to be measured — an unmeasurable roundtrip is not a clean one"
        )
    per_month = float(payload["salary_utility_per_month"])
    worst = 0.0
    for name, part in part_worths.items():
        recovered = part["salary_equivalent_per_month"] * per_month
        truth = fitted.utility_per_unit[name]
        worst = max(worst, abs(recovered - truth) / abs(truth))
    return worst


def encode_choice(choice: Choice, *, currency: str) -> str:
    """One choice as the text of an evidence row.

    JSON in `text` is T41's encoding for a structured capture, replayed here
    rather than reinvented — and it is why `EvidenceRow` needs no new field
    for step 6.
    """
    if not _CURRENCY.match(currency):
        raise WeightsError(f"{currency!r} is not a three-letter currency code")
    return json.dumps(
        {"currency": currency, **choice.model_dump(mode="json")},
        ensure_ascii=False,
        sort_keys=True,
    )


def decode_choice(text: str) -> tuple[str, Choice] | None:
    """`(currency, choice)`, or `None` for a row that is not a choice.

    Defensive on purpose: step 5 writes plenty of reaction rows whose text is
    a sentence, and a rebuild that crashed on one would make every later
    derived file hostage to a stray row. Cannot interpret it, cannot replay
    it.
    """
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    currency = payload.pop("currency", None)
    if not isinstance(currency, str) or not _CURRENCY.match(currency):
        return None
    try:
        return currency, Choice.model_validate(payload)
    except ValidationError:
        return None


def build_weights_payload(texts: Iterable[str]) -> dict[str, Any]:
    """`profile/weights.json`'s fitted body, from evidence-row texts.

    Takes strings rather than `EvidenceRow`s so this module stays free of
    `integral.profile`, which imports it. An empty result means "no choices
    recorded yet", which is a different thing from a fit that failed — the
    latter raises.
    """
    decoded = [found for found in (decode_choice(text) for text in texts) if found is not None]
    if not decoded:
        return {}
    currencies = {currency for currency, _ in decoded}
    if len(currencies) > 1:
        raise WeightsError(
            f"choices were recorded in more than one currency ({sorted(currencies)}) — "
            "two scales added together is a number in neither of them"
        )
    return as_payload(
        fit(ChoiceSet(currency=currencies.pop(), choices=tuple(choice for _, choice in decoded)))
    )


# One candidate's answers, fixed so the evidence is the same on any machine.
# Written out rather than generated: a probe whose stimulus is drawn at
# measurement time can be re-rolled until the number flatters the gate.
_FIXTURE: tuple[tuple[float, float, float, float, float, float, float, str], ...] = (
    (3200, 0.8, -0.6, 0.2, 3600, -0.4, 0.6, "a"),
    (2800, 1.0, 0.0, -0.4, 3400, -0.2, -0.8, "a"),
    (3000, -0.6, 0.4, 0.6, 3100, 0.8, -0.2, "b"),
    (3500, 0.2, -1.0, 0.0, 3300, -0.8, 0.4, "a"),
    (2600, 0.6, 0.8, -0.6, 3900, 0.4, 0.2, "b"),
    (3400, -1.0, -0.2, 0.8, 3200, 0.6, 0.6, "b"),
    (2900, 0.4, 0.6, -0.2, 3050, -0.6, -0.4, "a"),
    (3700, -0.2, 0.2, 0.4, 3150, 1.0, 0.0, "b"),
    (3100, 0.8, -0.4, -0.8, 3450, 0.0, 0.8, "b"),
    (2750, 1.0, 0.6, 0.2, 3250, 0.2, -0.6, "a"),
    (3300, -0.4, -0.8, 0.6, 2950, 0.8, 0.4, "a"),
    (3050, 0.6, 0.0, -0.4, 3600, -1.0, 0.2, "a"),
    (3600, 0.0, 0.4, 0.8, 3000, 0.4, -0.8, "a"),
    (2850, 0.8, -0.6, 0.0, 3350, -0.6, 0.6, "b"),
)

#: Coarse enough that the shown figure stops being the used one — the
#: mutation the probe plants so the gate's number can be seen to fail.
COARSE_QUANTUM = 250.0


def _fixture_choices() -> ChoiceSet:
    return ChoiceSet(
        currency="EUR",
        choices=tuple(
            Choice(
                a=Package(
                    salary_per_month=a_salary,
                    dimensions={"remote": a_remote, "commute": a_commute, "mentoring": a_mentor},
                ),
                b=Package(
                    salary_per_month=b_salary,
                    dimensions={"remote": b_remote, "commute": b_commute, "mentoring": -a_mentor},
                ),
                chosen=chosen,  # type: ignore[arg-type]
            )
            for (
                a_salary,
                a_remote,
                a_commute,
                a_mentor,
                b_salary,
                b_remote,
                b_commute,
                chosen,
            ) in _FIXTURE
        ),
    )


def measure() -> dict[str, Any]:
    """The gate's numbers: the roundtrip error, and proof it can rise."""
    fitted = fit(_fixture_choices())
    payload = as_payload(fitted)
    error = roundtrip_error(fitted, payload)

    coarse = as_payload(fitted, quantum=COARSE_QUANTUM)
    coarsened = roundtrip_error(fitted, coarse)

    refusals: list[str] = []
    for label, attempt in (
        ("salary_never_varied", _no_salary_variation),
        ("prefers_less_money", _prefers_less_money),
        ("dimensions_disagree", _dimensions_disagree),
        ("too_few_choices_for_the_coefficients", _too_few_choices),
        ("dimensions_never_moved_apart", _collinear_dimensions),
        ("two_currencies_in_one_fit", _two_currencies),
        ("nothing_left_to_measure", _nothing_to_measure),
    ):
        try:
            attempt()
        except WeightsError:
            refusals.append(label)
        else:  # pragma: no cover - a silent acceptance is the failure
            raise AssertionError(f"{label} was accepted")

    return {
        "weight_salary_equivalent_roundtrip_error": round(error, 6),
        # A separated answer sheet roundtrips just as tightly while its euro
        # figures mean nothing, so the gate's number is only readable
        # alongside this one.
        "fixture_separated": int(fitted.separated),
        "roundtrip_error_detected_when_coarsened": int(coarsened > ROUNDTRIP_THRESHOLD),
        "choices_fitted": fitted.choices,
        "dimensions_priced": len(payload["part_worths"]),
        "refusals": sorted(refusals),
    }


def _no_salary_variation() -> None:
    fit(
        ChoiceSet(
            currency="EUR",
            choices=tuple(
                Choice(
                    a=Package(salary_per_month=3000, dimensions={"remote": value}),
                    b=Package(salary_per_month=3000, dimensions={"remote": -value}),
                    chosen="a",
                )
                for value in (0.2, 0.4, 0.6, 0.8, 1.0)
            ),
        )
    )


def _prefers_less_money() -> None:
    fit(
        ChoiceSet(
            currency="EUR",
            choices=tuple(
                Choice(
                    a=Package(
                        salary_per_month=2000 + index * 10,
                        dimensions={"remote": 0.5 if index % 2 else -0.5},
                    ),
                    b=Package(
                        salary_per_month=4000 + index * 10,
                        dimensions={"remote": -0.5 if index % 2 else 0.5},
                    ),
                    chosen="a",
                )
                for index in range(8)
            ),
        )
    )


def _dimensions_disagree() -> None:
    fit(
        ChoiceSet(
            currency="EUR",
            choices=(
                Choice(
                    a=Package(salary_per_month=3000, dimensions={"remote": 1.0}),
                    b=Package(salary_per_month=3200, dimensions={"commute": 1.0}),
                    chosen="a",
                ),
            ),
        )
    )


def _too_few_choices() -> None:
    # Exactly as many choices as coefficients — the boundary, not a number
    # comfortably inside it, so a rule loosened by one is a rule that fails here.
    fit(ChoiceSet(currency="EUR", choices=_fixture_choices().choices[:4]))


def _collinear_dimensions() -> None:
    fit(
        ChoiceSet(
            currency="EUR",
            choices=tuple(
                Choice(
                    a=Package(
                        salary_per_month=choice.a.salary_per_month,
                        dimensions={
                            **choice.a.dimensions,
                            "commute": choice.a.dimensions["remote"],
                        },
                    ),
                    b=Package(
                        salary_per_month=choice.b.salary_per_month,
                        dimensions={
                            **choice.b.dimensions,
                            "commute": choice.b.dimensions["remote"],
                        },
                    ),
                    chosen=choice.chosen,
                )
                for choice in _fixture_choices().choices
            ),
        )
    )


def _two_currencies() -> None:
    choices = _fixture_choices().choices
    build_weights_payload(
        [
            *(encode_choice(choice, currency="EUR") for choice in choices[:-1]),
            encode_choice(choices[-1], currency="GBP"),
        ]
    )


def _nothing_to_measure() -> None:
    fitted = fit(_fixture_choices())
    roundtrip_error(fitted, as_payload(fitted, quantum=1_000_000.0))


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Measure T10's salary-equivalent roundtrip.")
    parser.add_argument("evidence", nargs="?", default=str(DEFAULT_EVIDENCE_PATH), type=Path)
    args = parser.parse_args(argv)
    measured = write_evidence(args.evidence)
    error = measured["weight_salary_equivalent_roundtrip_error"]
    print(f"weight_salary_equivalent_roundtrip_error: {error} (<= {ROUNDTRIP_THRESHOLD})")
    coarsened = measured["roundtrip_error_detected_when_coarsened"]
    print(f"roundtrip_error_detected_when_coarsened: {coarsened}")
    if error > ROUNDTRIP_THRESHOLD:
        return 1
    if not coarsened:
        # A roundtrip that cannot be made to fail is not measuring the design
        # decision it exists for — see the module docstring.
        print(
            "the roundtrip measure did not rise when the shown figure was coarsened",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv[1:]))
