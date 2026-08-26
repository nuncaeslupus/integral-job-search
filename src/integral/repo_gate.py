"""D-22 — the gate the docs require must have something that runs it.

`CLAUDE.md` says all four must pass before a merge — lint, test, evidence and
verify-gates. Nothing ran them. PR #89 fell through three holes
at once: GitHub Actions has had no runner minutes since 2026-08-19 (so `ci.yml`
enforces nothing today), `open_task_pr.sh` re-runs the *payload* gate and never
asks whether the repo gate passed, and `keyword-guard` only fires on
`arsenal/**` branches. They ran on #89 because a person asked, and `make
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

**T85 lives here too, beside D-22, not replacing it.** `make evidence` derives
its module list by grepping `src/integral/*.py` for a naming convention on the
entry-point function — first `^def _main`, and three modules
(`plan_v2`, `process_spec`, `step_specs`) that define `main` instead were
invisible to it, so their evidence never regenerated and never drift-checked.
Renaming those three would only rebuild the trap for the next module that
defines `main`. `evidence_writing_modules` fixes the *selection*: it statically
reads each module's source for a path expression it constructs under
`status/evidence/`, which does not care what the function that builds that
path is called — and never imports the module to find out, since nothing in
this package may execute arbitrary contributed code (PR #77). `measure_evidence_reach`
is the same assertion `measure` makes for D-22, one level down: not just "does
every required gate have an enforcement point" but "does the one command that
regenerates evidence actually reach every module that produces it".
"""

from __future__ import annotations

import argparse
import ast
import itertools
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-22.json"
DEFAULT_T85_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T85.json"
DEFAULT_MAKEFILE = _REPO_ROOT / "Makefile"
DEFAULT_INSTRUCTIONS = _REPO_ROOT / "CLAUDE.md"
DEFAULT_SRC_DIR = _REPO_ROOT / "src" / "integral"

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
# The count word is not pinned. It used to read "all five", which meant every
# change to the list had to edit this regex as well — and the count carries no
# weight here anyway: what a target is checked against is the fenced block below
# the sentence, target by target, and an unwired one is caught there. This
# sentence only answers "is the requirement still declared at all".
_REQUIREMENT_RE = re.compile(r"all\s+\w+\s+must\s*\n?\s*pass\s+before\s+a\s+merge", re.I)

# `make <target>` lines inside a fenced block — how CLAUDE.md states the list.
_MAKE_COMMAND_RE = re.compile(r"^\s*make\s+([a-z][a-z0-9-]*)\s*(?:#.*)?$", re.M)

# The fenced block that follows the requirement. Only that block is the list:
# scanning the whole file would promote any other `make …` the instructions
# happen to show — `make reader-steps`, `make arsenal-upgrade` — into a gate
# required before every merge, and then demand `host-gate` reach it.
_FENCE_RE = re.compile(r"^```[^\n]*\n(?P<inner>.*?)^```", re.M | re.S)

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
    """The `make` targets the instructions require before a merge, in order.

    Scoped to the fenced block the requirement introduces, not the whole file.
    A `make` command shown anywhere else is an instruction about something
    else, and treating it as a merge gate would fail this check over a target
    nobody ever claimed belonged to the gate.
    """
    text = instructions.read_text(encoding="utf-8")
    requirement = _REQUIREMENT_RE.search(text)
    if requirement is None:
        return []
    block = _FENCE_RE.search(text, requirement.end())
    if block is None:
        return []
    return list(dict.fromkeys(_MAKE_COMMAND_RE.findall(block.group("inner"))))


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


# ---------------------------------------------------------------------------
# T85 — the evidence run reaches every module that writes evidence


def _slash_chain_string_parts(node: ast.AST) -> list[str]:
    """The literal string segments of a `/`-joined path expression, in order.

    Handles `_REPO_ROOT / "status" / "evidence" / "x.json"` (each `/` a
    `BinOp`, `_REPO_ROOT` contributing nothing since it is not a literal) and
    `Path("status/evidence/x.json")` (one string, split on `/`) — both forms
    are in real use here — plus any mix of the two. A part of the chain that
    is neither just drops out rather than breaking the scan, since it never
    carries the two literals this is looking for anyway.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _slash_chain_string_parts(node.left) + _slash_chain_string_parts(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split("/")
    if isinstance(node, ast.Call) and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.split("/")
    return []


def _names_status_evidence_path(node: ast.AST) -> bool:
    parts = _slash_chain_string_parts(node)
    return any(a == "status" and b == "evidence" for a, b in itertools.pairwise(parts))


def _writes_evidence(source: str) -> bool:
    """Does this module's source construct a path under `status/evidence/`?

    Parsed statically, never imported: nothing in this package may execute
    arbitrary module code, `test_nothing_in_the_codebase_executes_a_contributed_parse_module`
    holds that line for the whole tree, and evidence discovery is not an
    exception to it. Any assignment whose right-hand side names such a path —
    see `_slash_chain_string_parts` — counts, regardless of what the constant
    or the function around it is called; a module that writes evidence
    through a function named `main`, `_main`, `write_cycle_evidence`, or
    anything else is found the same way. That is what
    `test_the_selection_does_not_depend_on_a_private_name_convention` asserts
    directly.
    """
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
            continue
        if _names_status_evidence_path(node.value):
            return True
    return False


def evidence_writing_modules(src_dir: Path = DEFAULT_SRC_DIR) -> list[str]:
    """Every `src/integral/*.py` module that writes to `status/evidence/`.

    Found by reading each module's source and checking `_writes_evidence` —
    the ground truth this file's own T85 gate is measured against, and what
    `make evidence` now asks for through `--list-evidence-modules` instead of
    grepping for a private naming convention.
    """
    names = []
    for path in sorted(src_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        if _writes_evidence(path.read_text(encoding="utf-8")):
            names.append(path.stem)
    return names


# The `evidence` target's header line, then its tab-indented recipe body.
_EVIDENCE_TARGET_RE = re.compile(r"^evidence:[^\n]*\n(?P<body>(?:\t[^\n]*\n?)+)", re.M)

# The module-list command inside `for m in $$(...); do` — read, not assumed,
# so a fixture Makefile carrying the old `grep '^def _main'` selection is
# exercised exactly as it would run, and a future rewrite of the target is
# checked against what it actually says rather than what this module expects.
_MODULE_LIST_CMD_RE = re.compile(r"for m in \$\$\((?P<cmd>.*?)\)\s*;\s*do", re.S)


def evidence_run_module_list_command(makefile: Path = DEFAULT_MAKEFILE) -> str:
    """The shell command the `evidence` target's `for` loop iterates over."""
    text = makefile.read_text(encoding="utf-8")
    target = _EVIDENCE_TARGET_RE.search(text)
    if target is None:
        raise ValueError(f"no `evidence` target in {makefile}")
    command = _MODULE_LIST_CMD_RE.search(target.group("body"))
    if command is None:
        raise ValueError(f"`evidence` target in {makefile} has no `for m in $$(...)` module list")
    # `$$` is Make's escape for a literal `$` inside a recipe; a real shell
    # never sees the doubled form.
    return command.group("cmd").replace("$$", "$")


def modules_reached_by_evidence_run(
    makefile: Path = DEFAULT_MAKEFILE, repo_root: Path = _REPO_ROOT
) -> set[str]:
    """Which modules `make evidence` actually iterates — run for real, not parsed.

    The command can be an arbitrary shell pipeline (today: `uv run python -m
    integral.repo_gate --list-evidence-modules`; before this task, a `grep`/
    `sed`/`xargs` chain keyed on a function name). Running it is the only way
    to know its result without re-encoding its logic a second time here.
    """
    command = evidence_run_module_list_command(makefile)
    result = subprocess.run(
        ["bash", "-c", command], cwd=repo_root, capture_output=True, text=True, check=True
    )
    return {name for name in result.stdout.split() if name}


def measure_evidence_reach(
    makefile: Path = DEFAULT_MAKEFILE,
    src_dir: Path = DEFAULT_SRC_DIR,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """T85's gate reading: `gate_modules_outside_the_evidence_run`.

    A zero count over zero evaluated modules is not a pass — it is what a
    check that never ran also reports — so `gate_modules_discovered` (the
    denominator) is asserted alongside it, and `gate_status` reads
    `"unmeasured"` rather than a clean pass while that denominator is empty.
    """
    discovered = evidence_writing_modules(src_dir)
    evaluated = len(discovered)
    if evaluated == 0:
        return {
            "gate_modules_outside_the_evidence_run": 0,
            "gate_modules_outside_the_evidence_run_evaluated": 0,
            "gate_modules_discovered": 0,
            "modules_missing": [],
            "gate_status": "unmeasured",
        }
    reached = modules_reached_by_evidence_run(makefile, repo_root)
    missing = sorted(set(discovered) - reached)
    return {
        "gate_modules_outside_the_evidence_run": len(missing),
        "gate_modules_outside_the_evidence_run_evaluated": evaluated,
        "gate_modules_discovered": evaluated,
        "modules_missing": missing,
        "gate_status": "measured",
    }


def write_evidence_reach(
    evidence: Path = DEFAULT_T85_EVIDENCE_PATH,
    makefile: Path = DEFAULT_MAKEFILE,
    src_dir: Path = DEFAULT_SRC_DIR,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, Any]:
    """Measure and record `status/evidence/T85.json`."""
    measured = measure_evidence_reach(makefile, src_dir, repo_root)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.repo_gate [--check] [--list-evidence-modules]`.

    Without arguments it writes both D-22's and T85's evidence files —
    `make evidence`'s module list invokes this module once, like any other, so
    both records are produced from the one run. `--list-evidence-modules` is
    the discovery command `make evidence` itself now runs to build that list.
    """
    parser = argparse.ArgumentParser(
        description="D-22 and T85: the gates that check the evidence run's own machinery"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence files",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write D-22 evidence JSON to PATH (default: status/evidence/D-22.json)",
    )
    parser.add_argument(
        "--list-evidence-modules",
        action="store_true",
        help=(
            "print every module under src/integral that writes evidence, one per line, "
            "and exit — this is what `make evidence` iterates"
        ),
    )
    args = parser.parse_args(argv[1:])

    if args.list_evidence_modules:
        for name in evidence_writing_modules():
            print(name)
        return 0

    d22 = measure() if args.check else write_evidence(Path(args.write_evidence))
    t85 = measure_evidence_reach() if args.check else write_evidence_reach()

    print(json.dumps({"D-22": d22, "T85": t85}, ensure_ascii=False))
    for reason in d22["unenforced"]:
        print(reason, file=sys.stderr)
    for module in t85["modules_missing"]:
        print(f"{module} writes evidence but is not reached by `make evidence`", file=sys.stderr)

    d22_unenforced = d22["required_gates_with_no_enforcement_point"]
    t85_unreached = t85["gate_modules_outside_the_evidence_run"]
    if d22_unenforced == -1 or t85["gate_status"] == "unmeasured":
        return 3
    if d22_unenforced or t85_unreached:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
