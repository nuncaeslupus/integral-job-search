"""T212 — `send/` is step 11's output, and what is in it is what was approved (T46).

Every claim here is pinned by reverting the one line that makes it true.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from integral.approval import (
    ApprovalError,
    PersonalDetails,
    payload_digest,
    prepare,
    read_payload,
    record_sent,
    stage_send,
    verify_send,
)
from integral.cv_store import CVMaster, Episode, Experience, Skill, write_master
from integral.identity import ProfileStore, create_profile
from integral.send_set import SendSetError, fixture_renderer, letter_text, name_stem

OFFER = "girona-1"
SENDABLE = [
    "Ada-Lovelace-Application.pdf",
    "Ada-Lovelace-CV.pdf",
    "Ada-Lovelace-Cover-Letter.pdf",
    "Cover-Letter.txt",
]
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
        episodes=(Episode(kind="achievement", text=WIN), Episode(kind="failure", text=FAILURE)),
    )
    write_master(store, built)
    return built


def _prepare(store: ProfileStore, master: CVMaster, approved: tuple[int, ...] = ()) -> int:
    return prepare(
        store,
        master,
        offer_id=OFFER,
        advert=ADVERT,
        recipient="hiring team, Girona",
        details=DETAILS,
        asks=("PostgreSQL",),
        approved_episodes=approved,
    ).version


def _version_dir(store: ProfileStore, version: int) -> Path:
    return store.path("cv", "generated", OFFER, f"v{version}")


def _confirm(store: ProfileStore, version: int) -> str:
    return payload_digest(read_payload(store, OFFER, version))


def _send(store: ProfileStore, version: int) -> Path:
    return _version_dir(store, version) / "send"


def _staged(store: ProfileStore, master: CVMaster) -> int:
    version = _prepare(store, master, (0,))
    stage_send(
        store, master, OFFER, version, confirms=_confirm(store, version), renderer=fixture_renderer
    )
    return version


def test_send_holds_exactly_the_approved_files_byte_for_byte(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    folder = _send(store, version)
    assert sorted(p.name for p in folder.iterdir()) == sorted(["cv.md", "letter.md", *SENDABLE])
    for name in ("cv.md", "letter.md"):
        assert (folder / name).read_bytes() == (folder.parent / name).read_bytes()
    assert verify_send(store, OFFER, version) == []
    # the folder holds only files that go: the record lives beside it, not in it
    assert (folder.parent / "send.json").is_file()


def test_staging_needs_the_digest_of_this_payload(store: ProfileStore, master: CVMaster) -> None:
    version = _prepare(store, master, (0,))
    with pytest.raises(ApprovalError, match="standing permission"):
        stage_send(
            store, master, OFFER, version, confirms="yes, send anything", renderer=fixture_renderer
        )
    assert not _send(store, version).exists()


def test_staging_refuses_a_document_edited_to_carry_an_unapproved_story(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _prepare(store, master)
    confirm = _confirm(store, version)
    letter = _version_dir(store, version) / "letter.md"
    letter.write_text(letter.read_text(encoding="utf-8") + f"\n{FAILURE}\n", encoding="utf-8")
    with pytest.raises(ApprovalError, match="nothing here is sendable"):
        stage_send(store, master, OFFER, version, confirms=confirm, renderer=fixture_renderer)
    assert not _send(store, version).exists()


def test_staging_twice_over_an_intact_folder_is_a_no_op(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    before = {p.name: p.read_bytes() for p in _send(store, version).iterdir()}
    stage_send(
        store, master, OFFER, version, confirms=_confirm(store, version), renderer=fixture_renderer
    )
    assert {p.name: p.read_bytes() for p in _send(store, version).iterdir()} == before


@pytest.mark.parametrize("tamper", ["edit", "add", "remove", "symlink", "subdir"])
def test_a_send_folder_that_is_not_what_was_approved_blocks_the_record(
    store: ProfileStore, master: CVMaster, tamper: str
) -> None:
    version = _staged(store, master)
    folder = _send(store, version)
    if tamper == "edit":
        (folder / "letter.md").write_text("something else entirely\n", encoding="utf-8")
    elif tamper == "add":
        (folder / "notes.md").write_text("an unapproved extra\n", encoding="utf-8")
    elif tamper == "remove":
        (folder / "cv.md").unlink()
    elif tamper == "symlink":
        (folder / "cv.md").unlink()
        (folder / "cv.md").symlink_to(folder.parent / "cv.md")  # identical bytes, still a link
    else:
        (folder / "extra").mkdir()
    assert verify_send(store, OFFER, version)
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))
    with pytest.raises(ApprovalError, match="not overwritten"):
        stage_send(
            store,
            master,
            OFFER,
            version,
            confirms=_confirm(store, version),
            renderer=fixture_renderer,
        )
    assert not store.path("applications").exists()


def test_a_send_folder_nobody_staged_is_refused(store: ProfileStore, master: CVMaster) -> None:
    version = _prepare(store, master)
    folder = _send(store, version)
    folder.mkdir()
    (folder / "letter.md").write_text("hand-collected\n", encoding="utf-8")
    assert verify_send(store, OFFER, version) == [
        "send/ exists but was not staged by stage_send, so nothing approved it"
    ]
    with pytest.raises(ApprovalError, match="not staged by stage_send"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_record_naming_another_payload_is_refused(store: ProfileStore, master: CVMaster) -> None:
    version = _staged(store, master)
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["confirmed_digest"] = "0" * 64
    record.write_text(json.dumps(data), encoding="utf-8")
    assert any("different payload" in d for d in verify_send(store, OFFER, version))


def test_an_unreadable_record_is_a_defect_not_a_crash(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    (_version_dir(store, version) / "send.json").write_text("{not json", encoding="utf-8")
    assert verify_send(store, OFFER, version) == [
        "send.json is unreadable, so send/ cannot be shown to be what was approved"
    ]


def test_an_intact_send_folder_lets_the_record_through(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    record_sent(store, master, OFFER, version, confirms=_confirm(store, version))
    assert store.path("applications", OFFER, f"v{version}.json").is_file()


def test_a_version_never_staged_still_records_as_before(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _prepare(store, master, (0,))
    assert verify_send(store, OFFER, version) == []
    record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_tampered_file_with_a_rewritten_record_is_still_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    """The record shares a tree with `send/`, so it cannot vouch for the files alone."""
    version = _staged(store, master)
    letter = _send(store, version) / "letter.md"
    letter.write_text(letter.read_text(encoding="utf-8") + f"\n{FAILURE}\n", encoding="utf-8")
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"]["letter.md"] = hashlib.sha256(letter.read_bytes()).hexdigest()
    record.write_text(json.dumps(data), encoding="utf-8")
    assert verify_send(store, OFFER, version) == [
        "letter.md in send/ differs from what was approved"
    ]
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_send_folder_that_is_a_link_to_another_folder_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    folder = _send(store, version)
    other = _version_dir(store, version) / "elsewhere"
    folder.rename(other)
    folder.symlink_to(other, target_is_directory=True)  # same bytes, still a link
    assert verify_send(store, OFFER, version) == ["send/ is missing or is not a real directory"]
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_document_edited_after_staging_in_both_places_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    """The staged hash is the reference the version-dir comparison cannot be."""
    version = _staged(store, master)
    for where in (_send(store, version), _version_dir(store, version)):
        letter = where / "letter.md"
        letter.write_text(letter.read_text(encoding="utf-8") + "\nBest wishes.\n", encoding="utf-8")
    assert verify_send(store, OFFER, version) == [
        "Cover-Letter.txt in send/ differs from what was approved",
        "letter.md in send/ differs from what was approved",
    ]


# -- T338: the sendable set --------------------------------------------------------


def test_the_folder_names_the_pdfs_for_sending_and_never_cv_pdf(
    store: ProfileStore, master: CVMaster
) -> None:
    folder = _send(store, _staged(store, master))
    names = {p.name for p in folder.iterdir()}
    assert set(SENDABLE) <= names
    assert not {n for n in names if n.lower() in ("cv.pdf", "letter.pdf", "carta.pdf")}


def test_the_combined_pdf_puts_the_letter_first(store: ProfileStore, master: CVMaster) -> None:
    folder = _send(store, _staged(store, master))
    combined = (folder / "Ada-Lovelace-Application.pdf").read_bytes()
    letter = (folder / "Ada-Lovelace-Cover-Letter.pdf").read_bytes().removeprefix(b"%PDF-fixture\n")
    cv = (folder / "Ada-Lovelace-CV.pdf").read_bytes().removeprefix(b"%PDF-fixture\n")
    assert letter != cv
    assert combined == b"%PDF-fixture\n" + letter + b"\n%%PAGE\n" + cv


def test_the_plain_text_letter_is_the_letter_without_markup(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    text = (_send(store, version) / "Cover-Letter.txt").read_text(encoding="utf-8")
    source = (_version_dir(store, version) / "letter.md").read_text(encoding="utf-8")
    assert text == letter_text(source)
    assert text.strip()
    assert "**" not in text and not any(line.startswith("#") for line in text.splitlines())


def test_letter_text_strips_markers_and_keeps_wording() -> None:
    markdown = "# Dear team\n\nI **led** the move.\n\n- one\n* two\n"
    assert letter_text(markdown) == "Dear team\n\nI led the move.\n\n- one\n- two\n"


@pytest.mark.parametrize(
    ("display", "stem"),
    [
        ("Ada Lovelace", "Ada-Lovelace"),
        ("Núria Ferrer i Puig", "Nuria-Puig"),
        ("Cher", "Cher"),
        ("  José   María  ", "Jose-Maria"),
    ],
)
def test_the_file_name_comes_from_the_display_name(display: str, stem: str) -> None:
    assert name_stem(display) == stem


def test_a_name_with_no_usable_letters_refuses() -> None:
    with pytest.raises(SendSetError):
        name_stem("—  ")


@pytest.mark.parametrize("target", [*SENDABLE])
@pytest.mark.parametrize("tamper", ["edit", "remove"])
def test_a_tampered_derived_file_is_refused(
    store: ProfileStore, master: CVMaster, target: str, tamper: str
) -> None:
    version = _staged(store, master)
    path = _send(store, version) / target
    if tamper == "edit":
        path.write_bytes(path.read_bytes() + b"\nan unapproved sentence\n")
    else:
        path.unlink()
    assert verify_send(store, OFFER, version)
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_derived_file_rewritten_with_its_record_is_still_refused_when_derivable(
    store: ProfileStore, master: CVMaster
) -> None:
    """The text file has an independent reference (the approved letter); a record cannot vouch."""
    version = _staged(store, master)
    path = _send(store, version) / "Cover-Letter.txt"
    path.write_text("a different letter\n", encoding="utf-8")
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"]["Cover-Letter.txt"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record.write_text(json.dumps(data), encoding="utf-8")
    assert verify_send(store, OFFER, version) == [
        "Cover-Letter.txt in send/ differs from what was approved"
    ]


def test_a_pdf_swapped_for_something_else_is_refused_even_with_a_matching_record(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    path = _send(store, version) / "Ada-Lovelace-CV.pdf"
    path.write_text("not a pdf\n", encoding="utf-8")
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"]["Ada-Lovelace-CV.pdf"] = hashlib.sha256(path.read_bytes()).hexdigest()
    record.write_text(json.dumps(data), encoding="utf-8")
    assert verify_send(store, OFFER, version) == ["Ada-Lovelace-CV.pdf in send/ is not a PDF"]


def test_a_record_that_omits_the_sendable_set_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    del data["files"]["Cover-Letter.txt"]
    (_send(store, version) / "Cover-Letter.txt").unlink()
    record.write_text(json.dumps(data), encoding="utf-8")
    assert any("does not list exactly" in d for d in verify_send(store, OFFER, version))


def test_no_pdf_engine_refuses_before_anything_is_staged(
    store: ProfileStore, master: CVMaster, monkeypatch: pytest.MonkeyPatch
) -> None:
    version = _prepare(store, master, (0,))
    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(ApprovalError, match="nothing was staged"):
        stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    assert not _send(store, version).exists()
    assert not (_version_dir(store, version) / "send.json").exists()


@pytest.mark.skipif(importlib.util.find_spec("weasyprint") is None, reason="needs the pdf extra")
def test_the_real_engine_stages_the_same_set(store: ProfileStore, master: CVMaster) -> None:
    version = _prepare(store, master, (0,))
    stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    folder = _send(store, version)
    assert {p.name for p in folder.iterdir()} == {"cv.md", "letter.md", *SENDABLE}
    for name in SENDABLE:
        if name.endswith(".pdf"):
            assert (folder / name).read_bytes().startswith(b"%PDF")
    assert verify_send(store, OFFER, version) == []
