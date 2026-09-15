"""T169 — no offer reaches the candidate with the board's markup still in it.

Six connectors publish an advert body as **HTML inside a field**, and one of
them, greenhouse, publishes it as HTML-*escaped* HTML. Read raw, those bodies
reach the candidate as tags, and they reach `dedup.normalise_for_comparison` as
tag tokens (`lt p gt`): the same advert read escaped and read clean scored a
Jaccard of 0.34-0.46 against a `SIMILARITY_THRESHOLD` of 0.25, which is most of
T75's employer-vs-aggregator margin spent on markup.

The fix is two `take:` members in `connectors.py`, and this module is the check
that they are actually *applied* — a vocabulary nobody uses fixes nothing. It
measures the property rather than the connectors: every offer every fixture can
build, counted for markup, with the population discovered from `connectors/`
rather than listed here. A connector added tomorrow with an HTML body is in the
denominator the day it lands.

Two numbers, because one of them alone could pass over nothing:

* `offers_whose_text_carries_markup` — the finding count, and the gate.
* `fixture_offers_checked` — the denominator, asserted against the literal floor
  `MINIMUM_FIXTURE_OFFERS`. A clean zero over an empty scan is what a broken
  scan also reports. The floor is a literal, not `len(...)` of the population it
  guards, for T122's reason.

And one more, because "is the text clean" does not say the two encodings agree:
`encodings_that_disagree` reads every markup-carrying fixture value both ways —
as raw markup, and escaped and read back through the escaped member — and
compares the **dedup shingles** of each result, not merely the strings. That is
the property T75 needs: the same advert from an escaped board and a raw board
must be one offer, not two.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from typing import Any

from integral import dedup
from integral.connectors import (
    CONNECTOR_FILENAME,
    DEFAULT_CONNECTORS_DIR,
    FIXTURE_DIRNAME,
    Connector,
    ConnectorError,
    _take,
    build_offer,
    load_connector,
    parse_detail_page,
    parse_list_page,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T169.json"

#: A tag, or a character reference. Deliberately not "an element name from a
#: list": a board's markup is not ours to enumerate, and the escaped form is
#: recognisable by the reference alone. An advert whose prose genuinely writes
#: `<canvas>` trips this, and that is the right outcome for a *fixture* — the
#: case is then a decision somebody makes, in a review, rather than a silent
#: allowance.
MARKUP = re.compile(
    r"</?[A-Za-z][A-Za-z0-9:_-]*(?:\s[^<>]*)?/?>|&[A-Za-z][A-Za-z0-9]{1,30};|&#\d+;|&#[xX][0-9A-Fa-f]+;"
)

#: The two members that say "this value is markup".
MARKUP_TAKES = ("html_text", "escaped_html_text")

#: getmanfred publishes **Markdown**, not HTML, with an occasional inline
#: `<u>`; its 24 newlines are structure a reader sees. `html_text` would strip
#: the tag and flatten the document, trading one defect for a worse one, so it
#: is exempt and the exemption is counted rather than hidden. A Markdown body
#: read as text is a different task from this one.
EXEMPT_SITES = {
    "getmanfred": "Markdown body with inline <u>; flattening it would lose 24 line breaks"
}

#: Floors, literal. 75 offers over 21 packages on 2026-09-14; 9 markup-carrying
#: values across the six connectors that declare a markup take. Set below
#: today's counts by a stated margin so an ordinary connector PR does not have
#: to move them, and far enough above zero that a scan reaching one package
#: fails rather than passes.
MINIMUM_FIXTURE_OFFERS = 50
MINIMUM_MARKUP_VALUES_COMPARED = 6

#: The contract table's own floor. A census over the shipped fixtures proves
#: markup does not *survive*; it cannot see a member that unescapes twice, or
#: one that returns the unparsed value when nothing survives, because no
#: fixture exercises either — all three of those mutations were measured
#: surviving the census alone before this table existed. The rows below are
#: what closes that, so a table that shrank must read `unmeasured` rather than
#: a clean zero.
#:
#: **Zero slack, unlike the two floors above**: the table only ever grows, so
#: the first row deleted must breach this — which is T159's test for a floor
#: that can actually fire. Raise it with the table; never lower it.
MINIMUM_MARKUP_CONTRACTS = 57


#: What each member must do, as (take, input, expected output, why).
#: `None` means the member yields nothing and the field is left empty.
#:
#: **Written by a session other than the implementer** (CLAUDE.md), from the
#: WHATWG HTML standard's character-reference and tokenisation rules and from
#: Greenhouse's Job Board API documentation, before that session read the
#: implementation. Each row's `why` carries the citation it was derived from.
MARKUP_CONTRACTS: tuple[tuple[str, str, str | None, str], ...] = (
    # --- no markup at all: both members are transparent --------------------
    (
        "html_text",
        "Senior Python Developer",
        "Senior Python Developer",
        "no markup is not a failure - the deliberate exception to _take's "
        "never-return-value-unchanged rule, because text IS what an HTML body yields",
    ),
    (
        "escaped_html_text",
        "Senior Python Developer",
        "Senior Python Developer",
        "same, after a no-op unescape",
    ),
    (
        "html_text",
        "Senior  Python\nDeveloper",
        "Senior Python Developer",
        "text_content collapses whitespace runs - the declared reflow that answers "
        "Node.raw_text's byte-for-byte docstring",
    ),
    (
        "html_text",
        "R&D team",
        "R&D team",
        "WHATWG 13.1.4: an ampersand not followed by alnum+';' is not a reference",
    ),
    # --- the escaped literal that forced two members rather than one -------
    (
        "html_text",
        "experience with &lt;canvas&gt; and WebGL",
        "experience with <canvas> and WebGL",
        "WHATWG 13.1.4: a character reference expands to a character and can never "
        "produce a tag - unescaping first would delete the word. FAIL-OPEN if lost",
    ),
    (
        "escaped_html_text",
        "experience with &amp;lt;canvas&amp;gt; and WebGL",
        "experience with <canvas> and WebGL",
        "greenhouse serves escaped HTML carrying an escaped literal - unescape ONCE "
        "then parse; a second unescape makes <canvas> a tag and the word disappears",
    ),
    (
        "escaped_html_text",
        "experience with &lt;canvas&gt; and WebGL",
        "experience with and WebGL",
        "NEGATIVE CONTROL: the wrong member on raw HTML deletes the keyword - which "
        "is why there are two members and not one 'unescape then strip'",
    ),
    (
        "html_text",
        "&lt;p&gt;Remote&lt;/p&gt;",
        "<p>Remote</p>",
        "NEGATIVE CONTROL the other way: the wrong member on escaped HTML leaves the "
        "tags as TEXT - FAIL-OPEN, and what this module's census catches",
    ),
    # --- escaping layers, exactly once -------------------------------------
    ("html_text", "Tom &amp; Jerry", "Tom & Jerry", "html.parser resolves exactly one layer"),
    (
        "html_text",
        "Tom &amp;amp; Jerry",
        "Tom &amp; Jerry",
        "one layer only: the board displays the literal '&amp;'",
    ),
    (
        "escaped_html_text",
        "Tom &amp;amp; Jerry",
        "Tom & Jerry",
        "unescape once + parse once = two layers, the right total for singly-escaped "
        "HTML whose source held &amp;",
    ),
    (
        "escaped_html_text",
        "&amp;lt;p&amp;gt;",
        "<p>",
        "EXACTLY-ONCE PROBE: a second unescape turns this into a tag and yields None",
    ),
    (
        "escaped_html_text",
        "&lt;p&gt;Remote&lt;/p&gt;",
        "Remote",
        "what boards-api.greenhouse.io actually serves (Greenhouse Job Board API: "
        "HTML from the hosted editor is converted into HTML entities)",
    ),
    (
        "escaped_html_text",
        "<p>Remote</p>",
        "Remote",
        "unescape is a no-op on raw HTML; the members differ ONLY on values carrying "
        "character references",
    ),
    # --- nbsp ---------------------------------------------------------------
    (
        "html_text",
        "Remote&nbsp;first",
        "Remote first",
        "DIVERGENCE, accepted: U+00A0 is whitespace to str.split, so text_content "
        "yields U+0020 where DOM textContent would keep U+00A0 - right for an advert "
        "body, and dedup is indifferent",
    ),
    (
        "escaped_html_text",
        "Remote&amp;nbsp;first",
        "Remote first",
        "greenhouse's doubled nbsp reaches the same character",
    ),
    (
        "escaped_html_text",
        "&lt;p&gt;&lt;strong&gt;Summary&lt;/strong&gt;&lt;/p&gt;&amp;nbsp;",
        "Summary",
        "the exact shape in T169's own report - the trailing nbsp contributes nothing",
    ),
    ("html_text", "&nbsp;", None, "whitespace-only after resolution - FAIL-CLOSED"),
    # --- numeric and named references ---------------------------------------
    ("html_text", "&#82;emote", "Remote", "WHATWG 13.1.4 decimal numeric reference"),
    ("html_text", "&#x52;emote", "Remote", "WHATWG 13.1.4 hexadecimal numeric reference"),
    (
        "html_text",
        "&#60;p&#62;",
        "<p>",
        "a numeric reference is a character, never markup - the text is literally '<p>'",
    ),
    (
        "html_text",
        "Pay&#0;rise",
        "Pay\ufffdrise",
        "WHATWG null-character-reference - resolved to U+FFFD",
    ),
    (
        "html_text",
        "&#x80;50.000",
        "\u20ac50.000",
        "WHATWG control-character-reference - C1 refs are replaced per the numeric "
        "character reference end state table; chr(0x80) would be FAIL-OPEN garbage",
    ),
    ("html_text", "&#x110000;", "\ufffd", "WHATWG character-reference-outside-unicode-range"),
    ("html_text", "&#xD800;", "\ufffd", "WHATWG surrogate-character-reference"),
    (
        "html_text",
        "&amp",
        "&",
        "WHATWG missing-semicolon-after-character-reference: 'behaves the same as if "
        "terminated by U+003B'",
    ),
    (
        "html_text",
        "&notit;",
        "\u00acit;",
        "longest-prefix match, exactly as the spec's own note has '&notin' parse as '\u00acin'",
    ),
    (
        "html_text",
        "&foo;",
        "&foo;",
        "WHATWG unknown-named-character-reference - an ambiguous ampersand is NOT "
        "resolved and must survive verbatim",
    ),
    (
        "html_text",
        "https://x.test/j?id=1&sect=eng",
        "https://x.test/j?id=1\u00a7=eng",
        "the same rule where it hurts: '&sect' without a semicolon IS a named "
        "reference, so a query string is mangled - spec-required, not a defect",
    ),
    # --- structure ----------------------------------------------------------
    (
        "html_text",
        "<p>Remote</p><p>Barcelona</p>",
        "Remote Barcelona",
        "pieces are joined with one space, so blocks never weld (DOM textContent "
        "would give 'RemoteBarcelona')",
    ),
    ("html_text", "<ul><li>Python</li><li>Django</li></ul>", "Python Django", "same, list items"),
    (
        "html_text",
        "line one<br>line two",
        "line one line two",
        "br is in _VOID_TAGS, so there is nothing to weld",
    ),
    (
        "html_text",
        '<p>Apply <a href="https://boards.test/x?ref=1">here</a></p>',
        "Apply here",
        "attribute values are never text - a URL reaching the body would be FAIL-OPEN",
    ),
    (
        "html_text",
        '<img alt="Remote" src="x.png">',
        None,
        "a void element with no text - FAIL-CLOSED, alt text is not text",
    ),
    ("html_text", "<P>Remote</P>", "Remote", "tag names are ASCII case-insensitive"),
    ("html_text", "<p>  Remote  </p>", "Remote", "outer whitespace stripped"),
    (
        "html_text",
        "<p>Java<strong>Script</strong> developer</p>",
        "Java Script developer",
        "CEILING, pinned: text_content joins every piece with a space, so an inline "
        "run splits mid-word. Pre-existing on every CSS connector, and it shifts one "
        "dedup shingle window - the upgrade path is a block/inline table, not a "
        "second reader of markup",
    ),
    (
        "html_text",
        "<p><strong>Summary</strong>: remote</p>",
        "Summary : remote",
        "the same join, detached punctuation - harmless, since normalise_for_"
        "comparison tokenises on words",
    ),
    # --- code is not prose ---------------------------------------------------
    (
        "html_text",
        "<p>Remote</p><script>var id = 42;</script>",
        "Remote",
        "script data is not a reader's text - _NON_PROSE. Before T169 it landed in "
        "the advert body and in dedup's token stream",
    ),
    (
        "html_text",
        "<script>if (a &lt; b) {}</script><p>Remote</p>",
        "Remote",
        "the strongest of the four: CPython resolves NO character reference inside "
        "script data, so this is the one place a raw '&lt;' could reach Offer.text "
        "through the very member added to remove markup - FAIL-OPEN",
    ),
    ("html_text", "<style>.a{color:#fff}</style><p>Remote</p>", "Remote", "same for a stylesheet"),
    (
        "html_text",
        "<script>var x = 1;</script>",
        None,
        "a body that is only code has no prose at all - FAIL-CLOSED",
    ),
    # --- nothing survives ----------------------------------------------------
    ("html_text", "", None, "empty - FAIL-CLOSED"),
    ("html_text", "   \n\t ", None, "whitespace only - FAIL-CLOSED"),
    ("html_text", "<p></p>", None, "markup with no text - FAIL-CLOSED"),
    ("html_text", "<div><br></div>", None, "still no text - FAIL-CLOSED"),
    (
        "html_text",
        "<!-- salary 200k -->",
        None,
        "a comment is not text; it was never rendered - FAIL-CLOSED",
    ),
    ("escaped_html_text", "", None, "FAIL-CLOSED"),
    ("escaped_html_text", "&lt;p&gt;&lt;/p&gt;", None, "FAIL-CLOSED"),
    (
        "escaped_html_text",
        "&amp;nbsp;",
        None,
        "greenhouse's trailing artefact on its own - FAIL-CLOSED",
    ),
    # --- malformed markup ----------------------------------------------------
    (
        "html_text",
        "<p>Senior Engineer",
        "Senior Engineer",
        "an unclosed element is still an element; its text is text",
    ),
    (
        "html_text",
        "5 < 10 years",
        "5 < 10 years",
        "tag open state: '<' not followed by an ASCII alpha is emitted as a character",
    ),
    (
        "html_text",
        "5 &lt; 10 years",
        "5 < 10 years",
        "references resolve after tokenisation, so this never re-tokenises",
    ),
    (
        "html_text",
        "<![CDATA[Remote]]>",
        None,
        "WHATWG cdata-in-html-content: a CDATA section outside foreign content is a "
        "comment, so it yields no text",
    ),
    (
        "html_text",
        "<p>a</p><![data[b]]>",
        "a",
        "an unknown marked section is a bogus comment. _markupbase asserts on the "
        "keyword, which raised out of parse_html and would have taken a whole "
        "sourcing run with it - _TreeBuilder.parse_marked_section consumes it",
    ),
    (
        "html_text",
        "a <b 10 years",
        "a <b 10 years",
        "FIXED, not pinned: an EOF-truncated tag has no settled cross-patch "
        "behaviour (html.parser has been measured to discard it, and "
        "separately to resurface it as data, on different CPython 3.12 "
        "builds this repository's own CI can draw) - so connectors.py's "
        "_neutralise_unterminated_tail() now recovers it as literal prose "
        "before parsing, deterministically, rather than pinning this row to "
        "whichever interpreter behaviour a given CI run happens to draw. "
        "Silently truncating the rest of a candidate-visible field on a bare "
        "'<' that was never markup at all is the FAIL-OPEN case this repo "
        "weights over a fail-closed one",
    ),
    (
        "html_text",
        "<p>Remote</p><!-- unterminated",
        "Remote",
        "GENUINE CEILING, argued from the already-settled rule a few rows up "
        "rather than from any interpreter's EOF recovery: a comment "
        "contributes no text whether or not it manages to close, exactly "
        "like the terminated '<!-- salary 200k -->' row above. "
        "_neutralise_unterminated_tail() drops an EOF-truncated '<!--' for "
        "that reason, so the result is the same on every interpreter tested "
        "rather than depending on whether html.parser flushes it via "
        "handle_comment or handle_data at EOF",
    ),
)


def measure_contracts() -> list[dict[str, str]]:
    """Every contract row whose member does not do what the row requires."""
    failures = []
    for take, value, expected, why in MARKUP_CONTRACTS:
        actual = _take(take, value)  # type: ignore[arg-type]
        if actual != expected:
            failures.append(
                {
                    "take": take,
                    "input": value[:80],
                    "expected": "" if expected is None else expected,
                    "actual": "" if actual is None else actual,
                    "why": why,
                }
            )
    return failures


def _sources(connector: Connector) -> list[tuple[str, Any]]:
    """`(where, page)` for each page of `connector` that declares fields."""
    pages: list[tuple[str, Any]] = [("list", connector.list)]
    if connector.detail is not None:
        pages.append(("detail", connector.detail))
    return pages


def _declared_markup_paths(connector: Connector) -> list[tuple[str, str, str]]:
    """`(where, field name, take)` for every field declared as markup."""
    found = []
    for where, page in _sources(connector):
        if page.from_json is not None:
            for name, field_ in page.from_json.fields.items():
                if field_.take in MARKUP_TAKES:
                    found.append((where, name, field_.take))
        for name, selector in (page.fields or {}).items():
            if selector.take in MARKUP_TAKES:
                found.append((where, name, selector.take))
    return found


def _fixture_offers(package: Path, connector: Connector) -> list[Any]:
    """Every offer this package's fixture can build, merged as `sourcing` merges.

    The detail fixture is one advert, so it is applied to the first row only —
    the same shape a run produces, where each row gets its own detail fetch.
    """
    fixture = package / FIXTURE_DIRNAME
    list_page = fixture / "list.html"
    if not list_page.exists():
        return []
    rows = parse_list_page(connector, list_page.read_text(encoding="utf-8"))
    detail_page = fixture / "detail.html"
    detail_fields: dict[str, str] = {}
    if detail_page.exists() and connector.detail is not None:
        detail_fields = parse_detail_page(connector, detail_page.read_text(encoding="utf-8"))
    offers = []
    for index, row in enumerate(rows):
        try:
            offers.append(
                build_offer(
                    connector,
                    list_fields=row,
                    detail_fields=detail_fields if index == 0 else None,
                    url=row.get("detail_url"),
                )
            )
        except (ConnectorError, ValueError):
            # A fixture row that cannot build an offer is not this gate's
            # subject — `connector_health` is the reader for that — and it
            # carries no text to be markup.
            continue
    return offers


def measure(directory: Path = DEFAULT_CONNECTORS_DIR) -> dict[str, Any]:
    """Count offers whose text still carries markup, and encodings that disagree."""
    findings: list[dict[str, str]] = []
    disagreements: list[dict[str, str]] = []
    offers_checked = 0
    values_compared = 0
    exempt_offers = 0
    packages = sorted(p for p in directory.iterdir() if (p / CONNECTOR_FILENAME).exists())
    for package in packages:
        connector = load_connector(package / CONNECTOR_FILENAME)
        offers = _fixture_offers(package, connector)
        for offer in offers:
            if connector.site in EXEMPT_SITES:
                exempt_offers += 1
                continue
            offers_checked += 1
            found = MARKUP.search(offer.text)
            if found is not None:
                findings.append(
                    {
                        "site": connector.site,
                        "offer": offer.id,
                        "markup": found.group()[:60],
                    }
                )
        # The parity half: read each declared markup value both ways.
        for value in _raw_markup_values(package, connector):
            values_compared += 1
            raw = _take("html_text", value)
            escaped = _take("escaped_html_text", html.escape(value))
            if _shingles(raw) != _shingles(escaped):
                disagreements.append({"site": connector.site, "value": value[:60]})
    contract_failures = measure_contracts()
    measured: dict[str, Any] = {
        "offers_whose_text_carries_markup": len(findings),
        "markup_contracts_failing": len(contract_failures),
        "markup_contracts": len(MARKUP_CONTRACTS),
        "contract_failures": contract_failures,
        "fixture_offers_checked": offers_checked,
        "encodings_that_disagree": len(disagreements),
        "markup_values_compared": values_compared,
        "offers_exempt": exempt_offers,
        "exempt_sites": sorted(EXEMPT_SITES),
        "findings": findings,
        "disagreements": disagreements,
    }
    measured["gate_status"] = (
        "measured"
        if offers_checked >= MINIMUM_FIXTURE_OFFERS
        and values_compared >= MINIMUM_MARKUP_VALUES_COMPARED
        and len(MARKUP_CONTRACTS) >= MINIMUM_MARKUP_CONTRACTS
        else "unmeasured"
    )
    return measured


def _shingles(text: str | None) -> frozenset[str]:
    """What the deduper would compare, for text either route produced."""
    return dedup.shingles(dedup.normalise_for_comparison(text or ""))


def _raw_markup_values(package: Path, connector: Connector) -> list[str]:
    """Every fixture value for a markup-declared field, as **raw** markup.

    Read from the fixture through the connector's own paths, with the escaped
    member's values unescaped once so both encodings start from the same
    document.
    """
    declared = _declared_markup_paths(connector)
    if not declared:
        return []
    fixture = package / FIXTURE_DIRNAME
    values: list[str] = []
    for where, name, take in declared:
        page_file = fixture / ("list.html" if where == "list" else "detail.html")
        if not page_file.exists():
            continue
        text = page_file.read_text(encoding="utf-8")
        if where == "list":
            records = _raw_list_records(connector, text)
        else:
            records = [_raw_detail_record(connector, text)]
        for record in records:
            value = record.get(name)
            if value:
                values.append(html.unescape(value) if take == "escaped_html_text" else value)
    return values


def _raw_list_records(connector: Connector, text: str) -> list[dict[str, str]]:
    return parse_list_page(_without_markup_takes(connector), text)


def _raw_detail_record(connector: Connector, text: str) -> dict[str, str]:
    return parse_detail_page(_without_markup_takes(connector), text)


def _without_markup_takes(connector: Connector) -> Connector:
    """The same connector with every markup `take` removed.

    The comparison needs the value the board sent, and the parser's job is to
    hand back the value the connector asked for. Rather than reimplement `dig`
    and `_extract` here — a second extraction implementation to keep honest —
    the connector is copied with those takes dropped and the real parser is run
    over the same fixture.
    """
    data = connector.model_dump()
    for where in ("list", "detail"):
        page = data.get(where)
        if not page:
            continue
        source = page.get("from_json")
        if source:
            for field_ in source["fields"].values():
                if field_.get("take") in MARKUP_TAKES:
                    field_["take"] = None
        for selector in (page.get("fields") or {}).values():
            if selector.get("take") in MARKUP_TAKES:
                selector["take"] = None
    return Connector.model_validate(data)


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """The committed subset: findings are printed, never committed as data.

    `fixture_offers_checked` is committed as its **floor** rather than as the
    count of the day, for T100's reason: an exact population drifts on the next
    connector anyone adds, and a floor is what the zero actually needs.
    """
    return {
        "offers_whose_text_carries_markup": measured["offers_whose_text_carries_markup"],
        "markup_contracts_failing": measured["markup_contracts_failing"],
        "encodings_that_disagree": measured["encodings_that_disagree"],
        "markup_contracts_at_least": MINIMUM_MARKUP_CONTRACTS,
        "fixture_offers_checked_at_least": MINIMUM_FIXTURE_OFFERS,
        "markup_values_compared_at_least": MINIMUM_MARKUP_VALUES_COMPARED,
        "offers_exempt": measured["offers_exempt"],
        "exempt_sites": measured["exempt_sites"],
        "gate_status": measured["gate_status"],
    }


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    measured = measure()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


def _main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    evidence = Path(args[0]) if args else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(evidence)
    print(json.dumps({k: v for k, v in measured.items() if k != "findings"}, ensure_ascii=False))
    for finding in measured["findings"]:
        print(f"✗ {finding['site']}: offer text carries {finding['markup']!r}", file=sys.stderr)
    for failure in measured["contract_failures"]:
        print(
            f"✗ take:{failure['take']} on {failure['input']!r} -> {failure['actual']!r}, "
            f"expected {failure['expected']!r} ({failure['why']})",
            file=sys.stderr,
        )
    for disagreement in measured["disagreements"]:
        print(
            f"✗ {disagreement['site']}: the two encodings of one body dedup differently",
            file=sys.stderr,
        )
    if measured["gate_status"] != "measured":
        print(
            f"only {measured['fixture_offers_checked']} fixture offer(s) and "
            f"{measured['markup_values_compared']} markup value(s) and "
            f"{measured['markup_contracts']} contract(s) reached the scan (floors "
            f"{MINIMUM_FIXTURE_OFFERS}, {MINIMUM_MARKUP_VALUES_COMPARED} and "
            f"{MINIMUM_MARKUP_CONTRACTS})",
            file=sys.stderr,
        )
        return 1
    return (
        1
        if measured["findings"] or measured["disagreements"] or measured["contract_failures"]
        else 0
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
