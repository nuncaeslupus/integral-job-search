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
import unicodedata
from pathlib import Path

import pytest

from integral.approval import (
    DEFAULT_D24_EVIDENCE_PATH,
    MINIMUM_PROBES,
    MINIMUM_RETRACTED_APPROVALS_EVALUATED,
    MINIMUM_RETRACTION_PROBES,
    ApprovalError,
    PersonalDetails,
    _carries,
    _main,
    _retraction_report,
    measure_prepared,
    payload_digest,
    personal_details_in_master,
    prepare,
    probe_boundary,
    probe_retracted_sends,
    read_payload,
    record_sent,
    retracted_episodes_sendable,
    sends_without_confirmation,
)
from integral.cv_store import (
    ConversationTurn,
    CVMaster,
    Episode,
    Experience,
    Skill,
    SourcedText,
    write_master,
)
from integral.generate import GenerationError, read_manifest
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog, ProfileError
from integral.retraction import retract, unretract

ADVERT = (
    "We are hiring a data engineer in Girona. You will own a PostgreSQL estate "
    "and lead a migration off legacy systems."
)

WIN = "Cut the nightly billing run from six hours to forty minutes by rewriting reconciliation."
FAILURE = (
    "Shipped a schema change without a backfill and left invoicing wrong for two days "
    "before anyone noticed."
)

OWNED = "Owned the client's month end close and cut the handover from three days to one."
LLEIDA = "Reduje el cierre contable de la vieja delegación de Lleida a cuarenta minutos justos."
RAW_UTTERANCE = (
    "Yeah, so basically I cut the nightly billing run from six hours to forty minutes "
    "by rewriting reconciliation, that was the thing I did there."
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


# ---------------------------------------------------------------------------
# D-24 — an approval cannot outlive the evidence it was granted over
#
# Every name below carries `retract`, because the task's gate selects these with
# `-k retract`. A name spelled `…retraction…` still matches; a name with neither
# is silently not run, which is the one failure a green gate cannot show.


def _episode_row(store: ProfileStore, text: str, *, at: str = "2026-01-01T09:00:00+00:00") -> str:
    """One story-bank row in the evidence log, returning its id."""
    return (
        EvidenceLog(store)
        .append(recorded_at=at, step="history", kind="episode", text=text, source="conversation")
        .id
    )


def _retract_row(store: ProfileStore, row_id: str, *, at: str = "2026-01-02T09:00:00+00:00") -> str:
    return retract(EvidenceLog(store), row_id, at=at).id


def test_a_retracted_episode_cannot_be_sent(store: ProfileStore, master: CVMaster) -> None:
    """The defect. Approve, retract the evidence, and the send boundary must refuse."""
    row = _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, row)

    with pytest.raises(ApprovalError):
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))


def test_an_unretracted_approval_still_sends(store: ProfileStore, master: CVMaster) -> None:
    """Retracting some *other* episode must not turn every send into a refusal."""
    _episode_row(store, WIN)
    other = _episode_row(store, FAILURE)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, other)

    record = record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    assert record.exists()


def test_retraction_after_send_does_not_rewrite_the_record(
    store: ProfileStore, master: CVMaster
) -> None:
    """An application record is what the candidate answers questions about later."""
    row = _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    record = record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    before = record.read_bytes()

    _retract_row(store, row)
    assert record.read_bytes() == before


def test_an_empty_retraction_check_reports_unmeasured(
    store: ProfileStore, master: CVMaster
) -> None:
    """An approval and no retraction checks nothing — and nothing checked is not a pass."""
    _episode_row(store, WIN)
    _prepare(store, master, approved=(0,))

    measured = retracted_episodes_sendable(store, master)
    assert measured["retracted_episodes_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert measured["retracted_episodes_still_sendable"] == 0


def test_a_populated_retraction_check_reports_measured(
    store: ProfileStore, master: CVMaster
) -> None:
    """The denominator assertion — it cannot live in the empty-input test above."""
    row = _episode_row(store, WIN)
    _prepare(store, master, approved=(0,))
    _retract_row(store, row)

    measured = retracted_episodes_sendable(store, master)
    assert measured["retracted_episodes_evaluated"] > 0
    assert measured["gate_status"] == "measured"
    assert measured["retracted_episodes_still_sendable"] == 0


def test_retracting_one_of_two_identical_episodes_withdraws_the_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """Two rows, one sentence. The approval names the sentence, so both go.

    Over-refusing on purpose: the approval carries no evidence id, so a text
    match cannot tell the retracted row from the survivor, and §6.2 prefers the
    refusal to the send.
    """
    _episode_row(store, WIN)
    twin = _episode_row(store, WIN, at="2026-01-01T10:00:00+00:00")
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, twin)

    with pytest.raises(ApprovalError):
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))


def test_an_undone_retraction_makes_the_approval_live_again(
    store: ProfileStore, master: CVMaster
) -> None:
    """`unretract` puts the row back, so the check must read the log, not a snapshot."""
    row = _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    retraction = _retract_row(store, row)
    unretract(EvidenceLog(store), retraction, at="2026-01-03T09:00:00+00:00")

    record = record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    assert record.exists()


def test_a_retracted_episode_is_refused_before_a_payload_is_written(
    store: ProfileStore, master: CVMaster
) -> None:
    """`prepare` routes through the same measurement, so a retracted story never drafts."""
    row = _episode_row(store, WIN)
    _retract_row(store, row)

    with pytest.raises(ApprovalError):
        _prepare(store, master, approved=(0,))
    assert not store.path("cv", "generated", "girona-1", "v1", "payload.json").exists()


def test_the_finding_names_the_retraction_that_withdrew_the_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """ "No per-use approval backs this line" would not tell the candidate their
    "forget that" was honoured — and the refusal is the one place they can see it."""
    row = _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    _retract_row(store, row)

    measured = measure_prepared(store, master, offer_id, version)
    assert measured["unapproved_episode_disclosures"] == 1
    assert "retracted the evidence" in measured["unapproved_episodes"][0]


def test_retracting_a_constraint_row_does_not_withdraw_an_episode_approval(
    store: ProfileStore, master: CVMaster
) -> None:
    """Only a story-bank row withdraws a story. Fail-closed guard."""
    log = EvidenceLog(store)
    constraint = log.append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="constraints",
        kind="constraint",
        text=WIN,
        source="conversation",
    )
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, constraint.id)

    record = record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    assert record.exists()


def test_retracting_a_reaction_row_withdraws_the_approval_naming_that_story(
    store: ProfileStore, master: CVMaster
) -> None:
    """A `reaction` row can be a story, so retracting one withdraws the approval.

    `reaction` sat in `_NEVER_A_STORY` beside `constraint`, excluded as "about an
    advert". That is the reasoning D-2 had already shown to fail for `statement`:
    the kind names *which step wrote the row*, not *whether the text is a story*.
    Step 5 captures reactions raw — "extract afterwards — never ask them to
    categorise their own reaction" — so a reaction is the candidate's own words
    in response to an advert, and answering one with the experience it brings to
    mind is the ordinary case, not a corner. Step 10 writes reactions after
    ranking, where that is likelier still.

    Fail-open if wrong in this direction: an exclusion can only shrink
    `withdrawn`, and a smaller `withdrawn` lets more sends through. §6.2 would
    rather refuse a live episode than send a withdrawn one — the same trade the
    module already makes for duplicate text.

    Found by the second reader on #305 (D-3).
    """
    log = EvidenceLog(store)
    reaction = log.append(
        recorded_at="2026-01-01T09:00:00+00:00",
        step="reactions",
        kind="reaction",
        text=WIN,
        source="conversation",
    )
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, reaction.id)

    with pytest.raises(ApprovalError):
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))


def test_a_retracted_row_withdraws_the_episode_its_provenance_names(store: ProfileStore) -> None:
    """The candidate polished the sentence on its way into the CV store.

    The log row and the store episode no longer share a word for word text, so a
    text match alone reads clean — fail-open. `Episode.provenance` is the join
    that already exists, and it is exact.
    """
    row = _episode_row(store, "Cut the nightly billing run right down. It took six hours.")
    built = CVMaster(
        skills=(Skill(name="PostgreSQL", level="strong"),),
        episodes=(
            Episode(kind="achievement", text=WIN, provenance=(ConversationTurn(evidence_id=row),)),
            Episode(kind="failure", text=FAILURE),
        ),
    )
    write_master(store, built)
    offer_id, version = _prepare(store, built, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, row)

    with pytest.raises(ApprovalError):
        record_sent(store, built, offer_id, version, confirms=payload_digest(payload))


# ---------------------------------------------------------------------------
# The second reader's cases (#305 audit). Each one is a single edit away from
# the sentence the approval names, and each one used to send.


def _bank(store: ProfileStore, *episodes: Episode) -> CVMaster:
    """A story bank of exactly these episodes, written to the store."""
    built = CVMaster(skills=(Skill(name="PostgreSQL", level="strong"),), episodes=episodes)
    write_master(store, built)
    return built


def _sends_after_retracting(store: ProfileStore, master: CVMaster, row_id: str) -> bool:
    """Approve episode 0, retract `row_id`, and report whether the send stood."""
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    _retract_row(store, row_id)
    try:
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))
    except ApprovalError:
        return False
    return True


def test_a_retracted_row_withdraws_an_approval_punctuated_differently(
    store: ProfileStore, master: CVMaster
) -> None:
    """The log row lost its full stop on the way into the story bank."""
    row = _episode_row(store, WIN.rstrip("."))
    assert not _sends_after_retracting(store, master, row)


def test_a_retracted_row_withdraws_an_approval_with_a_curly_apostrophe(
    store: ProfileStore,
) -> None:
    """One typographic apostrophe, and byte equality reads the story as a different one."""
    built = _bank(
        store, Episode(kind="achievement", text=OWNED), Episode(kind="failure", text=FAILURE)
    )
    row = _episode_row(store, OWNED.replace("'", "\u2019"))
    assert not _sends_after_retracting(store, built, row)


def test_a_retracted_row_withdraws_an_approval_spaced_differently(
    store: ProfileStore, master: CVMaster
) -> None:
    """A doubled space is not a different story."""
    row = _episode_row(store, WIN.replace("six hours", "six  hours"))
    assert not _sends_after_retracting(store, master, row)


def test_a_retracted_row_withdraws_an_approval_cased_differently(
    store: ProfileStore, master: CVMaster
) -> None:
    """Nor is a capital letter."""
    row = _episode_row(store, WIN.upper())
    assert not _sends_after_retracting(store, master, row)


def test_a_retracted_row_withdraws_an_accented_approval_in_either_normal_form(
    store: ProfileStore,
) -> None:
    """ES/EN/CA parity: a decomposed `ó` is the same letter as a composed one.

    `\\W+` splits NFD `delegación` into `delegacio` and a combining mark, so
    every eight-word shingle either side of it differs — which is why the
    shingle fix alone does not close this one and `_words` has to normalise.
    """
    composed = unicodedata.normalize("NFC", LLEIDA)
    built = _bank(
        store, Episode(kind="achievement", text=composed), Episode(kind="failure", text=FAILURE)
    )
    row = _episode_row(store, unicodedata.normalize("NFD", LLEIDA))
    assert not _sends_after_retracting(store, built, row)


def test_a_retracted_row_withdraws_the_polished_sentence_it_became(
    store: ProfileStore, master: CVMaster
) -> None:
    """Probe 7 with the provenance crutch removed.

    `Episode.provenance` defaults to `()` and is legitimately empty, so the
    text match — not the exact join — is what has to hold here.
    """
    row = _episode_row(store, RAW_UTTERANCE)
    assert not _sends_after_retracting(store, master, row)


def test_retracting_the_story_bank_row_withdraws_the_cv_store_episode(
    store: ProfileStore,
) -> None:
    """Two rows for one story, and the CV entry is provenanced to the wrong one.

    `add_conversation_entry` attaches its own intake row; the story-bank row is
    the one the candidate is talking about when they say to forget it.
    """
    bank = _episode_row(store, RAW_UTTERANCE)
    intake = EvidenceLog(store).append(
        recorded_at="2026-01-01T09:30:00+00:00",
        step="intake",
        kind="statement",
        text=WIN,
        source="conversation",
    )
    built = _bank(
        store,
        Episode(
            kind="achievement", text=WIN, provenance=(ConversationTurn(evidence_id=intake.id),)
        ),
        Episode(kind="failure", text=FAILURE),
    )
    assert not _sends_after_retracting(store, built, bank)


def test_a_retracted_statement_row_carrying_the_episode_withdraws_it(
    store: ProfileStore, master: CVMaster
) -> None:
    """`kind="statement"`, `step="intake"` — the shape `add_conversation_entry` writes.

    A whitelist of `episode` skipped the only kind the CV store puts an
    `Episode` behind, so the production path was the one path not joined.
    """
    row = (
        EvidenceLog(store)
        .append(
            recorded_at="2026-01-01T09:00:00+00:00",
            step="intake",
            kind="statement",
            text=WIN,
            source="conversation",
        )
        .id
    )
    assert not _sends_after_retracting(store, master, row)


def test_a_broken_retraction_chain_refuses_the_send(store: ProfileStore, master: CVMaster) -> None:
    """A log that does not settle must stop the send, not be read as no retraction."""
    _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    cycle = "\n".join(
        json.dumps(
            {
                "id": row_id,
                "recorded_at": "2026-01-02T09:00:00+00:00",
                "step": "any",
                "kind": "retraction",
                "text": "Forget that.",
                "source": "conversation",
                "retracts": retracts,
            }
        )
        for row_id, retracts in (("ev-000900", "ev-000901"), ("ev-000901", "ev-000900"))
    )
    evidence = store.path("profile", "evidence.jsonl")
    evidence.write_text(evidence.read_text(encoding="utf-8") + cycle + "\n", encoding="utf-8")

    with pytest.raises(ProfileError):
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))


def test_a_thrice_nested_retraction_still_withdraws(store: ProfileStore, master: CVMaster) -> None:
    """Retract, undo, undo the undo — the third level puts the row back under."""
    row = _episode_row(store, WIN)
    offer_id, version = _prepare(store, master, approved=(0,))
    payload = read_payload(store, offer_id, version)
    first = _retract_row(store, row)
    second = _retract_row(store, first, at="2026-01-03T09:00:00+00:00")
    _retract_row(store, second, at="2026-01-04T09:00:00+00:00")

    with pytest.raises(ApprovalError):
        record_sent(store, master, offer_id, version, confirms=payload_digest(payload))


def test_a_whitespace_only_retracted_row_withdraws_nothing(
    store: ProfileStore, master: CVMaster
) -> None:
    """The limit of the over-refusal: an empty sentence withdraws no approval."""
    row = _episode_row(store, "   ")
    assert _sends_after_retracting(store, master, row)


def test_the_retraction_probes_catch_every_planted_defect(tmp_path: Path) -> None:
    probed = probe_retracted_sends(tmp_path / "profiles")
    assert probed["retraction_probe_failures"] == []
    assert probed["retraction_probes"] >= MINIMUM_RETRACTION_PROBES
    assert probed["retracted_episodes_still_sendable"] == 0
    assert probed["retracted_episodes_evaluated"] >= MINIMUM_RETRACTED_APPROVALS_EVALUATED
    assert probed["gate_status"] == "measured"


def test_the_retraction_gate_report_names_the_two_failure_kinds_apart(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A red gate must say which way the boundary broke (#305 review).

    `retraction_probe_failures` carries the over-refusal cases — "a clean send
    was refused" — which is the *opposite* of a retracted episode getting out.
    One shared message over both lists told the reader the reverse of what had
    happened, on the failure that matters most.
    """
    failures = _retraction_report(
        {
            "retraction_probe_failures": ["a clean send was refused"],
            "retracted_episodes_sendable": ["ep-000001"],
            "retraction_probes": MINIMUM_RETRACTION_PROBES,
            "retracted_episodes_evaluated": MINIMUM_RETRACTED_APPROVALS_EVALUATED,
            "retracted_episodes_still_sendable": 1,
            "gate_status": "measured",
        }
    )
    reported = capsys.readouterr().err
    assert failures == 1  # the exit code, not the count
    assert reported.count("\u2717") == 2
    assert "the retraction boundary failed a planted case: a clean send was refused" in reported
    assert "a retracted episode was still sendable: ep-000001" in reported
    # The over-refusal line must not wear the fail-open wording.
    assert "still sendable: a clean send was refused" not in reported


def test_a_scratch_retraction_evidence_run_writes_nothing_into_the_repo(tmp_path: Path) -> None:
    """D-24's evidence must follow the path it was given, as T46's always has.

    `_main` read `argv[1]` for T46 and then called `write_retraction_evidence()`
    with no argument, so a run pointed at a scratch directory still rewrote the
    committed `status/evidence/D-24.json` (#305 review).
    """
    committed = DEFAULT_D24_EVIDENCE_PATH
    before = (committed.read_bytes(), committed.stat().st_mtime_ns) if committed.exists() else None

    assert _main(["integral.approval", str(tmp_path / "T46.json")]) == 0

    after = (committed.read_bytes(), committed.stat().st_mtime_ns) if committed.exists() else None
    assert after == before, "a scratch run rewrote the committed status/evidence/D-24.json"
    assert (tmp_path / "T46.json").exists()
    scratch = json.loads((tmp_path / "D-24.json").read_text(encoding="utf-8"))
    assert scratch["gate_status"] == "measured"
