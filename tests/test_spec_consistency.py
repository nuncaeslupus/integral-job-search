"""D-3 — a superseded gate must not survive as a gate in another document.

`status/spec-v2-steps.md` step 3 supersedes `story_failure_fraction >= 0.33`
explicitly: the revised History protocol forbids digging for failure episodes
to satisfy a quota, and a floor requires exactly that digging. The failure
this module exists to catch is not the superseded threshold itself — the step
spec already resolved it — it is a *reconciled-looking repo that still teaches
the old number to whoever reads a different document first*.
`status/specification.md`'s v1 success criteria and `docs/METHODS.md`'s
methodology entry both restated the floor as a live gate after the step spec
moved past it. A reader who starts in either of those documents, rather than
the step spec, would build to a number the protocol had already abandoned and
watch their gate pass against it.

`test_no_document_states_a_superseded_gate` is the committed-document check:
it must fail before the docs are fixed, and pass after. The rest exercise
`integral.spec_consistency` against synthetic documents so the mechanism is
shown to be general — keyed off the step spec's own declaration sentence,
never off the literal string `story_failure_fraction` — rather than a check
shaped to this one instance.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral.spec_consistency import (
    DIFFERENTIATOR_CLAIMS,
    MINIMUM_DECLARATIONS_FOUND,
    Contradiction,
    Declaration,
    find_contradictions,
    find_declarations,
    measure,
    measure_differentiator,
    write_differentiator_evidence,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_no_document_states_a_superseded_gate() -> None:
    """The committed documents must contain zero gate-shaped restatements of a
    superseded expression. This is the check the D-3 payload asks for, run
    against the real tree — it fails on the unreconciled documents and must
    pass once `status/specification.md` and `docs/METHODS.md` are fixed."""
    measured = measure()
    assert measured["superseded_declarations_found"] >= MINIMUM_DECLARATIONS_FOUND, (
        "no superseded-gate declaration was found in the step spec — the scan "
        "measured nothing, so a passing contradiction count would be vacuous"
    )
    assert measured["spec_gate_contradictions"] == 0, measured["contradictions"]


def test_the_known_declaration_is_found() -> None:
    """The story_failure_fraction supersession is exactly the declaration this
    check was filed for — if the sentence-shape regex stops matching it, the
    whole check goes quiet without anyone noticing."""
    declarations = find_declarations()
    exprs = {d.expr for d in declarations}
    assert "story_failure_fraction >= 0.33" in exprs


def test_a_gate_shaped_restatement_of_a_different_metric_is_caught(tmp_path: Path) -> None:
    """The scan must key off the step spec's declaration sentence, not off the
    literal string `story_failure_fraction` — otherwise the next superseded
    floor, for a metric nobody has thought of yet, would sail through
    unflagged. Proven here with a metric name the module has never seen."""
    source = tmp_path / "steps.md"
    source.write_text(
        "## Step 9\n\n"
        "**`widget_ratio >= 0.5` is superseded and must not be gated on.** "
        "The revised protocol reports it instead.\n",
        encoding="utf-8",
    )
    target = tmp_path / "spec.md"
    target.write_text(
        "## Success criteria\n\n- [ ] `widget_ratio >= 0.5` — at least half of widgets pass\n",
        encoding="utf-8",
    )

    declarations = find_declarations(source_docs=(source,))
    assert [d.expr for d in declarations] == ["widget_ratio >= 0.5"]

    contradictions = find_contradictions(declarations, target_docs=(target,))
    assert len(contradictions) == 1
    assert contradictions[0].expr == "widget_ratio >= 0.5"
    assert Path(contradictions[0].document).name == "spec.md"


def test_a_bare_metric_name_without_its_threshold_is_not_a_contradiction(tmp_path: Path) -> None:
    """`docs/METHODS.md`'s "Gate metrics" table names `story_failure_fraction`
    on its own, as a formula definition — that is exactly what "reported,
    never floored" requires, and must not itself be flagged. Only the metric
    *together with the superseded comparison* is a contradiction."""
    source = tmp_path / "steps.md"
    source.write_text(
        "**`widget_ratio >= 0.5` is superseded and must not be gated on.**\n",
        encoding="utf-8",
    )
    target = tmp_path / "methods.md"
    target.write_text(
        "| Metric | Formula | Used for |\n"
        "|---|---|---|\n"
        "| `widget_ratio` | passing widgets ÷ all widgets | Widget-bank composition |\n",
        encoding="utf-8",
    )

    declarations = find_declarations(source_docs=(source,))
    contradictions = find_contradictions(declarations, target_docs=(target,))
    assert contradictions == []


def test_a_gate_shaped_line_without_the_checklist_marker_is_still_caught(tmp_path: Path) -> None:
    """`docs/METHODS.md` states its floor as prose — "(gate: `metric >= n`)" —
    not as a `- [ ]` checklist item. The word "gate" alone must be enough to
    mark the context, or the METHODS.md restatement would never be caught."""
    source = tmp_path / "steps.md"
    source.write_text(
        "**`widget_ratio >= 0.5` is superseded and must not be gated on.**\n",
        encoding="utf-8",
    )
    target = tmp_path / "methods.md"
    target.write_text(
        "**What.** At least half of widgets must pass (gate: `widget_ratio >= 0.5`).\n",
        encoding="utf-8",
    )

    declarations = find_declarations(source_docs=(source,))
    contradictions = find_contradictions(declarations, target_docs=(target,))
    assert len(contradictions) == 1


def test_a_reported_only_mention_outside_any_gate_context_is_not_a_contradiction(
    tmp_path: Path,
) -> None:
    """Prose that reports the fraction without checklist or the word "gate" is
    exactly the resolution D-3 asks for, and must read as clean."""
    source = tmp_path / "steps.md"
    source.write_text(
        "**`widget_ratio >= 0.5` is superseded and must not be gated on.**\n",
        encoding="utf-8",
    )
    target = tmp_path / "spec.md"
    target.write_text(
        "widget_ratio >= 0.5 was the v1 draft's figure; it is now reported "
        "alongside the bank rather than thresholded.\n",
        encoding="utf-8",
    )

    declarations = find_declarations(source_docs=(source,))
    contradictions = find_contradictions(declarations, target_docs=(target,))
    assert contradictions == []


def test_zero_declarations_found_is_a_hard_failure(tmp_path: Path) -> None:
    """If the declaration sentence shape ever stops matching, the scan would
    silently check nothing and report zero contradictions — a vacuous pass.
    `_main` must refuse to call that a success."""
    empty_source = tmp_path / "steps.md"
    empty_source.write_text("Nothing here supersedes anything.\n", encoding="utf-8")
    empty_target = tmp_path / "spec.md"
    empty_target.write_text("Nothing here restates anything.\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "integral.spec_consistency",
            "--check",
            "--source-doc",
            str(empty_source),
            "--target-doc",
            str(empty_target),
        ],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")},
        check=False,
    )
    assert result.returncode == 3, result.stderr


def test_write_evidence_records_the_metric_the_payload_declares(tmp_path: Path) -> None:
    """The payload's gate reads `status/evidence/D3.json` key
    `spec_gate_contradictions` — evidence must actually carry that key, at
    the top level, as an int."""
    evidence = tmp_path / "D3.json"
    measured = write_evidence(evidence=evidence)

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded == measured
    assert isinstance(recorded["spec_gate_contradictions"], int)


def test_declaration_and_contradiction_are_frozen_strict_models() -> None:
    """House style: unknown keys are an error and instances are immutable —
    a typo'd field would otherwise be silently dropped or silently accepted."""
    declaration = Declaration(expr="x >= 1", document="d.md", line=1, text="t")
    contradiction = Contradiction(
        expr="x >= 1",
        superseded_in="d.md",
        superseded_at_line=1,
        document="e.md",
        line=2,
        text="t",
    )
    with pytest.raises(ValidationError):
        declaration.expr = "y >= 2"
    with pytest.raises(ValidationError):
        Declaration(expr="x >= 1", document="d.md", line=1, text="t", extra="nope")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        contradiction.line = 3


def test_every_document_states_the_same_differentiator() -> None:
    """D-3's three documents — the step spec and the two it reconciles — must
    each state the product's differentiator, both halves of it. A reader who
    starts in `docs/METHODS.md` rather than `status/specification.md` must not
    come away with a different argument about what this tool is."""
    measured = measure_differentiator()
    assert len(measured["documents"]) == 3, measured["documents"]
    assert measured["spec_consistency_violations"] == 0, measured["missing"]


def test_the_amendment_adds_a_sentence_without_removing_the_mechanism() -> None:
    """§1 *gains* the search sentence; it loses nothing. The mechanism claim —
    the dimensions surviving the trip from questionnaire to ranked list, carried
    by one shared vocabulary — must still be there word for word."""
    spec = " ".join(
        (_REPO_ROOT / "status" / "specification.md").read_text(encoding="utf-8").split()
    )
    assert (
        "so the candidate's non-skill dimensions never survive the trip from "
        "questionnaire to ranked list" in spec
    )
    assert "a **single dimension model is the shared vocabulary** across every stage" in spec
    assert "the dimensions are what make an iterative search steerable at all" in spec


def test_a_document_missing_the_differentiator_is_a_violation(tmp_path: Path) -> None:
    """Zero violations must mean the claims were found, not that nothing was
    looked for — the same vacuity trap `MINIMUM_DECLARATIONS_FOUND` guards."""
    silent = tmp_path / "silent.md"
    silent.write_text("Says nothing about what the product is.\n", encoding="utf-8")

    measured = measure_differentiator(docs=(silent,))

    assert measured["spec_consistency_violations"] == len(DIFFERENTIATOR_CLAIMS)


def test_write_differentiator_evidence_records_the_key_the_gate_reads(tmp_path: Path) -> None:
    """T61's gate reads `status/evidence/T61.json` key `spec_consistency_violations`."""
    evidence = tmp_path / "T61.json"
    measured = write_differentiator_evidence(evidence=evidence)

    recorded = json.loads(evidence.read_text(encoding="utf-8"))
    assert recorded == measured
    assert isinstance(recorded["spec_consistency_violations"], int)
