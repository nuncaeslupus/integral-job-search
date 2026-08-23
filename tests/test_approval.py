"""T46 — per-use episode approval, details at the point of use, the send boundary.

The gate is `unapproved_episode_disclosures == 0`, so the suite is built so that
the number can be *wrong*: `test_the_gate_notices_a_planted_disclosure` writes an
episode into a finished document with nothing approving it and requires the count
to rise and to name the offending episode. A gate that cannot fail is not a gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.approval import (
    ApprovalError,
    PersonalDetails,
    measure_prepared,
    payload_digest,
    personal_details_in_master,
    prepare,
    read_payload,
    record_sent,
    sends_without_confirmation,
)
from integral.cv_store import CVMaster, Episode, Experience, Skill, write_master
from integral.generate import GenerationError, read_manifest
from integral.identity import ProfileStore, create_profile

ADVERT = (
    "We are hiring a data engineer in Girona. You will own a PostgreSQL estate "
    "and lead a migration off legacy systems."
)

WIN = "Cut the nightly billing run from six hours to forty minutes."
FAILURE = "Shipped a schema change without a backfill and broke invoicing for two days."

DETAILS = PersonalDetails(
    full_name="Ada Lovelace",
    email="ada@example.invalid",
    phone="+34 600 111 222",
    postal_address="3 Carrer Nou, 17001 Girona",
    date_of_birth="1815-12-10",
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


@pytest.fixture
def master(store: ProfileStore) -> CVMaster:
    built = CVMaster(
        experience=(
            Experience(
                title="Data migration lead",
                organisation="Cintra Logistics",
                start="2021",
                end="2025",
                description="Moved the billing system off the mainframe.",
            ),
        ),
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(kind="achievement", text=WIN),
            Episode(kind="failure", text=FAILURE),
        ),
    )
    write_master(store, built)
    return built


def _prepare(
    store: ProfileStore, master: CVMaster, *, approved: tuple[int, ...] = ()
) -> tuple[str, int]:
    payload = prepare(
        store,
        master,
        offer_id="girona-1",
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
    )
    return payload.offer_id, payload.version


def _documents(store: ProfileStore, offer_id: str, version: int) -> str:
    where = store.path("cv", "generated", offer_id, f"v{version}")
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(where.glob("*.md")))


def test_episode_without_per_use_approval_never_enters_a_document(
    store: ProfileStore, master: CVMaster
) -> None:
    """The gate. An approved episode appears; an unapproved one does not exist to the draft."""
    offer_id, version = _prepare(store, master, approved=(0,))

    written = _documents(store, offer_id, version)
    assert WIN in written, "an approved episode is what the approval was for"
    assert FAILURE not in written, "recounting a failure was never consent to send it"

    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 0
    assert measured["unapproved_episodes"] == []
    assert measured["episode_disclosures"] == 1
    assert measured["episodes_withheld"] == 1


def test_the_gate_notices_a_planted_disclosure(store: ProfileStore, master: CVMaster) -> None:
    """The teeth: an episode reaching the document by any route is caught and named.

    The measurement reads the file, not the object that wrote it, so it does not
    matter whether a hand edit, a later feature or a model put the line there.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    letter = store.path("cv", "generated", offer_id, f"v{version}", "letter.md")
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 1
    assert measured["unapproved_episodes"] == [f"{offer_id}/v{version}: episode 1 — {FAILURE}"]


def test_an_approval_does_not_carry_to_the_next_version(
    store: ProfileStore, master: CVMaster
) -> None:
    """Per *use*: a regeneration is a new document and inherits no consent."""
    _prepare(store, master, approved=(0,))
    offer_id, second = _prepare(store, master)
    assert second == 2

    letter = store.path("cv", "generated", offer_id, "v2", "letter.md")
    assert WIN not in letter.read_text(encoding="utf-8")

    letter.write_text(letter.read_text(encoding="utf-8") + WIN + "\n", encoding="utf-8")
    measured = measure_prepared(store, master, offer_id, 2)
    assert measured["unapproved_episodes"] == [f"{offer_id}/v2: episode 0 — {WIN}"]


def test_an_approval_stops_backing_an_episode_the_candidate_changed(
    store: ProfileStore, master: CVMaster
) -> None:
    """The approval pins the text, so an edited episode does not ride out on old consent."""
    offer_id, version = _prepare(store, master, approved=(0,))
    edited = master.model_copy(
        update={"episodes": (Episode(kind="achievement", text=WIN), *master.episodes[1:])}
    )
    assert measure_prepared(store, edited, offer_id, version)["unapproved_episodes"] == []

    rewritten = master.model_copy(
        update={
            "episodes": (
                Episode(kind="achievement", text=WIN + " Twice."),
                *master.episodes[1:],
            )
        }
    )
    letter = store.path("cv", "generated", offer_id, f"v{version}", "letter.md")
    letter.write_text(
        letter.read_text(encoding="utf-8") + WIN + " Twice.\n",
        encoding="utf-8",
    )
    measured = measure_prepared(store, rewritten, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 1


def test_an_episode_the_store_does_not_hold_is_refused_before_anything_is_written(
    store: ProfileStore, master: CVMaster
) -> None:
    """A bad index costs no version number — validation precedes the reservation."""
    with pytest.raises(GenerationError, match="no episode 7"):
        _prepare(store, master, approved=(7,))
    assert not store.path("cv", "generated", "girona-1").exists()


def test_an_approved_episode_still_traces_to_the_store(
    store: ProfileStore, master: CVMaster
) -> None:
    """T45's contract is not weakened by the new line: it is a manifest claim too."""
    offer_id, version = _prepare(store, master, approved=(0,))
    manifest = read_manifest(store, offer_id, version)
    assert any(
        claim.section == "episodes" and claim.text == WIN and claim.document == "letter.md"
        for claim in manifest.claims
    )


def test_personal_details_are_asked_at_step_eleven_not_at_intake(
    store: ProfileStore, master: CVMaster
) -> None:
    """They live beside the document that needed them, never in the intake store."""
    offer_id, version = _prepare(store, master, approved=(0,))

    personal = store.path("cv", "generated", offer_id, f"v{version}", "personal.json")
    assert json.loads(personal.read_text(encoding="utf-8"))["date_of_birth"] == "1815-12-10"
    assert personal_details_in_master(store, DETAILS) == []

    # And the check has teeth: a detail gathered speculatively at Intake is
    # named wherever in `master.json` it is hiding.
    master_path = store.path("cv", "master.json")
    loaded = json.loads(master_path.read_text(encoding="utf-8"))
    loaded["headline"] = {"text": f"Backend engineer — {DETAILS.phone}", "provenance": []}
    master_path.write_text(json.dumps(loaded), encoding="utf-8")

    found = personal_details_in_master(store, DETAILS)
    assert found == ["cv/master.json: the phone given at step 11 is in the intake store"]


def test_nothing_is_sent_without_an_explicit_per_item_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """A standing permission is not a confirmation, and neither is another draft's."""
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)

    # The payload is the summary of everything that would go — §6.2's "not
    # 'shall I apply?' but the actual payload".
    assert payload.recipient == "hiring team, Girona"
    assert sorted(payload.documents) == ["cv.md", "letter.md"]
    assert payload.episodes == (WIN,)
    assert payload.contact_details["postal_address"] == DETAILS.postal_address

    with pytest.raises(ApprovalError, match="standing permission"):
        record_sent(store, offer_id, version, confirms="yes, send anything for this offer")

    _, second = _prepare(store, master)
    stale = payload_digest(read_payload(store, offer_id, second))
    with pytest.raises(ApprovalError, match="standing permission"):
        record_sent(store, offer_id, version, confirms=stale)

    assert not store.path("applications").exists(), "nothing was recorded as sent"

    record = record_sent(store, offer_id, version, confirms=payload_digest(payload))
    assert json.loads(record.read_text(encoding="utf-8"))["confirmed_digest"] == payload_digest(
        payload
    )
    assert sends_without_confirmation(store) == []


def test_an_application_record_is_immutable(store: ProfileStore, master: CVMaster) -> None:
    """It is what the candidate answers questions about later."""
    offer_id, version = _prepare(store, master, approved=(0,))
    digest = payload_digest(read_payload(store, offer_id, version))
    record_sent(store, offer_id, version, confirms=digest)
    with pytest.raises(ApprovalError, match="immutable"):
        record_sent(store, offer_id, version, confirms=digest)


def test_a_hand_written_send_record_is_named(store: ProfileStore, master: CVMaster) -> None:
    """The send check reads both files and compares — it does not take the record's word."""
    offer_id, version = _prepare(store, master, approved=(0,))
    forged = store.path("applications", offer_id, f"v{version}.json")
    forged.parent.mkdir(parents=True, exist_ok=True)
    forged.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "offer_id": offer_id,
                "version": version,
                "confirmed_digest": "0" * 64,
                "sent_at": "2026-08-23T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    assert sends_without_confirmation(store) == [
        f"{offer_id}/v{version}: confirms a different payload"
    ]


def test_a_draft_with_no_approvals_file_backs_nothing(
    store: ProfileStore, master: CVMaster
) -> None:
    """A missing approval file is zero approvals, never a permissive default."""
    offer_id, version = _prepare(store, master, approved=(0,))
    store.path("cv", "generated", offer_id, f"v{version}", "approvals.json").unlink()
    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episodes"] == [f"{offer_id}/v{version}: episode 0 — {WIN}"]
