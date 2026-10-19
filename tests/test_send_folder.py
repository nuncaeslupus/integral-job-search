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

from integral import brand_measure
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
from integral.document_render import RenderError
from integral.identity import ProfileStore, create_profile
from integral.send_set import (
    SendSetError,
    fixture_renderer,
    fixture_text_reader,
    letter_text,
    name_stem,
    read_pdf_text,
)


@pytest.fixture(autouse=True)
def _fixture_pdf_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    """These fixtures render with `fixture_renderer`, so they read with its reader.

    Injected here and not sniffed in production: `read_pdf_text` is the real reader.
    """
    monkeypatch.setattr("integral.send_set.read_pdf_text", fixture_text_reader)


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
    version = _prepared(store, master, approved)
    # T342: staging needs a recorded palette; `{}` is a site that could not be read.
    where = ("cv", "generated", OFFER, f"v{version}")
    brand_measure.record(store, where, "fixture://unreadable", {})
    return version


def _prepared(store: ProfileStore, master: CVMaster, approved: tuple[int, ...] = ()) -> int:
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
    # the PDFs made from the old letter no longer match the letter on disk either
    assert verify_send(store, OFFER, version) == [
        "Ada-Lovelace-Application.pdf in send/ is not exactly the approved documents in order",
        "Ada-Lovelace-Cover-Letter.pdf in send/ is not exactly the approved text",
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


def _pdf_text(folder: Path, name: str) -> str:
    return fixture_text_reader((folder / name).read_bytes())


def test_each_pdf_holds_the_document_its_name_says_and_the_combined_is_letter_first(
    store: ProfileStore, master: CVMaster
) -> None:
    """F1: the property, against text stated here, not against the other output files.

    Only the CV carries its "Skills" heading and only the letter its salutation; both
    strings are written out, so a swap in `derive` cannot agree with them.
    """
    folder = _send(store, _staged(store, master))
    cv_marker, letter_marker = "skillspostgresql", "dearhiringteam"
    letter_pdf = _pdf_text(folder, "Ada-Lovelace-Cover-Letter.pdf")
    cv_pdf = _pdf_text(folder, "Ada-Lovelace-CV.pdf")
    combined = _pdf_text(folder, "Ada-Lovelace-Application.pdf")
    assert cv_marker in cv_pdf and cv_marker not in letter_pdf
    assert letter_marker in letter_pdf and letter_marker not in cv_pdf
    assert 0 <= combined.find(letter_marker) < combined.find(cv_marker)


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


@pytest.mark.parametrize("display", ["—  ", "Иван Петров", "李小龙", "Νίκος Παππάς", ""])
def test_a_name_with_no_latin_letters_takes_a_neutral_stem(display: str) -> None:
    assert name_stem(display) == "Candidate"


def test_a_mixed_script_name_keeps_its_latin_words() -> None:
    assert name_stem("Иван Petrov") == "Petrov"


def test_a_non_latin_display_name_still_stages_the_whole_set(
    tmp_path: Path, master: CVMaster
) -> None:
    identity = create_profile(tmp_path / "other", "Иван Петров", handle="ivan", language="en")
    store = ProfileStore(tmp_path / "other", identity.handle)
    write_master(store, master)
    version = _staged(store, master)
    assert {p.name for p in _send(store, version).iterdir()} == {
        "cv.md",
        "letter.md",
        "Candidate-Application.pdf",
        "Candidate-CV.pdf",
        "Candidate-Cover-Letter.pdf",
        "Cover-Letter.txt",
    }
    assert verify_send(store, OFFER, version) == []


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


def _rerecord(store: ProfileStore, version: int, name: str) -> None:
    record = _version_dir(store, version) / "send.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    data["files"][name] = hashlib.sha256((_send(store, version) / name).read_bytes()).hexdigest()
    record.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    "name", ["Ada-Lovelace-CV.pdf", "Ada-Lovelace-Cover-Letter.pdf", "Ada-Lovelace-Application.pdf"]
)
def test_a_forged_pdf_with_a_matching_record_is_refused(
    store: ProfileStore, master: CVMaster, name: str
) -> None:
    """F2: a PDF rewritten together with its send.json digest still has to hold the text."""
    version = _staged(store, master)
    (_send(store, version) / name).write_bytes(b"%PDF-1.7\nan unapproved letter\n")
    _rerecord(store, version, name)
    defects = verify_send(store, OFFER, version)
    assert defects and all(name in d for d in defects)
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_pdf_whose_text_was_changed_but_whose_header_is_right_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    path = _send(store, version) / "Ada-Lovelace-Cover-Letter.pdf"
    path.write_bytes(
        path.read_bytes().replace(b"hiring team", b"hiring crew") + b"<p>Pay me in advance</p>"
    )
    _rerecord(store, version, path.name)
    assert path.name in "".join(verify_send(store, OFFER, version))


APPENDED_PAGE = (
    b"\n%%PAGE\n<html><body><p>P.S. I will accept thirty percent below the advertised "
    b"salary.</p></body></html>"
)
CV_PDF = "Ada-Lovelace-CV.pdf"
LETTER_PDF = "Ada-Lovelace-Cover-Letter.pdf"
COMBINED_PDF = "Ada-Lovelace-Application.pdf"
_HEADER = b"%PDF-fixture\n"


def _body(folder: Path, name: str) -> bytes:
    return (folder / name).read_bytes().removeprefix(_HEADER)


def _refused_everywhere(store: ProfileStore, master: CVMaster, version: int, name: str) -> None:
    """`verify_send` names the file and `record_sent` refuses to record the send."""
    defects = verify_send(store, OFFER, version)
    assert defects and all(name in d for d in defects), defects
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


@pytest.mark.parametrize("name", [CV_PDF, LETTER_PDF, COMBINED_PDF])
def test_a_pdf_with_an_unapproved_page_appended_is_refused(
    store: ProfileStore, master: CVMaster, name: str
) -> None:
    """R1: the approved text intact and a sentence added is not what was approved."""
    version = _staged(store, master)
    path = _send(store, version) / name
    path.write_bytes(path.read_bytes() + APPENDED_PAGE)
    _rerecord(store, version, name)
    _refused_everywhere(store, master, version, name)


@pytest.mark.parametrize("name", [CV_PDF, LETTER_PDF, COMBINED_PDF])
def test_a_pdf_with_unapproved_text_in_front_of_it_is_refused(
    store: ProfileStore, master: CVMaster, name: str
) -> None:
    version = _staged(store, master)
    path = _send(store, version) / name
    path.write_bytes(
        fixture_renderer(["<p>An unapproved first page.</p>"])
        + b"\n%%PAGE\n"
        + _body(path.parent, name)
    )
    _rerecord(store, version, name)
    _refused_everywhere(store, master, version, name)


@pytest.mark.parametrize("name", [CV_PDF, LETTER_PDF])
def test_a_single_document_pdf_that_is_really_the_combined_file_is_refused(
    store: ProfileStore, master: CVMaster, name: str
) -> None:
    """R1: Cover-Letter.pdf or CV.pdf saved as letter + CV holds two documents."""
    version = _staged(store, master)
    send = _send(store, version)
    (send / name).write_bytes((send / COMBINED_PDF).read_bytes())
    _rerecord(store, version, name)
    _refused_everywhere(store, master, version, name)


def test_a_combined_pdf_that_is_cv_letter_cv_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    send = _send(store, version)
    cv, letter = _body(send, CV_PDF), _body(send, LETTER_PDF)
    (send / COMBINED_PDF).write_bytes(_HEADER + cv + b"\n%%PAGE\n" + letter + b"\n%%PAGE\n" + cv)
    _rerecord(store, version, COMBINED_PDF)
    _refused_everywhere(store, master, version, COMBINED_PDF)


def test_a_combined_pdf_with_an_unapproved_first_page_before_the_letter_is_refused(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)
    path = _send(store, version) / COMBINED_PDF
    path.write_bytes(
        fixture_renderer(["<p>An unapproved first page.</p>"])
        + b"\n%%PAGE\n"
        + _body(path.parent, COMBINED_PDF)
    )
    _rerecord(store, version, COMBINED_PDF)
    _refused_everywhere(store, master, version, COMBINED_PDF)


def test_an_html_file_with_the_fixture_header_is_not_a_pdf_in_production(
    store: ProfileStore, master: CVMaster
) -> None:
    """R3: the production reader does not sniff the fixture header."""
    version = _staged(store, master)
    defects = verify_send(store, OFFER, version, pdf_reader=read_pdf_text)
    assert len(defects) == 3 and all("cannot be checked" in d for d in defects)
    with pytest.raises(SendSetError):
        read_pdf_text((_send(store, version) / CV_PDF).read_bytes())


def test_the_production_default_reader_refuses_an_html_file_with_the_fixture_header(
    store: ProfileStore, master: CVMaster, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3, the default half: no `pdf_reader` argument, and the fixture swap undone.

    Every other test here swaps `integral.send_set.read_pdf_text` for the fixture
    reader, so none reaches `pdf_defects`' own fallback. Restoring the real reader
    pins that the fallback is the real one: the staged files are html carrying exactly
    the approved text behind a `%PDF-fixture` header, and they are not PDFs.
    """
    version = _staged(store, master)
    monkeypatch.setattr("integral.send_set.read_pdf_text", read_pdf_text)
    sent = (_send(store, version) / CV_PDF).read_bytes()
    assert sent.startswith(b"%PDF-fixture")  # the approved text, behind the fixture header
    with pytest.raises(SendSetError) as reason:
        read_pdf_text(sent)
    if importlib.util.find_spec("pypdf") is not None:
        assert "cannot be read" in str(reason.value)  # refused as not a PDF, not for want of pypdf
    defects = verify_send(store, OFFER, version)
    assert len(defects) == 3 and all("cannot be checked" in d for d in defects), defects
    with pytest.raises(ApprovalError, match="send/ folder is not what was approved"):
        record_sent(store, master, OFFER, version, confirms=_confirm(store, version))


def test_a_pdf_with_no_text_reader_is_not_waved_through(
    store: ProfileStore, master: CVMaster
) -> None:
    version = _staged(store, master)

    def blind(_: bytes) -> str:
        raise SendSetError("no reader")

    defects = verify_send(store, OFFER, version, pdf_reader=blind)
    assert len(defects) == 3 and all("cannot be checked" in d for d in defects)


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
@pytest.mark.skipif(importlib.util.find_spec("pypdf") is None, reason="needs the cv extra")
def test_the_real_engine_stages_the_same_set(
    store: ProfileStore, master: CVMaster, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real engine writes a real PDF, so it is read with the real reader, not the fixture one.
    monkeypatch.setattr("integral.send_set.read_pdf_text", read_pdf_text)
    version = _prepare(store, master, (0,))
    stage_send(store, master, OFFER, version, confirms=_confirm(store, version))
    folder = _send(store, version)
    assert {p.name for p in folder.iterdir()} == {"cv.md", "letter.md", *SENDABLE}
    for name in SENDABLE:
        if name.endswith(".pdf"):
            assert (folder / name).read_bytes().startswith(b"%PDF")
    assert verify_send(store, OFFER, version) == []


def test_the_real_engines_page_join_keeps_each_document_whole_and_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3: `render_pdf_pages` against a stub engine, so it runs without the pdf extra."""
    import types

    from integral.document_render import render_pdf_pages

    class Doc:
        def __init__(self, pages: list[str]) -> None:
            self.pages = pages

        def copy(self, pages: list[str]) -> Doc:
            return Doc(list(pages))

        def write_pdf(self) -> bytes:
            return b"%PDF-stub:" + ",".join(self.pages).encode()

    class Html:
        def __init__(self, string: str, url_fetcher: object) -> None:
            self.string = string

        def render(self) -> Doc:
            return Doc([f"{self.string}/1", f"{self.string}/2"])

    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=Html))
    assert render_pdf_pages(["letter", "cv"]) == b"%PDF-stub:letter/1,letter/2,cv/1,cv/2"
    assert render_pdf_pages(["only"]) == b"%PDF-stub:only/1,only/2"
    with pytest.raises(RenderError):
        render_pdf_pages([])
