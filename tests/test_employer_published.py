"""T236 — an offer with no employer is counted, and a connector may only yield one on purpose.

Measured on one candidate's store: tecnoempleo 101 of 349 offers with an empty
`company`, pythonorg 8 of 16, foorilla 527 of 527. Nothing counted them, a card
was built from each with a blank employer, and every employer-keyed decision
skipped every one. The rule is closed over the connector library rather than
patched per board: `CONNECTORS` is every committed package, so a connector
added later is held to it without anyone remembering to list it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from integral.candidate import Aim, CandidateConstraints, Location, Reach
from integral.connectors import (
    Connector,
    ConnectorError,
    load_connectors,
    parse_connector,
    parse_detail_page,
    parse_list_page,
)
from integral.identity import ProfileStore, create_profile
from integral.offers import load_offer, names_an_employer
from integral.robots import Robots
from integral.sourcing import BoardOutcome, Response, Run, flood_board, source
from integral.sourcing_exclusions import Candidate, Exclusion, matches

ROOT = Path(__file__).resolve().parents[1]
CONNECTORS = sorted(load_connectors(ROOT / "connectors"), key=lambda c: c.site)
SITES = [c.site for c in CONNECTORS]
AT = "2026-01-01T00:00:00+00:00"

#: Floors, never counts of the day (T100): each stops the rule resting on an
#: empty population. The connector floor is the library's size, the row floor
#: the fixtures' rows, and the last two keep BOTH sides of the rule alive — a
#: library with no connector that yields an employer, or none that declares
#: its omission, would pass the parametrised checks below vacuously.
MINIMUM_CONNECTORS = 25
MINIMUM_ROWS = 100
MINIMUM_CONNECTORS_NAMING_AN_EMPLOYER = 15
MINIMUM_DECLARED = 1
MINIMUM_GAPS = 1


def _directory(connector: Connector) -> Path:
    return ROOT / "connectors" / f"{connector.site}_{connector.locale}"


def _list_supplies_text(connector: Connector) -> bool:
    page = connector.list
    return "text" in page.fields or (page.from_json is not None and "text" in page.from_json.fields)


def fixture_rows_without_employer(connector: Connector) -> tuple[int, int]:
    """`(rows, rows with no employer)` in this connector's own list fixture.

    The employer a row ends with is what sourcing would give it: its own
    `company`; failing that the `{employer}` the request named (an ATS board
    is the employer's, `_one_board`); failing that the detail page's, but only
    for a row the list cannot complete on its own, because that is the only
    row the detail page is fetched for. Derived from the connector's own
    declarations, never from a list of boards.
    """
    directory = _directory(connector) / "fixture"
    rows = parse_list_page(connector, (directory / "list.html").read_text(encoding="utf-8"))
    # `_one_board` fills a blank company from the request's employer, and only
    # a blank one: a row that names its own employer never needed the slot.
    slot = "{employer}" in connector.list.url_pattern
    detail_company = None
    detail = directory / "detail.html"
    if detail.exists() and connector.detail is not None and not _list_supplies_text(connector):
        detail_company = parse_detail_page(connector, detail.read_text(encoding="utf-8")).get(
            "company"
        )
    empty = [
        row
        for row in rows
        if not names_an_employer(row.get("company"))
        and not slot
        and not names_an_employer(detail_company)
    ]
    return len(rows), len(empty)


def test_the_library_is_large_enough_for_the_rule_to_mean_something() -> None:
    measured = [fixture_rows_without_employer(c) for c in CONNECTORS]
    assert len(CONNECTORS) >= MINIMUM_CONNECTORS
    assert sum(rows for rows, _ in measured) >= MINIMUM_ROWS
    assert sum(1 for _, empty in measured if empty == 0) >= MINIMUM_CONNECTORS_NAMING_AN_EMPLOYER
    assert sum(1 for c in CONNECTORS if c.employer_unpublished) >= MINIMUM_DECLARED
    assert sum(1 for c in CONNECTORS if c.employer_gap) >= MINIMUM_GAPS


@pytest.mark.parametrize("site", SITES)
def test_a_connector_whose_fixture_yields_no_employer_declares_it(site: str) -> None:
    connector = next(c for c in CONNECTORS if c.site == site)
    rows, empty = fixture_rows_without_employer(connector)
    assert rows, f"{site}: its list fixture parsed no rows, so nothing was checked"
    if empty:
        assert connector.employer_unpublished or connector.employer_gap, (
            f"{site}: {empty} of {rows} fixture rows yield no `company` and connector.yaml "
            "declares neither `employer_unpublished` (the board omits it) nor `employer_gap` "
            "(it names it and the connector does not read it) — fix the selector or declare"
        )


@pytest.mark.parametrize("site", SITES)
def test_a_declaration_is_not_kept_after_its_cause_is_gone(site: str) -> None:
    """The other direction: an exemption nothing needs is the check switched off
    for a board that now publishes an employer, and it would stay off."""
    connector = next(c for c in CONNECTORS if c.site == site)
    if connector.employer_unpublished or connector.employer_gap:
        _, empty = fixture_rows_without_employer(connector)
        assert empty, f"{site}: declares a missing employer but its fixture yields employers"


@pytest.mark.parametrize("site", SITES)
def test_a_gap_names_a_task_that_is_still_open(site: str) -> None:
    """A gap is a debt, not an exemption: it ends when its task merges. The plan's
    row for the task is what says whether it has."""
    connector = next(c for c in CONNECTORS if c.site == site)
    if connector.employer_gap:
        plan = (ROOT / "status" / "plan.md").read_text(encoding="utf-8")
        row = next(
            (
                line
                for line in plan.splitlines()
                if line.startswith(f"| {connector.employer_gap} |")
            ),
            None,
        )
        assert row is not None, f"{site}: {connector.employer_gap} is not a task on the plan"
        assert row.rstrip().endswith("☐ |"), (
            f"{site}: {connector.employer_gap} is no longer open — read the employer and drop "
            "`employer_gap`"
        )


@pytest.mark.parametrize("task", ["", "t235", "T235 ", "T", "T-1", "T235 owns it", "235"])
def test_a_gap_that_names_no_task_is_refused(task: str) -> None:
    text = (ROOT / "connectors" / "foorilla_en" / "connector.yaml").read_text(encoding="utf-8")
    assert parse_connector(text).employer_gap == "T235"
    broken = text.replace('employer_gap: "T235"', f'employer_gap: "{task}"', 1)
    with pytest.raises(ConnectorError, match="employer_gap"):
        parse_connector(broken)


def test_a_board_cannot_both_omit_the_employer_and_miss_a_selector() -> None:
    text = (ROOT / "connectors" / "foorilla_en" / "connector.yaml").read_text(encoding="utf-8")
    both = text.replace(
        'employer_gap: "T235"', 'employer_gap: "T235"\nemployer_unpublished: "x"', 1
    )
    with pytest.raises(ConnectorError, match="exclusive"):
        parse_connector(both)


def test_a_blank_reason_is_not_a_declaration() -> None:
    text = (ROOT / "connectors" / "tecnoempleo_es" / "connector.yaml").read_text(encoding="utf-8")
    assert parse_connector(text).employer_unpublished
    kept = [line for line in text.splitlines() if not line.startswith("employer_unpublished:")]
    blank = "\n".join(kept).replace("\nauth:", '\nemployer_unpublished: "  "\nauth:', 1)
    with pytest.raises(ConnectorError, match="employer_unpublished"):
        parse_connector(blank)


# --- the count at sourcing -------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


def _card(i: int, company_html: str) -> str:
    title = f"Python Engineer {i}"
    return (
        f'<div class="job"><a href="/jobs/{i}">{title}</a><span class="title">{title}</span>'
        f"{company_html}"
        f'<span class="text">Advert {i}: {title}, fully remote.</span></div>'
    )


_ROWS = (
    '<span class="company">Acme</span>',
    '<span class="company"></span>',
    "",  # no company element at all
    '<span class="company">   </span>',
)


def _run(
    store: ProfileStore, tmp_path: Path, declare: str | None = None, gap: str | None = None
) -> list[BoardOutcome]:
    directory = tmp_path / "connectors"
    pages = flood_board(directory, rows=1)
    if declare is not None:
        path = directory / "flood_en" / "connector.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "\nauth:", f'\nemployer_unpublished: "{declare}"\nauth:', 1
            ),
            encoding="utf-8",
        )
    if gap is not None:
        path = directory / "flood_en" / "connector.yaml"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "\nauth:", f'\nemployer_gap: "{gap}"\nauth:', 1
            ),
            encoding="utf-8",
        )
    body = "".join(_card(i, html) for i, html in enumerate(_ROWS))
    served = {url: f"<html><body>{body}</body></html>" for url in pages}
    run = source(
        store,
        CandidateConstraints(
            location=Location(state="stated", country="ES", accepts_onsite_in_country=True),
            reach=Reach(state="stated", modes=("remote",)),
        ),
        Aim(state="stated", terms=("python engineer",)),
        fetch=lambda request: Response(200, served[request.url]),
        at=AT,
        directory=directory,
        page_count=1,
        robots=Robots(fetch=lambda url: "User-agent: *\nAllow: /\n"),
    )
    stored = [
        load_offer(store, p.stem)
        for p in Path(store.path("offers")).glob("*.json")
        if not p.name.startswith("_")
    ]
    # The population is the stored offers, so a count that agrees with it is
    # measured against the property, not against the row count it was built from.
    assert len(stored) == len(_ROWS)
    assert sum(1 for o in stored if not names_an_employer(o.company)) == 3
    return run.outcomes


def _summary(
    store: ProfileStore, tmp_path: Path, declare: str | None = None, gap: str | None = None
) -> str:
    return Run(outcomes=_run(store, tmp_path, declare, gap)).summary()


def test_offers_with_no_employer_are_counted_per_board(store: ProfileStore, tmp_path: Path) -> None:
    (outcome,) = _run(store, tmp_path)
    assert outcome.no_employer == 3
    assert outcome.added == len(_ROWS)


def test_an_undeclared_count_is_reported_as_a_fault(store: ProfileStore, tmp_path: Path) -> None:
    text = _summary(store, tmp_path)
    assert "NO EMPLOYER flood_en: 3 of 4" in text
    assert "UNDECLARED" in text


def test_a_declared_count_is_reported_with_the_boards_reason(
    store: ProfileStore, tmp_path: Path
) -> None:
    text = _summary(store, tmp_path, declare="anonymous postings")
    assert "NO EMPLOYER flood_en: 3 of 4" in text
    assert "anonymous postings" in text
    assert "UNDECLARED" not in text


def test_a_gap_is_reported_as_a_connector_fault_never_as_an_omission(
    store: ProfileStore, tmp_path: Path
) -> None:
    text = _summary(store, tmp_path, gap="T235")
    assert "NO EMPLOYER flood_en: 3 of 4" in text
    assert "CONNECTOR FAULT" in text
    assert "T235 owns the fix" in text
    assert "does not publish" not in text
    assert "UNDECLARED" not in text


# --- a blank employer never matches ---------------------------------------


@pytest.mark.parametrize(
    ("company", "names"),
    [(None, False), ("", False), (" ", False), ("\t\n", False), ("Acme", True), (" Acme ", True)],
)
def test_what_names_an_employer(company: str | None, names: bool) -> None:
    assert names_an_employer(company) is names


@pytest.mark.parametrize("employer", [None, "", "   ", chr(0xA0)])
def test_a_blank_employer_trips_no_exclusion(employer: str | None) -> None:
    """The employer is one of the three things a topic is matched against. A
    blank one must contribute nothing — never a match, never a crash — so an
    exclusion is decided by the title and the text alone."""
    exclusion = Exclusion(about="sector:banca", stated_at_cycle=1, words="banca no")
    unrelated = Candidate(offer_id="a", title="Data engineer", text="Pipelines.", employer=employer)
    related = Candidate(
        offer_id="b", title="Data engineer", text="Para un banco.", employer=employer
    )
    assert not matches(unrelated, exclusion)
    assert matches(related, exclusion)


# --- the one definition agrees with the one that links copies (T225) -------


def _names_over_every_code_point() -> list[str]:
    import sys

    return [
        shaped
        for cp in range(sys.maxunicode + 1)
        if not 0xD800 <= cp <= 0xDFFF
        for shaped in (chr(cp), f" {chr(cp)} ", f"{chr(cp)}x")
    ]


def test_an_empty_company_links_nothing_and_names_nobody() -> None:
    """`posting_key` joins copies by employer and title; a company that
    `names_an_employer` refuses must give no key, so it can never join two
    adverts, and one it accepts must give one. Every code point, alone, padded
    with spaces and followed by a letter — not a sample of spellings, so a
    character class nobody thought of is still compared."""
    from integral.lifecycle import posting_key

    disagreements = [
        f"U+{ord(name.strip()[0]) if name.strip() else ord(name[0]):04X}"
        for name in _names_over_every_code_point()
        if (posting_key("Backend engineer", name) is not None) is not names_an_employer(name)
    ]
    assert not disagreements, disagreements[:10]
    # The two ends are populated, so the loop is not agreeing about nothing.
    assert names_an_employer("Acme")
    assert not names_an_employer(chr(0x200B))
    assert not names_an_employer(None)


def test_pythonorg_reads_the_employer_and_only_the_employer() -> None:
    """A non-empty `company` is not the right one: the enclosing span's whole
    text ("New Python developer Eleks") passes the empty-row rule and is wrong.
    The expected names are read off `fixture/list.html` — the loose text after
    each `<br/>` — not produced by the connector."""
    connector = next(c for c in CONNECTORS if c.site == "pythonorg")
    html = (_directory(connector) / "fixture" / "list.html").read_text(encoding="utf-8")
    rows = parse_list_page(connector, html)
    assert [row["company"] for row in rows] == [
        "Eleks",
        "NordVpn/NordSecurity",
        "Softech Associate",
    ]
    assert connector.employer_unpublished is None and connector.employer_gap is None
