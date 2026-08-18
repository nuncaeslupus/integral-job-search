#!/usr/bin/env python3
"""run_checkpoint.py — step 10 (Feedback) coverage checkpoint (S7).

Reads one candidate's session state (T35) and profile tree (T34) and reports whether
step `feedback`'s *machine-visible* half of its stop rule is met: every artefact it
produces is present, and the session's recorded position for this step carries nothing
outstanding. See `status/spec-v2-steps.md`, step 10, for the full stop rule —
most of it is conversational and cannot be read from a file; this checks only the half
a file can answer.

This is **not** the step's acceptance gate. `feedback_traceability == 1.0`,
owned by T21, measures something this script does not attempt, and is
written by that task's own evidence writer — never fabricated here. Writing this step's
number into that task's evidence file would let `jobsearch.step_gates` report a task as
implemented when it is not, which is exactly the false-`done` failure the project's own
queue protocol exists to prevent. So this script writes its own, separate file.

Run via (from the repo root, with the project's dev environment):
    uv run python3 .claude/skills/step-10-feedback/scripts/run_checkpoint.py \
        --id <handle> [--input-dir <profiles-root>] [--dev]

The profiles root defaults to the candidate store resolved from `$INTEGRAL_HOME`
(`jobsearch.state_home`), which refuses any path inside a git work tree — candidate
state never lives in the clone (T51, `docs/distribution.md` §2).

Exit codes: 0 the step's machine-visible coverage is met; 1 it is not (still open, or
blocked on a missing input); 2 the candidate or step could not be read at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from jobsearch.identity import IdentityError, ProfileStore  # noqa: E402
from jobsearch.process_spec import Step, StepList, load_steps  # noqa: E402
from jobsearch.session import SessionError, SessionStore  # noqa: E402
from jobsearch.state_home import (  # noqa: E402
    StateHomeRefused,
    ensure_outside_a_work_tree,
    profiles_root,
)
from jobsearch.step_runtime import (  # noqa: E402
    ProfileView,
    is_finished,
    missing_inputs,
    present_artefacts,
    sufficiency,
)

# This script's step, by id in status/spec-v2-steps.json — read from there on every
# run (below), never restated as a copy of its gate/reads/produces that could drift.
STEP_ID = "feedback"


class CheckpointError(Exception):
    """The checkpoint could not be computed."""


def _this_step(steps: StepList) -> Step:
    for candidate in steps.steps:
        if candidate.id == STEP_ID:
            return candidate
    raise CheckpointError(f"{STEP_ID!r} is no longer in the step list")


def checkpoint(profiles_root: Path, handle: str) -> dict[str, Any]:
    """This candidate's machine-visible coverage state for `feedback` — computed, not asserted."""
    steps = load_steps()
    step = _this_step(steps)
    store = ProfileStore(profiles_root, handle)
    if not store.path("identity.json").is_file():
        raise CheckpointError(f"no profile at {store.home}")

    view = ProfileView(store)
    present = present_artefacts(view, steps)
    missing = missing_inputs(step, present)
    finished = is_finished(step, present)

    session = SessionStore(store).read()
    on_this_step = bool(session and session.current_step == STEP_ID)
    outstanding = list(session.position.outstanding) if on_this_step else []
    started = bool(
        session
        and (on_this_step or finished or STEP_ID in session.pending_steps)
    )
    coverage_met = finished and not outstanding

    result: dict[str, Any] = {
        "step": STEP_ID,
        "n": step.n,
        "required": step.required,
        "runnable": not missing,
        "missing_inputs": list(missing),
        "produces": list(step.produces),
        "artefacts_present": finished,
        "position_outstanding": outstanding,
        "started": started,
        "coverage_met": coverage_met,
        "sufficiency": sufficiency(view, steps),
        "gate_metric": f"{step.gate.metric} {step.gate.op} {step.gate.threshold}",
        "gate_owner": step.gate.task,
        "gate_state": step.gate.state,
        "note": (
            "coverage_met is the machine-visible half of the stop rule — every produced "
            "artefact present and nothing left outstanding in the recorded position. "
            f"It is not the {step.gate.metric} gate, which {step.gate.task} owns and "
            "measures separately."
        ),
    }
    store.write_json(result, "session", f"checkpoint-{STEP_ID}.json")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, dest="handle", help="the candidate's resolved handle")
    parser.add_argument(
        "--input-dir",
        default=None,
        help=(
            "root of the profiles tree (default: the store resolved from "
            "$INTEGRAL_HOME). A path inside a git work tree is refused here too, "
            "with --dev as the only way past (T51)"
        ),
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="the explicit escape: allow a store inside a git work tree (INTEGRAL_DEV=1)",
    )
    args = parser.parse_args(argv)

    dev = True if args.dev else None
    try:
        # An explicitly supplied root goes through the same containment rule as
        # a resolved one. Taking `--input-dir` as a bare `Path` let a profiles
        # directory inside the clone through without `--dev`, which is the one
        # thing T51 exists to stop — an escape that only guards one of the two
        # ways in is not an escape.
        root = (
            ensure_outside_a_work_tree(args.input_dir, source="--input-dir", dev=dev)
            if args.input_dir
            else profiles_root(dev=dev)
        )
    except StateHomeRefused as exc:
        print(f"checkpoint could not be computed: {exc}", file=sys.stderr)
        return 2

    try:
        result = checkpoint(root, args.handle)
    except (CheckpointError, IdentityError, SessionError) as exc:
        print(f"checkpoint could not be computed: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(result, ensure_ascii=False))
    if not result["runnable"]:
        print(f"{STEP_ID} is not runnable: missing {result['missing_inputs']}", file=sys.stderr)
        return 1
    return 0 if result["coverage_met"] else 1


if __name__ == "__main__":
    sys.exit(main())
