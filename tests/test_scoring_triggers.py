"""T39 — the three scoring triggers, and never per message.

§4.2 separates cheap always-on capture from expensive scoring, and names
exactly three occasions for the second: a step boundary, an explicit request,
and a batch threshold of N new trait-bearing rows.

What makes deferral safe is the sentence that closes §4.2 — the profile is a
pure function of the log, so *deferring scoring costs freshness and nothing
else*. `test_deferred_scoring_loses_no_evidence` is that sentence, checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.identity import ProfileStore, create_profile
from jobsearch.profile import EvidenceLog
from jobsearch.scoring import (
    BATCH_THRESHOLD,
    TRIGGERS,
    Decision,
    ScoringError,
    decide,
    is_trait_bearing,
    pending_rows,
    probe_scoring,
    read_last_scoring,
    score,
    score_if_due,
    write_evidence,
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    return ProfileStore(root, identity.handle)


def _say(
    store: ProfileStore, index: int, *, dimensions: tuple[str, ...] = ("team_autonomy",)
) -> None:
    EvidenceLog(store).append(
        recorded_at=f"2026-08-17T10:{index:02d}:00Z",
        step="history",
        kind="statement",
        dimensions=list(dimensions),
        text=f"Something said in turn {index}.",
        source="conversation",
    )


# --- never per message -----------------------------------------------------


def test_scoring_does_not_run_per_message(store: ProfileStore) -> None:
    for index in range(1, 5):
        _say(store, index)
        decision = score_if_due(store, "message", at="2026-08-17T10:30:00Z", threshold=5)
        assert not decision.run, f"scoring ran on message {index}"
    assert read_last_scoring(store) is None


def test_the_batch_threshold_is_what_authorises_a_run_on_a_message(
    store: ProfileStore,
) -> None:
    """A message is an occasion, never a trigger.

    There is no fourth trigger called "a message arrived": the run is
    attributed to the threshold, because that is what permitted it.
    """
    for index in range(1, 6):
        _say(store, index)
    decision = score_if_due(store, "message", at="2026-08-17T10:30:00Z", threshold=5)
    assert decision.run
    assert decision.trigger == "batch_threshold"
    last = read_last_scoring(store)
    assert last is not None and last.trigger == "batch_threshold"


def test_the_threshold_is_the_one_the_traits_spec_settled() -> None:
    assert BATCH_THRESHOLD == 20


def test_a_step_boundary_and_an_explicit_request_score_outright(
    store: ProfileStore,
) -> None:
    _say(store, 1)
    assert decide(store, "step_boundary").trigger == "step_boundary"
    assert decide(store, "explicit_request").trigger == "explicit_request"


def test_only_trait_bearing_rows_count_towards_the_threshold(
    store: ProfileStore,
) -> None:
    """Twenty remarks about the weather must not trigger a rescore.

    A row with no dimension cannot move a trait score, so counting it would
    make the threshold fire on volume rather than on content.
    """
    log = EvidenceLog(store)
    for index in range(1, 6):
        log.append(
            recorded_at=f"2026-08-17T10:{index:02d}:00Z",
            step="history",
            kind="statement",
            text="Nice weather.",
            source="conversation",
        )
    assert pending_rows(store) == []
    assert not decide(store, "message", threshold=5).run

    _say(store, 6)
    assert len(pending_rows(store)) == 1


def test_a_retraction_row_is_not_trait_bearing(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    _say(store, 1)
    row = log.rows()[0]
    retraction = log.append(
        recorded_at="2026-08-17T10:05:00Z",
        step="history",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=row.id,
    )
    assert not is_trait_bearing(retraction)


# --- deferral is free ------------------------------------------------------


def test_deferred_scoring_loses_no_evidence(store: ProfileStore) -> None:
    """The log is never behind, whatever scoring did or did not do."""
    log = EvidenceLog(store)
    for index in range(1, 5):
        _say(store, index)
        score_if_due(store, "message", at="2026-08-17T10:30:00Z", threshold=99)
    assert read_last_scoring(store) is None, "nothing was scored"
    assert len(log.rows()) == 4, "but everything was captured"

    score_if_due(store, "explicit_request", at="2026-08-17T11:00:00Z")
    traits = store.read_text("profile", "traits.json")
    for row in log.effective_rows():
        assert row.id in traits, f"{row.id} arrived while scoring was deferred and was lost"


def test_the_pending_count_resets_after_a_run(store: ProfileStore) -> None:
    for index in range(1, 4):
        _say(store, index)
    assert len(pending_rows(store)) == 3
    score_if_due(store, "step_boundary", at="2026-08-17T11:00:00Z")
    assert pending_rows(store) == []
    _say(store, 4)
    assert len(pending_rows(store)) == 1


def test_the_decision_says_how_many_are_waiting(store: ProfileStore) -> None:
    """"Nothing is lost by waiting" is only reassuring with a number on it."""
    _say(store, 1)
    decision = decide(store, "message", threshold=5)
    assert decision.pending == 1
    assert "nothing is lost by waiting" in decision.reason


# --- the expensive path is closed -----------------------------------------


def test_scoring_cannot_be_reached_without_naming_a_trigger(store: ProfileStore) -> None:
    """This refusal is the mechanism, not an audit after the fact."""
    with pytest.raises(ScoringError, match="without one of"):
        score(store, Decision(False, None, "just because", 0), at="2026-08-17T11:00:00Z")
    with pytest.raises(ScoringError):
        score(store, Decision(True, None, "sneaking through", 0), at="2026-08-17T11:00:00Z")
    assert read_last_scoring(store) is None


def test_the_trigger_set_is_closed_at_three() -> None:
    assert {"step_boundary", "explicit_request", "batch_threshold"} == TRIGGERS


def test_a_malformed_marker_is_reported_rather_than_ignored(store: ProfileStore) -> None:
    store.write_text("not json", "session", "scoring.json")
    with pytest.raises(ScoringError, match="malformed"):
        read_last_scoring(store)


def test_one_candidates_scoring_marker_is_not_another_s(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en")
    second = create_profile(root, "Grace Hopper", language="en")
    first_store, second_store = ProfileStore(root, first.handle), ProfileStore(root, second.handle)
    _say(first_store, 1)
    score_if_due(first_store, "step_boundary", at="2026-08-17T11:00:00Z")
    assert read_last_scoring(second_store) is None


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T39.json"
    measured = write_evidence(evidence)
    assert measured["unscheduled_scoring_runs"] == 0
    assert measured["turns_evaluated"] >= 6
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_every_run_the_probe_saw_named_one_of_the_three(tmp_path: Path) -> None:
    result = probe_scoring(tmp_path / "profiles")
    assert result["failures"] == []
    assert result["scoring_runs"], "the probe must actually score at some point"
    assert set(result["scoring_runs"]) <= TRIGGERS
