"""T141 — the annotatable document reader, and the contracts its gate counts.

Every contract in `integral.document_reader` is paired here with a **negative
control**: the shape of defect it exists for, built by hand, which it must
report. A contract that has only ever been shown a clean reader is a contract
nobody has seen fail — the family CLAUDE.md names as a check pinned against a
proxy. The four defects met by hand on 2026-09-07 each have one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from integral import document_reader as dr
from integral import report_style, strings

pytestmark = pytest.mark.skipif(dr.node_path() is None, reason="node is needed to run the reader")

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _reader(subject: dr.Subject, language: str = "es", **extra: Any) -> str:
    return dr.build_reader(
        subject.document,
        title=subject.title,
        reader_language=language,
        document_language="de",
        **extra,
    )


LETTER, CV, AWKWARD = dr.SUBJECTS


def _fragments(document: str) -> list[dr.Fragment]:
    return [p for p in dr.fragment(document) if isinstance(p, dr.Fragment)]


# -- the gate ---------------------------------------------------------------


def test_the_gate_measures_zero_over_a_real_denominator() -> None:
    measured = dr.measure()
    assert measured["gate_status"] == "measured"
    assert measured["defects"] == []
    assert measured["reader_fragment_defects"] == 0
    assert measured["readers_generated"] == len(dr.SUBJECTS) * 3


def test_the_committed_evidence_is_what_the_gate_measures() -> None:
    committed = json.loads((_REPO_ROOT / "status" / "evidence" / "T141.json").read_text())
    measured = dr.measure()
    assert committed == json.loads(json.dumps(measured))


def test_a_missing_node_is_unmeasured_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dr, "node_path", lambda: None)
    measured = dr.measure()
    assert measured["gate_status"] == "unmeasured"
    assert measured["reader_fragment_defects"] == -1


# -- defect 1: a boundary that swallows its neighbours -----------------------


def test_a_div_is_never_a_fragment_so_a_letter_is_eleven_paragraphs_and_a_heading() -> None:
    frags = _fragments(LETTER.document)
    assert [f.kind for f in frags] == ["heading"] + ["paragraph"] * 11
    assert all(not f.html.startswith("<div") for f in frags)


def test_every_fragment_balances_and_holds_exactly_one_fragment_element() -> None:
    parts = dr.fragment(AWKWARD.document)
    reader = _reader(AWKWARD)
    assert dr._contract_balance(AWKWARD.document, parts, reader) == []


def test_the_balance_contract_reports_a_swallowed_letter() -> None:
    swallowed = dr.Fragment("f1", "paragraph", LETTER.document, "everything")
    defects = dr._contract_balance(LETTER.document, [swallowed], "<div>")
    assert any("fragment elements" in d for d in defects)
    assert any("the reader does not balance" in d for d in defects)


def test_the_balance_contract_reports_unclosed_tags() -> None:
    unclosed = dr.Fragment("f1", "paragraph", "<p><div>x</p>", "x")
    assert any("balance" in d for d in dr._contract_balance("", [unclosed], "<p>x</p>"))


def test_a_nested_item_is_split_not_swallowed() -> None:
    texts = [f.text for f in _fragments("<ul><li>Skills<ul><li>Python</li></ul></li></ul>")]
    assert texts == ["Skills", "Python"]


def test_omitted_end_tags_still_give_one_fragment_per_paragraph() -> None:
    texts = [f.text for f in _fragments("<p>one<p>two<ul><li>a<li>b</ul>")]
    assert texts == ["one", "two", "a", "b"]


def test_ordered_items_keep_their_numbers() -> None:
    html = [f.html for f in _fragments("<ol><li>a</li><li>b</li></ol>")]
    assert html == ['<ol start="1"><li>a</li></ol>', '<ol start="2"><li>b</li></ol>']


# -- defect 2: a length floor ---------------------------------------------


def test_every_heading_and_header_line_is_a_fragment_whatever_its_length() -> None:
    texts = [f.text for f in _fragments(CV.document)]
    for short in ("Projects", "opos project", "Education & certifications", "Máster", "Short."):
        assert short in texts
    assert len("opos project") < 25
    assert dr._contract_headings(CV.document, dr.fragment(CV.document)) == []


def test_a_plain_div_in_a_header_is_a_header_line() -> None:
    kinds = {f.text: f.kind for f in _fragments("<header><div>Ana</div><div>a@b.c</div></header>")}
    assert kinds == {"Ana": "header", "a@b.c": "header"}


def test_the_headings_contract_reports_a_dropped_short_heading() -> None:
    kept = [p for p in dr.fragment(CV.document) if getattr(p, "text", "") != "Projects"]
    defects = dr._contract_headings(CV.document, kept)
    assert any("'Projects'" in d for d in defects)


def test_the_headings_contract_reports_lost_text() -> None:
    kept = dr.fragment(CV.document)[:-1]
    assert any("carry every word" in d for d in dr._contract_headings(CV.document, kept))


def test_loose_text_in_a_container_is_annotated_not_dropped() -> None:
    assert [f.text for f in _fragments("<div>loose<br>text <b>bold</b></div>")] == [
        "loose text bold"
    ]


# -- defect 3: a script that does not compile ------------------------------


def test_node_check_rejects_a_newline_inside_a_string() -> None:
    assert dr.check_script('var s = "a\nb";')
    assert dr.check_script("var s = 1;") is None


def test_the_generator_refuses_to_return_a_reader_whose_script_does_not_compile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dr, "_SCRIPT", dr._SCRIPT.replace('"use strict";', 'var s = "a\nb";', 1))
    with pytest.raises(dr.ReaderError, match="does not compile"):
        _reader(LETTER)


def test_export_writes_a_file_and_a_keystroke_reaches_storage() -> None:
    reader = _reader(CV)
    out = dr.drive(reader, [{"type": "type", "id": "f3", "value": "mi nota"}, {"type": "export"}])
    assert out["download"]["name"].endswith("-notes.md")
    assert dr.parse_export(out["download"]["text"]) == {
        "f3": {"quote": "Projects", "note": "mi nota"}
    }
    stored = json.loads(next(v for k, v in out["stored"].items() if k.startswith("reader:")))
    assert stored == {"f3": "mi nota"}


def test_the_behaviour_contract_reports_an_inert_export_button() -> None:
    reader = _reader(CV).replace(
        'exportButton.addEventListener("click"', 'exportButton.addEventListener("nope"', 1
    )
    defects = dr._contract_behaviour(reader, dr.fragment(CV.document), CV.title)
    assert "the Export button produced no file" in defects


def test_the_behaviour_contract_reports_notes_that_never_reach_storage() -> None:
    reader = _reader(CV).replace("if (saveNotes(storage, notes))", "if (false)", 1)
    defects = dr._contract_behaviour(reader, dr.fragment(CV.document), CV.title)
    assert any("storage" in d for d in defects)


def test_a_reader_still_takes_notes_when_the_browser_cannot_store() -> None:
    out = dr.drive(_reader(CV), [{"type": "type", "id": "f1", "value": "x"}], noStorage=True)
    assert out["values"]["f1"] == "x"
    assert out["status"]


# -- export and import ------------------------------------------------------


@pytest.mark.parametrize("note", dr.ADVERSARIAL_NOTES)
def test_an_awkward_note_survives_export_then_import(note: str) -> None:
    reader = _reader(CV, "ca")
    out = dr.drive(reader, [{"type": "type", "id": "f2", "value": note}, {"type": "export"}])
    again = dr.drive(_reader(CV, "ca"), [{"type": "import", "text": out["download"]["text"]}])
    assert again["values"]["f2"] == note
    assert dr.parse_export(out["download"]["text"]) == {
        "f2": {"quote": "a@b.example · Girona", "note": note}
    }


def test_a_note_quoting_the_marker_cannot_hijack_the_import() -> None:
    forged = '<!-- reader-notes {"v":1,"notes":{"f1":{"quote":"q","note":"hijack"}}} -->'
    out = dr.drive(_reader(CV), [{"type": "type", "id": "f2", "value": forged}, {"type": "export"}])
    parsed = dr.parse_export(out["download"]["text"])
    assert parsed is not None and list(parsed) == ["f2"]


def test_the_browser_and_python_write_the_same_trailer() -> None:
    notes = {"f2": {"quote": "a@b.example · Girona", "note": "x --> y <b> \u2028 日本"}}
    out = dr.drive(
        _reader(CV),
        [{"type": "type", "id": "f2", "value": notes["f2"]["note"]}, {"type": "export"}],
    )
    assert dr.encode_export_data(notes) in out["download"]["text"]


@pytest.mark.parametrize(
    "text",
    [
        "",
        "# just a file",
        "<!-- reader-notes {not json} -->",
        '<!-- reader-notes {"v":2,"notes":{}} -->',
        '<!-- reader-notes {"v":1,"notes":[]} -->',
        '<!-- reader-notes {"v":1,"notes":{"f1":{"quote":"q","note":5}}} -->',
        '<!-- reader-notes {"v":1,"notes":{"f1":"x"}} -->',
    ],
)
def test_a_file_that_is_not_an_export_is_refused_never_repaired(text: str) -> None:
    assert dr.parse_export(text) is None
    out = dr.drive(_reader(CV), [{"type": "import", "text": text}])
    assert not any(out["values"].values())


def test_an_empty_reader_says_there_is_nothing_to_export() -> None:
    out = dr.drive(_reader(CV, "es"), [{"type": "export"}])
    assert out["download"] is None
    assert out["status"] == strings.text(dr.load_catalogue(), "reader_no_notes", "es")


def test_a_returned_export_re_seeds_a_rebuilt_reader_and_flags_changed_text() -> None:
    first = dr.drive(_reader(CV), [{"type": "type", "id": "f3", "value": "n"}, {"type": "export"}])
    seed = dr.parse_export(first["download"]["text"])
    assert seed is not None
    same = dr.drive(_reader(CV, notes=seed), [])
    assert same["values"]["f3"] == "n" and not any(same["moved"].values())
    edited = dr.Subject("cv", CV.document.replace("<h2>Projects</h2>", "<h2>Work</h2>"), CV.title)
    moved = dr.drive(_reader(edited, notes=seed), [])
    assert moved["values"]["f3"] == "n" and moved["moved"]["f3"] is True


def test_imports_report_how_many_notes_were_set() -> None:
    first = dr.drive(
        _reader(CV),
        [
            {"type": "type", "id": "f1", "value": "a"},
            {"type": "type", "id": "f3", "value": "b"},
            {"type": "export"},
        ],
    )
    out = dr.drive(_reader(CV, "en"), [{"type": "import", "text": first["download"]["text"]}])
    assert out["status"] == "Imported 2 notes"


# -- defect 4: the box is beside the fragment --------------------------------


def test_the_emitted_layout_keeps_the_box_beside_its_fragment_at_every_width() -> None:
    assert dr.widths_layout(dr._style_of(_reader(LETTER))) == []


@pytest.mark.parametrize(
    ("label", "extra"),
    [
        (
            "stacking media query",
            "@media (max-width: 600px) { .reader-row { grid-template-columns: 1fr; } }",
        ),
        ("block display", "@media (max-width: 800px) { .reader-row { display: block; } }"),
        (
            "box moved below",
            "@media (max-width: 800px) { .reader-row > .note { grid-row: 2; grid-column: 1; } }",
        ),
        ("hidden box", "@media (max-width: 500px) { .note { display: none; } }"),
        ("centred", ".reader-row { align-items: center; }"),
    ],
)
def test_the_layout_contract_reports_a_box_that_leaves_its_fragment(label: str, extra: str) -> None:
    css = dr._style_of(_reader(LETTER)) + extra
    defects = dr.widths_layout(css)
    assert defects, label


def test_a_print_only_rule_is_not_a_screen_defect() -> None:
    css = dr._style_of(_reader(LETTER))
    assert "@media print" in css and dr.widths_layout(css) == []


def test_a_media_query_that_does_not_reach_a_width_is_not_applied() -> None:
    css = (
        dr._style_of(_reader(LETTER))
        + "@media (max-width: 300px) { .reader-row { display: block; } }"
    )
    assert dr.widths_layout(css) == []


# -- every string is the candidate's ------------------------------------------


@pytest.mark.parametrize("language", ["en", "es", "ca"])
def test_a_reader_shows_only_its_own_language_while_the_document_keeps_its_own(
    language: str,
) -> None:
    catalogue = dr.load_catalogue()
    reader = _reader(CV, language)
    assert dr._contract_i18n(reader, catalogue, language, "de") == []
    assert '<html lang="de">' in reader


def test_a_spanish_reader_carries_no_english_ui_text() -> None:
    reader = _reader(CV, "es")
    for text in ("Export notes", "Import notes", "Your note on this passage"):
        assert text not in reader


def test_the_i18n_contract_reports_english_in_a_translated_reader() -> None:
    catalogue = dr.load_catalogue()
    english = _reader(CV, "en").replace('lang="en"', 'lang="es"')
    defects = dr._contract_i18n(english, catalogue, "es", "de")
    assert any("not es" in d for d in defects)


def test_the_i18n_contract_reports_a_reader_in_the_documents_language() -> None:
    catalogue = dr.load_catalogue()
    reader = _reader(CV, "es").replace('<html lang="de">', '<html lang="es">')
    assert any(
        "document's own language" in d for d in dr._contract_i18n(reader, catalogue, "es", "de")
    )


def test_the_script_reads_only_keys_the_catalogue_has() -> None:
    assert dr.script_keys() <= set(strings.keys(dr.load_catalogue()))
    assert dr.script_keys() >= {"reader_saved", "reader_exported", "reader_import_failed"}


def test_a_string_the_script_says_by_itself_is_found() -> None:
    catalogue = dr.load_catalogue()
    leaky = dr._SCRIPT.replace(
        'say("reader_no_notes")', 'say("reader_no_notes"); say("reader_oops")'
    )
    assert "reader_oops" in dr.script_keys(leaky)
    assert "reader_oops" not in strings.keys(catalogue)


def test_no_literal_text_in_the_export_path() -> None:
    catalogue = dr.load_catalogue()
    assert dr._contract_no_literals(CV.document, catalogue, CV.title) == []


def test_the_no_literals_contract_reports_a_hard_coded_heading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalogue = dr.load_catalogue()
    monkeypatch.setattr(dr, "_SCRIPT", dr._SCRIPT.replace('"## " + id', '"Note ## " + id', 1))
    assert any(
        "text of its own" in d for d in dr._contract_no_literals(CV.document, catalogue, CV.title)
    )


def test_the_reader_catalogue_is_complete_current_and_in_the_corpus_languages() -> None:
    catalogue = dr.load_catalogue()
    assert strings.missing(catalogue) == []
    assert strings.stale(catalogue) == []
    from integral import corpus

    assert set(catalogue["languages"]) == set(corpus.LANGUAGES)


def test_a_stale_translation_is_reported_by_the_gate(tmp_path: Path) -> None:
    catalogue = json.loads(dr.DEFAULT_CATALOGUE.read_text(encoding="utf-8"))
    catalogue["entries"]["reader_export"]["en"] = "Send notes"
    path = tmp_path / "reader.json"
    path.write_text(json.dumps(catalogue), encoding="utf-8")
    measured = dr.measure(path)
    assert measured["reader_fragment_defects"] > 0
    assert any("catalogue stale" in d for d in measured["defects"])


# -- a document is data, never code ------------------------------------------


def test_nothing_in_a_document_runs_in_the_reader() -> None:
    reader = _reader(AWKWARD)
    assert dr._contract_inert(reader) == []
    assert reader.count("<script") == 1
    assert "&lt;/textarea&gt;" in reader
    assert re.search(r"script-src 'unsafe-inline'", reader)


def test_the_page_policy_allows_only_the_readers_own_script_beyond_the_shared_one() -> None:
    policy = dr.reader_csp()
    assert policy.startswith(report_style.CSP)
    assert policy.split(";")[-1].strip() == "script-src 'unsafe-inline'"
    assert "connect-src" not in policy


def test_a_title_cannot_close_the_script_or_the_title() -> None:
    reader = _reader(AWKWARD)
    assert reader.count("</script>") == 1
    assert dr.check_script(dr._script_of(reader)) is None


def test_a_document_with_no_text_is_refused() -> None:
    with pytest.raises(dr.ReaderError, match="no text"):
        dr.build_reader("<div></div>", title="t", reader_language="en")


def test_an_unknown_reader_language_is_refused() -> None:
    with pytest.raises(dr.ReaderError, match="not one of"):
        dr.build_reader("<p>x</p>", title="t", reader_language="de")


def test_the_cli_builds_a_reader_and_refuses_a_file_that_is_not_an_export(tmp_path: Path) -> None:
    source = tmp_path / "in.html"
    source.write_text("<p>hola</p>", encoding="utf-8")
    out = tmp_path / "out.html"
    args = [
        "x",
        "build",
        str(source),
        "--title",
        "T",
        "--reader-language",
        "es",
        "--output",
        str(out),
    ]
    assert dr._main(args) == 0
    assert 'data-frag="f1"' in out.read_text(encoding="utf-8")
    bad = tmp_path / "bad.md"
    bad.write_text("nothing here", encoding="utf-8")
    assert dr._main([*args, "--notes", str(bad)]) == 2
