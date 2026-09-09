"""T113: a page key a package sends must be one that a capture actually carried.

`connectors/usajobs_en/connector.yaml` shipped a third body key, `Page:
"{page}"`, beside the two the capture was taken with. The ledger's measured
curl body is `{"Keyword":"python","ResultsPerPage":25}`; `probe/captured.json`
records that request; no capture and no retest ever sent a `Page`. The name
came from the board's **response** — `Pager.CurrentPageIndex` and
`Pager.NextPageIndex` — which shows that the board *reports* a page index, not
that it *accepts* one in the request under that spelling.

That distinction is the whole of this module, and it is not usajobs-specific:

* a value read out of a response says what the board sent back;
* a key present in a **recorded request** says what the board was asked.

Only the second certifies a request key, and only the second is what a fetcher
relies on when `max_pages` rises above 1. If the board ignores an unknown page
key, page 2 is a duplicate of page 1, the fetcher collects duplicate offers,
and nothing reports it — dedup may or may not catch it, and "may or may not"
is not a property.

**What counts as a capture here.** A package's capture is `probe/captured.json`
— "when and from what URL", the record that travels with the bytes in
`probe/`. For a POST board the URL alone does not identify the request, so the
record also carries the `body` it was taken with; that field is optional and a
capture predating it simply carries no body, which this reads as "no body was
recorded", never as "the body was empty".

**And how the record itself came to exist.** A capture says *when* and *from
what URL*; until #406 it never said *how*, so a record transcribed from a
command committed elsewhere and one written straight off the wire read
identically, and the difference had to be argued in a pull-request comment
rather than read in the file. `provenance` is that field — `live`,
`transcribed` or `unrecorded`. `usajobs_en` declares `transcribed`: its request
record is byte-identical to the re-runnable `retest` curl
`connectors/ruled-out.yaml` commits, and the response bytes beside it
(`Total: 43`, `ItemsPerPage: 25`, 25 rows) are that command's output. Nothing
*here* fails on an `unrecorded` capture — a provenance nobody has established is
not a defect, and stamping one on twenty files to make a number go green would
be the invention this module exists to refuse.

**T153 is what makes the field evidence rather than a label**, and it is a
separate module (`integral.capture_provenance`) because it asks a different
question of the same file: not "which request was measured" but "can this record
substantiate what it says about itself". It shipped advisory here — nothing
failed on any value, so a fabricated capture claiming `live` passed — and the
one change it made to this module's own reading is that a **missing** field is
no longer the same statement as a written `unrecorded`. `read_provenance` still
folds an absence into `UNRECORDED`, because reading a claim charitably is right;
enforcing one is where the two have to be told apart.

**The rule, per `pagination.mode`:**

* `query_param` — the named key must appear as a query-string key of the
  captured URL.
* `body_field` — the named key must appear as a top-level key of the captured
  request body.
* `path_segment` — the page number is positional, so there is no key for a
  capture to carry. The captured URL must instead match `url_pattern` with
  `{page}` bound to a number the connector would actually request
  (`start` … `start + max_pages - 1`).
* `none` — the package sends no page key, so there is nothing to certify.

Nothing here reads `probe/list.html`, `fixture/list.html` or any other
response body, and `test_a_page_index_read_from_a_response_does_not_certify_a_request_key`
holds that line: a probe whose *response* is full of the param name and full of
page indices, over a capture whose *request* carries neither, is still counted.

**The denominator is every request key across every shipped package** — the
query-string keys of `url_pattern` plus the top-level keys of `body_json` —
not merely the paginating ones. A metric named after the wrong outcome cannot
be satisfied by there being no such inputs, but it can be satisfied by there
being no *packages*, so `MINIMUM_REQUEST_KEYS` is the floor that refuses a
clean zero over an empty scan, and the count of the day is deliberately **not**
committed: it moves the moment anyone adds a connector, which is T100's and
T111's lesson about a denominator committed as an exact value.

**A reserved-TLD package is excluded, and says so.** `examplejobs_es` points at
`examplejobs.test`, which RFC 2606 and RFC 6761 guarantee will never resolve —
demanding a capture of a board that cannot be fetched is incoherent. The rule
is `connector_coverage.is_example_site`, reused rather than re-spelled, and the
excluded names are listed in the evidence so the exclusion is visible rather
than silent.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import yaml

from integral.connector_coverage import is_example_site, read_package
from integral.connector_health import PROBE_CAPTURE_FILE
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    PAGE_PLACEHOLDER,
    PROBE_DIRNAME,
    QUERY_PLACEHOLDER,
    ConnectorError,
    build_list_urls,
    load_connector,
    parse_connector,
    query_pair_names,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T113.json"

#: The floor the denominator is checked against, and what is committed in place
#: of the count of the day. Twenty packages ship today and declare 16 request
#: keys between them, so this leaves room for a package to be retired without a
#: false alarm while staying far above what an empty, unreadable or
#: example-only `connectors/` would produce. Raise it when the library grows;
#: it is a floor, not a target.
MINIMUM_REQUEST_KEYS = 12


# ---------------------------------------------------------------------------
# the URL side of the rule, probed rather than asserted
#
# The scan above reads what a package DECLARES against what its capture
# RECORDS, and that is only as strong as the coupling between `pagination.param`
# and the key a request actually carries. On the body side `ListPage`'s
# `_a_page_placeholder_and_a_body_field_imply_each_other` supplies that coupling
# at load. On the URL side nothing did, and the second-reader round on #406
# named three routes by which a package could send a page key no capture
# measured while this gate reported zero:
#
#   1. `pagination.param` naming a key the `url_pattern` does not hold —
#      `?p={page}` with `param: page`, over a capture of `?page=1`. The gate
#      finds `page` in the captured URL and passes; every request carries `p`.
#   2. `mode: none` with `{page}` still in the pattern. The scan short-circuits
#      ("nothing to certify") while `build_list_urls` still substitutes on the
#      text and fetches `?page=1` unchecked.
#   3. `query_param` with no `{page}` anywhere — the identical URL issued
#      `max_pages` times, which is the duplicate-offer harm this task is named
#      for.
#
# `connectors._a_page_placeholder_and_a_query_key_imply_each_other` closes all
# three at load. The probes below are how that is MEASURED rather than believed:
# each is a whole connector document, parsed, and — when it is one of the legal
# shapes — built into the requests it would issue. A probe that loads where the
# rule refuses it, or is refused where the rule allows it, is a defect named in
# the evidence. Reading the validator's source instead is the check T121's
# three defeated rounds are about.


@dataclass(frozen=True)
class UrlProbe:
    """One `url_pattern` / `pagination` pair, and the verdict the rule requires.

    `loads` and `issues` are written from the rule — "the key carrying the page
    number is the one the pagination names, it is the one a capture is read for,
    and something must vary" — not from running the validator. A fixture whose
    expected value was read off a run certifies the run.
    """

    name: str
    url_pattern: str
    pagination: dict[str, Any]
    #: Whether a well-formed library may contain this shape at all.
    loads: bool
    #: For a shape that loads, the exact URLs it must issue. Empty when it does
    #: not load, since there are none.
    issues: tuple[str, ...]
    #: The route this closes, or why the shape is legal. Cited, so a probe
    #: cannot drift into testing something the rule never said.
    route: str
    #: A POST board — the `body_field` mirror of route 2 needs one.
    body_json: dict[str, Any] | None = None


_PROBE_QUERY = "python"

URL_SIDE_PROBES: tuple[UrlProbe, ...] = (
    # ---- route 1: the certified key and the sent key were never the same key.
    UrlProbe(
        name="param names a query key the pattern does not hold",
        url_pattern="https://boards.test/jobs?p={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="route 1 — sends ?p=, and a capture of ?page= would certify it; fail-open",
    ),
    UrlProbe(
        name="param names a key holding a literal while another key holds the placeholder",
        url_pattern="https://boards.test/jobs?page=1&offset={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="route 1 — the named key is present in every URL and never varies, so a "
        "capture carrying it certifies nothing about `offset`; fail-open",
    ),
    UrlProbe(
        name="query_param mode over a placeholder that sits in the path",
        url_pattern="https://boards.test/jobs/{page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="route 1 — no query key holds the page number, so `param` names nothing "
        "the request carries; fail-open",
    ),
    # ---- route 2: a page key sent under a mode that certifies nothing.
    UrlProbe(
        name="mode none with the placeholder still in the pattern",
        url_pattern="https://boards.test/jobs?page={page}",
        pagination={"mode": "none", "max_pages": 1},
        loads=False,
        issues=(),
        route="route 2 — `mode: none` short-circuits the scan while ?page=1 still goes "
        "out, wholly unchecked; fail-open",
    ),
    UrlProbe(
        name="body_field mode with a second page slot in the URL",
        url_pattern="https://boards.test/Search/ExecuteSearch?page={page}",
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2},
        body_json={"Keyword": _PROBE_QUERY, "Page": PAGE_PLACEHOLDER},
        loads=False,
        issues=(),
        route="route 2, T109's shape on the URL half — the body key is certified and the "
        "URL key is a second substitution nothing declared; fail-open",
    ),
    # ---- route 3: nothing varies, so every page is the same request.
    UrlProbe(
        name="query_param mode with no placeholder anywhere",
        url_pattern="https://boards.test/jobs?page=1",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 3},
        loads=False,
        issues=(),
        route="route 3 — the identical URL issued max_pages times, which is the "
        "duplicate-offer harm the task names; fail-open",
    ),
    UrlProbe(
        name="path_segment mode with no placeholder anywhere",
        url_pattern="https://boards.test/jobs",
        pagination={"mode": "path_segment", "param": "page", "start": 1, "max_pages": 3},
        loads=False,
        issues=(),
        route="route 3, the positional flavour — nothing varies here either; fail-open",
    ),
    UrlProbe(
        name="a percent-encoded placeholder, which never substitutes",
        url_pattern="https://boards.test/jobs?page=%7Bpage%7D",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="route 3 in disguise — `%7Bpage%7D` decodes to the placeholder but "
        "`build_list_urls` substitutes on the raw text, so nothing varies; counting "
        "positions on `parse_qsl`'s decoded values would bless it. Fail-open",
    ),
    # ---- the T109 mirror: one page number, one position.
    UrlProbe(
        name="two query keys holding the placeholder, one of them named",
        url_pattern="https://boards.test/jobs?page={page}&p={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T109 on the URL half — `p` also varies, and no capture is read for it; fail-open",
    ),
    UrlProbe(
        name="the placeholder spelled into a query key's own name",
        url_pattern="https://boards.test/jobs?page={page}&{page}=1",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T109 on the URL half — a key whose own spelling varies by page can never "
        "be the key `param` names, and no capture can carry it; fail-open",
    ),
    # ---- the legal shapes. A check this aggressive would otherwise take the
    # library down with it, and every one of these is a committed package's
    # actual shape.
    UrlProbe(
        name="the ordinary shape: the named key holds the placeholder",
        url_pattern="https://boards.test/jobs?page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=True,
        issues=("https://boards.test/jobs?page=1", "https://boards.test/jobs?page=2"),
        route="legal — arbeitnow_en, builtin_en, nofluffjobs_en, wellfound_en",
    ),
    UrlProbe(
        name="a search slot beside the page slot, under a non-English key",
        url_pattern="https://boards.test/ofertas?te={query}&pagina={page}",
        pagination={"mode": "query_param", "param": "pagina", "start": 1, "max_pages": 2},
        loads=True,
        issues=(
            "https://boards.test/ofertas?te=python&pagina=1",
            "https://boards.test/ofertas?te=python&pagina=2",
        ),
        route="legal — tecnoempleo_es's shape; `{query}` is not a page slot",
    ),
    UrlProbe(
        name="a positional page number in the path",
        url_pattern="https://boards.test/jobs/{page}",
        pagination={"mode": "path_segment", "param": "page", "start": 1, "max_pages": 2},
        loads=True,
        issues=("https://boards.test/jobs/1", "https://boards.test/jobs/2"),
        route="legal — no key exists to name, which is why `path_segment` is certified "
        "by matching the whole captured URL instead",
    ),
    UrlProbe(
        name="a board with no second page, and no page slot",
        url_pattern="https://boards.test/jobs",
        pagination={"mode": "none", "max_pages": 1},
        loads=True,
        issues=("https://boards.test/jobs",),
        route="legal — pythonorg_en, remotive_en, jobsacuk_en and eight more",
    ),
    UrlProbe(
        name="a POST board whose page key is in the body and nowhere else",
        url_pattern="https://boards.test/Search/ExecuteSearch",
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2},
        body_json={"Keyword": _PROBE_QUERY, "Page": PAGE_PLACEHOLDER},
        loads=True,
        issues=(
            "https://boards.test/Search/ExecuteSearch",
            "https://boards.test/Search/ExecuteSearch",
        ),
        route="legal — the usajobs shape T89 added; two pages are the same URL and "
        "differ only in the payload",
    ),
)

#: The floor `URL_SIDE_PROBES` is checked against, committed in place of the
#: count of the day for T100's reason. Fifteen probes ship today; the names that
#: must stay are pinned by name in `tests/test_pagination_capture.py`, because a
#: count is satisfied by any N probes and a floor protects only against bulk
#: deletion.
MINIMUM_URL_SIDE_PROBES = 12


def _probe_document(probe: UrlProbe) -> str:
    """`probe` as a whole connector document, ready for `parse_connector`."""
    listing: dict[str, Any] = {
        "url_pattern": probe.url_pattern,
        "pagination": probe.pagination,
    }
    if probe.body_json is None:
        listing["item"] = ".job"
        listing["fields"] = {"text": {"css": ".body"}}
    else:
        listing["method"] = "POST"
        listing["body_json"] = probe.body_json
        listing["from_json"] = {
            "items": "Jobs",
            "fields": {"title": "Title", "text": "Summary", "detail_url": "Url"},
        }
    return yaml.safe_dump(
        {
            "site": "probeboard",
            "locale": "en",
            "version": "1.0.0",
            "last_verified": "2026-09-08",
            "auth": "none",
            "list": listing,
        },
        sort_keys=False,
    )


def probe_url_side() -> tuple[list[str], int]:
    """Run `URL_SIDE_PROBES`; return what disagreed with the rule, and how many ran.

    Behavioural, not textual. Every probe is parsed as a connector document and
    every loading one is built into the requests it would issue, so a validator
    that was deleted, weakened or replaced by a comment fails here — which is
    the lesson `integral.verified_gate` learned across three defeated rounds of
    reading a file's text.
    """
    defects: list[str] = []
    for probe in URL_SIDE_PROBES:
        try:
            connector = parse_connector(_probe_document(probe))
        except ConnectorError as exc:
            if probe.loads:
                defects.append(f"{probe.name}: refused a legal shape ({exc}) — {probe.route}")
            continue
        if not probe.loads:
            defects.append(f"{probe.name}: loaded a shape the rule refuses — {probe.route}")
            continue
        query = _PROBE_QUERY if QUERY_PLACEHOLDER in probe.url_pattern else None
        issued = tuple(build_list_urls(connector, query=query))
        if issued != probe.issues:
            defects.append(
                f"{probe.name}: issues {list(issued)}, not {list(probe.issues)} — {probe.route}"
            )
    return defects, len(URL_SIDE_PROBES)


#: How a `probe/captured.json` came to hold what it holds.
#:
#: `#406`'s third finding: the record said *when* and *from what URL*, and never
#: *how*, so "these bytes came off the wire into this file" and "this request was
#: written down from a command committed elsewhere" were indistinguishable — the
#: difference had to be argued in a pull-request comment, which is not where a
#: reader of the package looks. Two values and a default, because a vocabulary
#: nobody can spell wrongly is the only kind worth adding to twenty files.
LIVE = "live"
TRANSCRIBED = "transcribed"
UNRECORDED = "unrecorded"

#: The two a capture may *claim*. `UNRECORDED` is what a capture that declares
#: nothing — or declares something outside this vocabulary — reads as, so it is
#: deliberately not in here: the set is what a record asserts about its origin,
#: and "nobody established this" asserts none of it. Every shipped capture now
#: writes one of the three, `capture_provenance.DECLARABLE` being that wider
#: set — an absence used to be indistinguishable from a statement, which is the
#: hole T153 closed.
PROVENANCE = frozenset({LIVE, TRANSCRIBED})


def read_provenance(declared: Any) -> str:
    """`declared` as a provenance, `UNRECORDED` for anything unrecognised.

    Fail-closed on the *claim*, not on the package: an unknown spelling is
    "this capture does not say", never "this capture says something new". A
    typo that silently became a third category would be a provenance nobody
    agreed on, which is worse than an absence.
    """
    return declared if isinstance(declared, str) and declared in PROVENANCE else UNRECORDED


@dataclass(frozen=True)
class Capture:
    """The request a package's `probe/captured.json` records.

    `url` is what every capture has carried since the format existed; `body` is
    what a POST capture needs in addition, because two POSTs to one URL are two
    different requests. `present` distinguishes "no capture file" from "a
    capture that records no body" — the first is a package with no evidence at
    all, the second is a GET.
    """

    present: bool
    url: str | None
    body: Any
    #: How the record was produced — one of `PROVENANCE`, defaulting to
    #: `UNRECORDED`.
    provenance: str = UNRECORDED


def read_capture(package: Path) -> Capture:
    """`probe/captured.json` as the request it records, never raising.

    Absent, unreadable, not JSON, or JSON that is not an object all mean the
    same thing: this package records no request. That is a *finding* here, not
    an error — `connector_health` takes the same posture toward the same file
    for the same reason.
    """
    path = package / PROBE_DIRNAME / PROBE_CAPTURE_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return Capture(present=False, url=None, body=None)
    if not isinstance(payload, dict):
        return Capture(present=False, url=None, body=None)
    url = payload.get("url")
    return Capture(
        present=True,
        url=url if isinstance(url, str) else None,
        body=payload.get("body"),
        provenance=read_provenance(payload.get("provenance")),
    )


def query_keys(url: str | None) -> frozenset[str]:
    """The query-string keys of `url`. Empty for anything unparseable.

    `keep_blank_values` is on: `?page=` carries the key, and a board asked with
    an empty page is still a board that was asked with that key.
    """
    if not url:
        return frozenset()
    return frozenset(name for name, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True))


def declared_request_keys(url_pattern: str, body_json: Any) -> frozenset[str]:
    """Every request key a package sends: the URL's query keys and the body's.

    The denominator. `url_pattern` still carries its `{page}` and `{query}`
    placeholders at this point, which `parse_qsl` reads as ordinary values —
    the *keys* are what this counts, and those never contain a placeholder
    (`_literal_body_violations` refuses a key that does).
    """
    keys = set(query_keys(url_pattern))
    if isinstance(body_json, dict):
        keys.update(str(key) for key in body_json)
    return frozenset(keys)


def _page_numbers(start: int, max_pages: int) -> range:
    """The page numbers the connector would actually request."""
    return range(start, start + max_pages)


def _path_segment_measured(url_pattern: str, captured: str | None, pages: range) -> bool:
    """Does the captured URL match `url_pattern` at a page the connector requests?

    Under `path_segment` the page number is positional, so no key exists for a
    capture to carry and the key-presence rule has nothing to read. The
    equivalent evidence is that the captured URL *is* one of the URLs this
    pattern produces. `{query}` is left free — the candidate's terms are not
    part of what a page key certifies — while `{page}` must bind to a number in
    range, so a capture of some unrelated page is not accepted as evidence for
    the pages this connector issues.
    """
    if captured is None:
        return False
    parts = re.split(r"(\{page\}|\{query\})", url_pattern)
    if PAGE_PLACEHOLDER not in parts:
        return False
    pattern = "".join(
        r"(?P<page>\d+)"
        if part == PAGE_PLACEHOLDER
        else ".*"
        if part == QUERY_PLACEHOLDER
        else re.escape(part)
        for part in parts
    )
    match = re.fullmatch(pattern, captured)
    return match is not None and int(match.group("page")) in pages


@dataclass(frozen=True)
class Finding:
    """One pagination key that no capture measured."""

    package: str
    mode: str
    param: str | None
    reason: str

    def as_row(self) -> dict[str, str]:
        return {
            "package": self.package,
            "mode": self.mode,
            "param": self.param or "",
            "reason": self.reason,
            # Every finding here is fail-open by construction: the package
            # SENDS a key nothing measured, so the request goes out carrying a
            # page number in a field no board was ever asked with. The
            # fail-closed direction — refusing a key a capture does carry —
            # would cost a contributor a correction they can see.
            "direction": "fail-open",
        }


def check_package(package: Path) -> tuple[Finding | None, frozenset[str], int]:
    """One package: its finding (if any), its request keys, its paging keys.

    The third value is 0 or 1 — how many pagination keys this package was
    checked for — and it is what makes "no finding" distinguishable from "no
    package paginates at all".
    """
    try:
        connector = load_connector(package)
    except ConnectorError as exc:
        # Fail-closed. A package nobody can read is not a package whose page
        # key was measured, and skipping it would turn an unreadable library
        # into a clean number — `connector_coverage.read_package` refuses the
        # same shortcut for the same reason.
        return (
            Finding(package.name, "unreadable", None, f"connector.yaml did not load: {exc}"),
            frozenset(),
            1,
        )

    page = connector.list
    keys = declared_request_keys(page.url_pattern, page.body_json)
    mode = page.pagination.mode
    param = page.pagination.param
    if mode == "none":
        return None, keys, 0

    capture = read_capture(package)
    if not capture.present:
        return (
            Finding(package.name, mode, param, f"no {PROBE_DIRNAME}/{PROBE_CAPTURE_FILE} to read"),
            keys,
            1,
        )

    pages = _page_numbers(page.pagination.start, page.pagination.max_pages)
    if mode == "query_param":
        if param in query_keys(capture.url):
            return None, keys, 1
        return (
            Finding(
                package.name,
                mode,
                param,
                f"the captured URL {capture.url!r} ({capture.provenance}) carries no "
                f"{param!r} query key",
            ),
            keys,
            1,
        )
    if mode == "body_field":
        if isinstance(capture.body, dict) and param in capture.body:
            return None, keys, 1
        recorded = "no body" if capture.body is None else json.dumps(capture.body, sort_keys=True)
        return (
            Finding(
                package.name,
                mode,
                param,
                f"the captured request body ({recorded}, {capture.provenance}) carries no "
                f"{param!r} key",
            ),
            keys,
            1,
        )
    if mode == "path_segment":
        if _path_segment_measured(page.url_pattern, capture.url, pages):
            return None, keys, 1
        return (
            Finding(
                package.name,
                mode,
                param,
                f"the captured URL {capture.url!r} is not {page.url_pattern!r} at any page "
                f"in {pages.start}..{pages.stop - 1}",
            ),
            keys,
            1,
        )
    # Unreachable while `Pagination.mode` is the Literal it is today, and
    # fail-closed on the day somebody widens it: a mode this module has never
    # heard of has certainly not been shown to be measured.
    return (
        Finding(package.name, mode, param, f"unknown pagination mode {mode!r}"),
        keys,
        1,
    )


def measure(directory: Path | None = None) -> dict[str, Any]:
    """Every pagination key a shipped package sends that no capture measured.

    The default library is resolved at call time rather than bound as a default
    argument, so `DEFAULT_CONNECTORS_DIR` and `MINIMUM_REQUEST_KEYS` are both
    substitutable — a test that could only ever run against the committed
    library can only ever be run against a library that is already passing.
    """
    directory = DEFAULT_CONNECTORS_DIR if directory is None else directory
    packages = sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []

    examples: list[str] = []
    findings: list[Finding] = []
    request_keys = 0
    paginated_checked = 0
    scanned = 0
    for package in packages:
        if is_example_site(read_package(package).site):
            examples.append(package.name)
            continue
        scanned += 1
        finding, keys, checked = check_package(package)
        request_keys += len(keys)
        paginated_checked += checked
        if finding is not None:
            findings.append(finding)

    # The scan above says the committed library is clean; the probes say a
    # library that was not could not load. Both are this gate: #406 found the
    # library clean of all three URL-side routes and the schema silent about
    # every one of them, which is a zero resting on nothing.
    url_side_defects, url_side_probes = probe_url_side()

    measured: dict[str, Any] = {
        "paginated_request_keys_no_capture_measured": len(findings),
        "paginated_request_keys_checked": paginated_checked,
        "request_keys_scanned": request_keys,
        "packages_scanned": scanned,
        "example_packages_excluded": examples,
        "findings": [finding.as_row() for finding in findings],
        "url_side_routes_open": len(url_side_defects),
        "url_side_probes_checked": url_side_probes,
        "url_side_defects": url_side_defects,
        "fail_open": sum(1 for finding in findings if finding.as_row()["direction"] == "fail-open")
        + len(url_side_defects),
        "gate_status": "measured",
    }
    if request_keys < MINIMUM_REQUEST_KEYS:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {request_keys} request key(s) across {scanned} package(s) "
            f"(floor {MINIMUM_REQUEST_KEYS}) — zero unmeasured page keys over a library "
            "nobody read is not a pass"
        )
    elif url_side_probes < MINIMUM_URL_SIDE_PROBES:
        # The same refusal, for the same reason, on the other half: an emptied
        # probe table reports zero open routes.
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {url_side_probes} URL-side probe(s) (floor {MINIMUM_URL_SIDE_PROBES}) "
            "— zero open routes over a table nobody filled is not a pass"
        )
    return measured


def record(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured.

    The live counts are dropped and the floor is committed in their place, for
    T100's reason: `request_keys_scanned` and `packages_scanned` move the
    moment anybody adds or removes a connector, so committing them as exact
    values reddens `make evidence` on a change that is not a finding. What must
    not move is the numerator, and it does not.

    `paginated_request_keys_checked` is dropped for the same reason and is
    still asserted by `test_the_scan_reaches_the_packages_that_paginate`: the
    number of paginating packages is a property of the library on the day, not
    of this gate.

    `url_side_probes_checked` is dropped and floored too, and that one is not
    about the library — it is `test_connector_pagination`'s argument that an
    exact count in the evidence is doing a name's job badly: any N probes
    satisfy it, so the protection it gives a particular probe is coincidental.
    The probes that must stay are pinned **by name** in
    `tests/test_pagination_capture.py`; the floor only refuses bulk deletion.
    """
    dropped = (
        "request_keys_scanned",
        "packages_scanned",
        "paginated_request_keys_checked",
        "url_side_probes_checked",
    )
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["request_keys_scanned_at_least"] = MINIMUM_REQUEST_KEYS
    committed["url_side_probes_at_least"] = MINIMUM_URL_SIDE_PROBES
    return committed


def write_evidence(evidence: Path | None = None, directory: Path | None = None) -> dict[str, Any]:
    """Measure and record `status/evidence/T113.json`.

    Returns what was measured; writes what is recorded. A run that breaches the
    floor writes nothing — the only record it could write is one asserting a
    floor the run never met, and that artefact is what the next healthy run's
    `make evidence` would diff against (the ordering #297 got wrong).
    """
    evidence = DEFAULT_EVIDENCE_PATH if evidence is None else evidence
    measured = measure(directory)
    if measured["gate_status"] == "unmeasured":
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record(measured), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return measured


# ---------------------------------------------------------------------------
# T154 — the fourth URL-side route: a query key sent twice
#
# `_a_page_placeholder_and_a_query_key_imply_each_other`'s routes 1-3 are all
# read off *where the placeholder sits* in `url_pattern`. `?page=1&page={page}`
# holds it at exactly one position, under exactly the name `pagination.param`
# names — every one of those checks is satisfied — while the request this
# issues carries `page` **twice**, once fixed at a value no capture was ever
# taken at that position. `pagination_capture.query_keys` reads a captured
# URL into a *set* of names, so a capture of either page's request still
# contains `page` and certifies the pair a server may or may not honour.
#
# `connectors._a_page_placeholder_and_a_query_key_imply_each_other` closes it
# by counting **occurrences of the name** (`connectors.query_pair_names`, over
# both `&`- and `;`-separated pairs — see `connectors._QUERY_PAIR_SEPARATORS`),
# not positions of the placeholder, checked once ahead of the per-`mode`
# dispatch rather than inside `query_param`'s own branch — so it is closed on
# two axes a first version answered as one enumerated case:
#
# * the **mode** axis — a duplicated query key is a defect of the URL, which
#   every mode that names a `param` shares (`body_field` included: a POST
#   board's *body* field can be certified while its *URL* repeats the same
#   name, and a framework merging query/body namespaces may honour the fixed
#   query occurrence instead);
# * the **separator** axis — RFC 3986 §3.4 states no `name=value` pair
#   grammar at all (its `query` ABNF is `*( pchar / "/" / "?" )`, and calls
#   pairs only a frequent *usage*); the grammar this actually rests on is
#   `application/x-www-form-urlencoded`, which `;` is not part of — but is a
#   historical alternate (RFC 1866, pre-5.4 PHP) some servers still honour, so
#   it counts as a pair boundary here beside `&`.
#
# Measured the same way T113's own three routes are: a well-formed library can
# never carry an instance of what the load-time rule refuses, so a scan of the
# committed `connectors/` directory finds nothing to certify either way — the
# probes below are what would notice the rule going missing, weakening, or
# being satisfied by a comment instead.
DEFAULT_T154_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T154.json"

DUPLICATE_KEY_PROBES: tuple[UrlProbe, ...] = (
    UrlProbe(
        name="the named key sent twice, the fixed value first",
        url_pattern="https://boards.test/jobs?page=1&page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T154 route 4 — a capture of either page's request still carries `page`, so "
        "the fixed occurrence is certified by the name alone; fail-open",
    ),
    UrlProbe(
        name="the named key sent twice, the fixed value second",
        url_pattern="https://boards.test/jobs?page={page}&page=1",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T154 route 4, the other order — the rule counts occurrences of the name, "
        "not which position the placeholder happens to occupy; fail-open",
    ),
    UrlProbe(
        name="the same route under a name that does not spell 'page'",
        url_pattern="https://boards.test/search?p=1&p={page}",
        pagination={"mode": "query_param", "param": "p", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T154 route 4, generalised — keyed to whatever pagination.param names, not "
        "to the literal spelling 'page'; fail-open",
    ),
    UrlProbe(
        name="a duplicate under an unrelated key is not this rule's business",
        url_pattern="https://boards.test/jobs?tag=a&tag=b&page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=True,
        issues=(
            "https://boards.test/jobs?tag=a&tag=b&page=1",
            "https://boards.test/jobs?tag=a&tag=b&page=2",
        ),
        route="control — only the name pagination.param certifies is counted, so a board "
        "that happens to repeat some other filter is unaffected; refusing this would take "
        "a real shape down with the fix",
    ),
    UrlProbe(
        name="the ordinary single-occurrence shape still loads",
        url_pattern="https://boards.test/jobs?page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=True,
        issues=("https://boards.test/jobs?page=1", "https://boards.test/jobs?page=2"),
        route="control — the shape every paginating GET package in this library actually uses",
    ),
    # ---- the mode axis (F1): the first version lived inside `query_param`'s
    # own branch, so `body_field` (and `none`) never reached it at all.
    UrlProbe(
        name="the named key sent twice, across mode: body_field's own query string",
        url_pattern="https://boards.test/Search/ExecuteSearch?Page=1&Page=2",
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 3},
        body_json={"Keyword": _PROBE_QUERY, "Page": PAGE_PLACEHOLDER},
        loads=False,
        issues=(),
        route="T154 route 4, the mode axis (F1) — the certifying key lives in the body, "
        "but the URL repeats its own name too; a framework that merges query and body "
        "namespaces ($_REQUEST, Flask's request.values, Rails' params) may honour the "
        "fixed query occurrence over the varying body one; fail-open",
    ),
    UrlProbe(
        name="a body_field board with one fixed query pair beside the body field still loads",
        url_pattern="https://boards.test/Search/ExecuteSearch?Page=1",
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2},
        body_json={"Keyword": _PROBE_QUERY, "Page": PAGE_PLACEHOLDER},
        loads=True,
        issues=(
            "https://boards.test/Search/ExecuteSearch?Page=1",
            "https://boards.test/Search/ExecuteSearch?Page=1",
        ),
        route="control — a single, non-duplicated query pair beside the varying body field "
        "is not this rule's business, on the mode axis the same way the unrelated-key "
        "control is on the name axis",
    ),
    # ---- the separator axis (F2).
    UrlProbe(
        name="the named key sent twice via a ';'-separated pair",
        url_pattern="https://boards.test/jobs?page=1;page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
        loads=False,
        issues=(),
        route="T154 route 4, the separator axis (F2) — ';' is the historical alternate "
        "pair separator (RFC 1866, pre-5.4 PHP's arg_separator.input); a server that "
        "still splits on it sees `page` twice, and one that does not sees a value "
        "(`1;page=1`, `1;page=2`) that never parses as a page number either way; "
        "fail-open under both readings",
    ),
)

#: The floor `DUPLICATE_KEY_PROBES` is checked against, committed in place of
#: the count of the day for T100's reason — but set **equal** to today's count
#: (8) rather than below it: the by-name pin in
#: `tests/test_pagination_capture.py` already protects every individual shape,
#: so a lower floor's only effect would be slack that absorbs a bulk deletion
#: the pin does not happen to name — the second reader's point on F5. Equal to
#: the population, the first deletion of any kind breaches it.
MINIMUM_DUPLICATE_KEY_PROBES = 8

#: The floor the real-library half of this gate is checked against.
#:
#: **Occurrences of a query key, not distinct names** (F6): `query_keys`
#: returns a `frozenset`, so a `url_pattern` naming a key twice would
#: contribute 1 to a count built from it — collapsing the very duplication
#: this gate exists to measure out of its own denominator. `query_pair_names`
#: (occurrences, `connectors.py`) is what this counts instead.
#:
#: **Scoped to the packages route 4 actually reaches** (F6): every package
#: whose `pagination.mode` is not `"none"` — the same test route 4's own load
#: check applies to, after the mode-axis fix (F1) — not every shipped package
#: regardless of mode. Six packages ship in that scope today and declare
#: eight occurrences between them (`arbeitnow_en`, `builtin_en`,
#: `nofluffjobs_en`, `wellfound_en` one each; `jobfluent_es`, `tecnoempleo_es`
#: two each). The floor leaves room for **one** of the two double-key
#: packages to retire without a false alarm — losing `tecnoempleo_es` (2)
#: leaves 6, still at or above the floor — while losing both would leave 4,
#: below it, and staying far above what a library with no package this rule
#: reaches would produce (0). Raise it when the library grows; it is a floor,
#: not a target, mirroring `MINIMUM_REQUEST_KEYS`'s own stated margin.
MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED = 5


def probe_duplicate_page_keys() -> tuple[list[str], int]:
    """Run `DUPLICATE_KEY_PROBES`; return what disagreed with the rule, and how
    many ran. The same shape as `probe_url_side`, for the same reason:
    behavioural, so a validator deleted, weakened, or replaced by a comment
    fails here rather than reading as fixed."""
    defects: list[str] = []
    for probe in DUPLICATE_KEY_PROBES:
        try:
            connector = parse_connector(_probe_document(probe))
        except ConnectorError as exc:
            if probe.loads:
                defects.append(f"{probe.name}: refused a legal shape ({exc}) — {probe.route}")
            continue
        if not probe.loads:
            defects.append(f"{probe.name}: loaded a shape the rule refuses — {probe.route}")
            continue
        issued = tuple(build_list_urls(connector))
        if issued != probe.issues:
            defects.append(
                f"{probe.name}: issues {list(issued)}, not {list(probe.issues)} — {probe.route}"
            )
    return defects, len(DUPLICATE_KEY_PROBES)


def measure_duplicate_page_keys(directory: Path | None = None) -> dict[str, Any]:
    """T154's evidence: the committed library's query-key occurrences (the
    denominator, resolved at call time for the reason `measure` gives), plus
    the probes above.

    The real-library half can only ever find zero — a package carrying route
    4's shape cannot load once
    `connectors._a_page_placeholder_and_a_query_key_imply_each_other` refuses
    it, so nothing in `connectors/` can ever exhibit the defect this scans
    for. That is the same posture `probe_url_side` already takes toward
    routes 1-3, not a gap in this one: the scan says the committed library is
    clean, and the probes are what would notice the *rule* going missing
    rather than the library staying honest by construction.

    **Scoped to `pagination.mode != "none"`, and counted in occurrences, not
    distinct names (F6).** A package with `mode: "none"` sends no page key at
    all — route 4 never reaches it, so pooling it into the denominator would
    be measuring a population the rule does not touch. And `query_keys`
    returns a `frozenset`: summing its length would make a `url_pattern`
    naming a key twice contribute *fewer* occurrences to scan than one naming
    two distinct keys once each, which erases the very phenomenon a
    duplicate-key gate exists to count. `connectors.query_pair_names` returns
    one entry per occurrence for exactly this reason.
    """
    directory = DEFAULT_CONNECTORS_DIR if directory is None else directory
    packages = sorted(p for p in directory.iterdir() if p.is_dir()) if directory.is_dir() else []

    query_key_occurrences_scanned = 0
    paginated_packages_scanned = 0
    for package in packages:
        if is_example_site(read_package(package).site):
            continue
        try:
            connector = load_connector(package)
        except ConnectorError:
            # An unreadable package is T113's finding, not this gate's, and it
            # sends no request at all — contributing no occurrences either way
            # is the honest count, not a skipped one.
            continue
        if connector.list.pagination.mode == "none":
            # Route 4 never reaches a package with no page key at all —
            # pooling it in would count a population outside what the rule
            # touches (F6).
            continue
        paginated_packages_scanned += 1
        query_key_occurrences_scanned += len(query_pair_names(connector.list.url_pattern))

    defects, probes_checked = probe_duplicate_page_keys()

    measured: dict[str, Any] = {
        "duplicated_page_keys_certified": len(defects),
        "query_key_occurrences_scanned": query_key_occurrences_scanned,
        "paginated_packages_scanned": paginated_packages_scanned,
        "duplicate_key_probes_checked": probes_checked,
        "defects": defects,
        "gate_status": "measured",
    }
    if query_key_occurrences_scanned < MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {query_key_occurrences_scanned} query-key occurrence(s) across "
            f"{paginated_packages_scanned} paginated package(s) "
            f"(floor {MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED}) — zero certified duplicates "
            "over a library nobody read is not a pass"
        )
    elif probes_checked < MINIMUM_DUPLICATE_KEY_PROBES:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {probes_checked} probe(s) (floor {MINIMUM_DUPLICATE_KEY_PROBES}) — "
            "zero certified duplicates over a table nobody filled is not a pass"
        )
    return measured


def record_duplicate_page_keys(measured: dict[str, Any]) -> dict[str, Any]:
    """What is committed, out of what was measured —
    `query_key_occurrences_scanned`, `paginated_packages_scanned` and
    `duplicate_key_probes_checked` are dropped and floored for T100's reason:
    they move the moment anybody adds or removes a connector or a probe, and
    committing them as exact values would redden `make evidence` on a change
    that is not a finding. The numerator is not dropped."""
    dropped = (
        "query_key_occurrences_scanned",
        "paginated_packages_scanned",
        "duplicate_key_probes_checked",
    )
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["query_key_occurrences_scanned_at_least"] = MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED
    committed["duplicate_key_probes_at_least"] = MINIMUM_DUPLICATE_KEY_PROBES
    return committed


def write_duplicate_page_keys_evidence(
    evidence: Path | None = None, directory: Path | None = None
) -> dict[str, Any]:
    """Measure and record `status/evidence/T154.json`. Writes nothing on a
    breached floor, for the same ordering reason `write_evidence` gives."""
    evidence = DEFAULT_T154_EVIDENCE_PATH if evidence is None else evidence
    measured = measure_duplicate_page_keys(directory)
    if measured["gate_status"] == "unmeasured":
        return measured
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(
        json.dumps(record_duplicate_page_keys(measured), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.pagination_capture [evidence-path]` → T113's
    evidence and, in the same run, T154's — the fenced gate for both tasks
    invokes only this module, so one entry point has to write both files.

    The two gates' exit codes are combined by **severity**, not by which ran
    last: `1` (a real failure) from either beats `3` (unmeasured) from the
    other, which beats `0`. T154's own `unmeasured` reads `1`, not the `3`
    T113's keeps — see the exit-code table in this function's body for why:
    matching `capture_provenance._main` (T153, the same module family)
    rather than repeating T113's older, `make evidence`-transparent
    convention in a second gate that ships beside it (F3).
    """
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    evidence_path = Path(positional[0]) if positional else None
    measured = write_evidence(evidence_path)
    print(json.dumps(measured, ensure_ascii=False))

    t113_code = 0
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        t113_code = 3
    else:
        for row in measured["findings"]:
            print(
                f"{row['direction']}: {row['package']} sends {row['param']!r} "
                f"({row['mode']}) — {row['reason']}",
                file=sys.stderr,
            )
        for defect in measured["url_side_defects"]:
            print(f"fail-open: url-side probe — {defect}", file=sys.stderr)
        if (
            measured["paginated_request_keys_no_capture_measured"]
            or measured["url_side_routes_open"]
        ):
            t113_code = 1

    duplicate_evidence_path = None if evidence_path is None else evidence_path.parent / "T154.json"
    duplicate_measured = write_duplicate_page_keys_evidence(duplicate_evidence_path)
    print(json.dumps(duplicate_measured, ensure_ascii=False))

    t154_code = 0
    if duplicate_measured["gate_status"] == "unmeasured":
        print(duplicate_measured["unmeasured_reason"], file=sys.stderr)
        # T115/T153's rule, applied to this gate rather than merely cited
        # beside it (F3): a floor breach that `make evidence` prints as
        # "unmeasured (recorded)" and walks past — while the last-committed
        # T154.json still reads `gate_status: measured` — is a floor that
        # does not fail the gate, which is decoration. `1`, not `3`.
        t154_code = 1
    else:
        for defect in duplicate_measured["defects"]:
            print(f"fail-open: duplicate-key probe — {defect}", file=sys.stderr)
        if duplicate_measured["duplicated_page_keys_certified"]:
            t154_code = 1

    if t113_code == 1 or t154_code == 1:
        return 1
    if t113_code == 3 or t154_code == 3:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
