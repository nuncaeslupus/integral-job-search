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

import pytest

from jobsearch.process_spec import StepList, load_steps
from jobsearch.step_skills import (
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
