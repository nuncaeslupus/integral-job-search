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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

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

DEFAULT_T108_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T108.json"

#: T108's floors. `status_presence_fields_named_as_identity` is a metric named
#: after a **category** — T123's rule says such a metric is satisfiable by
#: there being none of them — so both its denominators are asserted rather
#: than reported. `emitted_fields_scanned` says the probe read a row at all;
#: `presence_recording_fields_scanned` says the row still carried fields of
#: the kind the metric ranges over. Today the emitted row carries six fields,
#: two of which record presence (`declares_status_key`, `status_key_resolves`),
#: and both floors sit at or just under those: unlike D-12's census these move
#: only when *this module's own* emitted row changes, which is a code change
#: somebody is already reading, never somebody else's task PR merging.
MINIMUM_EMITTED_FIELDS_SCANNED = 5
MINIMUM_PRESENCE_RECORDING_FIELDS = 2

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

#: The fence opener, and the whole of what `tools/verify_gates.py` used to
#: test for. T122: a substring is not a grammar. A payload can carry these
#: seven characters and still declare nothing any reader will read — the label
#: bolded rather than headed, the fence in a section the reader's regex has
#: already walked past, the string quoted inside a ``text`` block. Every one of
#: those counted as a gate and was then handed to a checker that extracted
#: nothing and exited 0, so the board's "gate(s) asserted" tally went *up* for
#: a task whose evidence file was never opened and was not required to exist.
GATE_FENCE = "```gate"


def gate_declaration(text: str) -> Literal["readable", "unreadable", "absent"]:
    """What a payload's gate fence amounts to, by the grammar that reads it.

    Three outcomes, because the two that a boolean conflates need different
    handling and it is their conflation that T122 is about:

    * ``readable`` — `parse_gate_block` extracts a block, so `gate_evidence.py`
      extracts the same one and asserts it. This is the only state in which a
      task may be counted among the gates a verifier asserted.
    * ``unreadable`` — the fence is *there* and no reader reaches it. Not an
      ungated task: an ungated task is a task whose author declared no gate,
      and this one declared one that nothing enforces. Reporting it as ungated
      is what let `t-2a30f58a` and `t-246f6dde` (#334) sit at terminal status
      with their evidence files never opened, so it is reported as a fault.
    * ``absent`` — no fence at all. `t-62612ae0` (T124) is the board's one
      honest case: an executable ``bash`` gate and no evidence block, which
      this layer has nothing to say about.

    The readable case is decided by `parse_gate_block` — the module comment
    above says why that is a *mirror* of `gate_evidence.py`'s regexes rather
    than an import of them, and a mirror is still two descriptions of one
    grammar. What T122 removes is the **third** description: `verify_gates.py`
    counting fences by substring while the checker read them by grammar. The
    remaining mirror is covered from the other end — a gate counted as
    asserted whose checker printed nothing is reported as a fault by
    `verify_gates.main`, which is a behavioural check that holds however far
    the two regex sets drift.
    """
    if parse_gate_block(text) is not None:
        return "readable"
    if GATE_FENCE in text:
        return "unreadable"
    return "absent"


@dataclass(frozen=True)
class Reading:
    """One task's evidence gate, and whether its measurement can be recorded.

    `status_key_resolves` was called `status_is_asserted` until T108, and the
    rename is the whole of that task. It records that the declared
    `status-key` **resolves to a non-empty string** — presence, not content —
    and `"measured"` satisfies it. Under the old name two independent reviews
    (#286, #290) read `status_is_asserted: true` as claiming the status *is*
    the word `asserted`, and both proposed setting it false because the
    evidence says `measured`; both were rejected, and the second one is what
    made the name the finding rather than the readers. The suggested change
    would also have made every status-only gate unrecordable, `recordable`
    being `value_is_numeric or status_key_resolves`.
    """

    task_id: str
    key: str
    evidence: str
    value_is_numeric: bool
    declares_status_key: bool
    status_key_resolves: bool
    reason: str = ""

    @property
    def recordable(self) -> bool:
        return self.value_is_numeric or self.status_key_resolves


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


def _emitted_row(reading: Reading) -> dict[str, Any]:
    """One reading as `measure` emits it.

    One function rather than a dict literal inside the comprehension, because
    T108's probe scans **the emitted row** and not the dataclass. Reading the
    dataclass would measure the field names a future `measure` might stop
    emitting, which is a different set from the one anybody reads out of
    `D12.json`.
    """
    return {
        "task": reading.task_id,
        "key": reading.key,
        "evidence": reading.evidence,
        "value_is_numeric": reading.value_is_numeric,
        "declares_status_key": reading.declares_status_key,
        "status_key_resolves": reading.status_key_resolves,
    }


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
        "readings": [_emitted_row(r) for r in sorted(readings, key=lambda r: r.task_id)],
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
        (r["task"] for r in readings if r["value_is_numeric"] or r["status_key_resolves"]),
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


# T108 — a field that records *presence* must not be named as a claim about
# *identity*. `<subject>_is_<claim>` is the grammar of an identity assertion:
# it binds the subject to the claim, which is exactly how two reviews coming
# to `D12.json` cold read `status_is_asserted: true` as "the status **is**
# `asserted`" and proposed setting it false because the evidence says
# `measured`. A field that records whether something is *there* has to be
# named with a verb of resolution or declaration — `resolves`, `declares_…`,
# `has_…` — because none of those can be read as the subject's value.
#
# `value_is_numeric` is the case the rule must NOT catch, and it is the reason
# the classification below is behavioural rather than a list of banned words:
# that field really does assert something about the value's content, so its
# `_is_` name is accurate and a keyword rule would have renamed it too.
#
# The rule above is **positive**, and it is applied positively. A denylist of
# copulas was the first attempt and is a fail-open filter: it passes every
# name that merely avoids four words, so `status_asserted` — the likeliest
# next name, and the one #286/#290 read exactly as they read the old one —
# scored clean. Second-reader finding F1 on #399. What the comment states is
# that a presence field must *carry* a verb of resolution or declaration, so a
# name carrying none is a finding, whatever else it avoids.
#
# The verbs are third-person present or `has`/`have` on purpose. A past
# participle — `asserted`, `resolved`, `declared` — is precisely the grammar
# that reads as the subject's value (`status_asserted` is "the status is
# asserted"), so admitting one would reopen the hole this closes.
_RESOLUTION_VERBS = frozenset(
    {
        "resolves",
        "declares",
        "has",
        "have",
        "carries",
        "records",
        "reports",
        "provides",
        "contains",
        "holds",
        "exists",
    }
)

# Retained *alongside* the positive rule, not instead of it: a name may carry a
# resolution verb and still be built as a copula (`status_is_resolved`), and
# that name is an identity claim however honest its verb. A field must pass
# both to count as honestly named.
_COPULA_RE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*_(?:is|are|was|were)_[a-z0-9]+(?:_[a-z0-9]+)*$")


def names_presence_honestly(name: str) -> bool:
    """Does `name` say it records *presence* rather than assert an identity?

    The positive half is the rule the comment above states — the name carries a
    verb of resolution or declaration. The negative half refuses a copula
    construction even when it does.
    """
    return bool(_RESOLUTION_VERBS & set(name.split("_"))) and not _COPULA_RE.match(name)


#: Absence, distinguishable from a `None` that is genuinely recorded.
_MISSING = object()

_PROBE_PAYLOAD = """---
id: probe-0001
title: "the synthetic gate T108 classifies the emitted row from"
priority: 5
---

## Acceptance gate

```gate
score >= 0.75
evidence: status/evidence/PROBE.json
key: score
{status_line}```
"""


def _write_probe(root: Path, *, value: object, status: object, declares: bool) -> Path:
    """One synthetic gate on disk, and the tasks directory holding it."""
    tasks = root / "arsenal" / "tasks"
    tasks.mkdir(parents=True)
    evidence = root / "status" / "evidence" / "PROBE.json"
    evidence.parent.mkdir(parents=True)
    data: dict[str, Any] = {}
    if value is not _MISSING:
        data["score"] = value
    if status is not _MISSING:
        data["score_status"] = status
    evidence.write_text(json.dumps(data), encoding="utf-8")
    tasks.joinpath("probe-0001.md").write_text(
        _PROBE_PAYLOAD.format(status_line="status-key: score_status\n" if declares else ""),
        encoding="utf-8",
    )
    return tasks


def _probe_row(root: Path, *, value: object, status: object, declares: bool) -> dict[str, Any]:
    """The emitted row for one synthetic gate, written to disk and read back.

    Synthetic and disposable deliberately. Classifying the live board's rows
    would make the record move whenever somebody else's task PR landed a gate
    — the drift `measure_board_sensitivity` exists to refuse, one axis over —
    and would make the classification depend on which gates the queue happens
    to hold today.
    """
    tasks = _write_probe(root, value=value, status=status, declares=declares)
    reading = read_gate("probe-0001", tasks / "probe-0001.md", root)
    return {} if reading is None else _emitted_row(reading)


def measure_emits_the_classified_row(root: Path) -> tuple[bool, list[str], list[str]]:
    """Does `measure` actually emit the row the classification above scans?

    `(they agree, what measure emits, what _emitted_row emits)`.

    Second-reader finding F2 on #399: the classification reads `_emitted_row`,
    and until this existed **nothing asserted that `measure` routes through
    it**. Reverting `measure` to the pre-T108 inline dict carrying
    `status_is_asserted` left the module emitting the exact defect T108 removes
    while the metric read zero and `--check` exited 0 — the gate green over the
    fault it was written for.

    Measured over the same synthetic board the probes use rather than the live
    one, for `_probe_row`'s reason: the live board's membership must not be
    able to move this reading.
    """
    tasks = _write_probe(root, value=5, status="measured", declares=True)
    # Positional, like every other call site: `measure` is looked up on the
    # module so a replacement of it is what this reading is about.
    measured = measure(tasks, root / "no-history", root)
    readings = measured["readings"]
    reference = sorted(_emitted_row(Reading("probe-0001", "score", "PROBE.json", True, True, True)))
    emitted = sorted(readings[0]) if readings else []
    return emitted == reference, emitted, reference


def classify_emitted_fields(
    present_a: dict[str, Any], present_b: dict[str, Any], absent: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """`(the presence-recording fields, those of them named as identity claims)`.

    A field records **presence** when its value is invariant across the two
    probes that differ only in the *content* of what the gate points at, and
    changes when that content is not there at all. Read off behaviour, never
    off the name: that is what lets the rule spare `value_is_numeric`, which
    flips between the two present probes and is therefore a claim about the
    value, while catching a field that answers the same in both and only
    notices the thing disappearing.
    """
    names = sorted(set(present_a) & set(present_b) & set(absent))
    presence = [
        name
        for name in names
        if all(isinstance(row[name], bool) for row in (present_a, present_b, absent))
        and present_a[name] == present_b[name]
        and present_a[name] != absent[name]
    ]
    return presence, [name for name in presence if not names_presence_honestly(name)]


def measure_field_naming() -> dict[str, Any]:
    """T108's gate reading: `status_presence_fields_named_as_identity`.

    Three probes over one synthetic gate. Two carry both a value and a status
    and differ only in what those *say* — `5`/`measured` against
    `"not a number"`/`pending`; the third carries neither and declares no
    `status-key` at all, so every presence a row could record is gone at once.
    """
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw)
        present_a = _probe_row(base / "a", value=5, status="measured", declares=True)
        present_b = _probe_row(base / "b", value="not a number", status="pending", declares=True)
        absent = _probe_row(base / "c", value=_MISSING, status=_MISSING, declares=False)
        agrees, measure_fields, classified_fields = measure_emits_the_classified_row(base / "d")

    names = sorted(set(present_a) & set(present_b) & set(absent))
    if not names:
        return {
            "status_presence_fields_named_as_identity": -1,
            "identity_named_presence_fields": [],
            "presence_recording_fields": [],
            "emitted_fields": [],
            "emitted_fields_scanned": 0,
            "presence_recording_fields_scanned": 0,
            "measure_fields_not_classified": [],
            "measure_emits_the_classified_row": agrees,
            "field_naming_status": "unmeasured",
            "field_naming_unmeasured_reason": (
                "the probe gate produced no emitted row, so no field was classified — "
                "not zero identity-named fields, no reading at all"
            ),
        }

    presence, identity = classify_emitted_fields(present_a, present_b, absent)
    return {
        "status_presence_fields_named_as_identity": len(identity),
        "identity_named_presence_fields": identity,
        "presence_recording_fields": presence,
        "emitted_fields": names,
        "emitted_fields_scanned": len(names),
        "presence_recording_fields_scanned": len(presence),
        # F2's finding, as a committed key: the fields `measure` really emits,
        # minus the ones the classification above ranges over. Non-empty means
        # the metric was scored over a row nobody reads.
        "measure_fields_not_classified": sorted(set(measure_fields) - set(classified_fields)),
        "measure_emits_the_classified_row": agrees,
        "field_naming_status": "measured",
    }


def field_naming_floor_breaches(measured: dict[str, Any]) -> list[str]:
    """Which of T108's two denominators came in short. Empty is the pass."""
    return [
        f"only {measured[name]} field(s) counted for {name} (floor {floor}) — "
        "a metric named after a category, verified over an empty category, is not a measurement"
        for name, floor in (
            ("emitted_fields_scanned", MINIMUM_EMITTED_FIELDS_SCANNED),
            ("presence_recording_fields_scanned", MINIMUM_PRESENCE_RECORDING_FIELDS),
        )
        if measured[name] < floor
    ]


def write_field_naming_evidence(
    evidence: Path = DEFAULT_T108_EVIDENCE_PATH, measured: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/T108.json`.

    A run that could not classify, or that came in under either floor, writes
    nothing at all — the only record it could write is one whose zero claims
    the rename holds over a population the run never found, and that file
    would become the baseline the next `make evidence` diffs against. Same
    refusal, same reason, as `write_evidence` above.
    """
    if measured is None:
        measured = measure_field_naming()
    if measured["field_naming_status"] != "measured" or field_naming_floor_breaches(measured):
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.task_gate [--check]`.

    Without arguments it writes both evidence files — D-12's and T108's — so
    `make evidence`, which invokes this module once like any other, regenerates
    both numbers with no flag to remember.

    Both records are written *before* either is adjudicated, and then the exit
    codes are taken in order. A finding in one gate must not stop the other
    from leaving the record it measured, or the file `make evidence` diffs
    against would depend on which gate failed first.
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
    parser.add_argument(
        "--write-t108-evidence",
        nargs="?",
        const=str(DEFAULT_T108_EVIDENCE_PATH),
        default=str(DEFAULT_T108_EVIDENCE_PATH),
        metavar="PATH",
        help="write T108's field-naming evidence to PATH (default: status/evidence/T108.json)",
    )
    args = parser.parse_args(argv[1:])

    if args.check:
        measured = measure() | measure_board_sensitivity()
        naming = measure_field_naming()
    else:
        measured = write_evidence(Path(args.write_evidence))
        naming = write_field_naming_evidence(Path(args.write_t108_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    print(json.dumps(naming, ensure_ascii=False))
    for reason in measured["unrecordable"]:
        print(reason, file=sys.stderr)
    for name in naming["identity_named_presence_fields"]:
        print(
            f"✗ `{name}` records whether something is *present* and is named as a claim about "
            "what it *is* — two reviews took `status_is_asserted: true` for a status equal to "
            "the word `asserted` and proposed setting it false",
            file=sys.stderr,
        )
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

    # T108, last, and by the same precedence: the finding first, its
    # denominators after. `write_field_naming_evidence` has already refused to
    # write anything a breach would have made false.
    if naming["field_naming_status"] != "measured":
        print(naming["field_naming_unmeasured_reason"], file=sys.stderr)
        return 3
    # Before the finding, the thing the finding is *about*. A classification of
    # a row `measure` does not emit is not a weaker reading of the board, it is
    # a reading of something else — so this is a failure and not a floor.
    if not naming["measure_emits_the_classified_row"]:
        print(
            "measure() does not emit the row T108 classifies — "
            f"fields measure emits and the classification never sees: "
            f"{naming['measure_fields_not_classified']}. The metric below was scored "
            "over `_emitted_row`, which nothing routes through.",
            file=sys.stderr,
        )
        return 1
    if naming["status_presence_fields_named_as_identity"]:
        return 1
    naming_breaches = field_naming_floor_breaches(naming)
    for breach in naming_breaches:
        print(breach, file=sys.stderr)
    if naming_breaches:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
