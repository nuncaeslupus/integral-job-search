"""T46 — per-use episode approval, details at the point of use, the send boundary.

The gate is `unapproved_episode_disclosures == 0`, so the suite is built so that
the number can be *wrong*. Four of these are regressions from an adversarial
review that killed eight of nine mutations against the first version:

* **S1** — the measurement wrote both sides of its own equality, so deleting the
  approval check left the evidence byte-identical. `test_the_probes_catch_every_planted_defect`
  is the half of the gate that is allowed to find something.
* **S2** — detection was an exact substring of the whole episode, and one
  character defeated it while `payload.json` still reported the story withheld.
* **S3** — enumerating the store meant deleting an episode erased the finding.
* **S6** — an approval bound to a list position broke when the story bank was
  reordered, so ordinary editing failed a `== 0` gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from integral.approval import (
    MINIMUM_PROBES,
    ApprovalError,
    PersonalDetails,
    _carries,
    measure_prepared,
    payload_digest,
    personal_details_in_master,
    prepare,
    probe_boundary,
    read_payload,
    record_sent,
    sends_without_confirmation,
)
from integral.cv_store import CVMaster, Episode, Experience, Skill, SourcedText, write_master
from integral.generate import GenerationError, read_manifest
from integral.identity import ProfileStore, create_profile

ADVERT = (
    "We are hiring a data engineer in Girona. You will own a PostgreSQL estate "
    "and lead a migration off legacy systems."
)

WIN = "Cut the nightly billing run from six hours to forty minutes by rewriting reconciliation."
FAILURE = (
    "Shipped a schema change without a backfill and left invoicing wrong for two days "
    "before anyone noticed."
)

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


def _master(store: ProfileStore, **overrides: object) -> CVMaster:
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
        **overrides,  # type: ignore[arg-type]
    )
    write_master(store, built)
    return built


@pytest.fixture
def master(store: ProfileStore) -> CVMaster:
    return _master(store)


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


def _letter(store: ProfileStore, offer_id: str, version: int) -> Path:
    return store.path("cv", "generated", offer_id, f"v{version}", "letter.md")


# ---------------------------------------------------------------------------
# the gate


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
    """The teeth: an episode reaching the document by any route is caught and named."""
    offer_id, version = _prepare(store, master, approved=(0,))
    letter = _letter(store, offer_id, version)
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 1
    assert FAILURE in measured["unapproved_episodes"][0]


def test_the_probes_catch_every_planted_defect(tmp_path: Path) -> None:
    """S1 — the half of the gate that is allowed to find something.

    `measure()` writes its approvals and its documents from one tuple in one
    call, so they agree by construction: on its own it proves only that
    `generate` emits the indices it was handed, and every check in the module
    could be deleted with the recorded evidence unchanged.
    """
    probed = probe_boundary(tmp_path / "profiles")
    assert probed["detection_probe_failures"] == []
    assert probed["detection_probes"] >= MINIMUM_PROBES


# ---------------------------------------------------------------------------
# S2 — substance, not an exact substring


def test_an_episode_smuggled_through_another_entry_is_caught(store: ProfileStore) -> None:
    """S2 — one character defeated the exact-substring check.

    `headline` and `Experience.description` are claimable free text and reach
    *both* documents. With the failure story minus its full stop sitting in the
    headline, the old gate read 0 while both documents carried it — and
    `payload.json`, the summary whose digest the candidate confirms, went on
    saying the story was withheld. A false summary is the one thing the send
    boundary cannot survive.
    """
    built = _master(store, headline=SourcedText(text=FAILURE.rstrip(".")))
    with pytest.raises(ApprovalError, match="no payload was written"):
        _prepare(store, built)

    assert FAILURE.rstrip(".") in _documents(store, "girona-1", 1)
    assert not store.path("cv", "generated", "girona-1", "v1", "payload.json").exists()
    measured = measure_prepared(store, built, "girona-1", 1)
    assert measured["unapproved_episode_disclosures"] >= 1
    assert any(FAILURE in item for item in measured["unapproved_episodes"])


def test_detection_survives_punctuation_and_spacing(store: ProfileStore, master: CVMaster) -> None:
    """The normalised form is what is compared, so a reflow is not a hiding place."""
    offer_id, version = _prepare(store, master, approved=(0,))
    letter = _letter(store, offer_id, version)
    mangled = "  ".join(FAILURE.replace(",", "").rstrip(".").upper().split())
    letter.write_text(letter.read_text(encoding="utf-8") + mangled + "\n", encoding="utf-8")

    assert measure_prepared(store, master, offer_id, version)["unapproved_episode_disclosures"] >= 1


# ---------------------------------------------------------------------------
# S3 — enumerate the documents, not the store


def test_deleting_the_episode_from_the_store_does_not_erase_the_finding(
    store: ProfileStore, master: CVMaster
) -> None:
    """S3 — a candidate tidying their story bank after a draft used to clear the gate.

    The document still carries the failure story; nothing about the tidy-up
    makes that untrue, and the measurement now reads the document.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    letter = _letter(store, offer_id, version)
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    tidied = master.model_copy(update={"episodes": (master.episodes[0],)})
    measured = measure_prepared(store, tidied, offer_id, version)
    assert measured["unapproved_episode_disclosures"] >= 1
    assert any(FAILURE in item for item in measured["unapproved_episodes"])


# ---------------------------------------------------------------------------
# S6 — an approval names a sentence, not a list position


def test_reordering_the_story_bank_does_not_break_an_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """S6 — a false positive that fires on ordinary editing.

    No document changed and no approved text changed. Since the gate is `== 0`,
    binding an approval to a list position made adding an episode a gate
    failure.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    reordered = master.model_copy(
        update={"episodes": (Episode(kind="context", text="Unrelated."), *master.episodes)}
    )
    measured = measure_prepared(store, reordered, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 0
    assert measured["unapproved_episodes"] == []


def test_rewriting_the_episode_afterwards_does_not_break_the_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """The approval names the sentence, and the sentence in the document is unchanged.

    The first version pinned the approval to the store entry, so editing the
    story bank after the draft failed a `== 0` gate over a document that still
    says exactly what was approved. Store edits are the candidate's business;
    what went to the employer is not retroactively unapproved by them.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    rewritten = master.model_copy(
        update={"episodes": (Episode(kind="achievement", text=WIN + " Twice."), master.episodes[1])}
    )
    assert (
        measure_prepared(store, rewritten, offer_id, version)["unapproved_episode_disclosures"] == 0
    )


def test_an_approval_given_for_another_offer_backs_nothing_here(
    store: ProfileStore, master: CVMaster
) -> None:
    """Per-use means per *this* use — a pasted approval is not one."""
    offer_id, version = _prepare(store, master, approved=(0,))
    approvals = store.path("cv", "generated", offer_id, f"v{version}", "approvals.json")
    approvals.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "offer_id": offer_id,
                "version": version,
                "episodes": [{"offer_id": "elsewhere", "version": 1, "text": WIN}],
            }
        ),
        encoding="utf-8",
    )
    assert measure_prepared(store, master, offer_id, version)["unapproved_episodes"] == [
        f"{offer_id}/v{version} letter.md: {WIN} — no per-use approval backs this line"
    ]


# ---------------------------------------------------------------------------
# per-use, and the rest of the boundary


def test_an_approval_does_not_carry_to_the_next_version(
    store: ProfileStore, master: CVMaster
) -> None:
    """Per *use*: a regeneration is a new document and inherits no consent."""
    _prepare(store, master, approved=(0,))
    offer_id, second = _prepare(store, master)
    assert second == 2
    assert WIN not in _letter(store, offer_id, 2).read_text(encoding="utf-8")

    letter = _letter(store, offer_id, 2)
    letter.write_text(letter.read_text(encoding="utf-8") + WIN + "\n", encoding="utf-8")
    measured = measure_prepared(store, master, offer_id, 2)
    assert any(WIN in item for item in measured["unapproved_episodes"])


def test_a_draft_with_no_approvals_file_backs_nothing(
    store: ProfileStore, master: CVMaster
) -> None:
    """A missing approval file is zero approvals, never a permissive default."""
    offer_id, version = _prepare(store, master, approved=(0,))
    store.path("cv", "generated", offer_id, f"v{version}", "approvals.json").unlink()
    assert measure_prepared(store, master, offer_id, version)["unapproved_episodes"] == [
        f"{offer_id}/v{version} letter.md: {WIN} — no per-use approval backs this line"
    ]


def test_a_version_that_was_never_written_is_not_a_version_that_passed(
    store: ProfileStore, master: CVMaster
) -> None:
    """S8 — an absent document used to measure clean and claim episodes withheld."""
    with pytest.raises(ApprovalError, match="never written"):
        measure_prepared(store, master, "girona-1", 99)


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


# ---------------------------------------------------------------------------
# personal details


def test_personal_details_are_asked_at_step_eleven_not_at_intake(
    store: ProfileStore, master: CVMaster
) -> None:
    """They live beside the document that needed them, never in the intake store."""
    offer_id, version = _prepare(store, master, approved=(0,))

    personal = store.path("cv", "generated", offer_id, f"v{version}", "personal.json")
    assert json.loads(personal.read_text(encoding="utf-8"))["date_of_birth"] == "1815-12-10"
    assert personal_details_in_master(store, DETAILS) == []

    # S4 — matched on letters and digits, so punctuation and spacing do not hide
    # a detail that was gathered speculatively at Intake after all.
    master_path = store.path("cv", "master.json")
    loaded = json.loads(master_path.read_text(encoding="utf-8"))
    loaded["headline"] = {"text": "Backend engineer, tel +34600111222", "provenance": []}
    master_path.write_text(json.dumps(loaded), encoding="utf-8")

    assert personal_details_in_master(store, DETAILS) == [
        "cv/master.json: the phone given at step 11 is in the intake store"
    ]


def test_an_address_missing_a_comma_is_still_found(store: ProfileStore, master: CVMaster) -> None:
    """The value, not its typography, is what leaked."""
    master_path = store.path("cv", "master.json")
    loaded = json.loads(master_path.read_text(encoding="utf-8"))
    loaded["residence_claim"] = {"text": "3 Carrer Nou 17001 Girona", "provenance": []}
    master_path.write_text(json.dumps(loaded), encoding="utf-8")

    assert personal_details_in_master(store, DETAILS) == [
        "cv/master.json: the postal_address given at step 11 is in the intake store"
    ]


# ---------------------------------------------------------------------------
# the send boundary


def test_nothing_is_sent_without_an_explicit_per_item_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """A standing permission is not a confirmation, and neither is another draft's."""
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)

    assert payload.recipient == "hiring team, Girona"
    assert sorted(payload.documents) == ["cv.md", "letter.md"]
    assert payload.episodes == (WIN,)
    assert payload.contact_details["postal_address"] == DETAILS.postal_address

    with pytest.raises(ApprovalError, match="standing permission"):
        record_sent(store, master, offer_id, version, confirms="yes, send anything for this offer")

    _, second = _prepare(store, master)
    stale = payload_digest(read_payload(store, offer_id, second))
    with pytest.raises(ApprovalError, match="standing permission"):
        record_sent(store, master, offer_id, version, confirms=stale)

    assert not store.path("applications").exists(), "nothing was recorded as sent"

    record = record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    assert json.loads(record.read_text(encoding="utf-8"))["confirmed_digest"] == payload_digest(
        payload
    )
    assert sends_without_confirmation(store) == []


def test_a_document_edited_after_drafting_is_not_sendable(
    store: ProfileStore, master: CVMaster
) -> None:
    """The boundary re-measures the files as they stand, not as they were.

    The digest still names the payload — `payload.json` did not change — so only
    reading the documents again catches this.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    digest = payload_digest(read_payload(store, offer_id, version))
    letter = _letter(store, offer_id, version)
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    with pytest.raises(ApprovalError, match="no per-use approval"):
        record_sent(store, master, offer_id, version, confirms=digest)
    assert not store.path("applications").exists()


def test_an_application_record_is_immutable(store: ProfileStore, master: CVMaster) -> None:
    """It is what the candidate answers questions about later."""
    offer_id, version = _prepare(store, master, approved=(0,))
    digest = payload_digest(read_payload(store, offer_id, version))
    record_sent(store, master, offer_id, version, confirms=digest)
    with pytest.raises(ApprovalError, match="immutable"):
        record_sent(store, master, offer_id, version, confirms=digest)


def test_a_hand_written_send_record_is_named(store: ProfileStore, master: CVMaster) -> None:
    """The send check reads both files and compares — it does not take the record's word."""
    offer_id, version = _prepare(store, master, approved=(0,))
    forged = store.path("applications", offer_id, f"v{version}.json")
    forged.parent.mkdir(parents=True, exist_ok=True)
    forged.write_text(
        json.dumps({"offer_id": offer_id, "version": version, "confirmed_digest": "0" * 64}),
        encoding="utf-8",
    )
    assert sends_without_confirmation(store) == [
        f"{offer_id}/v{version}: confirms a different payload"
    ]


def test_a_malformed_send_record_is_reported_not_raised(
    store: ProfileStore, master: CVMaster
) -> None:
    """S9/CodeRabbit — the one thing the check exists to catch must not crash it.

    A record missing its fields, and one that is not JSON at all, are both
    findings. Identity comes from the path, so a record too broken to name
    itself is still named.
    """
    _prepare(store, master, approved=(0,))
    root = store.path("applications", "girona-1")
    root.mkdir(parents=True, exist_ok=True)
    (root / "v1.json").write_text(json.dumps({"confirmed_digest": "0" * 64}), encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "v2.json").write_text("not json at all", encoding="utf-8")

    assert sends_without_confirmation(store) == [
        "applications/girona-1/nested/v2.json: unreadable application record (JSONDecodeError)",
        "applications/girona-1/v1.json: unreadable application record (KeyError)",
    ]


def test_a_short_episode_does_not_match_a_longer_word(store: ProfileStore) -> None:
    """CodeRabbit — the shingle match must consume whole normalised words.

    Unpadded, a one-word episode matched any longer word containing it. Because
    `prepare` refuses to write a payload over a finding, that is not a stray
    number in a report: it is a draft blocked for content that is not the
    episode.
    """
    built = CVMaster(
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(Episode(kind="context", text="Python"),),
    )
    write_master(store, built)
    assert not _carries("A Pythonista writing Pythonic code.", "Python")
    assert _carries("We shipped it in Python, mostly.", "Python")

    offer_id, version = _prepare(store, built)
    letter = _letter(store, offer_id, version)
    letter.write_text(
        letter.read_text(encoding="utf-8") + "Hired a Pythonista in 2024.\n", encoding="utf-8"
    )
    measured = measure_prepared(store, built, offer_id, version)
    assert all("Python —" not in item for item in measured["unapproved_episodes"]), (
        "the planted line is unbacked, but not as a disclosure of the episode"
    )


def test_a_planted_episode_is_not_counted_as_withheld(
    store: ProfileStore, master: CVMaster
) -> None:
    """CodeRabbit — disclosed and withheld in one call is a summary contradicting itself.

    `intact` deliberately excludes lines nothing backs, so measuring withholding
    over it could not see the very line it had just reported.
    """
    offer_id, version = _prepare(store, master, approved=(0,))
    letter = _letter(store, offer_id, version)
    letter.write_text(letter.read_text(encoding="utf-8") + FAILURE + "\n", encoding="utf-8")

    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 1
    assert FAILURE in measured["unapproved_episodes"][0]
    assert measured["episodes_withheld"] == 0, "it is in the document; it was not withheld"
