"""No step boundary closes by offering to end the session (D-15).

Captured during the first end-to-end test session, at step `constraints`. The
owner's correction is the whole of this module's subject:

> Don't ask to let the session so soon, just ask if you see it is taking too
> much time.

A candidate who answers four steps was asked four separate times whether he
would rather leave. Each offer is courteous on its own; four in a row read as
the tool losing interest, and §2.5's *right* to decline becomes a standing
*suggestion* to go.

## The requirement already existed — in the one place the model never reads

`status/spec-v2-steps.md` carries this as the fourth of its four cross-cutting
rules, and has since the document was settled:

    **Invite forward, do not offer an exit.** ... Stopping is always allowed and
    never the default suggestion.

Two things then diverged from it, in opposite directions, and the live session
sat exactly between them. The step spec's own per-step **Boundary** examples
contradicted the rule four times over — steps 1, 4, 5 and 10 closed with *"or
leave it here?"*, *"Leave it there?"*, *"or pause?"* and *"or leave it?"* — and
`status/spec-v2-process.md` §3.2 positively required the offer ("A step ends by
naming what was gained, offering the next thing, **and offering to stop**").
Meanwhile every step skill — the prose actually put in front of the model —
copied the examples verbatim and carried no rule at all.

So the model was given four worked demonstrations of the behaviour and zero
statements of the rule forbidding it. It behaved exactly as instructed.

## What is measured, and why it is not the obvious thing

The obvious check — "does any Boundary example contain *leave it here*" — is
limb 1, and it is the limb that would be satisfied forever by one afternoon's
rewriting. It does not protect anything: the next skill written from the spec's
shape reintroduces the offer, because nothing in the skill says not to.

So a step counts as **offering an exit** when either half holds:

1. what the skill says out loud at the boundary — its fenced example, the text
   a model copies — offers stopping as an alternative to carrying on; or
2. the skill's Boundary section carries no rule governing the offer, so whether
   the exit is named is left to improvisation from the example.

Limb 2 is the state the whole library was in on the day of the session, and it
is what makes this gate bite rather than decorate. A metric that reads `0` both
before and after the fix measures nothing — the shape this repository has been
bitten by more than once.

**The two limbs read different halves of the section, deliberately.** Limb 1
reads only fenced blocks, limb 2 only the prose around them. Without that split
the rule sentence ("the exit is offered only when the session has actually run
long") would trip the very check it satisfies, and the gate would be
unsatisfiable by any skill that stated its own rule.

## Why the spec is read rather than restated

`measure` reports `-1` — never a clean `0` — when the cross-cutting rule can no
longer be found in the step spec. This module measures conformance to a
requirement it does not own: if the project decides boundaries *should* offer an
exit, the rule goes and this gate must stop reading as a pass, not carry on
enforcing a policy nobody holds any more. A measurement is not allowed to look
healthiest at the moment it stops measuring the thing it was named for.
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
from jobsearch.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-15.json"
DEFAULT_STEPS_DOC = _REPO_ROOT / "status" / "spec-v2-steps.md"

# The cross-cutting rule this module enforces, as it appears in the step spec.
# Matched rather than restated: see the docstring's closing section.
CROSS_CUTTING_RULE_RE = re.compile(r"invite\s+forward,?\s+do\s+not\s+offer\s+an\s+exit", re.I)

# The `## Boundary` section of a SKILL.md, up to the next heading of any level.
_BOUNDARY_RE = re.compile(r"^##\s+Boundary\s*$(?P<body>.*?)(?=^#{1,6}\s|\Z)", re.M | re.S)

# Fenced blocks — what the skill says out loud. Everything else in the section
# is prose about how to say it.
_FENCE_RE = re.compile(r"^```[^\n]*\n(?P<inner>.*?)^```\s*$", re.M | re.S)

# Offering to stop, in spoken text. Every alternative names *ending the sitting*
# — not declining a subject (§5.4's business) and not deferring an artefact:
# step 11's "Ready to send, or sit on it?" chooses between two ways forward and
# is deliberately not matched.
#
# The list is enumerated rather than semantic, so it is only ever as good as its
# coverage: review found "wrap up here?", "end here?" and "take a break and
# resume tomorrow?" passing straight through an earlier cut. Widened here, and
# it will need widening again — a boundary that states its rule and then
# contradicts it in the example is the only case limb 2 does not already catch,
# which is what bounds the damage when a phrasing is missing.
_EXIT_OFFER_RE = re.compile(
    r"\b(?:"
    r"leave\s+(?:it|that|this|things)\b"
    r"|or\s+pause\b|pause\s+(?:here|there|for\s+(?:now|today))\b"
    r"|stop\s+(?:here|there|for\s+(?:now|today))\b|or\s+stop\b"
    r"|call\s+it\s+(?:a\s+day|there|quits)\b"
    r"|wrap\s+(?:it\s+|things\s+|up\s+)?up\b|wrap\s+up\b"
    r"|end\s+(?:it\s+)?(?:here|there|for\s+(?:now|today))\b|end\s+the\s+session\b"
    r"|take\s+a\s+break\b|have\s+a\s+break\b"
    r"|resume\s+(?:later|tomorrow|another\s+(?:time|day))\b"
    r"|had\s+enough\b|enough\s+for\s+(?:now|today|one\s+(?:day|sitting|go))\b"
    r"|that'?s\s+it\s+for\s+(?:now|today)\b"
    r"|come\s+back\s+(?:to\s+(?:it|this)\s+)?(?:later|another\s+(?:time|day))\b"
    r"|pick\s+(?:it|this)\s+up\s+(?:later|another\s+(?:time|day))\b"
    r")"
)

# §3.3's **offered skip**, which is not the exit and must never be counted as
# one. The process calls two different things stopping, and only one of them
# ends the sitting:
#
#   - the *exit* — the candidate leaves, and comes back another day;
#   - the *skip* — *"we can stop here and go look at real jobs with what I
#     have"* — the candidate stops the first-run climb and goes **forward** to a
#     provisional L1 ranking, sooner and rougher.
#
# `spec-v2-process.md` §3.3 requires the skip at the end of **every** first-run
# step, so a check that read its prescribed sentence as an exit offer would make
# the required behaviour unimplementable: a compliant boundary would fail
# `step_boundaries_offering_an_exit == 0`, and the gate would enforce the
# opposite of the process contract. Found by review, and the same false positive
# step 11's "Ready to send, or sit on it?" already had a case for — one forward
# choice was excluded and the other, the mandated one, was not.
#
# The licence requires a forward *destination*, not merely a soft word: the line
# has to name going on to the jobs, the offers, or the provisional ranking now.
# A genuine exit offer cannot be laundered through it, because a sentence that
# sends the candidate to their ranking is the skip.
_FORWARD_SHORTCUT_RE = re.compile(
    r"\b(?:go(?:ing)?\s+(?:and\s+)?(?:to\s+)?)?(?:look\s+at|see|show\s+you|going\s+to)\s+"
    r"(?:some\s+|the\s+|a\s+|real\s+|new\s+)*(?:jobs|offers|adverts|ads|roles|list|ranking)\b"
    r"|\bwith\s+what\s+i(?:'ve\s+got|\s+have|\s+know)\b"
    r"|\bprovisional\s+(?:ranking|list)\b"
    r"|\bfirst\s+pass\b",
    re.I,
)

# A Boundary's prose governs the offer when one paragraph both names the thing
# and constrains it. Two markers rather than one, for the reason D-14 records:
# either alone admits a paragraph that mentions the subject and requires
# nothing of it.
_EXIT_SUBJECT_RE = re.compile(
    r"\b(?:offer(?:s|ed|ing)?\s+to\s+stop|offer\s+an\s+exit|the\s+exit\b"
    r"|end\s+the\s+session|invite\s+forward)\b",
    re.I,
)
_GOVERNS_RE = re.compile(r"\b(?:never|must\s+not|do(?:es)?\s+not|only\s+when|only\s+if)\b", re.I)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundaryReading(Strict):
    """One step skill's answer to "does its boundary offer an exit?"

    Every field is read off the file. `reasons` carries the specific shortfall,
    so a non-zero measurement is legible without re-running the check by hand.
    """

    step: str
    n: int
    skill_dir: str
    skill_md_exists: bool
    has_boundary_section: bool = False
    spoken_examples: int = 0
    exit_offers: tuple[str, ...] = ()
    forward_shortcuts: tuple[str, ...] = ()
    states_the_rule: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def offers(self) -> bool:
        return bool(self.reasons)


def rule_is_declared(steps_doc: Path = DEFAULT_STEPS_DOC) -> bool:
    """Does the step spec still forbid closing a step with an exit offer?"""
    try:
        return bool(CROSS_CUTTING_RULE_RE.search(steps_doc.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def boundary_section(text: str) -> str | None:
    """The `## Boundary` section's body, or None if the skill has no boundary."""
    match = _BOUNDARY_RE.search(text)
    return match.group("body") if match else None


def split_spoken_and_prose(section: str) -> tuple[tuple[str, ...], str]:
    """The section's fenced blocks, and the prose with those blocks removed.

    The split is what lets a skill state the rule without the statement being
    read as the behaviour it forbids.
    """
    spoken = tuple(m.group("inner") for m in _FENCE_RE.finditer(section))
    return spoken, _FENCE_RE.sub("\n", section)


def _exit_offers(spoken: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split every spoken line that names stopping into exit offers and §3.3 skips.

    Returned as two tuples rather than one count, so the evidence records what
    was excluded and why. A check that silently drops the lines it decided not
    to count is one nobody can audit.
    """
    offers: list[str] = []
    skips: list[str] = []
    for block in spoken:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or not _EXIT_OFFER_RE.search(line.lower()):
                continue
            (skips if _FORWARD_SHORTCUT_RE.search(line) else offers).append(line)
    return tuple(offers), tuple(skips)


def _states_the_rule(prose: str) -> bool:
    """Does one paragraph of the prose both name the exit and constrain it?"""
    for paragraph in re.split(r"\n\s*\n", prose):
        joined = " ".join(paragraph.split())
        if _EXIT_SUBJECT_RE.search(joined) and _GOVERNS_RE.search(joined):
            return True
    return False


def read_boundary(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> BoundaryReading:
    """This step's `BoundaryReading` — read off its SKILL.md, never asserted."""
    directory = skill_dir_name(step)
    skill_md = skills_dir / directory / "SKILL.md"

    if not skill_md.is_file():
        # A missing skill has no boundary to get wrong, and S7's gate already
        # owns "every step has a skill". Reported, not counted — a step charged
        # twice for one absence is a number that overstates the problem.
        return BoundaryReading(
            step=step.id, n=step.n, skill_dir=directory, skill_md_exists=False
        )

    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # `UnicodeDecodeError` is a `ValueError`, not an `OSError` — catching
        # only the latter let undecodable prose crash the measurement instead
        # of recording it (D-14's third review finding).
        return BoundaryReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=True,
            reasons=(f"SKILL.md could not be read: {exc}",),
        )

    section = boundary_section(text)
    if section is None:
        return BoundaryReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=True,
            reasons=(
                "carries no `## Boundary` section, so neither what it says at the step's end "
                "nor the rule governing it can be read",
            ),
        )

    spoken, prose = split_spoken_and_prose(section)
    offers, shortcuts = _exit_offers(spoken)
    states_rule = _states_the_rule(prose)

    reasons: list[str] = []
    for line in offers:
        reasons.append(f"closes the step by offering to stop: {line!r}")
    if not states_rule:
        reasons.append(
            "carries no rule governing when the exit is offered, so whether to name it is "
            "left to improvisation from the example"
        )
    if not spoken:
        # The boundary is defined as what is said out loud, so a section with
        # no example leaves the regression limb reading nothing at all.
        reasons.append(
            "carries no spoken example, so there is no boundary text to check for an exit offer"
        )

    return BoundaryReading(
        step=step.id,
        n=step.n,
        skill_dir=directory,
        skill_md_exists=True,
        has_boundary_section=True,
        spoken_examples=len(spoken),
        exit_offers=offers,
        forward_shortcuts=shortcuts,
        states_the_rule=states_rule,
        reasons=tuple(reasons),
    )


def probe(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[BoundaryReading]:
    """Every settled step's reading, in step order."""
    steps = steps or load_steps()
    return [read_boundary(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def _unmeasured(reason: str, readings: list[BoundaryReading]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "step_boundaries_offering_an_exit": -1,
        "steps_checked": len(readings),
        "boundaries_checked": sum(1 for r in readings if r.has_boundary_section),
        "rule_declared_in_step_spec": False,
        "offenders": [{"step": None, "skill_dir": None, "reasons": [reason]}],
        "readings": [r.model_dump(mode="json") for r in readings],
    }


def measure(
    steps_path: Path | None = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    steps_doc: Path = DEFAULT_STEPS_DOC,
) -> dict[str, Any]:
    """D-15's gate reading: `step_boundaries_offering_an_exit`."""
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, not a crash
        return _unmeasured(f"step list could not be loaded: {exc}", [])

    readings = probe(steps, skills_dir)

    if not rule_is_declared(steps_doc):
        # The requirement, not the conformance, has gone. Reporting `0` here
        # would enforce a policy the project no longer holds while looking like
        # a clean pass; `-1` says the gate is no longer measuring D-15.
        return _unmeasured(
            f"{steps_doc.name} no longer declares 'Invite forward, do not offer an exit', "
            "so this gate is not measuring the requirement D-15 names",
            readings,
        )

    if not any(r.has_boundary_section for r in readings):
        return _unmeasured(
            "no step skill carries a `## Boundary` section — nothing was checked", readings
        )

    offenders = [reading for reading in readings if reading.offers]
    return {
        "step_boundaries_offering_an_exit": len(offenders),
        "steps_checked": len(readings),
        "boundaries_checked": sum(1 for r in readings if r.has_boundary_section),
        "rule_declared_in_step_spec": True,
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
    steps_doc: Path = DEFAULT_STEPS_DOC,
) -> dict[str, Any]:
    """Measure and record `status/evidence/D-15.json`."""
    measured = measure(steps_path, skills_dir, steps_doc)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.session_exit [--check] [--write-evidence [PATH]]`.

    Without `--check` the evidence file is written, so the plain no-argument
    invocation `make evidence` performs regenerates D-15's number — the same
    reason D-14's measurement is a module of its own: a gate reachable only
    behind a flag is a gate whose drift nothing notices.
    """
    parser = argparse.ArgumentParser(description="D-15's gate over the step skills' boundaries")
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
        help="write evidence JSON to PATH (default: status/evidence/D-15.json)",
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
    if measured["step_boundaries_offering_an_exit"] == -1:
        for offender in measured["offenders"]:
            print("; ".join(offender["reasons"]), file=sys.stderr)
        return 3
    for offender in measured["offenders"]:
        print(f"{offender['step']}: {'; '.join(offender['reasons'])}", file=sys.stderr)
    return 1 if measured["offenders"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
