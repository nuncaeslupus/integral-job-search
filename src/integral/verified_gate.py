"""Is the local substitute for CI still a substitute? (T121)

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

## What is counted, and why the zero hides nothing

`verified_gate_defects` is a sum, so every component is reported beside it by
name. A metric that reads 0 while a reader cannot see *which* properties were
checked is the shape this repository has now caught four times
(`status_is_asserted` T108, `incidental_duplicate_drops` #323,
`negation_recall_hits_by_mechanism` #318,
`robots_adjudications_without_a_competent_second_reader` T116).

- **`host_gate_targets_not_run`** — the drift guard. The script says
  `make host-gate` and nothing else, so it reaches whatever the aggregate
  reaches and this is 0 by delegation. Enumerating the targets in the script
  would be a second definition of the gate, free to fall behind the Makefile;
  that is exactly what D-22 was filed about. This counts what an enumerating
  edit would cost.
- **`missing_properties`** — the four claims that make a run *verified* rather
  than merely local: it resolves the ref to a commit, it checks that commit out
  detached, it clears bytecode, and its verdict names the SHA. Each is read from
  the script's own text.
- **`undocumented`** — `CLAUDE.md` must name the script where it tells a session
  how to merge without CI. Prose that names no script, and a script no prose
  names, are the two halves of D-22's original defect.

The denominator is a floor: `verified_gate_properties_at_least`. Zero defects
over a scan that found no properties is the vacuous pass this repository keeps
finding, and the floor is what refuses it.

**A grep is not a proof, and this docstring will not pretend otherwise.** These
checks read the script's text; they cannot tell you it *works*. That is
`tests/test_verified_gate.py`'s job, which runs the real script against a real
commit and asserts it reports the SHA it was given and fails a tree whose gate
fails. The two together are the argument; either alone is not.
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

# Read from the script's text, each with the reason it is load-bearing. Named
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
        "delegates to the aggregate target",
        r"make\s+host-gate",
        "a listed subset is a second definition of the gate, free to fall behind",
    ),
)

MINIMUM_PROPERTIES = len(REQUIRED_PROPERTIES)

_MAKE_TARGETS_RE = re.compile(r"\bmake\s+([a-z][a-z0-9-]*)")


def _script_targets(script: str) -> set[str]:
    """Every Make target the script invokes."""
    return set(_MAKE_TARGETS_RE.findall(script))


def host_gate_targets_not_run(
    script: str, makefile: Path = DEFAULT_MAKEFILE
) -> list[str]:
    """Targets the aggregate reaches that the script would not.

    Zero while the script delegates. An edit that replaces `make host-gate` with
    a listed subset makes this the size of what was dropped, which is the whole
    point of measuring it rather than trusting the delegation to survive.
    """
    invoked = _script_targets(script)
    if AGGREGATE_TARGET in invoked:
        return []
    reached = reached_from(AGGREGATE_TARGET, make_rules(makefile))
    return sorted(reached - invoked - {AGGREGATE_TARGET})


def missing_properties(script: str) -> list[str]:
    """The named claims the script's text no longer supports."""
    return [
        f"{name} — {why}"
        for name, pattern, why in REQUIRED_PROPERTIES
        if not re.search(pattern, script)
    ]


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
            "gate_status": "unmeasured",
            "host_gate_targets_not_run": [],
            "missing_properties": [],
            "undocumented": [],
        }
    script = script_path.read_text(encoding="utf-8")
    not_run = host_gate_targets_not_run(script, makefile)
    missing = missing_properties(script)
    undocumented = (
        []
        if instructions.exists()
        and is_documented(instructions.read_text(encoding="utf-8"), script_path)
        else [f"CLAUDE.md does not name {script_path.name}"]
    )
    checked = len(REQUIRED_PROPERTIES)
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
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """Write T121's gate evidence. Exit 1 while the substitute has a defect.

        python -m integral.verified_gate [evidence-path]
            [--script PATH] [--instructions PATH]
    """
    positional = [a for a in argv[1:] if not a.startswith("-")]

    def _flag(name: str, fallback: Path) -> Path:
        # `--script PATH` / `--instructions PATH`, the idiom `naming --repo`
        # uses: a measurement of another tree must be reachable, or the exit
        # path can only ever be tested by breaking this one.
        if name in argv[1:]:
            return Path(argv[argv.index(name) + 1])
        return fallback

    measured = write_evidence(
        Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH,
        script_path=_flag("--script", DEFAULT_SCRIPT_PATH),
        instructions=_flag("--instructions", DEFAULT_INSTRUCTIONS),
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
            f"verified-gate: {DEFAULT_SCRIPT_PATH.name} does not exist — the substitute "
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
