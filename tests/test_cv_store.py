"""S4 — the CV store: import, build-from-nothing, and the `master.json` contract.

The payload (`claude-arsenal/queue/lo-cb1c.md`) names three tests directly;
this file also covers what the module docstring and the payload's "things to
get right" call out: the dependency split (DOCX stdlib-only, PDF behind the
optional `cv` extra, absent everywhere these tests run), `cv/source/*` stored
unmodified, build-from-nothing reaching the identical contract a parsed
document does, and the required verification (strip one field's provenance,
watch `intake_field_provenance` fall and the CLI exit non-zero).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobsearch.cv_store import (
    _LEAK_PROBE_MARKER,
    MINIMUM_CHECKS,
    MINIMUM_FIELDS_MEASURED,
    CVMaster,
    CVStoreError,
    DocumentSpan,
    Experience,
    ImportResult,
    LanguageEntry,
    _build_minimal_docx,
    _extract_docx_text,
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
from jobsearch.identity import ProfileStore, create_profile
from jobsearch.profile import EvidenceLog


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


def test_pdf_import_reports_unavailable_without_crashing(
    store: ProfileStore, tmp_path: Path
) -> None:
    """This test environment has no `pypdf` installed — the same as every
    gate this project runs (`make ci`, no extras). Importing a `.pdf` must
    report a clear, structured outcome, never raise and never silently write
    an empty store.
    """
    with pytest.raises(ImportError):
        import pypdf  # type: ignore[import-not-found]  # noqa: F401 — confirms the extra is absent here

    pdf_path = tmp_path / "cv.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\nnot a real pdf\n")
    result = import_document(store, pdf_path)

    assert isinstance(result, ImportResult)
    assert result.status == "unavailable"
    assert result.doc_id is None
    assert result.blocks_added == 0
    assert result.detail  # a candidate-facing message, not silence
    assert load_master(store) == CVMaster(), "a failed import must not write anything"


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


# --- the on-disk contract: strict, frozen, extra keys refused ---------------


def test_master_json_forbids_unknown_keys() -> None:
    with pytest.raises(ValidationError):
        CVMaster.model_validate({"schema_version": 1, "date_of_birth": "1990-01-01"})


def test_cv_master_and_entries_are_frozen() -> None:
    master = CVMaster()
    with pytest.raises(ValidationError):
        master.schema_version = 2
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
    from jobsearch.cv_store import _main

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
    from jobsearch import cv_store
    from jobsearch.cv_store import _main

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
    from jobsearch import cv_store
    from jobsearch.cv_store import _main

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
