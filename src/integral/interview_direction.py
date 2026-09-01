"""The session offers where it should lead (T93).

Four notes from the same live session, one behaviour. The candidate asked to be
**directed** — *"You know what is needed, not the user, so saying it is better
than letting the user decide. You must justify your decisions and
recommendations."* — to be **drawn out** — *"You must induce the user to talk as
much as possible"* — and to be **followed up on** — *"Anything that intrigued
you about the CV or our conversation, you must pull the string."*

## What the defect actually was

Nothing in the runtime was wrong. `step_runtime.offered()` (T34) already answers
*which* steps may run, and T36 already makes re-entry an **offer, not an
action**. What reached the candidate was the wording, and the wording listed
options without ever saying which one the tool would pick or why:

    "Traits next — carry on?"
    "Want to see the new ones ranked?"
    "Carry on, or shall I show you a first pass now?"

Nine of the thirteen shipped closes read like that. Each is a menu handed to the
person with the least information in the room.

## The line this must not cross

**The choice stays the candidate's; the recommendation becomes ours.** An offer
with no recommendation attached is the defect. An offer the candidate declines
is not — so a close that has acquired a recommendation and lost the question
mark has traded one fault for a worse one, and `steps_overriding_a_decline`
counts exactly that.

## Why the measurement reads the shipped library

The strings this module checks are the ones a candidate hears: the fenced
`## Boundary` example in each of the thirteen step skills, which is the text a
model copies when it closes a step. Fixtures written for a test would measure
this module's author instead — T95 found a leak in a real shipped label for
precisely that reason. So the denominator is the shipped library, and it is
thirteen.

Regexes over prose can be satisfied by an author who writes to them, so
`NEGATIVE_CONTROLS` runs four synthetic closes through the same reader on every
measurement: three that must be rejected and one that must be accepted. A
reader that misjudges any of them cannot report a clean `0` — the metric goes
`-1` and `gate_status` reads `unmeasured`, because "could not be measured" must
never look healthier than "measured and dirty".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from integral.process_spec import Step, StepList, load_steps
from integral.session_exit import split_spoken_and_prose
from integral.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T93.json"

#: The step whose intake owns the CV, the follow-up and the artefact question.
INTAKE_STEP = "intake"

#: The invitation to talk freely has to arrive at the opening and come back.
#: Once is a disclaimer; the note asked for "the beginning and some other
#: times", so a single mention is not what was requested.
OPENING_STEP = "identify"
MINIMUM_OPEN_TALK_STEPS = 3

#: A field named in the intake artefact table that is *not* software. The
#: reported miss was a developer never asked for their repositories, and the
#: fix asked for is the general one — so a table that only knows about code has
#: reproduced the hardcoded GitHub prompt with extra steps.
MINIMUM_NON_SOFTWARE_ARTEFACT_FIELDS = 3

# Straight or curly: the library is written with ASCII apostrophes, but a line
# pasted out of a word processor must not read as a missing recommendation.
# Escaped rather than written literally: RUF001 refuses an ambiguous character
# in source, and it is right to — the two are indistinguishable in a diff.
_APOSTROPHE = "['\\u2019]?"

# Ours, said in the first person. A menu of equally weighted options is what
# this exists to fail, so "we could" and "shall we" are deliberately absent.
_RECOMMENDATION_RE = re.compile(
    rf"\bI{_APOSTROPHE}d\b|\bI would\b|\bI recommend\b|\bI suggest\b"
    r"|\bmy advice\b|\bif it were me\b",
    re.IGNORECASE,
)

# A causal connective joining the recommendation to something the candidate can
# weigh. Presence of a reason is checkable; its quality is not, which is why
# the negative controls carry a reasonless close rather than a weak one.
_REASON_RE = re.compile(
    rf"\bbecause\b|\bso that\b|\bso I can\b|\bso you\b|\bit{_APOSTROPHE}s what\b"
    rf"|\bthat{_APOSTROPHE}s what\b|\bwhich is what\b|\bthe quickest way\b"
    rf"|\bit lets\b|\bit means\b|\bthat{_APOSTROPHE}s where\b|\bwhich is why\b"
    r"|\botherwise\b",
    re.IGNORECASE,
)

# The T36 boundary, in the text: after the recommendation the candidate is still
# being asked, not told.
_CHOICE_RE = re.compile(
    rf"\?|\bsay if\b|\bup to you\b|\bif you{_APOSTROPHE}d rather\b|\bor shall\b",
    re.IGNORECASE,
)

_COERCION_RE = re.compile(
    r"\byou must\b|\byou have to\b|\byou need to\b|\bI need you to\b|\bwe have to\b"
    r"|\bnot optional\b|\bno choice\b|\bwhether you like\b",
    re.IGNORECASE,
)

# "this is a conversation, not a form" — the invitation to volunteer whatever
# the candidate has, including the things a CV has no box for.
_OPEN_TALK_RE = re.compile(
    r"\banecdote\b|\bspare time\b|\boutside work\b|\bgood or bad\b"
    r"|\bno wrong answer\b|\bwhatever comes to mind\b|\bnot a form\b"
    r"|\bthe more you tell me\b|\btangent\b",
    re.IGNORECASE,
)

# "pull the string" — a detail that does not explain itself gets one question.
_FOLLOW_UP_RE = re.compile(
    r"\bpull the string\b|\bunexplained\b|\bintrigu\w+\b|\bdoes not explain itself\b",
    re.IGNORECASE,
)

_ARTEFACT_RULE_RE = re.compile(r"\bartefacts?\b|\bwhat their field produces\b", re.IGNORECASE)

# The fallback that keeps the table a starting point rather than a closed
# vocabulary: a field with no row still gets the question.
_ARTEFACT_FALLBACK_RE = re.compile(
    r"\bnot on (?:this|the) list\b|\bno row\b|\bany other field\b"
    r"|\bnot listed\b|\bsomething else entirely\b",
    re.IGNORECASE,
)

SOFTWARE_FIELD_RE = re.compile(r"software|developer|engineer|programm", re.IGNORECASE)

_BOUNDARY_RE = re.compile(r"^##\s+Boundary\b(?P<body>.*?)(?=^#{1,6}\s|\Z)", re.M | re.S)
_PROTOCOL_RE = re.compile(r"^##\s+Protocol\b(?P<body>.*?)(?=^#{1,6}\s|\Z)", re.M | re.S)
_WHEN_DECLINED_RE = re.compile(r"^##\s+When declined\b", re.M)

#: A paragraph opening with a bold lead, plus everything up to the next one.
#: The skills state each protocol rule that way and put its worked example
#: immediately underneath, so this is how a rule is read together with the text
#: that demonstrates it — a rule with no example is what D-15 found the model
#: improvising around.
_RULE_CHUNK_RE = re.compile(r"(?=^\*\*)", re.M)

_TABLE_ROW_RE = re.compile(r"^\|(?P<first>[^|]*)\|(?P<rest>.*)\|\s*$", re.M)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CloseReading(Strict):
    """What one step's shipped close does and does not do.

    Recorded per step rather than counted, so the evidence file names the
    offender and the line, and a later reader can disagree with the verdict
    without re-running anything.
    """

    step: str
    n: int
    skill_dir: str
    skill_md_exists: bool = True
    spoken: tuple[str, ...] = ()
    has_recommendation: bool = False
    has_reason: bool = False
    leaves_the_choice: bool = False
    has_when_declined: bool = False
    coercive_lines: tuple[str, ...] = ()
    invites_open_ended_talk: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def lacks_a_recommendation(self) -> bool:
        """The gate's own limb: an offer that does not say which way, and why."""
        return not (self.has_recommendation and self.has_reason)

    @property
    def overrides_a_decline(self) -> bool:
        """T36's limb: directing that has stopped being an offer."""
        return bool(self.coercive_lines) or not self.leaves_the_choice


def _close_blocks(text: str) -> tuple[str, ...]:
    """The spoken examples of a skill's `## Boundary` section."""
    section = _BOUNDARY_RE.search(text)
    if section is None:
        return ()
    spoken, _ = split_spoken_and_prose(section.group("body"))
    return spoken


def rule_chunks(section: str) -> list[str]:
    """A protocol section split into `**bold lead**` rules with their examples."""
    return [chunk for chunk in _RULE_CHUNK_RE.split(section) if chunk.strip()]


def read_close(step_id: str, blocks: tuple[str, ...]) -> dict[str, Any]:
    """Judge a set of spoken closes. Shared by the library and the controls."""
    joined = "\n".join(blocks)
    coercive = tuple(
        line.strip()
        for block in blocks
        for line in block.splitlines()
        if line.strip() and _COERCION_RE.search(line)
    )
    return {
        "step": step_id,
        "spoken": blocks,
        "has_recommendation": bool(_RECOMMENDATION_RE.search(joined)),
        "has_reason": bool(_REASON_RE.search(joined)),
        "leaves_the_choice": bool(_CHOICE_RE.search(joined)),
        "coercive_lines": coercive,
    }


def read_skill(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> CloseReading:
    """This step's `CloseReading` — read off its SKILL.md, never asserted."""
    directory = skill_dir_name(step)
    skill_md = skills_dir / directory / "SKILL.md"

    if not skill_md.is_file():
        # S7's gate already owns "every step has a skill". Reported here,
        # not counted twice.
        return CloseReading(step=step.id, n=step.n, skill_dir=directory, skill_md_exists=False)

    try:
        text = skill_md.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        # `UnicodeDecodeError` is a `ValueError`, not an `OSError`: catching
        # only the latter turns a gate into a crash, which records no number.
        return CloseReading(
            step=step.id,
            n=step.n,
            skill_dir=directory,
            reasons=(f"SKILL.md could not be read: {exc}",),
        )

    blocks = _close_blocks(text)
    verdict = read_close(step.id, blocks)
    protocol = _PROTOCOL_RE.search(text)
    invites = bool(protocol and _OPEN_TALK_RE.search(protocol.group("body")))

    reasons: list[str] = []
    if not blocks:
        reasons.append(
            "carries no spoken close in its `## Boundary` section, so the text a model copies "
            "when it hands the step back is left to improvisation"
        )
    if not verdict["has_recommendation"]:
        reasons.append(
            "closes without saying which way it would go — a menu handed to the person with "
            "the least information in the room"
        )
    if not verdict["has_reason"]:
        reasons.append(
            "closes without justifying what it proposes, so the candidate is asked to weigh "
            "an option on nothing"
        )
    if not verdict["leaves_the_choice"]:
        reasons.append("closes by announcing rather than asking — directing has become deciding")
    for line in verdict["coercive_lines"]:
        reasons.append(f"presses rather than recommends: {line!r}")
    if not _WHEN_DECLINED_RE.search(text):
        reasons.append("carries no `## When declined` section, so the decline has nowhere to land")

    return CloseReading(
        step=step.id,
        n=step.n,
        skill_dir=directory,
        spoken=blocks,
        has_recommendation=verdict["has_recommendation"],
        has_reason=verdict["has_reason"],
        leaves_the_choice=verdict["leaves_the_choice"],
        has_when_declined=bool(_WHEN_DECLINED_RE.search(text)),
        coercive_lines=verdict["coercive_lines"],
        invites_open_ended_talk=invites,
        reasons=tuple(reasons),
    )


def follow_up_rule(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> bool:
    """Does this step's protocol both state the follow-up rule and show it?

    Both halves, for D-15's reason: a rule with no worked example is a rule the
    model improvises around, and the example is the text it actually copies.
    """
    skill_md = skills_dir / skill_dir_name(step) / "SKILL.md"
    if not skill_md.is_file():
        return False
    protocol = _PROTOCOL_RE.search(skill_md.read_text(encoding="utf-8"))
    if protocol is None:
        return False
    for chunk in rule_chunks(protocol.group("body")):
        if not _FOLLOW_UP_RE.search(chunk):
            continue
        spoken, _ = split_spoken_and_prose(chunk)
        if any("?" in block for block in spoken):
            return True
    return False


def artefact_fields(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> list[str]:
    """The fields named by the artefact table in this step's protocol.

    The table is what makes the ask follow the candidate rather than the
    tooling: a developer is asked for repositories and a designer for a
    portfolio because the rule reads a row, not because software is the only
    thing anyone thought of.
    """
    skill_md = skills_dir / skill_dir_name(step) / "SKILL.md"
    if not skill_md.is_file():
        return []
    protocol = _PROTOCOL_RE.search(skill_md.read_text(encoding="utf-8"))
    if protocol is None:
        return []
    for chunk in rule_chunks(protocol.group("body")):
        if not _ARTEFACT_RULE_RE.search(chunk):
            continue
        rows = [
            first
            for match in _TABLE_ROW_RE.finditer(chunk)
            if (first := match.group("first").strip())
            and not set(first) <= {"-", ":", " "}
            and first.lower() != "their field"
        ]
        if rows:
            return rows
    return []


def artefact_fallback(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> bool:
    """Does the artefact rule still ask when the candidate's field has no row?"""
    skill_md = skills_dir / skill_dir_name(step) / "SKILL.md"
    if not skill_md.is_file():
        return False
    protocol = _PROTOCOL_RE.search(skill_md.read_text(encoding="utf-8"))
    if protocol is None:
        return False
    return any(
        _ARTEFACT_RULE_RE.search(chunk) and _ARTEFACT_FALLBACK_RE.search(chunk)
        for chunk in rule_chunks(protocol.group("body"))
    )


#: Closes a plausible fix would ship, and the verdict each must get. Written as
#: the shape of the mistake rather than as a copy of any shipped line: three
#: that must be refused, one that must be accepted. A reader that gets any of
#: them wrong has its metric replaced by `-1`.
NEGATIVE_CONTROLS: tuple[tuple[str, str, bool, bool], ...] = (
    (
        "no reason attached",
        '"Traits next — carry on?"',
        False,
        False,
    ),
    (
        "a reason, but still a menu with no recommendation",
        '"Traits or reactions next? Either helps, because both feed the ranking."',
        False,
        False,
    ),
    (
        "a recommendation that took the choice away",
        '"I\'d do traits next, because it reads your episodes. You need to answer these first."',
        True,
        True,
    ),
    (
        "the shape asked for",
        "\"Traits next — I'd do it now, because it reads the episodes you have just given me "
        'rather than asking you to rate yourself. Shall we?"',
        True,
        False,
    ),
)


def judge_controls() -> list[str]:
    """Run `NEGATIVE_CONTROLS` through the reader; report every misjudgement."""
    misjudged: list[str] = []
    for name, close, want_recommended, want_override in NEGATIVE_CONTROLS:
        verdict = read_close("control", (close,))
        recommended = verdict["has_recommendation"] and verdict["has_reason"]
        override = bool(verdict["coercive_lines"]) or not verdict["leaves_the_choice"]
        if recommended != want_recommended:
            misjudged.append(
                f"control {name!r}: recommendation read as {recommended}, expected "
                f"{want_recommended}"
            )
        if override != want_override:
            misjudged.append(
                f"control {name!r}: decline override read as {override}, expected {want_override}"
            )
    return misjudged


def probe(
    steps: StepList | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> list[CloseReading]:
    """Every settled step's reading, in step order."""
    steps = steps or load_steps()
    return [read_skill(step, skills_dir) for step in sorted(steps.steps, key=lambda s: s.n)]


def _unmeasured(reason: str, readings: list[CloseReading]) -> dict[str, Any]:
    """The shape a reading that could not happen takes: `-1`, never `0`."""
    return {
        "steps_offered_without_a_recommendation": -1,
        "steps_offered_without_a_recommendation_evaluated": len(readings),
        "steps_overriding_a_decline": -1,
        "steps_inviting_open_ended_talk": [],
        "intake_follow_up_rule": False,
        "intake_artefact_fields": [],
        "intake_artefact_fallback": False,
        "negative_controls_misjudged": len(judge_controls()),
        "gate_status": "unmeasured",
        "unmeasured_reason": reason,
        "offenders": [],
        "readings": [r.model_dump(mode="json") for r in readings],
    }


def measure(
    steps_path: Path | None = None, skills_dir: Path = DEFAULT_SKILLS_DIR
) -> dict[str, Any]:
    """T93's gate reading: `steps_offered_without_a_recommendation`."""
    try:
        steps = load_steps() if steps_path is None else load_steps(steps_path)
    except Exception as exc:  # a load failure is evidence to report, not a crash
        return _unmeasured(f"step list could not be loaded: {exc}", [])

    readings = probe(steps, skills_dir)
    if not readings:
        return _unmeasured("the step list is empty — nothing was read", readings)

    misjudged = judge_controls()
    if misjudged:
        return _unmeasured(
            "the close reader misjudged its own negative controls, so a clean count over the "
            f"library would mean nothing: {'; '.join(misjudged)}",
            readings,
        )

    by_id = {step.id: step for step in steps.steps}
    intake = by_id.get(INTAKE_STEP)
    offenders = [r for r in readings if r.lacks_a_recommendation or r.overrides_a_decline]

    return {
        "steps_offered_without_a_recommendation": sum(
            1 for r in readings if r.lacks_a_recommendation
        ),
        "steps_offered_without_a_recommendation_evaluated": len(readings),
        "steps_overriding_a_decline": sum(1 for r in readings if r.overrides_a_decline),
        "steps_inviting_open_ended_talk": [r.step for r in readings if r.invites_open_ended_talk],
        "intake_follow_up_rule": follow_up_rule(intake, skills_dir) if intake else False,
        "intake_artefact_fields": artefact_fields(intake, skills_dir) if intake else [],
        "intake_artefact_fallback": artefact_fallback(intake, skills_dir) if intake else False,
        "negative_controls_misjudged": 0,
        "gate_status": "measured",
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
    """Measure and record `status/evidence/T93.json`."""
    measured = measure(steps_path, skills_dir)
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.interview_direction [--check] [--write-evidence [PATH]]`."""
    parser = argparse.ArgumentParser(description="T93's gate over the step skills' closes")
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
        help="write evidence JSON to PATH (default: status/evidence/T93.json)",
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
    for offender in measured["offenders"]:
        print(f"{offender['step']}: {'; '.join(offender['reasons'])}", file=sys.stderr)
    if measured["gate_status"] == "unmeasured":
        print(f"UNMEASURED — {measured['unmeasured_reason']}", file=sys.stderr)
        return 3
    if measured["steps_offered_without_a_recommendation"] or measured["steps_overriding_a_decline"]:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main(sys.argv))
