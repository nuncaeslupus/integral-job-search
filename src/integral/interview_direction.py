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

Three ways to hold both halves and still offer nothing, each found by review on
this task's own pull request and each now a limb of the count:

* **Recommend one thing, ask another.** *"I'd build that into a story […] How
  did it feel?"* satisfies a recommendation check and a question check taken
  separately, and gives the candidate nothing to accept or decline. So the
  question is read **against** the recommendation, not beside it.
* **Delete the `## When declined` section.** Every other limb still reads
  clean while the "no" has nowhere to land — the fail-open direction, which is
  the one that matters.
* **Recommend an application off the rank alone.** Step 11 requires an offer at
  `shortlisted` and step 10 forbids inferring a status from silence, so a close
  proposing an application has to name the transition that recorded the
  candidate's interest. Coming first in a list is not consent.

## Why the measurement reads the shipped library

The strings this module checks are the ones a candidate hears: the fenced
`## Boundary` example in each of the thirteen step skills, which is the text a
model copies when it closes a step. Fixtures written for a test would measure
this module's author instead — T95 found a leak in a real shipped label for
precisely that reason. So the denominator is the shipped library, and it is
thirteen.

Regexes over prose can be satisfied by an author who writes to them, so
`NEGATIVE_CONTROLS` runs eight synthetic closes through the same reader on every
measurement: six that must be rejected and two that must be accepted. A
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

# A question the candidate can answer about the thing just recommended, either
# by pointing back at it or by repeating its own words. Checked against the
# recommendation, never on its own: "I'd apply next. Anything else jump out?"
# carries a recommendation and a question and offers neither.
_ASSENT_RE = re.compile(
    r"\bshall (?:we|I)\b|\bwant to\b|\bwould you like\b|\bready to\b|\bcarry on\b"
    r"|\bgo ahead\b|\bdo you want\b|\bhappy (?:to|with)\b|\bthat all right\b"
    rf"|\bif you{_APOSTROPHE}re up for\b",
    re.IGNORECASE,
)

# Words common enough that repeating one says nothing about which action is
# being accepted. Everything else of four letters or more is distinctive here.
_CONTENT_STOPWORDS = frozenset(
    {
        "about", "after", "again", "already", "also", "another", "anything", "because",
        "been", "before", "both", "could", "does", "each", "else", "even", "ever",
        "every", "first", "from", "gave", "give", "going", "have", "here", "into",
        "just", "know", "like", "look", "made", "make", "many", "more", "most", "much",
        "must", "need", "next", "only", "other", "over", "rather", "really", "said",
        "same", "shall", "some", "something", "still", "such", "take", "than", "that",
        "them", "then", "there", "these", "they", "thing", "things", "this", "those",
        "time", "very", "want", "what", "when", "where", "which", "while", "will",
        "with", "would", "your", "yours",
    }
)  # fmt: skip

# Step 11's precondition is an offer at `shortlisted`, and step 10 says a status
# is never inferred from silence. A close that recommends applying has to name
# the transition that recorded the candidate's interest, not the rank it reached.
_APPLICATION_RE = re.compile(r"\bappl(?:y|ies|ying|ication)\b", re.IGNORECASE)
_SHORTLIST_RE = re.compile(r"\bshortlist\w*\b", re.IGNORECASE)

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
    question_answers_the_recommendation: bool = False
    recommends_applying: bool = False
    records_the_shortlist: bool = False
    has_when_declined: bool = False
    coercive_lines: tuple[str, ...] = ()
    invites_open_ended_talk: bool = False
    read_failure: str = ""
    reasons: tuple[str, ...] = ()

    @property
    def lacks_a_recommendation(self) -> bool:
        """The gate's own limb: an offer that does not say which way, and why.

        The question is judged **with** the recommendation rather than beside
        it. Counting the two independently passes a close that proposes one
        action and then asks about another — which has offered the candidate
        nothing to accept or decline, and is the defect wearing the fix.
        """
        return not (
            self.has_recommendation and self.has_reason and self.question_answers_the_recommendation
        )

    @property
    def infers_interest_from_rank(self) -> bool:
        """Recommending an application the candidate never asked for.

        Step 11 requires an offer at `shortlisted`; step 10 says a status is
        never inferred from silence. Reaching the top of a list is not the
        candidate saying they want it.
        """
        return self.recommends_applying and not self.records_the_shortlist

    @property
    def overrides_a_decline(self) -> bool:
        """T36's limb: directing that has stopped being an offer.

        A missing `## When declined` counts: delete the section that honours a
        "no" and every other limb still reads clean, which is the one direction
        this must never fail in.
        """
        return (
            bool(self.coercive_lines)
            or not self.leaves_the_choice
            or not self.has_when_declined
            or self.infers_interest_from_rank
        )


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


def _content_words(text: str) -> set[str]:
    """Words distinctive enough that repeating one points back at a clause."""
    return set(re.findall(r"[a-z]{4,}", text.lower())) - _CONTENT_STOPWORDS


def _recommended_action(joined: str) -> str:
    """The recommendation itself, stripped of the reason that follows it."""
    match = _RECOMMENDATION_RE.search(joined)
    if match is None:
        return ""
    tail = joined[match.start() :]
    return re.split(r"\bbecause\b|[.!?;]", tail, maxsplit=1, flags=re.IGNORECASE)[0]


def _asks_about_the_recommendation(joined: str) -> bool:
    """Is the candidate asked about the action that was just recommended?

    The question has to come **after** the recommendation and either point back
    at it ("shall I?") or repeat its own words ("mark it shortlisted?"). A
    question asked before it, or about something else entirely, leaves the
    recommendation unoffered however plainly it was stated.
    """
    action = _recommended_action(joined)
    if not action:
        return False
    wanted = _content_words(action)
    tail = joined[joined.index(action) :]
    return any(
        _ASSENT_RE.search(question) or wanted & _content_words(question)
        for question in re.findall(r"[^.!?]+\?", tail)
    )


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
        "question_answers_the_recommendation": _asks_about_the_recommendation(joined),
        "recommends_applying": bool(_APPLICATION_RE.search(_recommended_action(joined))),
        "records_the_shortlist": bool(_SHORTLIST_RE.search(joined)),
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
            read_failure=f"SKILL.md could not be read: {exc}",
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
    if verdict["has_recommendation"] and not verdict["question_answers_the_recommendation"]:
        reasons.append(
            "recommends one action and asks about another, so there is nothing for the candidate "
            "to accept or decline"
        )
    if verdict["recommends_applying"] and not verdict["records_the_shortlist"]:
        reasons.append(
            "recommends an application without the `shortlisted` transition that records the "
            "candidate wanting the role — a rank is not consent, and step 10 forbids reading a "
            "status off silence"
        )
    for line in verdict["coercive_lines"]:
        reasons.append(f"presses rather than recommends: {line!r}")
    if not _WHEN_DECLINED_RE.search(text):
        reasons.append("carries no `## When declined` section, so the decline has nowhere to land")

    return CloseReading(
        **verdict,
        n=step.n,
        skill_dir=directory,
        has_when_declined=bool(_WHEN_DECLINED_RE.search(text)),
        invites_open_ended_talk=invites,
        reasons=tuple(reasons),
    )


def _protocol_body(step: Step, skills_dir: Path) -> str | None:
    """This step's `## Protocol` body, or `None` when there is nothing to read.

    Missing, unreadable and invalid-UTF-8 all land here rather than raising:
    `read_skill` already turns the same failure into evidence, and a helper that
    aborts the run records no number at all — which is how a measurement that
    could not be taken ends up looking like one that was.
    """
    try:
        text = (skills_dir / skill_dir_name(step) / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    protocol = _PROTOCOL_RE.search(text)
    return protocol.group("body") if protocol else None


def follow_up_rule(step: Step, skills_dir: Path = DEFAULT_SKILLS_DIR) -> bool:
    """Does this step's protocol both state the follow-up rule and show it?

    Both halves, for D-15's reason: a rule with no worked example is a rule the
    model improvises around, and the example is the text it actually copies.
    """
    protocol = _protocol_body(step, skills_dir)
    if protocol is None:
        return False
    for chunk in rule_chunks(protocol):
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
    protocol = _protocol_body(step, skills_dir)
    if protocol is None:
        return []
    for chunk in rule_chunks(protocol):
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
    protocol = _protocol_body(step, skills_dir)
    if protocol is None:
        return False
    return any(
        _ARTEFACT_RULE_RE.search(chunk) and _ARTEFACT_FALLBACK_RE.search(chunk)
        for chunk in rule_chunks(protocol)
    )


#: Closes a plausible fix would ship, and the verdict each must get. Written as
#: the shape of the mistake rather than as a copy of any shipped line: six that
#: must be refused, two that must be accepted. A reader that gets any of them
#: wrong has its metric replaced by `-1`.
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
        "\"I'd do traits next, because it reads your episodes — shall we? You need to answer "
        'these first."',
        True,
        True,
    ),
    (
        "a recommendation the question does not answer",
        "\"I'd turn that into weights next, because it is what lets me price a shorter commute. "
        'How did it feel?"',
        False,
        False,
    ),
    (
        "a question asked before the recommendation, not about it",
        "\"Does that sound like you? I'd go and look at real jobs now, because the weights only "
        'prove themselves against adverts you can take or leave."',
        False,
        False,
    ),
    (
        "a question that answers the recommendation in its own words",
        "\"I'd mark the Girona role shortlisted now, because that is what records you wanting "
        'it. Mark it shortlisted?"',
        True,
        False,
    ),
    (
        "an application recommended off the rank alone",
        "\"The Girona role is top of the list now. I'd apply to it next, because it has stayed "
        'there through two rounds of your corrections. Shall I?"',
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
        # Judged through `CloseReading`'s own properties so the controls cannot
        # drift from the library's verdict. `has_when_declined` is asserted:
        # a synthetic close is a close, not a SKILL.md with sections round it.
        reading = CloseReading(
            **read_close("control", (close,)),
            n=0,
            skill_dir="<control>",
            has_when_declined=True,
        )
        recommended = not reading.lacks_a_recommendation
        override = reading.overrides_a_decline
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
        "negative_controls_evaluated": len(NEGATIVE_CONTROLS),
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

    unreadable = [r for r in readings if r.read_failure]
    if unreadable:
        return _unmeasured(
            "a step skill exists but could not be read, so the library was not judged: "
            + "; ".join(f"{r.step}: {r.read_failure}" for r in unreadable),
            readings,
        )

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
        "negative_controls_evaluated": len(NEGATIVE_CONTROLS),
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
