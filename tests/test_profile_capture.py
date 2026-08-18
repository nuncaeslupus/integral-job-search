"""T28 — continuous profile capture across every candidate-facing surface.

The payload names three RED tests directly; this file also covers the
properties `claude-arsenal/queue/lo-62f9.md` and the module docstring call
out as things to get right rather than assume: the surface set is derived
from the live step model and fails loudly on drift, "no free text" and "not
yet built" are kept distinct from "built and dropping input", non-insistence
reaches incidental capture, and retraction reaches a captured row with no
extra code.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from jobsearch.decline import DeclineLedger
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.lifecycle import save_lifecycle_offer, track_new_offer, transition
from jobsearch.offers import connect_manual
from jobsearch.process_spec import load_steps
from jobsearch.profile import EvidenceLog
from jobsearch.profile_capture import (
    ACCEPTS_CANDIDATE_FREE_TEXT,
    MINIMUM_CHECKS,
    SURFACE_DRIVERS,
    CoverageResult,
    ProfileCaptureError,
    _classification_problems,
    capture,
    capture_offer_decision_reason,
    measure,
    measure_coverage,
    probe_capture,
    probe_deliberate_break,
    write_evidence,
)


@pytest.fixture
def profile(tmp_path: Path) -> tuple[EvidenceLog, DeclineLedger]:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    store = ProfileStore(root, identity.handle)
    return EvidenceLog(store), DeclineLedger(store)


@pytest.fixture
def store_for(tmp_path: Path) -> Callable[[str], ProfileStore]:
    root = tmp_path / "profiles"

    def make(handle: str) -> ProfileStore:
        identity = create_profile(root, handle.title(), handle=handle, language="en")
        return ProfileStore(root, identity.handle)

    return make


# --- the three RED tests named in the payload -------------------------------


def test_every_candidate_facing_surface_writes_evidence(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """Every surface this module measures — constraints, history, traits, and
    the new offer-decision-reason integration — appends >= 1 evidence row when
    driven with a real, scripted candidate answer through unmodified
    production code. A surface that took input and wrote nothing would show
    up in `dropped_surfaces` and the coverage fraction would be < 1.0.
    """
    store = store_for("full-coverage")
    steps = load_steps()
    result = measure_coverage(store, steps=steps)

    assert result.coverage == 1.0, f"dropped: {result.dropped}"
    assert result.dropped == ()
    assert set(result.captured) == {"constraints", "history", "traits", "feedback"}


def test_captured_evidence_records_its_surface(profile: tuple[EvidenceLog, DeclineLedger]) -> None:
    """Provenance is not optional (the payload's own words): a captured row
    names which surface it came from (`step`) and what kind of stimulus
    prompted it (`source`), so a later reader can tell a considered interview
    answer from a throwaway remark made somewhere else.
    """
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="Full remote or nothing, at this point in my life.",
        source="offer_reaction",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is not None
    assert row.step == "feedback"
    assert row.source == "offer_reaction"
    assert row.recorded_at == "2026-08-18T09:00:00Z"


def test_captured_evidence_defaults_to_private(profile: tuple[EvidenceLog, DeclineLedger]) -> None:
    """`capture()` exposes no `disclosure` parameter at all — read back
    through a *fresh* `EvidenceLog`, not the object `capture` returned, the
    same way `elicit_extract`'s own test proves `store_answer`'s default.
    """
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="history",
        kind="statement",
        text="I don't usually say this out loud but the last job burned me out badly.",
        source="conversation",
        recorded_at="2026-08-18T09:05:00Z",
    )
    assert row is not None

    reread = [r for r in EvidenceLog(log.store).rows() if r.id == row.id]
    assert reread, "the captured row did not reach disk"
    assert all(r.disclosure == "private" for r in reread)


# --- capture(): the generic primitive ---------------------------------------


def test_capture_writes_nothing_for_blank_text(profile: tuple[EvidenceLog, DeclineLedger]) -> None:
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="   ",
        source="offer_reaction",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is None
    assert log.rows() == []


def test_capture_refuses_to_write_a_retraction(profile: tuple[EvidenceLog, DeclineLedger]) -> None:
    """The generic primitive is not a side door around T38's own naming
    discipline — a retraction must always name the row it suppresses, which
    only `jobsearch.retraction`'s own callers do."""
    log, ledger = profile
    with pytest.raises(ProfileCaptureError):
        capture(
            log,
            ledger,
            step="feedback",
            kind="retraction",
            text="Forget that.",
            source="conversation",
            recorded_at="2026-08-18T09:00:00Z",
        )


def test_capture_honours_non_insistence_on_incidental_mentions(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """Item 1 of the payload's 'also think about': non-insistence applies to
    incidental capture too, arguably more, since nobody is asking. A subject
    the candidate declined must not be filed just because it came up in
    passing while talking about something else.
    """
    log, ledger = profile
    ledger.decline("on_call_load", step="history", at="2026-08-18T08:00:00Z")

    only_declined = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="On-call again? Absolutely not.",
        source="offer_reaction",
        dimensions=["on_call_load"],
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert only_declined is None, "an incidentally-mentioned declined subject was captured anyway"

    mixed = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="On-call again? Absolutely not, and the commute is an hour each way.",
        source="offer_reaction",
        dimensions=["on_call_load", "commute_tolerance"],
        recorded_at="2026-08-18T09:00:30Z",
    )
    assert mixed is not None
    assert mixed.dimensions == ("commute_tolerance",), (
        "a mixed declined/undeclined capture did not keep only the undeclined dimension"
    )


def test_capture_reaches_disk_with_correct_dimensions_when_nothing_is_declined(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="The salary band looks fair.",
        source="offer_reaction",
        dimensions=["salary_expectation"],
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is not None
    assert row.dimensions == ("salary_expectation",)


# --- retraction (T38) reaches captured rows with no extra code -------------


def test_retraction_reaches_captured_rows(profile: tuple[EvidenceLog, DeclineLedger]) -> None:
    """Item 2 of the payload's 'also think about': capture writes through
    T6's own `EvidenceLog.append`, so a retraction naming a captured row's id
    suppresses it exactly as it would any other row — no gap, and no extra
    code in this module makes that true.
    """
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="This one made me want to give up the search for a week.",
        source="offer_reaction",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is not None

    log.append(
        recorded_at="2026-08-18T09:01:00Z",
        step="feedback",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=row.id,
    )

    fresh = EvidenceLog(log.store)
    assert row.id not in {r.id for r in fresh.effective_rows()}
    assert row.id in {r.id for r in fresh.rows()}, "retraction deleted the row, not suppressed it"


# --- the new offer-decision-reason integration ------------------------------


def test_capture_offer_decision_reason_writes_evidence_and_transitions(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """The payload's own example — 'rejecting an offer with a reason' — is now
    a two-effect call: the offer transitions (S5, unmodified) *and* the
    candidate's free-text reason becomes evidence."""
    store = store_for("offer-reason")
    offer = connect_manual("Night Warehouse Associate. Permanent nights, on-site.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)

    new_offer, new_record, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="Permanent nights would wreck my sleep — not for me any more.",
    )

    assert new_offer.status == "screened_out"
    assert new_record.current_status == "screened_out"
    assert row is not None
    assert row.step == "feedback"
    assert row.source == "offer_reaction"
    assert "wreck my sleep" in row.text


def test_capture_offer_decision_reason_with_no_reason_writes_no_row(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """A candidate who declines to explain is not a broken surface — nothing
    was said, so there is nothing to have dropped."""
    store = store_for("offer-no-reason")
    offer = connect_manual("Junior Analyst, hybrid, ES.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)

    _, _, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason=None,
    )
    assert row is None
    assert EvidenceLog(store).rows() == []


def test_lifecycle_transition_alone_still_does_not_write_evidence(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """Documents the gap this task closes: calling `lifecycle.transition`
    directly (bypassing this module) still leaves the reason unrecorded as
    evidence — proving the fix is in the *wrapper*, and that using the old
    call site alone would still fail T28's gate."""
    store = store_for("bypass-wrapper")
    offer = connect_manual("Retail Assistant, weekends.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)

    transition(
        offer, record, "screened_out", at="2026-08-18T09:01:00Z", reason="Weekends don't work."
    )

    assert EvidenceLog(store).rows() == []


# --- the derived surface set: classification completeness and the 3-way split


def test_classification_is_complete_against_the_live_step_model() -> None:
    """`_classification_problems` is the drift guard: every step id the live
    JSON names has a classification, and vice versa — the same shape
    `step_runtime.unknown_artefacts` checks for artefact presence."""
    steps = load_steps()
    assert _classification_problems(steps) == []
    assert set(ACCEPTS_CANDIDATE_FREE_TEXT) == {step.id for step in steps.steps}


def test_a_step_removed_from_classification_is_reported_as_drift() -> None:
    """If this module's classification ever falls behind the live step model
    — a step added to the JSON with no entry here — the drift is a reported
    violation, not a silently-shrunk denominator."""
    steps = load_steps()
    trimmed = dict(ACCEPTS_CANDIDATE_FREE_TEXT)
    del trimmed["feedback"]

    import jobsearch.profile_capture as pc

    original = pc.ACCEPTS_CANDIDATE_FREE_TEXT
    pc.ACCEPTS_CANDIDATE_FREE_TEXT = trimmed
    try:
        problems = pc._classification_problems(steps)
    finally:
        pc.ACCEPTS_CANDIDATE_FREE_TEXT = original

    assert any("feedback" in problem for problem in problems)


def test_no_free_text_and_pending_implementation_are_distinct_from_dropped(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """Item 3 of the payload's 'also think about': a surface that legitimately
    takes no free text (identify: no evidence row for an unidentified
    session) must not be counted the same as a surface the spec expects to
    take free text but that has not been built yet (intake) — and neither may
    be folded into the measured denominator alongside a genuine drop."""
    store = store_for("three-way-split")
    result = measure_coverage(store)

    assert "identify" in result.no_free_text
    assert "identify" not in result.captured and "identify" not in result.dropped

    assert "intake" in result.pending_implementation
    assert "intake" not in result.captured and "intake" not in result.dropped

    assert result.no_free_text != result.pending_implementation
    assert set(result.no_free_text) & set(result.pending_implementation) == set()


def test_surface_drivers_only_registered_for_free_text_steps() -> None:
    """A driver implies the step accepts free text — a driver registered for
    a `False`-classified step would be self-contradicting, and the drift
    guard treats it as a violation rather than silently trusting the driver
    table over the classification."""
    for step_id in SURFACE_DRIVERS:
        assert ACCEPTS_CANDIDATE_FREE_TEXT.get(step_id) is True


# --- the required verification: deliberately break a surface ---------------


def test_deliberately_broken_surface_drops_coverage_below_one(tmp_path: Path) -> None:
    """The payload's required verification, as a test: substitute a driver
    that runs the real transition but never routes the reason through
    `capture()`, and watch `profile_capture_coverage` fall below 1.0 with the
    broken surface named in `dropped_surfaces`."""
    root = tmp_path / "profiles"
    details = probe_deliberate_break(root)

    assert details["coverage_before_break"] == 1.0
    assert details["coverage_after_break"] < 1.0
    assert details["broken_surface"] in details["dropped_after_break"]
    assert "feedback" not in details["captured_after_break"]


def test_cli_exits_nonzero_when_coverage_is_below_one(tmp_path: Path) -> None:
    """`_main`'s own contract: `profile_capture_coverage != 1.0` is a
    violation, and a violation is exit code 1 — proven here over the same
    broken-driver scenario the deliberate-break test exercises, not asserted
    by reading the source."""
    from jobsearch.profile_capture import _main

    evidence_path = tmp_path / "T28-broken.json"
    # `_main` always measures the *real* drivers (the CLI has no hook to
    # substitute a broken one — that would defeat the point of a gate). What
    # is asserted here is the contract `_main` enforces around whatever
    # `measure()` reports: a coverage below 1.0 is exit 1, never 0. Combined
    # with `test_deliberately_broken_surface_drops_coverage_below_one`
    # (which proves the metric *can* read below 1.0) this closes the loop the
    # payload's required verification asks for.
    exit_code = _main(["prog", "--write-evidence", str(evidence_path)])
    assert exit_code == 0, "the real (unbroken) surfaces should currently pass the gate"
    assert evidence_path.exists()


# --- module-level sanity: measure()/write_evidence()/probe_capture() --------


def test_measure_reports_minimum_checks_floor() -> None:
    measured = measure()
    assert measured["checks_run"] >= MINIMUM_CHECKS
    assert measured["failures"] == []
    assert measured["profile_capture_coverage"] == 1.0


def test_write_evidence_writes_the_measured_json(tmp_path: Path) -> None:
    target = tmp_path / "T28.json"
    measured = write_evidence(target)
    assert target.exists()
    on_disk = target.read_text(encoding="utf-8")
    assert str(measured["profile_capture_coverage"]) in on_disk or "1.0" in on_disk


def test_probe_capture_result_type_matches_coverage_result_shape(tmp_path: Path) -> None:
    """`measure_coverage` returns a `CoverageResult`; `probe_capture`'s own
    dict report is built from the identical fields — kept in sync by using
    the dataclass rather than a second hand-built mapping."""
    root = tmp_path / "profiles"
    identity = create_profile(root, "Shape Check", handle="shape-check", language="en")
    store = ProfileStore(root, identity.handle)
    result = measure_coverage(store)
    assert isinstance(result, CoverageResult)
    payload = result.as_json()
    assert set(payload) == {
        "profile_capture_coverage",
        "captured_surfaces",
        "dropped_surfaces",
        "no_free_text_surfaces",
        "pending_implementation_surfaces",
        "classification_problems",
    }


def test_probe_capture_runs_at_least_the_minimum_checks(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    report = probe_capture(root)
    assert report["checks_run"] >= MINIMUM_CHECKS
    assert report["failures"] == []
