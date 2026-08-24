"""D-12 — a task gate whose metric cannot yet be scored must have somewhere to say so.

D-2 binds an extraction score to three outcomes, not two: a number, a failure,
or **unmeasured** — "an unmeasurable gate must not resolve to a pass or to a
fail". `integral.extraction` obeys it and records `extraction_macro_f1: null`
beside `extraction_status: "unmeasured"`, which with 14 evaluation labels
against a floor of 10 is the only honest output there is.

The gate layer used to have no third outcome, so that null landed in
`gate_evidence.py`'s "not numeric" branch and read as a hard failure — the one
honest answer scoring as the worst one. That is the pressure these gates exist
to remove: an author who cannot record "not yet measurable" weakens the gate
until it measures something.

`gate_evidence.py` now takes a `status-key:` line and exits 3 for a metric the
evidence file **positively asserts** is unmeasured. This module measures
whether the board actually uses it. A task gate is *unrecordable* when its
evidence file holds a non-numeric value at the gate's key and the gate block
declares no `status-key` — the honest measurement exists, and the gate has
nowhere to put it.

**Only a positive assertion counts.** A `status-key` pointing at a key the
evidence file does not carry is not a third outcome, it is a typo; treating it
as one would let a gate stop checking by omission, which is the vacuous-pass
hole reopened somewhere new.

**What this does not count.** A missing evidence file is CA-12's hole and is
meant to be a hard failure — a declared gate cannot pass without evidence, and
"unrecordable" is not a way to excuse having measured nothing. This counts only
gates that *did* measure, and found the metric unscorable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.taskboard import DEFAULT_HISTORY_DIR, DEFAULT_TASKS_DIR, load_board

# §4.4's site. The register's §4.4 is a table of metrics rather than one formula,
# and each metric is computed by the module that owns it — but the comparison
# that turns any of them into a pass, a fail or an `unmeasured` happens here,
# once, so this is the one place the table as a whole is implemented.
METHODS_REF = "METHODS.md#44-gate-metrics"

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D12.json"

# The fenced ``gate`` block inside the ## Acceptance gate section, and the
# ``field: value`` lines within it. Mirrors gate_evidence.py's grammar rather
# than importing it: that script lives under a hyphenated vendored directory,
# is not importable as a module, and exits the process instead of returning.
_SECTION_RE = re.compile(r"##\s+Acceptance gate\s*\n(.*?)(?=\n##\s|\Z)", re.DOTALL | re.IGNORECASE)
_BLOCK_RE = re.compile(r"```gate\s*\n(.*?)```", re.DOTALL)
_GATE_RE = re.compile(r"(<=|>=|==|!=|<|>)\s*([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")


@dataclass(frozen=True)
class Reading:
    """One task's evidence gate, and whether its measurement can be recorded."""

    task_id: str
    key: str
    evidence: str
    value_is_numeric: bool
    declares_status_key: bool
    status_is_asserted: bool
    reason: str = ""

    @property
    def recordable(self) -> bool:
        return self.value_is_numeric or self.status_is_asserted


def parse_gate_block(text: str) -> dict[str, str] | None:
    """The ``gate`` block's fields, or `None` if the payload declares no block."""
    section = _SECTION_RE.search(text)
    if section is None:
        return None
    block = _BLOCK_RE.search(section.group(1))
    if block is None:
        return None
    fields: dict[str, str] = {}
    for raw in block.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        if ":" in line and not _GATE_RE.search(line.split(":", 1)[0]):
            name, value = line.split(":", 1)
            fields[name.strip().lower()] = value.strip().strip("'\"")
    return fields


def _dig(data: object, dotted: str) -> tuple[bool, object]:
    """`(found, value)` for a dotted path into parsed JSON."""
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def read_gate(task_id: str, payload: Path, root: Path) -> Reading | None:
    """Whether one task's gate can record what its evidence actually says.

    `None` for a payload this check has nothing to say about: no fenced gate
    block, an incomplete one, or an evidence file that is missing or unreadable
    — the last is CA-12's hard failure and not this metric's business.
    """
    try:
        fields = parse_gate_block(payload.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not fields:
        return None
    evidence, key = fields.get("evidence"), fields.get("key")
    if not evidence or not key:
        return None

    evidence_path = root / evidence
    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    found, value = _dig(data, key)
    numeric = found and not isinstance(value, bool) and isinstance(value, int | float)

    status_key = fields.get("status-key")
    asserted = False
    if status_key:
        status_found, status = _dig(data, status_key)
        asserted = status_found and isinstance(status, str) and bool(status.strip())

    reason = ""
    if not numeric and not asserted:
        detail = (
            f"`status-key: {status_key}` is declared but the evidence file asserts no status there"
            if status_key
            else "the gate block declares no `status-key`"
        )
        reason = (
            f"{task_id}: {evidence} records {key}={value!r}, which is not a number, and "
            f"{detail} — the gate reads the one honest measurement as a hard failure"
        )
    return Reading(task_id, key, evidence, numeric, bool(status_key), asserted, reason)


def _unmeasured(reason: str) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "unrecordable_task_gates": -1,
        "evidence_gates_read": 0,
        "gates_declaring_status_key": 0,
        "unrecordable": [reason],
        "readings": [],
    }


def measure(
    tasks: Path = DEFAULT_TASKS_DIR,
    history: Path = DEFAULT_HISTORY_DIR,
    root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """D-12's gate reading: `unrecordable_task_gates`."""
    try:
        rows, violations = load_board(tasks, history if history.is_dir() else None)
    except OSError as exc:
        return _unmeasured(f"the board at {tasks} could not be read: {exc}")
    if violations:
        # A board that will not parse is not a board with no unrecordable
        # gates: the rows that failed to load are exactly the ones nobody
        # checked.
        return _unmeasured("the board does not parse: " + "; ".join(violations))

    readings: list[Reading] = []
    for row in rows:
        task_id = str(row.get("id", "?"))
        payload_name = str(row.get("payload") or f"{task_id}.md")
        for directory in (tasks, history):
            payload = directory / payload_name
            if payload.is_file():
                reading = read_gate(task_id, payload, root)
                if reading is not None:
                    readings.append(reading)
                break

    if not readings:
        # Not zero: with no evidence gate read there is nothing to record, and
        # a clean pass here would say "every gate can record what it measured"
        # on the strength of having found no gate at all.
        return _unmeasured(
            f"no task under {tasks} declares a readable evidence gate — nothing was checked"
        )

    unrecordable = [r for r in readings if not r.recordable]
    return {
        "unrecordable_task_gates": len(unrecordable),
        "evidence_gates_read": len(readings),
        "gates_declaring_status_key": sum(1 for r in readings if r.declares_status_key),
        "unrecordable": [r.reason for r in unrecordable],
        "readings": [
            {
                "task": r.task_id,
                "key": r.key,
                "evidence": r.evidence,
                "value_is_numeric": r.value_is_numeric,
                "declares_status_key": r.declares_status_key,
                "status_is_asserted": r.status_is_asserted,
            }
            for r in sorted(readings, key=lambda r: r.task_id)
        ],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    tasks: Path = DEFAULT_TASKS_DIR,
    history: Path = DEFAULT_HISTORY_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D12.json`."""
    measured = measure(tasks, history)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.task_gate [--check]`.

    Without arguments it writes the evidence file, so `make evidence` — whose
    module list is derived from `^def _main` — regenerates D-12's number with
    no flag to remember.
    """
    parser = argparse.ArgumentParser(
        description="D-12's gate: every task gate can record what its evidence actually says"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/D12.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured["unrecordable"]:
        print(reason, file=sys.stderr)
    if measured["unrecordable_task_gates"] == -1:
        return 3
    return 1 if measured["unrecordable_task_gates"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
