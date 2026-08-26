"""T82 — the application status vocabulary (spec §5.2).

`applications/{offer_id}/` records what was sent and when, and until now had
no vocabulary for what became of it. §5.2 fixes nine statuses, closed, split
Open and Final, with legacy space-spellings tolerated on read and never
written — and `hired`/`offer_declined` never inferred, only recorded when the
candidate says so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    FINAL_APPLICATION_STATUSES,
    OPEN_APPLICATION_STATUSES,
    ApplicationStatusError,
    application_status_class,
    audit_application_statuses,
    normalise_application_status,
    probe_application_statuses,
    read_application_status,
    record_application_status,
)

NOW = "2026-08-26T10:00:00Z"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Test Candidate", language="en")
    return ProfileStore(root, identity.handle)


# --- the vocabulary is closed -----------------------------------------------


def test_a_status_outside_the_vocabulary_is_refused(store: ProfileStore) -> None:
    with pytest.raises(ApplicationStatusError):
        normalise_application_status("ghosted")

    with pytest.raises(ApplicationStatusError):
        record_application_status(store, "offer-1", status="ghosted", at=NOW)

    audited = audit_application_statuses([("offer-1", "ghosted")])
    assert audited["applications_with_a_noncanonical_status"] == 1
    assert audited["applications_with_a_noncanonical_status_evaluated"] == 1
    assert "offer-1" in audited["violations"][0]
    assert "ghosted" in audited["violations"][0]


# --- legacy space-spellings: tolerance at the boundary, not a migration ----


def test_a_legacy_spelling_is_accepted_on_read_and_never_written(store: ProfileStore) -> None:
    # A pre-existing (or externally authored) record this module never wrote.
    store.write_json(
        {"status": "no response", "recorded_at": NOW},
        "applications",
        "offer-legacy",
        "status.json",
    )
    assert read_application_status(store, "offer-legacy") == "no_response"
    # Reading tolerated the space-spelling in memory; it did not migrate the
    # file — the record on disk is exactly what was written above.
    on_disk = store.read_json("applications", "offer-legacy", "status.json")
    assert on_disk["status"] == "no response"

    # A caller that hands the write path a legacy spelling never gets it
    # persisted with a space — every write this module performs is canonical.
    record_application_status(
        store, "offer-2", status="offer declined", at=NOW, candidate_confirmed=True
    )
    written = store.read_json("applications", "offer-2", "status.json")
    assert written["status"] == "offer_declined"
    assert " " not in written["status"]


# --- Open vs Final ------------------------------------------------------


def test_open_and_final_statuses_are_distinguishable() -> None:
    assert {"drafted", "applied", "interview", "offer"} == OPEN_APPLICATION_STATUSES
    assert {
        "hired",
        "rejected",
        "no_response",
        "offer_declined",
        "withdrawn",
    } == FINAL_APPLICATION_STATUSES
    assert not (OPEN_APPLICATION_STATUSES & FINAL_APPLICATION_STATUSES)
    assert len(OPEN_APPLICATION_STATUSES | FINAL_APPLICATION_STATUSES) == 9

    for status in OPEN_APPLICATION_STATUSES:
        assert application_status_class(status) == "open"
    for status in FINAL_APPLICATION_STATUSES:
        assert application_status_class(status) == "final"


# --- a zero count must prove the mechanism ran ------------------------------


def test_the_gate_does_not_pass_on_an_empty_input_set() -> None:
    empty = audit_application_statuses([])
    assert empty["applications_with_a_noncanonical_status_evaluated"] == 0
    assert empty["application_records_checked"] == 0
    assert empty["gate_status"] == "unmeasured"

    measured = probe_application_statuses()
    assert measured["applications_with_a_noncanonical_status_evaluated"] > 0
    assert (
        measured["application_records_checked"]
        == measured["applications_with_a_noncanonical_status_evaluated"]
    )
    assert measured["gate_status"] == "measured"
    assert measured["applications_with_a_noncanonical_status"] == 0


# --- hired/offer_declined are recorded only when the candidate says so -----


def test_hired_and_offer_declined_are_never_inferred(store: ProfileStore) -> None:
    with pytest.raises(ApplicationStatusError):
        record_application_status(store, "offer-3", status="hired", at=NOW)
    with pytest.raises(ApplicationStatusError):
        record_application_status(store, "offer-4", status="offer_declined", at=NOW)

    record_application_status(store, "offer-3", status="hired", at=NOW, candidate_confirmed=True)
    assert read_application_status(store, "offer-3") == "hired"


def test_an_unrecorded_offer_has_no_status(store: ProfileStore) -> None:
    assert read_application_status(store, "offer-none") is None


def test_a_malformed_status_record_is_an_error_not_a_missing_one(store: ProfileStore) -> None:
    """`read_json` raises IdentityError for a missing file AND for malformed
    JSON, so catching it wholesale reported corruption as "never recorded" —
    and the next write then overwrote the corrupt record instead of refusing.

    A record that parses as JSON but fails the schema was already an error, so
    the same damage was an error or a silent overwrite depending only on how
    broken the file was."""
    store.write_text("{ not json", "applications", "offer-1", "status.json")

    with pytest.raises(ApplicationStatusError, match="could not be read"):
        read_application_status(store, "offer-1")


def test_a_status_never_recorded_is_still_none(store: ProfileStore) -> None:
    """The missing case must survive the fix above."""
    assert read_application_status(store, "never-seen") is None
