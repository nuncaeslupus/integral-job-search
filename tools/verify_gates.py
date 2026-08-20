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


def declares_a_gate(payload: Path) -> bool:
    """Whether the payload carries a fenced ``gate`` block.

    The fence is what makes a gate mechanical — prose describing a threshold,
    or one in single backticks, is not checked by anything. A payload without
    the block has nothing for this tool to assert.
    """
    return "```gate" in payload.read_text(encoding="utf-8")


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
    failures: list[str] = []

    for row in rows:
        if row.get("status") not in TERMINAL:
            continue
        task_id = str(row.get("id", "?"))
        payload_name = str(row.get("payload") or f"{task_id}.md")
        payload = args.payload_dir / payload_name
        if not payload.exists():
            failures.append(f"{task_id}: recorded {row.get('status')} but has no payload file")
            continue
        if not declares_a_gate(payload):
            ungated += 1
            continue
        passed, output = check_payload(payload)
        checked += 1
        if not passed:
            reason = output.splitlines()[-1] if output else "gate check failed with no output"
            failures.append(f"{task_id} ({payload_name}): {reason}")

    terminal = sum(1 for row in rows if row.get("status") in TERMINAL)
    print(
        f"verify-gates: {terminal} terminal task(s); {checked} gate(s) asserted, "
        f"{ungated} carry no fenced gate block"
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
