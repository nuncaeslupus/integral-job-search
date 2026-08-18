"""T34 — the step graph at runtime.

The gate is `unrunnable_step_dispatches == 0`: a dispatcher takes the offered
set at its word, so a step whose non-optional input is missing must never
appear in it. Around that sit the two properties §3.1 says the graph exists for
— what is still owed, and how good what we have is.

The test that matters most is `test_declining_every_offered_step_still_reaches_
a_ranking`. T30 proves the closure over the *declarations*; this proves it over
a real tree, and it is the runtime half of §2.5's promise that any offered step
may be declined without blocking.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.identity import ProfileStore, create_profile
from jobsearch.process_spec import StepList, load_steps
from jobsearch.step_runtime import (
    DETECTORS,
    REQUIRED_TRACE,
    ProfileView,
    _produce,
    blocked,
    look,
    missing_inputs,
    offered,
    owed,
    present_artefacts,
    probe_runtime,
    runnable,
    sufficiency,
    unknown_artefacts,
    write_evidence,
)


@pytest.fixture
def steps() -> StepList:
    return load_steps()


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    return ProfileStore(root, identity.handle)


def _advance(store: ProfileStore, *artefacts: str) -> ProfileView:
    for artefact in artefacts:
        _produce(store, artefact)
    return ProfileView(store)


# --- nothing unrunnable is offered ----------------------------------------


def test_step_without_its_required_inputs_is_never_offered(
    store: ProfileStore, steps: StepList
) -> None:
    view = ProfileView(store)
    present = present_artefacts(view, steps)
    assert "constraints" not in present

    for step in offered(view, steps):
        assert missing_inputs(step, present) == (), f"{step.id} was offered without its inputs"
    assert "sourcing" not in {step.id for step in offered(view, steps)}
    assert "sourcing" in {entry.step for entry in blocked(view, steps)}


def test_a_blocked_step_says_what_it_is_waiting_for(
    store: ProfileStore, steps: StepList
) -> None:
    entry = next(item for item in blocked(ProfileView(store), steps) if item.step == "sourcing")
    assert entry.missing == ("constraints",)
    assert "constraints" in entry.reason()


def test_an_optional_input_does_not_block_a_step(store: ProfileStore, steps: StepList) -> None:
    """§3.1 — an absent optional input makes a step longer, never impossible."""
    view = ProfileView(store)
    present = present_artefacts(view, steps)
    assert "claimed_facts" not in present
    assert "constraints" in {step.id for step in runnable(view, steps)}
    assert "history" in {step.id for step in runnable(view, steps)}


def test_a_finished_step_is_not_offered_again(store: ProfileStore, steps: StepList) -> None:
    """Re-entering a finished step is what the freshness triggers are for."""
    view = _advance(store, "constraints")
    assert "constraints" not in {step.id for step in offered(view, steps)}
    assert "constraints" in {step.id for step in runnable(view, steps)}


# --- the required-only trace ----------------------------------------------


def test_declining_every_offered_step_still_reaches_a_ranking(
    store: ProfileStore, steps: StepList
) -> None:
    """0 → 2 → 7 → 8 → 9, with all eight offered steps declined.

    Nothing optional is ever produced, so if any required step stalls, §2.5's
    promise is false in code however true it is in prose.
    """
    by_id = {step.id: step for step in steps.steps}
    for expected in REQUIRED_TRACE:
        view = ProfileView(store)
        present = present_artefacts(view, steps)
        assert missing_inputs(by_id[expected], present) == (), (
            f"{expected} is blocked with every offered step declined"
        )
        for artefact in by_id[expected].produces:
            _produce(store, artefact)

    assert "rankings" in present_artefacts(ProfileView(store), steps)
    assert not ProfileView(store).has_file("cv", "master.json"), "no offered step ran"


# --- what is owed ----------------------------------------------------------


def test_what_is_owed_names_the_step_that_would_produce_it(
    store: ProfileStore, steps: StepList
) -> None:
    """This is what makes "where were we?" answerable with a step, not a feeling."""
    debts = {entry.artefact: entry.step for entry in owed(ProfileView(store), steps)}
    assert debts["constraints"] == "constraints"
    assert debts["offers"] == "sourcing"
    assert debts["rankings"] == "ranking"
    assert "handle" not in debts, "the handle exists, so it is not owed"


def test_owed_shrinks_as_steps_run(store: ProfileStore, steps: StepList) -> None:
    before = len(owed(ProfileView(store), steps))
    view = _advance(store, "constraints")
    assert len(owed(view, steps)) < before


# --- sufficiency -----------------------------------------------------------


def test_ranking_without_weights_is_l1(store: ProfileStore, steps: StepList) -> None:
    """The level is computed from what exists, not asserted by the caller."""
    view = _advance(store, "constraints", "offers", "extractions", "rankings")
    assert sufficiency(view, steps) == "L1"


def test_l2_needs_both_traits_and_weights(store: ProfileStore, steps: StepList) -> None:
    """One of the two is not the other half.

    A ranking recording L2 on traits alone would be labelled as explaining
    itself in salary-equivalent terms with no salary equivalence to use.
    """
    assert sufficiency(_advance(store, "constraints"), steps) == "L1"
    assert sufficiency(_advance(store, "traits"), steps) == "L1"
    assert sufficiency(_advance(store, "weights"), steps) == "L2"


def test_a_handle_alone_is_l0(store: ProfileStore, steps: StepList) -> None:
    assert sufficiency(ProfileView(store), steps) == "L0"


def test_an_empty_weights_file_is_not_fitted_weights(
    store: ProfileStore, steps: StepList
) -> None:
    """T6 writes it shaped-but-empty at every rebuild, so this matters.

    Treating the placeholder as weights would make every ranking read L2 from
    the first rebuild onward.
    """
    _produce(store, "constraints")
    _produce(store, "traits")
    store.write_json({"part_worths": {}, "reaction_evidence": []}, "profile", "weights.json")
    assert sufficiency(ProfileView(store), steps) == "L1"


def test_unresolved_constraints_are_not_resolved_constraints(
    store: ProfileStore, steps: StepList
) -> None:
    store.write_json({"fields": {}}, "profile", "constraints.json")
    assert sufficiency(ProfileView(store), steps) == "L0"
    store.write_json(
        {"fields": {"salary_floor": {"state": "pending"}}}, "profile", "constraints.json"
    )
    assert sufficiency(ProfileView(store), steps) == "L0"
    store.write_json(
        {"fields": {"salary_floor": {"state": "declined"}}}, "profile", "constraints.json"
    )
    assert sufficiency(ProfileView(store), steps) == "L1"


def test_a_malformed_derived_file_reads_as_absent(
    store: ProfileStore, steps: StepList
) -> None:
    """Reading it as present would offer a step that then cannot run."""
    store.write_text("{not json", "profile", "constraints.json")
    assert sufficiency(ProfileView(store), steps) == "L0"


# --- the table itself ------------------------------------------------------


def test_every_artefact_in_the_graph_has_a_detector(steps: StepList) -> None:
    """Otherwise a newly declared input is absent forever, and its step vanishes."""
    assert unknown_artefacts(steps) == []


def test_no_detector_names_an_artefact_the_graph_does_not(steps: StepList) -> None:
    declared = {artefact for step in steps.steps for artefact in step.produces}
    declared |= {read.artefact for step in steps.steps for read in step.reads}
    assert set(DETECTORS) <= declared | set(steps.external_artefacts)


def test_the_situation_answers_all_three_questions(
    store: ProfileStore, steps: StepList
) -> None:
    situation = look(ProfileView(store), steps)
    assert situation.sufficiency == "L0"
    assert situation.offered
    assert situation.owed
    assert set(situation.offered) <= set(situation.runnable)


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T34.json"
    measured = write_evidence(evidence)
    assert measured["unrunnable_step_dispatches"] == 0
    assert measured["probes_run"] >= 8
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_probe_walks_the_whole_required_trace(tmp_path: Path) -> None:
    """A trace that stops early measures nothing downstream of where it stopped."""
    probes, failures = probe_runtime(tmp_path / "profiles")
    assert failures == []
    assert probes == 1 + 2 * len(REQUIRED_TRACE) + 2
