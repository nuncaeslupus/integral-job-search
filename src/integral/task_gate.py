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

#: The floor `evidence_gates_read` is asserted against, and what the record
#: carries in its place. Today's board declares a little over a hundred and
#: twenty readable gates; this sits well below that, so the queue can shed a
#: workspace without the gate turning red for a reason that is not a finding.
#:
#: A floor rather than a census, for T100's reason one axis over. The count is
#: a **denominator** — it says the sweep found gates to read, so a clean zero
#: is not resting on an empty board — and it measures nothing about whether
#: any gate can record what it found. Committed as an exact value it moved
#: every time *another* task PR merged, because a merged task lands one more
#: gate block on the board and CI scores the merge ref: every other open PR's
#: D12 went stale on someone else's merge, quadratically.
MINIMUM_GATES_READ = 100

#: The same, for the third outcome. D-12 exists to make `unmeasured`
#: expressible, and a board where *no* gate declares a `status-key` has the
#: facility without the use. The exact count is still not committable — it
#: grows with the queue — but a floor of one was not a floor: the board
#: declares twenty-nine, so one permitted a 96% collapse in adoption with no
#: signal at all, and said nothing the test suite's `>= 1` did not already
#: say. Twenty is a round floor under the live twenty-nine — nine of headroom,
#: enough to shed a workspace and little enough that losing most of the
#: adoption is a finding. It is deliberately NOT derived from
#: `MINIMUM_GATES_READ`'s fraction: 100/132 is 76% and 20/29 is 69%, so a
#: sentence claiming the two floors sit at the same fraction of live would be
#: false, and a false rationale is worse than a stated round number — the next
#: reader would recompute the ratio to move the floor and land somewhere the
#: headroom argument never justified.
MINIMUM_STATUS_KEY_GATES = 20

#: The floor `record_keys_compared` is asserted against. `record` emits four
#: keys — the finding, its reasons, and the two floors — so the sensitivity
#: comparison spans four or the comparison did not span the record. It is a
#: literal rather than `len(record(measure()))` on purpose: derived from the
#: live record it would move with the record and could never fail, which is
#: exactly how a `record` that quietly stopped emitting a key would slip a
#: vacuous zero past this denominator.
MINIMUM_RECORD_KEYS_COMPARED = 4

#: What `record` drops in favour of a floor, or drops outright. `readings` is
#: the per-task detail — one row per gate, regenerable by `--check`, read by
#: nothing — and it is the largest of the three: a merged task appends a row
#: to a hundred-and-twenty-six-line array in every other open PR's evidence.
_CENSUS_KEYS = ("evidence_gates_read", "gates_declaring_status_key", "readings")

#: The one key the sensitivity reading measures but does not commit. *Which*
#: gate was withheld is itself a function of the board's membership, so
#: recording it would reintroduce the drift the reading exists to detect.
_DIAGNOSTIC_ONLY = frozenset({"withheld_for_the_comparison"})

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
    withheld: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """D-12's gate reading: `unrecordable_task_gates`.

    `withheld` names task ids to read the board *without* — the seam
    `measure_board_sensitivity` uses to ask what this reading would say if the
    board's gate census were one gate different.
    """
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
        if task_id in withheld:
            continue
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


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The finding stays exact: `unrecordable_task_gates` and the reasons behind
    it are what D-12 asserts, and a change in either is a change in the code.
    The census goes — two counts become the floors they were checked against,
    and the per-task `readings` array becomes `--check` output. None of the
    three said anything about this repository that a merge of somebody else's
    task could not change.
    """
    committed = {key: value for key, value in measured.items() if key not in _CENSUS_KEYS}
    committed["evidence_gates_read_at_least"] = MINIMUM_GATES_READ
    committed["gates_declaring_status_key_at_least"] = MINIMUM_STATUS_KEY_GATES
    return committed


def sensitive_keys(live: dict[str, Any], perturbed: dict[str, Any]) -> list[str]:
    """Which committed keys disagree across the perturbation. Empty is the goal."""
    return sorted(key for key in live | perturbed if live.get(key) != perturbed.get(key))


def measure_board_sensitivity(
    tasks: Path = DEFAULT_TASKS_DIR,
    history: Path = DEFAULT_HISTORY_DIR,
    root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Whether the committed record survives the board's gate census changing.

    Not a test of the fix's shape but of its effect — T100's argument, on the
    axis that actually moves here. Withholding one gate is the same
    perturbation as another task PR merging and landing one: both change the
    census by one, and the record must not notice either.

    Withholding rather than adding, because the count is what moves and its
    direction is not the point; and because withholding needs no synthetic
    task file, so nothing about the comparison depends on a fixture the
    implementation could have been written around.

    `record_keys_compared` is the denominator: `record` could satisfy "the
    board changes nothing" by committing nothing at all, and a zero over an
    empty record is the vacuous pass this repository's gates exist to refuse.
    """
    live_measured = measure(tasks, history, root)
    readings = live_measured["readings"]
    # A gate that is already unrecordable is a finding, and withholding it
    # would move `unrecordable_task_gates` — a real difference reported as
    # drift. Take one the board can record.
    candidate = next(
        (r["task"] for r in readings if r["value_is_numeric"] or r["status_is_asserted"]),
        None,
    )
    if candidate is None:
        return {
            "board_sensitive_record_keys": 0,
            "record_keys_compared": 0,
            "board_sensitivity_status": "unmeasured",
            "board_sensitive": [],
            "withheld_for_the_comparison": None,
        }
    live = record(live_measured)
    perturbed = record(measure(tasks, history, root, frozenset({candidate})))
    sensitive = sensitive_keys(live, perturbed)
    return {
        "board_sensitive_record_keys": len(sensitive),
        "record_keys_compared": len(live | perturbed),
        "board_sensitivity_status": "measured",
        "board_sensitive": sensitive,
        "withheld_for_the_comparison": candidate,
    }


def floor_breaches(measured: dict[str, Any]) -> list[str]:
    """Which census counts came in under their floor. Empty is the pass.

    Read **before** the record is written, not after. `record` writes
    `evidence_gates_read_at_least: 100` unconditionally, so a five-gate board
    that writes first leaves an artefact asserting a floor the run never met —
    and that artefact is what the next healthy run's `make evidence` diffs
    against. Same repair, same day, as `plan_v2.floor_breaches`.
    """
    return [
        f"only {measured[name]} gate(s) counted for {name} (floor {floor}) — "
        "zero unrecordable gates over nothing is not a measurement"
        for name, floor in (
            ("evidence_gates_read", MINIMUM_GATES_READ),
            ("gates_declaring_status_key", MINIMUM_STATUS_KEY_GATES),
        )
        if measured[name] < floor
    ]


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    tasks: Path = DEFAULT_TASKS_DIR,
    history: Path = DEFAULT_HISTORY_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D12.json`.

    Returns what was *measured*, sensitivity reading included; writes what is
    *recorded*. `_main` still needs the live counts to check them against
    their floors, and the file must not carry them.

    A run that breaches either floor writes nothing at all: the only record it
    could write is one that claims the floors held.

    The same argument covers the sensitivity reading, and it is the reason the
    refusal is not just about floors. `_main` returns 1 for a board-sensitive
    record, so CI stops — but a written file stays on disk and becomes the
    baseline the next `make evidence` diffs against, so the failing artefact
    outlives the failing run. Two readings are refused:

    * `board_sensitive_record_keys` non-zero — the record's own values move when
      the board's gate census does, which is the single thing D-12's gate
      exists to refuse. Committing it commits the defect.
    * `record_keys_compared` under its floor, *when the comparison actually
      ran* — a zero over too few keys is a vacuous zero, and the artefact
      cannot tell that apart from a real one.

    An `unmeasured` sensitivity status keeps writing, deliberately: `make
    evidence` maps exit 3 to "unmeasured (recorded)" and carries on, so a run
    that could not compare must still leave the record it did measure.
    """
    measured = measure(tasks, history)
    sensitivity = measure_board_sensitivity(tasks, history)
    thin = (
        sensitivity["board_sensitivity_status"] == "measured"
        and sensitivity["record_keys_compared"] < MINIMUM_RECORD_KEYS_COMPARED
    )
    if floor_breaches(measured) or sensitivity["board_sensitive_record_keys"] or thin:
        return measured | sensitivity
    committed = record(measured) | {
        key: value for key, value in sensitivity.items() if key not in _DIAGNOSTIC_ONLY
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured | sensitivity


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

    if args.check:
        measured = measure() | measure_board_sensitivity()
    else:
        measured = write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured["unrecordable"]:
        print(reason, file=sys.stderr)
    if measured["unrecordable_task_gates"] == -1:
        return 3
    if measured["unrecordable_task_gates"]:
        return 1

    for key in measured["board_sensitive"]:
        print(
            f"✗ `{key}` changes when the board's gate census does — a committed value that "
            "moves on somebody else's merge goes stale on every other open PR at once",
            file=sys.stderr,
        )
    if measured["board_sensitive_record_keys"]:
        return 1

    # The floors, last: a real finding outranks a thin denominator, the same
    # precedence `naming` applies between a surviving reference and a short
    # sweep. They are *reported* last and *checked* first — `write_evidence`
    # reads the same `floor_breaches` before it writes anything.
    #
    # **Exit 1, not 3.** A breach here is a finding, not an absence of one: the
    # sweep ran, counted, and came back short. Exit 3 is the code `make
    # evidence` deliberately tolerates — `Makefile`'s `case` prints "unmeasured
    # (recorded)" and carries on — so returning it turned every floor into
    # advice. And a floor that only advises is worse than the census it
    # replaced: `record` writes `evidence_gates_read_at_least` unconditionally,
    # so a five-gate board produced a green `make evidence` with no drift to
    # notice, where the exact value it replaced produced a red one. The
    # artefact cannot tell those two boards apart by construction — that is the
    # point of a floor — so the exit code is what has to, and it must be one
    # `make evidence` treats as failure. Found by second-reader audit on #297.
    breaches = floor_breaches(measured)
    for breach in breaches:
        print(breach, file=sys.stderr)
    if breaches:
        return 1
    if measured["board_sensitivity_status"] != "measured":
        print(
            "board_sensitive_record_keys: UNMEASURED — no recordable gate to withhold, so "
            "nothing was compared. Not a pass and not a fail.",
            file=sys.stderr,
        )
        return 3
    # The sensitivity reading's own denominator, after the board's. Zero
    # sensitive keys over three keys compared is a smaller claim than zero over
    # four, and nothing else would say so.
    if measured["record_keys_compared"] < MINIMUM_RECORD_KEYS_COMPARED:
        print(
            f"only {measured['record_keys_compared']} record key(s) were compared "
            f"(floor {MINIMUM_RECORD_KEYS_COMPARED}) — `record` stopped committing "
            "something, and zero sensitive keys over a shrunken record is not the "
            "property this gate asserts",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
