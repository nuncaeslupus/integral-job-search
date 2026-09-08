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

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from integral import pagination_capture as pc
from integral.connectors import build_list_requests, load_connector

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
