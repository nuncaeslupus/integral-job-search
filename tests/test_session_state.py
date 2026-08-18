"""T35 — session state, and the five-rule resumption order.

The gate is `resumption_position_loss == 0`, and it is about one failure: a
candidate who stopped mid-question comes back and is asked from the top. Three
properties carry it:

* an interrupted step resumes **at the recorded position**, not at its start;
* state survives a session that **never reached a boundary** — the write rule is
  "when something new is known", so the check kills the object and re-reads the
  file, because an in-process assertion passes on state that never hit the disk;
* every resumption **names the step and the reason**. There is no code path that
  yields a step without one, which is the structural version of §5.3's "it never
  resumes into a step silently".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.identity import ProfileStore, create_profile
from jobsearch.session import (
    Position,
    Resumption,
    SessionError,
    SessionState,
    SessionStore,
    Trigger,
    decide_resumption,
    first_run_order,
    write_evidence,
)

ORDER = ("identify", "intake", "constraints", "history", "traits", "reactions", "preferences")


@pytest.fixture
def sessions(tmp_path: Path) -> tuple[SessionStore, SessionStore]:
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en")
    second = create_profile(root, "Grace Hopper", language="en")
    return (
        SessionStore(ProfileStore(root, first.handle)),
        SessionStore(ProfileStore(root, second.handle)),
    )


# --- the write rule --------------------------------------------------------


def test_state_survives_a_session_that_never_reaches_a_boundary(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """The files are the memory, and a memory written only at the end is not one.

    Read back through a *new* store rather than the one that wrote it: an
    in-process check passes on state that never reached the disk, which is
    precisely the failure this test exists to catch.
    """
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(outstanding=("last_job", "reason_for_leaving")).model_dump(),
    )
    live.note_progress(at="2026-08-17T10:02:00Z", step="history", covered="last_job")
    # …and here the session dies. Nothing was closed, nothing was flushed.

    reopened = SessionStore(live.store).read()
    assert reopened is not None
    assert reopened.current_step == "history"
    assert reopened.position.covered == ("last_job",)
    assert reopened.position.outstanding == ("reason_for_leaving",)
    assert reopened.last_activity == "2026-08-17T10:02:00Z"


def test_every_record_moves_last_activity(sessions: tuple[SessionStore, SessionStore]) -> None:
    """§5.1 — rewritten whenever state moves, which is why `at` is mandatory."""
    live, _ = sessions
    live.record(at="2026-08-17T10:00:00Z", current_step="constraints")
    assert live.record(at="2026-08-17T10:05:00Z", sufficiency="L1").last_activity == (
        "2026-08-17T10:05:00Z"
    )


def test_the_write_is_atomic_and_leaves_no_debris(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    live, _ = sessions
    live.record(at="2026-08-17T10:00:00Z", current_step="history")
    session_dir = live.store.path("session")
    assert [path.name for path in session_dir.iterdir()] == ["state.json"]


def test_one_candidates_state_is_not_another_s(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    first, second = sessions
    first.record(at="2026-08-17T10:00:00Z", current_step="history")
    assert second.read() is None
    with pytest.raises(SessionError, match="cannot write"):
        second.write(SessionState(handle=first.handle, current_step="history"))


def test_state_naming_somebody_else_refuses_to_resume(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """A copied tree must not quietly resume the wrong person."""
    first, second = sessions
    first.record(at="2026-08-17T10:00:00Z", current_step="history")
    second.store.write_text(
        first.path.read_text(encoding="utf-8"), "session", "state.json"
    )
    with pytest.raises(SessionError, match="refusing to resume"):
        second.read()


def test_a_question_cannot_be_covered_and_outstanding_at_once() -> None:
    with pytest.raises(ValueError, match="covered and outstanding"):
        SessionState(
            handle="ada-lovelace",
            current_step="history",
            position=Position(covered=("last_job",), outstanding=("last_job",)),
        )


def test_a_position_without_a_step_says_nothing() -> None:
    with pytest.raises(ValueError, match="does not say where"):
        SessionState(handle="ada-lovelace", position=Position(outstanding=("last_job",)))


# --- the five rules --------------------------------------------------------


def test_interrupted_step_resumes_at_recorded_position(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(covered=("last_job",), outstanding=("earlier_roles",)).model_dump(),
    )
    resumption = decide_resumption(live.read(), order=ORDER)
    assert resumption.step == "history"
    assert resumption.rule == "position"
    assert resumption.position.outstanding == ("earlier_roles",)
    assert "earlier_roles" in resumption.reason


def test_resumption_names_the_step_and_the_reason(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """§5.3's second constraint, checked over every branch rather than one.

    Being dropped back into a half-finished interview with no explanation is
    indistinguishable from being asked the same questions twice.
    """
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(covered=("last_job",), outstanding=("earlier_roles",)).model_dump(),
    )
    state = live.read()
    every_branch = [
        decide_resumption(state, explicit="traits", order=ORDER),
        decide_resumption(state, cue_step="history", order=ORDER),
        decide_resumption(state, order=ORDER),
        decide_resumption(
            None, triggers=[Trigger("constraints", "your salary floor is unknown")], order=ORDER
        ),
        decide_resumption(None, order=ORDER),
    ]
    assert {resumption.rule for resumption in every_branch} == {
        "explicit",
        "cue",
        "position",
        "trigger",
        "sequence",
    }
    for resumption in every_branch:
        assert resumption.step
        assert resumption.reason.strip()
        assert resumption.step in resumption.announcement()


def test_an_explicit_request_outranks_everything(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(outstanding=("earlier_roles",)).model_dump(),
    )
    resumption = decide_resumption(
        live.read(),
        explicit="traits",
        cue_step="constraints",
        triggers=[Trigger("reactions", "stale", value=99.0)],
        order=ORDER,
    )
    assert (resumption.step, resumption.rule) == ("traits", "explicit")


def test_carrying_on_resumes_the_current_step_at_its_position(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """"let's carry on" resumes `current_step` at `position` (§5.3 rule 2)."""
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(covered=("last_job",), outstanding=("earlier_roles",)).model_dump(),
    )
    resumption = decide_resumption(live.read(), cue_step="history", order=ORDER)
    assert resumption.rule == "cue"
    assert resumption.position.outstanding == ("earlier_roles",)


def test_a_life_event_enters_its_own_step_from_the_top(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """A cue naming a different step is a fresh entry, not a continuation.

    Carrying the old step's position into it would resume a step at a position
    belonging to another one — which is how a candidate gets asked about their
    last job in the middle of the constraints conversation.
    """
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(outstanding=("earlier_roles",)).model_dump(),
    )
    resumption = decide_resumption(
        live.read(), cue_step="constraints", cue_reason="you said you left your job", order=ORDER
    )
    assert (resumption.step, resumption.rule) == ("constraints", "cue")
    assert resumption.position == Position()
    assert resumption.reason == "you said you left your job"


def test_a_freshness_trigger_is_only_reached_once_nothing_is_half_finished(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="history",
        position=Position(covered=("last_job", "earlier_roles")).model_dump(),
    )
    resumption = decide_resumption(
        live.read(),
        triggers=[
            Trigger("reactions", "it has been a while", value=1.0),
            Trigger("constraints", "your salary floor is still unknown", value=5.0),
        ],
        order=ORDER,
    )
    assert (resumption.step, resumption.rule) == ("constraints", "trigger")
    assert "salary floor" in resumption.reason


def test_the_highest_value_trigger_wins_and_ties_are_reproducible() -> None:
    triggers = [
        Trigger("preferences", "later in the order", value=3.0),
        Trigger("constraints", "earlier in the order", value=3.0),
    ]
    first = decide_resumption(None, triggers=triggers, order=ORDER)
    second = decide_resumption(None, triggers=list(reversed(triggers)), order=ORDER)
    assert first.step == second.step == "constraints"


def test_a_first_ever_session_starts_at_the_beginning() -> None:
    resumption = decide_resumption(None, order=ORDER)
    assert (resumption.step, resumption.rule) == ("identify", "sequence")


def test_a_finished_step_advances_to_the_next(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step="constraints",
        position=Position(covered=("salary_floor",)).model_dump(),
    )
    assert decide_resumption(live.read(), order=ORDER).step == "history"


def test_a_skipped_step_is_offered_again_rather_than_cancelled(
    sessions: tuple[SessionStore, SessionStore],
) -> None:
    """§5.1 — pending steps are skipped, not cancelled.

    Without this, "I'll come back to that" means "never", and the first run is
    declared complete over a step the candidate meant to return to.
    """
    live, _ = sessions
    live.record(
        at="2026-08-17T10:00:00Z",
        current_step=ORDER[-1],
        position=Position(covered=("done",)).model_dump(),
        pending_steps=("traits",),
    )
    assert decide_resumption(live.read(), order=ORDER).step == "traits"


def test_the_step_order_is_loaded_not_restated() -> None:
    """A second copy of the step list drifts from `spec-v2-steps.json`."""
    order = first_run_order()
    assert order[0] == "identify"
    assert "ranking" in order
    assert len(order) == len(set(order))


def test_a_resumption_always_announces_itself() -> None:
    resumption = Resumption(step="history", rule="sequence", reason="this is what comes next")
    assert resumption.announcement() == "Resuming history — this is what comes next."


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T35.json"
    measured = write_evidence(evidence)
    assert measured["resumption_position_loss"] == 0
    assert measured["probes_run"] >= 6
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured
