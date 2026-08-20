"""No step skill may offer an unlawful employment arrangement (D-14).

Captured during the first end-to-end test session, at step `constraints`. The
tool asked the candidate whether he would take work "as autónomo/falso
autónomo". The owner's correction is the whole of this module's subject:

> About "falso autónomo", this is a bad thing, not something someone wants to
> work of. Maybe you should have asked: "Are you autónomo?", or rather, given
> he is looking for a job, "Would you consider to become autónomo or you
> prefer payroll?"

*Falso autónomo* — being engaged as a self-employed contractor while working
under the direction, hours and dependence of an employee — is an unlawful
arrangement in Spain, not an employment mode on a menu. Genuine self-employment
is fine to offer; the sham version never is.

**The lawful set is already settled in data, and this module reads it rather
than re-deciding it.** `jobsearch.candidate.EmploymentModeName` is
`Literal["employed", "contracting"]` — two modes, both lawful, and *falso
autónomo* is not among them. So the code already knew; only the prose strayed.

## What is measured, and why it is not the obvious thing

The obvious check — "does any skill contain the string *falso autónomo*" —
would have passed on the day the defect happened, because no skill contained
it. The bad question was improvised, and it was improvised because the
constraints skill requires `employment_mode` to end the step resolved
(`state = stated | declined | unknown`, never blank) while saying nothing at
all about how that question may be put. Silence is what produced the offer.

So a skill counts as **offering** an unlawful arrangement when either half
holds:

1. it names an unlawful arrangement somewhere its prose is telling the model
   what to say, without ruling it out — the regression limb; or
2. it is the skill that must resolve the employment-mode constraint, and it
   carries no rule ruling the unlawful arrangement out — the silence limb,
   which is the state the live session was actually in.

Limb 2 is the reason this gate is not inert. A metric that reads `0` both
before and after a fix measures nothing, and this repository has been bitten
by that shape more than once (see `jobsearch.connector_contract`'s note on
measuring the real decision rather than a restatement of the rule).

**Which skill owns the question is derived, never listed here.** The owning
step is the one whose `produces` includes `constraints` in
`status/spec-v2-steps.json`, and the field itself comes from
`jobsearch.candidate.CONSTRAINT_FIELD_NAMES`. Hardcoding "step-02" would go
stale the first time the process is renumbered — which is precisely what
`skill_dir_name` exists to prevent.

## What licenses a mention

A skill may — must, under limb 2 — name the unlawful arrangement in order to
forbid it. A mention is licensed when its own line says both that the
arrangement is unlawful and that it is never to be offered: an **illegality**
marker and a **prohibition** marker on the same line. Two markers rather than
one, because either alone admits the sentence that caused this task ("some
employers offer falso autónomo, which is not ideal") while refusing nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict

from jobsearch.candidate import CONSTRAINT_FIELD_NAMES, EmploymentModeName
from jobsearch.process_spec import Step, StepList, load_steps
from jobsearch.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-14.json"

# The constraint field whose question produced the defect, and the artefact
# whose producing step owns it. Both are names that exist in data elsewhere —
# `CONSTRAINT_FIELD_NAMES` and each step's `produces` — and this module asserts
# the first still exists rather than assuming it.
EMPLOYMENT_MODE_FIELD = "employment_mode"
CONSTRAINTS_ARTEFACT = "constraints"

# The lawful modes, read from the type that already settles them. Recorded in
# the evidence so a reader can see what the check considered permissible
# without opening this file.
LAWFUL_MODES: tuple[str, ...] = tuple(get_args(EmploymentModeName))

# Arrangements that are unlawful rather than merely unattractive: they may be
# asked about as a *status* ("are you being engaged this way?") but never put
# to a candidate as a choice. Spelled with and without the accent because a
# skill's prose may use either, and the ASCII form is the one a hurried edit
# reaches for.
UNLAWFUL_ARRANGEMENTS: tuple[str, ...] = (
    "falso autónomo",
    "falso autonomo",
    "falsos autónomos",
    "falsos autonomos",
    "false self-employment",
    "bogus self-employment",
)

# An unlawful arrangement is named legitimately only to forbid it, so a
# licensed mention says both things on its own line: that the thing is against
# the law, and that it is never offered.
_ILLEGALITY_MARKERS: tuple[str, ...] = ("illegal", "unlawful", "against the law")
_PROHIBITION_MARKERS: tuple[str, ...] = ("never", "not ", "no ")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillReading(Strict):
    """One step skill's answer to "does it offer an unlawful arrangement?"

    Every field is something read off the file. `reasons` carries the specific
    shortfall so a non-zero measurement is legible without re-running the
    check by hand.
    """

    step: str
    n: int
    skill_dir: str
    skill_md_exists: bool
    owns_employment_mode: bool
    licensed_mentions: tuple[str, ...] = ()
    unlicensed_mentions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    @property
    def offers(self) -> bool:
        return bool(self.reasons)


def owns_employment_mode(step: Step) -> bool:
    """Does this step have to leave the employment-mode constraint resolved?

    Derived twice over: the artefact from the step's own `produces`, and the
    field from the pinned constraint set. A rename on either side makes this
    return `False` for every step, which `measure` reports as a shortfall
    rather than passing quietly — the divisor mistake `step_skills` warns
    about, in its "nothing was measured" form.
    """
    return CONSTRAINTS_ARTEFACT in step.produces and EMPLOYMENT_MODE_FIELD in CONSTRAINT_FIELD_NAMES


def _mentions(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split every line naming an unlawful arrangement into licensed and not."""
    licensed: list[str] = []
    unlicensed: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if not any(term in lowered for term in UNLAWFUL_ARRANGEMENTS):
            continue
        forbids = any(marker in lowered for marker in _ILLEGALITY_MARKERS) and any(
            marker in lowered for marker in _PROHIBITION_MARKERS
        )
        (licensed if forbids else unlicensed).append(line)
    return tuple(licensed), tuple(unlicensed)


def read_skill(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> SkillReading:
    """This step's `SkillReading` — read off its SKILL.md, never asserted."""
    directory = skill_dir_name(step)
    skill_md = skills_dir / directory / "SKILL.md"
    owns = owns_employment_mode(step)

    if not skill_md.is_file():
        # A missing skill cannot offer anything, and S7's gate already owns
        # "every step has a skill". Reported, not counted — a step measured
        # twice for one absence is a number that overstates the problem.
        return SkillReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=False,
            owns_employment_mode=owns,
        )

    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        return SkillReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=True,
            owns_employment_mode=owns,
            reasons=(f"SKILL.md could not be read: {exc}",),
        )

    licensed, unlicensed = _mentions(text)
    reasons: list[str] = []
    for line in unlicensed:
        reasons.append(f"names an unlawful arrangement without ruling it out: {line!r}")
    if owns and not licensed:
        reasons.append(
            f"resolves the {EMPLOYMENT_MODE_FIELD!r} constraint but carries no rule ruling "
            f"an unlawful arrangement out, so the question's phrasing is left to improvisation "
            f"(lawful modes: {', '.join(LAWFUL_MODES)})"
        )

    return SkillReading(
        step=step.id,
        n=step.n,
        skill_dir=directory,
        skill_md_exists=True,
        owns_employment_mode=owns,
        licensed_mentions=licensed,
        unlicensed_mentions=unlicensed,
        reasons=tuple(reasons),
    )


def probe(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[SkillReading]:
    """Every settled step's reading, in step order."""
    steps = steps or load_steps()
    return [read_skill(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def measure(
    steps_path: Path | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> dict[str, Any]:
    """D-14's gate reading: `skills_offering_an_illegal_employment_mode`."""
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, not a crash
        return {
            "skills_offering_an_illegal_employment_mode": -1,
            "steps_checked": 0,
            "owning_steps": [],
            "lawful_modes": list(LAWFUL_MODES),
            "unlawful_arrangements": list(UNLAWFUL_ARRANGEMENTS),
            "offenders": [{"step": None, "reasons": [f"step list could not be loaded: {exc}"]}],
            "readings": [],
        }

    readings = probe(steps, skills_dir)
    offenders = [reading for reading in readings if reading.offers]

    return {
        "skills_offering_an_illegal_employment_mode": len(offenders),
        "steps_checked": len(readings),
        "owning_steps": [r.step for r in readings if r.owns_employment_mode],
        "lawful_modes": list(LAWFUL_MODES),
        "unlawful_arrangements": list(UNLAWFUL_ARRANGEMENTS),
        "offenders": [
            {"step": r.step, "skill_dir": r.skill_dir, "reasons": list(r.reasons)}
            for r in offenders
        ],
        "readings": [r.model_dump(mode="json") for r in readings],
    }


def write_evidence(
    evidence: Path = DEFAULT_EVIDENCE_PATH,
    steps_path: Path | None = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-14.json`."""
    measured = measure(steps_path, skills_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.employment_mode [--check] [--write-evidence [PATH]]`.

    Without `--check` the evidence file is written, so the plain no-argument
    invocation `make evidence` performs regenerates D-14's number. That is the
    whole reason this measurement lives in a module of its own rather than
    behind a flag on `step_skills`: `make evidence` runs each module once with
    no arguments, so a gate reachable only via a flag is a gate whose drift
    nothing notices.
    """
    parser = argparse.ArgumentParser(description="D-14's gate over the step skills")
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
        help="write evidence JSON to PATH (default: status/evidence/D-14.json)",
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
    if not measured["owning_steps"]:
        print(
            f"no step produces {CONSTRAINTS_ARTEFACT!r} — the silence limb checked nothing, "
            "so this measurement is not the one D-14 asks for",
            file=sys.stderr,
        )
        return 3
    for offender in measured["offenders"]:
        print(f"{offender['step']}: {'; '.join(offender['reasons'])}", file=sys.stderr)
    return 1 if measured["offenders"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
