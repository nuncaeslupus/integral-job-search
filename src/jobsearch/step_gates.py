"""The step gate state register — derived, not declared (T48).

Every step in `spec-v2-steps.json` carries a gate metric and a `state`. The
state was hand-edited, and nothing checked it: truthful the day it was written,
and untruthful the moment a gate first passed. This derives it instead, from
the evidence files the gates actually write, so the field becomes a value that
is checked rather than one that is declared.

**A gate metric is counted, never restated.** The S2 checker learned this the
hard way — `steps_with_named_gate_metric` divided by `step_count` instead of
counting, so the number meant to say *which* step lacked a metric would have
said all of them had one. A state register that trusts its own input has the
same shape of bug: it reports whatever it was told. So nothing here reads
`gate.state` in order to decide anything; it reads it only to compare.

**`not_implemented` is a recorded value, not a blank.** A step whose task has
written no evidence yet reads `not_implemented`, and that is correct — the
alternative is a register that cannot tell "not built" from "built and
failing", which is the distinction the whole thing exists for. Failing evidence
therefore also reads `not_implemented`: a gate that ran and did not pass has
not implemented its step, and saying otherwise would let a red measurement
present as a green step.
"""

from __future__ import annotations

import json
import operator
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobsearch.process_spec import DEFAULT_STEPS_PATH, GateState, Step, StepList, load_steps

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = _REPO_ROOT / "status" / "evidence"
DEFAULT_EVIDENCE_PATH = DEFAULT_EVIDENCE_DIR / "T48.json"

_COMPARISONS: dict[str, Callable[[float, float], bool]] = {
    "==": operator.eq,
    ">=": operator.ge,
    "<=": operator.le,
    ">": operator.gt,
    "<": operator.lt,
}


class GateStateError(Exception):
    """The register cannot be computed."""


@dataclass(frozen=True)
class Reading:
    """What one step's evidence says, and what state that implies."""

    step: str
    task: str
    metric: str
    recorded: GateState
    derived: GateState
    measured: float | None
    why: str

    @property
    def drifted(self) -> bool:
        return self.recorded != self.derived


def evidence_path(task: str, evidence_dir: Path = DEFAULT_EVIDENCE_DIR) -> Path:
    """Where the task that owns a step's gate writes its measurement."""
    return Path(evidence_dir) / f"{task}.json"


def read_measurement(
    step: Step, evidence_dir: Path = DEFAULT_EVIDENCE_DIR
) -> tuple[float | None, str]:
    """The number this step's gate metric currently reads, and where it came from.

    Returns `None` rather than raising for every way the number can be absent —
    no file, unreadable file, no such key, a value that is not a number. The
    register has to report on thirteen steps, and one unwritten evidence file
    must not stop it describing the other twelve.
    """
    path = evidence_path(step.gate.task, evidence_dir)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, f"no evidence file at {path.name}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"{path.name} could not be read: {exc}"
    if not isinstance(payload, dict) or step.gate.metric not in payload:
        return None, f"{path.name} records no {step.gate.metric!r}"
    value = payload[step.gate.metric]
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None, f"{path.name} records {step.gate.metric!r} as {value!r}, which is not a number"
    return float(value), f"{path.name} records {step.gate.metric} = {value}"


def derive_state(step: Step, evidence_dir: Path = DEFAULT_EVIDENCE_DIR) -> Reading:
    """A step's state, computed from what its gate measured."""
    measured, why = read_measurement(step, evidence_dir)
    if measured is None:
        return Reading(
            step=step.id,
            task=step.gate.task,
            metric=step.gate.metric,
            recorded=step.gate.state,
            derived="not_implemented",
            measured=None,
            why=why,
        )
    compare = _COMPARISONS.get(step.gate.op)
    if compare is None:  # pragma: no cover - the schema's Literal forbids it
        raise GateStateError(f"{step.id}: {step.gate.op!r} is not a comparison")
    passes = compare(measured, step.gate.threshold)
    return Reading(
        step=step.id,
        task=step.gate.task,
        metric=step.gate.metric,
        recorded=step.gate.state,
        derived="implemented" if passes else "not_implemented",
        measured=measured,
        why=(
            f"{why} — {measured} {step.gate.op} {step.gate.threshold} is "
            f"{'satisfied' if passes else 'not satisfied'}"
        ),
    )


def register(
    steps: StepList | None = None, evidence_dir: Path = DEFAULT_EVIDENCE_DIR
) -> list[Reading]:
    """Every step, in journey order, with its recorded and derived states."""
    steps = steps or load_steps()
    return [
        derive_state(step, evidence_dir) for step in sorted(steps.steps, key=lambda s: s.n)
    ]


def drift(
    steps: StepList | None = None, evidence_dir: Path = DEFAULT_EVIDENCE_DIR
) -> list[Reading]:
    """The steps whose recorded state is not the state their evidence implies."""
    return [reading for reading in register(steps, evidence_dir) if reading.drifted]


def apply_states(
    steps_path: Path = DEFAULT_STEPS_PATH, evidence_dir: Path = DEFAULT_EVIDENCE_DIR
) -> list[Reading]:
    """Write the derived states back into the step list. Returns what changed.

    Editing the file rather than only reporting on it is the point: the field
    stops being hand-maintained. The rest of each step is untouched, and the
    file is rewritten with the same formatting so the diff shows only states.
    """
    steps = load_steps(steps_path)
    changed = drift(steps, evidence_dir)
    if not changed:
        return []
    by_step = {reading.step: reading for reading in changed}
    raw = json.loads(Path(steps_path).read_text(encoding="utf-8"))
    for entry in raw["steps"]:
        reading = by_step.get(entry["id"])
        if reading is not None:
            entry["gate"]["state"] = reading.derived
    Path(steps_path).write_text(
        json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return changed


# ---------------------------------------------------------------------------
# the gate


def measure(
    steps_path: Path = DEFAULT_STEPS_PATH, evidence_dir: Path = DEFAULT_EVIDENCE_DIR
) -> dict[str, Any]:
    steps = load_steps(steps_path)
    readings = register(steps, evidence_dir)
    drifted = [reading for reading in readings if reading.drifted]
    return {
        "step_gate_state_drift": len(drifted),
        "steps_read": len(readings),
        "implemented": sorted(r.step for r in readings if r.derived == "implemented"),
        "not_implemented": sorted(r.step for r in readings if r.derived == "not_implemented"),
        "drift": [
            {
                "step": r.step,
                "task": r.task,
                "metric": r.metric,
                "recorded": r.recorded,
                "derived": r.derived,
                "why": r.why,
            }
            for r in drifted
        ],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path = DEFAULT_STEPS_PATH,
    evidence_dir: Path = DEFAULT_EVIDENCE_DIR,
) -> dict[str, Any]:
    measured = measure(steps_path, evidence_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Report the register, or write the derived states into the step list.

        python -m jobsearch.step_gates [path]     → T48's gate evidence
        python -m jobsearch.step_gates --apply    → rewrite the states, then measure
    """
    if "--apply" in argv[1:]:
        for reading in apply_states():
            print(f"{reading.step}: {reading.recorded} → {reading.derived} ({reading.why})")

    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["steps_read"] == 0:
        print("no steps were read — nothing was measured", file=sys.stderr)
        return 3
    for entry in measured["drift"]:
        print(
            f"{entry['step']} records {entry['recorded']} but {entry['why']}",
            file=sys.stderr,
        )
    return 1 if measured["drift"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
