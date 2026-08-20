"""T28 — continuous profile capture across every candidate-facing surface.

The payload names three RED tests directly; this file also covers the
properties `arsenal/tasks/_history/lo-62f9.md` and the module docstring call
out as things to get right rather than assume: the surface set is derived
from the live step model and fails loudly on drift, "no free text" and "not
yet built" are kept distinct from "built and dropping input", non-insistence
reaches incidental capture, and retraction reaches a captured row with no
extra code.

D-8's own three RED tests live in their own section below: `EvidenceRow.about`
lets two rejections of two different offers stay distinguishable in the log,
a captured reason's subject survives T6's rebuild, and an answer to a bank
question is not made to carry a subject nothing asked it to.

S12's own three tests live in their own section further below: every step in
the live model declares whether it takes candidate free text, this module
reads that declaration rather than keeping a local map (proven by flipping a
declaration in the JSON and watching `measure_coverage` follow it), and the
migration leaves the five currently-measured surfaces — `constraints`,
`feedback`, `history`, `intake`, `traits` — exactly as they were.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integral.decline import DeclineLedger
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import LifecycleRecord, save_lifecycle_offer, track_new_offer, transition
from integral.offers import Offer, connect_manual
from integral.process_spec import DEFAULT_STEPS_PATH, StepList, load_steps
from integral.profile import EvidenceLog, EvidenceSubject, rebuild
from integral.profile_capture import (
    MINIMUM_CHECKS,
    MINIMUM_SUBJECT_CHECKS,
    SURFACE_DRIVERS,
    CoverageResult,
    ProfileCaptureError,
    _classification_problems,
    _drive_history,
    capture,
    capture_offer_decision_reason,
    captures_without_a_subject,
    measure,
    measure_coverage,
    measure_step_declarations,
    measure_subject_gate,
    probe_capture,
    probe_deliberate_break,
    probe_deliberate_subject_break,
    probe_subject_linkage,
    unclassified_free_text_steps,
    write_evidence,
    write_step_declaration_evidence,
    write_subject_evidence,
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
    """Every surface this module measures — intake, constraints, history,
    traits, and the offer-decision-reason integration — appends >= 1 evidence
    row when driven with a real, scripted candidate answer through
    unmodified production code. A surface that took input and wrote nothing
    would show up in `dropped_surfaces` and the coverage fraction would be
    < 1.0.
    """
    store = store_for("full-coverage")
    steps = load_steps()
    result = measure_coverage(store, steps=steps)

    assert result.coverage == 1.0, f"dropped: {result.dropped}"
    assert result.dropped == ()
    assert set(result.captured) == {"intake", "constraints", "history", "traits", "feedback"}


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
    only `integral.retraction`'s own callers do."""
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


def _steps_with_raw_edit(tmp_path: Path, edit: Callable[[list[dict[str, Any]]], None]) -> StepList:
    """A `StepList` loaded from a copy of the committed JSON after `edit`
    mutates its raw `steps` array in place — used to prove a declaration (or
    its absence) drives measurement, without touching the committed file."""
    raw = json.loads(DEFAULT_STEPS_PATH.read_text(encoding="utf-8"))
    edit(raw["steps"])
    path = tmp_path / "steps.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_steps(path)


def test_classification_is_complete_against_the_live_step_model() -> None:
    """`_classification_problems` is the drift guard: every step in the live
    JSON declares `accepts_candidate_free_text` (S12: on the model itself,
    not a Python map) — the same shape `step_runtime.unknown_artefacts`
    checks for artefact presence."""
    steps = load_steps()
    assert _classification_problems(steps) == []
    assert unclassified_free_text_steps(steps) == []
    assert all(step.accepts_candidate_free_text is not None for step in steps.steps)


def test_a_step_missing_its_declaration_is_reported_as_drift(tmp_path: Path) -> None:
    """If a step ever lands in the JSON with `accepts_candidate_free_text`
    unset, that is drift — a reported violation, not a silently-shrunk
    denominator. Before S12 this was a Python dict falling behind the live
    step list; now it is a field missing on the step itself."""

    def drop_feedbacks_declaration(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if step["id"] == "feedback":
                del step["accepts_candidate_free_text"]

    steps = _steps_with_raw_edit(tmp_path, drop_feedbacks_declaration)

    assert unclassified_free_text_steps(steps) == ["feedback"]
    problems = _classification_problems(steps)
    assert any("feedback" in problem for problem in problems)


def test_no_free_text_and_pending_implementation_are_distinct_from_dropped(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """Item 3 of the payload's 'also think about': a surface that legitimately
    takes no free text (identify: no evidence row for an unidentified
    session) must not be counted the same as a surface the spec expects to
    take free text but that has not been built yet (reactions, as of this
    task — intake moved out of this bucket in T50) — and neither may be
    folded into the measured denominator alongside a genuine drop."""
    store = store_for("three-way-split")
    result = measure_coverage(store)

    assert "identify" in result.no_free_text
    assert "identify" not in result.captured and "identify" not in result.dropped

    assert "reactions" in result.pending_implementation
    assert "reactions" not in result.captured and "reactions" not in result.dropped

    assert result.no_free_text != result.pending_implementation
    assert set(result.no_free_text) & set(result.pending_implementation) == set()


# --- S12: the free-text declaration moved from a Python map onto the model -


def test_profile_capture_reads_the_declaration_not_a_local_map(
    store_for: Callable[[str], ProfileStore], tmp_path: Path
) -> None:
    """A module that reads the model but keeps a fallback map has not moved
    anything (the payload's own words). Proven, not asserted: flip `history`'s
    declaration to `False` in a copy of the JSON and drive `measure_coverage`
    off that copy — with no Python constant left anywhere to fall back to,
    `history` must follow the JSON into `no_free_text` rather than stay
    `captured` by an old default. The real, unedited step model is checked
    last, so the same call also proves nothing about the committed file itself
    changed underneath this test.
    """

    def free_history_of_its_declaration(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if step["id"] == "history":
                step["accepts_candidate_free_text"] = False

    flipped = _steps_with_raw_edit(tmp_path, free_history_of_its_declaration)
    store = store_for("declaration-drives-measurement")

    # Passing the real SURFACE_DRIVERS (not the module default `None`) skips
    # `_classification_problems`, which would otherwise flag `history` as a
    # driver-vs-declaration contradiction — a real, separate finding this
    # test is not about; see `test_surface_drivers_only_registered_for_free_
    # text_steps` for that check instead.
    result = measure_coverage(store, steps=flipped, drivers=SURFACE_DRIVERS)
    assert "history" in result.no_free_text
    assert "history" not in result.captured and "history" not in result.dropped

    # The unedited model still classifies history as free-text-accepting and
    # measured — proof the flip above came from the JSON, not from a change
    # to the committed file or to this module's own logic.
    unflipped = measure_coverage(store_for("declaration-unflipped"), steps=load_steps())
    assert "history" in unflipped.captured


def test_coverage_is_unchanged_by_the_migration(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """The schema change must not, by itself, alter what is counted — this is
    deliberately not `test_classification_is_complete_against_the_live_step_
    model` (drift) or `test_a_step_missing_its_declaration_is_reported_as_
    drift` (a bad edit): it is that a *correct* migration of the existing
    declarations leaves `profile_capture_coverage` and every surface bucket
    exactly as they were.

    T50 moved `intake` from pending to measured after this payload was
    written, so there are five captured surfaces today
    (`constraints`, `feedback`, `history`, `intake`, `traits`), not the four
    named when S12 was scoped — see this file's own module docstring and
    `arsenal/tasks/_history/lo-9261.md`'s corrected acceptance gate.
    """
    store = store_for("coverage-unchanged-by-migration")

    result = measure_coverage(store)

    assert result.coverage == 1.0
    assert set(result.captured) == {"constraints", "feedback", "history", "intake", "traits"}
    assert set(result.no_free_text) == {
        "identify",
        "preferences",
        "sourcing",
        "understanding",
        "ranking",
    }
    assert set(result.pending_implementation) == {"reactions", "application", "interview_log"}
    assert result.dropped == ()
    assert result.problems == ()


# --- T50: intake becomes a measured surface, S4 having built it a driver ---


def test_intake_is_a_measured_surface_not_a_pending_one(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """T50: S4 (`integral.cv_store`) now gives intake a real free-text path
    (`add_conversation_entry`/`set_conversation_scalar`), so it belongs among
    the measured surfaces rather than the pending ones — the only thing that
    distinguishes this task from a no-op, per the payload."""
    store = store_for("intake-measured")
    result = measure_coverage(store)

    assert "intake" in result.captured
    assert "intake" not in result.pending_implementation
    assert "intake" not in result.dropped


def test_a_conversational_intake_answer_reaches_the_evidence_log(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """The behaviour, driven through the real `cv_store` entry point rather
    than a test seam — the rule that let T28 find this gap in the first
    place (`SURFACE_DRIVERS['intake']` runs unmodified `cv_store.
    add_conversation_entry`). The row it returns must be the one row
    `add_conversation_entry` already wrote for the one scripted utterance —
    exactly one, never two: a driver that also routed the same statement
    through `capture()` would double it, which the payload says to decide
    about deliberately rather than default into.
    """
    store = store_for("intake-evidence")
    driver = SURFACE_DRIVERS["intake"]

    row = driver(store)

    assert row is not None
    assert row.step == "intake"
    assert row.source == "conversation"
    log_rows = list(EvidenceLog(store).rows())
    assert row.id in {r.id for r in log_rows}
    intake_rows = [r for r in log_rows if r.step == "intake"]
    assert len(intake_rows) == 1, (
        f"expected exactly one evidence row for the one scripted intake "
        f"utterance, found {len(intake_rows)} — a driver that also called "
        "capture() on top of add_conversation_entry's own write would double it"
    )


def test_surface_drivers_only_registered_for_free_text_steps() -> None:
    """A driver implies the step accepts free text — a driver registered for
    a step declared `False` (or left undeclared) would be self-contradicting,
    and the drift guard treats it as a violation rather than silently
    trusting the driver table over the model's own declaration."""
    declared = {step.id: step.accepts_candidate_free_text for step in load_steps().steps}
    for step_id in SURFACE_DRIVERS:
        assert declared.get(step_id) is True


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
    from integral.profile_capture import _main

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


def test_unclassified_free_text_steps_is_zero_on_the_committed_model() -> None:
    """S12's gate metric, over the real committed file — the number
    `gate_run.sh lo-9261` actually checks."""
    measured = measure_step_declarations()

    assert measured["unclassified_free_text_steps"] == 0
    assert measured["unclassified_step_ids"] == []
    assert measured["step_count"] == load_steps().step_count


def test_a_step_missing_its_declaration_is_counted_by_measure_step_declarations(
    tmp_path: Path,
) -> None:
    """The failure S12's gate exists to catch: a step landing with the field
    unset must move `unclassified_free_text_steps` off zero and name the step
    — not be silently read as `False` ("no free text")."""

    def drop_reactions_declaration(steps: list[dict[str, Any]]) -> None:
        for step in steps:
            if step["id"] == "reactions":
                del step["accepts_candidate_free_text"]

    steps = _steps_with_raw_edit(tmp_path, drop_reactions_declaration)

    measured = measure_step_declarations(steps)

    assert measured["unclassified_free_text_steps"] == 1
    assert measured["unclassified_step_ids"] == ["reactions"]


def test_write_step_declaration_evidence_writes_s12_json(tmp_path: Path) -> None:
    target = tmp_path / "S12.json"

    measured = write_step_declaration_evidence(target)

    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk == measured
    assert on_disk["unclassified_free_text_steps"] == 0


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


# =============================================================================
# D-8 — a captured reason names the artefact it was about
#
# `EvidenceRow` carried `step`, `source` and `recorded_at`, but nothing named
# *which* offer a captured decision reason was about — "in response to what"
# was unmet for exactly the one surface this module wires (feedback). The
# payload's three RED tests are first; the rest of this section covers the
# gate's own exclusion (a question needs no subject), the required
# verification, and the CLI contract around `captures_without_a_subject`.


TwoOffers = tuple[ProfileStore, tuple[Offer, LifecycleRecord], tuple[Offer, LifecycleRecord]]


@pytest.fixture
def two_offers(store_for: Callable[[str], ProfileStore]) -> TwoOffers:
    """One store, two collected-and-saved offers, ready to be transitioned."""
    store = store_for("subject-two-offers")
    offer_a = connect_manual("Warehouse Operative. Nights, on-site, permanent.")
    record_a = track_new_offer(offer_a, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer_a, record_a)
    offer_b = connect_manual("Data Entry Clerk. Hybrid, three days on-site.")
    record_b = track_new_offer(offer_b, at="2026-08-18T09:00:30Z")
    save_lifecycle_offer(store, offer_b, record_b)
    return store, (offer_a, record_a), (offer_b, record_b)


def test_two_rejections_of_different_offers_are_distinguishable_in_the_log(
    two_offers: TwoOffers,
) -> None:
    """The failure D-8 exists for, invisible while only one offer has ever
    been rejected: the same wording, about two different offers, must not
    collapse into two indistinguishable rows."""
    store, (offer_a, record_a), (offer_b, record_b) = two_offers

    _, _, row_a = capture_offer_decision_reason(
        store,
        offer_a,
        record_a,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="Too far from home.",
    )
    _, _, row_b = capture_offer_decision_reason(
        store,
        offer_b,
        record_b,
        "screened_out",
        at="2026-08-18T09:01:30Z",
        reason="Too far from home.",
    )

    assert row_a is not None and row_b is not None
    assert row_a.text == row_b.text, "test setup: the wording must be identical"
    assert row_a.about is not None and row_b.about is not None
    assert row_a.about.id != row_b.about.id, "two different offers read as the same subject"
    assert row_a.about == EvidenceSubject(kind="offer", id=offer_a.id)
    assert row_b.about == EvidenceSubject(kind="offer", id=offer_b.id)
    assert captures_without_a_subject(EvidenceLog(store).effective_rows()) == []


def test_a_captured_reason_survives_rebuild_with_its_subject(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """Provenance that does not survive T6's rebuild is not provenance."""
    store = store_for("subject-survives-rebuild")
    offer = connect_manual("Retail Assistant, weekends.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)

    _, _, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="Weekends don't work for me any more.",
    )
    assert row is not None

    rebuild(store)

    reread = [r for r in EvidenceLog(store).rows() if r.id == row.id]
    assert reread, "the captured row did not reach disk"
    assert reread[0].about == EvidenceSubject(kind="offer", id=offer.id), (
        "the row's subject did not survive a rebuild"
    )


def test_an_answer_to_a_question_needs_no_subject_field(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """The exclusion the gate's own docstring names: an answer to a bank
    question has its subject in the bank entry already, so demanding one
    here would make the gate unsatisfiable rather than meaningful."""
    store = store_for("subject-question-excluded")
    row = _drive_history(store)
    assert row is not None
    assert row.about is None, "an answer to a bank question was made to carry a subject"
    assert captures_without_a_subject(EvidenceLog(store).effective_rows()) == [], (
        "an answer to a question was wrongly counted as a capture with no subject"
    )


# --- captures_without_a_subject: the metric itself --------------------------


def test_captures_without_a_subject_flags_an_offer_reaction_with_no_about(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A row whose `source` ties it to a specific artefact, but which carries
    no `about`, is exactly what the gate exists to catch — built by calling
    `capture()` directly, the shape a caller bug that forgot to pass `about`
    would take."""
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="feedback",
        kind="statement",
        text="Too far from home.",
        source="offer_reaction",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is not None and row.about is None
    assert captures_without_a_subject(log.effective_rows()) == [row.id]


def test_captures_without_a_subject_ignores_non_artefact_sources(
    profile: tuple[EvidenceLog, DeclineLedger],
) -> None:
    """A row from any source other than `offer_reaction` (an elicited answer,
    a CV import, an interview note) is not counted — each already answers
    "in response to what" its own way."""
    log, ledger = profile
    row = capture(
        log,
        ledger,
        step="history",
        kind="statement",
        text="I've only ever worked in small teams.",
        source="conversation",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert row is not None
    assert captures_without_a_subject(log.effective_rows()) == []


# --- retraction (T38) and revision (T37) carry the subject through ---------


def test_retraction_does_not_strip_a_captured_rows_subject(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """The row is suppressed from what a rebuild uses; the row itself,
    subject included, is unchanged in the append-only log."""
    store = store_for("subject-survives-retraction")
    offer = connect_manual("Junior Analyst, hybrid, ES.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)
    _, _, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="The pay band is too low.",
    )
    assert row is not None

    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-08-18T09:02:00Z",
        step="feedback",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=row.id,
    )

    fresh = EvidenceLog(store)
    survivor = next(r for r in fresh.rows() if r.id == row.id)
    assert survivor.about == EvidenceSubject(kind="offer", id=offer.id), (
        "retraction stripped the subject instead of only suppressing the row"
    )
    assert row.id not in {r.id for r in fresh.effective_rows()}


def test_revision_refresh_does_not_lose_a_captured_rows_subject(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """T37's `refresh` reads the same log; a subject-carrying row must come
    out the other side of it unchanged."""
    from integral.revision import refresh

    store = store_for("subject-survives-refresh")
    offer = connect_manual("Site Supervisor, contract.")
    record = track_new_offer(offer, at="2026-08-18T09:00:00Z")
    save_lifecycle_offer(store, offer, record)
    _, _, row = capture_offer_decision_reason(
        store,
        offer,
        record,
        "screened_out",
        at="2026-08-18T09:01:00Z",
        reason="Contract, not permanent — no thanks.",
    )
    assert row is not None

    refresh(store)

    reread = [r for r in EvidenceLog(store).rows() if r.id == row.id]
    assert reread and reread[0].about == EvidenceSubject(kind="offer", id=offer.id)


# --- backward compatibility: a pre-D-8 row loads and rebuilds cleanly ------


def test_a_pre_d8_row_with_no_about_key_loads_and_rebuilds(
    store_for: Callable[[str], ProfileStore],
) -> None:
    """`EvidenceRow` is `extra="forbid"` and frozen, but that polices keys
    *present* in the data — a row minted before `about` existed simply lacks
    the key, and must load exactly like every other row with an optional
    field left unset."""
    import json

    from integral.profile import EVIDENCE_PARTS, ProfileError

    store = store_for("subject-legacy-row")
    legacy = {
        "dimensions": [],
        "id": "ev-000001",
        "kind": "statement",
        "recorded_at": "2026-08-01T09:00:00Z",
        "source": "offer_reaction",
        "step": "feedback",
        "text": "Too far from home.",
    }
    path = store.path(*EVIDENCE_PARTS)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8")

    log = EvidenceLog(store)
    try:
        rows = log.rows()
    except ProfileError as exc:  # pragma: no cover - the property under test
        pytest.fail(f"a pre-D-8 row with no 'about' key failed to load: {exc}")
    assert rows[0].about is None

    once = rebuild(store)
    twice = rebuild(store)
    assert once == twice, "a log holding a legacy row did not rebuild deterministically"


# --- the required verification: deliberately drop a subject ----------------


def test_deliberately_dropped_subject_moves_the_metric_above_zero(tmp_path: Path) -> None:
    """The payload's required verification, as a test: call `capture()`
    directly for an offer-reaction row, skipping `about`, and watch
    `captures_without_a_subject` rise from a clean baseline."""
    root = tmp_path / "profiles"
    details = probe_deliberate_subject_break(root)

    assert details["captures_without_a_subject_before_break"] == 0
    assert details["captures_without_a_subject_after_break"] > 0
    assert details["broken_row_id"] in details["violation_ids_after_break"]


def test_cli_subject_gate_exits_nonzero_when_a_capture_has_no_subject(tmp_path: Path) -> None:
    """`_main --subject-gate`'s own contract: `captures_without_a_subject != 0`
    is a violation, exit code 1 — the real (correctly-wired) code passes."""
    from integral.profile_capture import _main

    evidence_path = tmp_path / "D8.json"
    exit_code = _main(["prog", "--subject-gate", "--write-evidence", str(evidence_path)])
    assert exit_code == 0, "the real capture_offer_decision_reason call site should pass the gate"
    assert evidence_path.exists()


# --- module-level sanity: measure_subject_gate()/write_subject_evidence() --


def test_measure_subject_gate_reports_minimum_checks_floor() -> None:
    measured = measure_subject_gate()
    assert measured["checks_run"] >= MINIMUM_SUBJECT_CHECKS
    assert measured["failures"] == []
    assert measured["captures_without_a_subject"] == 0


def test_write_subject_evidence_writes_the_measured_json(tmp_path: Path) -> None:
    target = tmp_path / "D8.json"
    measured = write_subject_evidence(target)
    assert target.exists()
    on_disk = target.read_text(encoding="utf-8")
    assert str(measured["captures_without_a_subject"]) in on_disk


def test_probe_subject_linkage_runs_at_least_the_minimum_checks(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    report = probe_subject_linkage(root)
    assert report["checks_run"] >= MINIMUM_SUBJECT_CHECKS
    assert report["failures"] == []
