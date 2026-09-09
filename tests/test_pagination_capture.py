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


def test_the_usajobs_package_issues_only_the_request_that_was_measured() -> None:
    """The plan's row for T113 named `test_usajobs_en_page_two_differs_from_page_one`,
    and that test cannot be written here: it needs a live POST carrying
    `"Page": 2`, and a fixture invented in its place would be the defect this
    task is about. Only one of the task's two resolutions was open, so `Page`
    was dropped and `pagination.mode` went to `none`.

    What is checkable without a network is that the connector now issues exactly
    the request the ledger records having measured, and no other.
    """
    package = _LIBRARY / "usajobs_en"
    requests = build_list_requests(load_connector(package))

    assert len(requests) == 1
    assert json.loads(requests[0].body or b"null") == {"Keyword": "python", "ResultsPerPage": 25}
    assert pc.read_capture(package).body == {"Keyword": "python", "ResultsPerPage": 25}


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


def test_a_library_too_small_to_measure_reports_unmeasured(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "MINIMUM_REQUEST_KEYS", 100)
    _real_board(library)
    _write_capture(
        library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs?page=1", status=200
    )

    measured = pc.measure(library)

    assert measured["gate_status"] == "unmeasured"
    assert "floor 100" in measured["unmeasured_reason"]


def test_a_breached_floor_writes_nothing(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ordering #297 got wrong on S8: a run that cannot measure must not
    leave behind a record asserting the floor it never met, because that record
    is what the next healthy run's `make evidence` diffs against."""
    monkeypatch.setattr(pc, "MINIMUM_REQUEST_KEYS", 100)
    target = tmp_path / "T113.json"

    pc.write_evidence(target, library)

    assert not target.exists()


def test_the_committed_record_carries_the_floor_and_not_the_count(tmp_path: Path) -> None:
    """T100's rule. `request_keys_scanned` and `packages_scanned` move whenever
    anybody adds or retires a connector; committing them as exact values would
    redden `make evidence` on a change that is not a finding."""
    target = tmp_path / "T113.json"
    pc.write_evidence(target, _LIBRARY)
    committed = json.loads(target.read_text(encoding="utf-8"))

    assert committed["request_keys_scanned_at_least"] == pc.MINIMUM_REQUEST_KEYS
    for moving in ("request_keys_scanned", "packages_scanned", "paginated_request_keys_checked"):
        assert moving not in committed
    assert committed["paginated_request_keys_no_capture_measured"] == 0


def test_the_committed_evidence_matches_what_the_code_measures_now(tmp_path: Path) -> None:
    target = tmp_path / "T113.json"
    pc.write_evidence(target, _LIBRARY)

    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(
        pc.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )


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


def _refused(library: Path, url_pattern: str, pagination: dict[str, Any]) -> str:
    """The message `load_connector` refuses this `list` block with."""
    _edit_connector(library, url_pattern=url_pattern, pagination=pagination)
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
    `integral.verified_gate`'s three defeated rounds are about."""
    defects, checked = pc.probe_url_side()

    assert defects == []
    assert checked >= pc.MINIMUM_URL_SIDE_PROBES


def test_the_url_side_probe_table_carries_the_three_routes_and_meets_its_floor() -> None:
    """Pinned **by name**, not by count, for `test_connector_pagination`'s
    reason: a count is satisfied by any N probes, so the protection it gives a
    particular shape is coincidental. These are the shapes #406 named, plus the
    legal ones that stop the rule from taking the library down with it."""
    assert len(pc.URL_SIDE_PROBES) >= pc.MINIMUM_URL_SIDE_PROBES
    names = {probe.name for probe in pc.URL_SIDE_PROBES}
    assert {
        "param names a query key the pattern does not hold",
        "param names a key holding a literal while another key holds the placeholder",
        "query_param mode over a placeholder that sits in the path",
        "mode none with the placeholder still in the pattern",
        "body_field mode with a second page slot in the URL",
        "query_param mode with no placeholder anywhere",
        "path_segment mode with no placeholder anywhere",
        "a percent-encoded placeholder, which never substitutes",
        "two query keys holding the placeholder, one of them named",
        "the placeholder spelled into a query key's own name",
        "the ordinary shape: the named key holds the placeholder",
        "a search slot beside the page slot, under a non-English key",
        "a positional page number in the path",
        "a board with no second page, and no page slot",
        "a POST board whose page key is in the body and nowhere else",
    } <= names, sorted(names)
    # Both verdicts are represented. A table of refusals alone would pass over a
    # validator that refuses everything — the fail-closed mirror of these
    # routes, which would take the whole library out.
    assert {probe.loads for probe in pc.URL_SIDE_PROBES} == {True, False}


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


def test_the_refusal_does_not_depend_on_the_name_being_page(library: Path) -> None:
    """The same route, under a name that does not spell `page` — the check
    counts occurrences of whatever `pagination.param` names, not the literal
    string `page`."""
    message = _refused(
        library,
        "https://realboard.io/jobs?p=1&p={page}",
        {"mode": "query_param", "param": "p", "start": 1, "max_pages": 2},
    )
    assert "names 'p' 2 times" in message


def test_a_duplicate_under_an_unrelated_key_still_loads(library: Path) -> None:
    """The fail-closed control: only the name `pagination.param` certifies is
    counted, so a board that happens to repeat some other filter is
    unaffected — refusing this would take a real shape down with the fix."""
    _edit_connector(
        library,
        url_pattern="https://realboard.io/jobs?tag=a&tag=b&page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
    )
    connector = load_connector(_package(library))
    assert build_list_urls(connector) == [
        "https://realboard.io/jobs?tag=a&tag=b&page=1",
        "https://realboard.io/jobs?tag=a&tag=b&page=2",
    ]


# ---------------------------------------------------------------------------
# T154, round 2 — the second reader's F1 (mode axis) and F2 (separator axis)
#
# The first version's check lived inside `if mode == "query_param":`, so
# `mode: body_field` never reached it, and it split only on `&`, so `;` never
# registered as a second pair. Both are enumerations the closed rule (count
# occurrences of `pagination.param`'s name, over every mode that names one and
# over both conventional separators) now covers structurally rather than by
# adding one more named shape per axis.


def test_a_duplicate_query_key_under_mode_body_field_is_refused_at_load(library: Path) -> None:
    """F1. A POST board whose *body* field is the certified page key can still
    repeat that same name in its **URL**, and the first version of route 4
    never reached a `body_field` package at all — `pagination_capture`'s
    `body_field` arm reads only the captured body, so nothing certifies the
    query string either. A framework that merges query and body namespaces
    ($_REQUEST, Flask's `request.values`, Rails' `params`) may honour the
    fixed query occurrence over the varying body one, which is the same
    pinned-to-one-page harm on the other half of the request."""
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/Search/ExecuteSearch?Page=1&Page=2",
        method="POST",
        body_json={"Keyword": "python", "ResultsPerPage": 25, "Page": PAGE_PLACEHOLDER},
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 3},
        item=None,
        fields=None,
        from_json={"items": "Jobs", "fields": {"title": "Title", "detail_url": "Url"}},
    )
    with pytest.raises(ConnectorError, match="names 'Page' 2 times"):
        load_connector(_package(library))


def test_a_single_fixed_query_pair_beside_a_body_field_still_loads(library: Path) -> None:
    """The mode-axis control: a single, non-duplicated query pair beside the
    varying body field is not this rule's business, the same way an
    unrelated query-side duplicate under `query_param` mode is not."""
    _edit_connector(
        library,
        url_pattern=f"https://{_REAL_SITE}/Search/ExecuteSearch?Page=1",
        method="POST",
        body_json={"Keyword": "python", "ResultsPerPage": 25, "Page": PAGE_PLACEHOLDER},
        pagination={"mode": "body_field", "param": "Page", "start": 1, "max_pages": 2},
        item=None,
        fields=None,
        from_json={"items": "Jobs", "fields": {"title": "Title", "detail_url": "Url"}},
    )
    connector = load_connector(_package(library))
    assert build_list_urls(connector) == [
        f"https://{_REAL_SITE}/Search/ExecuteSearch?Page=1",
        f"https://{_REAL_SITE}/Search/ExecuteSearch?Page=1",
    ]


def test_a_semicolon_separated_duplicate_is_refused_at_load(library: Path) -> None:
    """F2. `;` is not `application/x-www-form-urlencoded`'s pair separator —
    that grammar recognises only `&` — but it is the historical alternate
    (RFC 1866; PHP's `arg_separator.input` before 5.4), and RFC 3986 §3.4
    itself states no pair grammar at all (`query = *( pchar / "/" / "?" )`,
    pairs being only a stated *usage*). Either reading of
    `?page=1;page={page}` is a harm this module already refuses: a server
    that splits on `;` sees `page` sent twice (this task's own certified-
    duplicate harm), and one that does not sees the single value
    `1;page=1`/`1;page=2` — never an integer page number, so `page` never
    actually varies (T113 route 3's "identical request" harm)."""
    message = _refused(
        library,
        "https://realboard.io/jobs?page=1;page={page}",
        {"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
    )
    assert "names 'page' 2 times" in message


def test_a_value_that_merely_contains_an_equals_sign_is_not_a_second_pair(
    library: Path,
) -> None:
    """The separator-axis control: a value that happens to spell `key=value`
    inside itself is data, not a delimiter — `?q=page%3D1&page={page}` has
    exactly one `page` pair after percent-decoding is set aside, the same way
    `test_a_page_index_read_from_a_response_does_not_certify_a_request_key`
    keeps a response body's own text from being read as a request."""
    _edit_connector(
        library,
        url_pattern="https://realboard.io/jobs?q=page%3D1&page={page}",
        pagination={"mode": "query_param", "param": "page", "start": 1, "max_pages": 2},
    )
    connector = load_connector(_package(library))
    assert build_list_urls(connector) == [
        "https://realboard.io/jobs?q=page%3D1&page=1",
        "https://realboard.io/jobs?q=page%3D1&page=2",
    ]


def test_every_duplicate_key_probe_agrees_with_the_rule() -> None:
    """The measurement itself, same shape as `test_every_url_side_probe_agrees_with_the_rule`:
    behavioural, so a validator deleted, weakened or replaced by a comment
    fails here."""
    defects, checked = pc.probe_duplicate_page_keys()

    assert defects == []
    assert checked >= pc.MINIMUM_DUPLICATE_KEY_PROBES


def test_the_duplicate_key_probe_table_meets_its_floor_and_keeps_its_names() -> None:
    """Pinned **by name**, for the same reason
    `test_the_url_side_probe_table_carries_the_three_routes_and_meets_its_floor`
    is: a count alone is satisfied by any N probes and protects a particular
    shape only by coincidence."""
    assert len(pc.DUPLICATE_KEY_PROBES) >= pc.MINIMUM_DUPLICATE_KEY_PROBES
    names = {probe.name for probe in pc.DUPLICATE_KEY_PROBES}
    assert {
        "the named key sent twice, the fixed value first",
        "the named key sent twice, the fixed value second",
        "the same route under a name that does not spell 'page'",
        "a duplicate under an unrelated key is not this rule's business",
        "the ordinary single-occurrence shape still loads",
        "the named key sent twice, across mode: body_field's own query string",
        "a body_field board with one fixed query pair beside the body field still loads",
        "the named key sent twice via a ';'-separated pair",
    } <= names, sorted(names)
    # Both verdicts represented, for the same reason the URL-side table needs
    # both: a table of refusals alone passes over a validator that refuses
    # everything.
    assert {probe.loads for probe in pc.DUPLICATE_KEY_PROBES} == {True, False}


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


def test_a_library_too_small_to_scan_reports_unmeasured_for_duplicate_keys(
    library: Path,
) -> None:
    """The floor refuses a clean zero over a library nobody read — a
    one-package fixture with a single query key is exactly that."""
    measured = pc.measure_duplicate_page_keys(library)
    assert measured["gate_status"] == "unmeasured"
    assert "query-key occurrence" in measured["unmeasured_reason"]


def test_a_breached_duplicate_key_floor_writes_nothing(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pc, "MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED", 100)
    target = tmp_path / "T154.json"

    pc.write_duplicate_page_keys_evidence(target, _LIBRARY)

    assert not target.exists()


def test_a_breached_duplicate_key_floor_fails_the_entrypoint(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F3: T154's own instance of T115/T153's rule — a breached floor must
    fail `_main` outright at exit **1**, not the 3 `make evidence` prints as
    `unmeasured (recorded)` and walks past while the last-committed
    `T154.json` still reads `gate_status: measured`.

    T113 is given a real capture and left at its default floor so it reads
    cleanly (`t113_code == 0`) — otherwise a `no probe/captured.json` finding
    of T113's own would also read exit 1, and the assertion below would pass
    without T154's branch having been reached at all."""
    monkeypatch.setattr(pc, "MINIMUM_REQUEST_KEYS", 1)
    monkeypatch.setattr(pc, "MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED", 100)
    monkeypatch.setattr(pc, "DEFAULT_CONNECTORS_DIR", library)
    _real_board(library)
    _write_capture(library, url="https://www.examplejobs.test/jobs?page=1")
    target = tmp_path / "T113.json"

    t113_only = pc.measure(library)
    assert t113_only["gate_status"] == "measured"
    assert t113_only["paginated_request_keys_no_capture_measured"] == 0
    assert t113_only["url_side_routes_open"] == 0

    assert pc._main(["pagination_capture", str(target)]) == 1
    sibling = tmp_path / "T154.json"
    assert not sibling.exists()


def test_the_committed_duplicate_key_record_carries_the_floor_and_not_the_count(
    tmp_path: Path,
) -> None:
    """T100's rule, applied to this gate: `query_key_occurrences_scanned`,
    `paginated_packages_scanned` and `duplicate_key_probes_checked` all move
    whenever anybody adds or retires a connector or a probe."""
    target = tmp_path / "T154.json"
    pc.write_duplicate_page_keys_evidence(target, _LIBRARY)
    committed = json.loads(target.read_text(encoding="utf-8"))

    assert (
        committed["query_key_occurrences_scanned_at_least"]
        == pc.MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED
    )
    assert committed["duplicate_key_probes_at_least"] == pc.MINIMUM_DUPLICATE_KEY_PROBES
    for moving in (
        "query_key_occurrences_scanned",
        "paginated_packages_scanned",
        "duplicate_key_probes_checked",
    ):
        assert moving not in committed
    assert committed["duplicated_page_keys_certified"] == 0


def test_the_committed_duplicate_key_evidence_matches_what_the_code_measures_now(
    tmp_path: Path,
) -> None:
    target = tmp_path / "T154.json"
    pc.write_duplicate_page_keys_evidence(target, _LIBRARY)

    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(
        pc.DEFAULT_T154_EVIDENCE_PATH.read_text(encoding="utf-8")
    )


def test_the_entry_point_writes_both_t113_and_t154_evidence(tmp_path: Path) -> None:
    """The fenced gate for both tasks invokes only `python -m
    integral.pagination_capture`, so one run has to produce both files."""
    target = tmp_path / "T113.json"

    assert pc._main(["pagination_capture", str(target)]) == 0
    assert json.loads(target.read_text(encoding="utf-8"))["gate_status"] == "measured"
    sibling = tmp_path / "T154.json"
    assert json.loads(sibling.read_text(encoding="utf-8"))["duplicated_page_keys_certified"] == 0


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


def test_the_usajobs_capture_says_where_it_came_from() -> None:
    """The board this task is named for. Its request record is byte-identical
    to the re-runnable `retest` curl `connectors/ruled-out.yaml` commits, so
    `transcribed` is what the file now says — and the reason the distinction
    was worth a field is that `mode: none` means the scan never reads this
    capture at all, leaving its worth entirely to whoever opens the package."""
    capture = pc.read_capture(_LIBRARY / "usajobs_en")

    assert capture.provenance == pc.TRANSCRIBED
    assert capture.body == {"Keyword": "python", "ResultsPerPage": 25}


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


def test_a_live_response_file_that_is_a_symlink_is_not_a_committed_response(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The half of the sentence above that a name check cannot deliver, and
    which this test's neighbour claimed for two rounds without checking.

    `_PLAIN_FILENAME` constrains the **name**; `read_bytes` then follows a
    symlink, and git commits symlinks. So `probe/list.html` pointing at another
    package's response — or at any file on the machine — would let a capture
    certify itself against bytes it never received, with a `bytes` and a
    `sha256` that both match because they were computed over the target. The
    claim `live` makes is about what *this* board sent.
    """
    _real_board(library)
    outsider = tmp_path / "somebody-elses.html"
    outsider.write_bytes(b"<html>another package's response</html>")
    probe = _package(library) / "probe"
    probe.mkdir(exist_ok=True)

    for target in (outsider, Path("/etc/hostname")):
        link = probe / "list.html"
        link.unlink(missing_ok=True)
        link.symlink_to(target)
        body = link.read_bytes()
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=f"https://{_REAL_SITE}/jobs",
            status=200,
            provenance=pc.LIVE,
            # Honest about the bytes on the other end of the link, which is
            # exactly what makes the digest no defence here.
            response={
                "file": "list.html",
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
            },
        )

        (finding,) = _provenance_findings(library, today=date(2026, 9, 8))
        assert finding["claim"] == pc.LIVE
        assert "does not resolve inside the package's own probe/" in finding["reason"], target


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


def test_a_capture_cannot_cite_itself_as_the_request_it_was_transcribed_from(
    library: Path, provenance_floor: None
) -> None:
    """A record is not a source for itself.

    `captured.json` carries its own `url` and its own `body` by construction, so
    a containment check pointed at it answers every question it can ask. That
    makes self-citation the cheapest forgery the module could leave open — one
    line, no new file, no command — sitting behind `transcribed`, the word that
    sounds like somebody checked. The POST spelling matters as much as the GET
    one: pretty-printed JSON happens to break the compact body needles, and
    formatting is not a boundary — re-serialised compactly, the same forgery is
    the same forgery.
    """
    _real_board(library)
    repo_root = library.parent
    myself = f"connectors/{_REFERENCE.name}/probe/captured.json"
    url = f"https://{_REAL_SITE}/search"

    # GET: the record's own `url` is the whole of what a containment check reads.
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from=myself,
    )
    (finding,) = _provenance_findings(library, repo_root=repo_root)
    assert finding["claim"] == pc.TRANSCRIBED
    assert "own probe/" in finding["reason"], finding["reason"]

    # POST, written compactly so the body needles match the file byte for byte.
    record = {
        "captured_at": "2026-09-08",
        "url": url,
        "method": "POST",
        "body": {"Keyword": "python", "ResultsPerPage": 25},
        "status": 200,
        "provenance": pc.TRANSCRIBED,
        "transcribed_from": myself,
    }
    path = _package(library) / "probe" / "captured.json"
    path.write_text(json.dumps(record, separators=(",", ":")), encoding="utf-8")
    assert '"Keyword":"python"' in path.read_text(encoding="utf-8")

    (finding,) = _provenance_findings(library, repo_root=repo_root)
    assert finding["claim"] == pc.TRANSCRIBED
    assert "own probe/" in finding["reason"], finding["reason"]


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


def test_a_transcribed_source_reached_through_a_symlink_is_not_committed_here(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """`transcribed_from` refuses `..` and an absolute path, which constrains
    the string. A symlink is how that constraint is walked around: a path that
    reads as repo-relative, resolving to a file the repository does not carry
    at that path. "Committed here" is the claim, and a link is not it —
    including a link whose target is in the tree, which is why the reason no
    longer says "does not resolve inside this repo" about an input that plainly
    does. A second reader caught that sentence being false about its own case:
    the verdict was right and the words were not."""
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text(f"curl -s '{url}'\n", encoding="utf-8")
    (repo / "inside.sh").write_text(f"curl -s '{url}'\n", encoding="utf-8")

    _write_capture(
        library,
        captured_at="2026-09-08",
        url=url,
        status=200,
        provenance=pc.TRANSCRIBED,
        transcribed_from="ledger.yaml",
    )

    # Out of the tree, and — the case the old sentence lied about — in it.
    for target in (outside, Path("inside.sh")):
        (repo / "ledger.yaml").unlink(missing_ok=True)
        (repo / "ledger.yaml").symlink_to(target)
        (finding,) = _provenance_findings(library, repo_root=repo)
        assert "is not the file this repo commits at that path" in finding["reason"], target


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


def test_a_probe_linked_at_a_sibling_package_is_not_this_packages_capture(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """`test_deleting_the_capture_is_not_the_cheapest_way_to_pass`, with the
    deletion replaced by a link — and it is cheaper than the deletion, because
    it reads as a pass rather than as a finding.

    A package with **no capture at all** borrows a neighbour's by pointing its
    `probe/` at the neighbour's, and every question the module asks is answered
    by the neighbour's artefact: the record resolves, its `transcribed_from`
    resolves, the command is committed. What is not true is the only thing the
    row claims — that *this* package's request is the one that was recorded.
    """
    _real_board(library)
    package = _package(library)
    url = f"https://{_REAL_SITE}/search"

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "ledger.yaml").write_text(f"retest: curl -s '{url}'\n", encoding="utf-8")

    # A neighbour whose own capture is honest. It keeps the reference package's
    # reserved example domain, so it is excluded from the scan and the finding
    # below is unambiguously about the borrower.
    donor = library / "donorboard_es"
    shutil.copytree(_REFERENCE, donor)
    (donor / "probe").mkdir(exist_ok=True)
    (donor / "probe" / "captured.json").write_text(
        json.dumps(
            {
                "captured_at": "2026-09-08",
                "url": url,
                "status": 200,
                "provenance": pc.TRANSCRIBED,
                "transcribed_from": "ledger.yaml",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    shutil.rmtree(package / "probe", ignore_errors=True)
    (package / "probe").symlink_to(Path("..") / donor.name / "probe", target_is_directory=True)

    (finding,) = _provenance_findings(library, repo_root=repo, today=date(2026, 9, 8))
    assert finding["package"] == package.name
    assert finding["claim"] == "absent"
    assert "symlinked probe/" in finding["reason"], finding["reason"]


def test_a_symlinked_package_borrows_the_capture_it_reads_as_holding(
    library: Path, provenance_floor: None
) -> None:
    """`test_a_probe_linked_at_a_sibling_package_is_not_this_packages_capture`,
    one directory further up — and the fix for that one is what left this open.

    The containment rule resolves its **base** by design, so whatever it is
    asked from is the one path it cannot see. Asked from the package, the
    package directory is exempt: a package that is a committed symlink at a
    sibling — git stores one as mode `120000`, so this is a diff a reviewer
    receives — answers `probe/captured.json`, `response.file`, the byte count
    and the digest out of the sibling's artefact, all of them honest, none of
    them **its**. A package committing no capture at all then reads as an
    enforced `live`, which is exactly `test_deleting_the_capture_is_not_the_
    cheapest_way_to_pass` reached by a link instead of a deletion, and it reads
    as a pass rather than as a finding.

    So the question is asked with the **library** as the base and the package's
    own name as the first component of the path.
    """
    _real_board(library)
    donor = _package(library)
    probe = _capture_probe(library)
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.LIVE,
        response=_live_response(probe),
    )
    # The donor's own claim is fully substantiated, so nothing below is about a
    # broken capture: it is about which package holds it.
    assert _provenance_findings(library, today=date(2026, 9, 8)) == []

    borrower = library / "newboard_es"
    borrower.symlink_to(Path(donor.name), target_is_directory=True)

    measured = cp.measure(library, today=date(2026, 9, 8))
    assert measured["captures_scanned"] == 2
    (finding,) = measured["findings"]
    assert finding["package"] == borrower.name
    assert finding["claim"] == "absent"
    assert "symlinked package" in finding["reason"], finding["reason"]
    assert finding["direction"] == "fail-open"
    # The donor's `live` is counted once, by the package that holds it. A
    # borrowed claim is not a claim, so the tally does not read two.
    assert measured["claims"]["live"] == 1

    # And `check_capture` refuses it when handed the package directly, so the
    # guarantee does not rest on `measure` having got there first — the shape
    # `check_live` was blocked for in round three.
    direct = cp.check_capture(borrower, today=date(2026, 9, 8))
    assert direct is not None and "symlinked package" in direct.reason

    # Nor on `check_capture` having got there first. `_borrowed_package` is a
    # verdict about a package; the containment rule underneath it is a verdict
    # about a path, and each reader has to hold on its own — a mutant that
    # reverts the rule to asking from the package survived every assertion
    # above, because the verdict was answering first. That is the exact defect
    # F4 was blocked for, sitting inside F4's own fix, so it is pinned the way
    # F4's was: by asking the readers directly.
    record = json.loads((donor / "probe" / "captured.json").read_text(encoding="utf-8"))
    assert cp.read_record(borrower) is None
    reasons = cp.check_live(borrower, record, date(2026, 9, 8))
    assert any("own probe/" in reason for reason in reasons), reasons

    # The rule's own new argument. Making the package's name a component of the
    # path means the name is now something that can point out of the library,
    # and `..` is how: it resolves away to the parent, which is the shape the
    # comparison is built to notice. Fail-closed, which is the safe direction
    # for a name nothing legitimate spells.
    assert cp._committed_in_package(library / "..", Path("probe")) is False


def test_a_package_linked_at_an_excluded_one_is_not_excluded_with_it(
    library: Path, provenance_floor: None
) -> None:
    """What the borrowed-package check introduces: an order.

    `measure` reads a package's `site` to decide whether a reserved example
    domain excludes it from the scan. Read out of a **borrowed** package that
    is the donor's site, so a package linked at an excluded one is excluded by
    a property it does not have — it vanishes from the denominator instead of
    being counted, which is the quietest fail-open of the three: no finding, no
    claim, and a `captures_scanned` that never knew it was there.

    So the question is asked before anything is read out of the package. The
    exclusion rule is exercised from both sides here as it is everywhere in
    this file: the donor is still excluded, on its own domain.
    """
    borrower = library / "borrowedboard_es"
    borrower.symlink_to(Path(_REFERENCE.name), target_is_directory=True)

    measured = cp.measure(library, today=date(2026, 9, 8))
    assert measured["gate_status"] == "measured"
    assert measured["example_packages_excluded"] == [_REFERENCE.name]
    assert measured["captures_scanned"] == 1
    (finding,) = measured["findings"]
    assert finding["package"] == borrower.name
    assert "symlinked package" in finding["reason"], finding["reason"]


def test_a_library_reached_through_a_symlink_is_still_measured(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The control the case above is bounded by, and the reason the containment
    rule resolves its base at all.

    A path that leads through a link is not thereby a borrowed path: a checkout
    under a symlinked home, a worktree reached through one, a `/tmp` that is
    itself a link on some platforms. If the rule refused those, it would be
    fail-closed for **every** package at once — a gate that fails everywhere is
    as useless as one that passes everywhere, and it would fail for a reason
    nobody could act on. The base is the caller's own argument and is trusted
    as such; only what this module derives below it is checked.
    """
    _real_board(library)
    probe = _capture_probe(library)
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.LIVE,
        response=_live_response(probe),
    )

    through_a_link = tmp_path / "library-link"
    through_a_link.symlink_to(library, target_is_directory=True)

    measured = cp.measure(through_a_link, today=date(2026, 9, 8))
    assert measured["gate_status"] == "measured"
    assert measured["captures_scanned"] == 1
    assert measured["findings"] == []
    assert measured["claims"]["live"] == 1


def test_the_library_the_gate_measures_is_the_one_this_repo_commits() -> None:
    """The base the rule stops at, pinned where it can be — in the gate.

    Moving the containment question up to the library closes the package
    directory and makes the **library** the path nothing asks about, which is
    the same shape one step out again. It cannot be closed inside the module:
    the base is whatever the caller named, and refusing a caller's own root is
    the fail-closed failure the control above exists to prevent. What can be
    done is to ask it once about the root the shipped gate actually uses, which
    is a fact about this repository rather than a rule about an argument. So
    the recursion stops here, deliberately and in a test, rather than in a
    sentence saying it does not matter.
    """
    assert cp._committed_at(_REPO_ROOT, Path("connectors"))
    packages = [package for package in sorted(_LIBRARY.iterdir()) if package.is_dir()]
    # A clean zero over a scan nobody made is the failure this module's own
    # floor exists to refuse, and the list below is a scan.
    assert len(packages) >= cp.MINIMUM_CAPTURES_SCANNED, len(packages)
    borrowed = [
        package.name for package in packages if not cp._committed_at(_LIBRARY, Path(package.name))
    ]
    assert borrowed == [], borrowed


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


def test_a_refusal_that_quotes_a_command_is_inside_the_disclosed_ceiling(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """The limit, pinned rather than asserted in prose — the other half of
    `test_a_command_wrapped_over_several_lines…`, which bounds strictness from
    the same side.

    The module's honest claim is *"this repo commits the text of a command for
    this request"*. It is not, and cannot be, *"the fetch happened"*: reading
    what the surrounding prose says was done with the command means deciding
    textual negation, and a check that guessed at that would be worse than a
    narrow one. So a note denying the fetch while **quoting** the command
    passes, and a note that names no client word does not. Both spellings are
    committed here so that the ceiling is a measured fact rather than a
    sentence in a docstring — which is exactly the substitution this task
    exists to refuse, and which the docstring itself made until a second reader
    read it against the code.
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

    # Inside the ceiling: the command's text is committed, whatever the prose
    # around it says was done with it.
    quoting = [
        f"The fetch was REFUSED by robots.txt and never issued; it would have been: curl '{url}'\n",
        f"# do NOT curl {url} — the board refuses it\n",
        f"2026-09-02: robots refuses this. We never ran: curl -s '{url}'\n",
    ]
    for text in quoting:
        assert _cited(text) == [], text

    # Outside it: the same denial with no client word is the class the module
    # does refuse, and it is refused.
    (finding,) = _cited(f"The fetch of {url} was REFUSED by robots.txt and never issued.\n")
    assert "commits no command for it" in finding["reason"], finding["reason"]


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


def test_a_needle_that_is_not_there_covers_nothing(library: Path) -> None:
    """What the fix above introduces, asked about before something else asks.

    Independence is now a map of the character ranges the needles occupy, and
    an **empty** needle occupies none. Recording its zero-length spans would
    make it overlap every match instead — a span at 3 sits inside a match from
    2 to 6 — so a single empty string would refuse every transcribed claim in
    the library on the strength of something that is not in the file. It also
    constrains nothing, `"" in line` being true of every line, so it was never
    evidence to begin with.

    Nothing produces one today: `_body_needles` renders through `json.dumps`,
    whose shortest output is two characters, and `check_transcribed` refuses an
    empty `url` before the list is built. This is the guard for the caller that
    forgets, pinned rather than left to the next reader to rediscover — the
    same reason `_committed_at`'s absolute-path behaviour is written down.
    """
    url = f"https://{_REAL_SITE}/search"
    assert cp._issues_the_request(f"curl -s '{url}'", ["", url]) is True

    # And the scan advances one character rather than one needle, so
    # overlapping occurrences are all mapped: a span missed is a span a client
    # word can hide behind.
    assert cp._needle_spans("aaa", ["aa"]) == [(0, 2), (1, 3)]
    assert cp._needle_spans("abc", [""]) == []


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


def test_every_client_the_vocabulary_names_is_a_command(
    library: Path, tmp_path: Path, provenance_floor: None
) -> None:
    """All four members, not the one the corpus happens to use.

    `usajobs_en` writes `curl`, so narrowing `_REQUEST_COMMAND` to `curl` alone
    survived the suite: three quarters of a documented vocabulary was unmeasured
    while the docstring listed it. That is a gate certifying a property it does
    not test — this task's subject, applied to the fix for it — and it matters
    because the answer to an omitted client is "add the name", which nothing
    would catch being undone.
    """
    _real_board(library)
    url = f"https://{_REAL_SITE}/search"
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "notes.md"

    for command in ("curl", "wget", "xh", "Invoke-WebRequest"):
        source.write_text(f"{command} '{url}'\n", encoding="utf-8")
        _write_capture(
            library,
            captured_at="2026-09-08",
            url=url,
            status=200,
            provenance=pc.TRANSCRIBED,
            transcribed_from="notes.md",
        )
        assert _provenance_findings(library, repo_root=repo) == [], command


def test_the_committed_record_does_not_restate_the_numerator_as_a_measurement(
    library: Path, provenance_floor: None
) -> None:
    """The look-again this round was told to do, turned on this module's own
    evidence — and it found one.

    `Finding.direction` defaults to `fail-open` and nothing here ever sets it
    otherwise, so the committed `fail_open` was arithmetically
    `captures_with_an_unenforced_provenance`, in every run there will ever be.
    Two numbers in one evidence file that cannot disagree: the second reads as
    corroboration and corroborates nothing, which is the label-counting shape
    found four times in this repository the night this was written. It is
    dropped from the record and the identity is pinned here, so that a future
    finding with a genuinely different direction is a change somebody has to
    make on purpose rather than a silent divergence between two numbers nobody
    was comparing.

    Contrast `cue_audit` and `second_reader`, which derive a direction per case
    from the case: there `fail_open` is a measurement, and committing it says
    something.
    """
    _real_board(library)
    _write_capture(library, captured_at="2026-09-08", url=f"https://{_REAL_SITE}/jobs", status=200)

    measured = cp.measure(library)
    assert measured["captures_with_an_unenforced_provenance"] == 1
    assert measured["fail_open"] == measured["captures_with_an_unenforced_provenance"]
    assert {row["direction"] for row in measured["findings"]} == {"fail-open"}

    committed = cp.record(measured)
    assert "fail_open" not in committed
    assert "captures_with_an_unenforced_provenance" in committed


def test_the_claim_tally_is_the_vocabulary_and_not_a_second_copy_of_it(
    library: Path, monkeypatch: pytest.MonkeyPatch, provenance_floor: None
) -> None:
    """One spelling of the three values, not two.

    `measure` used to build its tally from a literal `{LIVE: 0, TRANSCRIBED: 0,
    UNRECORDED: 0}` and test membership against *that*, which is a second reader
    of `DECLARABLE` — the same T122 shape the containment rule was blocked for,
    one function along. A fourth declarable value would have been enforceable by
    `check_capture` and invisible to the tally, with nothing to notice.
    """
    _real_board(library)
    monkeypatch.setattr(cp, "DECLARABLE", frozenset({*cp.DECLARABLE, "reconstructed"}))
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance="reconstructed",
    )

    measured = cp.measure(library)
    assert measured["claims"]["reconstructed"] == 1, measured["claims"]


def test_deleting_the_capture_is_not_the_cheapest_way_to_pass(
    library: Path, provenance_floor: None
) -> None:
    """Otherwise a gate about capture provenance is satisfied by having no
    capture — the fail-open direction this family of tasks keeps meeting."""
    _real_board(library)
    probe = _package(library) / "probe" / "captured.json"
    probe.parent.mkdir(exist_ok=True)
    probe.write_text("{}", encoding="utf-8")
    assert _provenance_findings(library)[0]["claim"] == "absent"

    probe.unlink()
    (finding,) = _provenance_findings(library)
    assert finding["claim"] == "absent"
    assert "no readable" in finding["reason"]

    probe.write_text("[]", encoding="utf-8")
    assert _provenance_findings(library)[0]["reason"].startswith("no readable")


def test_the_committed_library_has_no_unenforced_provenance() -> None:
    """The gate itself, over the twenty shipped captures — nineteen truthfully
    `unrecorded`, one `transcribed` naming a ledger line that carries its URL
    and its body."""
    measured = cp.measure(_LIBRARY)

    assert measured["gate_status"] == "measured"
    assert measured["captures_with_an_unenforced_provenance"] == 0, measured["findings"]
    assert measured["claims"] == {"live": 0, "transcribed": 1, "unrecorded": 19}
    assert measured["example_packages_excluded"] == ["examplejobs_es"]


def test_the_usajobs_capture_names_a_resolvable_committed_request() -> None:
    """The one capture that claims anything. `connectors/ruled-out.yaml`'s
    `retest` line for usajobs.gov is a single committed `curl` carrying the POST
    URL and both body fields, so the claim is checkable rather than asserted —
    and the stricter join this task shipped is one the genuine citation still
    satisfies, which is the point of keeping it."""
    package = _LIBRARY / "usajobs_en"
    record = cp.read_record(package)

    assert record is not None
    assert record["provenance"] == pc.TRANSCRIBED
    assert record["transcribed_from"] == "connectors/ruled-out.yaml"
    assert cp.check_transcribed(package, record) == []


def test_the_usajobs_claim_rests_on_the_committed_command_and_not_on_a_mention(
    tmp_path: Path,
) -> None:
    """The join, exercised where it is actually load-bearing.

    Over the shipped library exactly one capture makes a substantive claim, so a
    weak join is invisible in the committed state — which is how bare
    containment shipped. Here the ledger is copied with the one `retest` command
    turned into prose about the same request: every string the check reads is
    still present, and the claim must stop resolving.
    """
    repo = tmp_path / "repo"
    (repo / "connectors").mkdir(parents=True)
    ledger = _LIBRARY / "ruled-out.yaml"
    prose = ledger.read_text(encoding="utf-8").replace(
        'retest: "curl -s -X POST', 'retest: "we once ran a POST'
    )
    (repo / "connectors" / "ruled-out.yaml").write_text(prose, encoding="utf-8")
    record = cp.read_record(_LIBRARY / "usajobs_en")
    assert record is not None

    (reason,) = cp.check_transcribed(_LIBRARY / "usajobs_en", record, repo)

    assert "commits no command for it" in reason


def test_a_fabricated_live_capture_over_the_real_library_raises_the_metric(
    tmp_path: Path,
) -> None:
    """The gate's own falsifiability, demonstrated on the shipped library
    rather than on a one-package fixture: copy the twenty, relabel one
    `live`, and the metric moves off zero. A gate nobody has watched fail is
    not known to be able to."""
    library = tmp_path / "connectors"
    shutil.copytree(_LIBRARY, library)
    path = library / "arbeitnow_en" / "probe" / "captured.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**record, "provenance": pc.LIVE}), encoding="utf-8")

    measured = cp.measure(library)

    assert measured["captures_with_an_unenforced_provenance"] == 1
    (finding,) = measured["findings"]
    assert finding["package"] == "arbeitnow_en"
    assert finding["claim"] == pc.LIVE
    assert measured["fail_open"] == 1


def test_a_library_too_small_to_enforce_reports_unmeasured(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean zero over a scan that found nothing is the vacuous truth this
    repository keeps meeting — so the floor, and `unmeasured` rather than 0."""
    monkeypatch.setattr(cp, "MINIMUM_CAPTURES_SCANNED", 100)
    _real_board(library)
    _write_capture(
        library,
        captured_at="2026-09-08",
        url=f"https://{_REAL_SITE}/jobs",
        status=200,
        provenance=pc.UNRECORDED,
    )

    measured = cp.measure(library)

    assert measured["gate_status"] == "unmeasured"
    assert measured["captures_with_an_unenforced_provenance"] == 0
    assert "floor 100" in measured["unmeasured_reason"]


def test_an_empty_library_is_unmeasured_rather_than_clean(tmp_path: Path) -> None:
    empty = tmp_path / "connectors"
    empty.mkdir()

    assert cp.measure(empty)["gate_status"] == "unmeasured"
    assert cp.measure(tmp_path / "absent")["gate_status"] == "unmeasured"


def test_a_breached_floor_writes_nothing_and_fails_the_gate(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two properties in one place because they are one decision. The record is
    not written (a run that could not measure must not leave behind an artefact
    asserting the floor it never met), and the exit status is **1** rather than
    the 3 `make evidence` prints as `unmeasured (recorded)` and walks past —
    T115's finding, which a module written after it has no reason to reproduce.
    """
    monkeypatch.setattr(cp, "MINIMUM_CAPTURES_SCANNED", 100)
    monkeypatch.setattr(cp, "DEFAULT_CONNECTORS_DIR", library)
    target = tmp_path / "T153.json"

    cp.write_evidence(target, library)
    assert not target.exists()

    assert cp._main(["capture_provenance", str(target)]) == 1
    assert not target.exists()


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


def test_the_committed_provenance_record_carries_the_floor_and_not_the_count(
    tmp_path: Path,
) -> None:
    """T100's rule. `captures_scanned` and the per-claim tally both move the
    moment anybody adds, retires or re-records a connector; committing them as
    exact values would redden `make evidence` on a change that is not a
    finding."""
    target = tmp_path / "T153.json"
    cp.write_evidence(target, _LIBRARY)
    committed = json.loads(target.read_text(encoding="utf-8"))

    assert committed["captures_scanned_at_least"] == cp.MINIMUM_CAPTURES_SCANNED
    for moving in ("captures_scanned", "claims", "example_packages_excluded"):
        assert moving not in committed
    assert committed["captures_with_an_unenforced_provenance"] == 0


def test_the_committed_provenance_evidence_matches_what_the_code_measures_now(
    tmp_path: Path,
) -> None:
    target = tmp_path / "T153.json"
    cp.write_evidence(target, _LIBRARY)

    assert json.loads(target.read_text(encoding="utf-8")) == json.loads(
        cp.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    )


def test_the_gate_is_not_satisfiable_by_the_state_it_was_filed_against(tmp_path: Path) -> None:
    """The check this repository keeps having to make about its own gates.

    A metric that already reads 0 over the defect it was filed against is
    satisfiable by doing nothing, and every `unmeasured`/floor mechanism above
    is decoration behind it. So: rebuild the library as T113 shipped it — no
    capture carrying a `provenance` key, and `usajobs_en`'s `transcribed`
    naming nothing — and the metric must be the whole population, not zero.

    Measured against the real `origin/main` tree while T153 was being written:
    **20 of 20**, nineteen `absent` and one `transcribed` that could not name
    its committed request. The reconstruction is exactly that state — the
    `provenance` key removed wherever this task added it, and `usajobs_en` left
    carrying T113's `transcribed` with nothing to substantiate it — rather than
    a flatter 20 `absent`, so the population it rebuilds is the one the
    measurement above cites. Reconstructed rather than pinned to a commit so it
    keeps holding as the library changes.
    """
    library = tmp_path / "connectors"
    shutil.copytree(_LIBRARY, library)
    for path in library.glob("*/probe/captured.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        # T113 shipped `transcribed` on usajobs_en and nothing anywhere else;
        # `transcribed_from` is this task's, and so is every `unrecorded`.
        record.pop("transcribed_from", None)
        if record.get("provenance") == pc.UNRECORDED:
            record.pop("provenance")
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    before = cp.measure(library)
    after = cp.measure(_LIBRARY)

    assert before["gate_status"] == "measured"
    assert before["captures_with_an_unenforced_provenance"] == before["captures_scanned"] > 0
    claims = sorted(row["claim"] for row in before["findings"])
    assert claims == ["absent"] * (before["captures_scanned"] - 1) + [pc.TRANSCRIBED]
    assert after["captures_with_an_unenforced_provenance"] == 0
