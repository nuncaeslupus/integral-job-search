"""T48 — the step gate state register.

Every step carries a gate metric and a `state`. The state was hand-edited and
nothing checked it, which is truthful the day it is written and untruthful the
moment a gate first passes. It is derived now, from the evidence the gates
write.

The failure mode to avoid is the one the S2 checker hit: a number that restates
its input instead of counting it. Nothing here reads `gate.state` to decide
anything — only to compare against what the evidence says.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.process_spec import StepList, load_steps
from integral.step_gates import (
    apply_states,
    derive_state,
    drift,
    evidence_path,
    measure,
    register,
    write_evidence,
)


@pytest.fixture
def steps() -> StepList:
    return load_steps()


@pytest.fixture
def evidence(tmp_path: Path) -> Path:
    directory = tmp_path / "evidence"
    directory.mkdir()
    return directory


def _record(evidence: Path, task: str, **values: object) -> None:
    (evidence / f"{task}.json").write_text(json.dumps(values) + "\n", encoding="utf-8")


def _step(steps: StepList, step_id: str):  # type: ignore[no-untyped-def]
    return next(step for step in steps.steps if step.id == step_id)


# --- the three states ------------------------------------------------------


def test_step_state_matches_recorded_evidence(steps: StepList, evidence: Path) -> None:
    """A step whose evidence records a passing measurement cannot read not_implemented."""
    identify = _step(steps, "identify")
    _record(evidence, identify.gate.task, cross_user_leaks=0)
    reading = derive_state(identify, evidence)
    assert reading.derived == "implemented"
    assert reading.measured == 0.0
    assert "cross_user_leaks" in reading.why


def test_missing_evidence_reads_not_implemented(steps: StepList, evidence: Path) -> None:
    """`not_implemented` is a recorded value, not a blank."""
    for step in steps.steps:
        reading = derive_state(step, evidence)
        assert reading.derived == "not_implemented"
        assert reading.measured is None
        assert "no evidence file" in reading.why


def test_failing_evidence_does_not_read_implemented(steps: StepList, evidence: Path) -> None:
    """A gate that ran and did not pass has not implemented its step.

    Saying otherwise would let a red measurement present as a green step, which
    is worse than saying nothing.
    """
    identify = _step(steps, "identify")
    _record(evidence, identify.gate.task, cross_user_leaks=3)
    reading = derive_state(identify, evidence)
    assert reading.derived == "not_implemented"
    assert reading.measured == 3.0
    assert "not satisfied" in reading.why


def test_every_comparison_the_schema_allows_is_applied(steps: StepList, evidence: Path) -> None:
    """A `>=` gate read as `==` would fail every step that overshot its floor."""
    for step in steps.steps:
        threshold = step.gate.threshold
        satisfying = {
            "==": threshold,
            ">=": threshold + 1,
            "<=": threshold - 1,
            ">": threshold + 1,
            "<": threshold - 1,
        }[step.gate.op]
        _record(evidence, step.gate.task, **{step.gate.metric: satisfying})
        assert derive_state(step, evidence).derived == "implemented", step.id


# --- evidence that is not a measurement -----------------------------------


def test_a_missing_key_is_not_a_measurement(steps: StepList, evidence: Path) -> None:
    identify = _step(steps, "identify")
    _record(evidence, identify.gate.task, something_else=0)
    reading = derive_state(identify, evidence)
    assert reading.derived == "not_implemented"
    assert "records no" in reading.why


def test_a_value_that_is_not_a_number_is_not_a_measurement(steps: StepList, evidence: Path) -> None:
    """A boolean is not a number here, even though Python says otherwise.

    `cross_user_leaks: true` would compare equal to 1 and read as a real
    measurement of one leak — or, worse, `passing: true` against a `== 1` gate
    would read as implemented on the strength of a word.
    """
    identify = _step(steps, "identify")
    for value in ("zero", None, True, [0]):
        _record(evidence, identify.gate.task, cross_user_leaks=value)
        reading = derive_state(identify, evidence)
        assert reading.derived == "not_implemented"
        assert "not a number" in reading.why


def test_unreadable_evidence_does_not_stop_the_other_twelve_steps(
    steps: StepList, evidence: Path
) -> None:
    """The register describes thirteen steps; one broken file must not end it."""
    identify = _step(steps, "identify")
    (evidence / f"{identify.gate.task}.json").write_text("{not json", encoding="utf-8")
    readings = register(steps, evidence)
    assert len(readings) == len(steps.steps)
    assert all(reading.derived == "not_implemented" for reading in readings)


def test_the_evidence_file_is_named_after_the_task_that_owns_the_gate(
    steps: StepList,
) -> None:
    assert evidence_path("S3", Path("/x")) == Path("/x/S3.json")
    assert _step(steps, "identify").gate.task == "S3"


# --- against the committed state ------------------------------------------


def test_the_committed_step_list_has_no_drift() -> None:
    """The register is applied, so the file and the evidence agree."""
    assert drift() == []


def test_step_zero_is_implemented_now_that_s3_measured_it() -> None:
    """The first state this register ever changed, kept as a test."""
    identify = next(reading for reading in register() if reading.step == "identify")
    assert identify.derived == "implemented"
    assert identify.recorded == "implemented"


def test_the_register_reads_every_step(steps: StepList) -> None:
    assert {reading.step for reading in register(steps)} == {step.id for step in steps.steps}


def test_applying_states_changes_only_the_state_field(tmp_path: Path, evidence: Path) -> None:
    """The rest of each step is untouched, so the diff shows only states."""
    steps_file = tmp_path / "steps.json"
    original = json.loads(Path("status/spec-v2-steps.json").read_text(encoding="utf-8"))
    for entry in original["steps"]:
        entry["gate"]["state"] = "not_implemented"
    steps_file.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    identify = next(entry for entry in original["steps"] if entry["id"] == "identify")
    _record(evidence, identify["gate"]["task"], cross_user_leaks=0)

    changed = apply_states(steps_file, evidence)
    assert [reading.step for reading in changed] == ["identify"]

    after = json.loads(steps_file.read_text(encoding="utf-8"))
    for before_step, after_step in zip(original["steps"], after["steps"], strict=True):
        before_gate = dict(before_step["gate"])
        after_gate = dict(after_step["gate"])
        before_gate.pop("state")
        after_gate.pop("state")
        assert before_gate == after_gate
        assert {k: v for k, v in before_step.items() if k != "gate"} == {
            k: v for k, v in after_step.items() if k != "gate"
        }


def test_applying_twice_changes_nothing_the_second_time(tmp_path: Path, evidence: Path) -> None:
    steps_file = tmp_path / "steps.json"
    steps_file.write_text(
        Path("status/spec-v2-steps.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    apply_states(steps_file, evidence)
    assert apply_states(steps_file, evidence) == []


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    target = tmp_path / "T48.json"
    measured = write_evidence(target)
    assert measured["step_gate_state_drift"] == 0
    assert measured["steps_read"] == 13
    assert json.loads(target.read_text(encoding="utf-8")) == measured


def test_the_measurement_counts_drift_rather_than_restating_the_field() -> None:
    """The S2 lesson: a number that divides by its own input says nothing.

    `step_gate_state_drift` is a count of disagreements, so a register that
    simply echoed `gate.state` back would score zero *and* be caught by
    `test_failing_evidence_does_not_read_implemented`.
    """
    measured = measure()
    assert measured["step_gate_state_drift"] == len(measured["drift"])
    assert len(measured["implemented"]) + len(measured["not_implemented"]) == measured["steps_read"]
