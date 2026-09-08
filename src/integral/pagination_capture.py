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
`transcribed`, or absent, which reads as `unrecorded` and is never written back.
`usajobs_en` declares `transcribed`: its request record is byte-identical to the
re-runnable `retest` curl `connectors/ruled-out.yaml` commits, and the response
bytes beside it (`Total: 43`, `ItemsPerPage: 25`, 25 rows) are that command's
output. Nothing here fails on an `unrecorded` capture — a provenance nobody has
established is not a defect, and stamping one on twenty files to make a number
go green would be the invention this module exists to refuse.

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

#: The two a capture may declare. `UNRECORDED` is what a capture that declares
#: nothing — or declares something outside this vocabulary — reads as; it is
#: never written, so an old capture is not retro-labelled by a schema it predates.
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


def _main(argv: list[str]) -> int:
    """`python -m integral.pagination_capture [evidence-path]` → T113's evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    measured = write_evidence(Path(positional[0]) if positional else None)
    print(json.dumps(measured, ensure_ascii=False))
    if measured["gate_status"] == "unmeasured":
        print(measured["unmeasured_reason"], file=sys.stderr)
        return 3
    for row in measured["findings"]:
        print(
            f"{row['direction']}: {row['package']} sends {row['param']!r} "
            f"({row['mode']}) — {row['reason']}",
            file=sys.stderr,
        )
    for defect in measured["url_side_defects"]:
        print(f"fail-open: url-side probe — {defect}", file=sys.stderr)
    return (
        1
        if measured["paginated_request_keys_no_capture_measured"]
        or measured["url_side_routes_open"]
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
