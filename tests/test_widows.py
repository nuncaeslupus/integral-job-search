"""T143: widow detection, over constructed word boxes and over real rendered pages.

The constructed boxes pin the definition; the rendered tests pin that the
renderer's own line breaking is what gets measured. PDF tests need WeasyPrint.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from integral import document_render as dr
from integral import widows as w

_NO_ENGINE = importlib.util.find_spec("weasyprint") is None
needs_engine = pytest.mark.skipif(_NO_ENGINE, reason="WeasyPrint (the 'pdf' extra) is absent")

LH = 20.0  # line height
FULL = 600.0


def frag(text: str, x0: float, x1: float, row: float, page: int = 1) -> w.Fragment:
    return w.Fragment(page, x0, x1, 100.0 + row * LH, LH, text)


def paragraph(last: str, last_x1: float, *, x0: float = 80.0) -> list[w.Fragment]:
    return [
        frag("a full line of body text that runs", x0, x0 + FULL, 0),
        frag("another full line of body text here", x0, x0 + FULL, 1),
        frag(last, x0, last_x1, 2),
    ]


def test_a_true_widow_is_detected_with_page_ratio_and_text() -> None:
    found = w.find_widows(paragraph("the end", 80 + 60))
    assert len(found) == 1
    assert found[0].page == 1
    assert found[0].text == "the end"
    assert found[0].ratio == pytest.approx(60 / FULL)


def test_the_word_count_is_reported() -> None:
    assert w.find_widows(paragraph("one", 80 + 30))[0].words == 1
    assert w.find_widows(paragraph("one two three", 80 + 100))[0].words == 3


def test_a_last_line_that_is_long_enough_is_not_a_widow() -> None:
    assert w.find_widows(paragraph("a respectable closing line", 80 + 0.5 * FULL)) == []


def test_a_full_last_line_is_not_a_widow() -> None:
    assert w.find_widows(paragraph("the last line is full too", 80 + FULL)) == []


def test_a_short_line_after_a_short_line_is_not_a_widow() -> None:
    lines = [
        frag("a full line of body text that runs", 80, 80 + FULL, 0),
        frag("short", 80, 130, 1),
        frag("tiny", 80, 110, 2),
    ]
    assert w.find_widows(lines) == []


def test_a_line_followed_by_more_text_in_its_block_is_not_the_last() -> None:
    lines = [*paragraph("mid", 80 + 40), frag("the block goes on", 80, 80 + 300, 3)]
    assert w.find_widows(lines) == []


def test_a_one_line_item_after_a_gap_is_not_a_widow() -> None:
    lines = [
        frag("a full line of body text that runs", 80, 80 + FULL, 0),
        frag("next item", 80, 140, 1.5),  # a list item's margin puts it a gap away
    ]
    assert w.find_widows(lines) == []


def test_all_caps_heading_after_a_full_line_is_not_reported() -> None:
    lines = [
        frag("a full line of body text that runs", 80, 80 + FULL, 0),
        frag("EXPERIENCE", 80, 150, 1),
    ]
    assert w.find_widows(lines) == []
    lines[1] = frag("Experience", 80, 150, 1)
    assert len(w.find_widows(lines)) == 1


def test_a_grid_row_of_three_columns_is_not_a_false_positive() -> None:
    # Three cells share a vertical position. Read as one line the row spans the page;
    # read as columns, each cell's two lines are measured against its own column.
    cells = []
    for x0, tail in ((80.0, 110.0), (280.0, 90.0), (480.0, 120.0)):
        cells.append(frag("cell title text", x0, x0 + 150, 0))
        cells.append(frag("and more", x0, x0 + tail, 1))
    runs = w.runs_of(cells)
    assert len(runs) == 6
    assert {r.x0 for r in runs} == {80.0, 280.0, 480.0}
    assert w.find_widows(cells) == []


def test_a_real_widow_in_one_grid_column_is_still_found() -> None:
    cells = [
        frag("left cell full line of text", 80, 80 + 190, 0),
        frag("right cell", 300, 340, 0),
        frag("tail", 80, 100, 1),
        frag("right tail", 300, 330, 1),
    ]
    found = w.find_widows(cells)
    assert [f.text for f in found] == ["tail"]


def test_pages_are_measured_separately() -> None:
    lines = paragraph("the end", 80 + 60)
    moved = [lines[0], lines[1], w.Fragment(2, 80, 140, 100.0, LH, "the end")]
    assert w.find_widows(moved) == []


def test_inline_fragments_on_one_line_are_one_run() -> None:
    lines = [
        frag("a full line of body text that runs", 80, 80 + FULL, 0),
        frag("see ", 80, 100, 1),
        frag("link", 101, 125, 1),
    ]
    found = w.find_widows(lines)
    assert [(f.text, f.words) for f in found] == [("see link", 2)]


# -- on real pages ----------------------------------------------------------


def _document(last_sentence: str) -> dict[str, Any]:
    body = (
        "I am writing about the data engineering role you advertised, because the work you "
        "describe, moving a warehouse from nightly batches to streaming without losing the "
        "trust of the analysts who depend on it, is the work I have spent years doing and "
        "want to keep doing well"
    )
    return {
        "title": "Letter",
        "blocks": [{"type": "text", "text": f"{body} {last_sentence}"}],
    }


def _widows_of(document: dict[str, Any]) -> list[w.Widow]:
    return w.find_widows(dr.layout_fragments(dr.render(document)))


def _with_widow() -> dict[str, Any]:
    """The paragraph, lengthened one word at a time until its last line is a widow.

    Line breaking is the renderer's, so the word that tips it is found, not assumed.
    """
    for extra in range(1, 40):
        document = _document(" ".join(["indeed"] * extra))
        if _widows_of(document):
            return document
    raise AssertionError("no length of tail produced a widow")


@needs_engine
def test_a_rendered_paragraph_with_a_short_last_line_is_a_widow() -> None:
    found = _widows_of(_with_widow())
    assert len(found) == 1
    assert found[0].words <= 2
    assert found[0].ratio < w.MAX_RATIO


@needs_engine
def test_the_fixture_documents_have_no_widow_and_wrap() -> None:
    for document in (w.fixture_cv(), w.fixture_letter()):
        fragments = dr.layout_fragments(dr.render(document))
        assert w.find_widows(fragments) == []
        assert w.full_lines(fragments) >= 3


@needs_engine
def test_the_grid_and_headings_of_the_fixture_cv_are_not_reported() -> None:
    fragments = dr.layout_fragments(dr.render(w.fixture_cv()))
    runs = w.runs_of(fragments)
    texts = [r.text for r in runs]
    assert "EXPERIENCE" in texts or "Experience" in texts
    cells = [r for r in runs if r.text.split()[0] in {"Python", "SQL", "Cloud"}]
    assert len(cells) == 3, "the three grid cells were not split into three runs"
    assert w.find_widows(fragments) == []


@needs_engine
def test_the_render_fails_on_a_widow_and_names_the_word_count() -> None:
    page = dr.render(_with_widow())
    with pytest.raises(dr.RenderError, match=r"widow.*\d word\(s\)"):
        dr.render_pdf(page)
    data, pages = dr.render_pdf(page, check_widows=False)
    assert data.startswith(b"%PDF") and pages == 1


@needs_engine
def test_the_gate_measures_zero_over_real_lines() -> None:
    measured = w.measure()
    assert measured["gate_status"] == "measured"
    assert measured["widow_defects"] == 0
