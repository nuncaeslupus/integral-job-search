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
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.plan_v2 import DEFAULT_PLAN, plan_rows
from integral.process_spec import (
    DEFAULT_PROCESS_DOC,
    DEFAULT_STEPS_PATH,
    GateState,
    Step,
    StepList,
    load_steps,
)
from integral.step_specs import DEFAULT_STEP_SPECS_DOC, split_steps

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_DIR = _REPO_ROOT / "status" / "evidence"
DEFAULT_EVIDENCE_PATH = DEFAULT_EVIDENCE_DIR / "T48.json"
DEFAULT_D7_EVIDENCE_PATH = DEFAULT_EVIDENCE_DIR / "D7.json"
DEFAULT_D4_EVIDENCE_PATH = DEFAULT_EVIDENCE_DIR / "D-4.json"

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
    return [derive_state(step, evidence_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


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
# certification (D-21): a step whose gate is unbuilt cannot certify itself
#
# `coverage_met` answers "is every artefact this step produces present, with
# nothing left outstanding" — a question a step can satisfy by writing files
# nobody checked. It is deliberately *not* the acceptance gate, and every step
# checkpoint already said so in its `note` and printed `gate_state` beside it.
# What did not follow was the exit code. A caller that reads a status rather
# than parsing JSON saw 0, and 0 reads as "this step passed": the checkpoint
# named the gate, said out loud that the gate does not exist, and exited clean
# anyway. Seven of the thirteen steps record `not_implemented`, so seven steps
# were certifying themselves against a gate nobody has built.
#
# This is the first of the two resolutions D-21 put up — a step with no gate
# cannot be certified, so its checkpoint does not exit 0 — with the code chosen
# to carry the reason. Reusing 1 would have made an unbuilt gate
# indistinguishable from a candidate who simply has not finished the step,
# which is the ambiguity that let this pass unnoticed to begin with.

#: Exit code: coverage is met, but the step's acceptance gate is not built, so
#: nothing the checkpoint reported may be read as "this step passed".
UNCERTIFIABLE = 3

#: Exit code: coverage is met and the gate may even be built, but this candidate's
#: extractions settled **no dimension at all**, so the vocabulary does not reach
#: their market and nothing the step produced may be read as understanding (D-19).
#:
#: Its own code, for the reason `UNCERTIFIABLE` has one: reusing 3 would make "the
#: gate nobody built" indistinguishable from "the gate is fine and the words do not
#: fit this trade", and those need opposite fixes — one is owed by a task, the other
#: by the dimension model.
VOCABULARY_SILENT = 4


def certifiable(step: Step) -> bool:
    """Whether a met checkpoint for `step` may be read as the step having passed.

    Read from the recorded `gate.state` rather than re-derived from the
    evidence tree, for two reasons. Drift between the two is already
    `drift()`'s job and `make evidence` fails the build on it, so deriving here
    would duplicate a check that exists. And a checkpoint that reached for
    `status/evidence/` would report every step uncertifiable when the package
    is installed rather than run from the clone, where that tree is not on disk
    at all — refusing to certify a step for the wrong reason.
    """
    return step.gate.state == "implemented"


def certification_note(step: Step) -> str:
    """The one line a checkpoint prints when it will not certify `step`."""
    return (
        f"{step.id}: the artefacts are present, but this step's acceptance gate "
        f"({step.gate.metric} {step.gate.op} {step.gate.threshold}, owned by "
        f"{step.gate.task}) is not built — coverage is met, the step is not certified"
    )


def checkpoint_exit(result: Mapping[str, Any]) -> int:
    """The exit code a step checkpoint reports — D-21's whole decision, in one place.

    Takes the checkpoint's own result rather than the `Step`, so the exit code
    and the JSON on stdout cannot disagree: `certifiable` is a field of the
    payload the caller reads, and this returns a code derived from that same
    field. A missing key is read as *not* met — a checkpoint that forgot to
    compute one of these is not a checkpoint that passed.
    """
    if not result.get("runnable") or not result.get("coverage_met"):
        return 1
    # Checked before certifiability, and only when the step computed it. A step
    # that produces no extractions never sets the key and is unaffected; a step
    # that does sets it to a real boolean, and `False` is a refusal that holds
    # whether or not the acceptance gate exists. That independence is the point:
    # step 8's gate is `not_implemented` today, so D-21 already keeps it off 0 —
    # by accident. The day T56 builds that gate, this is what still refuses.
    if result.get("vocabulary_settled") is False:
        return VOCABULARY_SILENT
    return 0 if result.get("certifiable") else UNCERTIFIABLE


# ---------------------------------------------------------------------------
# gate ownership (D-4, D-7): does `gate.task` name the task that writes the
# number, and does every document that names an owner agree with it?
#
# `evidence_path` above turns `gate.task` into `status/evidence/<task>.json`.
# So `gate.task` is not an attribution — it is a lookup key — and a step whose
# owner is contested between documents, or whose named task's own acceptance
# gate is a *different* metric, is a step the register is reading the wrong
# file for. PR #23 hit this for the constraints step: the prose (and, until
# fixed, `spec-v2-steps.json` itself) named T24, but `constraint_field_resolution`
# is T41's own gate — T24 only pins the field set. `gate_ownership` is that
# check, generalised to all thirteen steps and every document that names one.

_TASK_LABEL_RE = re.compile(r"^(?:T\d+[a-z]?|S\d+r?|D-\d+)$")
# `Owner: T19. State:` or, wrapped across a line, `Owner: T10. State:\n...` —
# DOTALL so a hard-wrapped clause is still one match.
_OWNER_RE = re.compile(r"Owner:\s*(.+?)\.\s*State:", re.DOTALL)
_METRIC_NAME_RE = re.compile(r"^([a-z][a-z0-9_]*)\s*(?:==|!=|<=|>=|<|>)")
# `| `metric` | 2 Constraints | T41 — ... |` — the metric in column 1, the
# owner token at the start of column 3. Scoped to §9 by the caller, not to the
# whole document, so it never matches the §2 step table (metric is its last
# column there, not its first).
_PROCESS_GATE_ROW_RE = re.compile(
    r"^\|\s*`(?P<metric>[a-z][a-z0-9_]*)`\s*\|[^|]*\|\s*(?P<owner>[A-Za-z0-9-]+)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class OwnershipReading:
    """One step's `gate.task`, checked against every document that names one."""

    step: str
    task: str
    metric: str
    problems: tuple[str, ...]

    @property
    def contradicted(self) -> bool:
        return bool(self.problems)


def _prose_owners(steps_doc: Path) -> dict[int, str]:
    """Each step's raw `Owner:` clause from `spec-v2-steps.md`, by step number."""
    if not steps_doc.is_file():
        return {}
    sections = split_steps(steps_doc.read_text(encoding="utf-8"))
    owners: dict[int, str] = {}
    for n, section in sections.items():
        match = _OWNER_RE.search(section)
        if match:
            owners[n] = match.group(1).strip()
    return owners


def _process_owners(process_doc: Path) -> dict[str, str]:
    """metric -> owner token, from §9 of `spec-v2-process.md`.

    §9 names an owner for only the metrics it calls new; a metric absent here
    is not a contradiction, it is simply not repeated in this document.
    """
    if not process_doc.is_file():
        return {}
    text = process_doc.read_text(encoding="utf-8")
    marker = "## 9. Where the gates come from"
    if marker not in text:
        return {}
    start = text.index(marker)
    rest = text[start:]
    end = rest.find("\n## 10")
    section = rest if end == -1 else rest[:end]
    return {m.group("metric"): m.group("owner") for m in _PROCESS_GATE_ROW_RE.finditer(section)}


def _primary_owners(clause: str) -> list[str]:
    """The task ids named at the top level of an `Owner:` clause.

    A parenthetical does not count as naming an owner: `T19 (ranked by T18)`
    names one owner. `T18, T19` — the shape D-7 found — names two, which is
    exactly the ambiguity `evidence_path` cannot resolve on its own.
    """
    head = clause.split("(", 1)[0]
    return [tok.strip() for tok in head.split(",") if _TASK_LABEL_RE.match(tok.strip())]


def gate_ownership(
    steps: StepList | None = None,
    steps_doc: Path = DEFAULT_STEP_SPECS_DOC,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    plan: Path = DEFAULT_PLAN,
) -> list[OwnershipReading]:
    """Every step's `gate.task`, checked against three sources of an owner:

    `spec-v2-steps.md`'s `Owner:` clause, `spec-v2-process.md` §9's table (for
    the metrics it repeats), and — the check the constraints-step fix
    generalises — whether `gate.task`'s own acceptance gate in `status/plan.md`
    *is* the step's metric, which is what makes it the task whose evidence file
    actually carries the number `evidence_path` goes looking for.
    """
    steps = steps or load_steps()
    prose = _prose_owners(steps_doc)
    process_owned = _process_owners(process_doc)
    own_gate_metric: dict[str, str | None] = {}
    for row in plan_rows(plan):
        match = _METRIC_NAME_RE.match(row.gate)
        own_gate_metric[row.label] = match.group(1) if match else None

    readings: list[OwnershipReading] = []
    for step in sorted(steps.steps, key=lambda s: s.n):
        problems: list[str] = []
        task = step.gate.task
        metric = step.gate.metric

        if not _TASK_LABEL_RE.match(task):
            problems.append(f"gate.task {task!r} does not name a single task")

        clause = prose.get(step.n)
        if clause is None:
            problems.append("spec-v2-steps.md names no Owner for this step")
        else:
            owners = _primary_owners(clause)
            if len(owners) != 1:
                problems.append(
                    f"spec-v2-steps.md names {len(owners)} owner(s) ({clause!r}), not one"
                )
            elif owners[0] != task:
                problems.append(
                    f"spec-v2-steps.md names {owners[0]}, spec-v2-steps.json names {task}"
                )

        process_owner = process_owned.get(metric)
        if process_owner is not None and process_owner != task:
            problems.append(
                f"spec-v2-process.md §9 names {process_owner} for {metric}, "
                f"spec-v2-steps.json names {task}"
            )

        if task in own_gate_metric:
            task_metric = own_gate_metric[task]
            if task_metric != metric:
                problems.append(
                    f"{task}'s own plan.md gate measures {task_metric!r}, not {metric!r} — "
                    f"{task} is not the task that writes this step's number"
                )
        else:
            problems.append(f"{task} has no gate row in status/plan.md")

        readings.append(
            OwnershipReading(step=step.id, task=task, metric=metric, problems=tuple(problems))
        )
    return readings


MINIMUM_STEPS_CHECKED = 13


def measure_gate_ownership(
    steps_path: Path = DEFAULT_STEPS_PATH,
    steps_doc: Path = DEFAULT_STEP_SPECS_DOC,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    plan: Path = DEFAULT_PLAN,
) -> dict[str, Any]:
    """D-7's gate: every step, checked for an owner contradiction."""
    steps = load_steps(steps_path)
    readings = gate_ownership(steps, steps_doc, process_doc, plan)
    contradicted = [r for r in readings if r.contradicted]
    return {
        "step_gate_owner_contradictions": len(contradicted),
        "steps_checked": len(readings),
        "contradictions": [
            {"step": r.step, "task": r.task, "metric": r.metric, "problems": list(r.problems)}
            for r in contradicted
        ],
    }


def write_owner_evidence(
    evidence: Path = DEFAULT_D7_EVIDENCE_PATH,
    steps_path: Path = DEFAULT_STEPS_PATH,
    steps_doc: Path = DEFAULT_STEP_SPECS_DOC,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    plan: Path = DEFAULT_PLAN,
) -> dict[str, Any]:
    measured = measure_gate_ownership(steps_path, steps_doc, process_doc, plan)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def measure_trait_gate_ownership(
    steps_path: Path = DEFAULT_STEPS_PATH,
    steps_doc: Path = DEFAULT_STEP_SPECS_DOC,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    plan: Path = DEFAULT_PLAN,
) -> dict[str, Any]:
    """D-4's gate: the Traits step alone, checked for an owner contradiction.

    Scoped to one step because D-4 is the narrower, still-open question: unlike
    every other step, neither of Traits's two candidate owners (T27, T28) has
    `trait_evidence_sufficiency` as its own plan.md gate, so this can measure
    `1` (contradicted) honestly without D-7's general check ever being asked to
    agree that the whole register is clean.
    """
    steps = load_steps(steps_path)
    readings = gate_ownership(steps, steps_doc, process_doc, plan)
    traits = next((r for r in readings if r.step == "traits"), None)
    if traits is None:
        return {"trait_gate_owner_contradictions": 0, "steps_checked": 0, "problems": []}
    return {
        "trait_gate_owner_contradictions": 1 if traits.contradicted else 0,
        "steps_checked": 1,
        "task": traits.task,
        "metric": traits.metric,
        "problems": list(traits.problems),
    }


def write_trait_owner_evidence(
    evidence: Path = DEFAULT_D4_EVIDENCE_PATH,
    steps_path: Path = DEFAULT_STEPS_PATH,
    steps_doc: Path = DEFAULT_STEP_SPECS_DOC,
    process_doc: Path = DEFAULT_PROCESS_DOC,
    plan: Path = DEFAULT_PLAN,
) -> dict[str, Any]:
    measured = measure_trait_gate_ownership(steps_path, steps_doc, process_doc, plan)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


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

    python -m integral.step_gates [path]     → T48's gate evidence
    python -m integral.step_gates --apply    → rewrite the states, then measure
    python -m integral.step_gates --owners [path]  → D-7's gate evidence
    python -m integral.step_gates --traits [path]  → D-4's gate evidence
    """
    args = argv[1:]
    positional = [arg for arg in args if not arg.startswith("--")]

    if "--owners" in args:
        target = Path(positional[0]) if positional else DEFAULT_D7_EVIDENCE_PATH
        measured = write_owner_evidence(target)
        print(json.dumps(measured, ensure_ascii=False))
        if measured["steps_checked"] < MINIMUM_STEPS_CHECKED:
            print(
                f"only {measured['steps_checked']} step(s) were checked "
                f"(floor {MINIMUM_STEPS_CHECKED}) — a partial register is not a measurement",
                file=sys.stderr,
            )
            return 3
        for entry in measured["contradictions"]:
            problems = "; ".join(entry["problems"])
            print(f"{entry['step']} ({entry['task']}): {problems}", file=sys.stderr)
        return 1 if measured["step_gate_owner_contradictions"] else 0

    if "--traits" in args:
        target = Path(positional[0]) if positional else DEFAULT_D4_EVIDENCE_PATH
        measured = write_trait_owner_evidence(target)
        print(json.dumps(measured, ensure_ascii=False))
        if measured["steps_checked"] < 1:
            print("the traits step could not be found — nothing was measured", file=sys.stderr)
            return 3
        for problem in measured["problems"]:
            print(problem, file=sys.stderr)
        return 1 if measured["trait_gate_owner_contradictions"] else 0

    if "--apply" in args:
        for reading in apply_states():
            print(f"{reading.step}: {reading.recorded} → {reading.derived} ({reading.why})")

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
