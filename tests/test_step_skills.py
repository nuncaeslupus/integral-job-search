"""S7 — one skill per step, and the checkpoint-not-prose distinction it gates.

The payload's failure mode: "a step whose skill embeds its checkpoint in prose
has not been converted; it has been transcribed." These tests check the two
mechanical facts that distinguish a converted step from a transcribed one
(gate metric named, checkpoint script named *and present on disk*), and the
two things a drifting skill gets wrong first (`status/spec-v2-steps.md` §"How
to read a step": the stop rule and the required/offered split).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from integral import employment_mode, session_exit, sourcing_scope_review, step_narration
from integral.candidate import EmploymentModeName
from integral.process_spec import Step, StepList, load_steps
from integral.session import Resumption
from integral.sourcing_strategy import EvidenceRow, ScopeDecision
from integral.step_skills import (
    DEFAULT_SKILLS_DIR,
    SkillCheck,
    check_step_skill,
    measure,
    probe_step_skills,
    skill_dir_name,
    write_evidence,
)

# The hard cap `status/spec-v2-steps.md` states for each step's stop rule — a
# fact from the settled prose, not a re-decision of it. Present only as a
# substring marker so a skill whose prose paraphrases the number rather than
# stating it is caught, without demanding the skill quote the spec verbatim.
_HARD_CAP_MARKER = {
    "identify": "three attempts",
    "intake": "12 questions",
    "constraints": "14 questions",
    "history": "8 episodes",
    "traits": "10 questions",
    "reactions": "25 stimuli",
    "preferences": "20 choices",
    "sourcing": "per-run offer ceiling",
    "understanding": "per-run extraction budget",
    "ranking": "number shown at once",
    "feedback": "twice",
    "application": "three regeneration rounds",
    "interview_log": "10 rehearsed questions",
}


@pytest.fixture
def steps() -> StepList:
    return load_steps()


def _skill_text(step_id: str, steps: StepList) -> str:
    step = next(s for s in steps.steps if s.id == step_id)
    skill_md = DEFAULT_SKILLS_DIR / skill_dir_name(step) / "SKILL.md"
    return skill_md.read_text(encoding="utf-8")


# --- required test 1: every step has a skill -------------------------------


def test_every_step_has_a_skill(steps: StepList) -> None:
    """Thirteen steps in the settled list, thirteen skill folders on disk.

    A step with no skill folder is the plainest way S7 could be incomplete —
    walking `steps.steps` (never `DEFAULT_SKILLS_DIR`'s own directory listing)
    is what stops an extra, unrelated skill folder from being mistaken for
    coverage of a step that has none.
    """
    for step in steps.steps:
        skill_dir = DEFAULT_SKILLS_DIR / skill_dir_name(step)
        assert (skill_dir / "SKILL.md").is_file(), f"{step.id} has no skill at {skill_dir}"


# --- required test 2: every skill names its gate metric ---------------------


def test_every_skill_names_its_gate_metric(steps: StepList) -> None:
    """The literal `gate.metric` identifier appears in the skill, not a paraphrase."""
    for step in steps.steps:
        text = _skill_text(step.id, steps)
        pattern = re.compile(rf"\b{re.escape(step.gate.metric)}\b")
        assert pattern.search(text), f"{step.id}'s skill never names {step.gate.metric!r}"


# --- required test 3: the checkpoint is a script, not prose ----------------


def test_every_skill_checkpoint_is_a_script_not_prose(steps: StepList) -> None:
    """A named script that does not exist is exactly the transcription failure.

    Beyond existence: the file must actually be runnable code (an argparse
    entry point), not an empty stub that merely satisfies "a file is there" —
    a payload with no `def main(` is a filename, not a checkpoint.
    """
    for step in steps.steps:
        check = check_step_skill(step, DEFAULT_SKILLS_DIR)
        assert check.checkpoint_script is not None, f"{step.id} names no checkpoint script"
        assert check.checkpoint_script_exists, (
            f"{step.id} names {check.checkpoint_script!r} but it does not exist on disk"
        )
        script_path = (
            DEFAULT_SKILLS_DIR / skill_dir_name(step) / "scripts" / check.checkpoint_script
        )
        script_text = script_path.read_text(encoding="utf-8")
        assert "def main(" in script_text, f"{step.id}'s checkpoint script has no entry point"
        assert "argparse" in script_text, f"{step.id}'s checkpoint script takes no arguments"
        assert check.passes


# --- required test 4: no skill contradicts its step specification ----------


def test_no_skill_contradicts_its_step_specification(steps: StepList) -> None:
    """The two things a drifting skill gets wrong first: stop rule, required/offered."""
    for step in steps.steps:
        text = _skill_text(step.id, steps)

        # required/offered — the JSON's `required` flag against the skill's own
        # marker, so a skill that quietly relaxed a required step (or tightened
        # an offered one) is caught rather than trusted.
        if step.required:
            assert "**Required.**" in text, f"{step.id} is required but its skill does not say so"
            assert "**Offered.**" not in text, f"{step.id} is required but its skill offers it"
        else:
            assert "**Offered.**" in text, f"{step.id} is offered but its skill does not say so"
            assert "**Required.**" not in text, f"{step.id} is offered but its skill requires it"

        # stop rule — the settled hard cap must appear under this skill's own
        # "## Stop rule" section, not merely somewhere in the file.
        stop_section = text.split("## Stop rule", 1)[1].split("## When declined", 1)[0]
        marker = _HARD_CAP_MARKER[step.id]
        assert marker.lower() in stop_section.lower(), (
            f"{step.id}'s Stop rule section does not carry the settled hard cap {marker!r}"
        )


# --- the naming scheme -------------------------------------------------


def test_skill_dir_name_sorts_in_spec_order(steps: StepList) -> None:
    """`step-<NN>-<id>` — the naming convention this module settles for S7."""
    names = [skill_dir_name(step) for step in sorted(steps.steps, key=lambda s: s.n)]
    assert names == sorted(names)
    assert names[0] == "step-00-identify"
    assert names[-1] == "step-12-interview-log"


def test_underscore_ids_become_hyphenated_directories(steps: StepList) -> None:
    interview_log = next(s for s in steps.steps if s.id == "interview_log")
    assert skill_dir_name(interview_log) == "step-12-interview-log"
    assert "_" not in skill_dir_name(interview_log)


# --- the gate over the real, committed skills -------------------------------


def test_the_committed_skills_score_full_fraction() -> None:
    measured = measure()
    assert measured["steps_with_a_skill_fraction"] == 1.0
    assert measured["shortfalls"] == []
    assert measured["step_count"] == 13
    assert measured["steps_checked"] == 13


def test_the_divisor_is_read_never_hardcoded(steps: StepList) -> None:
    """The S2 lesson, applied here: divide by `step_count`, not `len(checks)`.

    A module that divided by how many checks it happened to run would report
    1.0 over any subset — including an accidentally empty one. Proven by
    checking the field is read from the loaded list, not restated.
    """
    measured = measure()
    assert measured["step_count"] == steps.step_count


def test_write_evidence_matches_measure(tmp_path: Path) -> None:
    target = tmp_path / "S7.json"
    measured = write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["steps_with_a_skill_fraction"] == 1.0


# --- the gate over a synthetic, incomplete library --------------------------


def _write_step_list(tmp_path: Path) -> Path:
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(
        Path("status/spec-v2-steps.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return steps_path


def test_a_missing_skill_counts_against_the_divisor(tmp_path: Path, steps: StepList) -> None:
    """One of thirteen missing reads as 12/13, never as 1.0 over a smaller set."""
    empty_skills = tmp_path / "skills"
    empty_skills.mkdir()
    measured = measure(_write_step_list(tmp_path), empty_skills)
    assert measured["steps_with_a_skill_fraction"] == 0.0
    assert measured["step_count"] == 13
    assert len(measured["shortfalls"]) == 13


def test_a_gate_metric_missing_from_prose_is_not_counted(tmp_path: Path, steps: StepList) -> None:
    """Prose that never names the metric is the paraphrase this module refuses."""
    step = next(s for s in steps.steps if s.id == "identify")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "run_checkpoint.py").write_text("# stub\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\nUses scripts/run_checkpoint.py.\n",
        encoding="utf-8",
    )
    check = check_step_skill(step, skills_dir)
    assert not check.names_gate_metric
    assert not check.passes
    assert any("does not appear" in reason for reason in check.reasons)


def test_a_named_script_that_does_not_exist_is_the_transcription_failure(
    tmp_path: Path, steps: StepList
) -> None:
    """The exact case the payload names: prose describing a computation nobody can run."""
    step = next(s for s in steps.steps if s.id == "identify")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        f"Names the gate metric {step.gate.metric} and a checkpoint at "
        "scripts/run_checkpoint.py, which is prose describing what the step does "
        "rather than a script that does it.\n",
        encoding="utf-8",
    )
    check = check_step_skill(step, skills_dir)
    assert check.names_gate_metric
    assert check.checkpoint_script == "run_checkpoint.py"
    assert not check.checkpoint_script_exists
    assert not check.passes
    assert any("does not exist" in reason for reason in check.reasons)


def test_a_complete_synthetic_skill_passes(tmp_path: Path, steps: StepList) -> None:
    step = next(s for s in steps.steps if s.id == "identify")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "scripts" / "run_checkpoint.py").write_text("# stub\n", encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        f"Names {step.gate.metric} and scripts/run_checkpoint.py.\n",
        encoding="utf-8",
    )
    check = check_step_skill(step, skills_dir)
    assert check.passes
    assert check.reasons == ()


def test_probe_reads_every_step_in_settled_order(steps: StepList, tmp_path: Path) -> None:
    checks = probe_step_skills(steps, tmp_path / "nonexistent")
    assert [check.n for check in checks] == sorted(step.n for step in steps.steps)
    assert isinstance(checks[0], SkillCheck)


def test_an_unloadable_step_list_reads_zero_never_crashes(tmp_path: Path) -> None:
    """A gate that crashes records no number; this one records the reason instead."""
    bad = tmp_path / "not-json.json"
    bad.write_text("{not json", encoding="utf-8")
    measured = measure(bad, DEFAULT_SKILLS_DIR)
    assert measured["steps_with_a_skill_fraction"] == 0.0
    assert measured["step_count"] == 0
    assert measured["shortfalls"][0]["reason"]


# --- D-14: no skill offers an unlawful employment arrangement ---------------


def _employment_skill(tmp_path: Path, step: Step, body: str) -> Path:
    """A one-step synthetic library carrying `body` as that step's SKILL.md."""
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: x\ndescription: x\n---\n\n{body}\n", encoding="utf-8"
    )
    return skills_dir


def test_no_skill_offers_falso_autonomo_as_a_choice() -> None:
    """D-14's gate over the committed library: `== 0`, and the rule is really there.

    The count alone would pass on a library that never mentions the subject —
    which is the state the live session was in when it improvised the question.
    So the owning skill's licensed mention is asserted too: the number is 0
    *because* the rule is written down, not because everyone stayed silent.
    """
    measured = employment_mode.measure()
    assert measured["skills_offering_an_illegal_employment_mode"] == 0, measured["offenders"]
    assert measured["steps_checked"] == 13
    assert measured["owning_steps"] == ["constraints"]

    owning = next(r for r in measured["readings"] if r["step"] == "constraints")
    assert owning["licensed_mentions"], "the owning skill states no prohibition to be licensed"


def test_the_lawful_modes_are_read_from_the_type_not_listed_here() -> None:
    """`EmploymentModeName` settles what may be offered; this module must not restate it."""
    assert get_args(EmploymentModeName) == employment_mode.LAWFUL_MODES
    assert "falso autónomo" not in employment_mode.LAWFUL_MODES


def test_an_owning_skill_that_says_nothing_is_counted(tmp_path: Path, steps: StepList) -> None:
    """The silence limb — the pre-fix state, and why this gate is not inert.

    Before the fix the constraints skill required `employment_mode` to end the
    step resolved and said nothing about how to ask it. No string search for
    the unlawful term would have found anything, because the bad question was
    improvised rather than written down.
    """
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path, step, "Cover residence, pay floor, mobility and notice period."
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.owns_employment_mode
    assert reading.offers
    assert any("carries no rule" in reason for reason in reading.reasons)


def test_naming_the_arrangement_as_a_choice_is_counted(tmp_path: Path, steps: StepList) -> None:
    """The regression limb: the phrasing the live session actually used."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path, step, "Ask whether they would take work as autónomo/falso autónomo."
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.unlicensed_mentions
    assert reading.offers
    assert any("without ruling it out" in reason for reason in reading.reasons)


def test_a_step_that_owns_nothing_is_still_counted_when_it_offers(
    tmp_path: Path, steps: StepList
) -> None:
    """The regression limb applies to every skill, not only the owning one."""
    step = next(s for s in steps.steps if s.id == "ranking")
    skills_dir = _employment_skill(
        tmp_path, step, "Offer the candidate falso autónomo roles alongside payroll ones."
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert not reading.owns_employment_mode
    assert reading.offers


def test_a_prohibition_licenses_the_mention(tmp_path: Path, steps: StepList) -> None:
    """Saying it is illegal and never offered is the one way to name it."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path,
        step,
        "- Never offer falso autónomo: it is an illegal arrangement, not a mode on a menu.",
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.licensed_mentions
    assert not reading.unlicensed_mentions
    assert not reading.offers


def test_a_lukewarm_mention_is_not_a_prohibition(tmp_path: Path, steps: StepList) -> None:
    """Two markers, not one — 'not ideal' refuses nothing and licenses nothing."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path, step, "Some employers offer falso autónomo, which is not ideal."
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.unlicensed_mentions
    assert reading.offers


def test_stating_the_illegality_without_forbidding_it_licenses_nothing(
    tmp_path: Path, steps: StepList
) -> None:
    """ "illegal but not ideal" states the law and refuses nothing.

    The first version of the check took any bare negation as a prohibition, so
    this line — which offers the arrangement in the same breath as calling it
    illegal — read as licensed and satisfied the gate. A prohibition marker has
    to forbid an act, not merely negate something.
    """
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path,
        step,
        "You can offer falso autónomo — it is illegal, but not ideal is closer to the truth.",
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.unlicensed_mentions
    assert reading.offers


def test_a_negation_inside_another_word_is_not_a_prohibition(
    tmp_path: Path, steps: StepList
) -> None:
    """Word boundaries: "nowhere" is not "no", "cannot" is not a bare "not"."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(
        tmp_path,
        step,
        "Falso autónomo is illegal and nowhere near as common as it used to be.",
    )
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.unlicensed_mentions
    assert reading.offers


def test_no_owning_step_records_minus_one_never_a_clean_zero(tmp_path: Path) -> None:
    """A rename that switches the silence limb off must not read as a pass.

    The limb only runs over the step that owns the question. If none does, a
    count of offenders is `0` over a check that examined nothing — a
    measurement at its healthiest-looking the moment it stops happening.
    """
    spec = json.loads(Path("status/spec-v2-steps.json").read_text(encoding="utf-8"))
    for step in spec["steps"]:
        step["produces"] = [p for p in step["produces"] if p != "constraints"]
    drifted = tmp_path / "steps.json"
    drifted.write_text(json.dumps(spec), encoding="utf-8")

    measured = employment_mode.measure(drifted, DEFAULT_SKILLS_DIR)
    assert measured["skills_offering_an_illegal_employment_mode"] == -1
    assert measured["owning_steps"] == []
    assert "silence limb measured nothing" in measured["offenders"][0]["reasons"][0]


def test_undecodable_prose_is_recorded_as_a_reason_never_raised(
    tmp_path: Path, steps: StepList
) -> None:
    """`UnicodeDecodeError` is a `ValueError`, so catching `OSError` alone let it through."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"\xff\xfe not utf-8 at all")

    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.offers
    assert any("could not be read" in reason for reason in reading.reasons)


def test_the_unaccented_spelling_is_caught_too(tmp_path: Path, steps: StepList) -> None:
    """A hurried edit reaches for ASCII; the check must not be defeated by it."""
    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _employment_skill(tmp_path, step, "Would you consider falso autonomo work?")
    reading = employment_mode.read_skill(step, skills_dir)
    assert reading.unlicensed_mentions
    assert reading.offers


def test_a_missing_skill_is_reported_not_counted(tmp_path: Path, steps: StepList) -> None:
    """S7's gate owns "every step has a skill"; counting the absence twice overstates it."""
    step = next(s for s in steps.steps if s.id == "constraints")
    reading = employment_mode.read_skill(step, tmp_path / "nonexistent")
    assert not reading.skill_md_exists
    assert not reading.offers


def test_employment_evidence_matches_measure(tmp_path: Path) -> None:
    target = tmp_path / "D-14.json"
    measured = employment_mode.write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["skills_offering_an_illegal_employment_mode"] == 0


def test_an_unloadable_step_list_records_minus_one_never_zero(tmp_path: Path) -> None:
    """A gate that could not run must not read as a clean pass."""
    bad = tmp_path / "not-json.json"
    bad.write_text("{not json", encoding="utf-8")
    measured = employment_mode.measure(bad, DEFAULT_SKILLS_DIR)
    assert measured["skills_offering_an_illegal_employment_mode"] == -1
    assert measured["steps_checked"] == 0


# --- D-15: no step boundary closes by offering to end the session ----------


def _boundary_skill(tmp_path: Path, step: Step, boundary: str) -> Path:
    """A one-step synthetic library whose SKILL.md carries `boundary`.

    A `## Gotchas` heading follows, so the tests exercise the same
    section-terminated parse the real files get rather than the end-of-file
    special case.
    """
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: x\ndescription: x\n---\n\n## Boundary\n\n{boundary}\n\n## Gotchas\n\n- none\n",
        encoding="utf-8",
    )
    return skills_dir


_CONFORMING_BOUNDARY = (
    "**Invite forward; never close by offering to stop.** The exit is offered only when the\n"
    "session has actually run long.\n\n"
    '```text\n"That\'s traits done. Reactions next — carry on?"\n```'
)


def test_a_step_boundary_does_not_offer_to_end_the_session() -> None:
    """D-15's gate over the committed library: `== 0`, and the rule is really there.

    The count alone would pass on a library whose boundaries said nothing at
    all, so the two things that make the zero meaningful are asserted with it:
    every boundary states the governing rule, and every boundary still says
    something out loud (§3.2 — ending silently is its own defect).
    """
    measured = session_exit.measure()
    assert measured["step_boundaries_offering_an_exit"] == 0, measured["offenders"]
    assert measured["steps_checked"] == 13
    assert measured["boundaries_checked"] == 13
    assert measured["rule_declared_in_step_spec"] is True

    for reading in measured["readings"]:
        assert reading["states_the_rule"], f"{reading['step']} states no rule to govern the offer"
        assert reading["spoken_examples"] >= 1, f"{reading['step']} says nothing out loud"


def test_the_four_boundaries_that_offered_an_exit_are_counted(tmp_path: Path) -> None:
    """The regression limb, in the exact words the pre-fix library used.

    Steps 1, 4, 5 and 10 are the four a candidate answering four steps met, and
    each phrases the offer differently — "or leave it here?", "Leave it there?",
    "or pause?", "or leave it?" — which is why the check is a pattern over ways
    of saying it rather than one string.
    """
    said = [
        '"Want to keep going to what would rule a job out, or leave it here?"',
        '"I don\'t have enough yet on how you take pressure. Leave it there?"',
        '"Want to turn that into weights, or pause?"',
        '"Anything else, or leave it?"',
    ]
    for spoken in said:
        offers, shortcuts = session_exit._exit_offers((spoken,))
        assert offers == (spoken,), f"not read as an exit offer: {spoken}"
        assert shortcuts == (), f"wrongly licensed as §3.3's skip: {spoken}"


def test_a_boundary_that_states_no_rule_is_counted(tmp_path: Path, steps: StepList) -> None:
    """The silence limb — the state every one of the thirteen skills was in.

    A boundary whose example happens to invite forward still counts while no
    rule is written down: nothing stops the next edit from copying the spec's
    other examples back in. This is the limb that makes the gate bite, since
    the regression limb alone reads clean the moment four sentences are
    rewritten.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _boundary_skill(
        tmp_path,
        step,
        'What the tool says out loud:\n\n```text\n"That\'s traits done. Carry on?"\n```',
    )
    reading = session_exit.read_boundary(step, skills_dir)
    assert reading.exit_offers == ()
    assert not reading.states_the_rule
    assert reading.offers
    assert any("carries no rule governing" in reason for reason in reading.reasons)


def test_stating_the_rule_is_not_read_as_offering_the_exit(tmp_path: Path, steps: StepList) -> None:
    """The prose/spoken split, without which the fix would fail its own gate.

    The rule sentence necessarily names the thing it forbids ("the exit is
    offered only when…"). Were the regression limb to read the whole section,
    every skill that stated its rule would be counted for stating it, and no
    library could satisfy the gate at all.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _boundary_skill(tmp_path, step, _CONFORMING_BOUNDARY)
    reading = session_exit.read_boundary(step, skills_dir)
    assert reading.states_the_rule
    assert reading.exit_offers == ()
    assert not reading.offers, reading.reasons


def test_deferring_an_artefact_is_not_offering_to_leave(tmp_path: Path, steps: StepList) -> None:
    """Step 11's "Ready to send, or sit on it?" is two ways forward, not an exit.

    The check must separate ending the sitting from declining a subject or
    deferring a document, or it would force the process to stop offering
    genuine choices in order to score.
    """
    step = next(s for s in steps.steps if s.id == "application")
    skills_dir = _boundary_skill(
        tmp_path,
        step,
        "**Invite forward; the exit is offered only when the session has run long, never"
        " as this step's standard close.**\n\n```text\n\"That's the CV and letter for the"
        ' Girona role. Ready to send, or sit on it?"\n```',
    )
    reading = session_exit.read_boundary(step, skills_dir)
    assert reading.exit_offers == ()
    assert not reading.offers, reading.reasons


def test_a_bare_mention_of_stopping_does_not_state_the_rule(
    tmp_path: Path, steps: StepList
) -> None:
    """Naming the subject and requiring nothing of it licenses nothing.

    D-14 was reviewed into exactly this: a single marker admitted prose that
    raised the subject and forbade nothing. Two markers here for the same
    reason — the paragraph must name the exit *and* constrain it.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _boundary_skill(
        tmp_path,
        step,
        "Some candidates like being offered the exit at the end of a step.\n\n"
        '```text\n"That\'s traits done. Carry on?"\n```',
    )
    reading = session_exit.read_boundary(step, skills_dir)
    assert not reading.states_the_rule
    assert reading.offers


def test_a_dropped_spec_rule_records_minus_one_never_a_clean_zero(tmp_path: Path) -> None:
    """The requirement going away must not read as the requirement being met.

    This module enforces a rule it does not own. If the project decides a
    boundary *should* offer an exit, the rule leaves `spec-v2-steps.md` and
    this gate must stop reading as a pass rather than quietly keep policing a
    policy nobody holds.
    """
    without_rule = tmp_path / "spec-v2-steps.md"
    without_rule.write_text("## How to read a step\n\nFour rules apply.\n", encoding="utf-8")
    measured = session_exit.measure(None, DEFAULT_SKILLS_DIR, without_rule)
    assert measured["step_boundaries_offering_an_exit"] == -1
    assert measured["rule_declared_in_step_spec"] is False
    assert "no longer declares" in measured["offenders"][0]["reasons"][0]


def test_a_missing_spec_document_records_minus_one_never_zero(tmp_path: Path) -> None:
    """A moved or deleted spec is the same failure as a deleted rule."""
    measured = session_exit.measure(None, DEFAULT_SKILLS_DIR, tmp_path / "gone.md")
    assert measured["step_boundaries_offering_an_exit"] == -1


def test_a_boundaryless_library_records_minus_one_never_zero(tmp_path: Path) -> None:
    """No `## Boundary` anywhere means nothing was checked, not nothing was wrong."""
    (tmp_path / "skills").mkdir()
    measured = session_exit.measure(None, tmp_path / "skills")
    assert measured["step_boundaries_offering_an_exit"] == -1
    assert "nothing was checked" in measured["offenders"][0]["reasons"][0]


def test_an_unloadable_step_list_records_minus_one_for_the_exit_gate(tmp_path: Path) -> None:
    """A step list that cannot be read yields no measurement, not a passing one."""
    bad = tmp_path / "steps.json"
    bad.write_text("{not json", encoding="utf-8")
    measured = session_exit.measure(bad, DEFAULT_SKILLS_DIR)
    assert measured["step_boundaries_offering_an_exit"] == -1


def test_a_boundary_that_says_nothing_out_loud_is_counted(tmp_path: Path, steps: StepList) -> None:
    """§3.2: ending silently is its own defect, and it also measures nothing.

    A section with no fenced example leaves the regression limb with no text to
    read, so a clean count there would mean "not checked", not "checked and
    clean".
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _boundary_skill(
        tmp_path,
        step,
        "**The exit is offered only when the session has run long, and never as a"
        " standard close.** Writes `last_activity`.",
    )
    reading = session_exit.read_boundary(step, skills_dir)
    assert reading.spoken_examples == 0
    assert reading.offers
    assert any("no spoken example" in reason for reason in reading.reasons)


def test_undecodable_boundary_prose_is_recorded_as_a_reason_never_raised(
    tmp_path: Path, steps: StepList
) -> None:
    """`UnicodeDecodeError` is a `ValueError` — a gate that raises records nothing."""
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"## Boundary\n\n\xff\xfe not utf-8\n")
    reading = session_exit.read_boundary(step, skills_dir)
    assert reading.offers
    assert any("could not be read" in reason for reason in reading.reasons)


def test_a_missing_skill_is_reported_not_counted_by_the_exit_gate(
    tmp_path: Path, steps: StepList
) -> None:
    """S7's gate owns "every step has a skill"; charging it twice overstates it."""
    step = next(s for s in steps.steps if s.id == "traits")
    reading = session_exit.read_boundary(step, tmp_path / "nonexistent")
    assert not reading.skill_md_exists
    assert not reading.offers


def test_exit_evidence_matches_measure(tmp_path: Path) -> None:
    """The committed number is what the code says now, not what it said once."""
    target = tmp_path / "D-15.json"
    measured = session_exit.write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["step_boundaries_offering_an_exit"] == 0


# --- D-15 review round (Qodo, PR #102): the exit and the offered skip -------


def test_the_offered_skip_is_not_read_as_an_exit(tmp_path: Path, steps: StepList) -> None:
    """§3.3's prescribed sentence must never count as an exit offer.

    The process calls two different things stopping. The *exit* ends the
    sitting; §3.3's *skip* — "we can stop here and go look at real jobs with
    what I have" — ends the first-run climb and sends the candidate forward to a
    provisional ranking. Counting the second would make a required behaviour
    unimplementable: a compliant boundary would fail the gate, and the gate
    would enforce the opposite of the process contract.
    """
    spoken = (
        '"We can stop here and go look at real jobs with what I have; the list will be'
        " rougher and I'll tell you what would sharpen it.\""
    )
    offers, shortcuts = session_exit._exit_offers((spoken,))
    assert offers == ()
    assert shortcuts == (spoken,), "the skip must be recorded, not silently dropped"

    step = next(s for s in steps.steps if s.id == "constraints")
    skills_dir = _boundary_skill(
        tmp_path,
        step,
        "**Never close by offering to end the session.** The exit is offered only when the"
        f" session has run long.\n\n```text\n{spoken}\n```",
    )
    reading = session_exit.read_boundary(step, skills_dir)
    assert not reading.offers, reading.reasons


def test_exit_offers_phrased_another_way_are_still_counted(tmp_path: Path, steps: StepList) -> None:
    """The pattern is enumerated, so its coverage is the whole of its worth.

    Review found these four phrasings passing straight through: a boundary
    could state the governing rule and then offer the door in the example, with
    the count still reading zero.
    """
    for spoken in (
        '"Shall we wrap up here?"',
        '"End here, and pick it up next time?"',
        '"Want to take a break and resume tomorrow?"',
        '"That\'s probably enough for one sitting."',
    ):
        offers, shortcuts = session_exit._exit_offers((spoken,))
        assert offers == (spoken,), f"not read as an exit offer: {spoken}"
        assert shortcuts == ()


def test_the_skip_licence_needs_a_forward_destination(tmp_path: Path, steps: StepList) -> None:
    """An exit cannot be laundered into a skip by sounding constructive.

    The licence requires the line to name going on to the jobs, the offers or
    the ranking *now*. A sentence that sends the candidate to their ranking is
    the skip; one that just sounds warm about leaving is the exit.
    """
    offers, shortcuts = session_exit._exit_offers(
        ('"We can stop here, and it\'s been really useful — rest up."',)
    )
    assert offers, "a warm exit is still an exit"
    assert shortcuts == ()


def test_every_skill_preserves_the_offered_skip() -> None:
    """The committed rule must forbid the exit without deleting §3.3's shortcut.

    The first cut said "never close by offering to stop", which reads as
    forbidding the skip too — §3.3 requires it at the end of every first-run
    step, so a rule that suppressed it would remove a documented path through
    the process.
    """
    for skill_md in sorted(DEFAULT_SKILLS_DIR.glob("step-*/SKILL.md")):
        section = session_exit.boundary_section(skill_md.read_text(encoding="utf-8"))
        assert section is not None, skill_md
        _, prose = session_exit.split_spoken_and_prose(section)
        assert "§3.3" in prose, f"{skill_md.parent.name} does not preserve the offered skip"


def test_the_process_spec_distinguishes_the_exit_from_the_skip() -> None:
    """§3.2 and §3.3 must not read as one rule, in either direction.

    §3.2 forbidding the exit while §3.3 requires the skip is only coherent if
    both say which of the two they mean. This is D-15's own failure mode — a
    rule in one document contradicted by another — applied to the fix for it.
    """
    process = (Path("status") / "spec-v2-process.md").read_text(encoding="utf-8")
    assert "Two different things get called stopping" in process
    assert "This is a move forward, not the exit of §3.2" in process


# --- D-13: no step skill opens a silent stretch on a waiting candidate ------


def _protocol_skill(tmp_path: Path, step: Step, protocol: str) -> Path:
    """A one-step synthetic library whose SKILL.md carries `protocol`.

    A `## Stop rule` heading follows, so the tests exercise the same
    section-terminated parse the real files get rather than the end-of-file
    special case.
    """
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        f"## Protocol — the manner, not the mechanism\n\n{protocol}\n\n"
        "## Stop rule\n\nnone\n",
        encoding="utf-8",
    )
    return skills_dir


_CONFORMING_RULE = (
    "**Say what is happening before a silence.** Work the candidate waits through is named\n"
    "**before** it starts, in one short line, and closed when it finishes.\n"
)
_CONFORMING_EXAMPLE = (
    '```text\n"Saving that now — one moment."\n'
    "…then, once the work is finished…\n"
    '"All set — that\'s saved."\n```'
)


def test_every_step_skill_requires_acknowledging_before_a_silent_setup() -> None:
    """D-13's gate over the committed library: `== 0`, and the rule is really there.

    The count alone would pass on a library that stated the rule and never
    demonstrated it, so the two things that make the zero meaningful are
    asserted with it: every protocol states the governing rule, and every
    protocol carries a spoken line that actually performs the disclosure.
    """
    measured = step_narration.measure()
    assert measured["step_skills_without_a_progress_disclosure_rule"] == 0, measured["offenders"]
    assert measured["steps_checked"] == 13
    assert measured["protocols_checked"] == 13
    assert measured["rule_declared_in_step_spec"] is True

    for reading in measured["readings"]:
        assert reading["states_the_rule"], f"{reading['step']} states no rule to govern the silence"
        assert reading["disclosures"], f"{reading['step']} demonstrates the disclosure nowhere"
        assert reading["completions"], f"{reading['step']} never closes the pause it opened"


def test_the_silent_library_is_counted(tmp_path: Path, steps: StepList) -> None:
    """The regression limb: the state all thirteen skills were in on the day.

    Verified against the pre-fix library with `--skills-dir` over a `git
    archive HEAD` copy: 13 offenders, all thirteen on both the rule limb and
    the demonstration limb. This is that library in miniature — a protocol
    that describes the conversation and never mentions the work underneath it.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(
        tmp_path, step, "- Open by naming what was learned, and ask one thing at a time."
    )
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.lacks_the_rule
    assert not reading.states_the_rule
    assert reading.disclosures == ()
    assert any("no rule governing" in reason for reason in reading.reasons)
    assert any("no spoken example" in reason for reason in reading.reasons)


def test_stating_the_rule_is_not_read_as_performing_it(tmp_path: Path, steps: StepList) -> None:
    """The rule limb and the demonstration limb are independent, deliberately.

    D-15's review round is the record of why: the model copies the example. A
    skill that states the rule and demonstrates it nowhere leaves the text a
    model actually reaches for unchanged, so the rule alone does not satisfy
    this gate.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(tmp_path, step, _CONFORMING_RULE)
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.states_the_rule
    assert reading.disclosures == ()
    assert reading.lacks_the_rule


def test_the_rule_sentence_does_not_trip_the_check_it_satisfies(
    tmp_path: Path, steps: StepList
) -> None:
    """The prose/fence split, without which no library could pass.

    The rule is stated in prose and performed in a fenced block, and the two
    limbs read different halves of the section. Were the fences left in the
    prose, the sentence naming the silence would be indistinguishable from an
    example of it.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(tmp_path, step, _CONFORMING_RULE + "\n" + _CONFORMING_EXAMPLE)
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.states_the_rule
    assert reading.disclosures == ('"Saving that now — one moment."',)
    assert reading.completions == ('"All set — that\'s saved."',)
    assert not reading.lacks_the_rule


def test_an_example_without_a_rule_is_counted(tmp_path: Path, steps: StepList) -> None:
    """One demonstration is not a rule — the next skill written copies neither."""
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(tmp_path, step, "- Ask warmly.\n\n" + _CONFORMING_EXAMPLE)
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.disclosures
    assert not reading.states_the_rule
    assert reading.lacks_the_rule


def test_a_pause_with_no_subject_is_not_a_disclosure() -> None:
    """ "One moment" alone tells the candidate nothing about what is happening."""
    assert step_narration._disclosures(('"One moment."',)) == ()


def test_a_claim_with_no_pause_is_not_a_disclosure() -> None:
    """Naming the work without marking the wait leaves nothing to wait through."""
    assert step_narration._disclosures(('"I am saving that."',)) == ()


def test_first_contact_must_acknowledge_before_the_setup(tmp_path: Path, steps: StepList) -> None:
    """The reported defect in its exact shape: the greeting came afterwards.

    Both halves were present in the live transcript — the tool did eventually
    say hello. It said it after the profile tree had been built in silence,
    which is the ordering this limb reads as character offsets rather than as
    presence.
    """
    step = next(s for s in steps.steps if s.n == 0)
    after = _protocol_skill(
        tmp_path / "after",
        step,
        _CONFORMING_RULE + '\n```text\n"Setting your profile up — one moment. Hello, Marcos."\n```',
    )
    reading = step_narration.read_narration(step, after)
    assert reading.first_contact
    assert reading.acknowledges_first is False
    assert any("acknowledges them" in reason for reason in reading.reasons)

    before = _protocol_skill(
        tmp_path / "before",
        step,
        _CONFORMING_RULE
        + '\n```text\n"Nice to meet you, Marcos. Let me get your profile'
        + ' set up — one moment."\n"Thanks for waiting. Here\'s how this works."\n```',
    )
    ok = step_narration.read_narration(step, before)
    assert ok.acknowledges_first is True
    assert not ok.lacks_the_rule


def test_a_later_step_is_not_asked_to_greet(tmp_path: Path, steps: StepList) -> None:
    """Step 4's candidate has been said hello to already; asking twice is a script."""
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(tmp_path, step, _CONFORMING_RULE + "\n" + _CONFORMING_EXAMPLE)
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.first_contact is False
    assert reading.acknowledges_first is None
    assert not reading.lacks_the_rule


def test_the_greeting_limb_is_read_from_the_step_list_not_the_prose(
    tmp_path: Path, steps: StepList
) -> None:
    """Which step must greet is spec data, never a regex over the skill's words.

    The first cut detected it by searching the text for "creates their
    profile" — and matched all thirteen skills, because the shared rule
    sentence names profile creation. The probe found the rule rather than the
    behaviour and reported twelve false offenders. A skill that merely talks
    about creating a profile is not thereby first contact.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(
        tmp_path,
        step,
        _CONFORMING_RULE
        + "\n- Never offer to create a profile here; step 0 creates their profile.\n\n"
        + _CONFORMING_EXAMPLE,
    )
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.first_contact is False
    assert not reading.lacks_the_rule


def test_a_dropped_narration_rule_records_minus_one_never_a_clean_zero(tmp_path: Path) -> None:
    """The requirement going away must not read as the requirement being met."""
    without_rule = tmp_path / "spec-v2-steps.md"
    without_rule.write_text("## How to read a step\n\nFour rules apply.\n", encoding="utf-8")
    measured = step_narration.measure(None, DEFAULT_SKILLS_DIR, without_rule)
    assert measured["step_skills_without_a_progress_disclosure_rule"] == -1
    assert measured["rule_declared_in_step_spec"] is False
    assert "no longer declares" in measured["offenders"][0]["reasons"][0]


def test_a_missing_spec_document_records_minus_one_for_the_narration_gate(tmp_path: Path) -> None:
    """A moved or deleted spec is the same failure as a deleted rule."""
    measured = step_narration.measure(None, DEFAULT_SKILLS_DIR, tmp_path / "gone.md")
    assert measured["step_skills_without_a_progress_disclosure_rule"] == -1


def test_a_protocolless_library_records_minus_one_never_zero(tmp_path: Path) -> None:
    """No `## Protocol` anywhere means nothing was checked, not nothing was wrong."""
    (tmp_path / "skills").mkdir()
    measured = step_narration.measure(None, tmp_path / "skills")
    assert measured["step_skills_without_a_progress_disclosure_rule"] == -1
    assert "nothing was checked" in measured["offenders"][0]["reasons"][0]


def test_an_unloadable_step_list_records_minus_one_for_the_narration_gate(tmp_path: Path) -> None:
    """A step list that cannot be read yields no measurement, not a passing one."""
    bad = tmp_path / "steps.json"
    bad.write_text("{not json", encoding="utf-8")
    measured = step_narration.measure(bad, DEFAULT_SKILLS_DIR)
    assert measured["step_skills_without_a_progress_disclosure_rule"] == -1


def test_a_protocolless_skill_is_counted_with_its_reason(tmp_path: Path, steps: StepList) -> None:
    """A skill with no `## Protocol` has neither half, and says so."""
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("## Stop rule\n\nnone\n", encoding="utf-8")
    reading = step_narration.read_narration(step, skills_dir)
    assert not reading.has_protocol_section
    assert any("no `## Protocol` section" in reason for reason in reading.reasons)


def test_undecodable_protocol_prose_is_recorded_as_a_reason_never_raised(
    tmp_path: Path, steps: StepList
) -> None:
    """`UnicodeDecodeError` is a `ValueError` — a gate that raises records nothing."""
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_bytes(b"## Protocol\n\n\xff\xfe not utf-8\n")
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.lacks_the_rule
    assert any("could not be read" in reason for reason in reading.reasons)


def test_a_missing_skill_is_reported_not_counted_by_the_narration_gate(
    tmp_path: Path, steps: StepList
) -> None:
    """S7's gate owns "every step has a skill"; charging it twice overstates it."""
    step = next(s for s in steps.steps if s.id == "traits")
    reading = step_narration.read_narration(step, tmp_path / "nonexistent")
    assert not reading.skill_md_exists
    assert not reading.lacks_the_rule


def test_probe_reads_every_step_in_settled_order_for_the_narration_gate(steps: StepList) -> None:
    """Every step is walked, in spec order — a skipped step is a silent pass."""
    readings = step_narration.probe(steps)
    assert [r.n for r in readings] == sorted(s.n for s in steps.steps)


def test_narration_evidence_matches_measure(tmp_path: Path) -> None:
    """The committed number is what the code says now, not what it said once."""
    target = tmp_path / "D-13.json"
    measured = step_narration.write_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["step_skills_without_a_progress_disclosure_rule"] == 0


def _rule_paragraph(document: Path) -> str:
    """The paragraph of `document` that carries the narration rule."""
    text = document.read_text(encoding="utf-8")
    for paragraph in re.split(r"\n(?=- \*\*)|\n\s*\n", text):
        if step_narration.CROSS_CUTTING_RULE_RE.search(paragraph):
            return paragraph
    return ""


def test_both_specs_state_the_narration_rule_not_merely_its_name() -> None:
    """The two documents agree, which is the whole of D-15's root cause.

    D-15 was one rule stated in `spec-v2-steps.md` and contradicted in
    `spec-v2-process.md` §3.2, with the live session sitting between them. The
    same rule is therefore added to both at once.

    Searching both documents for the rule's *title* is not enough, and review
    on PR #105 said so: either document could reverse or gut the substantive
    requirement while keeping the phrase, and a test looking only for the
    phrase would still pass. So each document is held to the same standard the
    skills are — `_states_the_rule`, which requires governing language with the
    title struck out — and to both halves of the requirement by name.
    """
    for document in (Path("status/spec-v2-steps.md"), Path("status/spec-v2-process.md")):
        paragraph = _rule_paragraph(document)
        assert paragraph, f"{document} no longer carries the narration rule at all"
        assert step_narration._states_the_rule(paragraph), (
            f"{document} names the rule but no longer governs anything with it"
        )
        # Both halves, by name: the work is announced before it starts...
        assert re.search(r"\bbefore\b", paragraph), f"{document} drops the ordering requirement"
        # ...and the pause is closed when it ends.
        assert re.search(r"clos(?:e|ed|ing)\s+when\s+it\s+(?:finishes|ends)", paragraph), (
            f"{document} drops the requirement to close the pause"
        )
        # ...and the person comes first, which is the reported defect itself.
        assert re.search(r"\bfirst\b", paragraph), (
            f"{document} drops the acknowledge-first ordering"
        )

    steps_doc = Path("status/spec-v2-steps.md").read_text(encoding="utf-8")
    assert "Five rules apply to every step" in steps_doc


# --- D-13 review round (Qodo, PR #105) -------------------------------------


def test_the_rule_heading_alone_does_not_state_the_rule() -> None:
    """The phrase naming a rule may not also be the evidence it governs anything.

    "Say what is happening before a silence" carries a subject token *and* the
    governor `before`. So a Protocol section stripped down to nothing but the
    bold heading — every word of the actual instruction deleted — satisfied
    both halves of limb 1 and the gate reported conformance.

    That is the self-trip this module already avoided once between its limbs,
    recurring *inside* one of them. Governance is now searched for with the
    title struck out.
    """
    assert not step_narration._states_the_rule("**Say what is happening before a silence.**")
    assert not step_narration._states_the_rule(
        "**Say what is happening before a silence.** It is a good idea."
    )
    assert step_narration._states_the_rule(
        "**Say what is happening before a silence.** Work the candidate waits through is "
        "named before it starts, and never after."
    )


def test_an_example_that_never_closes_the_pause_is_counted(tmp_path: Path, steps: StepList) -> None:
    """Opening a silence and never coming back out of it is half a disclosure.

    The rule requires the work to be named before it starts **and closed when
    it finishes**, and the owner's correction names both halves. The first cut
    demonstrated only the opening half in twelve of thirteen skills and passed
    its own gate — a prose requirement nothing measured. On this task above
    all, an undemonstrated half is an unimplemented one.
    """
    step = next(s for s in steps.steps if s.id == "traits")
    skills_dir = _protocol_skill(
        tmp_path,
        step,
        _CONFORMING_RULE + '\n```text\n"Saving that now — one moment."\n```',
    )
    reading = step_narration.read_narration(step, skills_dir)
    assert reading.disclosures
    assert reading.completions == ()
    assert reading.lacks_the_rule
    assert any("closing the pause" in reason for reason in reading.reasons)


def test_every_step_skill_shows_the_candidate_the_pause_ending() -> None:
    """The committed library closes every pause it opens, in its own words."""
    for reading in step_narration.probe():
        assert reading.completions, f"{reading.step} opens a silence it never closes"


# --- T67: standing scope, re-surfaced on return (§5.7) -----------------


def _decision(**overrides: object) -> ScopeDecision:
    """A §5.5 row, with only what a test cares about spelled out."""
    row: dict[str, object] = {
        "about": "employer:acme",
        "decision": "narrow",
        "accepted": True,
        "cycle": 3,
        "reason": "you read both of Acme's adverts end to end",
        "session": "s1",
        "proposed_alternatives": ("widen:country",),
        "trigger": "the same eight adverts keep coming back",
    }
    row.update(overrides)
    return ScopeDecision(**row)  # type: ignore[arg-type]


_RETURNING = Resumption(
    step="history",
    rule="position",
    reason="last time we were partway through your work history",
)


def test_returning_shows_every_standing_scope_decision() -> None:
    """§5.7: the opening extends from position to substance — all of it."""
    log = [
        _decision(),
        EvidenceRow(kind="episode", step="history", session="s1"),
        _decision(about="country:spain", decision="widen", accepted=False, cycle=4),
    ]
    opening = sourcing_scope_review.resurface(_RETURNING, log)

    standing = sourcing_scope_review.standing_decisions(log)
    assert len(standing) == 2, "a refusal is a standing decision too (§5.5)"
    said = opening.say()
    assert _RETURNING.reason in said, "the opening still says where we stopped"
    for row in standing:
        assert row.about in said, f"{row.about} was never re-surfaced"
        assert row.decision in said
    assert "refused" in said, "a refusal that never re-surfaces cannot be revisited"


def test_a_resurfaced_decision_can_be_corrected_in_place() -> None:
    """Consent nobody can review is not consent — so the review can change it."""
    refusal = _decision(about="country:spain", decision="widen", accepted=False, cycle=4)

    corrected = sourcing_scope_review.correct(
        refusal, accepted=True, reason="I would look at Portugal now", session="s2", cycle=5
    )
    assert corrected.accepted
    assert corrected.trigger == sourcing_scope_review.REVIEW_TRIGGER

    log = [refusal, corrected]
    assert sourcing_scope_review.standing_decisions(log) == (corrected,), (
        "the correction is what stands, not the old word"
    )
    assert "accepted" in sourcing_scope_review.resurface(_RETURNING, log).say()


def test_an_opening_that_omits_a_standing_decision_is_rejected() -> None:
    """The rule has to bite, or the count is zero by nothing having tried it."""
    with pytest.raises(ValidationError):
        sourcing_scope_review.Opening(
            position=_RETURNING.announcement(),
            standing=(_decision(),),
            lines=(sourcing_scope_review.CORRECTION_INVITATION,),
        )


def test_a_review_that_never_invites_a_correction_is_rejected() -> None:
    """Showing the decisions without saying they can change is not a review."""
    with pytest.raises(ValidationError):
        sourcing_scope_review.Opening(
            position=_RETURNING.announcement(),
            standing=(),
            lines=(),
        )


def test_a_log_out_of_recorded_order_is_refused_not_believed() -> None:
    """The latest word wins — so the argument's order is a claim, and is checked."""
    with pytest.raises(ValueError, match="recorded order"):
        sourcing_scope_review.standing_decisions(
            [_decision(cycle=4), _decision(cycle=2, about="employer:globex")]
        )


def test_step_zero_re_surfaces_scope_not_only_position() -> None:
    """The skill that opens on return has to say it shows the standing scope."""
    text = (DEFAULT_SKILLS_DIR / "step-00-identify" / "SKILL.md").read_text(encoding="utf-8")
    assert "integral.sourcing_scope_review" in text, "step 0 does not name the re-surfacing"
    assert "scope" in text.lower()


def test_scope_review_evidence_matches_measure(tmp_path: Path) -> None:
    written = sourcing_scope_review.write_evidence(tmp_path / "T67.json")
    assert json.loads((tmp_path / "T67.json").read_text(encoding="utf-8")) == written
    assert written["standing_scope_decisions_not_resurfaced"] == 0
