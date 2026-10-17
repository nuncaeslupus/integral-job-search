"""T338: the gate reads zero over complete folders, and goes red for each omission."""

from __future__ import annotations

import pytest

from integral import send_gate, send_set


def test_the_gate_reads_zero_over_every_candidate() -> None:
    measured = send_gate.measure()
    assert measured["gate_status"] == "measured"
    assert measured["send_folders_missing_a_sendable_document"] == 0, measured["defects"]
    assert measured["send_folders_examined_at_least"] == send_gate.MINIMUM_FOLDERS == 3


_REAL_DERIVE = send_set.derive


def _without(name_part: str):  # type: ignore[no-untyped-def]
    real = send_set.derive

    def derive(*args, **kwargs):  # type: ignore[no-untyped-def]
        made = real(*args, **kwargs)
        return {k: v for k, v in made.items() if name_part not in k}

    return derive


@pytest.mark.parametrize("omitted", ["-CV.pdf", "-Cover-Letter.pdf", "-Application.pdf", ".txt"])
def test_a_folder_missing_any_sendable_document_is_counted(
    monkeypatch: pytest.MonkeyPatch, omitted: str
) -> None:
    monkeypatch.setattr("integral.approval.derive", _without(omitted))
    measured = send_gate.measure()
    # a record that omits the file is itself a verify_send defect, so staging may
    # report it too; what matters is that no folder is read as complete
    assert measured["send_folders_missing_a_sendable_document"] == 3


def test_a_combined_pdf_with_the_cv_first_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    real = send_set.derive

    def cv_first(display, lang, texts, render=None):  # type: ignore[no-untyped-def]
        made = real(display, lang, texts, render)
        stem = send_set.name_stem(display)
        made[f"{stem}-Application.pdf"] = send_set.fixture_renderer(
            [
                made[f"{stem}-CV.pdf"].removeprefix(b"%PDF-fixture\n").decode(),
                made[f"{stem}-Cover-Letter.pdf"].removeprefix(b"%PDF-fixture\n").decode(),
            ]
        )
        return made

    monkeypatch.setattr("integral.approval.derive", cv_first)
    assert send_gate.measure()["send_folders_missing_a_sendable_document"] == 3


def _swapped(display, lang, texts, render=None):  # type: ignore[no-untyped-def]
    """The second reader's mutation: each single holds the other document, CV first."""
    made = _REAL_DERIVE(display, lang, texts, render)
    stem = send_set.name_stem(display)
    cv, letter = made[f"{stem}-CV.pdf"], made[f"{stem}-Cover-Letter.pdf"]
    made[f"{stem}-CV.pdf"], made[f"{stem}-Cover-Letter.pdf"] = letter, cv
    made[f"{stem}-Application.pdf"] = send_set.fixture_renderer(
        [
            cv.removeprefix(b"%PDF-fixture\n").decode(),
            letter.removeprefix(b"%PDF-fixture\n").decode(),
        ]
    )
    return made


def test_pdfs_that_hold_each_others_documents_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F1: names and a self-consistent combined file do not make the right content."""
    monkeypatch.setattr("integral.approval.derive", _swapped)
    measured = send_gate.measure()
    assert measured["send_folders_missing_a_sendable_document"] == 3
    assert any("does not hold the CV" in d for d in measured["defects"])


def test_a_generic_cv_pdf_name_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    real = send_set.derive

    def generic(*args, **kwargs):  # type: ignore[no-untyped-def]
        made = real(*args, **kwargs)
        made["cv.pdf"] = b"%PDF-fixture\nextra"
        return made

    monkeypatch.setattr("integral.approval.derive", generic)
    assert send_gate.measure()["send_folders_missing_a_sendable_document"] > 0


def test_a_text_letter_that_keeps_markers_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("integral.send_set.letter_text", lambda markdown: markdown)
    monkeypatch.setattr(send_gate, "letter_text", lambda markdown: markdown)
    assert send_gate.measure()["send_folders_missing_a_sendable_document"] >= 1


def test_a_scan_that_examines_too_few_folders_is_unmeasured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(send_gate, "CANDIDATES", send_gate.CANDIDATES[:2])
    measured = send_gate.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["send_folders_missing_a_sendable_document"] == -1
