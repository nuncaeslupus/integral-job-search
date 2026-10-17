"""T191: `document_render version <dir>` renders a version directory's JSON documents.

Constructed fixtures only (`sample_cv` / `sample_letter`). The HTML must equal
what `render` returns for the same country, accent and language, so a CLI that
ignored a flag is caught by comparing against the library, not by grepping.

Most tests stub `render_pdf` so they run without the `pdf` extra (CI has none):
a positive assertion that rides on a skipped test pins nothing there. One test
exercises the real engine and is skipped, loudly, without it.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from integral import document_render as dr

needs_engine = pytest.mark.skipif(
    importlib.util.find_spec("weasyprint") is None,
    reason="WeasyPrint (the 'pdf' extra) is not installed: real-PDF half of T191 NOT exercised",
)

STUB = b"%PDF-stub"
FLAGS = ["--country", "US", "--accent", "#c0392b", "--language", "ca"]


MEASURED = {"#c0392b": 40, "#ffffff": 100, "#111217": 60}


def _version_dir(
    path: Path, *, cv: bool = True, letter: bool = True, counts: dict[str, int] | None = MEASURED
) -> Path:
    if counts is not None:  # T342: the accent is the version's recorded measurement
        record = {"schema_version": 1, "site": "https://x.example", "counts": counts}
        (path / "palette.json").write_text(json.dumps(record), encoding="utf-8")
    if cv:
        (path / "cv.json").write_text(json.dumps(dr.sample_cv()), encoding="utf-8")
    if letter:
        (path / "letter.json").write_text(json.dumps(dr.sample_letter()), encoding="utf-8")
    return path


@pytest.fixture
def stub_pdf(monkeypatch: pytest.MonkeyPatch) -> list[int | None]:
    budgets: list[int | None] = []

    def fake(page_html: str, *, max_pages: int | None = None) -> tuple[bytes, int]:
        budgets.append(max_pages)
        return STUB, 1

    monkeypatch.setattr(dr, "render_pdf", fake)
    return budgets


def _expected(doc: dict[str, Any], **chosen: Any) -> str:
    return dr.render(doc, dr.RenderParams.for_recipient("US", None, **chosen))


def test_version_html_matches_the_library_for_country_accent_and_language(
    tmp_path: Path, stub_pdf: list[int | None]
) -> None:
    folder = _version_dir(tmp_path)
    assert dr._main(["version", str(folder), *FLAGS]) == 0
    chosen = {"accent": "#c0392b", "language": "ca"}
    for name, doc in (("cv", dr.sample_cv()), ("letter", dr.sample_letter())):
        assert (folder / f"{name}.html").read_text(encoding="utf-8") == _expected(doc, **chosen)
        assert (folder / f"{name}.pdf").read_bytes() == STUB
    assert stub_pdf == [dr.CV_PAGE_BUDGET, None]


@pytest.mark.parametrize(
    "flag, other",
    [("--country", "ES"), ("--language", "en")],
)
def test_each_flag_changes_the_output(
    tmp_path: Path, stub_pdf: list[int | None], flag: str, other: str
) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    for folder in (first, second):
        folder.mkdir()
        _version_dir(folder)
    assert dr._main(["version", str(first), *FLAGS]) == 0
    flags = list(FLAGS)
    flags[flags.index(flag) + 1] = other
    assert dr._main(["version", str(second), *flags]) == 0
    for name in ("cv", "letter"):
        assert (first / f"{name}.html").read_text() != (second / f"{name}.html").read_text()


def test_the_accent_is_the_recorded_measurement_when_none_is_given(
    tmp_path: Path, stub_pdf: list[int | None]
) -> None:
    folder = _version_dir(tmp_path, counts={"#00aa44": 30, "#ffffff": 100})
    assert dr._main(["version", str(folder), "--country", "US"]) == 0
    expected = dr.render(
        dr.sample_cv(), dr.RenderParams.for_recipient("US", None, accent="#00aa44")
    )
    assert (folder / "cv.html").read_text(encoding="utf-8") == expected
    assert "#00aa44" in expected and "#999999" not in expected


def test_a_version_with_no_recorded_palette_is_refused_and_writes_nothing(
    tmp_path: Path, stub_pdf: list[int | None], capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _version_dir(tmp_path, counts=None)
    for flags in ([], ["--accent", "#123456"]):
        assert dr._main(["version", str(folder), *flags]) == 2
        assert "no palette.json" in capsys.readouterr().err
    assert sorted(p.name for p in folder.iterdir()) == ["cv.json", "letter.json"]


def test_a_hand_accent_that_disagrees_with_the_measurement_is_refused(
    tmp_path: Path, stub_pdf: list[int | None], capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _version_dir(tmp_path)
    assert dr._main(["version", str(folder), "--accent", "#00aa00"]) == 2
    assert "not the measured accent #c0392b" in capsys.readouterr().err
    assert sorted(p.name for p in folder.iterdir()) == ["cv.json", "letter.json", "palette.json"]
    # the same colour, spelled in capitals, is the measurement and goes through
    assert dr._main(["version", str(folder), "--accent", "#C0392B"]) == 0


def test_an_unreadable_palette_record_is_refused(
    tmp_path: Path, stub_pdf: list[int | None], capsys: pytest.CaptureFixture[str]
) -> None:
    folder = _version_dir(tmp_path, counts=None)
    (folder / "palette.json").write_text(
        '{"schema_version": 1, "site": "s", "counts": {"rgb(1, 2, 3)": 4}}'
    )
    assert dr._main(["version", str(folder)]) == 2
    assert "cannot be read" in capsys.readouterr().err
    assert not (folder / "cv.html").exists()


def test_version_refuses_a_sent_version_and_writes_nothing(
    tmp_path: Path, stub_pdf: list[int | None]
) -> None:
    folder = _version_dir(tmp_path)
    (folder / "send").mkdir()
    (folder / "cv.pdf").write_bytes(b"what was sent")
    assert dr._main(["version", str(folder)]) == 2
    assert (folder / "cv.pdf").read_bytes() == b"what was sent"
    assert not (folder / "cv.html").exists()
    assert not (folder / "letter.html").exists()


def test_version_writes_nothing_when_a_later_document_fails(
    tmp_path: Path, stub_pdf: list[int | None]
) -> None:
    folder = _version_dir(tmp_path)
    (folder / "letter.json").write_text(json.dumps({"title": "x", "blocks": []}))
    (folder / "cv.pdf").write_bytes(b"old")
    assert dr._main(["version", str(folder)]) == 2
    assert (folder / "cv.pdf").read_bytes() == b"old"
    assert sorted(p.name for p in folder.iterdir()) == [
        "cv.json",
        "cv.pdf",
        "letter.json",
        "palette.json",
    ]


def test_version_writes_nothing_when_the_pdf_cannot_be_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(page_html: str, *, max_pages: int | None = None) -> tuple[bytes, int]:
        raise dr.RenderError("pdf needs the 'pdf' extra")

    monkeypatch.setattr(dr, "render_pdf", refuse)
    folder = _version_dir(tmp_path)
    assert dr._main(["version", str(folder)]) == 2
    assert sorted(p.name for p in folder.iterdir()) == ["cv.json", "letter.json", "palette.json"]


@pytest.mark.parametrize("missing", ["cv", "letter"])
def test_version_with_one_document_renders_it_and_names_the_other(
    tmp_path: Path,
    stub_pdf: list[int | None],
    capsys: pytest.CaptureFixture[str],
    missing: str,
) -> None:
    present = "letter" if missing == "cv" else "cv"
    folder = _version_dir(tmp_path, cv=missing != "cv", letter=missing != "letter")
    assert dr._main(["version", str(folder)]) == 0
    assert f"{missing}.json is missing" in capsys.readouterr().err
    assert (folder / f"{present}.html").is_file()
    assert not (folder / f"{missing}.html").exists()


def test_version_without_documents_is_a_refusal(tmp_path: Path) -> None:
    assert dr._main(["version", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_version_with_an_invalid_document_writes_nothing_for_it(tmp_path: Path) -> None:
    (tmp_path / "cv.json").write_text(json.dumps({"title": "x", "blocks": []}), encoding="utf-8")
    _version_dir(tmp_path, cv=False, letter=False)
    assert dr._main(["version", str(tmp_path)]) == 2
    assert sorted(p.name for p in tmp_path.iterdir()) == ["cv.json", "palette.json"]


@needs_engine
def test_version_makes_real_pdfs(tmp_path: Path) -> None:
    folder = _version_dir(tmp_path)
    assert dr._main(["version", str(folder), *FLAGS]) == 0
    for name in ("cv", "letter"):
        assert (folder / f"{name}.pdf").read_bytes().startswith(b"%PDF")
