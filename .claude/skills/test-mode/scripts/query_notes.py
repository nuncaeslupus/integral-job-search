#!/usr/bin/env python3
"""query_notes.py — what test mode has captured, without leaving the session (S11).

Silent capture is the design: a note changes nothing in the conversation,
because a tool that acknowledged one would stop being the thing under test. The
cost is that a note mis-parsed, or eaten by the paste guard, is **invisible by
construction** — and the payload is explicit that a note which vanished quietly
is worse than one that interrupted.

So this is the window into the second channel. It reads the session's note
ledger and prints every note with the step it was made at and the skill it is
addressed in, plus the counts that separate "nothing was noted" from "something
was noted and lost": markers a paste guard declined, and markers that never
closed.

Everything it prints comes out of the ledger file, counters included. That
matters more than it looks: this runs in a different process from the session
that captured the notes, so anything the live channel kept in memory is gone by
the time the owner asks for the list. A count that does not survive the session
cannot audit it.

It is also the end-of-session pass. `--seed` takes the numbers the owner
confirmed and prints the `new_task.py` invocation for each — printed, never
run, because "seed only what was confirmed" has to be a decision a person makes
with the list in front of them.

Run via (from the repo root, with the project's dev environment):
    uv run python3 .claude/skills/test-mode/scripts/query_notes.py \
        --id <session-id> [--input-dir <profiles-root>] [--seed 1,3]

The profiles root defaults to the candidate store resolved from `$INTEGRAL_HOME`
(`jobsearch.state_home`), which refuses any path inside a git work tree —
candidate state never lives in the clone (T51, `docs/distribution.md` §2).

Exit codes: 0 the ledger was read; 1 notes were captured but something was also
lost to a guard or a typo (worth looking at before triage); 2 the ledger could
not be read at all.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from jobsearch.state_home import StateHomeRefused, profiles_root  # noqa: E402
from jobsearch.test_mode import (  # noqa: E402
    MetaNoteError,
    NoteLedger,
    build_review,
    ledger_path,
    render_review,
    seed_specs,
)


def _confirmed(raw: str | None) -> list[int]:
    if not raw:
        return []
    numbers = []
    for part in raw.replace(",", " ").split():
        try:
            numbers.append(int(part))
        except ValueError:
            print(f"query_notes: {part!r} is not a note number — ignored", file=sys.stderr)
    return numbers


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True, help="the test session's id")
    parser.add_argument(
        "--input-dir",
        default=None,
        help="profiles root (default: the candidate store from $INTEGRAL_HOME)",
    )
    # `--seed` is outside skill-creator's argument canon, deliberately: seeding
    # is this repository's own word for turning a finding into a queue task, and
    # the canon has no verb for it. `--apply` would be the nearest canonical
    # name and would be a lie — nothing is run here, the invocations are
    # printed for a person to read first (decision 4 of the S11 payload).
    parser.add_argument(
        "--seed",
        default=None,
        metavar="N[,N…]",
        help="print the queue-add invocation for these note numbers; nothing is run",
    )
    parser.add_argument("--json", action="store_true", help="print the review as JSON")
    args = parser.parse_args(argv[1:])

    try:
        root = Path(args.input_dir) if args.input_dir else profiles_root()
    except StateHomeRefused as exc:
        print(f"query_notes: {exc}", file=sys.stderr)
        return 2

    path = ledger_path(root, args.id)
    if not path.is_file():
        print(f"query_notes: no note ledger at {path}", file=sys.stderr)
        print("test mode — 0 note(s) captured\n  (none)")
        return 2

    try:
        review = build_review(NoteLedger(path))
    except MetaNoteError as exc:
        print(f"query_notes: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(review.model_dump(mode="json"), ensure_ascii=False, indent=2))
    else:
        print(render_review(review))

    confirmed = _confirmed(args.seed)
    if confirmed:
        print("\nSeed these — run each yourself, after reading it:")
        for spec in seed_specs(review, confirmed):
            print("  " + " ".join(repr(part) if " " in part else part for part in spec.command()))

    # A guard that ate a marker is not an error, but it is the one thing worth
    # noticing before triage: the note the owner thinks they made may not be in
    # the list they are about to confirm from.
    return 1 if (review.unparsed_markers or review.unclosed_markers) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
