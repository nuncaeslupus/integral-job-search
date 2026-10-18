"""T113 — a page key a package sends must be one a capture actually carried.

Every package a test measures here is a **copy of the committed reference
package**, broken one way at a time, for the reason `test_connector_contract.py`
gives: a hand-built package can fail for a reason nobody intended and still look
like proof, whereas a copy of the real thing was passing a moment ago and fails
for exactly the edit that was made.

The reference package points at `examplejobs.test`, a reserved TLD, which the
scan excludes — so almost every test here first gives the copy a site that could
be a real board. That is not a workaround: it is the exclusion rule being
exercised from both sides, and
`test_a_reserved_tld_package_is_excluded_and_says_so` is the other side.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import yaml

from integral import capture_provenance as cp
from integral import pagination_capture as pc
from integral.connectors import (
    PAGE_PLACEHOLDER,
    ConnectorError,
    build_list_requests,
    build_list_urls,
    load_connector,
    load_connectors,
    query_pair_names,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIBRARY = _REPO_ROOT / "connectors"
_REFERENCE = _LIBRARY / "examplejobs_es"

#: A site that is not a reserved example domain, so a copy of the reference
#: package is scanned rather than excluded.
_REAL_SITE = "realboard.io"


# ---------------------------------------------------------------------------
# building a library to measure


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A one-package library holding a copy of the committed reference."""
    root = tmp_path / "connectors"
    shutil.copytree(_REFERENCE, root / _REFERENCE.name)
    return root


@pytest.fixture
def low_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure a one-package library at all.

    The floor refuses a clean zero over a library nobody read, which is exactly
    what a one-package fixture is. It is asserted on its own terms by
    `test_a_library_too_small_to_measure_reports_unmeasured`; every test that
    takes this fixture is about the rule rather than the floor.
    """
    monkeypatch.setattr(pc, "MINIMUM_REQUEST_KEYS", 1)


def _package(library: Path) -> Path:
    return library / _REFERENCE.name


def _real_board(library: Path) -> None:
    """Give the copy a site that is not a reserved example domain."""
    meta_path = _package(library) / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    meta["site"] = _REAL_SITE
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


def _edit_connector(library: Path, **changes: Any) -> None:
    """Rewrite the copy's `list` block. A key given `None` is removed."""
    path = _package(library) / "connector.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            document["list"].pop(key, None)
        else:
            document["list"][key] = value
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _as_post_board(library: Path, body_json: dict[str, Any]) -> None:
    """Turn the copy into the usajobs shape: a POST whose page key is in the body."""
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/search",
        method="POST",
        body_json=body_json,
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2},
        item=None,
        fields=None,
        from_json={"items": "Jobs", "fields": {"title": "Title", "detail_url": "Url"}},
    )


def _write_capture(library: Path, **fields: Any) -> None:
    probe = _package(library) / "probe"
    probe.mkdir(exist_ok=True)
    (probe / "captured.json").write_text(json.dumps(fields, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# the denominator, over the committed library
#
# The gate itself — `test_every_pagination_key_a_package_sends_appears_in_a_capture`
# — lives in `tests/test_connector_contract.py`, beside the other assertion about
# what every shipped package must satisfy, and is the name `status/plan.md`'s row
# for T113 declared before this module existed.


def test_the_scan_reaches_the_packages_that_paginate() -> None:
    """The denominator, live rather than committed.

    `record` drops these counts (T100: an exact denominator drifts the moment
    anybody adds a connector), so this is where they are checked at all. A
    library that paginates nowhere would make the gate vacuous, and that is
    visible here and nowhere else.
    """
    measured = pc.measure(_LIBRARY)

    assert measured["paginated_request_keys_checked"] >= 5
    assert measured["packages_scanned"] >= 15


# ---------------------------------------------------------------------------
# the rule, mode by mode


def test_a_query_param_page_key_absent_from_the_captured_url_is_reported(
    library: Path, low_floor: None
) -> None:
    _real_board(library)
    _write_capture(library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs", status=200)

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    (finding,) = measured["findings"]
    assert finding["package"] == _REFERENCE.name
    assert finding["param"] == "page"
    assert finding["direction"] == "fail-open"


def test_a_query_param_page_key_present_in_the_captured_url_passes(
    library: Path, low_floor: None
) -> None:
    _real_board(library)
    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs?page=2", status=200
    )

    assert pc.measure(library)["findings"] == []


def test_an_unparseable_captured_url_is_a_finding_not_a_crash(
    library: Path, low_floor: None
) -> None:
    """An unmatched IPv6 bracket makes `urlsplit` raise `ValueError` (round-4
    second reader on PR #461, T171, observation O-B). `query_keys` must read
    that as "no keys", the same as a missing capture, so `measure()` names the
    package instead of ending the whole run with a traceback."""
    _real_board(library)
    _write_capture(
        library, captured_at="2026-09-08", url=f"https://[::1/{_REAL_SITE}/jobs", status=200
    )

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    (finding,) = measured["findings"]
    assert finding["package"] == _REFERENCE.name
    assert finding["param"] == "page"
    assert finding["direction"] == "fail-open"


def test_a_body_field_page_key_is_read_from_the_captured_body(
    library: Path, low_floor: None
) -> None:
    """The usajobs shape: two POSTs to one URL are two different requests, so
    the URL cannot answer for the body and the capture has to record it."""
    _real_board(library)
    _as_post_board(library, {"Keyword": "python", "Page": "{page}"})
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/search",
        method="POST",
        body={"Keyword": "python"},
        status=200,
    )

    measured = pc.measure(library)
    assert measured["paginated_request_keys_no_capture_measured"] == 1
    assert "no 'Page' key" in measured["findings"][0]["reason"]

    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/search",
        method="POST",
        body={"Keyword": "python", "Page": 2},
        status=200,
    )
    assert pc.measure(library)["findings"] == []


def test_a_capture_with_no_body_is_not_a_capture_with_an_empty_body(
    library: Path, low_floor: None
) -> None:
    """A capture predating the `body` field records no body. Reading that as
    `{}` would be reading silence as a measurement, so it is a finding."""
    _real_board(library)
    _as_post_board(library, {"Keyword": "python", "Page": "{page}"})
    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/search", status=200
    )

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    assert "no body" in measured["findings"][0]["reason"]


def test_a_path_segment_page_is_measured_by_the_url_the_connector_would_issue(
    library: Path, low_floor: None
) -> None:
    """The page number is positional under this mode, so there is no key for a
    capture to carry and the equivalent evidence is that the captured URL *is*
    one of the URLs the pattern produces — at a page in range, not any page."""
    _real_board(library)
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/jobs/page/{{page}}",
        pagination={"mode": "path_segment", "param": "page", "start": 1, "max_pages": 2},
    )

    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs/page/9", status=200
    )
    assert pc.measure(library)["paginated_request_keys_no_capture_measured"] == 1

    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs/page/2", status=200
    )
    assert pc.measure(library)["findings"] == []


def test_a_candidates_search_terms_do_not_have_to_match(library: Path, low_floor: None) -> None:
    """`{query}` is whatever the candidate asked for and is not part of what a
    page key certifies. Requiring it to match would refuse every capture of a
    board that takes search terms."""
    _real_board(library)
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/jobs/{{query}}/page/{{page}}",
        pagination={"mode": "path_segment", "param": "page", "start": 1, "max_pages": 2},
    )
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs/python/page/2",
        status=200,
    )

    assert pc.measure(library)["findings"] == []


def test_a_package_that_declares_no_pagination_is_not_checked(
    library: Path, low_floor: None
) -> None:
    _real_board(library)
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/jobs?q=python",
        pagination={"mode": "none", "max_pages": 1},
    )
    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs?q=python", status=200
    )

    measured = pc.measure(library)

    assert measured["findings"] == []
    assert measured["paginated_request_keys_checked"] == 0
    # The key is still in the denominator: a package that sends `q` and never
    # paginates is scanned, it simply has no page key to certify.
    assert measured["request_keys_scanned"] == 1


def test_a_post_boards_body_keys_are_in_the_denominator(library: Path, low_floor: None) -> None:
    """The denominator is "the request keys across every shipped package", and
    for a POST board most of them are in the body rather than in the URL.

    Counting only the query string would shrink the denominator silently — the
    floor would still be cleared, the numerator would still read 0, and the
    scan would be measuring less than it says. Found by a mutation that deleted
    the body half and passed every other test here.
    """
    _real_board(library)
    _as_post_board(library, {"Keyword": "python", "ResultsPerPage": 25, "Page": "{page}"})
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/search",
        method="POST",
        body={"Keyword": "python", "Page": 2},
        status=200,
    )

    measured = pc.measure(library)

    assert measured["findings"] == []
    # Three body keys and no query keys: a URL-only denominator reads 0 here.
    assert measured["request_keys_scanned"] == 3
    assert pc.declared_request_keys(
        f"https://{_REAL_SITE}/search?q={{query}}", {"Keyword": "python", "Page": "{page}"}
    ) == frozenset({"q", "Keyword", "Page"})


# ---------------------------------------------------------------------------
# the distinction the task is about


def test_a_page_index_read_from_a_response_does_not_certify_a_request_key(
    library: Path, low_floor: None
) -> None:
    """T113's whole argument, as a test.

    `Pager.CurrentPageIndex` was read out of the usajobs **response** and the
    request key was named after it. A response saying "you are on page 1" says
    the board reports a page index; it says nothing about what the board accepts
    in a request, and if it accepts nothing then page 2 duplicates page 1 and
    the fetcher collects duplicate offers.

    So this package's captured *response* is saturated with the param name and
    with page indices — in `probe/list.html`, in `fixture/list.html`, and in a
    `pager` object inside the capture record itself — while the captured
    *request* carries neither. The count must still be 1. Anybody who "fixes"
    this check by grepping a probe body fails here.
    """
    _real_board(library)
    response = (
        '<html><body><div class="pager" data-page="1" data-next-page="2">'
        '<a href="?page=1">1</a><a href="?page=2">2</a></div>'
        '<div class="job-card"><a class="job-link" href="/j/1"></a>'
        '<span class="job-title">Dev</span><span class="job-company">Co</span>'
        "</div></body></html>"
    )
    for name in ("probe/list.html", "fixture/list.html"):
        target = _package(library) / name
        target.parent.mkdir(exist_ok=True)
        target.write_text(response, encoding="utf-8")
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        pager={"CurrentPageIndex": 1, "NextPageIndex": 2, "page": 1},
    )

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    assert measured["findings"][0]["param"] == "page"


def test_the_usajobs_package_issues_the_request_that_was_measured() -> None:
    """T152 restored `Page`: a live POST carrying `"Page": 2` is committed, so
    the connector issues pages 1 and 2 and the committed capture is page 2's
    body, one of the requests the engine builds."""
    package = _LIBRARY / "usajobs_en"
    requests = build_list_requests(load_connector(package))

    assert [json.loads(r.body or b"null") for r in requests] == [
        {"Keyword": "python", "ResultsPerPage": 25, "Page": 1},
        {"Keyword": "python", "ResultsPerPage": 25, "Page": 2},
    ]
    assert pc.read_capture(package).body == {"Keyword": "python", "ResultsPerPage": 25, "Page": 2}


# ---------------------------------------------------------------------------
# what a missing or unreadable package does


def test_a_package_with_no_capture_at_all_is_reported(library: Path, low_floor: None) -> None:
    """The reference package ships no `probe/`, which is legal — the directory
    is optional — and is nonetheless "no capture measured this key"."""
    _real_board(library)
    assert not (_package(library) / "probe").exists()

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    assert "no probe/captured.json" in measured["findings"][0]["reason"]


def test_an_unparseable_capture_is_reported_rather_than_raising(
    library: Path, low_floor: None
) -> None:
    _real_board(library)
    probe = _package(library) / "probe"
    probe.mkdir()
    (probe / "captured.json").write_text("not json at all", encoding="utf-8")

    assert pc.measure(library)["paginated_request_keys_no_capture_measured"] == 1


def test_a_package_that_will_not_load_is_a_finding_not_a_skip(
    library: Path, low_floor: None
) -> None:
    """Fail-closed. Skipping a package nobody can read would turn a broken
    library into a clean number, which is the shape of every defect this
    repository has filed against a vacuous gate."""
    _real_board(library)
    (_package(library) / "connector.yaml").write_text("site: [oh dear\n", encoding="utf-8")

    measured = pc.measure(library)

    assert measured["paginated_request_keys_no_capture_measured"] == 1
    assert measured["findings"][0]["mode"] == "unreadable"


def test_a_reserved_tld_package_is_excluded_and_says_so(library: Path, low_floor: None) -> None:
    """A `.test` board can never be fetched, so demanding a capture of it is
    incoherent — but a silent exclusion is how a scan quietly measures nothing,
    so the excluded names are in the record."""
    measured = pc.measure(library)

    assert measured["example_packages_excluded"] == [_REFERENCE.name]
    assert measured["packages_scanned"] == 0
    assert measured["findings"] == []


# ---------------------------------------------------------------------------
# the floor, and what is committed


def test_the_entry_point_exits_one_on_a_finding(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A gate that reports a finding and exits 0 is a gate `make evidence` reads
    as `ok`. The library default is resolved at call time so this can be driven
    against a broken library rather than only against the passing one."""
    monkeypatch.setattr(pc, "MINIMUM_REQUEST_KEYS", 1)
    monkeypatch.setattr(pc, "DEFAULT_CONNECTORS_DIR", library)
    _real_board(library)
    target = tmp_path / "T113.json"

    assert pc._main(["pagination_capture", str(target)]) == 1
    assert json.loads(target.read_text(encoding="utf-8"))["findings"]


# ---------------------------------------------------------------------------
# the URL side of the rule — #406's three fail-open routes
#
# Each is written the same way, in two halves. The first half is the **harm**:
# an object built with `model_copy(update=...)`, which never meets a validator,
# so it is exactly what a package looked like before the load check existed —
# and the scan above reports nothing about it, because the scan reads
# `pagination.param` against a capture and every one of these routes leaves that
# pair agreeing. The second half is the **fix**: the same shape, written as a
# connector file, is refused at load.
#
# The first half is what makes the second load-bearing. A test that only
# asserted the refusal would pass just as well over a rule nothing needed.


def _skipping_validation(url_pattern: str, **pagination: Any) -> Any:
    """The reference connector with a `list` no validator ever saw."""
    connector = load_connector(_REFERENCE)
    page = connector.list
    return connector.model_copy(
        update={
            "list": page.model_copy(
                update={
                    "url_pattern": url_pattern,
                    "pagination": page.pagination.model_copy(update=pagination),
                }
            )
        }
    )


def _refused(library: Path, url_pattern: str, pagination: dict[str, Any], **extra: Any) -> str:
    """The message `load_connector` refuses this `list` block with. `extra`
    forwards additional `list` keys straight to `_edit_connector` — a
    `body_json` (and `method`) for a namespace-axis case, most often."""
    _edit_connector(library, url_pattern=url_pattern, pagination=pagination, **extra)
    with pytest.raises(ConnectorError) as raised:
        load_connector(_package(library))
    return str(raised.value)


def test_a_param_naming_a_key_the_url_does_not_hold_is_refused(library: Path) -> None:
    """Route 1. `?p={page}` under `param: page`, over a capture of `?page=1`:
    the gate looks for `page` in the captured URL, finds it, and reports
    measured — while every request goes out carrying `p`, a key no capture ever
    recorded. The certified key and the sent key were never required to be the
    same key."""
    unvalidated = _skipping_validation(
        "https://realboard.io/jobs?p={page}", mode="query_param", param="page", max_pages=2
    )
    assert build_list_urls(unvalidated) == [
        "https://realboard.io/jobs?p=1",
        "https://realboard.io/jobs?p=2",
    ]
    # And the capture that would certify it carries the OTHER key, so the scan
    # is satisfied by a request nothing here ever issues.
    assert "page" in pc.query_keys("https://realboard.io/jobs?page=1")
    assert "page" not in pc.query_keys("https://realboard.io/jobs?p=1")

    message = _refused(
        library,
        "https://realboard.io/jobs?p={page}",
        {"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
    )
    assert "pagination.param is 'page'" in message
    assert "query key 'p'" in message


def test_mode_none_with_a_page_slot_still_in_the_pattern_is_refused(library: Path) -> None:
    """Route 2. `mode: none` short-circuits the scan — "the package sends no
    page key, so there is nothing to certify" — and `build_list_urls`
    substitutes on the text regardless, so `?page=1` goes out with no capture
    read for it at all."""
    unvalidated = _skipping_validation(
        "https://realboard.io/jobs?page={page}", mode="none", param=None, max_pages=1
    )
    assert build_list_urls(unvalidated) == ["https://realboard.io/jobs?page=1"]

    message = _refused(
        library, "https://realboard.io/jobs?page={page}", {"mode": "none", "max_pages": 1}
    )
    assert "pagination.mode is 'none'" in message
    assert "query key 'page'" in message


def test_query_param_with_nothing_to_vary_is_refused(library: Path) -> None:
    """Route 3. No `{page}` anywhere, so `build_list_urls` returns the
    **identical** URL `max_pages` times — the duplicate request, and then the
    duplicate offers, this task is named for. The capture certifies `page`
    because the literal `?page=1` is right there in the pattern."""
    unvalidated = _skipping_validation(
        "https://realboard.io/jobs?page=1", mode="query_param", param="page", max_pages=3
    )
    issued = build_list_urls(unvalidated)
    assert issued == ["https://realboard.io/jobs?page=1"] * 3
    assert len(set(issued)) == 1
    assert "page" in pc.query_keys(issued[0])

    message = _refused(
        library,
        "https://realboard.io/jobs?page=1",
        {"mode": "query_param", "param": "page", "start": 1, "max_pages": 3},
    )
    assert "nothing would vary from page to page" in message


def test_every_url_side_probe_agrees_with_the_rule() -> None:
    """The measurement itself: every probe parsed, every legal one built into
    the requests it would issue. Behavioural, so a validator deleted, weakened
    or replaced by a comment fails here — which is what
    a since-deleted gate's three defeated rounds are about."""
    defects, checked = pc.probe_url_side()

    assert defects == []
    assert checked >= pc.MINIMUM_URL_SIDE_PROBES


def test_the_committed_library_survives_the_url_side_rule() -> None:
    """The other direction, over the real thing rather than over probes: a
    check this aggressive would have taken the library down with it, and every
    committed package still loads."""
    assert len(load_connectors(_LIBRARY)) >= 15


# ---------------------------------------------------------------------------
# T154 — the fourth URL-side route: a query key sent twice
#
# Found by the second reader on #406 and deliberately kept out of that diff so
# the first three routes could be verified on their own. `?page=1&page={page}`
# holds the placeholder at exactly one position, under exactly the name
# `pagination.param` names, so routes 1-3's own checks — all read off *where
# the placeholder sits* — are satisfied. The request this issues nonetheless
# carries `page` twice, once fixed at a value no capture was ever taken at
# that position, and `pagination_capture.query_keys` reads a captured URL into
# a *set* of names — so a capture of either page's request still contains
# `page` and certifies a key a server is free to ignore.


def test_a_query_key_sent_twice_is_refused_at_load(library: Path) -> None:
    """Route 4. The harm half first: a `list` no validator ever saw issues the
    identical fixed `page=1` on every request, alongside the one that varies —
    and the capture that would certify it needs only the *name*, so a capture
    of page 1's own request (`?page=1&page=1`) already contains `page` before
    a second page is ever fetched."""
    unvalidated = _skipping_validation(
        "https://realboard.io/jobs?page=1&page={page}",
        mode="query_param",
        param="page",
        max_pages=2,
    )
    assert build_list_urls(unvalidated) == [
        "https://realboard.io/jobs?page=1&page=1",
        "https://realboard.io/jobs?page=1&page=2",
    ]
    assert "page" in pc.query_keys("https://realboard.io/jobs?page=1&page=1")

    message = _refused(
        library,
        "https://realboard.io/jobs?page=1&page={page}",
        {"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
    )
    assert "names 'page' 2 times" in message


_JSON_ITEMS: dict[str, Any] = {
    "item": None,
    "fields": None,
    "from_json": {"items": "Jobs", "fields": {"title": "Title", "detail_url": "Url"}},
}
_QP = {"mode": "query_param", "param": "page", "start": 1, "max_pages": 2}
_BF = {"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2}
_POST = f"https://{_REAL_SITE}/Search/ExecuteSearch"


@pytest.mark.parametrize(
    ("url", "pagination", "extra", "expected"),
    [
        # Route 4: a name counted by occurrence, whatever it spells.
        ("https://realboard.io/jobs?p=1&p={page}", {**_QP, "param": "p"}, {}, "names 'p' 2 times"),
        # Percent-encoded, case-only, `;`-separated and final-sigma spellings of one key.
        ("https://realboard.io/jobs?%70age=1&page={page}", _QP, {}, "names 'page' 2 times"),
        ("https://realboard.io/jobs?Page=1&page={page}", _QP, {}, "names 'page' 2 times"),
        ("https://realboard.io/jobs?page=1;page={page}", _QP, {}, "names 'page' 2 times"),
        (
            "https://realboard.io/jobs?ς=1&\u03c3={page}",
            {**_QP, "param": "\u03c3"},
            {},
            "names '\u03c3' 2 times",
        ),
        (
            "https://realboard.io/jobs?%CF%82=1&%CF%83={page}",
            {**_QP, "param": "\u03c3"},
            {},
            "names '\u03c3' 2 times",
        ),
        (
            "https://realboard.io/jobs?straße=1&strasse={page}",
            {**_QP, "param": "strasse"},
            {},
            "names 'strasse' 2 times",
        ),
        # A param name that itself contains the permissive separator.
        (
            "https://realboard.io/jobs?a;b=1&a;b={page}",
            {**_QP, "param": "a;b"},
            {},
            "names 'a;b' 2 times",
        ),
        (
            "https://realboard.io/jobs?a;b=1;a;b={page}",
            {**_QP, "param": "a;b"},
            {},
            "names 'a;b'",
        ),
        # `mode: none` that still names a param refuses a duplicate of it.
        (
            "https://realboard.io/jobs?page=1&page=2",
            {"mode": "none", "param": "page", "max_pages": 1},
            {},
            "mode is 'none'",
        ),
        # A page slot hidden in another key's value, under strict `&` splitting.
        (
            "https://realboard.io/jobs?filter=a;page={page}",
            _QP,
            {},
            "not in a query-string value under that key",
        ),
        # Mode body_field: the query half and the body half both count.
        (
            f"{_POST}?Page=1",
            _BF,
            {"method": "POST", "body_json": {"Page": PAGE_PLACEHOLDER}},
            "names 'Page' 1 time",
        ),
        (
            _POST,
            _BF,
            {"method": "POST", "body_json": {"Page": PAGE_PLACEHOLDER, "page": "1"}, **_JSON_ITEMS},
            "body_json's top-level keys name 'Page' 2 times",
        ),
        (
            _POST,
            {**_BF, "param": "\u03c3"},
            {"method": "POST", "body_json": {"ς": "1", "\u03c3": PAGE_PLACEHOLDER}, **_JSON_ITEMS},
            "name '\u03c3' 2 times",
        ),
        # A fixed body field repeating the certified key, under any mode and case.
        (
            "https://realboard.io/jobs?page={page}",
            _QP,
            {"method": "POST", "body_json": {"page": "1"}, **_JSON_ITEMS},
            "list.body_json also declares 'page'",
        ),
        (
            "https://realboard.io/jobs?page={page}",
            _QP,
            {"method": "POST", "body_json": {"Page": "1"}, **_JSON_ITEMS},
            "list.body_json also declares 'page'",
        ),
        (
            "https://realboard.io/jobs?o={page}",
            {**_QP, "mode": "path_segment"},
            {"method": "POST", "body_json": {"page": "1"}, **_JSON_ITEMS},
            "list.body_json also declares 'page'",
        ),
    ],
)
def test_a_page_key_sent_twice_is_refused_at_load(
    library: Path, url: str, pagination: dict[str, Any], extra: dict[str, Any], expected: str
) -> None:
    assert expected in _refused(library, url, pagination, **extra)


@pytest.mark.parametrize(
    ("url", "pagination", "extra", "expected"),
    [
        # A repeated key that is not the page key is none of this rule's business.
        (
            "https://realboard.io/jobs?tag=a&tag=b&page={page}",
            _QP,
            {},
            [
                "https://realboard.io/jobs?tag=a&tag=b&page=1",
                "https://realboard.io/jobs?tag=a&tag=b&page=2",
            ],
        ),
        # `mode: none` with no param never runs the check.
        (
            "https://realboard.io/jobs?tag=a&tag=a",
            {"mode": "none", "max_pages": 1},
            {},
            ["https://realboard.io/jobs?tag=a&tag=a"],
        ),
        # A value that spells `key=value` inside itself is data, not a second pair.
        (
            "https://realboard.io/jobs?q=page%3D1&page={page}",
            _QP,
            {},
            [
                "https://realboard.io/jobs?q=page%3D1&page=1",
                "https://realboard.io/jobs?q=page%3D1&page=2",
            ],
        ),
        # Case-only difference between param and the URL key is the same key, so it loads.
        (
            "https://realboard.io/jobs?Page={page}",
            _QP,
            {},
            ["https://realboard.io/jobs?Page=1", "https://realboard.io/jobs?Page=2"],
        ),
        (
            "https://realboard.io/jobs?a;b={page}",
            {**_QP, "param": "a;b"},
            {},
            ["https://realboard.io/jobs?a;b=1", "https://realboard.io/jobs?a;b=2"],
        ),
        # Unrelated query / body keys under each mode.
        (
            f"{_POST}?Keyword=python",
            _BF,
            {
                "method": "POST",
                "body_json": {"Keyword": "python", "Page": PAGE_PLACEHOLDER},
                **_JSON_ITEMS,
            },
            [f"{_POST}?Keyword=python"] * 2,
        ),
        (
            "https://realboard.io/jobs?page={page}",
            _QP,
            {"method": "POST", "body_json": {"other": "1"}, **_JSON_ITEMS},
            ["https://realboard.io/jobs?page=1", "https://realboard.io/jobs?page=2"],
        ),
        (
            "https://realboard.io/jobs/{page}",
            {**_QP, "mode": "path_segment"},
            {"method": "POST", "body_json": {"other": "1"}, **_JSON_ITEMS},
            ["https://realboard.io/jobs/1", "https://realboard.io/jobs/2"],
        ),
    ],
)
def test_a_legitimate_page_key_shape_still_loads(
    library: Path, url: str, pagination: dict[str, Any], extra: dict[str, Any], expected: list[str]
) -> None:
    _edit_connector(library, url_pattern=url, pagination=pagination, **extra)
    assert build_list_urls(load_connector(_package(library))) == expected


def test_every_duplicate_key_probe_agrees_with_the_rule() -> None:
    """The measurement itself, same shape as `test_every_url_side_probe_agrees_with_the_rule`:
    behavioural, so a validator deleted, weakened or replaced by a comment
    fails here."""
    defects, checked = pc.probe_duplicate_page_keys()

    assert defects == []
    assert checked >= pc.MINIMUM_DUPLICATE_KEY_PROBES


def test_the_committed_library_has_no_duplicated_query_key() -> None:
    """The real thing rather than the probes: the committed library cannot
    carry route 4's shape once the load-time rule refuses it, so the scan over
    `connectors/` reports a clean zero — and it is a real scan, not a rule
    nobody exercises, per `test_the_committed_library_survives_the_url_side_rule`."""
    measured = pc.measure_duplicate_page_keys(_LIBRARY)
    assert measured["gate_status"] == "measured"
    assert measured["duplicated_page_keys_certified"] == 0
    assert measured["query_key_occurrences_scanned"] >= pc.MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED


def test_the_denominator_counts_occurrences_not_a_set_of_names() -> None:
    """F6, pinned directly: a `url_pattern` naming a key twice must contribute
    **two** to a scan built for this gate, not the one a `frozenset` of names
    (`pagination_capture.query_keys`, T113's own denominator) would give —
    that difference is exactly the duplication this gate exists to measure,
    so building its denominator on the set-shaped function would erase the
    numerator's own phenomenon from it. No package on disk can carry this
    shape (the load-time rule refuses it), which is why the comparison is
    made directly against the two functions rather than through a fixture
    library."""
    url = "https://boards.test/jobs?page=1&page=2"
    assert len(query_pair_names(url)) == 2  # what the denominator must use
    assert len(pc.query_keys(url)) == 1  # what it must not use


def test_the_denominator_is_scoped_to_the_packages_route_4_reaches() -> None:
    """F6's other half: a `mode: none` package sends no page key at all, so
    pooling it into the denominator would count a population route 4 never
    touches — `foorilla_en`, `getmanfred_es`, `himalayas_en` and `landingjobs_en`
    all carry a query key under `mode: none` and must **not** inflate the
    count `test_the_committed_library_has_no_duplicated_query_key` reads."""
    measured = pc.measure_duplicate_page_keys(_LIBRARY)
    # Six packages ship `pagination.mode != "none"` with a query key today
    # (see `MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED`'s own comment); the four
    # `mode: none` packages named above must not appear in that count.
    excluded_occurrences = 0
    for name in ("foorilla_en", "getmanfred_es", "himalayas_en", "landingjobs_en"):
        connector = load_connector(_LIBRARY / name)
        assert connector.list.pagination.mode == "none"
        excluded_occurrences += len(query_pair_names(connector.list.url_pattern))
    assert excluded_occurrences > 0  # the exclusion is real, not vacuous
    assert measured["query_key_occurrences_scanned"] < 14  # T113's old, unscoped total


# ---------------------------------------------------------------------------
# where a capture came from — #406's third finding


def test_a_capture_that_declares_no_provenance_reads_as_unrecorded(library: Path) -> None:
    """The default is an absence, not a guess. Every capture committed before
    the field existed says nothing about how it was made, and reading that as
    `live` would retro-label twenty files with a claim nobody checked."""
    _write_capture(library, captured_at="2026-09-08", url="https://realboard.io/jobs", status=200)

    assert pc.read_capture(_package(library)).provenance == pc.UNRECORDED


def test_a_declared_provenance_is_read_back(library: Path) -> None:
    """Both values, so the distinction the field exists for is legible in the
    file rather than in a pull-request comment."""
    for declared in (pc.LIVE, pc.TRANSCRIBED):
        _write_capture(
            library,
            captured_at="2026-09-08",
            url="https://realboard.io/jobs",
            status=200,
            provenance=declared,
        )
        assert pc.read_capture(_package(library)).provenance == declared


def test_an_unrecognised_provenance_is_an_absence_not_a_third_category(library: Path) -> None:
    """Fail-closed on the claim. A typo that silently became its own category
    would be a provenance nobody agreed on, which is worse than saying nothing
    — and `PROVENANCE` is the closed vocabulary that decides."""
    for declared in ("Live", "recorded live", "", 1, None, ["live"]):
        _write_capture(
            library,
            captured_at="2026-09-08",
            url="https://realboard.io/jobs",
            status=200,
            provenance=declared,
        )
        assert pc.read_capture(_package(library)).provenance == pc.UNRECORDED
    assert set(pc.PROVENANCE) == {pc.LIVE, pc.TRANSCRIBED}
    assert pc.UNRECORDED not in pc.PROVENANCE


def test_a_finding_names_the_provenance_of_the_capture_that_failed_to_certify(
    library: Path, low_floor: None
) -> None:
    """A finding is read by somebody deciding what to do next, and "the capture
    that does not carry this key was itself transcribed" is part of that
    decision. Reported in the reason rather than left to a second lookup."""
    _real_board(library)
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.TRANSCRIBED,
    )

    (finding,) = pc.measure(library)["findings"]

    assert pc.TRANSCRIBED in finding["reason"]


# ---------------------------------------------------------------------------
# T153 — the provenance is enforced, or it is a label wearing evidence's clothes
#
# T113 shipped `provenance` advisory: nineteen of twenty captures declared
# nothing, nothing failed on any value, and a fabricated capture claiming
# `live` passed. `integral.capture_provenance` is the check, and these are its
# fixtures. They live here rather than in a file of their own because the field
# and its enforcement are one subject, and the T113 tests above are what a
# reader needs beside them.
#
# Two rules run through all of them: a claim is substantiated by the ARTEFACT
# or it is counted, and `unrecorded` is a truthful statement rather than a hole
# — the nineteen must be able to pass while saying exactly what they know.


def _capture_probe(library: Path, body: bytes = b"<html>a list of jobs</html>") -> Path:
    """Response bytes committed beside the capture, as a live fetch leaves them."""
    probe = _package(library) / "probe"
    probe.mkdir(exist_ok=True)
    path = probe / "list.html"
    path.write_bytes(body)
    return path


def _live_response(path: Path) -> dict[str, Any]:
    """The `response` block that honestly describes `path`."""
    body = path.read_bytes()
    return {
        "file": path.name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
    }


@pytest.fixture
def provenance_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Measure a one-package library at all — the floor is asserted separately."""
    monkeypatch.setattr(cp, "MINIMUM_CAPTURES_SCANNED", 1)


def _provenance_findings(library: Path, **kwargs: Any) -> list[dict[str, str]]:
    measured = cp.measure(library, **kwargs)
    assert measured["gate_status"] == "measured", measured
    rows: list[dict[str, str]] = measured["findings"]
    assert measured["captures_with_an_unenforced_provenance"] == len(rows)
    return rows


def test_an_absent_provenance_is_a_finding_not_a_default(
    library: Path, provenance_floor: None
) -> None:
    """The hole T113 left. `read_provenance` maps a missing field to
    `unrecorded` and never writes it back, so "nobody established this" and
    "nobody wrote anything" are the same bytes — and the second read as a pass.
    After this task the absence has to be stated."""
    _real_board(library)
    _write_capture(library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs", status=200)

    (finding,) = _provenance_findings(library)

    assert finding["claim"] == "absent"
    assert "provenance" in finding["reason"]
    assert finding["direction"] == "fail-open"


def test_an_unrecorded_capture_is_the_truthful_label_and_still_passes(
    library: Path, provenance_floor: None
) -> None:
    """The control this task is bounded by. `unrecorded` claims nothing, so
    there is nothing to substantiate — and the nineteen committed captures for
    which it is the honest word must be able to say it and pass. A gate
    satisfiable only by stamping `live` on them would be the invention this
    whole module refuses."""
    _real_board(library)
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.UNRECORDED,
    )

    assert _provenance_findings(library) == []


def test_a_provenance_outside_the_vocabulary_is_a_finding(
    library: Path, provenance_floor: None
) -> None:
    """`pagination_capture.read_provenance` folds an unknown spelling into
    `unrecorded`, which is right for *reading* a claim and wrong for enforcing
    one: a file saying `Live` has stated something, and silently reading it as
    an absence is how a typo becomes a pass."""
    _real_board(library)
    for declared in ("Live", "recorded live", "", 1, None, ["live"]):
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=f"https://{_REAL_SITE}/jobs",
            status=200,
            provenance=declared,
        )
        (finding,) = _provenance_findings(library)
        assert "vocabulary" in finding["reason"], declared


def test_a_capture_claiming_live_provenance_carries_what_a_live_capture_leaves(
    library: Path, provenance_floor: None
) -> None:
    """The fabrication this task is named for, and the seven ways it is caught.

    A live fetch leaves the response behind; a hand-written record has nothing
    to leave. So `live` is held to the bytes in `probe/` — the digest most of
    all, because it binds the claim to the exact response committed rather than
    to a form filled in.
    """
    _real_board(library)
    response = _live_response(_capture_probe(library))
    honest: dict[str, Any] = {
        "captured_at": "2026-09-08",
        "url": f"https://{_REAL_SITE}/jobs",
        "status": 200,
        "provenance": pc.LIVE,
        "response": response,
    }
    today = date(2026, 9, 8)

    # The control first: a live claim that carries all of it is not a finding.
    _write_capture(library, **honest)
    assert _provenance_findings(library, today=today) == []

    broken: list[tuple[dict[str, Any], str]] = [
        # A bare claim — what a fabricated capture costs to write today.
        ({"response": None}, "no `response` block"),
        # The response named but not committed.
        ({"response": {**response, "file": "absent.html"}}, "not committed"),
        # Committed, and not the bytes the record describes.
        ({"response": {**response, "bytes": response["bytes"] + 1}}, "bytes on disk"),
        ({"response": {**response, "sha256": "0" * 64}}, "does not match"),
        ({"response": {**response, "sha256": "not-a-digest"}}, "not a sha256"),
        # A record of a fetch that has not happened.
        ({"captured_at": "2026-09-09"}, "in the future"),
        ({"captured_at": "the second of September"}, "not a YYYY-MM-DD"),
        # A status no response carried.
        ({"status": "200"}, "not an HTTP status"),
        ({"status": 999}, "not an HTTP status"),
    ]
    for change, expected in broken:
        record = {**honest, **change}
        if change.get("response", ...) is None:
            record.pop("response")
        _write_capture(library, **record)
        (finding,) = _provenance_findings(library, today=today)
        assert finding["claim"] == pc.LIVE, change
        assert expected in finding["reason"], (change, finding["reason"])


def test_a_live_response_cannot_name_a_file_outside_its_own_package(
    library: Path, provenance_floor: None
) -> None:
    """`response.file` addresses `probe/`, and only `probe/`. A claim that
    reaches up the tree could certify itself against any committed file in the
    repository — the fixture beside it, or another package's probe."""
    _real_board(library)
    honest = _live_response(_capture_probe(library))
    escapes = ("../fixture/list.html", "/etc/hostname", "..", "sub/list.html", "", "list.html\n")
    for escape in escapes:
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=f"https://{_REAL_SITE}/jobs",
            status=200,
            provenance=pc.LIVE,
            response={**honest, "file": escape},
        )
        (finding,) = _provenance_findings(library, today=date(2026, 9, 8))
        assert "plain filename" in finding["reason"], escape


def test_a_transcribed_capture_names_the_committed_request_it_came_from(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """`transcribed` means "somebody else's committed command produced this",
    so the whole content of the claim is *which* command — and it has to be
    here. A transcribed record naming nothing is a live claim in a quieter
    voice."""
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    (repo / "connectors").mkdir(parents=True)
    ledger = repo / "connectors" / "ruled-out.yaml"
    ledger.write_text(
        "  - site: realboard.io\n"
        f'    retest: "curl -s -X POST -d \'{{\\"Keyword\\":\\"python\\"}}\' \'{url}\'"\n',
        encoding="utf-8",
    )

    base: dict[str, Any] = {
        "captured_at": "2026-09-08",
        "url": url,
        "body": {"Keyword": "python"},
        "status": 200,
        "provenance": pc.TRANSCRIBED,
    }

    # The control: the ledger carries this URL and this body, so the claim
    # resolves. Note the committed command spells the body backslash-escaped
    # inside a YAML scalar and the capture spells it as JSON — the same request,
    # which is why the source text is read with backslashes stripped.
    _write_capture(library, **base, transcribed_from="connectors/ruled-out.yaml")
    assert _provenance_findings(library, repo_root=repo) == []

    broken: list[tuple[dict[str, Any], str]] = [
        ({}, "no `transcribed_from`"),
        ({"transcribed_from": "connectors/absent.yaml"}, "does not resolve"),
        ({"transcribed_from": "/etc/hostname"}, "not a repo-relative path"),
        ({"transcribed_from": "../../etc/hostname"}, "not a repo-relative path"),
        # The named file exists and is a command for a different request.
        (
            {"transcribed_from": "connectors/ruled-out.yaml", "url": f"https://{_REAL_SITE}/other"},
            "does not carry the captured URL",
        ),
        (
            {"transcribed_from": "connectors/ruled-out.yaml", "body": {"Keyword": "rust"}},
            "does not carry the captured body",
        ),
        (
            {
                "transcribed_from": "connectors/ruled-out.yaml",
                "body": {"Keyword": "python", "Page": 2},
            },
            "does not carry the captured body",
        ),
    ]
    for change, expected in broken:
        _write_capture(library, **{**base, **change})
        (finding,) = _provenance_findings(library, repo_root=repo)
        assert finding["claim"] == pc.TRANSCRIBED, change
        assert expected in finding["reason"], (change, finding["reason"])


def test_a_file_that_only_mentions_the_request_is_not_a_committed_command(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """T113's rule, applied to the field T113 created: **"a dated sentence in a
    comment is not a capture."**

    T113 refused to write `pythonorg_en`'s capture from a dated comment naming
    the request, and `status/plan.md`'s T152 row records that the refusal was
    right. A module enforcing T113's own marker cannot then accept the artefact
    T113 refused — so containment is not the join. Each source below contains
    the URL and **names no client command of its own**, which is the class this
    refuses; a refusal that quotes a `curl` is a different input and is pinned
    as a disclosed limit by
    `test_a_refusal_that_quotes_a_command_is_inside_the_disclosed_ceiling`. An
    earlier draft of this docstring called the third case "a source certifying
    the absence of the very request it is cited for" and left the reader to
    assume every spelling of that was caught. Only the ones without a client
    word are.
    """
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "notes.md"

    def _cited(text: str) -> dict[str, str]:
        source.write_text(text, encoding="utf-8")
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=url,
            status=200,
            provenance=pc.TRANSCRIBED,
            transcribed_from="notes.md",
        )
        (finding,) = _provenance_findings(library, repo_root=repo)
        assert finding["claim"] == pc.TRANSCRIBED
        return finding

    mentions = [
        # A file that denies the fetch ever happened, in the same breath.
        f"We have NEVER fetched this board.\n{url}\n",
        # T113's own case, verbatim in shape: a dated sentence in a comment.
        f"# 2026-09-02: someone said they saw {url} return 200. Not verified.\n",
        # A record of a REFUSAL that quotes no command — the spelling this
        # class covers, and the whole of what it covers.
        f"The fetch of {url} was REFUSED by robots.txt and never issued.\n",
        # The URL alone, with nothing around it at all.
        f"{url}\n",
    ]
    for text in mentions:
        assert "commits no command for it" in _cited(text)["reason"], text

    # And the same rule one level down: the pieces of a command are not a
    # command. Two body fields mentioned in unrelated places never described a
    # request anybody sent.
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        body={"Keyword": "python", "ResultsPerPage": 25},
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from="notes.md",
    )
    source.write_text(
        f"curl -s {url}\n"
        'Somewhere else entirely, we once discussed "Keyword":"python".\n'
        'And in a third place, "ResultsPerPage":25.\n',
        encoding="utf-8",
    )
    (finding,) = _provenance_findings(library, repo_root=repo)
    assert "commits no command for it" in finding["reason"], finding["reason"]


def test_a_command_wrapped_over_several_lines_is_still_one_command(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The other side of the one-line rule, so that "on one line" is a statement
    about commands rather than about typography. A `curl` continued over four
    physical lines with trailing backslashes is one command, and refusing it
    would be fail-closed for nothing."""
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "retest.sh").write_text(
        "curl -s -X POST \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        '  -d \'{"Keyword":"python","ResultsPerPage":25}\' \\\n'
        f"  '{url}'\n",
        encoding="utf-8",
    )
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        body={"Keyword": "python", "ResultsPerPage": 25},
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from="retest.sh",
    )

    assert _provenance_findings(library, repo_root=repo) == []


def test_a_transcribed_body_resolves_whatever_order_the_command_spells_it_in(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The claim is "this request is committed", not "these bytes are committed
    in this order". Matching one serialised object would make a ledger line
    spelling the same two fields the other way round read as a different
    request — fail-closed, and for nothing."""
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "ledger.yaml").write_text(
        f'retest: curl -d \'{{"ResultsPerPage":25,"Keyword":"python"}}\' {url}\n',
        encoding="utf-8",
    )
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        body={"Keyword": "python", "ResultsPerPage": 25},
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from="ledger.yaml",
    )

    assert _provenance_findings(library, repo_root=repo) == []


def test_a_symlinked_probe_directory_is_not_a_capture_this_package_holds(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The containment of `test_a_live_response_file_that_is_a_symlink…`, one
    directory up — and the case that showed the two checks were two rules.

    `check_live` used to resolve **both** sides of its own comparison, which
    normalises a symlinked `probe/` away on the left and the right alike: the
    leaf was checked and the directory holding it was not. So a package whose
    `probe/` linked at a donor passed a `live` claim over bytes it never held,
    with `bytes` and `sha256` honest over the donor's file because they were
    computed there. `check_transcribed` compared against the **unresolved**
    join and got this right, which is the whole defect — one rule, two readers,
    only one of them correct. `_committed_at` is now that one rule, and it is
    asked about `probe/captured.json` before anything else, because a package
    whose capture is borrowed has no capture of its own to enforce.
    """
    _real_board(library)
    package = _package(library)
    donor = tmp_path / "donor"
    donor.mkdir()
    body = b"<html>a donor package's list of jobs</html>"
    (donor / "list.html").write_bytes(body)
    record: dict[str, Any] = {
        "captured_at": "2026-09-08",
        "url": f"https://{_REAL_SITE}/jobs",
        "status": 200,
        "provenance": pc.LIVE,
        "response": {
            "file": "list.html",
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        },
    }
    (donor / "captured.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    shutil.rmtree(package / "probe", ignore_errors=True)
    (package / "probe").symlink_to(donor, target_is_directory=True)

    (finding,) = _provenance_findings(library, today=date(2026, 9, 8))
    assert finding["claim"] == "absent"
    assert "symlinked probe/" in finding["reason"], finding["reason"]

    # And `check_live` refuses it on its own terms, so its guarantee does not
    # rest on `read_record` having got there first. Handed the record directly
    # — which is what the unfixed check was handed by the unfixed reader — the
    # response is still not one this package commits.
    reasons = cp.check_live(package, record, date(2026, 9, 8))
    assert any("own probe/" in reason for reason in reasons), reasons


def test_the_request_under_test_may_not_supply_the_command_that_certifies_it(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The self-citation of `test_a_capture_cannot_cite_itself…`, one level in.

    The command is supposed to be evidence **independent** of the request: the
    file says somebody issued this, and the URL and body say which request that
    was. Searching the whole line for a client word collapses the two, so the
    needles certify themselves — a file whose entire content is the URL passed,
    if the URL's path happened to read `/curl/`, and so did a body of
    `{"q": "curl"}`, which is an ordinary search for this tool to have run
    against a job board. The committed case `C16` — "the URL alone, with nothing
    around it at all" — was passing on the luck of `arbeitnow`'s URL not
    containing a client name, which is not a fixture.
    """
    _real_board(library)
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "notes.md"

    def _cited(text: str, **capture: Any) -> list[dict[str, str]]:
        source.write_text(text, encoding="utf-8")
        _write_capture(
            library,
            captured_at="2026-09-08",
            status=200,
            provenance=pc.TRANSCRIBED,
            transcribed_from="notes.md",
            **capture,
        )
        return _provenance_findings(library, repo_root=repo)

    # The client name is inside the URL's own path.
    path_url = f"https://{_REAL_SITE}/curl/jobs"
    (finding,) = _cited(f"{path_url}\n", url=path_url)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # …and inside its query string.
    query_url = f"https://{_REAL_SITE}/jobs?utm_source=curl"
    (finding,) = _cited(f"{query_url}\n", url=query_url)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # …and inside a body value, which needs no unusual URL at all.
    url = f"https://{_REAL_SITE}/search"
    for term in ("curl", "wget developer", "xh"):
        needle = json.dumps({"q": term}, separators=(",", ":"))
        (finding,) = _cited(f"{url} {needle}\n", url=url, body={"q": term})
        assert "commits no command for it" in finding["reason"], term

    # The control, which is what stops the fix from being "refuse everything":
    # the same shape with a search term that is not a client name, and a real
    # command outside both needles.
    assert _cited(f'curl -d \'{{"q":"python"}}\' {url}\n', url=url, body={"q": "python"}) == []


def test_the_check_may_not_manufacture_the_boundaries_it_looks_for(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """`test_the_request_under_test_may_not_supply_the_command_that_certifies_
    it`, one level in — and the level the fix for it created.

    That fix put the client word out of the needles' reach by striking them out
    and replacing each with a space. A space is not a `[\\w-]` character, so
    every strike **inserts two word boundaries**, and `_REQUEST_COMMAND` is a
    rule about boundaries. `<url>curl<url>` carries no client word by this
    module's own predicate — the `curl` sits inside the longer token
    `apicurlhttps`, which `test_a_client_name_inside_a_longer_word_is_not_a_
    client` establishes is not a client — and the check's own edit turned it
    into ` curl ` and certified it. The needles did not supply the token there;
    they supplied the **delimiters** that made a non-token into one, which is
    the same independence property failing in a place it was not being watched.

    Deletion is not the other answer, and the third case is why: it *splices*,
    welding `cu<url>rl` into a `curl` that is in no committed file. Both
    spellings rewrite the input and then measure the rewrite. The line is now
    read as committed, and independence is a question about position.
    """
    _real_board(library)
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "notes.md"
    url = f"https://{_REAL_SITE}/api/job-board-api"

    def _cited(text: str, **capture: Any) -> list[dict[str, str]]:
        source.write_text(text, encoding="utf-8")
        _write_capture(
            library,
            captured_at="2026-09-08",
            status=200,
            provenance=pc.TRANSCRIBED,
            transcribed_from="notes.md",
            **capture,
        )
        return _provenance_findings(library, repo_root=repo)

    # The boundaries are manufactured on both sides of the client word by the
    # two needle occurrences that surround it.
    (finding,) = _cited(f"{url}curl{url}\n", url=url)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # One occurrence is enough when a body value supplies the other side, so
    # the case does not depend on a source naming the URL twice.
    body = {"page": 1}
    needle = json.dumps(body, separators=(",", ":"))[1:-1]
    (finding,) = _cited(f"{needle}curl{url}\n", url=url, body=body)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # The other direction, which is why a space was chosen over a deletion in
    # the first place: removing the needle welds the halves into a client word.
    (finding,) = _cited(f"cu{url}rl\n", url=url)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # A client word that a needle only **partially** covers is covered: the
    # ambiguous case resolves fail-closed, since one character outside a URL is
    # not a command.
    short = f"https://{_REAL_SITE}/cur"
    (finding,) = _cited(f"{short}l -s\n", url=short)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # And the same, welded by the one edit that happens *before* this check —
    # `_command_lines` drops backslashes, so `…/cur` + `\\l` renders as `…/curl`.
    # The property this rests on is not that the line is untouched (it is not)
    # but that the span map and the search read the same string, so a client
    # word made out of a needle's own characters still lands on that needle's
    # span. This is the assertion that pins it.
    (finding,) = _cited(f"{short}\\l -s\n", url=short)
    assert "commits no command for it" in finding["reason"], finding["reason"]

    # The controls. A real command whose URL is repeated, and a real command
    # whose URL legitimately contains a client name, both still resolve — the
    # fix must not buy its refusals by refusing everything.
    assert _cited(f"curl -s '{url}' # against {url}\n", url=url) == []
    curl_url = f"https://{_REAL_SITE}/curl/jobs"
    assert _cited(f"curl -s '{curl_url}'\n", url=curl_url) == []


def test_the_pieces_of_a_request_spread_over_several_commands_are_not_one_command(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The one-line rule, isolated — "all of the needles on one line" rather
    than "each needle on some line".

    Its neighbour `test_a_file_that_only_mentions_the_request…` scatters two
    body fields over lines carrying no client word, so it re-tests the command
    requirement and leaves this one unpinned: weakening `any(all(…))` to
    `all(any(…))` survived the whole suite. Prefixing each stray line with a
    real `curl` separates the two rules, and this is the source that does it —
    three commands for three different requests, none of them this one.
    """
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    other = "https://elsewhere.example/other"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "notes.md").write_text(
        f"curl -s '{url}'\n"
        f"curl -d '{{\"Keyword\":\"python\"}}' '{other}'\n"
        f"curl -d '{{\"ResultsPerPage\":25}}' '{other}'\n",
        encoding="utf-8",
    )
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        body={"Keyword": "python", "ResultsPerPage": 25},
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from="notes.md",
    )

    (finding,) = _provenance_findings(library, repo_root=repo)
    assert "commits no command for it" in finding["reason"], finding["reason"]


def test_a_client_name_inside_a_longer_word_is_not_a_client(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """`_REQUEST_COMMAND`'s word boundaries, which nothing pinned.

    Deleting them survives the suite, and it is a large widening in the
    fail-open direction: bare `xh` matches inside `exhausted` and `xhr`, and
    bare `curl` inside `curly`. Prose about a request is the exact input this
    module refuses, and prose is where those words live.
    """
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "notes.md"

    def _cited(text: str) -> list[dict[str, str]]:
        source.write_text(text, encoding="utf-8")
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=url,
            status=200,
            provenance=pc.TRANSCRIBED,
            transcribed_from="notes.md",
        )
        return _provenance_findings(library, repo_root=repo)

    embedded = [
        f"we discussed the curly-brace syntax for {url}\n",
        f"the xhr behind {url} never fired\n",
        f"our retry budget for {url} was exhausted\n",
    ]
    for text in embedded:
        (finding,) = _cited(text)
        assert "commits no command for it" in finding["reason"], text


def _usajobs_as_t113_shipped(package: Path) -> None:
    """Rewrite a copy of `usajobs_en`'s capture to the transcribed record T113
    committed: the page-one body, citing the ledger's `retest` line."""
    path = package / "probe" / "captured.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.pop("response", None)
    record.update(
        captured_at="2026-09-02",
        body={"Keyword": "python", "ResultsPerPage": 25},
        provenance=pc.TRANSCRIBED,
        transcribed_from="connectors/ruled-out.yaml",
    )
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")


def test_a_transcribed_claim_rests_on_the_committed_command_and_not_on_a_mention(
    tmp_path: Path,
) -> None:
    """The join, exercised where it is actually load-bearing.

    Here the ledger is copied with the one `retest` command turned into prose
    about the same request: every string the check reads is still present, and
    the claim must stop resolving.
    """
    repo = tmp_path / "repo"
    (repo / "connectors").mkdir(parents=True)
    ledger = _LIBRARY / "ruled-out.yaml"
    prose = ledger.read_text(encoding="utf-8").replace(
        'retest: "curl -s -X POST', 'retest: "we once ran a POST'
    )
    (repo / "connectors" / "ruled-out.yaml").write_text(prose, encoding="utf-8")
    package = tmp_path / "usajobs_en"
    shutil.copytree(_LIBRARY / "usajobs_en", package)
    _usajobs_as_t113_shipped(package)
    record = cp.read_record(package)
    assert record is not None

    (reason,) = cp.check_transcribed(package, record, repo)

    assert "commits no command for it" in reason


def test_an_empty_library_is_unmeasured_rather_than_clean(tmp_path: Path) -> None:
    empty = tmp_path / "connectors"
    empty.mkdir()

    assert cp.measure(empty)["gate_status"] == "unmeasured"
    assert cp.measure(tmp_path / "absent")["gate_status"] == "unmeasured"


def test_the_entry_point_exits_one_on_an_unenforced_provenance(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cp, "MINIMUM_CAPTURES_SCANNED", 1)
    monkeypatch.setattr(cp, "DEFAULT_CONNECTORS_DIR", library)
    _real_board(library)
    _write_capture(library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs", status=200)
    target = tmp_path / "T153.json"

    assert cp._main(["capture_provenance", str(target)]) == 1
    assert json.loads(target.read_text(encoding="utf-8"))["findings"]

    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.UNRECORDED,
    )
    assert cp._main(["capture_provenance", str(target)]) == 0


# ---------------------------------------------------------------------------
# T152 — a package dropped for want of a capture is named, not silent


def _library_copy(tmp_path: Path) -> Path:
    library = tmp_path / "connectors"
    shutil.copytree(_LIBRARY, library)
    return library


def _edit_pagination(library: Path, package: str, **changes: Any) -> None:
    path = library / package / "connector.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["list"]["pagination"].update(changes)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def _drop_pagination(library: Path, package: str) -> None:
    """Revert `package` to the state T113 left it in: `mode: none`, no page key,
    and the capture of the first page that nobody could record beyond."""
    path = library / package / "connector.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["list"]["pagination"] = {"mode": "none", "max_pages": 1}
    if package == "pythonorg_en":
        document["list"]["url_pattern"] = "https://www.python.org/jobs/"
        capture = {"url": "https://www.python.org/jobs/", "provenance": "unrecorded"}
    else:
        document["list"]["body_json"].pop("Page")
        capture = {
            "url": document["list"]["url_pattern"],
            "body": document["list"]["body_json"],
            "provenance": "unrecorded",
        }
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    (library / package / "probe" / "captured.json").write_text(
        json.dumps({"captured_at": "2026-09-02", "status": 200, **capture}), encoding="utf-8"
    )


def test_the_committed_library_drops_no_further_page() -> None:
    measured = pc.measure_unrecordable_drops()

    assert measured["gate_status"] == "measured"
    assert measured["packages_dropped_for_an_unrecordable_capture"] == 0, measured["still_dropped"]
    assert measured["packages_scanned"] >= pc.MINIMUM_PACKAGES_SCANNED_FOR_FURTHER_PAGES


@pytest.mark.parametrize("package", ["pythonorg_en", "usajobs_en"])
def test_a_restored_page_is_a_captured_request_beyond_the_first(package: str) -> None:
    """The closed form (T171's, applied to the page position): the committed
    capture is a request the engine issues, and not one it issues for page one."""
    directory = _LIBRARY / package

    assert pc.capture_is_beyond_the_first_page(directory)
    assert pc.check_package(directory)[0] is None
    assert cp.check_capture(directory) is None


@pytest.mark.parametrize("package", ["pythonorg_en", "usajobs_en"])
def test_the_derived_rule_flags_a_package_reverted_to_no_pagination(
    tmp_path: Path, package: str
) -> None:
    """Both boards were dropped to `mode: none` for want of a capture; the rule
    names each from its own committed response, and flags exactly that package."""
    library = _library_copy(tmp_path)
    assert pc.measure_unrecordable_drops(library)["still_dropped"] == []

    _drop_pagination(library, package)
    measured = pc.measure_unrecordable_drops(library)

    assert measured["still_dropped"] == [package]
    assert measured["packages_dropped_for_an_unrecordable_capture"] == 1


@pytest.mark.parametrize("package", ["pythonorg_en", "usajobs_en"])
@pytest.mark.parametrize("change", [{"max_pages": 1}, {"start": 3}], ids=["max_pages-1", "start-3"])
def test_a_restored_mode_that_loses_the_page_again_is_flagged(
    tmp_path: Path, package: str, change: dict[str, int]
) -> None:
    """`mode != "none"` was a proxy: `max_pages: 1` and `start: 3` both keep the
    mode and lose the recorded page. The metric asks the engine what it issues."""
    library = _library_copy(tmp_path)

    _edit_pagination(library, package, **change)

    assert pc.measure_unrecordable_drops(library)["still_dropped"] == [package]
    assert not pc.capture_is_beyond_the_first_page(library / package)


def test_a_board_whose_response_names_no_further_page_is_not_flagged(tmp_path: Path) -> None:
    library = _library_copy(tmp_path)
    for path in (library / "pythonorg_en").glob("*/*.html"):
        path.write_text("<html></html>", encoding="utf-8")
    _drop_pagination(library, "pythonorg_en")

    assert pc.measure_unrecordable_drops(library)["still_dropped"] == []


def test_an_empty_library_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    measured = pc.measure_unrecordable_drops(tmp_path)

    assert measured["gate_status"] == "unmeasured"
    assert measured["packages_scanned"] == 0


def test_the_exit_code_is_non_zero_when_the_t152_metric_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_main` combines three gates, and the T152 one is a term of that
    combination: dropping it would leave the metric a number nobody is stopped by."""
    target = tmp_path / "T113.json"
    assert pc._main(["pagination_capture", str(target)]) == 0

    monkeypatch.setattr(
        pc,
        "measure_unrecordable_drops",
        lambda directory=None: {
            "packages_dropped_for_an_unrecordable_capture": 1,
            "still_dropped": ["x"],
            "packages_scanned": 99,
            "gate_status": "measured",
        },
    )
    assert pc._main(["pagination_capture", str(target)]) == 1


def test_the_exit_code_is_non_zero_when_the_t152_scan_is_unmeasured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "MINIMUM_PACKAGES_SCANNED_FOR_FURTHER_PAGES", 10_000)

    assert pc._main(["pagination_capture", str(tmp_path / "T113.json")]) == 1
