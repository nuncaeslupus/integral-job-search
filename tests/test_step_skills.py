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

from integral import employment_mode, sourcing_scope_review
from integral.candidate import EmploymentModeName
from integral.process_spec import Step, StepList, load_steps
from integral.session import Resumption
from integral.sourcing_strategy import EvidenceRow, ScopeDecision
from integral.step_skills import (
    DEFAULT_SKILLS_DIR,
    DEFAULT_T84_EVIDENCE_PATH,
    DRAFTING_RULES_OWNER,
    SkillCheck,
    _main,
    check_step_skill,
    measure,
    measure_drafting_rules,
    probe_step_skills,
    read_drafting_rules,
    skill_dir_name,
    write_drafting_rules_evidence,
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
    "application": "no cap on versions",
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


def test_write_evidence_redirects_both_records_not_just_s7(tmp_path: Path) -> None:
    """`--write-evidence PATH` must move T84's record too.

    It honoured the flag for S7 and used the repository default for T84, so a
    caller redirecting to a temp directory still overwrote the committed
    `status/evidence/T84.json`. A test writing to `tmp_path` is exactly the
    caller that would have done it.
    """
    committed = DEFAULT_T84_EVIDENCE_PATH
    before = committed.read_text(encoding="utf-8") if committed.exists() else None

    target = tmp_path / "S7.json"
    _main(["step_skills", "--write-evidence", str(target)])

    assert (tmp_path / DEFAULT_T84_EVIDENCE_PATH.name).exists()
    after = committed.read_text(encoding="utf-8") if committed.exists() else None
    assert after == before, "the committed T84 record must not be touched"


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


# --- T84: step 11's two drafting rules --------------------------------------


def test_step_eleven_states_the_relevance_weighted_cut_rule(steps: StepList) -> None:
    step = next(s for s in steps.steps if s.id == DRAFTING_RULES_OWNER)
    reading = read_drafting_rules(step, DEFAULT_SKILLS_DIR)
    assert reading.states_cut_rule, reading.reasons


def test_step_eleven_states_the_interview_backtrack_test(steps: StepList) -> None:
    step = next(s for s in steps.steps if s.id == DRAFTING_RULES_OWNER)
    reading = read_drafting_rules(step, DEFAULT_SKILLS_DIR)
    assert reading.states_backtrack_test, reading.reasons


def test_the_cut_rule_names_narrative_load(tmp_path: Path, steps: StepList) -> None:
    """The third factor is the one most likely to be dropped in a paraphrase."""
    step = next(s for s in steps.steps if s.id == DRAFTING_RULES_OWNER)
    reading = read_drafting_rules(step, DEFAULT_SKILLS_DIR)
    assert reading.names_narrative_load

    # relevance and uniqueness alone, narrative load dropped, must not pass —
    # otherwise a paraphrase that quietly lost the third factor would score
    # the same as the real rule.
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        "Score each line by relevance to this posting and uniqueness in the "
        "document. Cut the lowest-scoring lines first, ignoring section "
        "boundaries.\n",
        encoding="utf-8",
    )
    reading = read_drafting_rules(step, skills_dir)
    assert not reading.names_narrative_load
    assert not reading.states_cut_rule
    assert any("narrative load" in reason for reason in reading.reasons)


def test_the_committed_skill_states_both_drafting_rules() -> None:
    """T84's gate over the committed library: `== 0`, and the rules are really there."""
    measured = measure_drafting_rules()
    assert measured["step_skills_without_the_drafting_rules"] == 0, measured["offenders"]
    assert measured["step_skills_checked"] == 13
    assert measured["gate_status"] == "measured"
    assert measured["owning_steps"] == [DRAFTING_RULES_OWNER]


def test_only_the_owning_step_is_required_to_carry_the_rules(steps: StepList) -> None:
    """Every other step's SKILL.md is never inspected for a rule that is not its own."""
    for step in steps.steps:
        if step.id == DRAFTING_RULES_OWNER:
            continue
        reading = read_drafting_rules(step, DEFAULT_SKILLS_DIR)
        assert not reading.owns_drafting_rules
        assert not reading.lacks_the_rules


def test_a_synthetic_skill_missing_the_backtrack_test_is_counted(
    tmp_path: Path, steps: StepList
) -> None:
    step = next(s for s in steps.steps if s.id == DRAFTING_RULES_OWNER)
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        "Score each line by relevance, uniqueness and narrative load. Cut the "
        "lowest-scoring lines first, ignoring section boundaries.\n",
        encoding="utf-8",
    )
    reading = read_drafting_rules(step, skills_dir)
    assert reading.states_cut_rule
    assert not reading.states_backtrack_test
    assert reading.lacks_the_rules
    assert any("backtrack" in reason for reason in reading.reasons)


def test_a_complete_synthetic_drafting_skill_passes(tmp_path: Path, steps: StepList) -> None:
    step = next(s for s in steps.steps if s.id == DRAFTING_RULES_OWNER)
    skills_dir = tmp_path / "skills"
    skill_dir = skills_dir / skill_dir_name(step)
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: x\ndescription: x\n---\n\n"
        "Score each line by relevance, uniqueness and narrative load. Cut the "
        "lowest-scoring lines first, ignoring section boundaries.\n\n"
        "The interview backtrack test: OK, Flag it, or Never.\n",
        encoding="utf-8",
    )
    reading = read_drafting_rules(step, skills_dir)
    assert reading.states_cut_rule
    assert reading.states_backtrack_test
    assert not reading.lacks_the_rules
    assert reading.reasons == ()


def test_no_drafting_rules_owner_records_minus_one_never_a_clean_zero(tmp_path: Path) -> None:
    """A rename of the owning step's id must not read as a clean pass.

    The check only runs over the step whose id is `DRAFTING_RULES_OWNER`. If no
    step carries that id any more, a bare `0` would read as "both rules are
    stated everywhere they need to be" over a check that examined nothing.
    """
    spec = json.loads(Path("status/spec-v2-steps.json").read_text(encoding="utf-8"))
    for step in spec["steps"]:
        if step["id"] == DRAFTING_RULES_OWNER:
            step["id"] = "renamed_step"
    drifted = tmp_path / "steps.json"
    drifted.write_text(json.dumps(spec), encoding="utf-8")

    measured = measure_drafting_rules(drifted, DEFAULT_SKILLS_DIR)
    assert measured["step_skills_without_the_drafting_rules"] == -1
    assert measured["step_skills_checked"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert measured["owning_steps"] == []


def test_the_gate_does_not_pass_on_an_empty_input_set(tmp_path: Path) -> None:
    """A step list that cannot be read yields no measurement, not a passing one.

    The gate asserts `step_skills_without_the_drafting_rules == 0`, and an
    empty input set — nothing examined at all — produces zero too. So the
    evidence record carries `step_skills_checked` beside the violation count,
    and `gate_status` reads `"unmeasured"` whenever that count is `0`, which is
    what `gate_evidence.py`'s `status-key` reads before it ever looks at the
    metric itself.
    """
    bad = tmp_path / "not-json.json"
    bad.write_text("{not json", encoding="utf-8")
    measured = measure_drafting_rules(bad, DEFAULT_SKILLS_DIR)
    assert measured["step_skills_checked"] == 0
    assert measured["step_skills_without_the_drafting_rules"] == -1
    assert measured["gate_status"] == "unmeasured"


def test_t84_evidence_matches_measure(tmp_path: Path) -> None:
    """The committed number is what the code says now, not what it said once."""
    target = tmp_path / "T84.json"
    measured = write_drafting_rules_evidence(target)
    assert json.loads(target.read_text(encoding="utf-8")) == measured
    assert measured["step_skills_without_the_drafting_rules"] == 0
    assert measured["gate_status"] == "measured"
