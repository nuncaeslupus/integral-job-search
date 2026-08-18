"""T30 — the declared step graph, and required-subset closure.

The gate is `required_subset_closure_violations == 0`, and it exists because
§2.5's promise — any offered step may be declined without blocking — is only
true if the required steps can run on required outputs alone. The defect it
guards against is not hypothetical: PR #16 shipped the graph and broke this in
the same diff, with required Constraints reading an artefact only the *offered*
Intake step produces.

Two things are checked, and they fail for different reasons: the closure
itself, and whether the JSON still says what §3.1 says. A gate over a graph
nobody documented is as useless as a document nobody checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.process_spec import DEFAULT_PROCESS_DOC, StepList, load_steps
from jobsearch.step_graph import (
    StepGraphError,
    closure_violations,
    drift_violations,
    measure,
    parse_prose_graph,
    unproduced_inputs,
    write_evidence,
)


@pytest.fixture
def steps() -> StepList:
    return load_steps()


def _rewritten(steps: StepList, **changes: object) -> StepList:
    """A copy of the settled graph with one step's declarations changed."""
    payload = json.loads(steps.model_dump_json())
    for step_id, reads in changes.items():
        for step in payload["steps"]:
            if step["id"] == step_id:
                step["reads"] = reads
    return StepList.model_validate(payload)


# --- the settled graph -----------------------------------------------------


def test_the_settled_graph_is_closed_over_its_required_steps(steps: StepList) -> None:
    assert closure_violations(steps) == []
    assert unproduced_inputs(steps) == []


def test_the_required_steps_are_the_five_the_owner_settled(steps: StepList) -> None:
    """A decision, pinned by a test — not a constant the validator carries.

    The validator reads which steps are required from the JSON, so a change of
    mind does not make it fail; this test is what makes the change deliberate.
    """
    assert [step.id for step in steps.steps if step.required] == [
        "identify",
        "constraints",
        "sourcing",
        "understanding",
        "ranking",
    ]


def test_every_step_declares_something_to_read_or_produce(steps: StepList) -> None:
    """A graph of empty declarations satisfies closure over nothing."""
    assert sum(len(step.reads) for step in steps.steps) > 0
    assert all(step.produces for step in steps.steps)


# --- closure ---------------------------------------------------------------


def test_a_required_step_reading_an_offered_steps_output_is_rejected(steps: StepList) -> None:
    """The PR #16 defect, as a fixture.

    Constraints is required; Intake, which produces `claimed_facts`, is not. A
    candidate with no CV — the person §2.5 exists to serve — would reach a
    required step with a missing input.
    """
    broken = _rewritten(steps, constraints=[{"artefact": "claimed_facts", "optional": False}])
    violations = closure_violations(broken)
    assert len(violations) == 1
    assert "claimed_facts" in violations[0]
    assert "intake" in violations[0]


def test_an_optional_input_does_not_break_closure(steps: StepList) -> None:
    """The `claimed facts?` case must pass — it is the same edge, marked."""
    fine = _rewritten(steps, constraints=[{"artefact": "claimed_facts", "optional": True}])
    assert closure_violations(fine) == []


def test_a_required_step_reading_an_artefact_nobody_produces_is_rejected(
    steps: StepList,
) -> None:
    broken = _rewritten(steps, ranking=[{"artefact": "astrology", "optional": False}])
    assert any("astrology" in violation for violation in closure_violations(broken))
    assert any("astrology" in violation for violation in unproduced_inputs(broken))


def test_an_offered_step_reading_an_unproduced_artefact_is_still_reported(
    steps: StepList,
) -> None:
    """Not a broken promise, but dead code in the graph — and still silent."""
    broken = _rewritten(steps, history=[{"artefact": "astrology", "optional": False}])
    assert closure_violations(broken) == []
    assert any("astrology" in violation for violation in unproduced_inputs(broken))


def test_an_external_artefact_satisfies_a_required_step(steps: StepList) -> None:
    """Understanding reads the dimension model, which no step produces."""
    assert "dimension_model" in steps.external_artefacts
    understanding = next(step for step in steps.steps if step.id == "understanding")
    assert any(read.artefact == "dimension_model" for read in understanding.reads)
    assert closure_violations(steps) == []


def test_a_graph_with_no_required_step_is_a_violation_not_a_pass(steps: StepList) -> None:
    """`collect_violations` used to assert only that *some* step is required.

    That is too weak to mean anything, and its mirror image — none required —
    would otherwise close vacuously over an empty set.
    """
    payload = json.loads(steps.model_dump_json())
    for step in payload["steps"]:
        step["required"] = False
    assert closure_violations(StepList.model_validate(payload)) != []


# --- drift against the prose ----------------------------------------------


def test_the_prose_graph_and_the_json_agree(steps: StepList) -> None:
    assert drift_violations(steps) == []


def test_a_read_dropped_from_the_json_is_drift(steps: StepList) -> None:
    """A JSON saying less than §3.1 leaves an input unchecked."""
    thinner = _rewritten(steps, ranking=[{"artefact": "extractions", "optional": False}])
    assert any("ranking" in violation for violation in drift_violations(thinner))


def test_an_optionality_flip_is_drift(steps: StepList) -> None:
    """The `?` is the whole content of §2.5's guarantee; losing it is silent."""
    flipped = _rewritten(steps, constraints=[{"artefact": "claimed_facts", "optional": False}])
    assert any("constraints" in violation for violation in drift_violations(flipped))


def test_the_prose_graph_parses_to_every_step(steps: StepList) -> None:
    prose = parse_prose_graph(DEFAULT_PROCESS_DOC.read_text(encoding="utf-8"))
    assert set(prose) == {step.n for step in steps.steps}
    assert prose[0][1] == [], "step 0 reads nothing, written as an em dash"
    assert ("weights.json", True) in prose[9][1], "the ? on weights survives the parse"


def test_a_label_with_no_alias_is_reported_rather_than_ignored(steps: StepList) -> None:
    """An unmapped label would otherwise compare as absent and read as agreement."""
    payload = json.loads(steps.model_dump_json())
    payload["artefact_aliases"].pop("a ranking")
    violations = drift_violations(StepList.model_validate(payload))
    assert any("a ranking" in violation for violation in violations)


def test_a_missing_graph_block_is_reported_not_silently_clean(
    steps: StepList, tmp_path: Path
) -> None:
    empty = tmp_path / "spec.md"
    empty.write_text("# no graph here\n", encoding="utf-8")
    assert drift_violations(steps, empty) != []
    with pytest.raises(StepGraphError):
        parse_prose_graph("# no graph here\n")


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T30.json"
    measured = write_evidence(evidence)
    assert measured["required_subset_closure_violations"] == 0
    assert measured["step_graph_prose_drift"] == 0
    assert measured["declared_reads"] > 0
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_measurement_counts_both_kinds_of_closure_failure(tmp_path: Path) -> None:
    """`required_subset_closure_violations` is the sum, so neither hides.

    A gate that counted only the offered-producer case would read zero on a
    graph whose required step reads something nothing produces at all.
    """
    measured = measure()
    assert measured["required_subset_closure_violations"] == len(
        measured["closure_violations"]
    ) + len(measured["unproduced_inputs"])
