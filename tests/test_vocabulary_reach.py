"""D-19 — a step whose vocabulary settled nothing must not report understanding.

The failure these guard was found with a real candidate: a Barcelona construction
worker, seven adverts, and `0 of 25` dimensions settled on every one of them.
Step 8 wrote a file per offer and reported coverage met, because the artefact was
present and nobody asked whether anything in it had been read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.identity import ProfileStore
from integral.step_gates import UNCERTIFIABLE, VOCABULARY_SILENT, checkpoint_exit
from integral.step_runtime import ProfileView, settled_extractions
from integral.vocabulary_reach import measure, write_evidence


def _store(root: Path) -> ProfileStore:
    store = ProfileStore(root, "probe")
    store.write_json({"handle": "probe"}, "identity.json")
    return store


def _extraction(offer_id: str, *, settled: bool) -> dict[str, object]:
    return {
        "offer_id": offer_id,
        "language": "es",
        "scores": [{"dimension": "on_call_load", "value": 0.6}] if settled else [],
        "unsettled": [] if settled else ["on_call_load", "stack_modernity"],
    }


def test_an_extraction_that_settled_nothing_is_present_but_does_not_reach(tmp_path: Path) -> None:
    """The seam D-19 found: the file exists, and nothing in it was read."""
    store = _store(tmp_path)
    store.write_json(_extraction("silent", settled=False), "extractions", "silent.json")

    settled, read = settled_extractions(ProfileView(store))

    assert (settled, read) == (0, 1)


def test_a_settling_extraction_is_counted(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.write_json(_extraction("silent", settled=False), "extractions", "silent.json")
    store.write_json(_extraction("reaching", settled=True), "extractions", "reaching.json")

    assert settled_extractions(ProfileView(store)) == (1, 2)


def test_no_extractions_at_all_is_not_a_silent_vocabulary(tmp_path: Path) -> None:
    """A step that has not run has not failed to reach anything."""
    assert settled_extractions(ProfileView(_store(tmp_path))) == (0, 0)


def test_a_malformed_extraction_is_read_but_never_counted_as_settled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.path("extractions").mkdir(parents=True, exist_ok=True)
    (store.path("extractions") / "broken.json").write_text("{not json", encoding="utf-8")
    store.write_json(_extraction("silent", settled=False), "extractions", "silent.json")

    settled, read = settled_extractions(ProfileView(store))

    assert settled == 0
    assert read == 1, "a file that cannot be parsed is not an extraction that was read"


@pytest.mark.parametrize("certifiable", [True, False])
def test_a_silent_vocabulary_is_refused_whatever_the_gate_says(certifiable: bool) -> None:
    """The refusal must not ride on D-21.

    Step 8's gate is `not_implemented` today, so D-21 already keeps that
    checkpoint off 0 — for an unrelated reason. The day T56 builds the gate,
    this is the only thing left refusing.
    """
    result = {
        "runnable": True,
        "coverage_met": True,
        "certifiable": certifiable,
        "vocabulary_settled": False,
    }

    assert checkpoint_exit(result) == VOCABULARY_SILENT


def test_a_reaching_vocabulary_with_a_built_gate_still_passes() -> None:
    result = {
        "runnable": True,
        "coverage_met": True,
        "certifiable": True,
        "vocabulary_settled": True,
    }

    assert checkpoint_exit(result) == 0


def test_an_unanswerable_vocabulary_question_falls_through_to_d21() -> None:
    """`None` is "nothing to judge yet" and must not be read as a refusal."""
    result = {
        "runnable": True,
        "coverage_met": True,
        "certifiable": False,
        "vocabulary_settled": None,
    }

    assert checkpoint_exit(result) == UNCERTIFIABLE


def test_a_step_that_never_computed_the_key_is_unaffected() -> None:
    """Twelve of the thirteen steps produce no extractions and never set it."""
    result = {"runnable": True, "coverage_met": True, "certifiable": True}

    assert checkpoint_exit(result) == 0


def test_the_gate_holds() -> None:
    """D-19's acceptance gate: no market is reported as extracted without reach."""
    measured = measure()

    assert measured["markets_with_no_applicable_dimension_reported_as_extracted"] == 0, measured[
        "shortfalls"
    ]
    assert measured["claims_checked"] >= 6


def test_write_evidence_records_what_measure_found(tmp_path: Path) -> None:
    target = tmp_path / "D-19.json"

    measured = write_evidence(target)

    assert json.loads(target.read_text(encoding="utf-8")) == measured


def test_the_static_check_is_not_satisfied_by_merely_naming_the_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkpoint that mentions the key without computing it must not pass.

    The first version of this claim walked the whole module for any string
    constant equal to the key, so a docstring naming it would satisfy a
    checkpoint that returned nothing — a claim that cannot fail, which is the
    defect this module exists to refuse, in this module.
    """
    from integral import vocabulary_reach

    script = tmp_path / "run_checkpoint.py"
    script.write_text('NOTE = "vocabulary_settled"\ndef checkpoint():\n    return {}\n', "utf-8")
    monkeypatch.setattr(vocabulary_reach, "CHECKPOINT_SCRIPT", script)

    reason = vocabulary_reach._claim_the_checkpoint_computes_the_key()

    assert reason and "builds no" in reason


def test_the_static_check_holds_for_the_committed_checkpoint() -> None:
    from integral import vocabulary_reach

    assert vocabulary_reach._claim_the_checkpoint_computes_the_key() is None
