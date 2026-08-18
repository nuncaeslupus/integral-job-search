"""The v2 plan, made checkable (S8).

`status/plan.md` is the build order for specification v2: one row per task, a
measurable gate on each, and a milestone that says when it lands. Its failure
mode is not being wrong — it is going **out of date silently**, which is exactly
what happened between the v1 plan and the spec-v2 round: tasks were seeded into
the queue from review findings, the plan never learned about them, and the
overlap sat unresolved until someone read both documents side by side.

So the gate is drift, measured in both directions:

- a task in `claude-arsenal/queue/tasks.jsonl` with no row in the plan — work
  nobody sequenced, gated or reconciled;
- a row in the plan with no task in the queue — work nobody can pick up.

`plan_queue_task_drift` counts both. Zero is the only acceptable value, and the
count is a **count**, never a restatement of either side's length: the S2
checker learned that lesson the hard way when a metric divided by the number it
was supposed to measure and could only ever report success.

Reports, never raises. A malformed plan or an unreadable queue is a violation
with an evidence file, not a traceback — a run that dies writes nothing, which
is indistinguishable from a run that never happened.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = _REPO_ROOT / "status" / "plan.md"
DEFAULT_QUEUE = _REPO_ROOT / "claude-arsenal" / "queue" / "tasks.jsonl"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S8.json"

# T1, T4b, S3, S1r, D-1 — every label the two documents use for a task.
_LABEL_RE = re.compile(r"^(?:T\d+[a-z]?|S\d+r?|D-\d+)$")

# A measurable gate: `<metric> <op> <threshold>`. The metric may carry digits
# (`extraction_macro_f1`), which is why this is not `[a-z_]+`.
_GATE_RE = re.compile(r"^[a-z][a-z0-9_]*\s*(?:==|!=|<=|>=|<|>)\s*-?\d+(?:\.\d+)?$")

_MIN_TASK_CELLS = 4


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def plan_rows(plan: Path) -> list[tuple[str, str]]:
    """Every implementation-task row in the plan as `(label, gate)`.

    The plan groups its tasks into one table per layer, so the Gate column is
    located from each table's own header rather than from a fixed index. A
    grouped plan that gains a column somewhere is then still measured correctly
    — the alternative silently reads the wrong cell and reports every gate as
    malformed, which is the loudest possible way to be wrong about the quietest
    possible cause.

    A header must carry **Description** as well as T# and Gate. The Evidence log
    has a T# column and a Gate column too, and without that third requirement it
    reads as a task table: its rows then satisfy the plan side of the drift
    check, so a task with an evidence row but no plan row would score zero
    drift. A measured task that nobody sequenced is precisely what this gate
    exists to catch.
    """
    rows: list[tuple[str, str]] = []
    gate_column: int | None = None
    for line in plan.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            gate_column = None
            continue
        cells = _cells(line)
        if len(cells) < _MIN_TASK_CELLS:
            continue
        lowered = [c.strip("*` ").lower() for c in cells]
        if "t#" in lowered and "gate" in lowered and "description" in lowered:
            gate_column = lowered.index("gate")
            continue
        label = cells[0].strip("*` ")
        if gate_column is None or not _LABEL_RE.match(label):
            continue
        gate = cells[gate_column].strip("*` ") if gate_column < len(cells) else ""
        rows.append((label, gate))
    return rows


def queue_labels(queue: Path) -> tuple[set[str], list[str]]:
    """Task labels from the queue, and a violation for every title that has none.

    The label is the text before the first colon of the title — `T24: …` yields
    `T24`. A task whose title does not start with one cannot be matched against
    the plan at all, so it is reported rather than skipped.
    """
    labels: set[str] = set()
    violations: list[str] = []
    for number, line in enumerate(queue.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            violations.append(f"{queue.name}:{number} is not valid JSON: {exc}")
            continue
        title = str(row.get("title", ""))
        label = title.split(":", 1)[0].strip()
        if not _LABEL_RE.match(label):
            violations.append(
                f"{row.get('id', '?')} title does not start with a task label: {title!r}"
            )
            continue
        labels.add(label)
    return labels, violations


def measure(plan: Path = DEFAULT_PLAN, queue: Path = DEFAULT_QUEUE) -> dict[str, object]:
    """Measure plan/queue drift and the plan's gate grammar."""
    violations: list[str] = []

    if not plan.exists():
        return _unmeasurable(f"{plan} not found")
    if not queue.exists():
        return _unmeasurable(f"{queue} not found")

    rows = plan_rows(plan)
    planned = {label for label, _ in rows}
    queued, queue_violations = queue_labels(queue)
    violations.extend(queue_violations)

    in_queue_only = sorted(queued - planned)
    in_plan_only = sorted(planned - queued)
    for label in in_queue_only:
        violations.append(f"{label} is in the queue and has no row in the plan")
    for label in in_plan_only:
        violations.append(f"{label} has a row in the plan and no task in the queue")

    ungated = sorted(label for label, gate in rows if not _GATE_RE.match(gate))
    for label in ungated:
        violations.append(f"{label} has no gate in `<metric> <op> <threshold>` form")

    return {
        "plan_queue_task_drift": len(in_queue_only) + len(in_plan_only),
        "rows_without_a_measurable_gate": len(ungated),
        "plan_rows": len(rows),
        "queue_tasks": len(queued),
        "in_queue_only": in_queue_only,
        "in_plan_only": in_plan_only,
        "ungated_rows": ungated,
        "violations": violations,
    }


def _unmeasurable(reason: str) -> dict[str, object]:
    """A run that could not measure records that, rather than a passing zero."""
    return {
        "plan_queue_task_drift": -1,
        "rows_without_a_measurable_gate": -1,
        "plan_rows": 0,
        "queue_tasks": 0,
        "in_queue_only": [],
        "in_plan_only": [],
        "ungated_rows": [],
        "violations": [reason],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    plan: Path = DEFAULT_PLAN,
    queue: Path = DEFAULT_QUEUE,
) -> dict[str, object]:
    """Measure and record `status/evidence/S8.json`."""
    measured = measure(plan, queue)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def main(argv: list[str] | None = None) -> int:
    """Write the S8 gate evidence. Exit 1 when the plan and the queue disagree."""
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH

    measured = write_evidence(evidence)
    violations = measured["violations"]
    assert isinstance(violations, list)

    for violation in violations:
        print(f"✗ {violation}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    return 0 if not violations else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
