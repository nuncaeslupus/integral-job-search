"""T142: parametrised CV and letter rendering.

Every contract in `integral.document_render` is paired with a negative control:
a page built by hand with the defect it exists for, which it must report. A
contract that has only ever been shown a clean page is a contract nobody has
seen fail (the family CLAUDE.md names as a check pinned against a proxy). The
PDF contracts need WeasyPrint (the optional `pdf` extra) and are skipped
without it, which is why the gate itself reads HTML/CSS only.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

from integral import ats, brand_palette, report_style
from integral import document_render as dr

_REPO_ROOT = Path(__file__).resolve().parents[1]
_NO_ENGINE = importlib.util.find_spec("weasyprint") is None
needs_engine = pytest.mark.skipif(
    _NO_ENGINE, reason="WeasyPrint (the 'pdf' extra) is not installed"
)

# Every ISO 3166-1 alpha-2 officially assigned code. Letter is five of them.
ISO = (  # noqa: SIM905
    "AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR "
    "BS BT BV BW BY BZ CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ "
    "EC EE EG EH ER ES ET FI FJ FK FM FO FR GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW "
    "GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP KE KG KH KI KM KN KP KR KW KY "
    "KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV "
    "MW MX MY MZ NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY "
    "QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ TC TD TF TG "
    "TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT "
    "ZA ZM ZW "
).split()


def _page(doc: dict[str, Any] | None = None, **params: Any) -> str:
    return dr.render(doc or dr.sample_cv(), dataclasses.replace(dr.RenderParams(), **params))


# -- the gate ---------------------------------------------------------------


def test_the_gate_measures_zero_over_a_real_denominator() -> None:
    measured = dr.measure()
    assert measured["gate_status"] == "measured"
    assert measured["defects"] == []
    assert measured["document_render_defects"] == 0


def test_the_committed_evidence_is_what_the_gate_measures() -> None:
    committed = json.loads((_REPO_ROOT / "status" / "evidence" / "T142.json").read_text())
    assert committed == json.loads(json.dumps(dr.measure()))


def test_too_few_contracts_is_unmeasured_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dr, "MINIMUM_CONTRACTS_EVALUATED", 10_000)
    measured = dr.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["document_render_defects"] == -1


# -- page size: derived, not asked --------------------------------------------


def test_letter_for_exactly_the_five_countries_and_a4_for_every_other_one() -> None:
    letter = {c for c in ISO if dr.page_size_for(c) == "Letter"}
    assert letter == {"US", "CA", "MX", "PH", "CL"} == set(dr.LETTER_COUNTRIES)
    assert {dr.page_size_for(c) for c in ISO if c not in letter} == {"A4"}


@pytest.mark.parametrize("raw", ["us", " US ", "Us", "cl\n"])
def test_the_country_is_read_the_way_a_person_would_type_it(raw: str) -> None:
    assert dr.page_size_for(raw) == "Letter"


@pytest.mark.parametrize("raw", [None, "", "  ", "Atlantis", "USA", "United States"])
def test_an_unknown_country_is_a4_never_an_error(raw: str | None) -> None:
    assert dr.page_size_for(raw) == "A4"


def test_the_page_size_reaches_the_page_rule() -> None:
    assert "size: 215.9mm 279.4mm" in _page(page_size="Letter")
    assert "size: 210mm 297mm" in _page(page_size="A4")


# -- the parameter set is closed, and every member is varied -----------------


def test_there_are_five_parameters_and_nothing_else() -> None:
    assert [f.name for f in dataclasses.fields(dr.RenderParams)] == [
        "page_size",
        "accent",
        "margins_mm",
        "body_size_pt",
        "language",
    ]


def test_every_parameter_is_varied_whatever_it_is_called() -> None:
    names = {f.name for f in dataclasses.fields(dr.RenderParams)}
    assert set(dr.variations()) == names
    for name, (one, other) in dr.variations().items():
        assert _page(**{name: one}) != _page(**{name: other}), name


def test_a_parameter_added_without_a_variation_fails_the_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclasses.dataclass(frozen=True)
    class Wider(dr.RenderParams):
        gutter: float = 0.0

    monkeypatch.setattr(dr, "RenderParams", Wider)
    assert any("differ" in d for d in dr.contract_every_parameter_matters())


# -- the type scale is one number ---------------------------------------------


def test_exactly_one_font_size_is_absolute_and_it_is_the_body_size() -> None:
    sizes = dr.font_sizes(_page(body_size_pt=11.0))
    assert [s for s in sizes if not s.endswith("em")] == ["11pt"]
    assert len(sizes) > 5


def test_the_type_scale_moves_with_one_number() -> None:
    assert _page(body_size_pt=10.0).replace("10pt", "11pt") == _page(body_size_pt=11.0)


def test_negative_a_second_absolute_size_is_reported() -> None:
    params = dr.RenderParams()
    drifted = _page().replace(".contact { font-size: 0.9em", ".contact { font-size: 8.6pt")
    assert drifted != _page()
    assert dr.contract_parameters(drifted, params)


def test_every_small_size_is_a_fraction_of_the_body_not_larger_than_it_by_accident() -> None:
    # The drift this exists for: small cells ended up *smaller than the body* in
    # absolute terms after the body grew. In em they stay in proportion.
    for size in (10.0, 10.5, 13.0):
        absolute = [s for s in dr.font_sizes(_page(body_size_pt=size)) if s.endswith("pt")]
        assert absolute == [f"{size:g}pt"]


# -- margins and line length ---------------------------------------------------


def test_the_default_line_length_is_readable_on_both_papers() -> None:
    for size in dr.PAGE_SIZES:
        lo, hi = dr.LINE_CHARS
        assert lo <= dr.line_chars(dr.RenderParams(page_size=size)) <= hi


def test_a_margin_that_makes_the_lines_unreadable_is_refused() -> None:
    with pytest.raises(dr.RenderError, match="characters a line"):
        _page(margins_mm=10.0, body_size_pt=8.0)


@pytest.mark.parametrize(
    "bad",
    [
        {"margins_mm": 9.9},
        {"margins_mm": 40.1},
        {"body_size_pt": 7.9},
        {"body_size_pt": 14.1},
        {"page_size": "A3"},
        {"accent": "orange"},
        {"accent": "#ff671"},
        {"accent": "#ff671d; } * { display:none"},
        {"language": "english please"},
        {"language": '"><script>'},
    ],
)
def test_a_bad_parameter_is_refused(bad: dict[str, Any]) -> None:
    with pytest.raises(dr.RenderError):
        _page(**bad)


def test_the_margin_reaches_the_page_rule() -> None:
    assert "margin: 26mm" in _page(margins_mm=26.0)


# -- the accent ---------------------------------------------------------------


def test_the_accent_is_normalised() -> None:
    assert dr.normalise_accent("#F60") == "#ff6600"
    assert dr.normalise_accent(" #FF671D ") == "#ff671d"


def test_the_default_accent_is_the_employers_own() -> None:
    site = {"#ff671d": 31, "#ffffff": 80, "#111217": 40}
    assert dr.RenderParams.for_recipient("SE", site).accent == "#ff671d"


def test_an_unread_site_gives_the_neutral_accent_not_a_guess() -> None:
    assert dr.RenderParams.for_recipient("SE", None).accent == brand_palette.NEUTRAL_ACCENT
    assert dr.RenderParams.for_recipient("SE", {"#ffffff": 5}).accent == (
        brand_palette.NEUTRAL_ACCENT
    )


def test_the_authors_choice_overrides_the_derived_defaults() -> None:
    got = dr.RenderParams.for_recipient("US", {"#ff671d": 9}, accent="#123abc", page_size="A4")
    assert (got.accent, got.page_size) == ("#123abc", "A4")


@pytest.mark.parametrize("accent", dr.READABLE_ACCENTS)
@pytest.mark.parametrize("size", dr.PAGE_SIZES)
def test_two_accents_differ_only_by_the_colour(accent: str, size: str) -> None:
    other = "#0a6e4f"
    assert dr.swap_accent(accent, other, dr.RenderParams(page_size=size)) == []


def test_negative_a_hard_coded_colour_is_found_by_the_swap() -> None:
    a = _page(accent="#123abc")
    stuck = a.replace(
        "border-bottom: 0.15em solid var(--accent)", "border-bottom: 0.15em solid #123abc", 1
    )
    assert stuck.replace("#123abc", "#8a2be2") != _page(accent="#8a2be2")


def test_negative_a_colour_literal_in_a_rule_is_reported() -> None:
    page = _page().replace("color: var(--muted)", "color: #ff0000", 1)
    assert dr.colour_literals_outside_tokens(page) == ["#ff0000"]
    assert dr.contract_accent(page, dr.RenderParams())


def test_the_template_names_a_colour_only_by_token() -> None:
    assert dr.colour_literals_outside_tokens(_page()) == []


def test_every_named_accent_place_is_reached() -> None:
    assert dr.accent_places_reached(_page()) == dict.fromkeys(dr.ACCENT_PLACES, True)


@pytest.mark.parametrize("place", sorted(dr.ACCENT_PLACES))
def test_negative_an_unaccented_place_is_reported(place: str) -> None:
    selector, prop, token = dr.ACCENT_PLACES[place]
    page = _page()

    def unaccent(match: re.Match[str]) -> str:
        head, _, body = match.group(0).partition("{")
        if " ".join(head.split()) != selector:
            return match.group(0)
        pattern = rf"({re.escape(prop)}\s*:[^;}}]*){re.escape(token)}"
        return head + "{" + re.sub(pattern, r"\1var(--ink)", body)

    broken = re.sub(r"[^{}]+\{[^{}]*\}", unaccent, page)
    assert broken != page
    reached = dr.accent_places_reached(broken)
    assert reached[place] is False
    assert [p for p, ok in reached.items() if not ok] == [place]  # and no other place moved


@pytest.mark.parametrize("accent", ["#ff671d", "#ffd400", "#999999", "#123abc"])
def test_the_accent_text_reaches_aa_and_the_decoration_stays_the_accent(accent: str) -> None:
    assert dr.contract_text_accent(accent) == []


def test_negative_an_undarkened_accent_text_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(brand_palette, "text_variant", lambda colour, paper, minimum=4.5: colour)
    assert dr.contract_text_accent("#ffd400")


def test_the_accent_text_is_darkened_only_when_it_has_to_be() -> None:
    orange = _page(accent="#ff671d")
    assert dr.effective_token(orange, "accent") == "#ff671d"
    assert dr.effective_token(orange, "accent-text") != "#ff671d"
    blue = _page(accent="#123abc")
    assert dr.effective_token(blue, "accent-text") == "#123abc"


def test_the_shells_own_accent_token_does_not_win() -> None:
    page = _page(accent="#ff671d")
    assert dr.effective_token(page, "accent") == "#ff671d"
    assert page.count("--accent:") >= 2  # the shell's, then ours: ours is last


# -- drawn things: the stylesheet never reaches inside an SVG ------------------


def test_every_svg_paint_is_a_literal_attribute_equal_to_the_accent() -> None:
    page = _page(accent="#ff671d")
    paints = dr.svg_paints(page)
    assert paints and dr.drawn_elements(page) == 2
    assert {v for _, v in paints} == {"#ff671d"}


def test_the_accent_reaches_the_svg_in_every_project_with_a_live_link() -> None:
    page = _page(accent="#abcdef")
    assert page.count('fill="#abcdef"') == 2  # the header bar and the one LIVE dot


def test_negative_an_svg_filled_from_the_stylesheet_is_reported() -> None:
    page = _page().replace('fill="#999999"', 'fill="var(--accent)"', 1)
    problems = dr.contract_accent(page, dr.RenderParams())
    assert any("svg fill" in p for p in problems)


def test_negative_an_svg_with_no_paint_does_not_pass_by_having_nothing_to_check() -> None:
    page = re.sub(r'\s(?:fill|stroke)="[^"]*"', "", _page())
    assert any("not exercised" in p for p in dr.contract_accent(page, dr.RenderParams()))


# -- text passes through as written -------------------------------------------


def test_text_fields_pass_through_and_only_href_is_escaped() -> None:
    page = _page()
    assert "Education &amp; certifications" in page
    assert "<em>p95</em>" in page
    assert "https://example.org/repo?a=1&amp;b=2" in page
    assert not re.search(r"&amp;amp;|&AMP;", page)


def test_no_python_capitalisation_touches_markup() -> None:
    assert "text-transform: uppercase" in _page()
    assert "Education &amp; certifications" in _page()  # capitals are CSS's, applied to glyphs


def test_every_text_field_of_every_block_is_inline_html() -> None:
    marker = "<i>MARK</i>"
    for doc in (dr.sample_cv(), dr.sample_letter()):
        for block in doc["blocks"]:
            for key, value in block.items():
                if key == "type" or key in ("href", "live"):
                    continue
                probe = json.loads(json.dumps(doc))
                target = probe["blocks"][doc["blocks"].index(block)]
                if isinstance(value, str):
                    target[key] = marker
                elif isinstance(value, list) and value and isinstance(value[0], str):
                    target[key] = [marker]
                else:
                    continue
                assert marker in dr.render(probe), (block["type"], key)


def test_a_javascript_href_is_refused_and_a_quote_in_one_is_escaped() -> None:
    doc: dict[str, Any] = {
        "title": "t",
        "blocks": [{"type": "project", "name": "n", "text": "t", "href": "javascript:1"}],
    }
    with pytest.raises(dr.RenderError):
        dr.render(doc)
    doc["blocks"][0]["href"] = 'https://x.test/?q="a"'
    with pytest.raises(dr.RenderError):  # a quote ends the attribute: refused outright
        dr.render(doc)


# -- projects: two links, two claims -------------------------------------------


@pytest.mark.parametrize(("href", "live"), [(True, True), (True, False), (False, True)])
def test_live_is_shown_exactly_when_a_live_link_is_given(href: bool, live: bool) -> None:
    project: dict[str, object] = {"type": "project", "name": "p", "text": "t"}
    if href:
        project["href"] = "https://r.test/p"
    if live:
        project["live"] = "https://l.test/p"
    body = dr.render({"title": "x", "blocks": [project]})
    body = body[body.index("<body") :]
    assert body.count("LIVE") == int(live)
    assert ("https://r.test/p" in body) is href
    assert ("https://l.test/p" in body) is live


def test_the_two_links_are_different_links() -> None:
    body = _page()
    assert 'href="https://example.org/demo"' in body
    assert body.count('class="live"') == 1


# -- the vocabulary is closed -------------------------------------------------


def test_the_fixtures_cover_every_block_in_the_vocabulary() -> None:
    seen = {b["type"] for d in (dr.sample_cv(), dr.sample_letter()) for b in d["blocks"]}
    assert seen == set(dr.BLOCKS)
    assert set(dr.BLOCKS) == {
        "header", "summary", "section", "job", "project", "bullets", "grid", "board",
        "letter", "to", "text", "sign",
    }  # fmt: skip


def test_every_block_renders_something_unless_it_is_an_empty_dateline() -> None:
    for doc in (dr.sample_cv(), dr.sample_letter()):
        for block in doc["blocks"]:
            assert dr.render({"title": "t", "blocks": [block]}).count("<body") == 1


@pytest.mark.parametrize(
    "doc",
    [
        {"title": "t", "blocks": [{"type": "script", "text": "x"}]},
        {"title": "t", "blocks": [{"type": "summary", "text": "x", "style": "y"}]},
        {"title": "t", "blocks": [{"type": "job", "role": "r"}]},
        {"title": "t", "blocks": [{"type": "summary", "text": "x"}, {"type": "text", "text": "y"}]},
        {"title": "t", "blocks": []},
        {"title": "t", "blocks": [{"type": "summary", "text": 3}]},
        {"title": "t", "blocks": [{"type": "bullets", "items": "not a list"}]},
        {"title": "t", "blocks": [{"type": "grid", "cells": [{"text": "x", "style": "y"}]}]},
        {"title": "t", "blocks": [{"type": "summary", "text": "x"}], "extra": 1},
    ],
)
def test_a_document_outside_the_vocabulary_is_refused(doc: dict[str, Any]) -> None:
    with pytest.raises(dr.RenderError):
        dr.render(doc)


def test_a_page_carries_no_external_reference_and_the_language_is_the_documents_own() -> None:
    page = _page(language="ca")
    assert '<html lang="ca">' in page
    assert report_style.external_references(page) == []


# -- the command line ---------------------------------------------------------


def test_the_command_renders_a_document_for_a_country(tmp_path: Path) -> None:
    source = tmp_path / "cv.json"
    source.write_text(json.dumps(dr.sample_cv()), encoding="utf-8")
    out = tmp_path / "cv.html"
    code = dr._main(
        ["render", str(source), "--country", "US", "--accent", "#123abc", "--output", str(out)]
    )
    assert code == 0
    page = out.read_text(encoding="utf-8")
    assert "size: 215.9mm" in page and "--accent: #123abc" in page


def test_the_command_refuses_with_a_message_not_a_traceback(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text('{"title": "t", "blocks": [{"type": "nope"}]}', encoding="utf-8")
    assert dr._main(["render", str(source), "--output", str(tmp_path / "o.html")]) == 2


# -- the PDF -------------------------------------------------------------------


def test_without_the_engine_a_pdf_is_a_named_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "weasyprint", None)
    with pytest.raises(dr.RenderError, match="pdf"):
        dr.render_pdf(_page())


@needs_engine
@pytest.mark.parametrize("size", dr.PAGE_SIZES)
def test_the_cv_fits_its_page_budget_on_either_paper(size: str) -> None:
    _, pages = dr.render_pdf(_page(page_size=size), max_pages=dr.CV_PAGE_BUDGET)
    assert pages <= dr.CV_PAGE_BUDGET


@needs_engine
def test_a_cv_that_outgrows_its_budget_fails_loudly() -> None:
    doc = dr.sample_cv()
    doc["blocks"] += [{"type": "bullets", "items": ["line " * 12] * 12} for _ in range(8)]
    with pytest.raises(dr.RenderError, match="budget"):
        dr.render_pdf(dr.render(doc), max_pages=dr.CV_PAGE_BUDGET)


def _pdf_with_text(text: str) -> bytes:
    doc = dr.sample_cv()
    doc["blocks"] = [{"type": "summary", "text": text}, *doc["blocks"]]
    return dr.render_pdf(dr.render(doc))[0]


def _streams(pdf: bytes) -> bytes:
    """Every stream of the PDF, Flate-decoded where it decodes, concatenated."""
    import zlib

    out = b""
    for raw in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL):
        try:
            out += zlib.decompress(raw)
        except zlib.error:
            out += raw
    return out


@needs_engine
@pytest.mark.parametrize("kind", ["attachment", "svg-file", "svg-http"])
def test_the_pdf_engine_fetches_nothing(
    tmp_path: Path, kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Text fields pass through as HTML; the engine must not read files or the network."""
    import socket

    from weasyprint.urls import URLFetcher

    fetched: list[str] = []

    def spy(self: Any, url: str, headers: Any = None) -> Any:
        fetched.append(url)
        raise ValueError("spy")

    monkeypatch.setattr(URLFetcher, "fetch", spy)  # the engine's own fetching
    canary = tmp_path / "canary.txt"
    canary.write_bytes(b"CANARY-SECRET-0451")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    text = {
        "attachment": f'<a rel="attachment" href="file://{canary}">x</a>',
        "svg-file": f'<svg width="10" height="10"><image href="file://{canary}" '
        'width="10" height="10"/></svg>',
        "svg-http": f'<svg width="10" height="10"><image href="http://127.0.0.1:{port}/x.png" '
        'width="10" height="10"/></svg>',
    }[kind]
    try:
        pdf = _pdf_with_text(text)
        with pytest.raises(BlockingIOError):
            listener.accept()  # nothing connected
    finally:
        listener.close()
    assert fetched == []
    assert b"CANARY-SECRET-0451" not in pdf
    assert b"CANARY-SECRET-0451" not in _streams(pdf)
    assert b"/EmbeddedFile" not in pdf and b"/EmbeddedFile" not in _streams(pdf)


@needs_engine
def test_the_cli_refuses_an_over_budget_cv(tmp_path: Path) -> None:
    doc = dr.sample_cv()
    doc["blocks"] += [{"type": "bullets", "items": ["line " * 12] * 12} for _ in range(8)]
    source = tmp_path / "cv.json"
    source.write_text(json.dumps(doc), encoding="utf-8")
    args = ["render", str(source), "--output", str(tmp_path / "o.html")]
    assert dr._main([*args, "--pdf", str(tmp_path / "o.pdf")]) == 2
    assert not (tmp_path / "o.pdf").exists()


@pytest.mark.parametrize(
    "block", [{"type": ["x"]}, {"type": {"a": 1}}, {"type": 3}, {"type": None}]
)
def test_a_non_text_block_type_is_a_refusal_not_a_traceback(block: dict[str, Any]) -> None:
    with pytest.raises(dr.RenderError):
        dr.validate({"title": "t", "blocks": [block]})


@pytest.mark.parametrize(
    "params",
    [
        dr.RenderParams(margins_mm="22"),  # type: ignore[arg-type]
        dr.RenderParams(body_size_pt="10"),  # type: ignore[arg-type]
        dr.RenderParams(margins_mm=None),  # type: ignore[arg-type]
        dr.RenderParams(margins_mm=True),
        dr.RenderParams(page_size=["A4"]),  # type: ignore[arg-type]
    ],
)
def test_parameters_of_the_wrong_type_are_a_refusal(params: dr.RenderParams) -> None:
    with pytest.raises(dr.RenderError):
        params.checked()


@needs_engine
def test_the_pdf_page_size_is_the_one_asked_for() -> None:
    import io

    PdfReader = pytest.importorskip("pypdf").PdfReader

    for size, width in (("A4", 595), ("Letter", 612)):
        pdf, _ = dr.render_pdf(_page(page_size=size))
        box = PdfReader(io.BytesIO(pdf)).pages[0].mediabox
        assert round(float(box.width)) == width


@needs_engine
@pytest.mark.parametrize("size", dr.PAGE_SIZES)
def test_the_text_layer_is_one_integral_ats_accepts(tmp_path: Path, size: str) -> None:
    pdf, _ = dr.render_pdf(_page(page_size=size))
    path = tmp_path / "cv.pdf"
    path.write_bytes(pdf)
    report = ats.check_document(path)
    assert report["violations"] == []
    text = ats.text_layer(path)
    assert "ana@example.org" in text
    assert "EDUCATION & CERTIFICATIONS" in text
    assert "&AMP;" not in text and "&amp;" not in text


@needs_engine
def test_the_letter_text_layer_reads_in_order(tmp_path: Path) -> None:
    pdf, pages = dr.render_pdf(dr.render(dr.sample_letter()))
    path = tmp_path / "letter.pdf"
    path.write_bytes(pdf)
    text = " ".join(ats.text_layer(path).split())
    assert pages == 1
    assert text.index("Hiring team") < text.index("data role") < text.index("Ana Perez")


@needs_engine
def test_the_accent_reaches_the_pdf(tmp_path: Path) -> None:
    import io

    PdfReader = pytest.importorskip("pypdf").PdfReader

    pdf, _ = dr.render_pdf(_page(accent="#123abc"))
    stream = b"".join(
        p.get_contents().get_data()
        for p in PdfReader(io.BytesIO(pdf)).pages
        if p.get_contents() is not None
    )
    want = tuple(c / 255 for c in (0x12, 0x3A, 0xBC))
    found = {
        op: [
            triple
            for triple in re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) " + op, stream)
            if all(abs(float(v) - w) < 0.002 for v, w in zip(triple, want, strict=True))
        ]
        for op in (b"rg", b"RG")
    }
    # fill: section titles' text, the SVG bar and dot; stroke: the heading rules
    assert found[b"rg"], found
    assert found[b"RG"], found
