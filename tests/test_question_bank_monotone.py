"""T96 — an elicitation item whose dimension is monotone has no coherent answer.

    7 is weird. Given the same job, always better more money.

The candidate is right and the question was wrong. Holding everything else
equal, more pay is never worse, so a mid-scale answer is not a preference — it
is somebody being cooperative with a malformed question, and `weights.py` then
fits a part-worth to noise.

What *is* elicitable on a monotone quantity is the **trade-off**: how much of
something else this pay is worth. That is what a part-worth means, and it is
what step 6's forced pairwise choice already asks. So the repair belongs to the
question bank rather than to the fitter — a dimension declared monotone may not
produce a level-rating item at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from integral import question_bank as qb
from integral.dimensions import (
    Dimension,
    Elicitation,
    Extraction,
    LocalisedText,
    Question,
    load_dimensions,
    synthetic_levels,
)


def _dimension(dimension_id: str, *, monotone: bool, form: str) -> Dimension:
    return Dimension(
        id=dimension_id,
        kind="soft",
        polarity="unipolar",
        group="terms",
        monotone=monotone,
        label=LocalisedText(en=dimension_id, es=dimension_id, ca=dimension_id),
        definition="a synthetic dimension used only to probe the monotone rule",
        levels=synthetic_levels(),
        elicitation=Elicitation(
            questions=[
                Question(
                    id=f"{dimension_id}_q1",
                    form=form,  # type: ignore[arg-type]
                    text=LocalisedText(
                        en="How much is it worth?",
                        es="¿Cuánto vale?",
                        ca="Quant val?",
                    ),
                )
            ]
        ),
        extraction=Extraction(),
        methods_ref="METHODS.md#21-structured-behavioural-elicitation",
    )


def test_a_monotone_dimension_never_yields_a_level_rating_item() -> None:
    """Refused where the dimension is defined, so the malformed item cannot
    reach the bank to be counted later. A gate that only reports the item
    after it was asked has already let the candidate answer it."""
    with pytest.raises(ValidationError, match="monotone"):
        _dimension("more_is_better", monotone=True, form="level_rating")


def test_a_non_monotone_dimension_may_still_be_rated() -> None:
    """The rule is about monotone dimensions and nothing else. Travel and
    on-call have a genuine middle, and asking for one is the right question."""
    assert _dimension("has_a_middle", monotone=False, form="level_rating")


def test_pay_is_declared_monotone() -> None:
    """The concrete case, so the rule has a subject.

    Pay is not a `dimensions/*.yaml` file — it is a currency amount, carried by
    `weights.Package.salary_per_month` — so declaring it needs a register that
    reaches past the dimension model. Without this the rule would be true of
    nothing that was actually asked.
    """
    assert "salary" in qb.MONOTONE_ELICITABLES


def test_a_monotone_dimension_is_elicited_as_a_trade_off() -> None:
    """`weights.py`'s forced pairwise choice is the trade-off route, and every
    monotone quantity must have one — otherwise the rule above deletes the
    question and puts nothing in its place."""
    for elicitable in qb.MONOTONE_ELICITABLES:
        assert qb.trade_off_route(elicitable), elicitable


def test_a_monotone_dimension_must_carry_a_trade_off_question() -> None:
    """The same requirement for a dimension that declares itself monotone:
    forbidding the level rating without requiring the trade-off would leave
    the dimension unelicited and the model quietly poorer."""
    with pytest.raises(ValidationError, match="trade-off"):
        _dimension("more_is_better", monotone=True, form="narrative")


def test_an_answer_to_a_retired_malformed_item_does_not_reach_the_fit() -> None:
    """Old responses must not keep feeding `weights.py`.

    Two ways an answer is stale, and both are the same mistake. It answers a
    `bank_id` the bank no longer carries — the item was retired, which is what
    happens to a malformed one. Or the item is still there and is a level
    rating on a monotone quantity, which should never have been asked and
    whose answer is noise however recently it was given.
    """
    live = qb.Answer(bank_id="has_a_middle:has_a_middle_q1", value=0.5)
    retired = qb.Answer(bank_id="more_is_better:more_is_better_q1", value=0.5)
    bank = qb.build_bank([_dimension("has_a_middle", monotone=False, form="level_rating")])

    kept = qb.answers_for_the_fit([live, retired], bank)

    assert [a.bank_id for a in kept] == ["has_a_middle:has_a_middle_q1"]


def test_a_live_monotone_level_rating_is_dropped_too() -> None:
    """The belt to the braces above: if one ever reaches the bank by a route
    the model validator does not cover, its answer still never reaches a fit."""
    entry = qb.BankEntry(
        bank_id="salary:salary_q1",
        dimension_id="salary",
        question_id="salary_q1",
        order=0,
        form="level_rating",
        text=LocalisedText(en="Rate pay 1-7", es="Puntúa el salario 1-7", ca="Puntua 1-7"),
    )
    bank = qb.QuestionBank(entries=(entry,), dimension_count=1)

    assert qb.answers_for_the_fit([qb.Answer(bank_id="salary:salary_q1", value=7.0)], bank) == ()


def test_the_committed_model_asks_no_monotone_level_rating() -> None:
    measured = qb.measure_monotone(load_dimensions())

    assert measured["monotone_dimensions_asked_as_level_ratings"] == 0
    assert measured["offending_items"] == []
    assert measured["gate_status"] == "measured"


def test_the_gate_counts_the_items_it_checked() -> None:
    """A rule true of nothing is true. The denominator is every bank entry
    put through the check, plus every monotone quantity considered."""
    measured = qb.measure_monotone(load_dimensions())

    assert measured["monotone_dimensions_asked_as_level_ratings_evaluated"] > 0
    assert measured["items_checked"] == measured[
        "monotone_dimensions_asked_as_level_ratings_evaluated"
    ]
    assert measured["monotone_elicitables_checked"] >= 1


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    measured = qb.measure_monotone([], elicitables=frozenset())

    assert measured["monotone_dimensions_asked_as_level_ratings"] == 0
    assert measured["monotone_dimensions_asked_as_level_ratings_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_the_gate_catches_one_that_got_through() -> None:
    """Shown failing, over a bank assembled around the model validator — the
    same belt-and-braces the bank already applies to duplicate ids."""
    entry = qb.BankEntry(
        bank_id="salary:salary_q1",
        dimension_id="salary",
        question_id="salary_q1",
        order=0,
        form="level_rating",
        text=LocalisedText(en="Rate pay 1-7", es="Puntúa el salario 1-7", ca="Puntua 1-7"),
    )
    bank = qb.QuestionBank(entries=(entry,), dimension_count=1)

    measured = qb.measure_monotone([], bank=bank)

    assert measured["monotone_dimensions_asked_as_level_ratings"] == 1
    assert measured["offending_items"] == ["salary:salary_q1"]


def test_the_module_writes_both_records(tmp_path: Path) -> None:
    target = tmp_path / "T7.json"

    assert qb._main(["question_bank", "--write-evidence", str(target)]) == 0
    assert target.is_file()
    assert (tmp_path / "T96.json").is_file()
