"""S4 — the CV store: import, build-from-nothing, and the `master.json` contract.

The payload (`arsenal/tasks/_history/lo-cb1c.md`) names three tests directly;
this file also covers what the module docstring and the payload's "things to
get right" call out: the dependency split (DOCX stdlib-only, PDF behind the
optional `cv` extra), `cv/source/*` stored unmodified, build-from-nothing
reaching the identical contract a parsed document does, and the required
verification (strip one field's provenance, watch `intake_field_provenance`
fall and the CLI exit non-zero).

Every test here gives the same verdict with and without the `cv` extra
installed. The dependency split is exercised by forcing the missing path
(`_pypdf_forced_missing`) and by skipping the installed-only path when the
extra is genuinely absent — never by asserting that `import pypdf` fails,
which would make a green suite a fact about the machine rather than the code.
"""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral import cv_store as cv_store_module
from integral.cv_store import (
    _LEAK_PROBE_MARKER,
    MINIMUM_CHECKS,
    MINIMUM_FIELDS_MEASURED,
    CVMaster,
    CVStoreError,
    DeclinedSubjectError,
    DocumentSpan,
    Experience,
    ImportResult,
    LanguageEntry,
    _build_minimal_docx,
    _extract_docx_text,
    _pypdf_forced_missing,
    _wrap_docx_body,
    add_conversation_entry,
    add_document_entry,
    import_document,
    load_master,
    measure_provenance,
    next_doc_id,
    probe_intake,
    set_conversation_scalar,
    set_document_scalar,
    write_evidence,
    write_master,
)
from integral.decline import DeclineError, DeclineLedger
from integral.identity import ProfileStore, create_profile
from integral.profile import EvidenceLog


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    root = tmp_path / "profiles"
    identity = create_profile(root, "Ada Lovelace", handle="ada", language="en")
    return ProfileStore(root, identity.handle)


# --- the three RED tests named in the payload -------------------------------


def test_every_master_field_names_its_source(store: ProfileStore) -> None:
    """`intake_field_provenance` is the fraction of populated `master.json`
    fields that name where they came from. A store where every field carries
    a resolvable document span or evidence-row reference must measure 1.0;
    the moment one field's provenance is stripped the fraction must drop and
    name exactly that field — proving the metric reads real state, not a
    a hopeful default.
    """
    master = CVMaster()
    master = set_conversation_scalar(
        store,
        master,
        "residence_claim",
        said="I live in Girona.",
        recorded_at="2026-08-18T09:00:00Z",
    )
    master = add_conversation_entry(
        store,
        master,
        "experience",
        {"title": "Supervisor", "organisation": "Cintra Logistics"},
        said="I supervised the night shift at Cintra Logistics.",
        recorded_at="2026-08-18T09:00:01Z",
    )
    write_master(store, master)

    good = measure_provenance(store, master)
    assert good.coverage == 1.0
    assert good.fields_measured == 2
    assert good.violations == ()

    stripped = master.experience[0].model_copy(update={"provenance": ()})
    broken = master.model_copy(update={"experience": (stripped,)})
    bad = measure_provenance(store, broken)
    assert bad.coverage < 1.0
    assert bad.fields_measured == good.fields_measured, (
        "stripping provenance changed the field, not the count"
    )
    assert any("experience[0]" in violation for violation in bad.violations)
    assert any("no provenance recorded" in violation for violation in bad.violations)


def test_a_candidate_with_no_cv_can_still_reach_a_first_version(store: ProfileStore) -> None:
    """Intake never produces a document, and a candidate with nothing to
    import is not shortchanged: build-from-nothing writes the *same*
    `CVMaster` contract — the same section types, fully provenanced — that
    parsing a real CV would, just citing conversation turns instead of
    document spans.
    """
    master = CVMaster()
    assert master == CVMaster(), "a fresh store is the same empty contract every time"

    master = set_conversation_scalar(
        store,
        master,
        "headline",
        said="Backend engineer, twelve years.",
        recorded_at="2026-08-18T09:00:00Z",
    )
    master = add_conversation_entry(
        store,
        master,
        "experience",
        {
            "title": "Backend Engineer",
            "organisation": "Cintra Logistics",
            "start": "2021",
            "end": None,
            "description": "Rebuilt the pick-and-pack pipeline.",
        },
        said="I've been the backend engineer at Cintra Logistics since 2021, and rebuilt "
        "the pick-and-pack pipeline while I was there.",
        recorded_at="2026-08-18T09:00:01Z",
    )
    master = add_conversation_entry(
        store,
        master,
        "episodes",
        {"kind": "lesson", "text": "I now confirm supplier dates before promising a delivery."},
        said="I once promised a delivery date before checking with our supplier — cost us a "
        "client. I confirm supplier dates before promising, now.",
        recorded_at="2026-08-18T09:00:02Z",
    )
    write_master(store, master)

    result = measure_provenance(store, master)
    assert result.coverage == 1.0
    assert result.fields_measured >= 3

    # Reaches the identical on-disk contract a document import would: same
    # types, and a genuine round-trip through write/load.
    assert isinstance(master.experience[0], Experience)
    reloaded = load_master(store)
    assert reloaded == master

    # And every conversation-sourced field really did write to
    # `profile/evidence.jsonl` (T6, unmodified) — step 1's own outputs line.
    evidence_ids = {row.id for row in EvidenceLog(store).rows()}
    assert len(evidence_ids) == 3
    for entry in (master.headline, master.experience[0], master.episodes[0]):
        assert entry is not None
        (provenance,) = entry.provenance
        assert provenance.evidence_id in evidence_ids  # type: ignore[union-attr]


def test_the_store_is_never_sent_verbatim(tmp_path: Path) -> None:
    """§2.6: the store is "never sent anywhere as-is". Intake generates no
    outbound document (that is T45/T46's job), so the one real send-path at
    this layer is the gate's own evidence artefact — committed to git,
    printed in CI, and pasted into chat. This builds a store carrying a
    distinctive marker standing in for something a candidate actually said,
    and proves that text never reaches the measured evidence payload: only
    field paths, counts, and booleans do.
    """
    root = tmp_path / "profiles"
    measured = probe_intake(root)

    payload = json.dumps(measured, ensure_ascii=False)
    assert _LEAK_PROBE_MARKER not in payload, (
        "the store's own content leaked into the gate's evidence — this is exactly the "
        "kind of artefact that gets committed, logged, and pasted into a conversation"
    )
    # And the violation strings that *do* appear are field paths, never text.
    for violation in measured["build_from_nothing"]["violations"]:
        assert _LEAK_PROBE_MARKER not in violation


# --- the dependency decision: DOCX stdlib, PDF behind the optional extra ----


def test_docx_extraction_needs_no_third_party_package() -> None:
    """`_extract_docx_text` reads a `.docx` with stdlib `zipfile` +
    `xml.etree` only — proven by round-tripping a fixture built the same way
    (`_build_minimal_docx`, also stdlib-only)."""
    docx_bytes = _build_minimal_docx(
        ["First paragraph.", "", "Second paragraph, with more to say."]
    )
    tmp = Path("/tmp") / "cv_store_docx_test.docx"
    tmp.write_bytes(docx_bytes)
    try:
        text = _extract_docx_text(tmp)
    finally:
        tmp.unlink()
    assert "First paragraph." in text
    assert "Second paragraph, with more to say." in text


def test_docx_extraction_reads_headers_and_footers_in_document_order() -> None:
    """Content in a DOCX running head or foot must reach the extracted text.

    A word processor's header is where a CV's name and contact details
    usually live, and reading only `word/document.xml` dropped them with no
    error and no drop in `intake_field_provenance` — that metric asks whether
    the fields present name their origin, not whether the file's contents all
    made it in. So the import scored a clean 1.0 over a CV with no name.

    Order is asserted, not just membership: the extracted text is the artefact
    provenance spans index into, so headers-then-body-then-footers has to be
    stable or every span offset moves between runs.
    """
    docx_bytes = _wrap_docx_body(
        "<w:p><w:r><w:t>Body paragraph.</w:t></w:r></w:p>",
        extra_parts={
            "word/header1.xml": "<w:p><w:r><w:t>Ada Lovelace</w:t></w:r></w:p>",
            "word/footer1.xml": "<w:p><w:r><w:t>Page 1 of 1</w:t></w:r></w:p>",
        },
    )
    tmp = Path("/tmp") / "cv_store_docx_headers_test.docx"
    tmp.write_bytes(docx_bytes)
    try:
        text = _extract_docx_text(tmp)
    finally:
        tmp.unlink()

    assert "Ada Lovelace" in text, "header content was dropped"
    assert "Page 1 of 1" in text, "footer content was dropped"
    assert text == "Ada Lovelace\nBody paragraph.\nPage 1 of 1"


def test_pdf_import_reports_unavailable_when_pypdf_cannot_be_imported(
    store: ProfileStore, tmp_path: Path
) -> None:
    """A PDF handed in without the optional `cv` extra must report, not raise.

    This forces the missing-dependency path rather than assuming it. The
    earlier version of this test asserted `pytest.raises(ImportError)` on a
    bare `import pypdf`, which made the test a statement about the machine it
    ran on: it passed in CI (no extras) and failed the moment anyone ran
    `uv sync --extra cv`, with nothing about the CV store having changed. That
    is the same defect the intake probe was just fixed for — a measurement
    whose answer depends on what happens to be installed — and a test carrying
    it turns "the optional extra is present" into a red build.
    """
    pdf_path = tmp_path / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nnot a real pdf\n")

    with _pypdf_forced_missing():
        result = import_document(store, pdf_path)

    assert isinstance(result, ImportResult)
    assert result.doc_id is None
    assert result.blocks_added == 0
    assert result.detail  # a candidate-facing message, not silence
    assert load_master(store) == CVMaster(), "a failed import must not write anything"
    assert result.status == "unavailable"


def test_pdf_import_reports_corrupt_when_pypdf_is_installed(
    store: ProfileStore, tmp_path: Path
) -> None:
    """With the extra present, a malformed PDF is `corrupt`, not `unavailable`.

    The two statuses mean different things to a candidate — "install something"
    versus "this file is damaged, send another" — and only the installed path
    can tell them apart. Skipping rather than asserting absence keeps this
    file's verdict identical in both environments.
    """
    pytest.importorskip("pypdf", reason="the optional `cv` extra is not installed here")

    pdf_path = tmp_path / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nnot a real pdf\n")
    result = import_document(store, pdf_path)

    assert isinstance(result, ImportResult)
    assert result.blocks_added == 0
    assert result.detail
    assert load_master(store) == CVMaster(), "a failed import must not write anything"
    assert result.status == "corrupt"


def test_import_document_rejects_unsupported_formats_without_crashing(
    store: ProfileStore, tmp_path: Path
) -> None:
    txt_path = tmp_path / "cv.txt"
    txt_path.write_text("plain text is not a supported CV format", encoding="utf-8")
    result = import_document(store, txt_path)
    assert result.status == "unsupported"
    assert load_master(store) == CVMaster()


def test_import_document_reports_empty_when_nothing_extracts(
    store: ProfileStore, tmp_path: Path
) -> None:
    docx_bytes = _build_minimal_docx(["", "   ", ""])
    path = tmp_path / "blank.docx"
    path.write_bytes(docx_bytes)
    result = import_document(store, path)
    assert result.status == "empty"
    assert load_master(store) == CVMaster()


# --- `cv/source/*` stored unmodified; spans are offsets into it ------------


def test_imported_source_text_is_stored_unmodified_and_spans_resolve(
    store: ProfileStore, tmp_path: Path
) -> None:
    paragraph = "Led the migration off a monolith, cutting deploy time from 45 to 6 minutes."
    docx_bytes = _build_minimal_docx(["Header line.", paragraph])
    path = tmp_path / "cv.docx"
    path.write_bytes(docx_bytes)

    result = import_document(store, path)
    assert result.status == "imported"
    assert result.doc_id is not None

    on_disk = store.read_text("cv", "source", f"{result.doc_id}.txt")
    assert on_disk == _extract_docx_text(path), (
        "cv/source/* must match the extractor's own output exactly"
    )

    master = load_master(store)
    assert len(master.raw_blocks) == 2
    for block in master.raw_blocks:
        (span,) = block.provenance
        assert isinstance(span, DocumentSpan)
        assert on_disk[span.start : span.end] == block.text

    provenance_result = measure_provenance(store, master)
    assert provenance_result.coverage == 1.0


def test_next_doc_id_derives_from_what_is_on_disk(store: ProfileStore) -> None:
    assert next_doc_id(store) == "doc-000001"
    store.write_text("existing text", "cv", "source", "doc-000001.txt")
    store.write_text("existing text", "cv", "source", "doc-000005.txt")
    assert next_doc_id(store) == "doc-000006"


# --- classification into typed sections, from either origin ----------------


def test_add_document_entry_and_add_conversation_entry_use_the_same_section_models(
    store: ProfileStore,
) -> None:
    doc_master = add_document_entry(
        CVMaster(),
        "languages",
        {"language": "en", "level": "professional"},
        doc_id="doc-000001",
        start=0,
        end=10,
    )
    conv_master = add_conversation_entry(
        store,
        CVMaster(),
        "languages",
        {"language": "en", "level": "professional"},
        said="My English is professional-level.",
        recorded_at="2026-08-18T09:00:00Z",
    )
    assert type(doc_master.languages[0]) is type(conv_master.languages[0]) is LanguageEntry
    assert doc_master.languages[0].level == conv_master.languages[0].level == "professional"
    assert isinstance(doc_master.languages[0].provenance[0], DocumentSpan)
    assert doc_master.languages[0].provenance[0].__class__.__name__ == "DocumentSpan"


def test_unknown_section_is_refused_not_silently_dropped(store: ProfileStore) -> None:
    with pytest.raises(CVStoreError):
        add_document_entry(CVMaster(), "hobbies", {}, doc_id="doc-000001", start=0, end=1)
    with pytest.raises(CVStoreError):
        add_conversation_entry(
            store,
            CVMaster(),
            "hobbies",
            {},
            said="I collect stamps.",
            recorded_at="2026-08-18T09:00:00Z",
        )
    with pytest.raises(CVStoreError):
        set_document_scalar(
            CVMaster(), "date_of_birth", text="x", doc_id="doc-000001", start=0, end=1
        )


def test_add_conversation_entry_refuses_blank_text(store: ProfileStore) -> None:
    """Nothing was said, so there is nothing to provenance — a blank answer
    must not silently mint an entry citing an evidence row that says nothing."""
    with pytest.raises(CVStoreError):
        add_conversation_entry(
            store,
            CVMaster(),
            "experience",
            {"title": "x", "organisation": "y"},
            said="   ",
            recorded_at="2026-08-18T09:00:00Z",
        )
    assert list(EvidenceLog(store).rows()) == []


def test_a_declined_subject_is_not_written_by_the_conversational_path(
    store: ProfileStore,
) -> None:
    """D-9/T40: non-insistence must hold on the *write* path, not only the
    ask path. Every other free-text writer in this codebase filters through
    `DeclineLedger` before it appends (`elicit_extract._undeclined`,
    `constraints_step.resolve`); before this fix, `add_conversation_entry`
    did not, so a candidate who declined "experience" and never reopened it
    could still have an answer on it filed here — the one surface built for
    the candidate with no CV, who answers the most questions of anyone."""
    ledger = DeclineLedger(store)
    ledger.decline("experience", step="intake", at="2026-08-18T09:00:00Z")

    with pytest.raises(DeclinedSubjectError):
        add_conversation_entry(
            store,
            CVMaster(),
            "experience",
            {"title": "Warehouse Team Lead", "organisation": "Northgate Logistics"},
            said="I ran the night shift at Northgate Logistics for two years.",
            recorded_at="2026-08-18T09:00:30Z",
        )

    assert list(EvidenceLog(store).rows()) == []


def test_an_unreadable_decline_ledger_refuses_the_write_as_a_cv_store_error(
    store: ProfileStore,
) -> None:
    """A corrupt `declines.jsonl` must not escape the documented contract, and
    must not let the write through.

    `DeclineLedger.entries` raises `DeclineError` on a line that is not a
    ledger entry, and `DeclineError` is a plain `Exception` — not a
    `CVStoreError`. Both writers promise callers that `except CVStoreError` is
    enough to survive any submission they cannot honour, so an untranslated
    `DeclineError` would sail past a caller that did exactly what the
    docstring told it to do.

    Fail-closed is the half that matters more: a ledger that cannot be read
    cannot show the subject is *permitted*, and writing anyway would file the
    very answer T40 exists to keep out — onto an append-only log with no
    rollback. So the assertion here is not only the exception type but the
    empty log after it.
    """
    ledger_path = DeclineLedger(store).path
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("{not json at all\n", encoding="utf-8")

    with pytest.raises(CVStoreError) as entry_failure:
        add_conversation_entry(
            store,
            CVMaster(),
            "experience",
            {"title": "Warehouse Team Lead", "organisation": "Northgate Logistics"},
            said="I ran the night shift at Northgate Logistics for two years.",
            recorded_at="2026-08-18T09:00:30Z",
        )
    assert isinstance(entry_failure.value.__cause__, DeclineError)
    assert list(EvidenceLog(store).rows()) == []

    with pytest.raises(CVStoreError) as scalar_failure:
        set_conversation_scalar(
            store,
            CVMaster(),
            "headline",
            said="Ten years in logistics, most of it on nights.",
            recorded_at="2026-08-18T09:01:00Z",
        )
    assert isinstance(scalar_failure.value.__cause__, DeclineError)
    assert list(EvidenceLog(store).rows()) == []

    # And a readable ledger still writes, so the guard above is refusing the
    # unreadable ledger rather than refusing everything.
    ledger_path.write_text("", encoding="utf-8")
    set_conversation_scalar(
        store,
        CVMaster(),
        "headline",
        said="Ten years in logistics, most of it on nights.",
        recorded_at="2026-08-18T09:01:00Z",
    )
    assert len(list(EvidenceLog(store).rows())) == 1


def test_a_reopened_decline_lets_the_subject_be_recorded_again(store: ProfileStore) -> None:
    """The other half of the fix: refusing every write for a declined subject
    is not the same as honouring T40, and a fix that never writes anything
    would pass the previous test for the wrong reason. §5.4: only the
    candidate reopening a subject clears it — once "experience" is reopened,
    the exact same conversational entry the previous test refused must be
    recorded, with a real `profile/evidence.jsonl` row behind it."""
    ledger = DeclineLedger(store)
    ledger.decline("experience", step="intake", at="2026-08-18T09:00:00Z")
    ledger.reopen("experience", at="2026-08-18T09:05:00Z")

    master = add_conversation_entry(
        store,
        CVMaster(),
        "experience",
        {"title": "Warehouse Team Lead", "organisation": "Northgate Logistics"},
        said="I ran the night shift at Northgate Logistics for two years.",
        recorded_at="2026-08-18T09:10:00Z",
    )

    rows = list(EvidenceLog(store).rows())
    assert len(rows) == 1
    assert master.experience[-1].provenance[0].evidence_id == rows[0].id  # type: ignore[union-attr]


# --- the on-disk contract: strict, frozen, extra keys refused ---------------


def test_master_json_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        CVMaster.model_validate({"schema_version": 1, "date_of_birth": "1990-01-01"})


def test_cv_master_and_entries_are_frozen() -> None:
    master = CVMaster()
    with pytest.raises(ValidationError):
        master.schema_version = 2  # type: ignore[assignment]
    entry = Experience(title="x", organisation="y")
    with pytest.raises(ValidationError):
        entry.title = "z"


def test_load_master_raises_on_structural_corruption(store: ProfileStore) -> None:
    """A missing file is a normal starting state (no error); a file that
    exists but is not a valid `CVMaster` is corruption, and raises."""
    assert load_master(store) == CVMaster()
    store.write_json({"schema_version": 1, "not_a_real_field": True}, "cv", "master.json")
    with pytest.raises(CVStoreError):
        load_master(store)


def test_a_field_may_load_with_no_provenance_but_is_measured_as_a_violation(
    store: ProfileStore,
) -> None:
    """`provenance` has no `min_length` — an empty tuple loads without error
    (this is what makes the deliberate-break demonstration a *measurement*,
    not a load failure), but `measure_provenance` still reports it."""
    entry = Experience(title="x", organisation="y")  # no provenance supplied at all
    assert entry.provenance == ()
    master = CVMaster(experience=(entry,))
    write_master(store, master)
    reloaded = load_master(store)
    assert reloaded == master  # loaded without error

    result = measure_provenance(store, reloaded)
    assert result.coverage == 0.0
    assert "experience[0]: no provenance recorded" in result.violations


def test_a_provenance_reference_that_does_not_resolve_is_also_a_violation(
    store: ProfileStore,
) -> None:
    """Non-empty provenance is not enough on its own — a span past the end of
    its source text, or an evidence id nobody ever wrote, must count as a
    violation exactly like having none at all."""
    bogus_span = Experience(
        title="x",
        organisation="y",
        provenance=(DocumentSpan(source_file="doc-000001", start=0, end=999),),
    )
    master = CVMaster(experience=(bogus_span,))
    result = measure_provenance(store, master)
    assert result.coverage == 0.0
    assert any("out of bounds" in v or "no stored source text" in v for v in result.violations)


# --- an empty store must not report full provenance -------------------------


def test_empty_store_reports_zero_not_one(store: ProfileStore) -> None:
    result = measure_provenance(store, CVMaster())
    assert result.coverage == 0.0
    assert result.fields_measured == 0


# --- the adversarial probe + CLI ---------------------------------------------


def test_probe_intake_runs_at_least_the_minimum_checks_and_all_pass(tmp_path: Path) -> None:
    report = probe_intake(tmp_path / "profiles")
    assert report["checks_run"] >= MINIMUM_CHECKS
    assert report["failures"] == []
    assert report["intake_field_provenance"] == 1.0
    assert report["fields_measured"] >= MINIMUM_FIELDS_MEASURED


def test_write_evidence_writes_the_measured_json(tmp_path: Path) -> None:
    target = tmp_path / "S4.json"
    write_evidence(target)
    assert target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["intake_field_provenance"] == 1.0


def test_cli_exits_zero_when_the_real_scenarios_pass(tmp_path: Path) -> None:
    from integral.cv_store import _main

    evidence_path = tmp_path / "S4.json"
    exit_code = _main(["prog", "--write-evidence", str(evidence_path)])
    assert exit_code == 0
    assert evidence_path.exists()


def test_cli_exits_nonzero_when_intake_field_provenance_is_below_one(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The required verification, run through the real CLI entry point: a
    `master.json` with one field stripped of provenance must drop the
    measured metric below 1.0 and make `_main` exit non-zero — not merely
    the probe's own internal bookkeeping.
    """
    from integral import cv_store
    from integral.cv_store import _main

    def broken_probe(root: Path) -> dict[str, object]:
        stripped = Experience(title="x", organisation="y")  # no provenance
        good_master = CVMaster()
        good_master = set_conversation_scalar(
            store,
            good_master,
            "headline",
            said="Backend engineer.",
            recorded_at="2026-08-18T09:00:00Z",
        )
        good_master = add_conversation_entry(
            store,
            good_master,
            "experience",
            {"title": "a", "organisation": "b"},
            said="I was a backend engineer at a logistics company.",
            recorded_at="2026-08-18T09:00:01Z",
        )
        good_master = add_conversation_entry(
            store,
            good_master,
            "experience",
            {"title": "c", "organisation": "d"},
            said="Before that I was a warehouse operative.",
            recorded_at="2026-08-18T09:00:02Z",
        )
        good_master = add_conversation_entry(
            store,
            good_master,
            "episodes",
            {"kind": "lesson", "text": "I always confirm dates now."},
            said="I once promised a date I could not keep. I always confirm dates now.",
            recorded_at="2026-08-18T09:00:03Z",
        )
        master = good_master.model_copy(update={"experience": (*good_master.experience, stripped)})
        result = measure_provenance(store, master)
        return {
            "intake_field_provenance": result.coverage,
            "fields_measured": result.fields_measured,
            "intake_declined_subjects_written": 0,
            "failures": [],
            "checks_run": MINIMUM_CHECKS,
        }

    monkeypatch.setattr(cv_store, "probe_intake", broken_probe)
    evidence_path = tmp_path / "S4-broken.json"
    exit_code = _main(["prog", "--write-evidence", str(evidence_path)])

    measured = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert measured["intake_field_provenance"] < 1.0
    assert exit_code == 1


def test_cli_exits_three_when_too_few_checks_ran(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean score without exercising the real scenarios is not a
    measurement — the same `MINIMUM_CHECKS`-floor pattern T28/T6/D-6 each
    enforce for their own probes."""
    from integral import cv_store
    from integral.cv_store import _main

    def thin_probe(root: Path) -> dict[str, object]:
        return {
            "intake_field_provenance": 1.0,
            "fields_measured": MINIMUM_FIELDS_MEASURED,
            "failures": [],
            "checks_run": 1,
        }

    monkeypatch.setattr(cv_store, "probe_intake", thin_probe)
    exit_code = _main(["prog", "--write-evidence", str(tmp_path / "S4-thin.json")])
    assert exit_code == 3


# =============================================================================
# Six review findings (lo-cb1c follow-up) + the deferred provenance decision
# =============================================================================


# --- finding 1: the gate must not depend on whether `pypdf` is installed ----


def test_probe_intake_pdf_check_is_deterministic_regardless_of_pypdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`probe_intake` used to assert the malformed-PDF fixture is
    'unavailable' unconditionally — true only when `pypdf` happens to be
    absent. Simulate `pypdf` being importable (via `sys.modules`, so this
    does not depend on it actually being installed) and confirm the probe
    still reports 'unavailable' for the *forced-missing* scenario, and
    'corrupt' for the scenario that genuinely has the dependency — never
    one status standing in for whichever the ambient environment supplies.
    """

    class _FakePdfReader:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise ValueError("not a real PDF — this is exactly what a real pypdf would raise too")

    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = _FakePdfReader  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdf", fake_pypdf)

    report = probe_intake(tmp_path / "profiles")
    assert report["failures"] == []
    states = report["document_import"]["pdf_dependency_states"]
    assert states["forced_missing"]["status"] == "unavailable"
    assert states["installed"]["status"] == "corrupt"


def test_pdf_forced_missing_path_does_not_depend_on_real_absence(tmp_path: Path) -> None:
    """The forced-missing path inside `probe_intake` must give 'unavailable'
    even when run in *this* environment, where `pypdf` really is absent —
    proving the forcing mechanism (`sys.modules["pypdf"] = None`) and the
    ordinary absent-dependency path agree."""
    report = probe_intake(tmp_path / "profiles")
    assert report["document_import"]["pdf_dependency_states"]["forced_missing"]["status"] == (
        "unavailable"
    )


# --- finding 2: import_document is non-transactional -------------------------


def test_two_racing_imports_do_not_silently_clobber_each_others_source_text(
    store: ProfileStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`next_doc_id` only reads the directory — it reserves nothing — so two
    imports racing before either has written anything can both compute the
    same 'next' id. Force that deterministically: the first two calls to
    `next_doc_id` both return 'doc-000001' (what a real race would produce),
    then fall through to the real function so a reservation's retry can
    recover. Pre-fix, the second import silently overwrites the first
    import's source text under the shared id — leaving `master.json` spans
    that were cut from the first import's text pointing into the second
    import's text instead: the "wrong document" corruption finding 2 names.
    """
    real_next_doc_id = cv_store_module.next_doc_id
    calls = {"count": 0}

    def racy_next_doc_id(s: ProfileStore) -> str:
        calls["count"] += 1
        if calls["count"] <= 2:
            return "doc-000001"
        return real_next_doc_id(s)

    monkeypatch.setattr(cv_store_module, "next_doc_id", racy_next_doc_id)

    docx_a = _build_minimal_docx(["Importer A's paragraph, not B's."])
    docx_b = _build_minimal_docx(["Importer B's paragraph, not A's."])
    path_a = tmp_path / "a.docx"
    path_b = tmp_path / "b.docx"
    path_a.write_bytes(docx_a)
    path_b.write_bytes(docx_b)

    result_a = import_document(store, path_a)
    result_b = import_document(store, path_b)

    assert result_a.doc_id != result_b.doc_id, (
        "two imports that raced on the same computed id both ended up 'imported' under it"
    )
    text_a = store.read_text("cv", "source", f"{result_a.doc_id}.txt")
    assert "Importer A" in text_a and "Importer B" not in text_a, (
        "importer A's source text was silently overwritten by importer B's import"
    )


def test_atomic_write_leaves_no_partial_file_when_interrupted(
    store: ProfileStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`write_master`/`import_document` must never let a reader observe a
    half-written file: the write lands wholly (temp file, then
    `os.replace`) or not at all — never truncated in place."""
    store.write_text('{"already": "here"}\n', "cv", "master.json")
    original = store.path("cv", "master.json").read_bytes()

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr(os, "fdopen", boom)
    with pytest.raises(OSError):
        cv_store_module._atomic_write(store, b"new content", "cv", "master.json")

    assert store.path("cv", "master.json").read_bytes() == original, (
        "an interrupted write corrupted the file that was already there"
    )
    leftovers = list(store.path("cv").glob(".master.json.*.tmp"))
    assert leftovers == [], f"a temp file was left behind after the interrupted write: {leftovers}"


# --- finding 3: evidence must not be written before validation ---------------


def test_invalid_fields_do_not_leave_an_orphan_evidence_row(store: ProfileStore) -> None:
    """`EvidenceLog.append` is append-only with no rollback (`integral.
    profile`'s own module docstring) — if `add_conversation_entry` writes
    the row before validating `fields`, an invalid submission leaves a
    permanent, unreferenced row nothing can ever remove. Validate first."""
    with pytest.raises(CVStoreError):
        add_conversation_entry(
            store,
            CVMaster(),
            "experience",
            {"title": "Supervisor"},  # missing required 'organisation'
            said="Something a candidate actually said, worth recording.",
            recorded_at="2026-08-18T09:00:00Z",
        )
    assert list(EvidenceLog(store).rows()) == [], (
        "an invalid submission left a permanent, unrecoverable evidence row on disk"
    )


def test_valid_conversation_entry_still_writes_exactly_one_evidence_row(
    store: ProfileStore,
) -> None:
    """Validating before appending must not change the well-formed case:
    still exactly one row, still cited by the entry it provenances."""
    master = add_conversation_entry(
        store,
        CVMaster(),
        "experience",
        {"title": "Supervisor", "organisation": "Cintra Logistics"},
        said="I supervised the night shift at Cintra Logistics.",
        recorded_at="2026-08-18T09:00:00Z",
    )
    rows = list(EvidenceLog(store).rows())
    assert len(rows) == 1
    (provenance,) = master.experience[0].provenance
    assert provenance.evidence_id == rows[0].id  # type: ignore[union-attr]


# --- finding 4: the original document bytes must be kept, not just the text -


def test_import_document_keeps_the_original_file_bytes_alongside_extracted_text(
    store: ProfileStore, tmp_path: Path
) -> None:
    """The scope change says `cv/source/*` is stored unmodified; the
    importer only ever wrote *extracted text*. Keep both, named so nobody
    mistakes one for the other: `<doc-id>.txt` is the extracted text spans
    index into, `<doc-id>.original<suffix>` is the uploaded bytes verbatim.
    """
    docx_bytes = _build_minimal_docx(["A paragraph a candidate's CV really has."])
    path = tmp_path / "cv.docx"
    path.write_bytes(docx_bytes)

    result = import_document(store, path)
    assert result.status == "imported"
    assert result.doc_id is not None

    original_name = f"{result.doc_id}.original.docx"
    assert store.exists("cv", "source", original_name), (
        "the original uploaded file bytes were discarded on import"
    )
    assert store.path("cv", "source", original_name).read_bytes() == docx_bytes, (
        "the kept 'original' file does not match what was actually uploaded"
    )
    # And the extracted-text file is still the one spans index into.
    extracted = store.read_text("cv", "source", f"{result.doc_id}.txt")
    assert extracted == _extract_docx_text(path)


# --- finding 5: DOCX separators (tabs, line breaks) must not vanish ---------


def test_docx_extraction_preserves_tabs_and_line_breaks(tmp_path: Path) -> None:
    """`_extract_docx_text` concatenated only `<w:t>` runs, so an explicit
    `<w:tab/>` or `<w:br/>` contributed nothing — merging tab-separated
    values and losing line breaks. Since the extracted text is what
    provenance spans index into, a dropped separator shifts every later
    offset, not just the display."""
    body = (
        '<w:p><w:r><w:t xml:space="preserve">Name</w:t></w:r>'
        "<w:r><w:tab/></w:r>"
        '<w:r><w:t xml:space="preserve">Role</w:t></w:r>'
        "<w:r><w:br/></w:r>"
        '<w:r><w:t xml:space="preserve">Ada Lovelace</w:t></w:r></w:p>'
    )
    docx_path = tmp_path / "seps.docx"
    docx_path.write_bytes(_wrap_docx_body(body))

    text = _extract_docx_text(docx_path)
    assert text == "Name\tRole\nAda Lovelace"


def test_docx_separators_keep_offsets_meaningful_end_to_end(
    store: ProfileStore, tmp_path: Path
) -> None:
    """A dropped separator does not just look wrong in isolation — it shifts
    every span computed after it. Import a document containing one and
    confirm the stored source text, and the spans cut from it, still agree.
    """
    body = (
        '<w:p><w:r><w:t xml:space="preserve">Skills:</w:t></w:r>'
        "<w:r><w:tab/></w:r>"
        '<w:r><w:t xml:space="preserve">Python, SQL</w:t></w:r></w:p>'
        '<w:p><w:r><w:t xml:space="preserve">Second paragraph.</w:t></w:r></w:p>'
    )
    path = tmp_path / "cv.docx"
    path.write_bytes(_wrap_docx_body(body))

    result = import_document(store, path)
    assert result.status == "imported"
    on_disk = store.read_text("cv", "source", f"{result.doc_id}.txt")
    assert on_disk == "Skills:\tPython, SQL\nSecond paragraph."

    master = load_master(store)
    for block in master.raw_blocks:
        (span,) = block.provenance
        assert isinstance(span, DocumentSpan)
        assert on_disk[span.start : span.end] == block.text


# --- finding 6: schema_version must be constrained, and refused if unknown --


def test_schema_version_must_be_the_known_literal() -> None:
    with pytest.raises(ValidationError):
        CVMaster(schema_version=2)  # type: ignore[arg-type]


def test_load_master_refuses_an_unknown_schema_version_by_name(store: ProfileStore) -> None:
    """A file marked `schema_version: 2` must not silently validate against
    the version-1 model just because its other keys happen to fit — and the
    refusal must name the version, not surface as a generic field error."""
    store.write_json({"schema_version": 2, "experience": []}, "cv", "master.json")
    with pytest.raises(CVStoreError, match="schema_version"):
        load_master(store)


# --- the deferred decision: per-entry provenance, reconciled with the metric
# name and the spec wording (see `_named_fields`'s docstring for the reasoning)


def test_an_entry_with_several_fields_is_one_provenance_measurement() -> None:
    """Documents the chosen granularity: `measure_provenance` counts one
    measurement for a whole `Experience` (title, organisation, start, end,
    description), not one per leaf attribute — see `_named_fields`."""
    from integral.cv_store import _named_fields

    entry = Experience(
        title="Backend Engineer",
        organisation="Cintra Logistics",
        start="2021",
        end=None,
        description="Rebuilt the pick-and-pack pipeline.",
        provenance=(DocumentSpan(source_file="doc-000001", start=0, end=10),),
    )
    master = CVMaster(experience=(entry,))
    named = _named_fields(master)
    assert named == [("experience[0]", entry)], (
        "a multi-field entry must count as exactly one named measurement, not one per leaf field"
    )
