"""D-21 — a step whose gate is `not_implemented` must not exit 0.

The defect: `run_checkpoint.py` printed `"gate_state": "not_implemented"` and exited
clean in the same breath, so a caller reading a status rather than the JSON saw the
step pass. Seven of the thirteen steps were in that position.

Three halves, deliberately:

* the decision itself — `step_gates.checkpoint_exit`, unit-tested over every shape of
  result a checkpoint can produce;
* the reading — `step_certification`, which counts scripts that could still reach 0
  without asking, and which has to be shown to *fail* on the old tail as well as pass
  on the new one;
* the running — each of the thirteen scripts imported here and driven through its own
  `main` with `checkpoint()` stubbed. That machinery lives in this file and not in the
  package, because `test_nothing_in_the_codebase_executes_a_contributed_parse_module`
  forbids `integral` from loading code out of a path, and the connector contract's
  safety argument rests on it.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from integral import step_certification
from integral.process_spec import Step, StepList, load_steps
from integral.step_certification import (
    UNBUILT_ANNOUNCEMENT,
    checkpoint_script,
    measure,
    probe_checkpoint,
    probe_checkpoints,
    write_evidence,
)
from integral.step_gates import (
    UNCERTIFIABLE,
    certifiable,
    certification_note,
    checkpoint_exit,
)


@pytest.fixture
def steps() -> StepList:
    return load_steps()


def _step(state: str, *, step_id: str = "ranking") -> Step:
    """A settled step with its gate state overridden — never a hand-built one.

    Every other field comes from `spec-v2-steps.json`, so a schema change breaks
    this once, in `load_steps`, rather than leaving a stale literal here that
    still validates and no longer resembles a real step.
    """
    real = next(step for step in load_steps().steps if step.id == step_id)
    return real.model_copy(update={"gate": real.gate.model_copy(update={"state": state})})


def _result(step: Step, **overrides: Any) -> dict[str, Any]:
    """What a checkpoint reports when the step's artefacts are all present.

    The best case, deliberately: a step that is *not* covered exits 1 either way
    and could never have shown the defect.
    """
    payload: dict[str, Any] = {
        "step": step.id,
        "runnable": True,
        "missing_inputs": [],
        "coverage_met": True,
        "certifiable": certifiable(step),
        "gate_state": step.gate.state,
        "certification_note": (None if certifiable(step) else certification_note(step)),
    }
    return payload | overrides


# --- the decision -----------------------------------------------------------


def test_an_unbuilt_gate_does_not_certify_the_step() -> None:
    result = _result(_step("not_implemented"))
    assert result["coverage_met"] is True
    assert result["certifiable"] is False
    assert checkpoint_exit(result) == UNCERTIFIABLE


def test_a_built_gate_with_coverage_met_still_exits_zero() -> None:
    result = _result(_step("implemented"))
    assert result["certifiable"] is True
    assert checkpoint_exit(result) == 0


def test_the_uncertifiable_code_is_distinct_from_every_code_already_in_use() -> None:
    """Reusing 1 would make an unbuilt gate look like an unfinished candidate.

    That ambiguity is why this went unnoticed: a caller had no way to tell the two
    apart, so it read the only clean answer it got as the good one.
    """
    assert UNCERTIFIABLE not in (0, 1, 2)


def test_coverage_not_met_is_one_whether_or_not_the_gate_is_built() -> None:
    for state in ("implemented", "not_implemented"):
        assert checkpoint_exit(_result(_step(state), coverage_met=False)) == 1


def test_a_step_that_is_not_runnable_is_one() -> None:
    assert checkpoint_exit(_result(_step("implemented"), runnable=False)) == 1


def test_a_result_missing_the_certifiable_key_is_not_certified() -> None:
    """A checkpoint that forgot to compute it has not passed — it has not answered."""
    result = _result(_step("implemented"))
    del result["certifiable"]
    assert checkpoint_exit(result) == UNCERTIFIABLE


def test_certifiable_reads_the_recorded_gate_state() -> None:
    assert certifiable(_step("implemented")) is True
    assert certifiable(_step("not_implemented")) is False


def test_the_refusal_names_the_metric_and_its_owner() -> None:
    note = certification_note(_step("not_implemented"))
    assert "explained_fraction" in note
    assert "T19" in note
    assert "not certified" in note


def test_a_certified_step_carries_no_refusal_note() -> None:
    assert _result(_step("implemented"))["certification_note"] is None


# --- the reading ------------------------------------------------------------


def test_the_probe_reads_every_settled_step(steps: StepList) -> None:
    probes = probe_checkpoints(steps)
    assert [probe.step for probe in probes] == [
        step.id for step in sorted(steps.steps, key=lambda s: s.n)
    ]
    assert len(probes) == steps.step_count


def test_no_committed_checkpoint_can_reach_zero_without_asking() -> None:
    measured = measure()
    assert measured["steps_certified_on_an_unimplemented_gate"] == 0, measured["shortfalls"]
    assert measured["steps_probed"] == measured["step_count"]


def test_at_least_one_step_is_actually_refused(steps: StepList) -> None:
    """The measurement would read 0 just as happily if nothing were unbuilt.

    A gate that can only be satisfied vacuously is the inert gate one level up, so
    this asserts there is a `not_implemented` step for the refusal to apply to.
    """
    refused = [probe for probe in probe_checkpoints(steps) if not probe.certifiable]
    assert refused, "no step records not_implemented — this gate is passing vacuously"


def _synthetic_skill(tmp_path: Path, step: Step, body: str, *, prose: str | None = None) -> Path:
    skills = tmp_path / "skills"
    skill_dir = skills / f"step-{step.n:02d}-{step.id.replace('_', '-')}"
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "run_checkpoint.py").write_text(body, encoding="utf-8")
    if prose is None:
        prose = "" if certifiable(step) else f"This checkpoint {UNBUILT_ANNOUNCEMENT}."
    (skill_dir / "SKILL.md").write_text(f"# {step.id}\n\n{prose}\n", encoding="utf-8")
    return skills


#: The tail as it stood before D-21, reduced to the part that decided the code.
_OLD_TAIL = """from integral.step_gates import certifiable


def checkpoint(root, handle):
    return {"coverage_met": True, "certifiable": certifiable(root)}


def main(argv=None):
    result = checkpoint(None, None)
    return 0 if result["coverage_met"] else 1
"""

_NEW_TAIL = """from integral.step_gates import certifiable, checkpoint_exit


def checkpoint(root, handle):
    return {"coverage_met": True, "certifiable": certifiable(root)}


def main(argv=None):
    result = checkpoint(None, None)
    if not result["coverage_met"]:
        return 1
    return checkpoint_exit(result)
"""


def test_the_old_tail_is_what_this_counts(tmp_path: Path) -> None:
    """The regression, planted: a check that cannot fail measures nothing."""
    step = _step("not_implemented")
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, _OLD_TAIL))
    assert not probe.routes_through_the_shared_decision
    assert any("can return 0" in reason for reason in probe.reasons)


def test_the_new_tail_passes(tmp_path: Path) -> None:
    step = _step("not_implemented")
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, _NEW_TAIL))
    assert probe.routes_through_the_shared_decision, probe.reasons


def test_a_locally_defined_decider_does_not_count(tmp_path: Path) -> None:
    """`checkpoint_exit` has to be *the* one, or thirteen copies decide thirteen ways."""
    step = _step("not_implemented")
    body = _NEW_TAIL.replace(
        "from integral.step_gates import certifiable, checkpoint_exit",
        "from integral.step_gates import certifiable\n\n\n"
        "def checkpoint_exit(result):\n    return 0",
    )
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert any("does not import checkpoint_exit" in reason for reason in probe.reasons)


def test_a_checkpoint_that_never_computes_certifiable_is_counted(tmp_path: Path) -> None:
    step = _step("not_implemented")
    body = _NEW_TAIL.replace('"certifiable": certifiable(root)', '"certifiable": True')
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert any("does not set 'certifiable'" in reason for reason in probe.reasons)


def test_a_missing_checkpoint_is_counted_never_a_clean_zero(tmp_path: Path) -> None:
    probe = probe_checkpoint(_step("implemented"), tmp_path / "nothing-here")
    assert not probe.routes_through_the_shared_decision
    assert any("no checkpoint script" in reason for reason in probe.reasons)


def test_an_unparseable_checkpoint_is_counted(tmp_path: Path) -> None:
    step = _step("not_implemented")
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, "this is not python(\n"))
    assert any("could not be read" in reason for reason in probe.reasons)


def test_a_script_with_no_main_is_counted(tmp_path: Path) -> None:
    step = _step("not_implemented")
    body = (
        "from integral.step_gates import certifiable, checkpoint_exit\n\n\n"
        "def checkpoint(root, handle):\n    return {'certifiable': certifiable(root)}\n"
    )
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert any("defines no main()" in reason for reason in probe.reasons)


def test_a_nested_helpers_zero_is_not_read_as_mains(tmp_path: Path) -> None:
    """`ast.walk` descends into nested defs; the returns there are not `main`'s.

    Latent in the committed scripts — none of them nest — which is exactly why
    it needs a test: a false positive on a gate is a gate somebody switches off.
    """
    step = _step("not_implemented")
    body = _NEW_TAIL.replace(
        "def main(argv=None):\n",
        "def main(argv=None):\n"
        "    def _tally(rows):\n"
        "        if not rows:\n"
        "            return 0\n"
        "        return len(rows)\n\n"
        "    _tally([])\n",
    )
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert probe.routes_through_the_shared_decision, probe.reasons


def test_mains_own_zero_is_still_caught_when_a_helper_nests(tmp_path: Path) -> None:
    """Narrowing the walk must not narrow it past the thing it is looking for."""
    step = _step("not_implemented")
    body = _NEW_TAIL.replace(
        "    return checkpoint_exit(result)",
        "    def _noop():\n        return None\n\n    _noop()\n    return 0",
    )
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert any("can return 0" in reason for reason in probe.reasons), probe.reasons


def test_a_bare_return_is_read_as_a_zero(tmp_path: Path) -> None:
    """`return` with no value is `None`, and `sys.exit(None)` is a clean exit."""
    step = _step("not_implemented")
    body = _NEW_TAIL.replace("        return 1", "        return")
    probe = probe_checkpoint(step, _synthetic_skill(tmp_path, step, body))
    assert any("can return 0" in reason for reason in probe.reasons)


# --- the running ------------------------------------------------------------


def _run_checkpoint(step: Step, result: dict[str, Any]) -> int:
    """Drive one committed checkpoint's own `main` over a stubbed result."""
    script = checkpoint_script(step)
    name = f"_probe_run_checkpoint_{step.n:02d}_{step.id}"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # Step 0's checkpoint re-execs the interpreter when it has just installed the
    # project's dependencies (T52). Under the dev environment it never does, but a
    # probe that could replace the process running pytest is not a probe.
    previous = os.environ.get("INTEGRAL_BOOTSTRAP_REEXEC")
    os.environ["INTEGRAL_BOOTSTRAP_REEXEC"] = "1"
    try:
        spec.loader.exec_module(module)
        module.checkpoint = lambda _root, _handle: result
        with (
            tempfile.TemporaryDirectory() as tmp,
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            return int(module.main(["--id", "probe", "--input-dir", tmp, "--dev"]))
    finally:
        sys.modules.pop(name, None)
        if previous is None:
            os.environ.pop("INTEGRAL_BOOTSTRAP_REEXEC", None)
        else:
            os.environ["INTEGRAL_BOOTSTRAP_REEXEC"] = previous


def test_every_committed_checkpoint_returns_the_code_its_gate_state_implies(
    steps: StepList,
) -> None:
    """The end-to-end claim, through each script's own `main`."""
    for step in sorted(steps.steps, key=lambda s: s.n):
        expected = 0 if step.gate.state == "implemented" else UNCERTIFIABLE
        assert _run_checkpoint(step, _result(step)) == expected, step.id


def test_every_committed_checkpoint_still_reports_one_when_coverage_is_short(
    steps: StepList,
) -> None:
    """The new code must not swallow the old one: 1 still means "not finished"."""
    for step in sorted(steps.steps, key=lambda s: s.n):
        assert _run_checkpoint(step, _result(step, coverage_met=False)) == 1, step.id
        assert _run_checkpoint(step, _result(step, runnable=False)) == 1, step.id


def test_a_step_with_an_unbuilt_gate_says_so_on_stderr(steps: StepList) -> None:
    """Exit 3 is for callers; the sentence is for whoever is reading the terminal."""
    step = next(s for s in steps.steps if s.gate.state != "implemented")
    result = _result(step)
    assert result["certification_note"] is not None
    assert step.gate.metric in result["certification_note"]
    assert step.gate.task in result["certification_note"]


# --- the evidence ------------------------------------------------------------


def test_an_unloadable_step_list_records_minus_one_never_a_clean_zero(tmp_path: Path) -> None:
    broken = tmp_path / "steps.json"
    broken.write_text("{ not json", encoding="utf-8")
    measured = measure(broken)
    assert measured["steps_certified_on_an_unimplemented_gate"] == -1
    assert measured["steps_probed"] == 0


def test_write_evidence_matches_measure(tmp_path: Path) -> None:
    target = tmp_path / "D-21.json"
    written = write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == written
    assert written == measure()


def test_the_committed_evidence_matches_what_the_code_measures_now() -> None:
    committed = json.loads(step_certification.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed == measure()


def test_a_skill_that_does_not_announce_its_unbuilt_gate_is_counted(tmp_path: Path) -> None:
    """The second half of D-21's fix, and it drifts the moment nothing reads it."""
    step = _step("not_implemented")
    skills = _synthetic_skill(tmp_path, step, _NEW_TAIL, prose="Run the checkpoint.")
    probe = probe_checkpoint(step, skills)
    assert any("does not say" in reason for reason in probe.reasons), probe.reasons


def test_a_skill_still_announcing_a_gate_that_got_built_is_counted(tmp_path: Path) -> None:
    """The same drift from the other side — the one a passing gate would leave behind."""
    step = _step("implemented")
    skills = _synthetic_skill(
        tmp_path, step, _NEW_TAIL, prose=f"This checkpoint {UNBUILT_ANNOUNCEMENT}."
    )
    probe = probe_checkpoint(step, skills)
    assert any("has built it" in reason for reason in probe.reasons), probe.reasons


def test_every_committed_skill_agrees_with_its_recorded_gate_state(steps: StepList) -> None:
    for step in sorted(steps.steps, key=lambda s: s.n):
        text = step_certification.skill_doc(step).read_text(encoding="utf-8")
        assert (UNBUILT_ANNOUNCEMENT in text) is (step.gate.state != "implemented"), step.id


def test_no_committed_checkpoint_decides_any_exit_code_for_itself(steps: StepList) -> None:
    """Not even the codes it would get right.

    `checkpoint_exit` already answers 1 for a step that is not runnable, so an
    early `return 1` beside the diagnostic was a second implementation that
    agreed by coincidence — correct until the shared function learns a new
    answer, which is the drift D-21 is about.
    """
    for step in sorted(steps.steps, key=lambda s: s.n):
        source = checkpoint_script(step).read_text(encoding="utf-8")
        main = source[source.index("def main(") :]
        decided_here = [
            line.strip()
            for line in main.splitlines()
            if line.strip().startswith("return ")
            and line.strip() != "return checkpoint_exit(result)"
        ]
        # 2 is the pre-flight code: the candidate could not be read, so there is
        # no result to hand anybody. Every other code comes from the one place.
        assert decided_here == ["return 2", "return 2"], (step.id, decided_here)
