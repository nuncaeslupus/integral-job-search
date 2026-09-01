"""T97 — step 1 could not read the CV, and carried on.

The note that opened the task was the candidate's: *"I see you had some
problems with reading the CV or knowing what to do with it."* Two failures
sit inside that one sentence and they need different fixes, so they are
tested apart here:

* **reading it** — the file arriving as text at all. `import_document` has
  always returned a full account of that (`unsupported`, `unavailable`,
  `corrupt`, `empty`), and the account died with the call that produced it.
* **knowing what to do with it** — which fields the document was expected to
  yield. A CV that imports cleanly and produces no contact address and no
  year anywhere was read badly, and nothing said so either.

A partial read is acceptable. A partial read that reports success is what
leaves the candidate answering questions the CV already answered, so the
behaviour under test throughout is whether the failure is *said*, never
whether it is avoided.

The last test drives the committed step-1 checkpoint itself rather than a
copy of its decision. The seam T97 is about is precisely the one between "the
library knows" and "the thing that certifies the step asks" — a test that
re-implemented the fold would pass over a checkpoint that had never been
wired to it, which is this defect with a green tick beside it.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest

from integral.cv_store import (
    EXPECTED_DOCUMENT_FIELDS,
    IMPORT_LOG_PARTS,
    MINIMUM_READ_CHECKS,
    _build_minimal_docx,
    _pypdf_forced_missing,
    acknowledge_read_problems,
    import_document,
    probe_read_reporting,
    read_import_log,
    unextracted_fields,
    unreported_read_problems,
)
from integral.identity import ProfileStore, create_profile
from integral.step_gates import checkpoint_exit

_REPO_ROOT = Path(__file__).resolve().parents[1]
_STEP_1_CHECKPOINT = (
    _REPO_ROOT / ".claude" / "skills" / "step-01-intake" / "scripts" / "run_checkpoint.py"
)

# A CV that reads properly: an address to reply to and a year. Both of
# `EXPECTED_DOCUMENT_FIELDS`, so this is the fixture every "and the clean case
# stays clean" assertion leans on.
_READABLE_CV = (
    "Núria Bosch — Data Engineer",
    "nuria.bosch@example.invalid",
    "2019-2024, Barcelona: built the ingestion layer three teams now depend on.",
)


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    identity = create_profile(tmp_path / "profiles", "T97 Probe", handle="t97-probe")
    return ProfileStore(tmp_path / "profiles", identity.handle)


def _docx(tmp_path: Path, name: str, paragraphs: tuple[str, ...]) -> Path:
    path = tmp_path / name
    path.write_bytes(_build_minimal_docx(list(paragraphs)))
    return path


# --- reading it -------------------------------------------------------------


def test_an_unreadable_cv_is_reported_not_skipped(store: ProfileStore, tmp_path: Path) -> None:
    """Every way a document can fail to arrive as text leaves a record.

    All four are driven, not one standing in for the rest: they take four
    different exits out of `import_document`, and the defect was that an exit
    left nothing behind — so an exit that is not exercised is an exit that
    could still be silent.
    """
    unsupported = tmp_path / "cv.txt"
    unsupported.write_text("a CV, in a format nothing here reads", encoding="utf-8")

    corrupt = tmp_path / "cv.docx"
    corrupt.write_bytes(b"PK\x03\x04 and then nothing that is a zip")

    empty = _docx(tmp_path, "blank.docx", ("", "   ", ""))

    unavailable = tmp_path / "cv.pdf"
    unavailable.write_bytes(b"%PDF-1.4\n")

    assert import_document(store, unsupported).status == "unsupported"
    assert import_document(store, corrupt).status == "corrupt"
    assert import_document(store, empty).status == "empty"
    with _pypdf_forced_missing():
        assert import_document(store, unavailable).status == "unavailable"

    log = read_import_log(store)
    assert [record["status"] for record in log] == [
        "unsupported",
        "corrupt",
        "empty",
        "unavailable",
    ]
    assert [record["file"] for record in log] == ["cv.txt", "cv.docx", "blank.docx", "cv.pdf"]

    problems = unreported_read_problems(store)
    assert len(problems) == 4, problems
    # Each names its own file. A count that was right while every line said
    # the same thing would tell the candidate a document failed without
    # telling them which one.
    for name in ("cv.txt", "cv.docx", "blank.docx", "cv.pdf"):
        assert any(line.startswith(f"{name}: ") for line in problems), (name, problems)


def test_a_clean_read_leaves_nothing_to_report(store: ProfileStore, tmp_path: Path) -> None:
    """The complement, and the reason the gate is worth having: a CV that read
    properly must not manufacture a problem, or the check becomes noise the
    session learns to acknowledge without reading."""
    result = import_document(store, _docx(tmp_path, "cv.docx", _READABLE_CV))

    assert result.status == "imported"
    assert result.unextracted == ()
    assert result.complete
    assert result.problem() is None
    assert unreported_read_problems(store) == []
    # Still logged. The log is the record of what happened, not a list of
    # complaints — a successful import that left no trace would make "no
    # problems" and "nobody tried" the same reading.
    assert len(read_import_log(store)) == 1


# --- knowing what to do with it ---------------------------------------------


def test_a_partially_read_cv_names_what_it_could_not_extract(
    store: ProfileStore, tmp_path: Path
) -> None:
    """A document that imports and yields less than it should says which fields.

    It is still an import: blocks land, spans are citable, the original is
    kept. Demoting it to a failure would force the caller to choose between
    discarding real content and staying quiet about what is missing, and the
    whole point of the task is that neither is necessary.
    """
    partial = _docx(
        tmp_path,
        "scanned.docx",
        ("Núria Bosch — Data Engineer", "Built the ingestion layer three teams depend on."),
    )
    result = import_document(store, partial)

    assert result.status == "imported"
    assert result.blocks_added == 2
    assert result.doc_id is not None
    assert not result.complete
    assert set(result.unextracted) == set(EXPECTED_DOCUMENT_FIELDS)

    problem = result.problem()
    assert problem is not None
    for field in EXPECTED_DOCUMENT_FIELDS:
        assert field in problem, (field, problem)
    assert unreported_read_problems(store) == [f"scanned.docx: {problem}"]


def test_one_missing_field_is_named_and_the_other_is_not(tmp_path: Path) -> None:
    """The fields are reported individually, not as one all-or-nothing verdict.

    `unextracted_fields` is the unit under the two tests above; driving it
    directly is what stops "names what it could not extract" from being
    satisfied by a message that always lists everything.
    """
    assert unextracted_fields("nuria.bosch@example.invalid, Barcelona") == ("dated_experience",)
    assert unextracted_fields("Barcelona, 2019-2024") == ("contact_email",)
    assert unextracted_fields("\n".join(_READABLE_CV)) == ()


def test_the_profile_records_which_fields_came_from_the_document(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The log is per-document and cumulative, so a later upload cannot erase
    what an earlier one did or did not yield.

    This is the half of the note about *knowing what to do with it*: after two
    uploads the profile can say, for each document, which expected fields that
    read produced — which is what a session needs to avoid asking the
    candidate for something one of their own files already gave.
    """
    import_document(store, _docx(tmp_path, "old.docx", ("Núria Bosch", "Data Engineer")))
    import_document(store, _docx(tmp_path, "new.docx", _READABLE_CV))

    log = read_import_log(store)
    assert [record["file"] for record in log] == ["old.docx", "new.docx"]
    assert set(log[0]["unextracted"]) == set(EXPECTED_DOCUMENT_FIELDS)
    assert log[1]["unextracted"] == []
    assert log[1]["doc_id"] is not None and log[1]["doc_id"] != log[0]["doc_id"]

    # A read that worked does not retire a read that did not. The candidate
    # still handed over a document this project could not use, and deciding on
    # their behalf that it stopped mattering is the same silence, politer.
    assert len(unreported_read_problems(store)) == 1
    assert unreported_read_problems(store)[0].startswith("old.docx: ")


def test_acknowledging_clears_the_problems_and_keeps_the_record(
    store: ProfileStore, tmp_path: Path
) -> None:
    """Saying it is what clears it — and the log still says it happened.

    Without this the first unreadable upload would strand the candidate on
    step 1 forever, which is a worse failure than the one being fixed: a
    document this project genuinely cannot read is a fact to state, not a
    reason to refuse to continue.
    """
    import_document(store, _docx(tmp_path, "old.docx", ("Núria Bosch",)))
    outstanding = acknowledge_read_problems(store)

    assert len(outstanding) == 1
    assert unreported_read_problems(store) == []
    assert acknowledge_read_problems(store) == []
    assert [record["reported"] for record in read_import_log(store)] == [True]
    assert read_import_log(store)[0]["problem"] is not None


def test_a_corrupt_log_reads_as_empty_rather_than_taking_intake_down(
    store: ProfileStore,
) -> None:
    """A caller reaching for this is usually already mid-failure."""
    store.path(*IMPORT_LOG_PARTS).parent.mkdir(parents=True, exist_ok=True)
    store.path(*IMPORT_LOG_PARTS).write_text("{ not json", encoding="utf-8")

    assert read_import_log(store) == []
    assert unreported_read_problems(store) == []


# --- and what it costs the step ---------------------------------------------


def _drive_step_1_checkpoint(root: Path, handle: str) -> dict[str, Any]:
    """The committed step-1 checkpoint's own `checkpoint`, over a real store."""
    spec = importlib.util.spec_from_file_location("_t97_step_1_checkpoint", _STEP_1_CHECKPOINT)
    assert spec is not None and spec.loader is not None
    module: Any = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
            return dict(module.checkpoint(root, handle))
    finally:
        sys.modules.pop(spec.name, None)


def test_a_failed_read_does_not_certify_step_1(store: ProfileStore, tmp_path: Path) -> None:
    """The defect, end to end, through the script that actually decides.

    `cv_master` is present the moment `cv/master.json` exists, and it exists
    whether the document was read, half-read or refused — so the first
    assertion here is the *baseline*: with the artefacts in place and nothing
    outstanding, this step reports covered. That is correct, and it is exactly
    what made the failure invisible. The second assertion is the fix.
    """
    import_document(store, _docx(tmp_path, "cv.docx", _READABLE_CV))
    acknowledge_read_problems(store)

    baseline = _drive_step_1_checkpoint(store.root, store.handle)
    assert baseline["artefacts_present"] is True
    assert baseline["cv_read_problems"] == []
    assert baseline["coverage_met"] is True
    assert checkpoint_exit(baseline) == 0

    corrupt = tmp_path / "second.docx"
    corrupt.write_bytes(b"PK\x03\x04 not a zip")
    import_document(store, corrupt)

    after = _drive_step_1_checkpoint(store.root, store.handle)
    assert after["artefacts_present"] is True, "the artefact is still there — that is the trap"
    assert len(after["cv_read_problems"]) == 1
    assert after["cv_read_problems"][0].startswith("second.docx: ")
    assert after["coverage_met"] is False
    assert checkpoint_exit(after) == 1

    # And saying it releases the step, rather than the candidate being stuck
    # behind a document nothing can read.
    acknowledge_read_problems(store)
    assert _drive_step_1_checkpoint(store.root, store.handle)["coverage_met"] is True


# --- the gate ---------------------------------------------------------------


def test_the_probe_reports_no_unreported_read_failures(tmp_path: Path) -> None:
    """T97's own measurement, and the floor under it."""
    measured = probe_read_reporting(tmp_path / "profiles")

    assert measured["failures"] == []
    assert measured["unreported_cv_read_failures"] == 0
    assert measured["read_failures_produced"] >= 5
    assert measured["checks_run"] >= MINIMUM_READ_CHECKS


def test_the_probe_counts_a_failure_nothing_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean zero has to be capable of being non-zero.

    Blind the reporter and the metric must rise — otherwise the gate is
    measuring that the probe ran, which is the failure mode this repository
    keeps catching in its own gates.
    """
    import integral.cv_store as module

    monkeypatch.setattr(module, "unreported_read_problems", lambda _store: [])
    measured = module.probe_read_reporting(tmp_path / "profiles")

    assert measured["unreported_cv_read_failures"] == measured["read_failures_produced"]
    assert measured["unreported_cv_read_failures"] > 0
    assert measured["failures"]


def test_the_import_log_never_carries_the_document_text(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The log records what happened to a document, never what was in it.

    `cv/source/*` and `master.json` already hold the candidate's own words
    under their own tree; a second copy in a diagnostic file is content nobody
    asked this to keep, in a file whose whole purpose is to be read by
    something that failed.
    """
    secret = "Zylofoundry Q9 supply-chain rescue, 2019"
    import_document(store, _docx(tmp_path, "cv.docx", ("Núria Bosch", secret)))

    assert secret not in store.path(*IMPORT_LOG_PARTS).read_text(encoding="utf-8")


def test_the_log_survives_a_reader_that_is_not_a_list(store: ProfileStore, tmp_path: Path) -> None:
    """A hand-edited log that became an object is replaced, not appended to."""
    store.path(*IMPORT_LOG_PARTS).parent.mkdir(parents=True, exist_ok=True)
    store.path(*IMPORT_LOG_PARTS).write_text('{"status": "imported"}', encoding="utf-8")

    import_document(store, _docx(tmp_path, "cv.docx", _READABLE_CV))
    assert [record["file"] for record in read_import_log(store)] == ["cv.docx"]


def test_zipfile_is_imported_for_the_fixtures_this_file_builds() -> None:
    """`_build_minimal_docx` writes a real zip; this pins that the fixtures
    above are documents rather than bytes that merely end in `.docx`."""
    assert zipfile.is_zipfile(io.BytesIO(_build_minimal_docx(["Núria Bosch"])))
