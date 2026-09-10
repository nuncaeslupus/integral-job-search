"""T12 acceptance tests: the live-portal connector against its recorded pages.

`connectors/trabajos_es` is the first connector in the library pointed at a real
board — `examplejobs_es` is a worked example against a fictitious site. The
fixtures here are the bytes trabajos.com actually served on 2026-08-23, so these
tests are the only place the repo's small HTML parser meets markup nobody wrote
for it.
"""

from __future__ import annotations

import json

import pytest

from integral.connect_portal import DEFAULT_EXPECTED, DEFAULT_PACKAGE, measure, normalise, score
from integral.connectors import build_offer, load_connector, parse_detail_page, parse_list_page

# Read from disk rather than restated here, so these tests exercise the very
# files a contributor would add to the library — the same reason
# `tests/test_connectors.py` reads the worked example's yaml instead of inlining it.
CONNECTOR = load_connector(DEFAULT_PACKAGE)
LIST_HTML = (DEFAULT_PACKAGE / "fixture" / "list.html").read_text(encoding="utf-8")
DETAIL_HTML = (DEFAULT_PACKAGE / "fixture" / "detail.html").read_text(encoding="utf-8")
EXPECTED = json.loads(DEFAULT_EXPECTED.read_text(encoding="utf-8"))

PARSE_F1_FLOOR = 0.95

# `connectors/` is a public library of crawlers, and an advert body is the board's
# content, not ours: only the crawler belongs in the repository. A fixture needs
# enough real markup to prove the connector finds the right fields, which is far
# less than a whole advert. These ceilings are what stop a re-recording from
# quietly restoring the full bodies — the excerpting step is easy to forget, and
# nothing else in the suite would notice.
TEASER_CEILING = 200
BODY_CEILING = 800


def test_connector_parses_fixture_pages_to_offers() -> None:
    """The acceptance gate: recorded pages parse to the expected offers.

    The expectation was written by `tools/annotate_connector_fixture.py`, which
    read the same bytes with `lxml` and BeautifulSoup's full CSS engine. The two
    sides share no parser and no selector implementation, so agreement between
    them is evidence about the markup rather than about one library agreeing
    with itself.
    """
    measured = measure()

    assert measured["connector_fixture_parse_f1"] >= PARSE_F1_FLOOR, measured["mismatches"][:5]
    assert measured["items_parsed"] == measured["items_expected"]


def test_the_listing_yields_every_offer_on_the_page_with_its_fields() -> None:
    """Concrete values, not just "no exception" — a connector that silently
    stopped finding cards would otherwise pass everything above."""
    items = parse_list_page(CONNECTOR, LIST_HTML)

    assert len(items) == 40
    assert items[2]["title"] == "Administrativo/a Atención al Cliente con Inglés"
    assert items[2]["company"] == "Iman Temporing"
    assert items[2]["location_raw"] == "Barcelona"
    assert items[2]["detail_url"].startswith("https://www.trabajos.com/ofertas/1196549926/")
    # Nine companies and twenty-two locations on the page: a connector that
    # hardcoded either field could not score well against this fixture.
    assert len({item.get("company") for item in items}) >= 5
    assert len({item.get("title") for item in items}) == 40


def test_the_detail_page_supplies_the_full_body_the_listing_truncates() -> None:
    """The listing carries a teaser ending in an ellipsis; the offer body must
    come from the detail page, which is why `detail` fields win on overlap."""
    items = parse_list_page(CONNECTOR, LIST_HTML)
    detail = parse_detail_page(CONNECTOR, DETAIL_HTML)

    teaser = items[2]["text"]
    assert teaser.rstrip().endswith("...")
    assert len(detail["text"]) > len(teaser)

    offer = build_offer(
        CONNECTOR, list_fields=items[2], detail_fields=detail, url=items[2]["detail_url"]
    )
    assert offer.text == detail["text"]
    assert offer.title == "Administrativo/a Atención al Cliente con Inglés"
    assert offer.company == "Iman Temporing"
    assert offer.source == "trabajos"
    assert offer.language == "es"


def test_a_missed_offer_costs_the_score_its_whole_row() -> None:
    """Item count is inside the number the gate reads.

    An F1 computed only over the rows both sides produced would let a connector
    that found 20 of 40 offers score 1.0 by parsing those 20 perfectly. This
    pins the definition that cannot.
    """
    expected = {(i, "title"): f"offer {i}" for i in range(40)}
    found_half = {(i, "title"): f"offer {i}" for i in range(20)}

    assert score(expected, expected)["connector_fixture_parse_f1"] == 1.0
    halved = score(expected, found_half)
    assert halved["connector_fixture_parse_f1"] < PARSE_F1_FLOOR
    assert halved["recall"] == 0.5


def test_a_wrong_value_counts_against_both_precision_and_recall() -> None:
    """A cell the connector filled with the wrong text is not a near-miss: what
    it produced is wrong *and* what it owed is missing."""
    # One cell right, one filled with the wrong text. Both halves have to move:
    # scoring the wrong cell as only a miss would leave precision at a clean 1.0
    # and report a connector that invents values as merely incomplete.
    expected = {(0, "title"): "Real title", (0, "company"): "Real company"}
    half_wrong = {(0, "title"): "Real title", (0, "company"): "Something else"}

    measured = score(expected, half_wrong)
    assert measured["precision"] == 0.5, "a wrong value must count against precision"
    assert measured["recall"] == 0.5, "a wrong value must count against recall"
    assert measured["connector_fixture_parse_f1"] == 0.5
    assert measured["mismatches"][0]["expected"] == "Real company"
    assert measured["mismatches"][0]["parsed"] == "Something else"

    # And a cell the connector simply did not fill costs recall alone.
    missing = score(expected, {(0, "title"): "Real title"})
    assert missing["precision"] == 1.0
    assert missing["recall"] == 0.5


def test_the_expectation_is_committed_data_not_a_live_re_derivation() -> None:
    """If the gate re-ran the annotator, both sides would be recomputed from the
    fixture in the same breath and would agree whatever either parser did."""
    assert DEFAULT_EXPECTED.exists()
    assert EXPECTED["list_items"], "the frozen expectation must carry the offers"
    assert "lxml" in EXPECTED["annotated_by"]


@pytest.mark.parametrize("raw", ["  a   b  ", "a\n\nb", "a\tb"])
def test_both_sides_are_normalised_the_same_way(raw: str) -> None:
    """Normalising only one side would measure the two parsers' whitespace
    policies rather than which field each of them found."""
    assert normalise(raw) == "a b"


def test_the_committed_fixture_carries_excerpts_not_whole_adverts() -> None:
    """`tools/excerpt_fixture.py` ran, and a future re-recording has to run it too.

    The excerpting is a byte-level edit: everything outside the truncated bodies
    is exactly what the server sent, because round-tripping the page through a
    real parser would repair whatever the server got wrong, and repaired markup
    is what a fixture must never be.
    """
    teasers = [item["text"] for item in parse_list_page(CONNECTOR, LIST_HTML) if "text" in item]
    body = parse_detail_page(CONNECTOR, DETAIL_HTML)["text"]

    assert teasers, "the listing fixture should still carry previews to parse"
    assert max(len(t) for t in teasers) <= TEASER_CEILING, (
        f"longest listing preview is {max(len(t) for t in teasers)} chars — re-run "
        "tools/excerpt_fixture.py before committing"
    )
    assert len(body) <= BODY_CEILING, (
        f"the detail body is {len(body)} chars — that is an advert, not an excerpt"
    )


# ---------------------------------------------------------------------------
# T166 — the board searches the candidate's terms, and a miss is empty

NO_HITS_HTML = (
    DEFAULT_PACKAGE.parents[1] / "tests" / "fixtures" / "connectors" / "trabajos_es_no_hits.html"
).read_text(encoding="utf-8")


def test_the_probe_was_recorded_from_the_request_the_connector_sends() -> None:
    """`{query}` being in `url_pattern` proves the connector sends *a* query,
    not that the board reads it. The second reader on #447 swapped `CADENA`
    for `q` — a key trabajos.com ignores, answering with forty unrelated
    adverts — and every test and `make evidence` stayed green. The probe is a
    live capture of the board's own search, so the connector must rebuild its
    URL exactly from the query that capture carries."""
    from urllib.parse import parse_qs, urlsplit

    from integral.connectors import build_list_urls

    captured = json.loads((DEFAULT_PACKAGE / "probe" / "captured.json").read_text("utf-8"))
    (query,) = parse_qs(urlsplit(captured["url"]).query)["CADENA"]

    assert build_list_urls(CONNECTOR, page_count=1, query=query) == [captured["url"]]


def test_a_search_with_no_hits_parses_to_no_rows() -> None:
    """A miss must be empty, not a fallback list — infoempleo.com's page is
    ruled out in `connectors/ruled-out.yaml` for exactly that. The capture is
    the board's answer to a nonsense word, and it echoes the word back in its
    own search box, so this is a results page and not an empty file."""
    assert 'name="CADENA" class="liviano" value="zzqxvw"' in NO_HITS_HTML
    assert parse_list_page(CONNECTOR, NO_HITS_HTML) == []
