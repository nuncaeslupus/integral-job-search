"""D-29 — the plan's merge-order table lists the tasks it says it lists.

`status/plan.md`'s merge-order section states a contract: merged tasks are not
listed in a milestone row, and every open task appears in exactly one. Nothing
read it, and it drifted in **both** directions — merged tasks left in the rows
(82 of the 89 labels when D-29 was filed) and open tasks in no row at all.
A metric over one direction would have gone green over the other, so the gate
counts **membership violations**:

- a label listed in a milestone row whose task the board says is `merged`;
- an open task (neither `merged` nor `cancelled`) listed in no row;
- an open task listed in more than one row, or twice in one — counted with
  multiplicity, so appending a second copy cannot hide the first;
- a listed label no task on the board carries, or a token that is no label.

**Merged state comes from the archive, never from the plan.** The board is read
by `plan_v2.queue_tasks` and "merged" is `plan_v2.merged_tasks`, the same
function D-27's tick check uses, so the two cannot disagree about which tasks
are finished. A tick in the plan is not consulted: a check that read the
document it is checking would be satisfiable by editing that document.

**Denominators.** A zero over nothing is not a pass. `merged_tasks_resolved` (the
archive) and `milestone_labels_scanned` (the rows) are asserted as floors in the
`naming.MINIMUM_SCANNED` style — committed as the floor, never as a count of the
day, because the count moves on every task PR (T100). A breach is **exit 1**,
not 3: `make evidence` records 3 as "unmeasured" and carries on (#297). The
floors are read *before* anything is written, so a breaching run leaves the
committed record alone rather than writing one that claims the floor held.
`gate_status` is `unmeasured` (and the metric `-1`) when the archive resolves no
merged task or the table yields no label.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from integral.plan_v2 import (
    _LABEL_RE,
    DEFAULT_PLAN,
    DEFAULT_QUEUE,
    _cells,
    _clean,
    merged_tasks,
    queue_tasks,
    task_label,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-29.json"

#: Floor on the archive: merged tasks resolved from `_history/`. The archive only
#: grows (248 when this landed), so a floor well under it survives pruning and
#: still refuses a scan that read nothing. A floor, not a census, for T100's reason.
MINIMUM_MERGED_RESOLVED = 100

#: Floor on the table: milestone-row labels scanned. The rows *shrink* as tasks
#: merge — removing a merged label is the contract — so this sits well below
#: today's population (about 50) and is a statement that the table was read, not
#: that it is any particular size. When the open set falls below it the plan is
#: nearly finished and this is the number to revisit, deliberately.
MINIMUM_ROW_LABELS = 20

#: `cancelled` is closed without being merged: the contract neither requires nor
#: forbids listing it, so it is outside both directions.
_CLOSED = frozenset({"merged", "cancelled"})

_NOT_A_LABEL = "is not a task label"


def milestone_rows(plan: Path) -> list[tuple[str, list[str]]]:
    """`(milestone, raw task tokens)` for each row of the merge-order table.

    The table is found by its header (`milestone | … | tasks`), and the column
    by name, so a reordered table still reads correctly. Any non-table line
    clears the column, so a later table cannot be read as milestone rows.
    """
    rows: list[tuple[str, list[str]]] = []
    column: int | None = None
    for line in plan.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            column = None
            continue
        cells = _cells(line)
        lowered = [_clean(c).lower() for c in cells]
        if lowered and lowered[0] == "milestone" and "tasks" in lowered:
            column = lowered.index("tasks")
            continue
        if column is None or set("".join(cells)) <= set("-: "):
            continue
        if column < len(cells):
            tokens = [t.strip() for t in cells[column].split(",") if t.strip()]
            rows.append((_clean(cells[0]), tokens))
    return rows


def measure(plan: Path = DEFAULT_PLAN, queue: Path = DEFAULT_QUEUE) -> dict[str, object]:
    """Count membership violations between the milestone rows and the archive."""
    if not plan.exists():
        return _unmeasurable(f"{plan} not found")
    if not queue.exists():
        return _unmeasurable(f"{queue} not found")
    tasks, board_violations = queue_tasks(queue)
    labelled = {label: row for row in tasks if (label := task_label(row)) is not None}
    merged = merged_tasks(labelled)
    open_labels = sorted(
        label for label, task in labelled.items() if str(task.get("status")) not in _CLOSED
    )

    listed: list[str] = []
    malformed: list[str] = []
    for milestone, tokens in milestone_rows(plan):
        for token in tokens:
            if _LABEL_RE.match(token):
                listed.append(token)
            else:
                malformed.append(f"{milestone}: `{token}` {_NOT_A_LABEL}")
    counts = Counter(listed)

    merged_still_listed = sorted(label for label in counts if label in merged)
    unknown = sorted(label for label in counts if label not in labelled)
    unlisted = [label for label in open_labels if counts[label] == 0]
    repeated = [label for label in open_labels if counts[label] > 1]
    violations = [
        *board_violations,
        *malformed,
        *(
            f"{label} is merged and still listed in a milestone row"
            for label in merged_still_listed
        ),
        *(f"{label} is listed and no task on the board carries it" for label in unknown),
        *(f"{label} is open and in no milestone row" for label in unlisted),
        *(f"{label} is open and listed {counts[label]} times" for label in repeated),
    ]

    measurable = bool(merged) and bool(listed)
    return {
        "milestone_row_membership_violations": len(violations) if measurable else -1,
        "gate_status": "measured" if measurable else "unmeasured",
        "merged_still_listed": merged_still_listed,
        "listed_without_a_task": unknown,
        "open_but_unlisted": unlisted,
        "open_but_listed_more_than_once": repeated,
        "milestone_labels_scanned": len(listed),
        "merged_tasks_resolved": len(merged),
        "open_tasks_evaluated": len(open_labels),
        "violations": violations,
    }


def _unmeasurable(reason: str) -> dict[str, object]:
    return {
        "milestone_row_membership_violations": -1,
        "gate_status": "unmeasured",
        "merged_still_listed": [],
        "listed_without_a_task": [],
        "open_but_unlisted": [],
        "open_but_listed_more_than_once": [],
        "milestone_labels_scanned": 0,
        "merged_tasks_resolved": 0,
        "open_tasks_evaluated": 0,
        "violations": [reason],
    }


def floor_breaches(measured: dict[str, object]) -> list[str]:
    """Which denominators fell under their floor. Empty is the pass."""
    breaches = []
    for name, floor in (
        ("merged_tasks_resolved", MINIMUM_MERGED_RESOLVED),
        ("milestone_labels_scanned", MINIMUM_ROW_LABELS),
    ):
        count = measured[name]
        assert isinstance(count, int)
        if count < floor:
            breaches.append(
                f"only {count} {name} (floor {floor}) — zero violations over a scan that "
                "read nothing is not a measurement"
            )
    return breaches


def record(measured: dict[str, object]) -> dict[str, object]:
    """What is committed: the violations exactly, the denominators as their floors."""
    dropped = ("merged_tasks_resolved", "milestone_labels_scanned", "open_tasks_evaluated")
    committed = {k: v for k, v in measured.items() if k not in dropped}
    committed["merged_tasks_resolved_at_least"] = MINIMUM_MERGED_RESOLVED
    committed["milestone_labels_scanned_at_least"] = MINIMUM_ROW_LABELS
    return committed


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    plan: Path = DEFAULT_PLAN,
    queue: Path = DEFAULT_QUEUE,
) -> dict[str, object]:
    """Measure, check the floors, and only then record. A breach writes nothing."""
    measured = measure(plan, queue)
    if floor_breaches(measured):
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """Write the D-29 evidence. Exit 1 on a violation or on a floor breach."""
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(evidence)
    violations = measured["violations"]
    assert isinstance(violations, list)
    for violation in violations:
        print(f"✗ {violation}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if violations:
        return 1
    breaches = floor_breaches(measured)
    for breach in breaches:
        print(breach, file=sys.stderr)
    # Exit 1, not 3: the Makefile records 3 as "unmeasured" and continues (#297).
    return 1 if breaches else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
