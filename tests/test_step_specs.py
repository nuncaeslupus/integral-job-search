"""S2 — every step has a specification, and every specification fills the template."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.process_spec import DEFAULT_STEPS_PATH, Step, load_steps
from integral.step_specs import (
    DEFAULT_STEP_SPECS_DOC,
    MIN_FIELD_WORDS,
    REQUIRED_FIELDS,
    collect_violations,
    field_words,
    measure,
    split_steps,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_a_step_flag_must_be_a_real_boolean_not_something_coercible_to_one() -> None:
    """The S12 gate counts only *absent* declarations, on the stated grounds
    that a present non-boolean would already have failed `load_steps()`.

    Pydantic's ordinary `bool` is lax, so that claim was false: `1`, `0`,
    `"true"`, `"false"` and `"yes"` all validated and became `True`/`False`.
    A typo'd declaration was therefore counted as a declaration, and the value
    it produced looked entirely legitimate downstream — the gate reporting zero
    unclassified steps while a step's classification came from the string
    "yes". `2` was already rejected, so only the values that look deliberate
    got through, which is the worst subset to let past.

    The same laxness applied to every flag in the file, so all of them are
    strict — this file is the settled model other modules read instead of
    keeping their own copy, and a typo that still parses is the failure that
    model exists to prevent.
    """
    steps = load_steps()
    base = steps.steps[0].model_dump()

    for flag in ("required", "automatic", "accepts_candidate_free_text"):
        for coercible in (1, 0, "true", "false", "yes"):
            with pytest.raises(ValidationError):
                Step.model_validate({**base, flag: coercible})

    # The committed model is unaffected: every flag in it is a real boolean.
    assert load_steps().steps[0].accepts_candidate_free_text is not None


def test_every_step_declares_whether_it_takes_candidate_free_text() -> None:
    """S12: `Step.accepts_candidate_free_text` is the completeness check that
    stops a step being added to `spec-v2-steps.json` without one — the
    migration's own "did every step actually get a value" test, over the
    committed file this repo ships. `None` is a real, undeclared state, not
    coerced to `False`; `integral.profile_capture.unclassified_free_text_steps`
    is the same check as a reusable gate metric, exercised more thoroughly
    (including the failure case) in `tests/test_profile_capture.py`."""
    steps = load_steps()

    undeclared = [step.id for step in steps.steps if step.accepts_candidate_free_text is None]

    assert undeclared == [], f"steps with no free-text declaration: {undeclared}"


def test_every_step_spec_fills_the_template() -> None:
    """The brief's ten fields plus the two §10 requires every step to repeat."""
    sections = split_steps(DEFAULT_STEP_SPECS_DOC.read_text(encoding="utf-8"))

    for step in load_steps().steps:
        assert step.n in sections, f"step {step.n} ({step.id}) has no specification"
        counts = field_words(sections[step.n])
        missing = [f for f in REQUIRED_FIELDS if counts.get(f, 0) < MIN_FIELD_WORDS]
        assert not missing, f"step {step.n} ({step.id}) leaves {missing} unanswered"


def test_every_step_has_a_stop_rule() -> None:
    """The one field that cannot be defaulted: a step with no cap runs until the
    candidate gives up, which is the failure the whole design exists to avoid."""
    sections = split_steps(DEFAULT_STEP_SPECS_DOC.read_text(encoding="utf-8"))

    for step in load_steps().steps:
        stop_rule_words = field_words(sections[step.n]).get("Stop rule", 0)
        assert stop_rule_words >= MIN_FIELD_WORDS, f"step {step.n} ({step.id}) has no stop rule"


def test_every_step_says_what_happens_when_the_candidate_declines() -> None:
    """Non-insistence is the rule that overrides coverage, so it is per step or it
    is nowhere — a general principle is what the last spec written will not have."""
    sections = split_steps(DEFAULT_STEP_SPECS_DOC.read_text(encoding="utf-8"))

    for step in load_steps().steps:
        declined = field_words(sections[step.n]).get("When declined", 0)
        assert declined >= MIN_FIELD_WORDS, f"step {step.n} ({step.id}) does not handle a decline"


def test_the_gate_passes_on_the_committed_specifications() -> None:
    measured = measure()

    assert measured["violations"] == []
    assert measured["step_specs_complete_fraction"] == 1.0


def test_the_divisor_is_the_settled_count_not_the_number_of_specs_written(
    tmp_path: Path,
) -> None:
    """Dividing by what was written makes any amount of work look complete: a
    document specifying one step flawlessly must score 1/13, never 1/1."""
    doc = tmp_path / "steps.md"
    one_step = "\n\n".join(
        f"**{field}.** " + " ".join(["word"] * (MIN_FIELD_WORDS + 2)) for field in REQUIRED_FIELDS
    )
    doc.write_text(f"## Step 0 — Identify\n\n{one_step}\n", encoding="utf-8")

    measured = measure(doc=doc)

    assert measured["steps_specified"] == 1
    assert measured["step_count"] == load_steps().step_count
    assert measured["step_specs_complete_fraction"] == round(1 / load_steps().step_count, 4)


def test_a_field_named_but_not_answered_does_not_count(tmp_path: Path) -> None:
    """A heading over an empty body passes a presence check and answers nothing."""
    doc = tmp_path / "steps.md"
    fields = []
    for field in REQUIRED_FIELDS:
        body = "thin" if field == "Privacy" else " ".join(["word"] * (MIN_FIELD_WORDS + 2))
        fields.append(f"**{field}.** {body}")
    doc.write_text("## Step 0 — Identify\n\n" + "\n\n".join(fields) + "\n", encoding="utf-8")

    violations = collect_violations(doc=doc)

    assert any("`Privacy`" in violation for violation in violations)


def test_a_step_outside_the_settled_list_is_rejected(tmp_path: Path) -> None:
    doc = tmp_path / "steps.md"
    body = " ".join(["word"] * (MIN_FIELD_WORDS + 2))
    filled = "\n\n".join(f"**{f}.** {body}" for f in REQUIRED_FIELDS)
    doc.write_text(f"## Step 99 — Invented\n\n{filled}\n", encoding="utf-8")

    violations = collect_violations(doc=doc)

    assert any("step 99" in violation for violation in violations)


def test_evidence_records_the_fraction_and_its_divisor(tmp_path: Path) -> None:
    evidence = tmp_path / "S2.json"

    measured = write_evidence(evidence=evidence)

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded == measured
    assert (
        recorded["step_count"]
        == json.loads(DEFAULT_STEPS_PATH.read_text(encoding="utf-8"))["step_count"]
    )


@pytest.mark.skipif(
    not (_REPO_ROOT / ".claude" / "skills" / "specify" / "scripts" / "create_reader.py").is_file()
    or shutil.which("uv") is None,
    reason="the specify skill is not vendored here, or uv is unavailable",
)
def test_regenerating_the_reader_produces_no_diff(tmp_path: Path) -> None:
    """The reader is generated but committed, so it can silently fall behind the
    Markdown — leaving a reviewer commenting on text that has since changed."""
    script = _REPO_ROOT / ".claude" / "skills" / "specify" / "scripts" / "create_reader.py"
    committed = _REPO_ROOT / "docs" / "spec-v2-steps"
    if not (committed / "spec-reader.html").is_file():
        pytest.skip("reader has not been generated yet")

    # The generator seeds reviewer notes from `notes.json` in its output
    # directory, so regenerating into an empty one produces a reader with empty
    # note fields and a spurious diff. Same inputs or the comparison is
    # meaningless — this check exists to catch a stale document, not to
    # rediscover that two different inputs give two different outputs.
    seed = committed / "notes.json"
    if seed.is_file():
        shutil.copy(seed, tmp_path / "notes.json")

    # Run it the way `make reader` does. Invoking it with a bare interpreter
    # skips for a missing `markdown` import, and a check that always skips is a
    # check that never runs — which is how a guarantee ends up true of the
    # function and false of the tool.
    result = subprocess.run(
        [
            "uv",
            "run",
            "--with",
            "markdown",
            "python3",
            str(script),
            "--input",
            str(DEFAULT_STEP_SPECS_DOC),
            "--output-dir",
            str(tmp_path),
            "--name",
            "Job Search — Specification v2",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"create_reader could not run here: {result.stderr.strip()[:160]}")

    for name in ("spec-reader.html", "spec-annotated.md"):
        regenerated = (tmp_path / name).read_text(encoding="utf-8")
        on_disk = (committed / name).read_text(encoding="utf-8")
        # The generator stamps the date it ran; everything else must match.
        assert _without_dates(regenerated) == _without_dates(on_disk), (
            f"{name} is stale — run `make reader` and commit the result"
        )


def _without_dates(text: str) -> list[str]:
    return [line for line in text.split("\n") if not re.search(r"\d{4}-\d{2}-\d{2}", line)]


def test_a_duplicated_step_heading_is_reported(tmp_path: Path) -> None:
    """Only the last section under a repeated number is checked, so without this
    an earlier duplicate could be empty and the gate would still read 1.0."""
    doc = tmp_path / "steps.md"
    body = " ".join(["word"] * (MIN_FIELD_WORDS + 2))
    filled = "\n\n".join(f"**{f}.** {body}" for f in REQUIRED_FIELDS)
    doc.write_text(
        f"## Step 0 — Identify\n\n**Purpose.** thin\n\n## Step 0 — Identify\n\n{filled}\n",
        encoding="utf-8",
    )

    violations = collect_violations(doc=doc)

    assert any("headed 2 times" in violation for violation in violations)


def test_an_unloadable_step_list_is_a_violation_not_a_traceback(tmp_path: Path) -> None:
    """A gate that crashes records no number — the run that cannot measure must
    still leave evidence saying why."""
    broken = tmp_path / "steps.json"
    broken.write_text("{ not json", encoding="utf-8")

    violations = collect_violations(steps_path=broken)
    measured = measure(steps_path=broken)

    assert any("step list could not be loaded" in violation for violation in violations)
    assert measured["step_specs_complete_fraction"] == 0.0
    assert measured["step_count"] == 0


def test_a_missing_step_list_writes_evidence_rather_than_failing(tmp_path: Path) -> None:
    evidence = tmp_path / "S2.json"

    measured = write_evidence(evidence=evidence, steps_path=tmp_path / "absent.json")

    assert evidence.is_file()
    assert measured["step_specs_complete_fraction"] == 0.0
