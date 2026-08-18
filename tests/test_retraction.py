"""T38 — retracting a fact, and deleting a person.

Two operations that sound alike and are nothing like each other.

**Retraction** suppresses one fact everywhere derived while the row survives,
because the log is append-only. Two things follow and both are the point: a
rebuild stays deterministic, and an accidental "forget that" — a mistake
somebody makes in the middle of a sentence — can be taken back.

**Deletion** removes a person's tree entirely, is confirmed once by naming what
goes, and is not reversible. An instruction that does not name a profile
deletes nothing: not "the current one", not "the only one". A deletion that can
be triggered without a name happens by accident, and nothing stands behind it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jobsearch.identity import IdentityError, ProfileStore, create_profile
from jobsearch.profile import EvidenceLog, EvidenceSubject, rebuild
from jobsearch.retraction import (
    DeletionRefused,
    delete_profile,
    derived_files,
    plan_deletion,
    probe_retraction,
    purge_derived_citations,
    retract,
    survivors,
    unretract,
    write_evidence,
)

REGRETTED = "A thing said once and regretted afterwards."


@pytest.fixture
def two_profiles(tmp_path: Path) -> tuple[ProfileStore, ProfileStore]:
    root = tmp_path / "profiles"
    first = create_profile(root, "Ada Lovelace", language="en")
    second = create_profile(root, "Grace Hopper", language="en")
    store = ProfileStore(root, first.handle)
    log = EvidenceLog(store)
    log.append(
        recorded_at="2026-08-17T10:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text=REGRETTED,
        source="conversation",
    )
    log.append(
        recorded_at="2026-08-17T10:01:00Z",
        step="constraints",
        kind="constraint",
        dimensions=["remote_work"],
        text="Fully remote, or nothing.",
        source="conversation",
    )
    rebuild(store)
    return store, ProfileStore(root, second.handle)


# --- retraction ------------------------------------------------------------


def test_retracted_row_is_absent_from_every_derived_file(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    assert any(REGRETTED in path.read_text(encoding="utf-8") for path in derived_files(store))

    retract(log, episode.id, at="2026-08-18T09:00:00Z")

    assert survivors(store) == []
    for path in derived_files(store):
        content = path.read_text(encoding="utf-8")
        assert REGRETTED not in content
        assert episode.id not in content


def test_a_retraction_takes_effect_in_the_same_turn(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """§4.1 — suppressed everywhere derived, in the same turn.

    Forgetting is the one operation whose effect the candidate has to be able
    to see now, rather than at the next step boundary.
    """
    store, _ = two_profiles
    log = EvidenceLog(store)
    retract(log, log.rows()[0].id, at="2026-08-18T09:00:00Z")
    assert REGRETTED not in store.read_text("profile", "stories.jsonl")


def test_the_row_itself_survives_the_retraction(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    retract(log, episode.id, at="2026-08-18T09:00:00Z")
    assert REGRETTED in log.raw_bytes().decode("utf-8")
    assert episode.id in {row.id for row in log.rows()}
    assert episode.id not in {row.id for row in log.effective_rows()}


def test_retraction_is_itself_reversible(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    undo = retract(log, episode.id, at="2026-08-18T09:00:00Z")
    assert episode.id in log.suppressed_ids()

    unretract(log, undo.id, at="2026-08-18T09:05:00Z")
    assert episode.id not in log.suppressed_ids()
    assert REGRETTED in store.read_text("profile", "stories.jsonl")


def test_a_derived_artefact_outside_the_rebuild_is_removed_not_left(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """Rankings are derived, and nothing recomputes them yet (T18).

    Leaving one behind would keep the retracted words on disk and readable,
    which is the one outcome "forget that" must not have. Deleting it is safe
    because a derived artefact is regenerable by definition.
    """
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    ranking = store.write_json(
        {"level": "L1", "cites": [episode.id], "quote": episode.text},
        "rankings",
        "2026-08-17T10-02-00.json",
    )
    assert ranking.exists()

    retract(log, episode.id, at="2026-08-18T09:00:00Z")
    assert not ranking.exists()
    assert survivors(store) == []


def test_purging_names_what_it_removed(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """A ranking that has gone must be sayable, not silently vanished."""
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    store.write_json({"quote": episode.text}, "rankings", "r.json")
    log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="any",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=episode.id,
    )
    rebuild(store)
    assert purge_derived_citations(store) == ["rankings/r.json"]


def test_a_survivor_is_found_by_the_words_as_well_as_the_id(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """Citing the id leaks the reference; quoting the words leaks the fact."""
    store, _ = two_profiles
    log = EvidenceLog(store)
    episode = log.rows()[0]
    log.append(
        recorded_at="2026-08-18T09:00:00Z",
        step="any",
        kind="retraction",
        text="Forget that.",
        source="conversation",
        retracts=episode.id,
    )
    rebuild(store)
    store.write_json({"quote": episode.text}, "rankings", "quoted.json")
    store.write_json({"cites": [episode.id]}, "rankings", "cited.json")
    found = survivors(store)
    assert any("quotes the words" in message for message in found)
    assert any("cites" in message for message in found)


def test_the_evidence_log_itself_is_never_scanned_as_derived(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """It is historical, and the retracted row is supposed to still be in it."""
    store, _ = two_profiles
    assert all(path.name != "evidence.jsonl" for path in derived_files(store))


def test_one_profiles_retraction_does_not_touch_another(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, neighbour = two_profiles
    log = EvidenceLog(store)
    EvidenceLog(neighbour).append(
        recorded_at="2026-08-17T11:00:00Z",
        step="history",
        kind="episode",
        dimensions=["team_autonomy"],
        text="Grace's own words.",
        source="conversation",
    )
    rebuild(neighbour)
    before = neighbour.read_text("profile", "stories.jsonl")
    retract(log, log.rows()[0].id, at="2026-08-18T09:00:00Z")
    assert neighbour.read_text("profile", "stories.jsonl") == before


# --- deletion --------------------------------------------------------------


def test_deletion_without_a_named_target_deletes_nothing(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, neighbour = two_profiles
    for confirmation in (None, "", "   ", "somebody else", "Ada Lovelace"):
        with pytest.raises(DeletionRefused):
            delete_profile(neighbour.root, neighbour.handle, confirmation=confirmation)
    assert neighbour.path().is_dir()
    assert store.path().is_dir()


def test_naming_a_different_profile_does_not_delete_either(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """The name has to be the target's, not just *a* name the tool knows."""
    store, neighbour = two_profiles
    with pytest.raises(DeletionRefused):
        delete_profile(neighbour.root, neighbour.handle, confirmation="Ada Lovelace")
    assert neighbour.path().is_dir()
    assert store.path().is_dir()


def test_a_confirmed_deletion_removes_the_whole_tree(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    store, neighbour = two_profiles
    neighbour.write_json({"sent": True}, "applications", "offer-1", "sent.json")
    neighbour.append_jsonl({"id": "o1"}, "offers", "tombstones.jsonl")

    plan = delete_profile(neighbour.root, neighbour.handle, confirmation="Grace Hopper")
    assert not neighbour.path().exists()
    assert plan.display_name == "Grace Hopper"
    assert store.path().is_dir(), "deleting one profile must not touch another"


def test_either_the_handle_or_the_display_name_confirms(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    _, neighbour = two_profiles
    delete_profile(neighbour.root, neighbour.handle, confirmation=neighbour.handle)
    assert not neighbour.path().exists()


def test_deleting_another_profile_is_permitted_after_naming_it(
    two_profiles: tuple[ProfileStore, ProfileStore],
) -> None:
    """§4.3 — a refusal would protect nothing on a shared laptop.

    Anyone who can run the tool can delete the directory with a file manager.
    What the tool adds is that the target is stated before it happens.
    """
    store, neighbour = two_profiles
    plan = plan_deletion(neighbour.root, neighbour.handle)
    assert "Grace Hopper" in plan.sentence()
    assert "Confirm by typing their name" in plan.sentence()
    delete_profile(neighbour.root, neighbour.handle, confirmation="grace hopper")
    assert not neighbour.path().exists()
    assert store.path().is_dir()


def test_the_plan_says_what_would_go(two_profiles: tuple[ProfileStore, ProfileStore]) -> None:
    store, _ = two_profiles
    store.write_json({"sent": True}, "applications", "offer-1", "sent.json")
    plan = plan_deletion(store.root, store.handle)
    assert "profile" in plan.areas
    assert "applications" in plan.areas
    assert plan.files > 0


def test_deleting_a_profile_that_does_not_exist_is_an_error_not_a_no_op(
    tmp_path: Path,
) -> None:
    with pytest.raises(IdentityError):
        delete_profile(tmp_path / "profiles", "nobody", confirmation="nobody")


# --- the gate --------------------------------------------------------------


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T38.json"
    measured = write_evidence(evidence)
    assert measured["retracted_rows_surviving_rebuild"] == 0
    assert measured["derived_files_scanned"] >= 4
    assert measured["failures"] == []
    assert json.loads(evidence.read_text(encoding="utf-8")) == measured


def test_the_probe_cleans_nothing_up_by_hand(tmp_path: Path) -> None:
    """Whatever `retract` does not clear is a survivor.

    An earlier version of the probe rewrote the ranking itself before counting,
    which made zero survivors true by construction rather than by the code.
    """
    result = probe_retraction(tmp_path / "profiles")
    assert result["failures"] == []
    assert result["retracted_rows_surviving_rebuild"] == 0


def test_retracting_a_subject_carrying_row_does_not_strip_its_subject(
    tmp_path: Path,
) -> None:
    """D-8: a retraction suppresses a row from what a rebuild uses; it must
    not, in the process, lose the `about` field that names what the row was
    about. `retract` calls `rebuild`, and T6's `rebuild` never rewrites the
    log itself — this proves that holds for a subject-carrying row too,
    rather than assuming it because it holds for every other field.
    """
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", language="en")
    store = ProfileStore(root, identity.handle)
    log = EvidenceLog(store)
    subject = EvidenceSubject(kind="offer", id=f"sha256:{'b' * 64}")
    row = log.append(
        recorded_at="2026-08-17T10:00:00Z",
        step="feedback",
        kind="statement",
        text="Too far from home.",
        source="offer_reaction",
        about=subject,
    )

    retract(log, row.id, at="2026-08-18T09:00:00Z")

    fresh = EvidenceLog(store)
    survivor = next(r for r in fresh.rows() if r.id == row.id)
    assert survivor.about == subject, "retraction stripped the subject instead of only suppressing"
    assert row.id not in {r.id for r in fresh.effective_rows()}
