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
    ConnectorError,
    build_list_requests,
    build_list_urls,
    load_connector,
    load_connectors,
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
    for escape in ("../fixture/list.html", "/etc/hostname", "..", "sub/list.html", ""):
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
    `retest` line for usajobs.gov carries the POST URL and both body fields, so
    the claim is checkable rather than asserted."""
    record = cp.read_record(_LIBRARY / "usajobs_en")

    assert record is not None
    assert record["provenance"] == pc.TRANSCRIBED
    assert record["transcribed_from"] == "connectors/ruled-out.yaml"
    assert cp.check_transcribed(record) == []


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
    for moving in ("captures_scanned", "claims"):
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
    its committed request. Reconstructed here rather than pinned to a commit so
    it keeps holding as the library changes.
    """
    library = tmp_path / "connectors"
    shutil.copytree(_LIBRARY, library)
    for path in library.glob("*/probe/captured.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        for advisory in ("provenance", "transcribed_from"):
            record.pop(advisory, None)
        path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    before = cp.measure(library)
    after = cp.measure(_LIBRARY)

    assert before["gate_status"] == "measured"
    assert before["captures_with_an_unenforced_provenance"] == before["captures_scanned"] > 0
    assert {row["claim"] for row in before["findings"]} == {"absent"}
    assert after["captures_with_an_unenforced_provenance"] == 0
