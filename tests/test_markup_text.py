"""T169 — a field can say its value is markup, and every connector's does.

The census in `integral.markup_text` is the gate; these are the assertions a
reader can run one at a time. The contract table they exercise was written by a
session other than this task's implementer, from the HTML standard, which is
what stops the cases being a description of what the code already does.
"""

from __future__ import annotations

import html
from pathlib import Path

import pytest
from pydantic import ValidationError

from integral import markup_text
from integral.connectors import (
    JsonSource,
    Node,
    _neutralise_unterminated_tail,
    _take,
    parse_connector,
    parse_html,
)


def test_no_fixture_offer_text_carries_markup() -> None:
    measured = markup_text.measure()
    assert measured["findings"] == []
    assert measured["offers_whose_text_carries_markup"] == 0


def test_the_scan_reaches_a_real_population() -> None:
    # A clean zero over an empty scan is what a broken scan also reports.
    measured = markup_text.measure()
    assert measured["fixture_offers_checked"] >= markup_text.MINIMUM_FIXTURE_OFFERS
    assert measured["markup_values_compared"] >= markup_text.MINIMUM_MARKUP_VALUES_COMPARED
    assert len(markup_text.MARKUP_CONTRACTS) >= markup_text.MINIMUM_MARKUP_CONTRACTS
    assert measured["gate_status"] == "measured"


def test_the_floors_are_literals() -> None:
    # T122: a floor derived from the population it guards can never fire.
    text = Path(markup_text.__file__).read_text(encoding="utf-8")
    for name in (
        "MINIMUM_FIXTURE_OFFERS",
        "MINIMUM_MARKUP_VALUES_COMPARED",
        "MINIMUM_MARKUP_CONTRACTS",
    ):
        line = next(row for row in text.splitlines() if row.startswith(f"{name} = "))
        assert line.split("=")[1].strip().isdigit(), line


def test_markup_take_contracts() -> None:
    assert markup_text.measure_contracts() == []


def test_escaped_and_raw_markup_read_to_the_same_text() -> None:
    # The property T75's dedup margin rests on: one advert, two encodings, one
    # set of shingles.
    measured = markup_text.measure()
    assert measured["disagreements"] == []
    assert measured["encodings_that_disagree"] == 0


def test_an_escaped_literal_survives_on_both_routes() -> None:
    # The case that ruled out a single "unescape, then strip" member: an advert
    # writing `<canvas>` as text keeps the word either way.
    raw = "<p>experience with &lt;canvas&gt;</p>"
    assert _take("html_text", raw) == "experience with <canvas>"
    assert _take("escaped_html_text", html.escape(raw)) == "experience with <canvas>"


def test_a_markup_take_yields_nothing_when_no_text_survives() -> None:
    # Fail-closed, like every other member: `build_offer` drops an offer with
    # no text rather than showing the candidate a row of tags.
    assert _take("html_text", "<p> </p><br/>") is None
    assert _take("escaped_html_text", "&lt;p&gt;&lt;/p&gt;") is None


def test_a_json_field_may_be_a_path_or_a_rule() -> None:
    source = JsonSource.model_validate(
        {"fields": {"title": "title", "text": {"path": "content", "take": "escaped_html_text"}}}
    )
    assert source.fields["title"].path == "title"
    assert source.fields["title"].take is None
    assert source.fields["text"].take == "escaped_html_text"


def test_last_text_node_is_refused_on_a_json_field() -> None:
    with pytest.raises(ValidationError, match="has no elements"):
        JsonSource.model_validate(
            {"fields": {"text": {"path": "content", "take": "last_text_node"}}}
        )


CONNECTOR = """
site: example
locale: en
version: "1.0.0"
last_verified: "2026-09-14"
auth: none
list:
  url_pattern: "https://example.com/jobs.json"
  pagination:
    mode: none
    max_pages: 1
  from_json:
    items: jobs
    fields:
      title: title
      text:
        path: content
        take: escaped_html_text
"""


def test_a_connector_file_can_declare_a_markup_take() -> None:
    connector = parse_connector(CONNECTOR)
    assert connector.list.from_json is not None
    assert connector.list.from_json.fields["text"].take == "escaped_html_text"


def test_script_and_style_are_not_prose() -> None:
    # Before T169 a script body was part of the advert, and — because CPython
    # resolves no character reference inside script data — it was the one place
    # a raw `&lt;` could reach `Offer.text` through the member added to remove
    # markup. Found by the second reader.
    assert _take("html_text", "<p>Remote</p><script>var id = 42;</script>") == "Remote"
    assert _take("html_text", "<script>if (a &lt; b) {}</script><p>Remote</p>") == "Remote"
    assert _take("html_text", "<style>.a{color:#fff}</style><p>Remote</p>") == "Remote"


def test_a_script_holding_json_is_still_readable() -> None:
    # The other half of that change: `raw_text` must keep script content, or
    # every embedded-JSON connector (rippling's `__NEXT_DATA__`, justjoin's
    # ld+json) silently reads an empty document.
    root = parse_html('<p>Remote</p><script id="__NEXT_DATA__">{"a": 1}</script>')
    script = next(node for node in root.iter_descendants() if node.tag == "script")
    assert isinstance(script, Node)
    # What the embedded-JSON route reads is untouched...
    assert script.raw_text() == '{"a": 1}'
    # ...and calling raw_text() on an ancestor must not filter the script out
    # either - the skip is text_content()'s alone, so a mutation that widened
    # it onto raw_text() would still pass the assertion above (raw_text()
    # called directly on the script node never tests its own tag against
    # skip) and only shows up here.
    assert root.raw_text() == 'Remote{"a": 1}'
    # ...while the prose around it no longer carries the document.
    assert root.text_content() == "Remote"


def test_a_malformed_marked_section_does_not_raise() -> None:
    # `_markupbase` asserts on an unknown marked-section keyword, so a board
    # serving this raised out of `parse_html` and took the whole sourcing run
    # with it. WHATWG calls it a bogus comment, which yields no text.
    assert _take("html_text", "<p>a</p><![data[b]]>") == "a"
    assert _take("html_text", "<![CDATA[Remote]]>") is None


def test_a_malformed_marked_section_ends_at_the_next_gt() -> None:
    # WHATWG's bogus comment state ends at the first literal '>' wherever it
    # falls, not at the marked section's own ']]>' - so recovery must keep
    # parsing past a bogus comment that swallows into the next real tag,
    # rather than either raising or discarding everything to EOF.
    assert _take("html_text", "<p>a</p><![foo]><p>b</p>") == "a b"
    assert _take("html_text", "<p>a</p><![data[b]<p>c</p>") == "a c"


def test_an_eof_truncated_tag_survives_as_prose() -> None:
    # An EOF-truncated start tag has no settled behaviour across CPython
    # patches (measured: silently discarded by one build, resurfaced as data
    # by another), so pinning MARKUP_CONTRACTS to either is a check against a
    # proxy for the property. _neutralise_unterminated_tail() makes the
    # outcome deterministic instead: the '<' can never open a real tag (there
    # is no '>' left to close it with), so it is neutralised and the rest of
    # the field survives - the fail-open direction this repo weights.
    assert _take("html_text", "a <b 10 years") == "a <b 10 years"
    assert _take("html_text", "5 years <b experience needed") == "5 years <b experience needed"
    # An EOF-truncated end tag is the same family.
    assert _take("html_text", "Remote </b 10 years") == "Remote </b 10 years"


def test_an_eof_truncated_comment_still_contributes_no_text() -> None:
    # The other half of the same fix, argued from the rule an ordinary,
    # *terminated* comment already follows a few lines up in
    # MARKUP_CONTRACTS: a comment is never text, whether or not it manages to
    # close. Kept deterministic rather than left to whichever of
    # handle_comment/handle_data a given interpreter flushes it through at
    # EOF.
    assert _take("html_text", "<p>Remote</p><!-- unterminated") == "Remote"
    assert _take("html_text", "<!-- <p>nested-looking</p> unterminated") is None


def test_neutralise_unterminated_tail_is_a_no_op_on_well_formed_markup() -> None:
    # Every construct in these already finds its own '>' (or, for the entity
    # rows, has no literal '<' at all) - the function must leave them
    # byte-for-byte untouched rather than rewrite markup that was never
    # pathological.
    for markup in (
        "<p>Remote</p>",
        "&lt;p&gt;Remote&lt;/p&gt;",
        "<![CDATA[Remote]]>",
    ):
        assert _neutralise_unterminated_tail(markup) == markup


def test_neutralise_unterminated_tail_still_reads_correctly_on_a_bare_lt() -> None:
    # `5 < 10 years` DOES have its lone '<' rewritten to '&lt;' here (it has
    # no '>' anywhere after it either, the same shape as the pathological
    # cases) - that is not the no-op the rows above get, but it must still
    # read back as exactly the same text once html.parser resolves the
    # reference, since this '<' was already destined to survive as a literal
    # character rather than open anything.
    assert _neutralise_unterminated_tail("5 < 10 years") != "5 < 10 years"
    assert _take("html_text", "5 < 10 years") == "5 < 10 years"


def test_neutralise_unterminated_tail_actually_transforms_the_pathological_inputs() -> None:
    # A no-op fix would still make the two MARKUP_CONTRACTS rows above pass
    # coincidentally if parse_html's own tolerance happened to agree - it
    # doesn't here, but this pins the function itself to actually act,
    # so a future refactor that quietly turns it into pass-through is caught
    # at this seam rather than only by however html.parser happens to behave.
    assert _neutralise_unterminated_tail("a <b 10 years") != "a <b 10 years"
    assert _neutralise_unterminated_tail("<p>Remote</p><!-- unterminated") != (
        "<p>Remote</p><!-- unterminated"
    )
