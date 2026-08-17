"""S1 — the process specification is complete, and its step list is machine-readable."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobsearch.process_spec import (
    DEFAULT_PROCESS_DOC,
    DEFAULT_STEPS_PATH,
    MIN_ITEM_WORDS,
    REQUIRED_ITEMS,
    collect_violations,
    load_steps,
    measure,
    required_item_words,
    write_evidence,
)


def test_process_spec_answers_every_required_item() -> None:
    """Each of the six items S1 owes is anchored once, and answered rather than named."""
    document = DEFAULT_PROCESS_DOC.read_text(encoding="utf-8")
    counts = required_item_words(document)

    missing = [item for item in REQUIRED_ITEMS if item not in counts]
    assert not missing, f"required items with no anchor: {missing}"

    thin = {item: counts[item] for item in REQUIRED_ITEMS if counts[item] < MIN_ITEM_WORDS}
    assert not thin, f"required items present but unanswered: {thin}"


def test_the_settled_step_count_is_machine_readable() -> None:
    """S2 divides by this number, so it cannot live only in prose."""
    steps = load_steps()

    assert steps.step_count == len(steps.steps)
    assert steps.step_count > 0
    assert [step.n for step in steps.steps] == list(range(steps.step_count))
    assert len({step.id for step in steps.steps}) == steps.step_count


def test_every_step_in_the_list_has_a_named_gate_metric() -> None:
    """`not_implemented` is a valid state while a step is unbuilt; a blank metric is not."""
    for step in load_steps().steps:
        assert step.gate.metric.strip(), f"step {step.n} ({step.id}) names no gate metric"
        assert step.gate.state in {"implemented", "not_implemented"}


def test_every_step_promises_the_candidate_something_visible() -> None:
    """Brief §2.2: a step that only fills internal state will feel like an interrogation."""
    for step in load_steps().steps:
        assert step.visible_output.strip(), f"step {step.n} ({step.id}) has no visible output"


def test_the_gate_passes_on_the_committed_specification() -> None:
    measured = measure()
    assert measured["violations"] == []
    assert measured["process_spec_complete"] == 1


def test_a_document_missing_a_required_item_does_not_pass(tmp_path: Path) -> None:
    """The failure this gate exists for: a step list settled, a lifecycle unwritten."""
    body = " ".join(["word"] * (MIN_ITEM_WORDS + 10))
    kept = [item for item in REQUIRED_ITEMS if item != "offer-lifecycle"]
    doc = tmp_path / "process.md"
    doc.write_text(
        "\n\n".join(f"<!-- required-item: {item} -->\n{body}" for item in kept),
        encoding="utf-8",
    )

    violations = collect_violations(process_doc=doc, steps_path=DEFAULT_STEPS_PATH)

    assert any("offer-lifecycle" in violation for violation in violations)


def test_a_named_but_unanswered_item_does_not_pass(tmp_path: Path) -> None:
    """An anchor over an empty section passes a presence check and answers nothing."""
    body = " ".join(["word"] * (MIN_ITEM_WORDS + 10))
    sections = []
    for item in REQUIRED_ITEMS:
        sections.append(
            f"<!-- required-item: {item} -->\n" + ("thin" if item == "resumption" else body)
        )
    doc = tmp_path / "process.md"
    doc.write_text("\n\n".join(sections), encoding="utf-8")

    violations = collect_violations(process_doc=doc, steps_path=DEFAULT_STEPS_PATH)

    assert any("resumption" in violation for violation in violations)


def test_a_stale_step_count_is_rejected(tmp_path: Path) -> None:
    """A count that disagrees with the list would silently mis-measure S2."""
    raw = json.loads(DEFAULT_STEPS_PATH.read_text(encoding="utf-8"))
    raw["step_count"] = raw["step_count"] + 1
    stale = tmp_path / "steps.json"
    stale.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_steps(stale)

    violations = collect_violations(process_doc=DEFAULT_PROCESS_DOC, steps_path=stale)
    assert any("step list is invalid" in violation for violation in violations)


def test_a_step_with_a_blank_gate_metric_is_rejected(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_STEPS_PATH.read_text(encoding="utf-8"))
    raw["steps"][0]["gate"]["metric"] = ""
    blank = tmp_path / "steps.json"
    blank.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValidationError):
        load_steps(blank)


def test_evidence_records_the_step_count_s2_divides_by(tmp_path: Path) -> None:
    evidence = tmp_path / "S1.json"

    measured = write_evidence(evidence=evidence)

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded == measured
    assert recorded["step_count"] == load_steps().step_count
    assert recorded["process_spec_complete"] == 1
