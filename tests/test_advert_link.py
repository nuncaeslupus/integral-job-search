"""T252 — an offer's url is the advert, never the application form.

The property is about *offers*, so the main check builds every offer every
committed connector fixture yields and reads `Offer.url` off the result; the
classifier is then pinned case by case. A test that only called
`is_application_form_url` would pin the proxy (the predicate) and stay green
with the call removed from `build_offer`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin

import pytest

from integral.advert_link import advert_url, is_application_form_url
from integral.connectors import build_offer, load_connectors, parse_list_page

ROOT = Path(__file__).resolve().parent.parent
CONNECTORS = load_connectors()

#: Floors, not counts of the day (T100): a scan that built nothing must not pass.
MINIMUM_OFFERS_BUILT = 50
MINIMUM_CONNECTORS_READ = 8


def _built_offers() -> list[tuple[str, str, str | None]]:
    """(site, the url the row carried, the url the Offer ended up with)."""
    built = []
    for connector in CONNECTORS:
        path = (
            ROOT / "connectors" / f"{connector.site}_{connector.locale}" / "fixture" / "list.html"
        )
        if not path.exists():
            continue
        base = connector.list.url_pattern.replace("{page}", "1").replace("{employer}", "a0")
        for item in parse_list_page(connector, path.read_text(encoding="utf-8")):
            raw = item.get("url") or item.get("detail_url")
            absolute = urljoin(base, raw) if raw else None
            try:
                offer = build_offer(connector, list_fields=item, url=absolute)
            except Exception:  # a row that is not an offer is not this test's subject
                continue
            built.append((connector.site, absolute or "", offer.url))
    return built


def test_no_offer_built_from_a_committed_fixture_links_to_a_form() -> None:
    built = _built_offers()
    assert len(built) >= MINIMUM_OFFERS_BUILT
    assert len({site for site, _, _ in built}) >= MINIMUM_CONNECTORS_READ
    forms = [(site, url) for site, _, url in built if is_application_form_url(url)]
    assert forms == []


def test_the_fixtures_actually_contain_a_form_link_for_the_check_above_to_refuse() -> None:
    # Without this the test above could pass over a library that never offered
    # a form link: it shows the input population reaches the refused branch.
    raw_forms = [(s, u) for s, u, _ in _built_offers() if is_application_form_url(u)]
    assert any(site == "greenhouse" for site, _ in raw_forms)


@pytest.mark.parametrize(
    "url",
    [
        "https://job-boards.eu.greenhouse.io/acme/jobs/4012345",  # the reported case
        "https://job-boards.greenhouse.io/anthropic/jobs/5397751008",
        "https://boards.greenhouse.io/embed/job_app?for=acme&token=123",
        "https://jobs.lever.co/blablacar/0ec3b691-9abe-4365-8d1d-6733ffd68b91/apply",
        "https://jobs.ashbyhq.com/oyster/e926bced-b09b-4f2b-a3da-37b2a634ac91/application",
        "https://apply.workable.com/acme/j/ABC123/apply/",
        "https://acme.example/careers/applications/new",
        "HTTPS://JOBS.LEVER.CO/x/1/APPLY",
    ],
)
def test_a_form_page_is_recognised(url: str) -> None:
    assert is_application_form_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://acme.example/careers/jobs/application-engineer-4411",
        "https://acme.example/jobs/apply-ml-4411",
        "https://jobs.lever.co/blablacar/0ec3b691-9abe-4365-8d1d-6733ffd68b91",
        "https://jobs.ashbyhq.com/oyster/e926bced-b09b-4f2b-a3da-37b2a634ac91",
        "https://himalayas.app/companies/micro1/jobs/microbiologist-59050287",
        "https://acme.example/careers?gh_jid=5397751008",
        "https://acme.example/",
        "",
        None,
    ],
)
def test_an_advert_page_is_not_taken_for_a_form(url: str | None) -> None:
    assert not is_application_form_url(url)


def test_the_employers_own_advert_is_preferred_over_the_form() -> None:
    form = "https://job-boards.eu.greenhouse.io/acme/jobs/4012345"
    employer = "https://acme.example/careers?gh_jid=4012345"
    assert advert_url([form, employer]) == employer
    assert advert_url([employer, form]) == employer


def test_a_form_whose_advert_is_the_same_path_without_the_form_is_rewritten() -> None:
    assert (
        advert_url(["https://jobs.lever.co/blablacar/0ec3/apply"])
        == "https://jobs.lever.co/blablacar/0ec3"
    )
    assert (
        advert_url(["https://jobs.ashbyhq.com/oyster/e926/application?utm=x"])
        == "https://jobs.ashbyhq.com/oyster/e926"
    )


def test_a_form_with_no_known_advert_gives_no_link_rather_than_the_form() -> None:
    assert advert_url(["https://job-boards.eu.greenhouse.io/acme/jobs/4012345"]) is None
    assert advert_url([None, ""]) is None


def test_build_offer_applies_it_to_every_connector() -> None:
    connector = next(c for c in CONNECTORS if c.site == "greenhouse")
    form = "https://job-boards.eu.greenhouse.io/acme/jobs/4012345"
    offer = build_offer(connector, list_fields={"text": "A job."}, url=form)
    assert offer.url is None
    employer = "https://acme.example/careers?gh_jid=4012345"
    assert build_offer(connector, list_fields={"text": "A job."}, url=employer).url == employer
