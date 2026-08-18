"""The v2 plan, made checkable (S8).

`status/plan.md` is the build order for specification v2: one row per task, a
measurable gate on each, the tasks it depends on, and a milestone that says when
it lands. Its failure mode is not being wrong — it is going **out of date
silently**, which is exactly what happened between the v1 plan and the spec-v2
round: tasks were seeded into the queue from review findings, the plan never
learned about them, and the overlap sat unresolved until someone read both
documents side by side.

So the gate is drift, measured in three dimensions and in both directions:

- **membership** — a task in `claude-arsenal/queue/tasks.jsonl` with no row in
  the plan is work nobody sequenced, gated or reconciled; a row in the plan with
  no task in the queue is work nobody can pick up;
- **gate** — a plan row whose Gate cell disagrees with the `gate` block in that
  task's payload. Both are read as the acceptance condition, so a disagreement
  means whichever is implemented silently contradicts the other;
- **dependency** — a plan row whose `Depends` cell disagrees with the queue
  row's blocking `deps`. The plan is what a human reads; `queue_batch.sh`
  dispatches from the queue alone, so a prerequisite recorded only in the plan
  does not exist. A task can then be built before the thing it was sequenced
  behind, which is the concrete failure the milestones exist to prevent.

`plan_queue_task_drift` counts all three. Zero is the only acceptable value, and
the count is a **count**, never a restatement of either side's length: the S2
checker learned that lesson the hard way when a metric divided by the number it
was supposed to measure and could only ever report success. Labels are counted
with multiplicity for the same reason — collapsing them into a set hides a
duplicated row instead of reporting it.

Reports, never raises. A malformed plan, an unreadable queue, a JSONL line that
parses to something other than an object — each is a violation with an evidence
file, not a traceback. A run that dies writes nothing, which is
indistinguishable from a run that never happened.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
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

_GATE_BLOCK_RE = re.compile(r"^```gate\s*$", re.MULTILINE)
_MIN_TASK_CELLS = 4


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _clean(cell: str) -> str:
    return cell.strip("*` ")


def _normalise_gate(gate: str) -> str:
    """Collapse whitespace so `a  ==  0` and `a == 0` compare equal."""
    return " ".join(gate.replace("`", "").split())


class PlanRow:
    """One implementation-task row: its label, its gate, and what it depends on."""

    def __init__(self, label: str, gate: str, depends: list[str]) -> None:
        self.label = label
        self.gate = gate
        self.depends = depends


def plan_rows(plan: Path) -> list[PlanRow]:
    """Every implementation-task row in the plan.

    The plan groups its tasks into one table per layer, so the Gate and Depends
    columns are located from each table's own header rather than from a fixed
    index. A grouped plan that gains a column somewhere is then still measured
    correctly — the alternative silently reads the wrong cell and reports every
    gate as malformed, which is the loudest possible way to be wrong about the
    quietest possible cause.

    A task header must carry **Description** as well as T# and Gate. The
    Evidence log has a T# column and a Gate column too, and without that third
    requirement it reads as a task table: its rows then satisfy the plan side of
    the drift check, so a task with an evidence row but no plan row would score
    zero drift. A measured task that nobody sequenced is precisely what this
    gate exists to catch.

    Column state is cleared by **any** header row, not only by leaving the
    table. Resetting on a blank line alone would make the Evidence log safe by
    typography: it is preceded by a blank line today, and an edit that removed
    it would silently turn its rows into plan rows carrying the wrong gate.
    """
    rows: list[PlanRow] = []
    gate_column: int | None = None
    depends_column: int | None = None
    for line in plan.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            gate_column = depends_column = None
            continue
        cells = _cells(line)
        if len(cells) < _MIN_TASK_CELLS:
            continue
        lowered = [_clean(c).lower() for c in cells]
        if "t#" in lowered:  # a header row — this table's columns, or none
            is_task_table = "gate" in lowered and "description" in lowered
            gate_column = lowered.index("gate") if is_task_table else None
            depends_column = (
                lowered.index("depends") if is_task_table and "depends" in lowered else None
            )
            continue
        label = _clean(cells[0])
        if gate_column is None or not _LABEL_RE.match(label):
            continue
        gate = _clean(cells[gate_column]) if gate_column < len(cells) else ""
        depends: list[str] = []
        if depends_column is not None and depends_column < len(cells):
            depends = [
                _clean(part)
                for part in cells[depends_column].split(",")
                if _LABEL_RE.match(_clean(part))
            ]
        rows.append(PlanRow(label, gate, depends))
    return rows


def payload_gate(payload: Path) -> str | None:
    """The metric line of a payload's first fenced `gate` block, if it has one."""
    if not payload.exists():
        return None
    lines = payload.read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if _GATE_BLOCK_RE.match(line) and index + 1 < len(lines):
            return lines[index + 1].strip()
    return None


def queue_tasks(queue: Path) -> tuple[list[dict[str, object]], list[str]]:
    """Every queue record that is a JSON object, and a violation for the rest."""
    tasks: list[dict[str, object]] = []
    violations: list[str] = []
    for number, line in enumerate(queue.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            violations.append(f"{queue.name}:{number} is not valid JSON: {exc}")
            continue
        if not isinstance(row, dict):
            # Valid JSON, invalid queue record — the queue doctor's `bad-row`.
            violations.append(f"{queue.name}:{number} is not a JSON object: {type(row).__name__}")
            continue
        tasks.append(row)
    return tasks, violations


def task_label(row: dict[str, object]) -> str | None:
    """The task label a queue title starts with — `T24: …` yields `T24`."""
    label = str(row.get("title", "")).split(":", 1)[0].strip()
    return label if _LABEL_RE.match(label) else None


def _duplicates(labels: list[str], side: str) -> list[str]:
    counted = Counter(labels)
    return [
        f"{label} appears {count} times in the {side}"
        for label, count in sorted(counted.items())
        if count > 1
    ]


def measure(plan: Path = DEFAULT_PLAN, queue: Path = DEFAULT_QUEUE) -> dict[str, object]:
    """Measure plan/queue drift in membership, gate and dependency."""
    if not plan.exists():
        return _unmeasurable(f"{plan} not found")
    if not queue.exists():
        return _unmeasurable(f"{queue} not found")

    violations: list[str] = []
    rows = plan_rows(plan)
    tasks, queue_violations = queue_tasks(queue)
    violations.extend(queue_violations)

    planned = [row.label for row in rows]
    by_label = {row.label: row for row in rows}
    labelled = {label: row for row in tasks if (label := task_label(row)) is not None}
    queued = [label for row in tasks if (label := task_label(row)) is not None]
    for row in tasks:
        if task_label(row) is None:
            violations.append(
                f"{row.get('id', '?')} title does not start with a task label: "
                f"{row.get('title', '')!r}"
            )

    duplicates = _duplicates(planned, "plan") + _duplicates(queued, "queue")
    violations.extend(duplicates)

    in_queue_only = sorted(set(queued) - set(planned))
    in_plan_only = sorted(set(planned) - set(queued))
    for label in in_queue_only:
        violations.append(f"{label} is in the queue and has no row in the plan")
    for label in in_plan_only:
        violations.append(f"{label} has a row in the plan and no task in the queue")

    ungated = sorted(row.label for row in rows if not _GATE_RE.match(_normalise_gate(row.gate)))
    for label in ungated:
        violations.append(f"{label} has no gate in `<metric> <op> <threshold>` form")

    # --- gate agreement: the plan row against the task's own payload ---
    gate_mismatches: list[str] = []
    id_to_label = {str(row.get("id")): label for label, row in labelled.items()}
    for label, task in sorted(labelled.items()):
        planned_row = by_label.get(label)
        if planned_row is None:
            continue
        payload_name = str(task.get("payload") or f"{task.get('id')}.md")
        declared = payload_gate(queue.parent / payload_name)
        if declared is None:
            continue  # a payload with no gate block is queue_doctor's finding
        if _normalise_gate(declared) != _normalise_gate(planned_row.gate):
            gate_mismatches.append(
                f"{label}: plan says `{_normalise_gate(planned_row.gate)}`, "
                f"payload says `{_normalise_gate(declared)}`"
            )
    violations.extend(gate_mismatches)

    # --- dependency agreement: the plan's Depends against the queue's deps ---
    dependency_mismatches: list[str] = []
    for label, task in sorted(labelled.items()):
        planned_row = by_label.get(label)
        if planned_row is None:
            continue
        deps = task.get("deps")
        queued_deps = set()
        if isinstance(deps, list):
            for dep in deps:
                if isinstance(dep, dict) and dep.get("type", "blocks") == "blocks":
                    queued_deps.add(id_to_label.get(str(dep.get("id")), str(dep.get("id"))))
        planned_deps = set(planned_row.depends)
        for missing in sorted(planned_deps - queued_deps):
            dependency_mismatches.append(
                f"{label} depends on {missing} in the plan and not in the queue"
            )
        for extra in sorted(queued_deps - planned_deps):
            dependency_mismatches.append(
                f"{label} depends on {extra} in the queue and not in the plan"
            )
    violations.extend(dependency_mismatches)

    return {
        "plan_queue_task_drift": (
            len(in_queue_only)
            + len(in_plan_only)
            + len(gate_mismatches)
            + len(dependency_mismatches)
            + len(duplicates)
        ),
        "rows_without_a_measurable_gate": len(ungated),
        "plan_rows": len(rows),
        "queue_tasks": len(queued),
        "in_queue_only": in_queue_only,
        "in_plan_only": in_plan_only,
        "duplicate_labels": duplicates,
        "gate_mismatches": gate_mismatches,
        "dependency_mismatches": dependency_mismatches,
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
        "duplicate_labels": [],
        "gate_mismatches": [],
        "dependency_mismatches": [],
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
