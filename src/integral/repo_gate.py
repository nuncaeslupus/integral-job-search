"""D-22 — the gate the docs require must have something that runs it.

`CLAUDE.md` says all five must pass before a merge — lint, test, evidence,
verify-subtree, verify-gates. Nothing ran them. PR #89 fell through three holes
at once: GitHub Actions has had no runner minutes since 2026-08-19 (so `ci.yml`
enforces nothing today), `open_task_pr.sh` re-runs the *payload* gate and never
asks whether the repo gate passed, and `keyword-guard` only fires on
`arsenal/**` branches. The five ran on #89 because a person asked, and `make
test` then failed on nine violations that would otherwise have merged.

Prose is not an enforcement point. This module measures whether each gate the
docs require has one.

**What counts as an enforcement point.** Two things, and the second is the one
that rots. A required gate must be a real, runnable Make target — and it must
be reached by the repo's aggregate gate, so that one command runs all five. A
gate the aggregate has forgotten is the failure this exists to catch: somebody
adds a sixth line to `CLAUDE.md` and the target nobody wired up is the one
nobody runs.

**What this module does not claim.** The worker half is upstream's
(`claude-arsenal#175`): `open_task_pr.sh` re-runs `gate_run.sh` on the payload
and never runs the host's repo gate, so a worker can still open a green task PR
that breaks `make test`. Editing the vendored script here would be overwritten
by the next subtree upgrade and would fail `make verify-subtree` in the
meantime. What the host can do — and now does — is *have* the enforcement point
under the name upstream's `host-gate` key expects, so the hook has something
real to call the day it lands. `payload_gate_is_not_the_repo_gate` records that
the two are still distinct here, which is what made the confusion possible.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-22.json"
DEFAULT_MAKEFILE = _REPO_ROOT / "Makefile"
DEFAULT_INSTRUCTIONS = _REPO_ROOT / "CLAUDE.md"

#: The target that runs the whole repo gate in one command. Named for the key
#: `claude-arsenal` points a worker at, not for what CI happens to call it.
AGGREGATE_TARGET = "host-gate"

#: The target that records T1's lint exit code. Deliberately *not* the repo
#: gate: it is one check, and treating it as the gate is exactly how "the
#: payload gate ran" came to read as "the repo gate ran".
PAYLOAD_TARGET = "gate"

# The sentence in CLAUDE.md that makes the five a requirement rather than a
# suggestion. Measured, so that deleting the requirement records `-1` instead
# of a clean `0` — a check that outlives its rule enforces a policy the project
# has dropped while looking like a pass.
_REQUIREMENT_RE = re.compile(r"all\s+five\s+must\s*\n?\s*pass\s+before\s+a\s+merge", re.I)

# `make <target>` lines inside a fenced block — how CLAUDE.md states the list.
_MAKE_COMMAND_RE = re.compile(r"^\s*make\s+([a-z][a-z0-9-]*)\s*(?:#.*)?$", re.M)

# A Makefile rule: `name: deps  ## help`. Only the first colon matters.
_RULE_RE = re.compile(r"^([a-z][a-z0-9-]*)\s*:(?!=)([^\n#]*)", re.M)


@dataclass(frozen=True)
class Reading:
    """One required gate, and whether anything runs it."""

    target: str
    is_a_target: bool
    reached_by_aggregate: bool
    reasons: tuple[str, ...]

    @property
    def enforced(self) -> bool:
        return self.is_a_target and self.reached_by_aggregate


def required_gates(instructions: Path = DEFAULT_INSTRUCTIONS) -> list[str]:
    """The `make` targets the instructions require before a merge, in order."""
    text = instructions.read_text(encoding="utf-8")
    return list(dict.fromkeys(_MAKE_COMMAND_RE.findall(text)))


def requirement_is_declared(instructions: Path = DEFAULT_INSTRUCTIONS) -> bool:
    """Do the instructions still require the gate before a merge?"""
    try:
        return bool(_REQUIREMENT_RE.search(instructions.read_text(encoding="utf-8")))
    except OSError:
        return False


def make_rules(makefile: Path = DEFAULT_MAKEFILE) -> dict[str, tuple[str, ...]]:
    """Every Make target and its direct prerequisites."""
    text = makefile.read_text(encoding="utf-8")
    rules: dict[str, tuple[str, ...]] = {}
    for name, deps in _RULE_RE.findall(text):
        if name == "PHONY":
            continue
        rules.setdefault(name, tuple(deps.split()))
    return rules


def reached_from(target: str, rules: dict[str, tuple[str, ...]]) -> set[str]:
    """Every target `target` reaches, transitively.

    Transitive on purpose: `ci` depends on `host-gate` rather than repeating
    its five, and a check that only looked one level down would call that
    arrangement broken and push the project back to two lists that drift.
    """
    seen: set[str] = set()
    stack = [target]
    while stack:
        current = stack.pop()
        for dep in rules.get(current, ()):
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def read_gate(target: str, rules: dict[str, tuple[str, ...]]) -> Reading:
    """Whether one required gate has something that runs it."""
    reasons = []
    is_a_target = target in rules
    if not is_a_target:
        reasons.append(f"`make {target}` is required but no such target exists")
    # The aggregate is reached by running the aggregate. Without this the
    # instructions could not name `make host-gate` as one of the things to
    # run — which is the whole point of having it — without the check calling
    # it unenforced.
    reached = target == AGGREGATE_TARGET or target in reached_from(AGGREGATE_TARGET, rules)
    if is_a_target and not reached:
        reasons.append(
            f"`make {target}` exists but `make {AGGREGATE_TARGET}` does not reach it — "
            "the one command that is supposed to run the gate would skip it"
        )
    return Reading(target, is_a_target, reached, tuple(reasons))


def payload_gate_is_not_the_repo_gate(rules: dict[str, tuple[str, ...]]) -> bool:
    """Is the repo gate strictly more than the payload gate?

    Hole 2 of D-22: a worker re-runs its payload gate and nothing runs the
    repo suite, so a green task PR can break `make test`. The two must stay
    distinguishable — if `host-gate` ever collapsed to what `gate` does, the
    distinction that makes that hole visible would be gone.
    """
    repo = reached_from(AGGREGATE_TARGET, rules)
    payload = reached_from(PAYLOAD_TARGET, rules) | {PAYLOAD_TARGET}
    return bool(repo - payload)


def _unmeasured(reason: str, readings: list[Reading]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "required_gates_with_no_enforcement_point": -1,
        "gates_required": len(readings),
        "aggregate_target": AGGREGATE_TARGET,
        "requirement_declared": False,
        "payload_gate_is_not_the_repo_gate": False,
        "unenforced": [reason],
        "readings": [
            {
                "target": r.target,
                "is_a_target": r.is_a_target,
                "reached_by_aggregate": r.reached_by_aggregate,
                "reasons": list(r.reasons),
            }
            for r in readings
        ],
    }


def measure(
    instructions: Path = DEFAULT_INSTRUCTIONS, makefile: Path = DEFAULT_MAKEFILE
) -> dict[str, Any]:
    """D-22's gate reading: `required_gates_with_no_enforcement_point`."""
    try:
        rules = make_rules(makefile)
    except OSError as exc:
        return _unmeasured(f"{makefile.name} could not be read: {exc}", [])
    try:
        required = required_gates(instructions)
    except OSError as exc:
        return _unmeasured(f"{instructions.name} could not be read: {exc}", [])

    if not requirement_is_declared(instructions):
        return _unmeasured(
            f"{instructions.name} no longer says the gate must pass before a merge, so this "
            "check is not measuring the requirement D-22 names",
            [],
        )
    if not required:
        # Not zero: with no required gates parsed there is nothing to enforce,
        # and reporting a clean pass would say "everything the docs require is
        # enforced" on the strength of having found nothing they require.
        return _unmeasured(
            f"{instructions.name} declares the requirement but names no `make` targets — "
            "the list could not be read",
            [],
        )
    if AGGREGATE_TARGET not in rules:
        return _unmeasured(
            f"no `{AGGREGATE_TARGET}` target — there is no one command that runs the gate, "
            "so nothing to check the required list against",
            [read_gate(target, rules) for target in required],
        )

    readings = [read_gate(target, rules) for target in required]
    unenforced = [r for r in readings if not r.enforced]
    return {
        "required_gates_with_no_enforcement_point": len(unenforced),
        "gates_required": len(readings),
        "aggregate_target": AGGREGATE_TARGET,
        "requirement_declared": True,
        "payload_gate_is_not_the_repo_gate": payload_gate_is_not_the_repo_gate(rules),
        "unenforced": [reason for r in unenforced for reason in r.reasons],
        "readings": [
            {
                "target": r.target,
                "is_a_target": r.is_a_target,
                "reached_by_aggregate": r.reached_by_aggregate,
                "reasons": list(r.reasons),
            }
            for r in readings
        ],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    instructions: Path = DEFAULT_INSTRUCTIONS,
    makefile: Path = DEFAULT_MAKEFILE,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-22.json`."""
    measured = measure(instructions, makefile)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.repo_gate [--check]`.

    Without arguments it writes the evidence file, so `make evidence` — whose
    module list is derived from `^def _main` — regenerates D-22's number with
    no flag to remember.
    """
    parser = argparse.ArgumentParser(
        description="D-22's gate: every gate the docs require has something that runs it"
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
        help="write evidence JSON to PATH (default: status/evidence/D-22.json)",
    )
    args = parser.parse_args(argv[1:])

    measured = measure() if args.check else write_evidence(Path(args.write_evidence))
    print(json.dumps(measured, ensure_ascii=False))
    for reason in measured["unenforced"]:
        print(reason, file=sys.stderr)
    if measured["required_gates_with_no_enforcement_point"] == -1:
        return 3
    return 1 if measured["required_gates_with_no_enforcement_point"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
