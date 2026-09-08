"""T122 — a gate counted as asserted that the evidence reader never read.

Two readers used to decide whether a task file declares a gate, by different
rules. `claude-arsenal/scripts/gate_evidence.py` — the checker that actually
asserts the number — finds the first ``## Acceptance gate`` **heading**, and
searches only that section for a fenced ``gate`` block. `tools/verify_gates.py`
decided it from the substring ``` ```gate ``` anywhere in the payload.

Where the two disagreed the task was counted among "gate(s) asserted" and then
handed to a checker that extracted nothing and exited 0 — so the count of
asserted gates went **up**, and the board looked healthier for a task whose
evidence file was never opened and was not required to exist. Measured on #334:
`t-2a30f58a` (T118) and `t-246f6dde` (D-29) wrote their label as
``**Acceptance gate**`` — bold text, not a heading — and passed that way. Both
were repaired there; the gap that let them through was not, and the next task
file writing the label in bold falls into it.

**The metric counts the divergence, not the fences.** `gates_counted_as_asserted_but_never_read`
is, over every payload compared, the number the verifier counted as asserting a
gate and the checker did not read. A repository with no gates at all scores zero
on it, which is why `gates_compared_at_least` is asserted beside it as a floor
(T100's precedent: a count committed exactly moves on every task PR).

**Measured behaviourally, and that is the whole design.** This module does not
compare the two grammars — comparing two descriptions of one grammar is the
defect one level up, and a fix could satisfy such a check by making both
descriptions equally wrong. It **runs `tools/verify_gates.py`**:

* over the real board, reading its `--report-json`;
* over a fixture per way a fence can be present and unread, each declaring an
  evidence file that **does not exist**.

That last condition is what makes the fixtures unfakeable. A gate the checker
genuinely reads cannot pass with its evidence file missing, so for a fixture the
two possible outcomes are: the run goes red (the gate was read), or the run goes
green while claiming it asserted a gate (the gate was counted and never read).
The second is the divergence, and it is read from the run's own exit status
rather than from a counter the run could hard-code.

The controls are the other half. `second_fence_after_the_first` and
`label_in_a_later_section` both declare gates that the checker's grammar **does**
reach, so they must go red; `readable_gates_the_verifier_stopped_asserting`
counts the ones that did not. Without it the primary metric is satisfiable by a
verifier that counts nothing at all — zero divergence over zero gates asserted,
the vacuous pass this repository keeps finding — and no fixture would notice.

`no_fence_at_all` is the third shape and has the third finding to itself,
`ungated_tasks_refused_as_faulty`. The board's one honestly ungated terminal
task is `t-62612ae0` (T124) — an executable ``bash`` gate with no evidence
block — and a verifier that reported *it* as a fault would be wrong in the
direction this fix must not overshoot into. It is a finding of its own rather
than a row filed under the guard above, because a payload with no fence
declares no *readable* gate either: counting it there would put it under a
name that does not describe it, which is the mistake T108 and T123 are both
about.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T122.json"
DEFAULT_VERIFIER = _REPO_ROOT / "tools" / "verify_gates.py"
DEFAULT_TASKS_DIR = _REPO_ROOT / "arsenal" / "tasks"

#: The floor `gates_compared` is asserted against, and what the record carries
#: in its place. The live comparison spans the board's terminal tasks — a
#: hundred and sixty-six today — plus one payload per arrangement below. It is
#: a floor for T100's reason: committed as an exact value it would move every
#: time *another* task PR merged, because a merge archives one more terminal
#: task, and every other open PR's T122 would go stale on somebody else's
#: merge. A hundred and fifty sits under today's total with room for the queue
#: to shed a workspace, and far enough above the arrangements alone that a run
#: which lost the board entirely cannot clear it.
MINIMUM_GATES_COMPARED = 150

#: The floor `arrangements_probed` is asserted against — one per way a fence
#: can be present and unread, plus the controls and the ungated shape. Unlike
#: the board census this moves only when *this module's own* fixture set
#: changes, which is a code change somebody is already reading. It is what
#: stops a clean zero that was reached by deleting the fixtures.
MINIMUM_ARRANGEMENTS_PROBED = 7

_FRONT_MATTER = """---
id: {task_id}
title: "{title}"
priority: 5
status: merged
---
"""

#: The block every arrangement declares. Its `evidence:` path is deliberately
#: one this repository does not have and must never acquire, so a checker that
#: reads the block **must** fail: CA-12's rule is that a declared gate cannot pass
#: without its evidence file. A green run over one of these is therefore proof
#: the block was never read, taken from the exit status rather than from any
#: number the run reports about itself.
_GATE_BLOCK = """```gate
fixture_metric == 0
evidence: status/evidence/absent-fixture.json
key: fixture_metric
```"""


@dataclass(frozen=True)
class Arrangement:
    """One way a ``gate`` fence can sit in a payload, and what must happen to it.

    `carries_a_readable_gate` is asserted from the **specification of the
    checker's grammar** — the first ``gate`` fence inside the first
    ``## Acceptance gate`` heading's section — never from what either reader
    currently returns. Deciding it by running the code is the circularity these
    fixtures exist to break.
    """

    name: str
    body: str
    carries_a_readable_gate: bool
    why: str


ARRANGEMENTS: tuple[Arrangement, ...] = (
    Arrangement(
        name="bold_label",
        body=(
            "The label is bold text, not a heading.\n\n**Acceptance gate**\n\n" + _GATE_BLOCK + "\n"
        ),
        carries_a_readable_gate=False,
        why=(
            "`##\\s+Acceptance gate` matches a heading; `**Acceptance gate**` is not one, "
            "so the checker finds no section and reads no block. The #334 case, verbatim."
        ),
    ),
    Arrangement(
        name="no_section_heading_at_all",
        body="A payload with a fence and no `##` heading anywhere.\n\n" + _GATE_BLOCK + "\n",
        carries_a_readable_gate=False,
        why="With no `## Acceptance gate` heading there is no section to search.",
    ),
    Arrangement(
        name="fence_after_the_section_ends",
        body=(
            "## Acceptance gate\n\n"
            "Prose only — the fence is below, under the next heading.\n\n"
            "## Notes\n\n" + _GATE_BLOCK + "\n"
        ),
        carries_a_readable_gate=False,
        why=(
            "The section ends at the next `##`, so a fence under `## Notes` is outside it. "
            "The lookahead `(?=\\n##\\s|\\Z)` is what bounds it."
        ),
    ),
    Arrangement(
        name="fence_above_the_heading",
        body=(
            "## Overview\n\n" + _GATE_BLOCK + "\n\n"
            "## Acceptance gate\n\n"
            "The heading is here; the fence was above it.\n"
        ),
        carries_a_readable_gate=False,
        why=(
            "The search starts at the heading and runs forward, so a fence earlier in the "
            "file is never in the section's span."
        ),
    ),
    Arrangement(
        name="fence_quoted_in_prose_only",
        body=(
            "## Acceptance gate\n\n"
            "This task documents the grammar rather than declaring a gate: a block\n"
            "opens with ```gate on its own line. No fence is closed and no block is\n"
            "declared.\n"
        ),
        carries_a_readable_gate=False,
        why=(
            "`_BLOCK_RE` requires ```` ```gate ```` followed by a newline and a closing "
            "fence; a mention inside a sentence closes nothing, so no block is extracted."
        ),
    ),
    Arrangement(
        name="second_fence_after_the_first",
        body=(
            "## Acceptance gate\n\n" + _GATE_BLOCK + "\n\n"
            "## Appendix\n\n"
            "```gate\nsecond_metric == 0\nevidence: status/evidence/absent-second.json\n"
            "key: second_metric\n```\n"
        ),
        carries_a_readable_gate=True,
        why=(
            "CONTROL. The first fence is inside the section and is the one the checker "
            "reads; a second fence elsewhere does not unmake it."
        ),
    ),
    Arrangement(
        name="label_in_a_later_section",
        body=(
            "## Why this exists\n\nA long preamble.\n\n## Acceptance gate\n\n" + _GATE_BLOCK + "\n"
        ),
        carries_a_readable_gate=True,
        why=(
            "CONTROL. The heading search is unanchored, so a section that appears after "
            "others is found exactly as a first section is."
        ),
    ),
)

#: The shape that is neither: no fence anywhere, which is the board's one
#: honestly ungated terminal task. Probed separately because a verifier that
#: reported it as a fault would be wrong in the direction the fix must not
#: overshoot into.
UNGATED_ARRANGEMENT = Arrangement(
    name="no_fence_at_all",
    body="## Acceptance gate\n\n```bash\nuv run pytest -q\n```\n",
    carries_a_readable_gate=False,
    why="`t-62612ae0`'s shape: an executable gate, no evidence block, nothing to assert.",
)


@dataclass(frozen=True)
class Probe:
    """One arrangement run end to end through `tools/verify_gates.py`."""

    name: str
    counted_as_asserted: int
    exit_status: int
    reported_ungated: int
    reported_never_read: int

    @property
    def green(self) -> bool:
        return self.exit_status == 0

    @property
    def counted_but_never_read(self) -> bool:
        """Counted a gate the checker did not read, by either of two signals.

        **What the run says.** `verify_gates.py` counts a gate it asserted
        whose checker printed nothing at all, which is the only state in which
        `gate_evidence.py` exits 0 without having read a block.

        **What the run did.** Counted a gate, and still returned green over an
        evidence file that does not exist. A checker that read the block would
        have failed on the absent file, so green-while-counting is the same
        divergence with nothing else it can be.

        Either alone is insufficient, and that is why both are read. The first
        is a number the verifier reports about itself, so a verifier that
        hard-coded it empty would clear it — the second is its exit status over
        a fixture built to make a real assertion fail, which it cannot fake
        without also failing the controls. The second, on its own, misses a
        verifier that has drifted back to a substring rule and *reports* the
        drift honestly: the divergence is real, the run is red about it, and
        only the first signal names it.
        """
        if self.reported_never_read:
            return True
        return self.counted_as_asserted > 0 and self.green

    @property
    def stopped_asserting(self) -> bool:
        """A gate the grammar requires be read, and the run did not read it."""
        return self.counted_as_asserted == 0 or self.green


def _write_fixture(root: Path, arrangement: Arrangement) -> Path:
    """A throwaway one-task board carrying just this arrangement."""
    tasks = root / "arsenal" / "tasks"
    tasks.mkdir(parents=True, exist_ok=True)
    task_id = f"t-{arrangement.name}"
    payload = tasks / f"{task_id}.md"
    payload.write_text(
        _FRONT_MATTER.format(task_id=task_id, title=f"T122 fixture: {arrangement.name}")
        + "\n"
        + arrangement.body,
        encoding="utf-8",
    )
    return tasks


def run_verifier(
    queue: Path, cwd: Path, verifier: Path = DEFAULT_VERIFIER
) -> tuple[int, dict[str, Any]]:
    """Run the verifier over `queue` from `cwd`; its exit status and its report.

    `cwd` holds only the report file. It is deliberately **not** what makes a
    fixture's evidence file absent: `verify_gates.check_payload` runs the
    checker with `cwd` pinned to the repository root, so a declared
    `evidence:` path resolves there whatever directory this call is made from.
    What makes it absent is the path itself — `status/evidence/absent-fixture.json`
    is a file this repository does not have and must never acquire, which is
    why the name says so.
    """
    report = cwd / "verify-gates-report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(verifier),
            "--queue",
            str(queue),
            "--payload-dir",
            str(queue),
            "--report-json",
            str(report),
        ],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if not report.is_file():
        raise RuntimeError(
            f"{verifier.name} wrote no report over {queue}: "
            f"exit {result.returncode}; {(result.stdout + result.stderr).strip()[:400]}"
        )
    payload: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    return result.returncode, payload


def probe(arrangement: Arrangement, verifier: Path = DEFAULT_VERIFIER) -> Probe:
    """Run one arrangement end to end in a tree that holds no evidence file."""
    with tempfile.TemporaryDirectory(prefix="t122-") as tmp:
        root = Path(tmp)
        queue = _write_fixture(root, arrangement)
        status, report = run_verifier(queue, root, verifier)
    return Probe(
        name=arrangement.name,
        counted_as_asserted=int(report["counted_as_asserted"]),
        exit_status=status,
        reported_ungated=int(report["ungated"]),
        reported_never_read=len(report["counted_as_asserted_but_never_read"]),
    )


def _unmeasured(reason: str) -> dict[str, Any]:
    return {
        "gates_counted_as_asserted_but_never_read": -1,
        "readable_gates_the_verifier_stopped_asserting": -1,
        "ungated_tasks_refused_as_faulty": -1,
        "divergent": [],
        "stopped_asserting": [],
        "refused_as_faulty": [],
        "gates_compared": 0,
        "arrangements_probed": [],
        "gate_reader_agreement_status": "unmeasured",
        "unmeasured_reason": reason,
    }


def measure(
    tasks: Path = DEFAULT_TASKS_DIR,
    verifier: Path = DEFAULT_VERIFIER,
    arrangements: tuple[Arrangement, ...] = ARRANGEMENTS,
) -> dict[str, Any]:
    """T122's reading: the board, then a probe per arrangement.

    The board half is the verifier's own report of what it counted and what the
    checker read — the only place that pairing exists, because the checker runs
    inside the verifier. The fixture half is the end-to-end probe, which is
    what keeps the board half honest: a verifier that hard-coded an empty
    `counted_as_asserted_but_never_read` would still go green over
    `bold_label`, and a verifier that counted nothing would still fail the two
    controls.
    """
    if not verifier.is_file():
        return _unmeasured(f"no verifier at {verifier}")
    if not tasks.is_dir():
        return _unmeasured(f"no task tree at {tasks}")

    with tempfile.TemporaryDirectory(prefix="t122-board-") as tmp:
        report_path = Path(tmp) / "board.json"
        subprocess.run(
            [
                sys.executable,
                str(verifier),
                "--queue",
                str(tasks),
                "--payload-dir",
                str(tasks),
                "--report-json",
                str(report_path),
            ],
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        if not report_path.is_file():
            return _unmeasured(f"{verifier.name} wrote no report over {tasks}")
        board: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))

    probes = [probe(arrangement, verifier) for arrangement in arrangements]
    probes.append(probe(UNGATED_ARRANGEMENT, verifier))
    by_name = {item.name: item for item in probes}

    divergent = [f"board:{task_id}" for task_id in board["counted_as_asserted_but_never_read"]]
    stopped: list[str] = []
    for arrangement in arrangements:
        item = by_name[arrangement.name]
        if arrangement.carries_a_readable_gate:
            if item.stopped_asserting:
                stopped.append(arrangement.name)
        elif item.counted_but_never_read:
            divergent.append(arrangement.name)

    # The other direction, and its own finding rather than a line filed under
    # the guard above: a payload with no fence at all declares no *readable*
    # gate either, so counting it there would put it under a name that does
    # not describe it — the mistake T108 and T123 are both about. A task whose
    # author declared nothing must be reported as carrying no fence, not
    # refused as faulty.
    ungated_probe = by_name[UNGATED_ARRANGEMENT.name]
    over_reach = [UNGATED_ARRANGEMENT.name] if ungated_probe.reported_ungated != 1 else []

    compared = int(board["compared"]) + len(probes)
    return {
        "gates_counted_as_asserted_but_never_read": len(divergent),
        "readable_gates_the_verifier_stopped_asserting": len(stopped),
        "ungated_tasks_refused_as_faulty": len(over_reach),
        "divergent": sorted(divergent),
        "stopped_asserting": sorted(stopped),
        "refused_as_faulty": sorted(over_reach),
        "gates_compared": compared,
        "arrangements_probed": sorted(item.name for item in probes),
        "gate_reader_agreement_status": "measured",
    }


def floor_breaches(measured: dict[str, Any]) -> list[str]:
    """Which denominators came in under their floor. Empty is the pass.

    Read **before** the record is written, for `task_gate.floor_breaches`'s
    reason: `record` writes the floors unconditionally, so a thin run that
    wrote first would leave an artefact asserting a floor the run never met —
    and that artefact is what the next healthy run's `make evidence` diffs
    against.
    """
    breaches = []
    if measured["gates_compared"] < MINIMUM_GATES_COMPARED:
        breaches.append(
            f"only {measured['gates_compared']} payload(s) compared "
            f"(floor {MINIMUM_GATES_COMPARED}) — zero divergences over an empty scan "
            "is not a measurement"
        )
    probed = len(measured["arrangements_probed"])
    if probed < MINIMUM_ARRANGEMENTS_PROBED:
        breaches.append(
            f"only {probed} arrangement(s) probed (floor {MINIMUM_ARRANGEMENTS_PROBED}) — "
            "a clean zero reached by deleting the fixtures is the defect, not the fix"
        )
    return breaches


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed: the findings, and the floors in place of the censuses.

    `gates_compared` is dropped for the floor because it moves on every task PR
    — a merge archives one more terminal task — and a record that moves on
    somebody else's merge goes stale in every other open PR at once (T100).
    `arrangements_probed` is kept in full: it is this module's own fixture set,
    it moves only when this file does, and naming it is what makes deleting a
    fixture visible in the diff rather than only in a count.
    """
    committed = {
        key: value
        for key, value in measured.items()
        if key not in {"gates_compared", "arrangements_probed"}
    }
    committed["gates_compared_at_least"] = MINIMUM_GATES_COMPARED
    committed["arrangements_probed"] = measured["arrangements_probed"]
    return committed


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    tasks: Path = DEFAULT_TASKS_DIR,
    verifier: Path = DEFAULT_VERIFIER,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T122.json`; return what was measured.

    A run that breaches a floor writes nothing at all: the only record it could
    write is one whose committed floors claim they held.
    """
    measured = measure(tasks, verifier)
    if floor_breaches(measured):
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    """`python -m integral.gate_reader_agreement [--check]`."""
    parser = argparse.ArgumentParser(
        description="T122's gate: a gate counted as asserted is a gate the checker read"
    )
    parser.add_argument(
        "--check", action="store_true", help="measure and report only; write no evidence file"
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/T122.json)",
    )
    args = parser.parse_args([] if argv is None else argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for breach in floor_breaches(measured):
        print(f"gate_reader_agreement: {breach}", file=sys.stderr)
    for name in measured["divergent"]:
        print(
            f"✗ {name}: counted as asserting a gate the evidence checker never read",
            file=sys.stderr,
        )
    for name in measured["stopped_asserting"]:
        print(
            f"✗ {name}: declares a gate the grammar reaches, and it was not asserted",
            file=sys.stderr,
        )
    for name in measured["refused_as_faulty"]:
        print(
            f"✗ {name}: declares no gate at all, and was refused as though it had",
            file=sys.stderr,
        )

    if measured["gate_reader_agreement_status"] == "unmeasured":
        return 3
    if floor_breaches(measured):
        return 1
    if measured["gates_counted_as_asserted_but_never_read"]:
        return 1
    if measured["readable_gates_the_verifier_stopped_asserting"]:
        return 1
    if measured["ungated_tasks_refused_as_faulty"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
