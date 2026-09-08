"""D-22 — the gate the docs require must have something that runs it.

`CLAUDE.md` says all four must pass before a merge — lint, test, evidence and
verify-gates. Nothing ran them. PR #89 fell through three holes
at once: GitHub Actions had no runner minutes from 2026-08-19 (so `ci.yml`
enforced nothing while that lasted; runners returned 2026-09-01),
`open_task_pr.sh` re-runs the *payload* gate and never
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

**T101 is D-22's own hole, one file over.** `DEFAULT_INSTRUCTIONS` is
`CLAUDE.md` and nothing else, so nothing asserted that a target named in
`.github/workflows/` exists — and one did not. `verify-subtree` lost its rule
in #123 and its job kept calling it, red on every run until 2026-09-01 and
invisible while the runner outage failed everything else too.
`ci_targets_missing_from_makefile` is recorded into D-22's file rather than
its own, because it is the same claim about the same Makefile: every `make`
the project tells something to run is a rule that exists.
"""

from __future__ import annotations

import argparse
import ast
import itertools
import json
import re
import shlex
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from integral import naming

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-22.json"
DEFAULT_T85_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T85.json"
DEFAULT_MAKEFILE = _REPO_ROOT / "Makefile"
DEFAULT_INSTRUCTIONS = _REPO_ROOT / "CLAUDE.md"
DEFAULT_SRC_DIR = _REPO_ROOT / "src" / "integral"
DEFAULT_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"

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


# ---------------------------------------------------------------------------
# T101 — a CI job may not name a Makefile target that does not exist


# A Make target name, spelled as `_RULE_RE` spells it. Reading a `make`
# invocation stops at the first token that is not one, so `make lint && ./x`
# yields `lint` and not `&&`.
_TARGET_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _run_scripts(document: Any) -> list[str]:
    """Every `run:` script in a parsed workflow document.

    Parsed, never matched against the file text. A regex over the text reads
    the word `make` out of comments, and this repository's workflows discuss
    Make targets at length — the comment naming `verify-subtree` outlived the
    job that ran it, so a regex would report a violation that is not there.

    `jobs.<job_id>.steps[*].run` and nowhere else, because that is the one
    place the Actions schema puts a shell command. The first version of this
    walked the whole document for any mapping with a string `run`, which reads
    `jobs.<id>.env.run` — an ordinary environment variable — as a step, and
    then fails the gate over a `make` in somebody's data (review on #291).
    """
    if not isinstance(document, dict):
        return []
    jobs = document.get("jobs")
    if not isinstance(jobs, dict):
        return []
    scripts: list[str] = []
    for job in jobs.values():
        steps = job.get("steps") if isinstance(job, dict) else None
        for step in steps if isinstance(steps, list) else []:
            script = step.get("run") if isinstance(step, dict) else None
            if isinstance(script, str):
                scripts.append(script)
    return scripts


def _make_targets_in(script: str) -> list[str]:
    """The targets every `make` invocation in one shell script names.

    `shlex` rather than a second regex: a `run: |` block is a shell script,
    and `shlex` already knows that a `#` inside quotes does not start a
    comment and that a trailing backslash continues a line.

    `punctuation_chars` rather than `shlex.split`, because that helper keeps
    `ghost;` as a single token, `_TARGET_TOKEN_RE` then rejects it, and a
    genuinely missing target goes unreported — the fail-open direction. The
    lexer emits `;`, `&&` and `|` as tokens of their own, so the target is
    read and the delimiter ends the invocation (review on #291).

    ponytail: reading stops at the first token that is not a target name, so
    `make -C sub thing` contributes nothing rather than reading `sub` as a
    target. Nothing here invokes make that way; teach it options the day one
    does, not before — guessing which options take an argument is how a check
    starts reporting violations that are not there.
    """
    lexer = shlex.shlex(script, posix=True, punctuation_chars=";&|()")
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        # An unbalanced quote is a broken step, not a target reference.
        return []
    targets: list[str] = []
    after_make = False
    for token in tokens:
        if token == "make":
            after_make = True
        elif after_make and _TARGET_TOKEN_RE.match(token):
            targets.append(token)
        else:
            after_make = False
    return targets


#: Constructed workflows the reader must get right, read by the same two
#: functions the live tree goes through. The live tree names four targets and
#: all four exist, so a denominator counting only those never moves when the
#: *reader* regresses — and both of these were reader faults found by review on
#: #291, each fail-open: a real missing target that goes unreported, or a
#: violation invented out of somebody's data.
CI_READER_CONTROLS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "a shell delimiter glued to the target name — `make ghost;`",
        "jobs:\n  a:\n    steps:\n      - run: make ghost; make phantom && make lint\n",
        ("ghost", "phantom", "lint"),
    ),
    (
        "`run` as an environment variable name, which is data and not a step",
        "jobs:\n  a:\n    env:\n      run: make ghost\n    steps:\n      - run: make lint\n",
        ("lint",),
    ),
)


def _control_readings() -> tuple[int, list[str]]:
    """`CI_READER_CONTROLS` put through the reader: targets seen, failures."""
    evaluated = 0
    failures: list[str] = []
    for label, document, expected in CI_READER_CONTROLS:
        read = tuple(t for s in _run_scripts(yaml.safe_load(document)) for t in _make_targets_in(s))
        evaluated += len(expected)
        if read != expected:
            failures.append(f"accepted: {label} — read {list(read)}, expected {list(expected)}")
    return evaluated, failures


def ci_make_targets(workflows: Path = DEFAULT_WORKFLOWS_DIR) -> list[str]:
    """Every Make target a workflow step runs, sorted and deduplicated."""
    named: set[str] = set()
    for path in sorted(itertools.chain(workflows.glob("*.yml"), workflows.glob("*.yaml"))):
        for script in _run_scripts(yaml.safe_load(path.read_text(encoding="utf-8"))):
            named.update(_make_targets_in(script))
    return sorted(named)


def ci_make_targets_missing(repo_root: Path = _REPO_ROOT) -> list[str]:
    """The targets CI runs that the Makefile does not define.

    One direction only. *A target that exists must be named in CI* is the
    tempting converse and is false on a correct repository: `format`, `clean`,
    `build`, `publish`, `sync`, `help`, `reader` and `labelling-round` are
    deliberately not CI steps, so asserting it would fail from its first run
    and the repair would be an allowlist edited every time a target is added.
    """
    rules = make_rules(repo_root / "Makefile")
    return [t for t in ci_make_targets(repo_root / ".github" / "workflows") if t not in rules]


def measure_ci_targets(
    makefile: Path = DEFAULT_MAKEFILE, workflows: Path = DEFAULT_WORKFLOWS_DIR
) -> dict[str, Any]:
    """T101's half of the D-22 record: `ci_targets_missing_from_makefile`.

    Its own reading rather than a branch of `measure`'s, so that an unreadable
    workflow tree records `-1` here without also erasing D-22's answer about
    `CLAUDE.md`. Two questions, two verdicts.

    `verify-subtree` is the fault behind it: `a4e9541` (T58, #123) deleted the
    target when the bundle stopped being a subtree and left the job calling
    it. It failed on every run from then until 2026-09-01, invisible because
    the runner outage was failing every job for an unrelated reason.
    """

    def _unreadable(reason: str) -> dict[str, Any]:
        return {
            "ci_targets_missing_from_makefile": -1,
            "ci_targets_missing_from_makefile_evaluated": 0,
            "ci_targets_missing": [],
            "ci_unmeasured_reason": reason,
        }

    try:
        rules = make_rules(makefile)
    except OSError as exc:
        return _unreadable(f"{makefile.name} could not be read: {exc}")
    try:
        named = ci_make_targets(workflows)
    except (OSError, yaml.YAMLError) as exc:
        return _unreadable(f"a workflow under {workflows.name}/ could not be parsed: {exc}")
    if not named:
        return _unreadable(
            f"no step under {workflows.name}/ runs a `make` target, so a zero count here "
            "would rest on having scanned nothing"
        )
    missing = [t for t in named if t not in rules]
    control_targets, control_failures = _control_readings()
    return {
        # A control the reader gets wrong counts as a violation: the number
        # this gate asserts is zero has to move when the reader breaks, not
        # only when a workflow does.
        "ci_targets_missing_from_makefile": len(missing) + len(control_failures),
        "ci_targets_missing_from_makefile_evaluated": len(named) + control_targets,
        "ci_targets_missing": missing,
        "ci_reader_controls": [label for label, _, _ in CI_READER_CONTROLS],
        "ci_reader_control_failures": control_failures,
    }


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
    instructions: Path = DEFAULT_INSTRUCTIONS,
    makefile: Path = DEFAULT_MAKEFILE,
    workflows: Path = DEFAULT_WORKFLOWS_DIR,
) -> dict[str, Any]:
    """D-22's reading, with T101's `ci_targets_missing_from_makefile` beside it."""
    return {
        **_measure_required_gates(instructions, makefile),
        **measure_ci_targets(makefile, workflows),
    }


def _measure_required_gates(
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
    workflows: Path = DEFAULT_WORKFLOWS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-22.json`."""
    measured = measure(instructions, makefile, workflows)
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

    def _unmeasured(reason: str) -> dict[str, Any]:
        return {
            "gate_modules_outside_the_evidence_run": 0,
            "gate_modules_outside_the_evidence_run_evaluated": 0,
            "gate_modules_discovered": 0,
            "modules_missing": [],
            "gate_status": "unmeasured",
            "unmeasured_reason": reason,
        }

    discovered = evidence_writing_modules(src_dir)
    evaluated = len(discovered)
    if evaluated == 0:
        return _unmeasured("no module under src/ constructs an evidence path")
    try:
        reached = modules_reached_by_evidence_run(makefile, repo_root)
    except ValueError as exc:
        # The `evidence` target was rewritten into a shape this cannot read.
        # That is exactly what a merge between two branches that both edit the
        # recipe can produce, and a traceback there would take `--check` down
        # instead of reporting that the reach cannot be scored. A check that
        # cannot run must say so, which is the same rule the empty-input branch
        # above already follows.
        return _unmeasured(f"cannot read the evidence target: {exc}")
    except subprocess.CalledProcessError as exc:
        return _unmeasured(
            f"the evidence target's module list failed to evaluate: exit {exc.returncode}"
        )
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


DEFAULT_T125_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T125.json"


def measure_formatting(repo_root: Path = _REPO_ROOT) -> dict[str, Any]:
    """T125: how many files `ruff format` would still rewrite.

    Lives here rather than in a module of its own because it is the same
    question this file already asks — whether the repo's own checking machinery
    is wired up — and a whole module for one `subprocess.run` would be more
    scaffolding than measurement.

    Two numbers, not one. `unformatted_files` alone is satisfiable by a repo
    that cannot run the formatter at all, so `files_checked` is the denominator
    and `lint_runs_the_check` records whether anything would *notice* a
    regression: a formatted tree with no check in `make lint` drifts back within
    one session, which is exactly how this task came to exist.
    """
    try:
        result = subprocess.run(
            ["uv", "run", "--extra", "dev", "ruff", "format", "--check", "."],
            capture_output=True,
            text=True,
            cwd=repo_root,
            check=False,
        )
    except OSError as exc:
        return {
            "unformatted_files": -1,
            "files_checked": 0,
            "lint_runs_the_check": False,
            "gate_status": "unmeasured",
            "reasons": [f"ruff could not be run: {exc}"],
        }
    output = result.stdout + result.stderr
    # ruff's summary line, not a per-file marker. An earlier version of this
    # counted `^Would reformat: ` lines, which `--check` does not emit at all —
    # it prints a diff and one summary — so the metric read 0 with a genuinely
    # unformatted file in the tree. Caught by a negative control, which is the
    # only reason it is not still reading 0.
    summary = re.search(
        r"(?:(\d+) files? would be reformatted(?:, (\d+) files? already formatted)?"
        r"|(\d+) files? already formatted)",
        output,
    )
    if summary is None:
        return {
            "unformatted_files": -1,
            "files_checked": 0,
            "lint_runs_the_check": False,
            "gate_status": "unmeasured",
            "reasons": [f"ruff printed no summary line to parse: {output[-200:]!r}"],
        }
    would_reformat = int(summary.group(1) or 0)
    already = int(summary.group(2) or summary.group(3) or 0)
    files_checked = would_reformat + already
    lint_checks = "ruff format --check" in (repo_root / "Makefile").read_text(encoding="utf-8")
    measured: dict[str, Any] = {
        "unformatted_files": would_reformat,
        "files_checked": files_checked,
        "lint_runs_the_check": lint_checks,
        "gate_status": "measured",
    }
    if files_checked < MINIMUM_FILES_FORMATTED:
        # A zero over a scan that found almost nothing is what a broken
        # invocation also reports.
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {files_checked} file(s) checked (floor {MINIMUM_FILES_FORMATTED}) — "
            "a pass over nothing is not a pass"
        ]
    return measured


#: The tree held 427 files when T125 landed. The floor sits well below that so
#: deleting a module never trips it, and a broken invocation reporting two does.
MINIMUM_FILES_FORMATTED = 300


def record_formatting(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what `measure_formatting` measured.

    The one difference is the denominator, and it is `naming.record`'s
    difference for `naming.record`'s reason (T100). `files_checked` measures
    nothing about the code: it exists so that `unformatted_files == 0` cannot
    rest on a scan that found nothing. Committed as an exact value it moved on
    every pull request that added a file — and since ruff 0.16 the formatter
    reads **Markdown**, so a pull request that adds nine task files and no
    Python at all took it from 453 to 462 and `make evidence` went red for a
    reason that had nothing to do with formatting (T150).

    The floor does the denominator's whole job and does not move. The number is
    not hidden — the run still prints what it saw, and refuses to score at all
    below the floor.
    """
    committed = {key: value for key, value in measured.items() if key != "files_checked"}
    committed["files_checked_at_least"] = MINIMUM_FILES_FORMATTED
    return committed


def write_formatting_evidence(
    evidence: Path = DEFAULT_T125_EVIDENCE_PATH, repo_root: Path = _REPO_ROOT
) -> dict[str, Any]:
    """Measure and record `status/evidence/T125.json`."""
    committed = record_formatting(measure_formatting(repo_root))
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(committed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return committed


DEFAULT_T150_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T150.json"

#: The two ways the tree moves under a pull request that changes no behaviour.
#: T100 asked the second one only, which is why it never saw `files_checked`:
#: archiving a task file moves it inside the tree, and `ruff format` reads it
#: either way, so the key that drifts on every added file survived a check
#: built entirely out of moving one.
A_FILE_IS_ADDED = "a Markdown file is added"
A_TASK_FILE_IS_ARCHIVED = "a task file is archived"


@dataclass(frozen=True)
class EvidenceSource:
    """One committed evidence record, and how the tree's shape moves it.

    `measure` is the live measurement and `record` is what gets committed out
    of it — the same pair `naming.measure`/`naming.record` already are.
    `mutations` maps a mutation name to a function of `(repo_root, measured)`
    returning the measurement the *mutated* tree would produce.

    A mutation is stated as a transform of the measurement rather than
    performed on disk because the alternative is not available here: measuring
    a whole second tree means regenerating evidence in it, and this metric is
    itself part of `make evidence`, which would then run inside itself. What
    keeps a transform from being a comfortable fiction is that it must
    *actually move the measurement it is given* — a mutation that changes
    nothing is dropped from the denominator below, so a registry of identity
    transforms reports `unmeasured`, never a clean zero.
    """

    name: str
    measure: Callable[[Path], dict[str, Any]]
    record: Callable[[dict[str, Any]], dict[str, Any]]
    mutations: Mapping[str, Callable[[Path, dict[str, Any]], dict[str, Any]]]


def _one_more_file(key: str) -> Callable[[Path, dict[str, Any]], dict[str, Any]]:
    """The measurement a tree with one more Markdown file in it would produce.

    One more file, and no new finding in it: a task file adds nothing to
    `unformatted_files` (the formatter would rewrite it otherwise and `make
    lint` is red) and nothing to the old-name counts. Measured, not assumed —
    `ruff format --check` over a directory of *n* Markdown files reports *n*,
    which `test_adding_a_markdown_file_adds_one_to_the_formatter_population`
    holds down.
    """

    def mutate(repo_root: Path, measured: dict[str, Any]) -> dict[str, Any]:
        population = measured.get(key)
        if not isinstance(population, int) or isinstance(population, bool):
            return dict(measured)
        return {**measured, key: population + 1}

    return mutate


def _with_a_task_file_archived(repo_root: Path, measured: dict[str, Any]) -> dict[str, Any]:
    """T100's mutation, reused: the sweep with one live task file in `_history/`."""
    candidate = naming.first_task_file(repo_root)
    if candidate is None:
        return dict(measured)
    return naming.measure(repo_root, archived=frozenset({candidate}))


def evidence_sources() -> tuple[EvidenceSource, ...]:
    """The records this gate compares across both mutations.

    Every measurement that counts a **population of files** belongs here, and
    the two that do today are the two that have already been caught committing
    one: T55's `files_scanned` (fixed by T100) and T125's `files_checked`
    (fixed by T150). A new sweep that commits a census and is not registered
    here is not covered — which is why the fix is the floor in each record and
    this is the check that the floor is really doing its job.
    """
    return (
        EvidenceSource(
            name="T125",
            measure=measure_formatting,
            record=record_formatting,
            mutations={A_FILE_IS_ADDED: _one_more_file("files_checked")},
        ),
        EvidenceSource(
            name="T55",
            measure=naming.measure,
            record=naming.record,
            mutations={
                A_FILE_IS_ADDED: _one_more_file("files_scanned"),
                A_TASK_FILE_IS_ARCHIVED: _with_a_task_file_archived,
            },
        ),
    )


def measure_evidence_stability(
    repo_root: Path = _REPO_ROOT,
    *,
    sources: Sequence[EvidenceSource] | None = None,
) -> dict[str, Any]:
    """T150's gate: `unstable_evidence_keys`.

    A committed evidence key must say the same thing about a tree that gained a
    file and about a tree that archived one. Anything else is a gate that goes
    red on pull requests it has no opinion about, which is the state that
    teaches sessions to expect red.

    Three things make the zero mean something:

    - a mutation that leaves the measurement untouched is **not a comparison**
      and is not counted — the self-comparison T100's `first_task_file` was
      rewritten to avoid;
    - `evidence_keys_compared` is the denominator, so a `record` that reached
      stability by dropping all of its keys scores zero over zero and is
      `unmeasured`;
    - **both** mutations must be exercised somewhere in the registry. T100 was
      green while blind to one of them; a run that has quietly lost the added-
      file half must not read like a pass.
    """
    registry = evidence_sources() if sources is None else tuple(sources)
    unstable: list[str] = []
    skipped: list[str] = []
    exercised: set[str] = set()
    keys_compared = 0
    comparisons = 0

    for source in registry:
        measured = source.measure(repo_root)
        live = source.record(measured)
        for mutation, mutate in sorted(source.mutations.items()):
            mutated = mutate(repo_root, measured)
            if mutated == measured:
                skipped.append(f"{source.name}: {mutation} moved nothing to compare")
                continue
            after = source.record(mutated)
            compared = live.keys() | after.keys()
            if not compared:
                skipped.append(f"{source.name}: {mutation} left no committed key to compare")
                continue
            comparisons += 1
            exercised.add(mutation)
            keys_compared += len(compared)
            unstable.extend(
                f"{source.name}.{key} moves when {mutation}"
                for key in sorted(compared)
                if live.get(key) != after.get(key)
            )

    result: dict[str, Any] = {
        "unstable_evidence_keys": len(unstable),
        "evidence_keys_compared": keys_compared,
        "mutations_compared": sorted(exercised),
        "gate_status": "measured",
        "unstable": unstable,
    }
    missing = sorted({A_FILE_IS_ADDED, A_TASK_FILE_IS_ARCHIVED} - exercised)
    if comparisons == 0 or missing:
        result["gate_status"] = "unmeasured"
        result["reasons"] = [
            *(
                [f"no evidence record was compared across {mutation}" for mutation in missing]
                if missing
                else []
            ),
            *skipped,
        ]
    return result


def write_evidence_stability(
    evidence: Path = DEFAULT_T150_EVIDENCE_PATH, repo_root: Path = _REPO_ROOT
) -> dict[str, Any]:
    """Measure and record `status/evidence/T150.json`."""
    measured = measure_evidence_stability(repo_root)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.repo_gate [--check] [--list-evidence-modules]`.

    Without arguments it writes both D-22's (T101 included) and T85's evidence files —
    `make evidence`'s module list invokes this module once, like any other, so
    both records are produced from the one run. `--list-evidence-modules` is
    the discovery command `make evidence` itself now runs to build that list.
    """
    parser = argparse.ArgumentParser(
        description="D-22, T101 and T85: the gates that check the repo's own gate machinery"
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
    t125 = record_formatting(measure_formatting()) if args.check else write_formatting_evidence()
    t150 = measure_evidence_stability() if args.check else write_evidence_stability()

    print(json.dumps({"D-22": d22, "T85": t85, "T125": t125, "T150": t150}, ensure_ascii=False))
    for reason in d22["unenforced"]:
        print(reason, file=sys.stderr)
    if "ci_unmeasured_reason" in d22:
        print(d22["ci_unmeasured_reason"], file=sys.stderr)
    for target in d22["ci_targets_missing"]:
        print(
            f"a CI step runs `make {target}`, which the Makefile does not define",
            file=sys.stderr,
        )
    for failure in d22.get("ci_reader_control_failures", []):
        print(f"the CI reader misread a control: {failure}", file=sys.stderr)
    for module in t85["modules_missing"]:
        print(f"{module} writes evidence but is not reached by `make evidence`", file=sys.stderr)
    for key in t150["unstable"]:
        print(f"a committed evidence key is not stable: {key}", file=sys.stderr)
    for reason in t150.get("reasons", []):
        print(f"evidence stability is unmeasured: {reason}", file=sys.stderr)

    d22_unenforced = d22["required_gates_with_no_enforcement_point"]
    ci_missing = d22["ci_targets_missing_from_makefile"]
    t85_unreached = t85["gate_modules_outside_the_evidence_run"]
    if t125["unformatted_files"]:
        print(
            f"{t125['unformatted_files']} file(s) would be reformatted — run `make format`",
            file=sys.stderr,
        )
    if not t125["lint_runs_the_check"]:
        print(
            "make lint does not run `ruff format --check` — formatting will drift", file=sys.stderr
        )
    if (
        d22_unenforced == -1
        or ci_missing == -1
        or t85["gate_status"] == "unmeasured"
        or t125["gate_status"] == "unmeasured"
        or t150["gate_status"] == "unmeasured"
    ):
        return 3
    if (
        d22_unenforced
        or ci_missing
        or t85_unreached
        or t125["unformatted_files"]
        or t150["unstable_evidence_keys"]
    ):
        return 1
    if not t125["lint_runs_the_check"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
