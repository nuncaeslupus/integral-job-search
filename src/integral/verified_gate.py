r"""Is the local substitute for CI still a substitute? (T121)

GitHub Actions ran out of monthly minutes on 2026-09-04, four days into the
billing period, and `merge-policy` is `after-ci-and-review`. `make host-gate`
runs exactly the four checks CI ran, so it is the obvious stand-in — but run in
a session's own checkout it answers a **weaker question**, and the difference is
the whole reason this module exists:

- CI measured the **pushed commit**. A local run measures the working tree,
  which can carry uncommitted edits, staged-but-uncommitted files, or a stale
  `.pyc` whose source was restored inside the same second (`CLAUDE.md`, "A
  reverted mutation can leave the mutated bytecode running").
- CI's verdict named the commit it tested. A local run's verdict is whatever the
  session says it is, and the tested-equals-merged property was checked by hand
  twice on 2026-09-04.

`tools/verified_gate.sh` closes both: it resolves the ref to a 40-character SHA,
checks that SHA into a throwaway detached worktree, runs the gate there, and
prints a block naming the commit measured. This module asserts the script still
does that, because a substitute nobody checks is how the thing it substitutes
for stops being done at all — which is D-22's subject, one layer out.

## Text is read from the script's CODE, never from its prose

Every property below is a claim about what the script *does*, so the patterns
are matched against `executable_text()` — the file with its comment-only lines
removed — and the load-bearing ones are anchored on a specific line rather than
on a string that could appear anywhere.

That is not a nicety. The first version of this module searched the whole file
for `make\s+host-gate`, which the script's own header comments contained twice.
Measured by the second-reader report on #333 (F1): a script whose run line said
`make lint`, and a script with the gate line deleted and `status=0` hard-coded
so every verdict printed PASS, **both** scored `verified_gate_defects == 0`.
`host_gate_targets_not_run` was documented as the drift guard and counted
nothing, because the aggregate's name was already in the comments.

## What is counted, and why the zero hides nothing

`verified_gate_defects` is a sum, so every component is reported beside it by
name. A metric that reads 0 while a reader cannot see *which* properties were
checked is the shape this repository has now caught four times
(`status_is_asserted` T108, `incidental_duplicate_drops` #323,
`negation_recall_hits_by_mechanism` #318,
`robots_adjudications_without_a_competent_second_reader` T116).

- **`host_gate_targets_not_run`** — the drift guard. The script delegates to the
  aggregate and lists no targets, so it reaches whatever the aggregate reaches
  and this is 0. Enumerating the targets in the script would be a second
  definition of the gate, free to fall behind the Makefile; that is exactly what
  D-22 was filed about. This counts what an enumerating edit would cost.
- **`missing_properties`** — the named claims that make a run *verified* rather
  than merely local, each read from the script's code.
- **`undocumented`** — `CLAUDE.md` must name the script where it tells a session
  how to merge without CI. Prose that names no script, and a script no prose
  names, are the two halves of D-22's original defect.

The denominator is a floor: `verified_gate_properties_at_least`. Zero defects
over a scan that found no properties is the vacuous pass this repository keeps
finding, and the floor is what refuses it — **as a literal**, the way
`naming.MINIMUM_SCANNED` is one. It read `len(REQUIRED_PROPERTIES)` while the
number it guarded read `len(REQUIRED_PROPERTIES)` too, so the guard compared an
expression to itself, the floor could never fire, and deleting entries from the
table shrank both sides together (#333, F3).

**A grep is not a proof, and this docstring will not pretend otherwise.** These
checks read the script's text; they cannot tell you it *works*. That is
`tests/test_verified_gate.py`'s job, which runs the real script against a real
commit — including against a throwaway repo that has an `origin`, because the
remote-resolution path is where the no-argument form used to measure origin's
default branch and report PASS (#333, F2). The two together are the argument;
either alone is not.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from integral.repo_gate import AGGREGATE_TARGET, make_rules, reached_from

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCRIPT_PATH = _REPO_ROOT / "tools" / "verified_gate.sh"
DEFAULT_INSTRUCTIONS = _REPO_ROOT / "CLAUDE.md"
DEFAULT_MAKEFILE = _REPO_ROOT / "Makefile"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T121.json"

_COMMENT_LINE_RE = re.compile(r"^\s*#")


def executable_text(script: str) -> str:
    """The script with its comment-only lines removed.

    A comment saying `make host-gate` is prose *about* the script, not something
    the script does, and satisfying a property from prose is how this checker
    came to report zero defects over a script that ran `make lint` (#333, F1).
    """
    return "\n".join(
        line for line in script.splitlines() if not _COMMENT_LINE_RE.match(line)
    )


# Read from the script's CODE, each with the reason it is load-bearing. Named
# rather than numbered so a failure says which property is gone.
REQUIRED_PROPERTIES: tuple[tuple[str, str, str], ...] = (
    (
        "resolves the ref to a commit",
        r"rev-parse\s+--verify",
        "a ref is a moving target; a SHA is the thing that gets merged",
    ),
    (
        "checks it out detached, away from the caller's tree",
        r"worktree\s+add\s+--detach",
        "the working tree is not what a reviewer merges",
    ),
    (
        "clears bytecode",
        r"__pycache__",
        "a stale .pyc can make a restored source run mutated code",
    ),
    (
        "names the measured commit in its verdict",
        r"commit\s+\$\{sha\}",
        "a verdict that does not say what it measured cannot be checked later",
    ),
    (
        "delegates to the aggregate target, in one assignment",
        r"(?m)^gate_command=\"make host-gate\"\s*$",
        "a listed subset is a second definition of the gate, free to fall behind; "
        "anchored on the assignment because the bare string matched two comments",
    ),
    (
        "runs that command, in the checked-out tree",
        r"cd\s+\"\$\{tree\}\"\s*&&\s*\$\{gate_command\}",
        "declaring the command and running something else is #333's mutation 1: "
        "`make lint` at this line scored zero defects",
    ),
    (
        "reports the command it actually ran",
        r"command\s+\$\{gate_command\}",
        "the block printed the aggregate's name unconditionally, so a script "
        "running `make lint` pasted a verdict claiming it ran the aggregate",
    ),
    (
        "never asks the remote for `HEAD`",
        r"\[\s*\"\$\{ref\}\"\s*!=\s*\"HEAD\"\s*\]",
        "`git fetch origin HEAD` succeeds and returns origin's DEFAULT BRANCH, so "
        "the no-argument form measured `main` and printed PASS (#333, F2)",
    ),
    (
        "says where the SHA was resolved from",
        r"resolved\s+\$\{resolved_from\}",
        "a fetch that fails falls back to the local ref; the block must not go on "
        "claiming `the pushed commit` for one (#333, F2b)",
    ),
    (
        "says whether the commit is on origin",
        r"on origin\s+\$\{pushed\}",
        "a PASS pasted for a commit nobody can fetch is not evidence about a merge",
    ),
    (
        "ends the fetch's options before the ref",
        r"fetch\s+--quiet\s+origin\s+--\s",
        "a ref beginning with `-` is otherwise parsed by `git fetch` as an option",
    ),
    (
        "prunes the worktree registration on exit",
        r"worktree\s+prune",
        "`worktree remove` failing leaves both the directory and the "
        "`.git/worktrees/` entry behind, and only the happy path was covered",
    ),
)

#: A literal, on purpose — `naming.MINIMUM_SCANNED`'s form, and for its reason.
#: Written as `len(REQUIRED_PROPERTIES)` it was compared at the guard below
#: against `len(REQUIRED_PROPERTIES)`, so the floor was `x < x`: unreachable,
#: and deleting half the table moved both sides together. #333, F3. Raise this
#: when the table grows; `test_the_floor_is_a_literal_the_table_cannot_drag`
#: refuses a table that has shrunk below it.
MINIMUM_PROPERTIES = 12

_MAKE_TARGETS_RE = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)")


def _script_targets(script: str) -> set[str]:
    """Every Make target the script's CODE invokes.

    Comment-only lines are dropped first: a header sentence naming the aggregate
    target used to be enough to satisfy the delegation check below on its own.
    """
    return set(_MAKE_TARGETS_RE.findall(executable_text(script)))


def host_gate_targets_not_run(
    script: str, makefile: Path = DEFAULT_MAKEFILE
) -> list[str]:
    """Targets the aggregate reaches that the script would not.

    Zero while the script delegates. An edit that replaces the delegation with a
    listed subset makes this the size of what was dropped, which is the whole
    point of measuring it rather than trusting the delegation to survive.
    """
    invoked = _script_targets(script)
    if AGGREGATE_TARGET in invoked:
        return []
    reached = reached_from(AGGREGATE_TARGET, make_rules(makefile))
    return sorted(reached - invoked - {AGGREGATE_TARGET})


def evaluate_properties(script: str) -> tuple[list[str], int]:
    """`(the claims the script's code no longer supports, how many were tried)`.

    The second element is produced by this loop, not by `len(REQUIRED_PROPERTIES)`
    — that is what makes it independent of the floor it is compared against. A
    script with no executable line at all evaluates nothing, and reporting zero
    defects over that is the vacuous pass the floor exists to refuse.
    """
    text = executable_text(script)
    if not text.strip():
        return [], 0
    missing: list[str] = []
    evaluated = 0
    for name, pattern, why in REQUIRED_PROPERTIES:
        evaluated += 1
        if not re.search(pattern, text):
            missing.append(f"{name} — {why}")
    return missing, evaluated


def missing_properties(script: str) -> list[str]:
    """The named claims the script's code no longer supports."""
    return evaluate_properties(script)[0]


def is_documented(instructions: str, script_path: Path = DEFAULT_SCRIPT_PATH) -> bool:
    """Does `CLAUDE.md` name the script?

    One direction only, and deliberately shallow: asserting that the prose
    *describes* it correctly is not something a regex can do, and a check that
    pretends to would be worse than none.
    """
    return script_path.name in instructions


def measure(
    script_path: Path = DEFAULT_SCRIPT_PATH,
    instructions: Path = DEFAULT_INSTRUCTIONS,
    makefile: Path = DEFAULT_MAKEFILE,
) -> dict[str, Any]:
    """Count the ways the local substitute has stopped substituting."""
    if not script_path.exists():
        return {
            "verified_gate_defects": -1,
            "verified_gate_properties_checked": 0,
            "verified_gate_properties_at_least": MINIMUM_PROPERTIES,
            # `measured`, not `unmeasured`: the check RAN and its answer is "the
            # script is gone". `unmeasured` is this repository's word for a check
            # that cannot be scored yet, it is signalled by exit 3, and
            # `make evidence` records it and CONTINUES — so writing it here said,
            # in the repo's own vocabulary, the opposite of what `_main` decided
            # (it returns 1). #333, F5.
            "gate_status": "measured",
            "host_gate_targets_not_run": [],
            "missing_properties": [],
            "undocumented": [],
        }
    script = script_path.read_text(encoding="utf-8")
    not_run = host_gate_targets_not_run(script, makefile)
    missing, checked = evaluate_properties(script)
    undocumented = (
        []
        if instructions.exists()
        and is_documented(instructions.read_text(encoding="utf-8"), script_path)
        else [f"CLAUDE.md does not name {script_path.name}"]
    )
    return {
        "verified_gate_defects": len(not_run) + len(missing) + len(undocumented),
        "verified_gate_properties_checked": checked,
        "verified_gate_properties_at_least": MINIMUM_PROPERTIES,
        "gate_status": "measured" if checked else "unmeasured",
        "host_gate_targets_not_run": not_run,
        "missing_properties": missing,
        "undocumented": undocumented,
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    script_path: Path = DEFAULT_SCRIPT_PATH,
    instructions: Path = DEFAULT_INSTRUCTIONS,
    makefile: Path = DEFAULT_MAKEFILE,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T121.json`."""
    measured = measure(script_path, instructions, makefile)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _take_flag(args: list[str], name: str) -> tuple[list[str], Path | None, bool]:
    """Remove `name` **and its value** from `args`.

    `naming.py` does exactly this before computing its positionals, and the
    comment here used to claim that idiom while the code filtered only tokens
    beginning with `-`. So `--script /path/x.sh` left `/path/x.sh` standing as
    the first positional, which is the EVIDENCE PATH — and the documented
    invocation overwrote the script it was pointed at with 230 bytes of JSON,
    rc 0, no warning. Measured on #333, F4.

    Returns `(remaining, value, ok)`; `ok` is False for a trailing flag with no
    value, which used to raise `IndexError`.
    """
    if name not in args:
        return args, None, True
    index = args.index(name)
    if index + 1 >= len(args):
        return args, None, False
    return args[:index] + args[index + 2 :], Path(args[index + 1]), True


def _main(argv: list[str]) -> int:
    """Write T121's gate evidence. Exit 1 while the substitute has a defect.

        python -m integral.verified_gate [evidence-path]
            [--script PATH] [--instructions PATH]

    Naming a script or an instructions file other than this repository's makes
    the evidence path default to *nothing*: a measurement of some other tree is
    not evidence about this repository, so it is printed and not recorded unless
    the caller also said where. `naming --repo` sets that precedent, and this
    followed only the half of it that let the exit path be tested.
    """
    args = list(argv[1:])
    args, script_value, ok = _take_flag(args, "--script")
    if not ok:
        print("verified-gate: --script needs a path", file=sys.stderr)
        return 2
    args, instructions_value, ok = _take_flag(args, "--instructions")
    if not ok:
        print("verified-gate: --instructions needs a path", file=sys.stderr)
        return 2

    own_tree = script_value is None and instructions_value is None
    script_path = script_value if script_value is not None else DEFAULT_SCRIPT_PATH
    instructions = (
        instructions_value if instructions_value is not None else DEFAULT_INSTRUCTIONS
    )

    positional = [a for a in args if not a.startswith("-")]
    default_target = DEFAULT_EVIDENCE_PATH if own_tree else None
    target: Path | None = Path(positional[0]) if positional else default_target

    measured = (
        measure(script_path, instructions)
        if target is None
        else write_evidence(target, script_path=script_path, instructions=instructions)
    )
    for key in ("host_gate_targets_not_run", "missing_properties", "undocumented"):
        for item in measured[key]:
            print(f"✗ {key}: {item}", file=sys.stderr)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["verified_gate_defects"] > 0:
        return 1
    # The floor last and below the finding, the precedence `naming` sets: a real
    # defect outranks a thin denominator. -1 is "the script is gone", which is
    # the maximal defect and not an honest "cannot measure yet" — so it fails
    # rather than reporting unmeasured.
    if measured["verified_gate_defects"] < 0:
        print(
            f"verified-gate: {script_path.name} does not exist — the substitute "
            "CLAUDE.md tells sessions to merge on is missing entirely",
            file=sys.stderr,
        )
        return 1
    if measured["verified_gate_properties_checked"] < MINIMUM_PROPERTIES:
        print(
            f"verified_gate_properties_checked: {measured['verified_gate_properties_checked']} "
            f"is below the floor of {MINIMUM_PROPERTIES} — zero defects over that few "
            "properties is not a measurement",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
