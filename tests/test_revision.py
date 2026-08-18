"""T37 — profile revision, and §3.4's three classes of staleness.

The gate is `stale_artefact_detection_recall == 1.0`: of the artefacts really
behind the current revision, the fraction reported. Recall rather than
precision, because the expensive failure is silent — an out-of-date CV shown as
current is worse than a current one flagged for a second look.

The distinction that carries the task is **authored**. A generated CV may
already be with an employer, so it is marked and kept, never regenerated;
silently rewriting it leaves the candidate unable to answer a question about
their own application.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.constraints_step import CandidateTurn
from jobsearch.constraints_step import resolve as resolve_constraints
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.profile import EvidenceLog, EvidenceSubject, ProfileRevision, rebuild
from jobsearch.revision import (
    STALE_SUFFIX,
    classify,
    is_immutable,
    mark_stale,
    probe_staleness,
    recorded_revision,
    refresh,
    revisioned_artefacts,
    rows_since,
    stale_artefacts,
    write_evidence,
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)
    EvidenceLog(store).append(
        recorded_at="2026-08-17T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="They let me pick the stack.",
        source="conversation",
    )
    rebuild(store)
    return store


def _generated_cv(store: ProfileStore, revision: ProfileRevision) -> Path:
    return store.write_json(
        {"profile_revision": revision.as_json(), "claims": ["picked the stack"]},
        "cv",
        "generated",
        "offer-1",
        "v1",
        "cv.json",
    )


def _move_on(store: ProfileStore) -> None:
    EvidenceLog(store).append(
        recorded_at="2026-08-18T09:00:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote, or nothing.",
        source="conversation",
    )


# --- the three classes -----------------------------------------------------


def test_each_artefact_lands_in_the_class_the_spec_gives_it() -> None:
    assert classify("profile/constraints.json") == "derived"
    assert classify("profile/stories.jsonl") == "derived"
    assert classify("rankings/2026-08-18.json") == "derived"
    assert classify("extractions/o1.json") == "derived"
    assert classify("cv/generated/offer-1/v1/cv.json") == "authored"
    assert classify("interviews/offer-1/preparation.md") == "authored"
    assert classify("profile/evidence.jsonl") == "historical"
    assert classify("applications/offer-1/sent.json") == "historical"
    assert classify("interviews/offer-1/record.json") == "historical"
    assert classify("offers/tombstones.jsonl") == "historical"
    assert classify("cv/source/original.pdf") == "historical"


def test_an_interview_record_and_its_preparation_are_different_classes() -> None:
    """The notes made before it are revisable; what happened is not."""
    assert classify("interviews/offer-1/preparation.md") == "authored"
    assert is_immutable("interviews/offer-1/record.json")


def test_an_unplaced_artefact_defaults_to_authored() -> None:
    """The safe default is "it may be out of date", never "regenerate it"."""
    assert classify("something/nobody/placed.json") == "authored"


def test_classification_is_by_location_not_by_a_field_in_the_file() -> None:
    """A file that declares its own class can declare the wrong one.

    The file that matters is a generated CV claiming to be derived — which is
    exactly the one that would then be regenerated after it had been sent.
    """
    assert classify("cv/generated/offer-1/v1/cv.json") == "authored"


# --- staleness is computed -------------------------------------------------


def test_artefact_behind_current_revision_reads_stale(store: ProfileStore) -> None:
    log = EvidenceLog(store)
    _generated_cv(store, log.revision())
    assert stale_artefacts(store) == []

    _move_on(store)
    stale = {entry.artefact: entry for entry in stale_artefacts(store)}
    assert "cv/generated/offer-1/v1/cv.json" in stale
    assert "profile/constraints.json" in stale
    assert stale["cv/generated/offer-1/v1/cv.json"].rows_behind == 1
    assert "remote_work" in stale["cv/generated/offer-1/v1/cv.json"].changed


def test_the_reason_says_what_changed(store: ProfileStore) -> None:
    _generated_cv(store, EvidenceLog(store).revision())
    _move_on(store)
    entry = next(e for e in stale_artefacts(store) if e.artefact_class == "authored")
    assert "1 new evidence row" in entry.reason()
    assert "remote_work" in entry.reason()


def test_an_artefact_recording_no_revision_is_treated_as_behind(
    store: ProfileStore,
) -> None:
    """Forgetting to stamp a file must not make it permanently fresh."""
    store.write_json({"claims": []}, "cv", "generated", "offer-1", "v1", "cv.json")
    stale = {entry.artefact for entry in stale_artefacts(store)}
    assert "cv/generated/offer-1/v1/cv.json" in stale


def test_a_derived_jsonl_can_be_shown_to_be_current(store: ProfileStore) -> None:
    """`stories.jsonl` carries no header, so the derived manifest speaks for it.

    Without that, it could never be shown to be current and a rebuild would
    never clear it — the stale list would never converge.
    """
    assert stale_artefacts(store) == []
    _move_on(store)
    assert "profile/stories.jsonl" in {entry.artefact for entry in stale_artefacts(store)}
    rebuild(store)
    assert "profile/stories.jsonl" not in {entry.artefact for entry in stale_artefacts(store)}


def test_historical_artefacts_are_never_listed_as_stale(store: ProfileStore) -> None:
    """There is no operation that would bring one up to date."""
    store.write_json({"sent_at": "2026-08-17T12:00:00Z"}, "applications", "offer-1", "sent.json")
    store.write_json({"outcome": "rejected"}, "interviews", "offer-1", "record.json")
    _move_on(store)
    assert all(entry.artefact_class != "historical" for entry in stale_artefacts(store))
    listed = {relative for relative, _ in revisioned_artefacts(store)}
    assert Path("profile/evidence.jsonl") not in listed
    assert Path("applications/offer-1/sent.json") not in listed


def test_identity_and_session_state_are_not_judged_against_the_log(
    store: ProfileStore,
) -> None:
    """They are the frame the log sits in, not something derived from it."""
    store.write_json({"current_step": "history"}, "session", "state.json")
    _move_on(store)
    listed = {str(relative) for relative, _ in revisioned_artefacts(store)}
    assert "identity.json" not in listed
    assert "session/state.json" not in listed


def test_rows_since_counts_by_position_not_by_timestamp(store: ProfileStore) -> None:
    """Two rows recorded in the same second are still two rows."""
    log = EvidenceLog(store)
    before = log.revision()
    _move_on(store)
    assert len(rows_since(log, before)) == 1
    assert len(rows_since(log, None)) == len(log.rows())


def test_a_revision_stamp_that_is_not_one_reads_as_absent() -> None:
    assert recorded_revision({"profile_revision": {"rows": "many"}}) is None
    assert recorded_revision({"profile_revision": "412"}) is None
    assert recorded_revision("nonsense") is None
    assert recorded_revision({"profile_revision": {"rows": 4, "sha256": "ab"}}) == ProfileRevision(
        rows=4, sha256="ab"
    )


# --- acting on it ----------------------------------------------------------


def test_authored_artefact_is_marked_not_regenerated(store: ProfileStore) -> None:
    """§3.4 — kept exactly as they are; regeneration is offered, never automatic."""
    cv = _generated_cv(store, EvidenceLog(store).revision())
    before = cv.read_bytes()
    _move_on(store)

    result = refresh(store)
    assert cv.read_bytes() == before, "the CV that was sent must still be the file that was sent"
    assert result.marked == ("cv/generated/offer-1/v1/cv.json" + STALE_SUFFIX,)

    marker = json.loads(store.path(*result.marked[0].split("/")).read_text(encoding="utf-8"))
    assert marker["action"] == "offer to regenerate"
    assert marker["changed"] == ["remote_work"]
    assert "1 new evidence row" in marker["reason"]


def test_historical_artefact_is_never_revised(store: ProfileStore) -> None:
    store.write_json({"sent_at": "2026-08-17T12:00:00Z"}, "applications", "offer-1", "sent.json")
    store.write_json({"outcome": "rejected"}, "interviews", "offer-1", "record.json")
    _move_on(store)
    before = {
        str(path.relative_to(store.path())): path.read_bytes()
        for path in sorted(store.path().rglob("*"))
        if path.is_file() and is_immutable(path.relative_to(store.path()))
    }
    result = refresh(store)
    after = {
        relative: store.path(*Path(relative).parts).read_bytes() for relative in before
    }
    assert after == before
    assert set(result.untouched_historical) == set(before)


def test_derived_artefacts_are_recomputed_by_a_refresh(store: ProfileStore) -> None:
    _move_on(store)
    assert any(entry.artefact_class == "derived" for entry in stale_artefacts(store))
    refresh(store)
    assert [entry for entry in stale_artefacts(store) if entry.artefact_class == "derived"] == []


def test_a_marker_sits_beside_the_artefact_not_inside_it(store: ProfileStore) -> None:
    cv = _generated_cv(store, EvidenceLog(store).revision())
    _move_on(store)
    entry = next(e for e in stale_artefacts(store) if e.artefact_class == "authored")
    marker = mark_stale(store, entry)
    assert marker != cv
    assert marker.name.endswith(STALE_SUFFIX)
    assert "stale" not in json.loads(cv.read_text(encoding="utf-8"))


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T37.json"
    measured = write_evidence(evidence)
    assert measured["stale_artefact_detection_recall"] == 1.0
    assert measured["artefacts_aged"] >= 4
    assert measured["failures"] == []
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_a_failure_elsewhere_in_the_class_rules_does_not_pass_behind_a_clean_recall(
    tmp_path: Path,
) -> None:
    """The recall number alone would report 1.0 while a CV was being rewritten."""
    result = probe_staleness(tmp_path / "profiles")
    assert result["failures"] == []
    assert result["stale_artefact_detection_recall"] == 1.0


# --- D-6: a refresh must not un-ask a question the candidate already answered


def test_a_declined_field_survives_a_rebuild(tmp_path: Path) -> None:
    """A refresh must not revert a declined field to never-asked.

    T41's engine records a decline in `session/declines.jsonl`, not in the
    evidence log, and writes `state: "declined"` into `constraints.json`.
    Before the fix, `revision.refresh` called `jobsearch.profile.rebuild`,
    which regenerated `constraints.json` from the evidence log alone — a
    field the candidate explicitly refused reverted to
    indistinguishable-from-never-asked, and the tool would ask again, which
    is exactly the non-insistence guarantee T40 exists to provide.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)

    resolve_constraints(
        store, [CandidateTurn(field="salary", action="decline")], now="2026-08-18T09:00:00Z"
    )
    before = json.loads(store.path("profile", "constraints.json").read_text(encoding="utf-8"))
    assert before["fields"]["salary"]["state"] == "declined"

    refresh(store)

    after = json.loads(store.path("profile", "constraints.json").read_text(encoding="utf-8"))
    assert after["fields"]["salary"]["state"] == "declined", (
        "a refresh after a constraints step un-declined a field the candidate "
        "had explicitly refused"
    )


def test_an_unknown_field_survives_a_rebuild(tmp_path: Path) -> None:
    """An unaddressed pinned field must still read `unknown`, not disappear.

    T41 writes all ten of T24's pinned fields on every call, including the
    ones nobody has addressed yet. Before the fix, `rebuild` only wrote a
    field that had a `stated` evidence row behind it, so an untouched pinned
    field vanished from `constraints.json` entirely once a refresh ran —
    indistinguishable from a field that was never part of the schema at all.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)

    resolve_constraints(
        store,
        [
            CandidateTurn(
                field="salary", action="state", value={"floor": 40000, "currency": "EUR"}
            )
        ],
        now="2026-08-18T09:00:00Z",
    )
    before = json.loads(store.path("profile", "constraints.json").read_text(encoding="utf-8"))
    assert before["fields"]["location"]["state"] == "unknown"

    refresh(store)

    after = json.loads(store.path("profile", "constraints.json").read_text(encoding="utf-8"))
    assert "location" in after["fields"], (
        "a refresh after a constraints step dropped an unaddressed pinned field entirely"
    )
    assert after["fields"]["location"]["state"] == "unknown"


def test_a_subject_carrying_row_survives_a_refresh(tmp_path: Path) -> None:
    """D-8: `refresh` reads the same log every other T37 function does — a
    row carrying `about` (T28's offer-decision-reason capture) must come out
    the other side of a refresh unchanged, not just unregressed on the fields
    this module itself computes.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    subject = EvidenceSubject(kind="offer", id=f"sha256:{'a' * 64}")
    row = log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="feedback",
        kind="statement",
        text="Too far from home.",
        source="offer_reaction",
        about=subject,
    )

    refresh(store)

    reread = [r for r in EvidenceLog(store).rows() if r.id == row.id]
    assert reread and reread[0].about == subject, (
        "a subject-carrying row lost its subject across a refresh"
    )
