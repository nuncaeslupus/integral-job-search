"""T93 — the session offers where it should lead.

Every assertion here reads the **shipped** step-skill library, because that is
the text a candidate actually hears when a step hands back. Fixtures written
here would measure this test's author instead; the only synthetic strings below
are negative controls, and they exist to prove the reader can still say no.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from integral.interview_direction import (
    MINIMUM_NON_SOFTWARE_ARTEFACT_FIELDS,
    MINIMUM_OPEN_TALK_STEPS,
    NEGATIVE_CONTROLS,
    OPENING_STEP,
    SOFTWARE_FIELD_RE,
    artefact_fallback,
    artefact_fields,
    follow_up_rule,
    judge_controls,
    measure,
    read_close,
    read_skill,
    write_evidence,
)
from integral.process_spec import Step, StepList, load_steps
from integral.step_skills import DEFAULT_SKILLS_DIR, skill_dir_name


@pytest.fixture(scope="module")
def measured() -> dict[str, Any]:
    return measure()


@pytest.fixture(scope="module")
def steps() -> StepList:
    return load_steps()


def _step(steps: StepList, step_id: str) -> Step:
    return next(step for step in steps.steps if step.id == step_id)


def test_every_offered_step_carries_a_recommendation_and_a_reason(
    measured: dict[str, Any], steps: StepList
) -> None:
    """A step that hands back without saying which way, and why, is the defect.

    The candidate's words: *"You know what is needed, not the user, so saying it
    is better than letting the user decide. You must justify your decisions and
    recommendations."* Before this task nine of the thirteen shipped closes were
    a menu — `"Traits next — carry on?"` — and four of the remaining offered a
    reason with no recommendation attached to it.
    """
    assert measured["gate_status"] == "measured"
    assert measured["steps_offered_without_a_recommendation_evaluated"] == len(steps.steps)
    assert measured["steps_offered_without_a_recommendation_evaluated"] > 0
    assert measured["steps_offered_without_a_recommendation"] == 0, measured["offenders"]

    for reading in measured["readings"]:
        assert reading["spoken"], f"{reading['step']} ships no close at all"
        assert reading["has_recommendation"], f"{reading['step']} closes without a recommendation"
        assert reading["has_reason"], f"{reading['step']} closes without a reason"


def test_a_declined_recommendation_is_still_honoured(measured: dict[str, Any]) -> None:
    """Directing is not overriding — T36's boundary, in the shipped wording.

    An offer with no recommendation is the defect; an offer the candidate
    declines is not. A close that gained a recommendation and lost the question
    mark has traded one fault for a worse one.
    """
    assert measured["steps_overriding_a_decline"] == 0, measured["offenders"]
    for reading in measured["readings"]:
        assert reading["leaves_the_choice"], f"{reading['step']} announces instead of asking"
        assert not reading["coercive_lines"], f"{reading['step']} presses: {reading}"
        assert reading["has_when_declined"], f"{reading['step']} has nowhere for a decline to land"

    # And the reader is not merely agreeable: a close that took the choice away
    # is refused even though it carries a recommendation and a reason.
    coercive = read_close(
        "control",
        ('"I\'d do traits next, because it reads your episodes. You need to answer these first."',),
    )
    assert coercive["has_recommendation"] and coercive["has_reason"]
    assert coercive["coercive_lines"]


def test_the_opening_invites_open_ended_talk(measured: dict[str, Any]) -> None:
    """*"You must induce the user to talk as much as possible"* — and repeatedly.

    The note asked for it "at the beginning and some other times". Once is a
    disclaimer: a candidate who hears it only at step 0 is back to answering
    exactly what was asked by the time they are listing job titles.
    """
    inviting = measured["steps_inviting_open_ended_talk"]
    assert OPENING_STEP in inviting, f"the opening step does not invite it: {inviting}"
    assert len(inviting) >= MINIMUM_OPEN_TALK_STEPS, f"said once, not repeated: {inviting}"


def test_an_unexplained_detail_in_the_intake_produces_a_follow_up_question(
    measured: dict[str, Any], steps: StepList, tmp_path: Path
) -> None:
    """*"Anything that intrigued you about the CV, you must pull the string."*

    Both halves are required: the rule, and a worked example of asking. D-15's
    finding is that a rule shipped without a demonstration is a rule the model
    improvises around, so a library carrying the paragraph and no example must
    still read as missing.
    """
    assert measured["intake_follow_up_rule"] is True

    library = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, library)
    intake = _step(steps, "intake")
    skill_md = library / skill_dir_name(intake) / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    stripped = text.replace(
        '"Two things I noticed: eighteen months between the hospital and Acme, and Rust '
        'appears once and never again. Anything in either of those?"',
        '"Noted."',
    )
    assert stripped != text, "the follow-up example this test strips is no longer shipped"
    skill_md.write_text(stripped, encoding="utf-8")
    assert follow_up_rule(intake, library) is False


def test_the_artefact_question_follows_the_candidates_field(
    measured: dict[str, Any], steps: StepList
) -> None:
    """Repositories for a developer, a portfolio for a designer — nothing hardcoded.

    The reported miss was a developer never asked for their public repositories.
    Fixing that with a GitHub prompt would reproduce it one layer down, so what
    ships is a table the ask is read out of, plus a fallback for a field with no
    row.
    """
    fields = measured["intake_artefact_fields"]
    assert fields, "the intake skill carries no artefact table"

    rows = _artefact_rows(_step(steps, "intake"))
    software = [ask for field, ask in rows.items() if SOFTWARE_FIELD_RE.search(field)]
    design = [ask for field, ask in rows.items() if "design" in field]
    assert software and "repositor" in software[0], software
    assert design and "portfolio" in design[0], design

    non_software = [f for f in fields if not SOFTWARE_FIELD_RE.search(f)]
    assert len(non_software) >= MINIMUM_NON_SOFTWARE_ARTEFACT_FIELDS, non_software
    assert measured["intake_artefact_fallback"] is True, "a field with no row loses the question"


def _artefact_rows(intake: Step) -> dict[str, str]:
    """The shipped table as `field -> what to ask for`, read off SKILL.md."""
    skill_md = DEFAULT_SKILLS_DIR / skill_dir_name(intake) / "SKILL.md"
    rows: dict[str, str] = {}
    for field in artefact_fields(intake):
        for line in skill_md.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"| {field} |"):
                rows[field] = line.split("|")[2].strip()
    return rows


def test_the_reader_refuses_its_own_negative_controls() -> None:
    """A regex over prose is only worth what it refuses.

    Each control is a close a plausible fix would ship. If the reader misjudges
    any of them, `measure` replaces the metric with `-1` rather than reporting a
    clean count over the library — the same reason `judge_controls` runs on
    every measurement and not only here.
    """
    assert judge_controls() == []
    assert len(NEGATIVE_CONTROLS) >= 4
    refused = [
        name for name, _, recommended, override in NEGATIVE_CONTROLS if not recommended or override
    ]
    assert len(refused) >= 3, "the controls no longer include anything that must be refused"


def test_a_library_with_no_close_reads_as_an_offer_without_a_recommendation(
    steps: StepList, tmp_path: Path
) -> None:
    """A skill whose Boundary example is removed must not pass by absence."""
    library = tmp_path / "skills"
    shutil.copytree(DEFAULT_SKILLS_DIR, library)
    history = _step(steps, "history")
    skill_md = library / skill_dir_name(history) / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    head, _, tail = text.partition("## Boundary")
    skill_md.write_text(head + "## Boundary\n\nNothing.\n\n" + tail.split("## Checkpoint")[-1])

    reading = read_skill(history, library)
    assert reading.spoken == ()
    assert reading.lacks_a_recommendation
    assert any("no spoken close" in reason for reason in reading.reasons)


def test_a_load_failure_is_recorded_as_unmeasured_not_as_a_clean_zero(tmp_path: Path) -> None:
    """ "Could not be measured" must never look healthier than "measured dirty"."""
    missing = measure(steps_path=tmp_path / "no-such-steps.json")
    assert missing["gate_status"] == "unmeasured"
    assert missing["steps_offered_without_a_recommendation"] == -1


def test_write_evidence_records_the_measurement(tmp_path: Path) -> None:
    evidence = tmp_path / "T93.json"
    measured = write_evidence(evidence)
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
    assert measured["steps_offered_without_a_recommendation"] == 0
    assert artefact_fallback(_step(load_steps(), "intake")) is True
