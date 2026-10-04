"""T234 — a selector built on a build hash, and a detail page that matches nothing.

`connectors/talent_es` read the advert body with `div.sc-f4dbceab-10`, a
styled-components class. A live page (2026-10-02) answered 200 with zero
elements carrying it, and nothing said so: the row was `dropped` for "no text",
which is also what an advert with no body looks like. Two halves, both pinned
against behaviour:

* the connector format refuses a build-generated class in `list:` / `detail:`
  unless the selector says why (`build_hash_accepted`);
* a 200 detail page that yields no text is counted per board
  (`BoardOutcome.empty_detail`) and printed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from integral.connector_coverage import installed_packages
from integral.connectors import (
    ConnectorError,
    ListRequest,
    generated_classes,
    load_connector,
)
from integral.identity import ProfileStore, create_profile
from integral.robots import Robots
from integral.sourcing import BoardOutcome, Response, Run, _one_board

_ROOT = Path(__file__).resolve().parents[1]
_CONNECTORS = _ROOT / "connectors"
_AT = "2026-01-01T00:00:00+00:00"
_ALLOW = "User-agent: *\nAllow: /\n"
_EMPTY_PAGE = "<html><body><p>nothing here</p></body></html>"


@pytest.fixture
def store(tmp_path: Path) -> ProfileStore:
    create_profile(tmp_path, "Test", handle="test", language="es", fiction=True)
    return ProfileStore(tmp_path, "test")


# ---------------------------------------------------------------------------
# the connector format


def _package_with(tmp_path: Path, edit: Any) -> Path:
    """The committed talent_es package with its `connector.yaml` passed through
    `edit` — the real file with one thing changed, never a look-alike."""
    source = _CONNECTORS / "talent_es" / "connector.yaml"
    target = tmp_path / "talent_es"
    target.mkdir()
    (target / "connector.yaml").write_text(edit(source.read_text(encoding="utf-8")), "utf-8")
    return target


def _without_acceptance(text: str, selector: str) -> str:
    """Drop the `build_hash_accepted` line that follows `selector`."""
    lines = text.splitlines(keepends=True)
    index = next(i for i, line in enumerate(lines) if selector in line)
    assert "build_hash_accepted" in lines[index + 1], "the committed file moved"
    del lines[index + 1]
    return "".join(lines)


def test_the_committed_talent_package_loads_with_its_stated_exceptions() -> None:
    connector = load_connector(_CONNECTORS / "talent_es")
    assert connector.detail is not None
    text = connector.detail.fields["text"]
    assert generated_classes(text.css) == ("sc-f4dbceab-10",)
    assert text.build_hash_accepted


def test_a_detail_selector_on_a_styled_components_class_is_refused(tmp_path: Path) -> None:
    package = _package_with(tmp_path, lambda t: _without_acceptance(t, 'css: "div.sc-f4dbceab-10"'))
    with pytest.raises(ConnectorError, match=r"detail selector.*sc-f4dbceab-10"):
        load_connector(package)


def test_a_list_selector_on_a_css_module_class_is_refused(tmp_path: Path) -> None:
    package = _package_with(
        tmp_path, lambda t: _without_acceptance(t, 'css: "span.JobCard_company__NmRol"')
    )
    with pytest.raises(ConnectorError, match=r"list selector.*JobCard_company__NmRol"):
        load_connector(package)


def test_an_accepted_hash_needs_a_reason_not_a_blank(tmp_path: Path) -> None:
    package = _package_with(
        tmp_path,
        lambda t: t.replace(
            'build_hash_accepted: "see company: the CSS-module hash is the only thing that '
            'distinguishes this span"',
            'build_hash_accepted: "  "',
        ),
    )
    with pytest.raises(ConnectorError, match="must say why"):
        load_connector(package)


def test_a_tag_a_data_attribute_and_a_plain_class_are_not_generated_classes() -> None:
    for css in (
        "h2",
        'article[data-testid="job-card-unified"]',
        "div.job-description",
        "span.salary_range",
        "div.styles_jobDescription",
    ):
        assert generated_classes(css) == (), css


def test_every_generated_class_selector_in_the_library_states_its_reason() -> None:
    """Derived from what loads, not from a list of names: every installed package
    loads (so none carries an unexplained hash) and the exceptions that exist are
    all explained. The denominator proves the scan reached the exceptions."""
    packages = installed_packages(_CONNECTORS)
    assert len(packages) >= 20
    accepted = 0
    for package in packages:
        connector = load_connector(_CONNECTORS / package.name)
        sections = [connector.list.fields]
        if connector.detail is not None:
            sections.append(connector.detail.fields)
        for fields in sections:
            for selector in fields.values():
                if generated_classes(selector.css):
                    assert selector.build_hash_accepted, (package.name, selector.css)
                    accepted += 1
    assert accepted >= 3, "talent_es's three stated exceptions were not reached"


# ---------------------------------------------------------------------------
# a 200 detail page that yields no text is counted per board


def _fetch_for(package: str, detail_html: str | None, seen: list[str] | None = None) -> Any:
    """List from the package's own `list.html`; every other URL is its advert page,
    answered 200 with `detail_html` (the committed `detail.html` when None)."""
    directory = _CONNECTORS / package
    listing = (directory / "fixture" / "list.html").read_text(encoding="utf-8")
    committed = (directory / "fixture" / "detail.html").read_text(encoding="utf-8")
    connector = load_connector(directory)
    list_path = urlsplit(connector.list.url_pattern).path

    def answer(request: ListRequest) -> Response:
        if urlsplit(request.url).path == list_path:
            return Response(200, listing, error=None)
        if seen is not None:
            seen.append(request.url)
        return Response(200, committed if detail_html is None else detail_html, error=None)

    return answer


def _outcome(store: ProfileStore, package: str, detail_html: str | None) -> BoardOutcome:
    seen: list[str] = []
    found = next(p for p in installed_packages(_CONNECTORS) if p.name == package)
    outcome = _one_board(
        store,
        found,
        "python",
        fetch=_fetch_for(package, detail_html, seen),
        at=_AT,
        directory=_CONNECTORS,
        page_count=1,
        robots=Robots(fetch=lambda url: _ALLOW),
        phrases=("python",),
    )
    assert seen, f"{package}: no advert page was fetched, so this proves nothing"
    assert outcome.detail_fetched == len(seen), outcome
    return outcome


def _talent_detail_with_the_class_rotated() -> str:
    """The committed advert page as the live one now is: the class the selector
    names is gone. The one thing changed is the build hash."""
    committed = (_CONNECTORS / "talent_es" / "fixture" / "detail.html").read_text("utf-8")
    assert committed.count("sc-f4dbceab-10") >= 2, "the committed fixture moved"
    return committed.replace("sc-f4dbceab-10", "sc-126c3eb4-10")


def test_a_200_page_whose_selector_matches_nothing_is_counted(store: ProfileStore) -> None:
    rotated = _outcome(store, "talent_es", _talent_detail_with_the_class_rotated())
    assert rotated.detail_fetched >= 1
    assert rotated.empty_detail == rotated.detail_fetched, rotated
    # The row is lost either way; `empty_detail` is what says *why*.
    assert rotated.added == 0 and rotated.dropped >= rotated.empty_detail, rotated


def test_a_detail_page_with_text_is_not_counted(store: ProfileStore) -> None:
    healthy = _outcome(store, "talent_es", None)
    assert healthy.added >= 1, healthy
    assert healthy.empty_detail == 0, healthy


def test_the_count_is_per_board(store: ProfileStore) -> None:
    """Two boards in one run, one served an empty page and one its real advert:
    the count lands on the first alone, and the summary names that board only."""
    rotated = _outcome(store, "talent_es", _EMPTY_PAGE)
    other = _outcome(store, "trabajos_es", None)
    assert other.detail_fetched >= 1 and other.added >= 1, other
    assert (rotated.empty_detail, other.empty_detail) == (rotated.detail_fetched, 0)
    summary = Run(outcomes=[rotated, other]).summary()
    assert f"EMPTY DETAIL talent_es: {rotated.empty_detail} advert page(s)" in summary
    assert "EMPTY DETAIL trabajos_es" not in summary


def test_the_summary_is_silent_when_nothing_came_back_empty(store: ProfileStore) -> None:
    summary = Run(outcomes=[_outcome(store, "talent_es", None)]).summary()
    assert "EMPTY DETAIL" not in summary


def test_an_empty_detail_row_is_not_counted_twice_as_unrealized(store: ProfileStore) -> None:
    """`empty_detail` is a subset of `dropped`; summing both would count a row
    twice and make `items - unrealized` go negative."""
    from integral.sourcing import _unrealized_rows

    outcome = _outcome(store, "talent_es", _EMPTY_PAGE)
    assert outcome.empty_detail
    assert _unrealized_rows(outcome) <= outcome.items, outcome
