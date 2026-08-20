"""Does every step checkpoint refuse to certify a step whose gate is unbuilt? (D-21)

`run_checkpoint.py` exists thirteen times, once per step skill, and each copy ended by
turning its result into an exit code. That tail was written thirteen times too, and it
read the coverage half of the stop rule and nothing else — so a step whose acceptance
gate does not exist still exited 0. Step 9 printed `"gate_state": "not_implemented"`
and exited clean in the same breath; step 8 did it while `extract()` was settling 0 of
25 dimensions on every advert.

`integral.step_gates.checkpoint_exit` is now the single place that decision is made.
This module counts the copies that do not route through it, by reading each script's
`main` on the AST: a `return` that can still yield 0 by any path other than that call
is what the defect looked like, and it is what is counted here.

**Why a reading and not a run.** Probing this by importing each script and calling its
`main` was the first shape of this module, and it put `spec_from_file_location` /
`exec_module` into `integral` — which
`test_nothing_in_the_codebase_executes_a_contributed_parse_module` forbids outright, and
rightly: the connector contract's whole safety argument is that nothing in the package
loads code from a path. So the package reads, and
`tests/test_step_certification.py` does the running — stubbing each script's
`checkpoint()` and asserting the code its own `main` returns. The claim is checked both
ways; only the machinery for one of them is allowed to live here.

D-21 offered two resolutions and this takes both, because they answer different
readers. The exit code is for a caller; the skill's own prose is for whoever is being
shown the step's output, and a step whose gate is unbuilt now says so there too. That
sentence is checked here as well — present exactly when the gate is unbuilt — so it
cannot go on claiming an unbuilt gate after the gate is built.

The gate is the name `status/plan.md` settled for it —
`steps_certified_on_an_unimplemented_gate == 0` — counted as the checkpoints that *could*
still certify one, which is the only form a static reading can take and the stricter of
the two. A script or `SKILL.md` that cannot be read at all counts toward that number
rather than being skipped: a checkpoint nobody can parse has not been shown to refuse
anything, and a measurement that quietly drops its hard cases is the clean zero this
repository keeps finding in its own history.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from integral.process_spec import Step, StepList, load_steps
from integral.step_gates import UNCERTIFIABLE, certifiable
from integral.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-21.json"

CHECKPOINT_SCRIPT = "run_checkpoint.py"
#: The shared decision, and the module it must come from. A local function of the
#: same name would satisfy the call check and decide nothing shared, so the import
#: is checked too.
DECIDER = "checkpoint_exit"
DECIDER_MODULE = "integral.step_gates"
#: The result key the exit code is derived from — see `step_gates.checkpoint_exit`.
CERTIFIABLE_KEY = "certifiable"
CERTIFIABLE_FN = "certifiable"
#: D-21 put up two resolutions and this repository took both: the exit code refuses,
#: and the skill says so before it presents the step's output. The second half is a
#: sentence in prose, so it is checked the way `step_skills` checks the others — by a
#: marker, present exactly when the step's gate is unbuilt. A skill still announcing a
#: gate that has since been built is the same drift in the other direction, and is
#: counted too.
UNBUILT_ANNOUNCEMENT = "exits 3 at best"
SKILL_DOC = "SKILL.md"


@dataclass(frozen=True)
class CheckpointProbe:
    """How one step's checkpoint decides its exit code."""

    step: str
    n: int
    gate_state: str
    gate_metric: str
    gate_owner: str
    certifiable: bool
    reasons: tuple[str, ...]

    @property
    def routes_through_the_shared_decision(self) -> bool:
        return not self.reasons


def checkpoint_script(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> Path:
    """Where this step's checkpoint lives — S7's naming convention, not a listing."""
    return skills_dir / skill_dir_name(step) / "scripts" / CHECKPOINT_SCRIPT


def skill_doc(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> Path:
    """Where this step's skill prose lives."""
    return skills_dir / skill_dir_name(step) / SKILL_DOC


def _announcement_reasons(step: Step, skills_dir: Path) -> list[str]:
    """Whether the skill's prose agrees with the step's recorded gate state."""
    doc = skill_doc(step, skills_dir)
    if not doc.is_file():
        return [f"no {SKILL_DOC} at {doc}"]
    try:
        text = doc.read_text(encoding="utf-8")
    except OSError as exc:  # a read failure is evidence, never a crash
        return [f"{SKILL_DOC} could not be read: {exc}"]
    announces = UNBUILT_ANNOUNCEMENT in text
    if certifiable(step) and announces:
        return [f"{SKILL_DOC} says the gate is unbuilt, but {step.gate.task} has built it"]
    if not certifiable(step) and not announces:
        return [
            f"{SKILL_DOC} does not say {step.gate.metric} is unbuilt "
            f"(no {UNBUILT_ANNOUNCEMENT!r})"
        ]
    return []


def _imports_the_decider(tree: ast.Module) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == DECIDER_MODULE
        and any(alias.name == DECIDER and alias.asname is None for alias in node.names)
        for node in ast.walk(tree)
    )


def _function(tree: ast.Module, name: str) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _returns(function: ast.FunctionDef) -> list[ast.Return]:
    """Every `return` this function itself makes — a nested def's are its own."""
    found: list[ast.Return] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node is not None:
            found.append(node)
    return found


def _is_decider_call(value: ast.expr | None) -> bool:
    return (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == DECIDER
    )


def _can_yield_zero(value: ast.expr | None) -> bool:
    """Could this return expression evaluate to 0 — the code that reads as "passed"?

    Answered by looking for a literal 0 anywhere in the expression rather than by
    listing the shapes it has taken. The old tail was `0 if result["coverage_met"]
    else 1`; a later one could be `int(not met)` or a lookup in a tuple, and every
    such rewrite still has to write the zero down somewhere.
    """
    if value is None:
        return True
    return any(
        isinstance(node, ast.Constant) and node.value == 0 and not isinstance(node.value, bool)
        for node in ast.walk(value)
    )


def _sets_certifiable(function: ast.FunctionDef) -> bool:
    """Does `checkpoint()` compute the key the exit code is derived from?

    `checkpoint_exit` reads `certifiable` out of the payload, so a script that
    routes through it but never sets the key would exit `UNCERTIFIABLE` for every
    step, including the ones whose gate is built. That is a different wrong answer,
    not a safe one: a refusal nobody can act on is as uninformative as the clean
    exit it replaced.
    """
    for node in ast.walk(function):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values, strict=True):
            if not (isinstance(key, ast.Constant) and key.value == CERTIFIABLE_KEY):
                continue
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == CERTIFIABLE_FN
            ):
                return True
    return False


def probe_checkpoint(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> CheckpointProbe:
    """Read one step's checkpoint and report every way it could still certify itself."""

    def probe(*reasons: str) -> CheckpointProbe:
        return CheckpointProbe(
            step=step.id,
            n=step.n,
            gate_state=step.gate.state,
            gate_metric=f"{step.gate.metric} {step.gate.op} {step.gate.threshold}",
            gate_owner=step.gate.task,
            certifiable=certifiable(step),
            reasons=reasons,
        )

    script = checkpoint_script(step, skills_dir)
    prose = _announcement_reasons(step, skills_dir)
    if not script.is_file():
        return probe(*prose, f"no checkpoint script at {script}")
    try:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    except (OSError, SyntaxError) as exc:  # a read failure is evidence, never a crash
        return probe(*prose, f"{script.name} could not be read: {exc}")

    reasons: list[str] = list(prose)
    if not _imports_the_decider(tree):
        reasons.append(f"does not import {DECIDER} from {DECIDER_MODULE}")

    checkpoint = _function(tree, "checkpoint")
    if checkpoint is None:
        reasons.append("defines no checkpoint()")
    elif not _sets_certifiable(checkpoint):
        reasons.append(f"checkpoint() does not set {CERTIFIABLE_KEY!r} from {CERTIFIABLE_FN}()")

    main = _function(tree, "main")
    if main is None:
        reasons.append("defines no main()")
    else:
        returns = _returns(main)
        if not any(_is_decider_call(node.value) for node in returns):
            reasons.append(f"main() never returns {DECIDER}(...)")
        for node in returns:
            if _is_decider_call(node.value):
                continue
            if _can_yield_zero(node.value):
                reasons.append(
                    f"main() line {node.lineno} can return 0 without asking {DECIDER}"
                )

    return probe(*reasons)


def probe_checkpoints(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[CheckpointProbe]:
    """Every settled step's probe, in journey order.

    Walks the step list, never the contents of `skills_dir`: the divisor is the
    number of steps that exist, so a deleted skill directory reads as a step that
    could not be probed rather than as one fewer step to answer for.
    """
    steps = steps or load_steps()
    return [probe_checkpoint(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def measure(
    steps_path: Path | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> dict[str, Any]:
    """D-21's gate reading, as it is written to evidence."""
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, never a crash
        return {
            "steps_certified_on_an_unimplemented_gate": -1,
            "step_count": 0,
            "steps_probed": 0,
            "uncertifiable_exit_code": UNCERTIFIABLE,
            "shortfalls": [{"step": None, "reasons": [f"step list could not be loaded: {exc}"]}],
            "probes": [],
        }

    probes = probe_checkpoints(steps, skills_dir)
    shortfalls = [probe for probe in probes if not probe.routes_through_the_shared_decision]
    # A step the probe never reached is not a step that passed. Counting the
    # shortfall into the metric keeps `== 0` from being satisfiable by a probe
    # that walked fewer steps than the spec settles.
    unprobed = max(steps.step_count - len(probes), 0)
    return {
        "steps_certified_on_an_unimplemented_gate": len(shortfalls) + unprobed,
        "step_count": steps.step_count,
        "steps_probed": len(probes),
        "uncertifiable_exit_code": UNCERTIFIABLE,
        "shortfalls": [
            {"step": probe.step, "gate_state": probe.gate_state, "reasons": list(probe.reasons)}
            for probe in shortfalls
        ],
        "probes": [
            {
                "step": probe.step,
                "n": probe.n,
                "gate_state": probe.gate_state,
                "gate_metric": probe.gate_metric,
                "gate_owner": probe.gate_owner,
                "certifiable": probe.certifiable,
                "expected_exit": 0 if probe.certifiable else UNCERTIFIABLE,
            }
            for probe in probes
        ],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path | None = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-21.json`."""
    measured = measure(steps_path, skills_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.step_certification [--check] [--write-evidence [PATH]]`.

    `--check` measures and reports without writing — the read-only path. Without
    it the evidence file is written, defaulting to `status/evidence/D-21.json`, so
    plain `python -m integral.step_certification` behaves like every other gate
    module in this package and `make evidence` picks it up unprompted.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="measure and report only; do not write the evidence file",
    )
    parser.add_argument(
        "--write-evidence",
        nargs="?",
        const=str(DEFAULT_EVIDENCE_PATH),
        default=None,
        help=f"write the evidence file (default: {DEFAULT_EVIDENCE_PATH})",
    )
    args = parser.parse_args(argv[1:])

    measured = (
        measure()
        if args.check
        else write_evidence(Path(args.write_evidence or DEFAULT_EVIDENCE_PATH))
    )

    print(json.dumps(measured, ensure_ascii=False))
    if measured["steps_probed"] < measured["step_count"]:
        print(
            f"step_certification: probed {measured['steps_probed']} of "
            f"{measured['step_count']} steps",
            file=sys.stderr,
        )
        return 1
    if measured["steps_certified_on_an_unimplemented_gate"] != 0:
        for shortfall in measured["shortfalls"]:
            for reason in shortfall["reasons"]:
                print(f"step_certification: {shortfall['step']}: {reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    sys.exit(_main(sys.argv))
