"""T191: `document_render version <dir>` renders a version directory's JSON documents.

Constructed fixtures only (`sample_cv` / `sample_letter`). The HTML must equal
what `render` returns for the same country, so a CLI that ignored `--country`
or `--accent` is caught by comparing against the library, not by grepping.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from integral import document_render as dr

needs_engine = pytest.mark.skipif(
    importlib.util.find_spec("weasyprint") is None,
    reason="WeasyPrint (the 'pdf' extra) is not installed: PDF half of T191 NOT exercised",
)


def _version_dir(tmp_path: Path) -> Path:
    (tmp_path / "cv.json").write_text(json.dumps(dr.sample_cv()), encoding="utf-8")
    (tmp_path / "letter.json").write_text(json.dumps(dr.sample_letter()), encoding="utf-8")
    return tmp_path


@needs_engine
def test_version_renders_html_and_pdf_beside_each_document(tmp_path: Path) -> None:
    folder = _version_dir(tmp_path)
    code = dr._main(["version", str(folder), "--country", "US", "--accent", "#c0392b"])
    assert code == 0
    params = dr.RenderParams.for_recipient("US", None, accent="#c0392b", language="en")
    for name, doc in (("cv", dr.sample_cv()), ("letter", dr.sample_letter())):
        assert (folder / f"{name}.html").read_text(encoding="utf-8") == dr.render(doc, params)
        assert (folder / f"{name}.pdf").read_bytes().startswith(b"%PDF")
    other = dr.RenderParams.for_recipient("ES", None, language="en")
    assert (folder / "cv.html").read_text(encoding="utf-8") != dr.render(dr.sample_cv(), other)


def test_version_without_documents_is_a_refusal(tmp_path: Path) -> None:
    assert dr._main(["version", str(tmp_path)]) == 2
    assert list(tmp_path.iterdir()) == []


def test_version_with_an_invalid_document_writes_nothing_for_it(tmp_path: Path) -> None:
    (tmp_path / "cv.json").write_text(json.dumps({"title": "x", "blocks": []}), encoding="utf-8")
    assert dr._main(["version", str(tmp_path)]) == 2
    assert not (tmp_path / "cv.html").exists()
    assert not (tmp_path / "cv.pdf").exists()
