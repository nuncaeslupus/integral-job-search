"""T144 — the `{employer}` slot, the requests it expands to, and the gate."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
from integral.sourcing import FETCH_LOG, Response, source

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
        ("https://{employer}.ats.test/jobs", "in the path"),  # every employer its own origin
        ("https://api.ats.test/jobs?company={employer}", "in the path"),
        ("https://api.ats.test/jobs#{employer}", "in the path"),
        ("https://{employer}@api.ats.test/jobs", "in the path"),  # userinfo is the netloc
        ("https://api.ats.test:{employer}/jobs", "in the path"),
        ("https://api.ats.test/{employer}/{employer}", "once"),
        # #445 second reader, E20a/c/d: `urlsplit` files each of these slots
        # under `path`, and each still decides the origin.
        ("{employer}://api.ats.test/jobs", "in the path"),
        ("{employer}.evil.example/jobs", "in the path"),
        (r"https:\\{employer}.evil.example/jobs", "in the path"),
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


def test_a_slug_with_a_trailing_newline_is_refused() -> None:
    """#445 E11b/E13b: `$` matches before a final newline; the rule says a slug
    holds only letters, digits, . _ or -."""
    with pytest.raises(ConnectorError, match="slug"):
        parse_connector(_yaml(GOOD, '  employers:\n    "acme\\n": Name\n'))
    with pytest.raises(ConnectorError, match="slug"):
        parse_connector(_yaml(GOOD, '  employers:\n    acme: A\n    "acme\\n": B\n'))


def test_a_placeholder_spliced_from_two_others_is_refused() -> None:
    """#445 E17: removing `{query}` from `{emp{query}loyer}` forms `{employer}`;
    a chain of `.replace` then removed that too and a brace shipped."""
    with pytest.raises(ConnectorError, match="placeholders"):
        parse_connector(_yaml("https://api.ats.test/{emp{query}loyer}", ""))
    with pytest.raises(ConnectorError, match="placeholders"):
        parse_connector(_yaml("https://api.ats.test/{que{page}ry}", ""))


def test_a_copied_connector_cannot_move_the_slot_where_the_validator_refused_it() -> None:
    """#445 E18: `model_copy(update=...)` skips validators, so the rules are
    asked again where URLs are built — the module's own posture (T110)."""
    connector = parse_connector(_yaml(GOOD))
    for update in (
        {"url_pattern": "https://{employer}.evil.example/jobs"},
        {"method": "POST", "body_json": {"q": "x"}},
        {"employers": {"..": "Dots"}},
        # round 2: `.match` would pass this one where `.fullmatch` refuses (M14)
        {"employers": {"acme\n": "Newline"}},
        # round 2 N6: `urlsplit` raising ValueError must reach the caller as
        # the board's ConnectorError, not end the run
        {"url_pattern": "https://[h/{employer}/jobs"},
    ):
        copied = connector.model_copy(update={"list": connector.list.model_copy(update=update)})
        with pytest.raises(ConnectorError):
            build_list_requests(copied)


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


# ---------------------------------------------------------------------------
# #445 second reader: fixtures for what the first round let through


def _ledger_with(tmp: Path, package: str, **changes: object) -> Path:
    """The real ledger, with one package's row changed — through YAML, not text."""
    import yaml

    doc = yaml.safe_load(_LEDGER.read_text(encoding="utf-8"))
    for row in doc["adjudications"]:
        if row.get("package") == f"connectors/{package}":
            row.update(changes)
            for key, value in list(row.items()):
                if value is None:
                    del row[key]
    ledger = tmp / "ledger.yaml"
    ledger.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return ledger


def test_a_row_whose_own_robots_txt_refuses_the_package_does_not_count(tmp_path: Path) -> None:
    """G1: well-formed row, and its committed file disallows the list path."""
    directory = _library(tmp_path, "lever_en")
    ledger = _ledger_with(
        tmp_path,
        "lever_en",
        robots_txt="User-agent: *\nDisallow: /v0/\n",
        allowed=None,
        standing="single_parser",
    )
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 0
    assert any("disallows" in why for why in measured["not_conforming"]["lever_en"])


def test_a_row_for_another_host_does_not_count(tmp_path: Path) -> None:
    """G2: the verdict must be about the host the package fetches."""
    directory = _library(tmp_path, "greenhouse_en")
    ledger = _ledger_with(tmp_path, "greenhouse_en", site="unrelated.example")
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 0


def test_a_row_with_nothing_to_replay_does_not_count(tmp_path: Path) -> None:
    directory = _library(tmp_path, "ashby_en")
    ledger = _ledger_with(tmp_path, "ashby_en", robots_status=None)
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 0
    assert any("nothing to replay" in why for why in measured["not_conforming"]["ashby_en"])


@pytest.mark.parametrize(
    ("status", "counts"), [(401, True), (404, True), (403, False), (500, False)]
)
def test_a_recorded_status_is_replayed_through_the_matcher(
    tmp_path: Path, status: int, counts: bool
) -> None:
    """401 and 404 are what `integral.robots` reads as no rules; anything else
    refuses, and the row saying otherwise is itself a problem."""
    directory = _library(tmp_path, "ashby_en")
    ledger = _ledger_with(tmp_path, "ashby_en", robots_status=status)
    measured = measure(directory, ledger)
    assert (measured["ats_host_connectors_conforming"] == 1) is counts


def test_lever_reads_the_requirements_the_api_keeps_apart() -> None:
    """F2: the list's `descriptionPlain` omits Lever's `lists`, where this
    advert's language requirement sits. Mapped from it, the requirement read
    as "none stated". The body now comes from the advert's own page."""
    from integral.connectors import build_offer, load_connector, parse_detail_page, parse_list_page

    package = _CONNECTORS / "lever_en"
    connector = load_connector(package)
    row = parse_list_page(connector, (package / "fixture" / "list.html").read_text())[0]
    assert "text" not in row
    detail = parse_detail_page(connector, (package / "fixture" / "detail.html").read_text())
    offer = build_offer(connector, list_fields=row, detail_fields=detail, url=row["detail_url"])
    assert "Full professional proficiency in French and English" in offer.text


def test_a_row_admitting_only_the_first_employer_does_not_count(tmp_path: Path) -> None:
    """#445 round 2, B1: the gate replayed the first list URL only, so a
    well-formed row refusing 12 of Lever's 13 employer boards still counted."""
    directory = _library(tmp_path, "lever_en")
    ledger = _ledger_with(
        tmp_path,
        "lever_en",
        robots_txt="User-agent: *\nAllow: /v0/postings/aircall\nDisallow: /v0/postings/\n",
        standing="two_parsers_agreed",
        allowed=["/v0/postings/aircall?mode=json"],
        second_reader_refused=["/v0/postings/blablacar?mode=json"],
    )
    measured = measure(directory, ledger)
    assert measured["ats_host_connectors_conforming"] == 0
    why = measured["not_conforming"]["lever_en"]
    # Every reason is the replay's — the row's own checks pass, so this case
    # reaches the code it pins rather than being refused earlier.
    assert len(why) == 12 and all("disallows" in w for w in why), why


def _three_employer_run(
    tmp_path: Path, answers: dict[str, Response], robots_txt: str | Robots
) -> Any:
    directory = _package(tmp_path)
    package = directory / "atshost_en"
    text = (package / "connector.yaml").read_text(encoding="utf-8")
    (package / "connector.yaml").write_text(
        text.replace("    beta: Beta Inc\n", "    gone: Gone Co\n    beta: Beta Inc\n"),
        encoding="utf-8",
    )
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    store = ProfileStore(tmp_path / "p", "test")
    asked: list[str] = []

    def fetch(request: ListRequest) -> Response:
        asked.append(request.url.split("/")[-2])
        return answers[asked[-1]]

    run = source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
        ),
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=directory,
        robots=robots_txt
        if isinstance(robots_txt, Robots)
        else Robots(fetch=lambda url: robots_txt),
    )
    return run, asked


def _jobs(title: str) -> Response:
    return Response(200, json.dumps({"jobs": [{"title": title, "body": f"about {title}"}]}))


def test_one_failing_employer_does_not_end_the_host(tmp_path: Path) -> None:
    """F4: each request is a different employer's board."""
    answers = {"acme": _jobs("A"), "gone": Response(404, "", error="HTTP 404"), "beta": _jobs("B")}
    run, asked = _three_employer_run(tmp_path, answers, "User-agent: *\nAllow: /\n")
    assert asked == ["acme", "gone", "beta"]
    (outcome,) = run.outcomes
    assert outcome.added == 2
    assert outcome.employers_failed == ("Gone Co (HTTP 404)",)
    assert outcome.error is None
    assert "PARTIAL atshost_en: 1 employer board(s) not read" in run.summary()
    store = ProfileStore(tmp_path / "p", "test")
    logged = [r for r in store.read_jsonl("offers", FETCH_LOG) if "/gone/" in r["url"]]
    assert [(r["status"], r["items"]) for r in logged] == [(404, 0)]


def test_an_employer_whose_path_robots_disallows_is_passed_over(tmp_path: Path) -> None:
    """Round 2 M6: a disallowed path is that employer's answer, not the host's."""
    answers = {"acme": _jobs("A"), "beta": _jobs("B")}
    run, asked = _three_employer_run(
        tmp_path, answers, "User-agent: *\nDisallow: /v1/boards/gone/\n"
    )
    assert asked == ["acme", "beta"]
    (outcome,) = run.outcomes
    assert outcome.added == 2
    assert outcome.employers_failed == ("Gone Co (robots.txt disallows it)",)


def test_an_unreadable_robots_txt_is_asked_once_per_host(tmp_path: Path) -> None:
    """Round 2 B2: RFC 9309 §2.3.1.4 — an unreachable robots.txt is complete
    disallow for the origin. It cost one fetch and one browser retry per
    employer; it is one answer for the host."""
    import urllib.error

    asked_robots: list[str] = []

    def refuse(url: str) -> str:
        asked_robots.append(url)
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)  # type: ignore[arg-type]

    robots = Robots(fetch=refuse, browser_fetch=refuse)
    run, asked = _three_employer_run(tmp_path, {}, robots)
    assert asked == []
    assert len(asked_robots) == 2  # the fetch, and T71's one browser retry
    (outcome,) = run.outcomes
    assert outcome.skipped and "could not be read" in outcome.skipped


@pytest.mark.parametrize(
    "refusal",
    [
        Response(429, "", error="HTTP 429"),
        Response(503, "", error="HTTP 503"),
        Response(403, "", error="HTTP 403"),
        Response(429, "Too Many Requests"),
    ],
)
def test_a_host_that_refuses_the_read_is_not_asked_again(tmp_path: Path, refusal: Response) -> None:
    """Round 2 B2 and N3: a 429 on one employer is not leave to ask for the
    next — and what was read before it is still counted."""
    answers = {"acme": _jobs("A"), "gone": refusal, "beta": _jobs("B")}
    run, asked = _three_employer_run(tmp_path, answers, "User-agent: *\nAllow: /\n")
    assert asked == ["acme", "gone"]
    (outcome,) = run.outcomes
    assert outcome.refused
    assert outcome.added == 1
    assert run.summary().startswith("1 offer(s) added")


def _detail_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adverts_robots: str | None
) -> tuple[Any, list[str], list[float]]:
    """Two employers, two rows each, every body on an advert host of its own."""
    import urllib.error

    import integral.sourcing as sourcing

    directory = _package(tmp_path)
    (directory / "atshost_en" / "connector.yaml").write_text(
        _yaml(GOOD, "  employers:\n    acme: Acme Corp\n    beta: Beta Inc\n").replace(
            "fields: {title: title, company: company, text: body}",
            "fields: {title: title, detail_url: url}",
        )
        + "detail:\n  fields:\n    text:\n      css: 'div.content'\n",
        encoding="utf-8",
    )
    create_profile(tmp_path / "p", "Test", handle="test", language="es", fiction=True)
    pauses: list[float] = []
    monkeypatch.setattr(sourcing, "_pause", pauses.append)
    robots_asked: list[str] = []

    def robots_fetch(url: str) -> str:
        robots_asked.append(url)
        if "adverts" not in url:
            return "User-agent: *\nAllow: /\n"
        if adverts_robots is None:
            raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)  # type: ignore[arg-type]
        return adverts_robots

    def fetch(request: ListRequest) -> Response:
        if "adverts" in request.url:
            return Response(200, "<div class='content'>the whole advert</div>")
        slug = request.url.split("/")[-2]
        rows = [
            {"title": f"{slug} {n}", "url": f"https://adverts.ats.test/{slug}/{n}"} for n in (1, 2)
        ]
        return Response(200, json.dumps({"jobs": rows}))

    run = source(
        ProfileStore(tmp_path / "p", "test"),
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True)
        ),
        Aim(state="stated", terms=("python",)),
        fetch=fetch,
        at=AT,
        directory=directory,
        robots=Robots(fetch=robots_fetch, browser_fetch=robots_fetch),
    )
    return run, robots_asked, pauses


def test_an_unreadable_advert_host_robots_txt_is_asked_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2 B2(b): Lever's bodies are on jobs.lever.co. Its robots.txt
    failing was re-fetched for every row; it is one answer for the origin."""
    run, robots_asked, _ = _detail_run(tmp_path, monkeypatch, adverts_robots=None)
    assert [u for u in robots_asked if "adverts" in u] == ["https://adverts.ats.test/robots.txt"]
    (outcome,) = run.outcomes
    assert (outcome.detail_needed, outcome.detail_fetched) == (4, 0)


def test_the_advert_host_crawl_delay_is_kept_and_a_budget_stop_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Round 2 M8 and N5: the pause before each advert page, and a row the
    detail budget did not reach reported as that, not as a connector fault."""
    import integral.sourcing as sourcing

    monkeypatch.setattr(sourcing, "DETAIL_FETCH_CEILING", 3)
    run, _, pauses = _detail_run(
        tmp_path, monkeypatch, adverts_robots="User-agent: *\nAllow: /\nCrawl-delay: 5\n"
    )
    (outcome,) = run.outcomes
    assert (outcome.added, outcome.detail_fetched) == (3, 3)
    assert pauses.count(5.0) == 3
    assert outcome.drop_reason and "budget ran out" in outcome.drop_reason


def test_every_employer_failing_is_an_error(tmp_path: Path) -> None:
    failure = Response(None, "", error="timed out")
    run, _ = _three_employer_run(
        tmp_path, dict.fromkeys(("acme", "gone", "beta"), failure), "User-agent: *\nAllow: /\n"
    )
    (outcome,) = run.outcomes
    assert outcome.error and not outcome.reached_the_board


def test_the_crawl_delay_is_kept_between_one_hosts_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F11: api.lever.co states `Crawl-delay: 1`; a host is now many requests."""
    import integral.sourcing as sourcing

    pauses: list[float] = []
    monkeypatch.setattr(sourcing, "_pause", pauses.append)
    answers = {"acme": _jobs("A"), "gone": _jobs("G"), "beta": _jobs("B")}
    _three_employer_run(tmp_path, answers, "User-agent: *\nAllow: /\nCrawl-delay: 2\n")
    assert pauses == [2.0, 2.0]
