#!/usr/bin/env python3
"""Assert that every task the board calls finished has evidence to show for it.

A terminal task — `done`, meaning "the PR is opened and the gate passed", or
`merged`, meaning that PR landed — is making a claim about a measurement.
Nothing enforced them after the fact: the orchestrator ran `gate_run.sh` once,
at release time, against the tree as it stood that minute. A later commit that
breaks an earlier task's gate leaves the board saying `done` and the evidence
saying otherwise, and no one finds out — the false-`done` hole, reopened by
time rather than by carelessness.

So this runs in CI, on every push, over the *whole* board:

1. **Every terminal task's declared gate still holds.** For each task with
   status `done` or `merged`, the payload's fenced ``gate`` block is asserted
   against its committed evidence file by `claude-arsenal/scripts/gate_evidence.py`
   — the same checker `gate_run.sh` uses, so CI and the release path speak one
   language rather than two that drift apart.

1b. **What counts as declaring a gate is the checker's own answer.** This file
   used to decide it from the substring ``` ```gate ``` anywhere in the payload
   while the checker read only the first fence inside the first
   ``## Acceptance gate`` *heading*'s section. Where the two disagreed the task
   was counted among "gate(s) asserted" and then checked by a reader that
   asserted nothing, so the asserted tally went **up** for a task whose evidence
   file was never opened — measured on #334 over `t-2a30f58a` and `t-246f6dde`,
   whose label was bold rather than a heading. One predicate now answers both
   questions (`integral.task_gate.gate_declaration`), a fence no reader reaches
   is a **failure** rather than a quieter tally, and a counted gate whose
   checker printed nothing is a failure too — the second is the end-to-end
   catch that survives any future drift between the two grammars.
   `status/evidence/T122.json` measures both, over this board and over a fixture
   per way a fence can be present and unread.

2. **An open task with no evidence is not a failure.** A task nobody has
   started legitimately has no measurement, and demanding one would make the
   whole board red from the first commit and stay that way — a check that is
   always failing is a check nobody reads. Terminal status is what turns a
   declared gate into a promise.

The complementary half — that committed evidence still matches what the code
*actually measures today*, rather than what it measured when it was written —
is `make evidence`, which regenerates every module's evidence and fails on any
diff. This file checks the numbers clear their thresholds; that one checks the
numbers are current. Neither subsumes the other: evidence can be perfectly
fresh and still fail its gate, and it can satisfy a gate while being months
stale.

Exit: 0 all terminal gates pass; 1 one or more fail; 2 the queue or a payload
could not be read (a broken board is not a green board).

The board moved when this repository migrated off the coordination-branch
queue (claude-arsenal v0.26.0). Finished tasks are no longer rows in
`tasks.jsonl`; they are entries in `arsenal/tasks/_migrated-history.md`, and
their payloads — the fenced ``gate`` blocks this tool asserts — are kept in
`arsenal/tasks/_history/` precisely so it still has something to check. The
migration itself does not preserve them: it records a finished task's id,
title and PR, and drops the payload that carried its gate. Keeping them is
what stops the move from silently retiring 51 assertions.

So `load_tasks` accepts either shape, dispatching on the file's suffix: a
`.jsonl` ledger for the old board, a `.md` history for the new one. Both
produce the same rows, and every test below drives whichever it needs.

`--queue` and `--payload-dir` default to this repository's board and exist so
the checker can be driven against a fixture. A verifier whose only input is the
real board can only ever be tested on a board that is already passing, which
is no test at all.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from integral.task_gate import gate_declaration
from integral.taskboard import load_board

_REPO_ROOT = Path(__file__).resolve().parents[1]
QUEUE_PATH = _REPO_ROOT / "arsenal" / "tasks"
PAYLOAD_DIR = _REPO_ROOT / "arsenal" / "tasks"
GATE_EVIDENCE = _REPO_ROOT / "claude-arsenal" / "scripts" / "gate_evidence.py"

# The two statuses that assert a gate was measured and passed. `escalated` and
# `blocked` are failure states and claim nothing; `open` has not been started.
TERMINAL = frozenset({"done", "merged"})


class VerifyError(Exception):
    """The board itself could not be read — distinct from a gate failing."""


def load_tasks(queue: Path) -> list[dict[str, object]]:
    """Every row of the board, or a raised error naming the bad line.

    Dispatches on shape so the old ledger and the new board are both readable:
    a directory of front-matter task files, or a JSONL ledger. A board that
    will not parse is reported rather than skipped — one reduced to the rows
    that happened to be readable would quietly stop checking whatever the
    broken entry described.
    """
    if not queue.exists():
        raise VerifyError(f"no queue at {queue}")
    if queue.is_dir():
        history = queue / "_history"
        rows, violations = load_board(queue, history if history.is_dir() else None)
        if violations:
            raise VerifyError("; ".join(violations))
        return [dict(row) for row in rows]
    rows: list[dict[str, object]] = []
    for number, line in enumerate(queue.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise VerifyError(f"{queue.name} line {number} is not valid JSON: {exc}") from exc
    return rows


# There is deliberately no local `declares_a_gate` any more. It was
# ``"```gate" in payload.read_text(...)`` — a second description of a grammar
# whose only implementation is `gate_evidence.py`'s regexes, and the gap
# between the two descriptions is T122. Rewriting it to delegate would leave
# the same shape: a predicate that `main` might or might not be the caller of,
# free to drift again the moment somebody adds a branch. `main` asks
# `gate_declaration` directly, and the fence is classified in exactly one place.


def check_payload(payload: Path) -> tuple[bool, str]:
    """Run the shared checker over one payload; `(passed, its output)`."""
    result = subprocess.run(
        [sys.executable, str(GATE_EVIDENCE), str(payload)],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=QUEUE_PATH)
    parser.add_argument("--payload-dir", type=Path, default=PAYLOAD_DIR)
    parser.add_argument(
        "--report-json",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "write what this run counted and what the checker actually read to PATH — "
            "the input `integral.gate_reader_agreement` measures T122's gate from"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse(sys.argv[1:] if argv is None else argv)
    try:
        rows = load_tasks(args.queue)
    except VerifyError as exc:
        print(f"verify-gates: {exc}", file=sys.stderr)
        return 2

    checked = 0
    ungated = 0
    compared = 0
    failures: list[str] = []
    unreadable: list[str] = []
    silently_unread: list[str] = []

    for row in rows:
        if row.get("status") not in TERMINAL:
            continue
        task_id = str(row.get("id", "?"))
        payload_name = str(row.get("payload") or f"{task_id}.md")
        payload = args.payload_dir / payload_name
        if not payload.exists():
            failures.append(f"{task_id}: recorded {row.get('status')} but has no payload file")
            continue
        compared += 1
        declaration = gate_declaration(payload.read_text(encoding="utf-8"))
        if declaration == "unreadable":
            # T122. Not the same thing as declaring no gate, and reporting it
            # as one is what let two terminal tasks sit in the "gate(s)
            # asserted" tally with their evidence files never opened. The
            # author wrote a gate; no reader reaches it; the honest verdict is
            # a refusal, not a quieter tally.
            unreadable.append(task_id)
            failures.append(
                f"{task_id} ({payload_name}): carries a ```gate fence that no reader reaches — "
                "the label must be a `## Acceptance gate` heading and the fence must sit "
                "inside that section, before the next `##`"
            )
            continue
        if declaration == "absent":
            ungated += 1
            continue
        passed, output = check_payload(payload)
        checked += 1
        if passed and not output.strip():
            # The end-to-end half of the same defect, and the one that survives
            # any future drift between this file's grammar and the checker's:
            # a gate counted as asserted whose checker printed nothing at all
            # was not asserted. `gate_evidence.py` exits 0 in exactly two
            # states — it read a block and the measurement cleared the
            # threshold (and says so on stdout), or it found no block and
            # returned silently. Only the second is mute.
            silently_unread.append(task_id)
            failures.append(
                f"{task_id} ({payload_name}): counted as asserting a gate, and the evidence "
                "checker read nothing — a silent pass is not a measurement"
            )
        elif not passed:
            reason = output.splitlines()[-1] if output else "gate check failed with no output"
            failures.append(f"{task_id} ({payload_name}): {reason}")

    terminal = sum(1 for row in rows if row.get("status") in TERMINAL)
    print(
        f"verify-gates: {terminal} terminal task(s); {checked} gate(s) asserted, "
        f"{ungated} carry no fenced gate block"
    )
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(
                {
                    "terminal": terminal,
                    "compared": compared,
                    "counted_as_asserted": checked,
                    "ungated": ungated,
                    "unreadable_fences": unreadable,
                    "counted_as_asserted_but_never_read": silently_unread,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    for failure in failures:
        print(f"  FAIL {failure}", file=sys.stderr)

    if failures:
        print(
            f"verify-gates: {len(failures)} terminal task(s) cannot show the measurement "
            "their status claims",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
