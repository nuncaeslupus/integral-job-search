"""No step skill opens a silent stretch of work on a waiting candidate (D-13).

Captured during the first end-to-end test session, at step `intake`. The
owner's correction is the whole of this module's subject:

> You are doing a lot of things and the user is waiting. You should answer the
> user and tell him "Nice to meet you, XXX. Let me prepare the environment, it
> will take a moment" or similar. Then, you prepare the folders, run your
> scripts and finally answer something like "Thanks for waiting, XXX / Here's
> how this works..."

What the candidate actually saw, having just given his name, was
`Skill(step-02-constraints) Successfully loaded` and a run of Bash calls with
no narration at all. Nothing in the conversation told him whether the tool was
working, waiting on him, or hung.

## Why this is a rule and not a stylistic preference

Every one of the thirteen steps does work the candidate waits through: step 0
creates their profile tree before a word of the process is explained, every
step writes evidence rows as it goes, and every step runs its checkpoint
script before it ends. The silence is therefore structural — it is not a
property of one badly written skill, and it recurs at every step boundary.

§5.4 of the process spec already required the tool to **say why** — each step
opens with what it is for and what it will store. That governs the *subject*
of a step. It says nothing about the seconds in which the tool is executing,
which is the interval the candidate was actually sitting in. So the rule was
absent rather than broken, and the model, given no instruction, did the
efficient thing and worked in silence.

## What is measured, and why it is not the obvious thing

The obvious check — "does the library mention saying what it is doing" —
passes on one sentence pasted into thirteen files, and D-15's review round is
the record of why that is not enough: the model copies the **example**, and a
rule with no worked example is left to improvisation. The complaint that
started this task is precisely a model behaving well given the demonstrations
it had.

So a skill counts as **lacking a progress disclosure rule** when any limb
holds:

1. its `## Protocol` prose carries no rule governing what is said before work
   the candidate waits through — the limb the whole library failed on the day
   of the session;
2. it carries no spoken example performing the disclosure — a line naming the
   work *and* marking the wait, which is the text a model copies; or
3. at the step where the candidate first says who they are, its spoken
   example names the work before acknowledging the person. That is the
   reported defect in its exact shape: the acknowledgement is not optional and
   it is not afterwards.

Limbs 1 and 2 read different halves of the section — limb 1 only the prose,
limb 2 only the fenced blocks — for the reason `session_exit` records: without
the split, the sentence stating the rule would trip the check it satisfies.

## Why the spec is read rather than restated

`measure` reports `-1` — never a clean `0` — when the cross-cutting rule can
no longer be found in the step spec. This module measures conformance to a
requirement it does not own: if the project decides the narration is noise,
the rule goes and this gate must stop reading as a pass rather than carry on
enforcing a policy nobody holds. A measurement is not allowed to look
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
from jobsearch.session_exit import split_spoken_and_prose
from jobsearch.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "D-13.json"
DEFAULT_STEPS_DOC = _REPO_ROOT / "status" / "spec-v2-steps.md"

# The cross-cutting rule this module enforces, as it appears in the step spec.
# Matched rather than restated: see the docstring's closing section.
CROSS_CUTTING_RULE_RE = re.compile(r"say\s+what\s+is\s+happening\s+before\s+a\s+silence", re.I)

# The `## Protocol` section of a SKILL.md — "the manner, not the mechanism" —
# up to the next heading of any level. The manner is where this rule belongs:
# `## Boundary` is what is said when a step *ends*, and the silence being
# measured happens in the middle of one.
_PROTOCOL_RE = re.compile(r"^##\s+Protocol\b(?P<body>.*?)(?=^#{1,6}\s|\Z)", re.M | re.S)

# --- limb 1: the rule, read from the prose ---------------------------------
#
# Two markers rather than one, for the reason D-14 records: either alone admits
# a paragraph that mentions the subject and requires nothing of it. The two
# vocabularies are kept disjoint — no word is both a subject and a governor —
# because a paragraph satisfying both halves with the same token is a
# one-marker check wearing a two-marker shape.
_DISCLOSURE_SUBJECT_RE = re.compile(
    r"\b(?:"
    r"say(?:s|ing)?\s+what\s+(?:is\s+happening|it\s+is\s+doing|you(?:'re|\s+are)\s+doing)"
    r"|name(?:s|d|ing)?\s+(?:the\s+)?work\b"
    r"|in\s+silence\b"
    r"|silent(?:ly)?\s+(?:setup|run|stretch|work|calls)\b"
    r"|(?:they|he|she|the\s+candidate)\s+waits?\s+through\b"
    r"|while\s+(?:they|the\s+candidate)\s+waits?\b"
    r"|keep(?:s|ing)?\s+(?:them|the\s+candidate)\s+waiting\b"
    r"|progress\s+disclosure\b"
    r")",
    re.I,
)
# Ordering and prohibition. `before` and `first` matter as much as `never`
# here: the defect this gate exists for is not that the tool said nothing, but
# that it said it afterwards.
_GOVERNS_RE = re.compile(
    r"\b(?:never|must\s+not|do(?:es)?\s+not|always|before|first(?:,|\s)|only\s+(?:when|if))",
    re.I,
)

# --- limb 2: the demonstration, read from the fenced blocks ----------------
#
# Two markers again, and for the same reason: "one moment" alone is a pause
# with no subject, and "saving that" alone is a claim the candidate has no way
# to wait through. The disclosure is the pair.
_WAIT_MARKER_RE = re.compile(
    r"\b(?:"
    r"(?:give\s+me\s+|just\s+)?(?:a|one)\s+(?:moment|sec|second|minute)\b"
    r"|take[sn]?\s+a\s+(?:moment|second|minute)\b"
    r"|bear\s+with\s+me\b|hold\s+on\b|won'?t\s+be\s+long\b"
    r"|thanks?\s+(?:you\s+)?for\s+waiting\b"
    r")",
    re.I,
)
_WORK_MARKER_RE = re.compile(
    r"\b(?:set(?:ting)?\s+(?:up|it\s+up)|sav(?:e|ing)|writ(?:e|ing)|record(?:ing)?"
    r"|check(?:ing)?|prepar(?:e|ing)|read(?:ing)?|pull(?:ing)?|fetch(?:ing)?"
    r"|search(?:ing)?|scor(?:e|ing)|rank(?:ing)?|re-?rank(?:ing)?|draft(?:ing)?"
    r"|(?:work|turn)(?:ing)?\s+(?:that|those|them)\s+(?:in|into)"
    r"|go(?:ing)?\s+through)\b",
    re.I,
)

# --- limb 3: the acknowledgement, at first contact --------------------------
#
# Which step this applies to is read from the settled step list — `n == 0` —
# and deliberately **not** from a regex over the skill's prose. The first cut
# detected it by looking for "creates their profile" in the text, and every one
# of the thirteen skills matched: the shared rule sentence names profile
# creation, so the probe found the rule rather than the behaviour and reported
# twelve false offenders. A check whose subject is named by the very sentence
# that satisfies it is the self-trip `session_exit` split its two limbs to
# avoid, in a second disguise.
_ACKNOWLEDGEMENT_RE = re.compile(
    r"\b(?:nice\s+to\s+meet\s+you|good\s+to\s+meet\s+you|hello|hi\b|hey\b|welcome\b"
    r"|thanks,|thank\s+you,|right,|got\s+it\b|lovely\b|great,)",
    re.I,
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NarrationReading(Strict):
    """One step skill's answer to "does it say what it is doing?"

    Every field is read off the file. `reasons` carries the specific shortfall,
    so a non-zero measurement is legible without re-running the check by hand.
    """

    step: str
    n: int
    skill_dir: str
    skill_md_exists: bool
    has_protocol_section: bool = False
    spoken_examples: int = 0
    disclosures: tuple[str, ...] = ()
    states_the_rule: bool = False
    first_contact: bool = False
    acknowledges_first: bool | None = None
    reasons: tuple[str, ...] = ()

    @property
    def lacks_the_rule(self) -> bool:
        return bool(self.reasons)


def rule_is_declared(steps_doc: Path = DEFAULT_STEPS_DOC) -> bool:
    """Does the step spec still require narration before a silent stretch?"""
    try:
        return bool(CROSS_CUTTING_RULE_RE.search(steps_doc.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError):
        return False


def protocol_section(text: str) -> str | None:
    """The `## Protocol` section's body, or None if the skill has no protocol."""
    match = _PROTOCOL_RE.search(text)
    return match.group("body") if match else None


def _states_the_rule(prose: str) -> bool:
    """Does one paragraph both name the silence and govern what is said in it?"""
    for paragraph in re.split(r"\n\s*\n", prose):
        joined = " ".join(paragraph.split())
        if _DISCLOSURE_SUBJECT_RE.search(joined) and _GOVERNS_RE.search(joined):
            return True
    return False


def _disclosures(spoken: tuple[str, ...]) -> tuple[str, ...]:
    """Every spoken line that names the work *and* marks the wait, in order."""
    found: list[str] = []
    for block in spoken:
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if _WAIT_MARKER_RE.search(line) and _WORK_MARKER_RE.search(line):
                found.append(line)
    return tuple(found)


def _acknowledges_before_the_work(spoken: tuple[str, ...]) -> bool:
    """In the block that discloses, does the person come before the setup?

    Read as character offsets inside one block rather than as a property of
    the library, because that is the defect exactly: the acknowledgement and
    the work were both present in the transcript, in the wrong order.
    """
    for block in spoken:
        disclosure = _WAIT_MARKER_RE.search(block)
        if disclosure is None or not _WORK_MARKER_RE.search(block):
            continue
        greeting = _ACKNOWLEDGEMENT_RE.search(block)
        work = _WORK_MARKER_RE.search(block)
        if greeting is not None and work is not None and greeting.start() < work.start():
            return True
    return False


def read_narration(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> NarrationReading:
    """This step's `NarrationReading` — read off its SKILL.md, never asserted."""
    directory = skill_dir_name(step)
    skill_md = skills_dir / directory / "SKILL.md"

    if not skill_md.is_file():
        # A missing skill has no protocol to get wrong, and S7's gate already
        # owns "every step has a skill". Reported, not counted — a step charged
        # twice for one absence is a number that overstates the problem.
        return NarrationReading(step=step.id, n=step.n, skill_dir=directory, skill_md_exists=False)

    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # `UnicodeDecodeError` is a `ValueError`, not an `OSError` — catching
        # only the latter let undecodable prose crash the measurement instead
        # of recording it (D-14's third review finding).
        return NarrationReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=True,
            reasons=(f"SKILL.md could not be read: {exc}",),
        )

    section = protocol_section(text)
    if section is None:
        return NarrationReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            skill_md_exists=True,
            reasons=(
                "carries no `## Protocol` section, so neither the rule governing what is said "
                "during the work nor an example of saying it can be read",
            ),
        )

    spoken, prose = split_spoken_and_prose(section)
    disclosures = _disclosures(spoken)
    states_rule = _states_the_rule(prose)
    first_contact = step.n == 0
    acknowledges_first = _acknowledges_before_the_work(spoken) if first_contact else None

    reasons: list[str] = []
    if not states_rule:
        reasons.append(
            "carries no rule governing what is said before work the candidate waits through, "
            "so whether to narrate it is left to improvisation from the example"
        )
    if not disclosures:
        reasons.append(
            "carries no spoken example naming the work and marking the wait, so the text a "
            "model copies still opens the silence without a word"
        )
    if first_contact and not acknowledges_first:
        reasons.append(
            "is where the candidate first says who they are, and its spoken example names the "
            "setup before it acknowledges them — the reported defect in its exact shape"
        )

    return NarrationReading(
        step=step.id,
        n=step.n,
        skill_dir=directory,
        skill_md_exists=True,
        has_protocol_section=True,
        spoken_examples=len(spoken),
        disclosures=disclosures,
        states_the_rule=states_rule,
        first_contact=first_contact,
        acknowledges_first=acknowledges_first,
        reasons=tuple(reasons),
    )


def probe(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[NarrationReading]:
    """Every settled step's reading, in step order."""
    steps = steps or load_steps()
    return [read_narration(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def _unmeasured(reason: str, readings: list[NarrationReading]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "step_skills_without_a_progress_disclosure_rule": -1,
        "steps_checked": len(readings),
        "protocols_checked": sum(1 for r in readings if r.has_protocol_section),
        "rule_declared_in_step_spec": False,
        "offenders": [{"step": None, "skill_dir": None, "reasons": [reason]}],
        "readings": [r.model_dump(mode="json") for r in readings],
    }


def measure(
    steps_path: Path | None = None,
    skills_dir: Path = DEFAULT_SKILLS_DIR,
    steps_doc: Path = DEFAULT_STEPS_DOC,
) -> dict[str, Any]:
    """D-13's gate reading: `step_skills_without_a_progress_disclosure_rule`."""
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, not a crash
        return _unmeasured(f"step list could not be loaded: {exc}", [])

    readings = probe(steps, skills_dir)

    if not rule_is_declared(steps_doc):
        # The requirement, not the conformance, has gone. Reporting `0` here
        # would enforce a policy the project no longer holds while looking like
        # a clean pass; `-1` says the gate is no longer measuring D-13.
        return _unmeasured(
            f"{steps_doc.name} no longer declares 'Say what is happening before a silence', "
            "so this gate is not measuring the requirement D-13 names",
            readings,
        )

    if not any(r.has_protocol_section for r in readings):
        return _unmeasured(
            "no step skill carries a `## Protocol` section — nothing was checked", readings
        )

    offenders = [reading for reading in readings if reading.lacks_the_rule]
    return {
        "step_skills_without_a_progress_disclosure_rule": len(offenders),
        "steps_checked": len(readings),
        "protocols_checked": sum(1 for r in readings if r.has_protocol_section),
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
    """Measure and record `status/evidence/D-13.json`."""
    measured = measure(steps_path, skills_dir, steps_doc)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.step_narration [--check] [--write-evidence [PATH]]`.

    Without `--check` the evidence file is written, so the plain no-argument
    invocation `make evidence` performs regenerates D-13's number — the same
    reason D-14's and D-15's measurements are modules of their own: a gate
    reachable only behind a flag is a gate whose drift nothing notices.
    """
    parser = argparse.ArgumentParser(description="D-13's gate over the step skills' protocols")
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
        help="write evidence JSON to PATH (default: status/evidence/D-13.json)",
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
    if measured["step_skills_without_a_progress_disclosure_rule"] == -1:
        for offender in measured["offenders"]:
            print("; ".join(offender["reasons"]), file=sys.stderr)
        return 3
    for offender in measured["offenders"]:
        print(f"{offender['step']}: {'; '.join(offender['reasons'])}", file=sys.stderr)
    return 1 if measured["offenders"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
