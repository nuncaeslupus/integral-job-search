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

from integral.connector_coverage import is_example_site, read_package
from integral.connector_health import PROBE_CAPTURE_FILE
from integral.connectors import (
    DEFAULT_CONNECTORS_DIR,
    PAGE_PLACEHOLDER,
    PROBE_DIRNAME,
    QUERY_PLACEHOLDER,
    ConnectorError,
    load_connector,
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
                f"the captured URL {capture.url!r} carries no {param!r} query key",
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
                f"the captured request body ({recorded}) carries no {param!r} key",
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

    measured: dict[str, Any] = {
        "paginated_request_keys_no_capture_measured": len(findings),
        "paginated_request_keys_checked": paginated_checked,
        "request_keys_scanned": request_keys,
        "packages_scanned": scanned,
        "example_packages_excluded": examples,
        "findings": [finding.as_row() for finding in findings],
        "fail_open": sum(1 for finding in findings if finding.as_row()["direction"] == "fail-open"),
        "gate_status": "measured",
    }
    if request_keys < MINIMUM_REQUEST_KEYS:
        measured["gate_status"] = "unmeasured"
        measured["unmeasured_reason"] = (
            f"only {request_keys} request key(s) across {scanned} package(s) "
            f"(floor {MINIMUM_REQUEST_KEYS}) — zero unmeasured page keys over a library "
            "nobody read is not a pass"
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
    """
    dropped = ("request_keys_scanned", "packages_scanned", "paginated_request_keys_checked")
    committed = {key: value for key, value in measured.items() if key not in dropped}
    committed["request_keys_scanned_at_least"] = MINIMUM_REQUEST_KEYS
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
    return 1 if measured["paginated_request_keys_no_capture_measured"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
