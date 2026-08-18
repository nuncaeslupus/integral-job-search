"""One skill per step, measured rather than declared (S7).

`status/spec-v2-steps.json` settles thirteen steps (§ divisor `step_count`, the
same field S1/S2/T30's gates already read rather than re-count — a checker
that carries its own copy of 13 fails on the next legitimate change until
somebody edits the constant, and a check that gets edited to pass protects
nothing). S7's payload converts each step into a Claude Code skill written
with the `skill-creator` skill's rules, split the way this repo already
splits everything: **prose for the manner, scripts for the numbers.**

> A step whose skill embeds its checkpoint in prose has not been converted; it
> has been transcribed.

That sentence is the failure mode this module exists to catch. It is not a
literary judgement — it is two mechanical facts about a skill folder:

1. the `SKILL.md` **names its gate metric** — the literal identifier from
   `status/spec-v2-steps.json`'s `gate.metric` for this step appears in the
   skill's text, so the skill is talking about *this* step's actual acceptance
   condition rather than a paraphrase of it;
2. the `SKILL.md` **names its checkpoint script**, and that script **exists on
   disk** in the skill's own `scripts/` folder. Naming a script that is not
   there is exactly the "prose transcription" the payload warns about: words
   describing a computation nobody can run.

Both checks are string/filesystem facts, not a read of whether the prose is
*good* — the skill-creator gate (`validate.py` / `audit_library.py`) already
owns structural and content-quality review, and this module does not repeat
it. This module owns exactly the fraction named in the payload:

    steps_with_a_skill_fraction = (steps satisfying both checks) / step_count

**Every number here is counted, never restated.** `step_gates.py`'s docstring
records the S2 lesson this repo learned about that mistake: a checker that
divides by "however many steps had a metric" instead of counting can report
1.0 while some step failed silently. `probe_step_skills` walks every step in
the settled list and reports a `SkillCheck` for each one — a step with no
skill folder at all is still counted, against the divisor, as a failure.

**The skill-directory naming scheme is this module's own convention, not a
re-decision of the spec.** The spec settles step ids and order; it says
nothing about Claude Code folder names. The scheme adopted for S7 is
`step-<NN>-<id>` (two-digit, zero-padded, spec id with underscores turned to
hyphens — `interview_log` becomes `step-12-interview-log`), which sorts in
spec order in a directory listing. `skill_dir_name` is the one function that
encodes it; changing the scheme means changing that function and the thirteen
directories together, not silently drifting the two apart.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from jobsearch.process_spec import Step, StepList, load_steps

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "S7.json"

# A checkpoint script is named by a `scripts/<name>.py` reference anywhere in
# the skill's text — whether spelled as a literal repo-relative path or as
# `${CLAUDE_SKILL_DIR}/scripts/<name>.py` (the form skill-creator's own
# `body.skill-dir-var` rule requires for a project-scope skill citing its own
# script; see `.claude/skills/skill-creator/references/scripts-and-cli-conventions.md`).
# Either spelling contains this substring, which is all the naming check reads —
# existence on disk is verified separately, never inferred from the mention.
_SCRIPT_REF_RE = re.compile(r"scripts/([\w.\-]+\.py)")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillCheck(Strict):
    """One step's answer to "does it have a skill that names its gate and its script?"

    Every field is a fact this module observed, not an opinion — `reasons`
    carries the specific thing that was missing when `passes` is `False`, so a
    shortfall is legible without re-running the check by hand.
    """

    step: str
    n: int
    required: bool
    skill_dir: str
    skill_md_exists: bool
    gate_metric: str
    names_gate_metric: bool
    checkpoint_script: str | None
    checkpoint_script_exists: bool
    reasons: tuple[str, ...] = ()

    @property
    def passes(self) -> bool:
        return self.skill_md_exists and self.names_gate_metric and self.checkpoint_script_exists


def skill_dir_name(step: Step) -> str:
    """`step-<NN>-<id>` — S7's own naming convention (see module docstring)."""
    return f"step-{step.n:02d}-{step.id.replace('_', '-')}"


def _names_checkpoint_script(text: str, skill_dir: Path) -> tuple[str | None, bool]:
    """The first `scripts/<name>.py` this skill's text names, and whether it exists.

    The *first* match, not "any match that happens to exist": a skill naming a
    script that is not there is the failure this function exists to catch, so
    picking a later, real match over an earlier, missing one would hide it.
    """
    match = _SCRIPT_REF_RE.search(text)
    if match is None:
        return None, False
    name = match.group(1)
    return name, (skill_dir / "scripts" / name).is_file()


def check_step_skill(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> SkillCheck:
    """This step's `SkillCheck`, read from its skill folder — never asserted."""
    skill_dir = skills_dir / skill_dir_name(step)
    skill_md = skill_dir / "SKILL.md"
    reasons: list[str] = []

    if not skill_md.is_file():
        reasons.append(f"no SKILL.md at {skill_md}")
        return SkillCheck(
            step=step.id,
            n=step.n,
            required=step.required,
            skill_dir=skill_dir_name(step),
            skill_md_exists=False,
            gate_metric=step.gate.metric,
            names_gate_metric=False,
            checkpoint_script=None,
            checkpoint_script_exists=False,
            reasons=tuple(reasons),
        )

    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        reasons.append(f"SKILL.md could not be read: {exc}")
        text = ""

    metric_re = re.compile(rf"\b{re.escape(step.gate.metric)}\b")
    names_metric = bool(metric_re.search(text))
    if not names_metric:
        reasons.append(f"gate metric {step.gate.metric!r} does not appear in SKILL.md")

    script_name, script_exists = _names_checkpoint_script(text, skill_dir)
    if script_name is None:
        reasons.append("no scripts/<name>.py checkpoint script is named in SKILL.md")
    elif not script_exists:
        reasons.append(f"names scripts/{script_name} but it does not exist in {skill_dir}")

    return SkillCheck(
        step=step.id,
        n=step.n,
        required=step.required,
        skill_dir=skill_dir_name(step),
        skill_md_exists=True,
        gate_metric=step.gate.metric,
        names_gate_metric=names_metric,
        checkpoint_script=script_name,
        checkpoint_script_exists=script_exists,
        reasons=tuple(reasons),
    )


def probe_step_skills(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[SkillCheck]:
    """Every settled step's `SkillCheck`, in step order — the divisor's own steps.

    Walks `steps.steps`, never the contents of `skills_dir`: a stray skill
    folder that matches nobody's naming scheme is invisible here on purpose,
    because it cannot make an *existing* step pass or fail. What would make a
    step invisible — reading `len(skills_dir.iterdir())` as the count instead
    of `step_count` — is exactly S2's divisor mistake one level up, and this
    function is built so it cannot repeat it: nothing here can iterate more or
    fewer entries than the settled step list has rows.
    """
    steps = steps or load_steps()
    return [check_step_skill(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def measure(
    steps_path: Path | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> dict[str, Any]:
    """The S7 gate reading, as it is written to evidence.

    `steps_with_a_skill_fraction` divides by `steps.step_count` — read from
    `status/spec-v2-steps.json`, never hardcoded and never `len(checks)` (which
    would equal the divisor here by construction, but restating it would be
    the self-counting mistake `step_gates` and `step_specs` both warn against;
    reading `step_count` keeps this module unable to drift from the JSON even
    if a future edit changes how `probe_step_skills` walks the list).
    """
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, never a crash to propagate
        return {
            "steps_with_a_skill_fraction": 0.0,
            "step_count": 0,
            "steps_checked": 0,
            "shortfalls": [{"step": None, "reason": f"step list could not be loaded: {exc}"}],
            "checks": [],
        }

    checks = probe_step_skills(steps, skills_dir)
    passing = [check for check in checks if check.passes]
    shortfalls = [
        {"step": check.step, "skill_dir": check.skill_dir, "reasons": list(check.reasons)}
        for check in checks
        if not check.passes
    ]

    return {
        "steps_with_a_skill_fraction": round(len(passing) / steps.step_count, 4),
        "step_count": steps.step_count,
        "steps_checked": len(checks),
        "shortfalls": shortfalls,
        "checks": [check.model_dump(mode="json") for check in checks],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path | None = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/S7.json`."""
    measured = measure(steps_path, skills_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.step_skills [--check] [--write-evidence [PATH]]` → S7's gate.

    `--check` measures and reports without writing a file — the read-only path
    a test or a reviewer runs. Without it (the default, and with
    `--write-evidence` explicit), the evidence file is written — `[PATH]`
    defaults to `status/evidence/S7.json` when the flag carries no value, so
    plain `python -m jobsearch.step_skills` still writes there, matching every
    other gate module in this package (`step_runtime`, `step_gates`, ...).
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
        default=str(DEFAULT_EVIDENCE_PATH),
        metavar="PATH",
        help="write evidence JSON to PATH (default: status/evidence/S7.json)",
    )
    parser.add_argument(
        "--skills-dir",
        default=str(DEFAULT_SKILLS_DIR),
        metavar="DIR",
        help="skills library root to check (default: .claude/skills)",
    )
    args = parser.parse_args(argv[1:])
    skills_dir = Path(args.skills_dir)

    if args.check:
        measured = measure(skills_dir=skills_dir)
    else:
        measured = write_evidence(Path(args.write_evidence), skills_dir=skills_dir)

    print(json.dumps(measured, ensure_ascii=False))
    if measured["steps_checked"] == 0:
        print("no steps were checked — nothing was measured", file=sys.stderr)
        return 3
    for shortfall in measured["shortfalls"]:
        print(f"{shortfall['step']}: {', '.join(shortfall['reasons'])}", file=sys.stderr)
    return 1 if measured["shortfalls"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
