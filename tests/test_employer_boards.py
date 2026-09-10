"""T144 — the `{employer}` slot, the requests it expands to, and the gate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from integral.candidate import Aim, CandidateConstraints, Location
from integral.connectors import (
    MAX_EMPLOYERS,
    ConnectorError,
    ListRequest,
    build_list_requests,
    build_list_urls,
    parse_connector,
)
from integral.employer_boards import MINIMUM_CONFORMING, measure, record
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import load_lifecycle_offer
from integral.robots import Robots
from integral.sourcing import Response, source

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _REPO_ROOT / "connectors"
_LEDGER = _CONNECTORS / "robots-adjudications.yaml"
AT = "2026-01-01T00:00:00+00:00"


def _yaml(url: str, employers: str = "  employers:\n    acme: Acme Corp\n", extra: str = "") -> str:
    return (
        "site: atshost\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-09-10'\n"
        f"list:\n  url_pattern: '{url}'\n{extra}"
        "  pagination: {mode: none, max_pages: 1}\n"
        "  from_json:\n    items: jobs\n    fields: {title: title, company: company, text: body}\n"
        f"{employers}"
    )


GOOD = "https://api.ats.test/v1/boards/{employer}/jobs"


# ---------------------------------------------------------------------------
# the format


def test_an_employer_slot_with_employers_loads() -> None:
    assert parse_connector(_yaml(GOOD)).list.employers == {"acme": "Acme Corp"}


@pytest.mark.parametrize(
    ("url", "employers"),
    [
        (GOOD, ""),  # a slot nothing fills
        ("https://api.ats.test/v1/jobs", "  employers:\n    acme: Acme\n"),  # N identical URLs
    ],
)
def test_the_slot_and_the_employers_imply_each_other(url: str, employers: str) -> None:
    with pytest.raises(ConnectorError, match="each implies the other"):
        parse_connector(_yaml(url, employers))


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://{employer}.ats.test/jobs", "URL path"),  # every employer its own origin
        ("https://api.ats.test/jobs?company={employer}", "URL path"),
        ("https://api.ats.test/jobs#{employer}", "URL path"),
        ("https://api.ats.test/{employer}/{employer}", "once"),
    ],
)
def test_the_slot_sits_once_in_the_path(url: str, why: str) -> None:
    with pytest.raises(ConnectorError, match=why):
        parse_connector(_yaml(url))


def test_a_post_listing_cannot_carry_the_slot() -> None:
    extra = "  method: POST\n  body_json: {q: x}\n"
    with pytest.raises(ConnectorError, match="GET listing only"):
        parse_connector(_yaml(GOOD, extra=extra))


@pytest.mark.parametrize("slug", ["../etc", "a/b", ".hidden", "-x", "a b", "x" * 101, "é"])
def test_a_slug_that_is_not_one_path_segment_is_refused(slug: str) -> None:
    with pytest.raises(ConnectorError, match="slug"):
        parse_connector(_yaml(GOOD, f"  employers:\n    '{slug}': Name\n"))


def test_two_slugs_differing_only_in_case_are_refused() -> None:
    with pytest.raises(ConnectorError, match="twice"):
        parse_connector(_yaml(GOOD, "  employers:\n    Acme: A\n    acme: B\n"))


def test_a_blank_display_name_is_refused() -> None:
    with pytest.raises(ConnectorError, match="display name"):
        parse_connector(_yaml(GOOD, "  employers:\n    acme: '  '\n"))


def test_the_employer_list_is_capped() -> None:
    many = "".join(f"    e{i}: E{i}\n" for i in range(MAX_EMPLOYERS + 1))
    with pytest.raises(ConnectorError, match=f"at most {MAX_EMPLOYERS}"):
        parse_connector(_yaml(GOOD, "  employers:\n" + many))


# ---------------------------------------------------------------------------
# the requests


def test_one_request_per_employer_carrying_its_name() -> None:
    connector = parse_connector(_yaml(GOOD, "  employers:\n    acme: Acme\n    1b.c_d-e: B Co\n"))
    requests = build_list_requests(connector)
    assert [(r.url, r.employer) for r in requests] == [
        ("https://api.ats.test/v1/boards/acme/jobs", "Acme"),
        ("https://api.ats.test/v1/boards/1b.c_d-e/jobs", "B Co"),
    ]
    assert build_list_urls(connector) == [r.url for r in requests]


def test_employers_multiply_pages_employer_major() -> None:
    extra = ""
    text = _yaml(
        "https://api.ats.test/{employer}/jobs?page={page}",
        "  employers:\n    a: A\n    b: B\n",
        extra,
    ).replace("{mode: none, max_pages: 1}", "{mode: query_param, param: page, max_pages: 2}")
    urls = build_list_urls(parse_connector(text))
    assert urls == [
        "https://api.ats.test/a/jobs?page=1",
        "https://api.ats.test/a/jobs?page=2",
        "https://api.ats.test/b/jobs?page=1",
        "https://api.ats.test/b/jobs?page=2",
    ]


def test_a_board_without_the_slot_names_no_employer() -> None:
    connector = parse_connector(_yaml("https://api.ats.test/jobs", ""))
    assert [r.employer for r in build_list_requests(connector)] == [None]


# ---------------------------------------------------------------------------
# the engine: `company` comes from the employer list only when the record is silent


def _package(tmp: Path) -> Path:
    package = tmp / "connectors" / "atshost_en"
    (package / "fixture").mkdir(parents=True)
    (package / "connector.yaml").write_text(
        _yaml(GOOD, "  employers:\n    acme: Acme Corp\n    beta: Beta Inc\n"), encoding="utf-8"
    )
    shutil.copy(_CONNECTORS / "greenhouse_en" / "meta.yaml", package / "meta.yaml")
    meta = (package / "meta.yaml").read_text(encoding="utf-8").replace("GLOBAL", "ES")
    (package / "meta.yaml").write_text(meta, encoding="utf-8")
    (package / "fixture" / "list.html").write_text(
        json.dumps({"jobs": [{"title": "t", "body": "b"}]}), encoding="utf-8"
    )
    return package.parent


def test_the_employer_name_fills_a_missing_company_and_never_overrides_one(
    tmp_path: Path,
) -> None:
    directory = _package(tmp_path)
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path / "p", "test")
    bodies = {
        "acme": {"jobs": [{"title": "Role A", "body": "about A"}]},
        "beta": {"jobs": [{"title": "Role B", "body": "about B", "company": "Beta (own)"}]},
    }

    def fetch(request: ListRequest) -> Response:
        slug = request.url.split("/")[-2]
        return Response(200, json.dumps(bodies[slug]))

    constraints = CandidateConstraints(
        location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
    )
    run = source(
        store,
        constraints,
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=directory,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )
    assert run.added == 2, run.summary()
    companies = {
        load_lifecycle_offer(store, path.stem)[0].company
        for path in store.path("offers").glob("sha256:*.json")
    }
    assert companies == {"Acme Corp", "Beta (own)"}


# ---------------------------------------------------------------------------
# the gate


def test_the_committed_library_clears_the_floor() -> None:
    measured = measure(_CONNECTORS, _LEDGER)
    assert measured["not_conforming"] == {}
    assert measured["ats_host_connectors_conforming"] >= MINIMUM_CONFORMING


def _library(tmp: Path, *names: str) -> Path:
    directory = tmp / "connectors"
    directory.mkdir()
    for name in names:
        shutil.copytree(_CONNECTORS / name, directory / name)
    return directory


def test_a_package_with_no_robots_row_does_not_count(tmp_path: Path) -> None:
    directory = _library(tmp_path, "greenhouse_en", "lever_en")
    ledger = tmp_path / "ledger.yaml"
    rows = [r for r in _LEDGER.read_text(encoding="utf-8").split("\n  - site: ")]
    kept = [rows[0]] + [r for r in rows[1:] if "package: connectors/lever_en" in r]
    ledger.write_text("\n  - site: ".join(kept), encoding="utf-8")
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 1
    assert "greenhouse_en" in measured["not_conforming"]


def test_a_robots_row_that_fails_its_own_checks_does_not_count(tmp_path: Path) -> None:
    """A row is a verdict only if `problems()` is empty — present is not enough.
    Here the lever row claims an agreement its own snapshot cannot support."""
    directory = _library(tmp_path, "lever_en")
    ledger = tmp_path / "ledger.yaml"
    text = _LEDGER.read_text(encoding="utf-8")
    row = text[text.index("  - site: api.lever.co") :].split("\n\n")[0]
    ledger.write_text(
        text.replace(row, row.replace("no_negative_control_possible", "two_parsers_agreed"))
    )
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 0
    assert any("two parsers agreed" in why for why in measured["not_conforming"]["lever_en"])


def test_a_package_whose_fixture_parses_to_nothing_does_not_count(tmp_path: Path) -> None:
    directory = _library(tmp_path, "lever_en")
    (directory / "lever_en" / "fixture" / "list.html").write_text("[]", encoding="utf-8")
    measured = measure(directory, _LEDGER)
    assert measured["ats_host_connectors_conforming"] == 0
    assert measured["not_conforming"]["lever_en"]


def test_two_packages_on_one_host_count_once(tmp_path: Path) -> None:
    directory = _library(tmp_path, "lever_en")
    twin = directory / "levertwin_en"
    shutil.copytree(directory / "lever_en", twin)
    yaml_text = (twin / "connector.yaml").read_text(encoding="utf-8")
    (twin / "connector.yaml").write_text(yaml_text.replace("site: lever", "site: levertwin"))
    ledger = tmp_path / "ledger.yaml"
    text = _LEDGER.read_text(encoding="utf-8")
    row = text[text.index("  - site: api.lever.co") :].split("\n\n")[0]
    twin_row = row.replace("package: connectors/lever_en", "package: connectors/levertwin_en")
    ledger.write_text(text + "\n" + twin_row)
    measured = measure(directory, ledger)
    assert measured["not_conforming"] == {}
    assert measured["ats_host_connectors_conforming"] == 1


def test_the_record_commits_the_floor_and_nothing_that_grows() -> None:
    above = {
        "ats_host_connectors_conforming": 9,
        "conforming_hosts": ["x"] * 9,
        "employers_listed": 400,
        "not_conforming": {},
    }
    below = {**above, "ats_host_connectors_conforming": 3}
    assert record(above) == {
        "ats_host_connectors_conforming": MINIMUM_CONFORMING,
        "ats_host_connectors_floor": MINIMUM_CONFORMING,
        "not_conforming": {},
    }
    assert record(below)["ats_host_connectors_conforming"] == 3
