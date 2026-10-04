"""T252 — an offer's url is the advert, never the application form.

The property is about *offers*, so the checks build offers through every
constructor and read `Offer.url` off the result; the classifier is then pinned
case by case. A test that only called `is_application_form_url` would pin the
proxy (the predicate) and stay green with the call removed from a constructor.

A Greenhouse-hosted job page (`job-boards[.eu].greenhouse.io/<co>/jobs/<id>`)
is the advert with the form embedded below it, so it is kept when the board
gives nothing better (second-reader finding B1 on #705).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import pytest

from integral.advert_link import advert_url, is_application_form_url
from integral.connectors import (
    Connector,
    build_offer,
    build_search_offer,
    load_connectors,
    parse_detail_page,
    parse_list_page,
)
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import collect_offer
from integral.offers import Offer, connect_manual
from integral.reaction_elicit import check_stimulus

ROOT = Path(__file__).resolve().parent.parent
CONNECTORS = load_connectors()

#: Floors, not counts of the day (T100): a scan that built nothing must not pass.
MINIMUM_OFFERS_BUILT = 50
MINIMUM_CONNECTORS_READ = 8
MINIMUM_CONNECTORS_NEEDING_A_DETAIL_PAGE = 5

HOSTED = "https://job-boards.greenhouse.io/anthropic/jobs/5397751008"
HOSTED_EU = "https://job-boards.eu.greenhouse.io/acme/jobs/4012345"
EMPLOYER = "https://acme.example/careers?gh_jid=4012345"


def _greenhouse() -> Connector:
    return next(c for c in CONNECTORS if c.site == "greenhouse")


def _fixture_dir(connector: Connector) -> Path:
    return ROOT / "connectors" / f"{connector.site}_{connector.locale}" / "fixture"


def _built_offers() -> tuple[list[tuple[str, str | None]], dict[str, int]]:
    """(site, Offer.url) for every offer every fixture yields, list page plus
    the package's own detail page when the row has no text of its own."""
    built: list[tuple[str, str | None]] = []
    via_detail: dict[str, int] = {}
    for connector in CONNECTORS:
        listing = _fixture_dir(connector) / "list.html"
        if not listing.exists():
            continue
        detail_page = _fixture_dir(connector) / "detail.html"
        detail = (
            parse_detail_page(connector, detail_page.read_text(encoding="utf-8"))
            if detail_page.exists()
            else {}
        )
        base = connector.list.url_pattern.replace("{page}", "1").replace("{employer}", "a0")
        for item in parse_list_page(connector, listing.read_text(encoding="utf-8")):
            raw = item.get("url") or item.get("detail_url")
            absolute = urljoin(base, raw) if raw else None
            if item.get("text"):
                offer = build_offer(connector, list_fields=item, url=absolute)
            elif detail.get("text"):
                offer = build_offer(connector, list_fields=item, detail_fields=detail, url=absolute)
                via_detail[connector.site] = via_detail.get(connector.site, 0) + 1
            else:
                continue  # no text anywhere: not an offer, and counted by the floor below
            built.append((connector.site, offer.url))
    return built, via_detail


def test_no_offer_built_from_a_committed_fixture_links_to_a_form() -> None:
    built, via_detail = _built_offers()
    assert len(built) >= MINIMUM_OFFERS_BUILT
    assert len({site for site, _ in built}) >= MINIMUM_CONNECTORS_READ
    assert len(via_detail) >= MINIMUM_CONNECTORS_NEEDING_A_DETAIL_PAGE
    assert [(s, u) for s, u in built if is_application_form_url(u)] == []


def test_every_connector_refuses_a_form_url_it_is_handed() -> None:
    # The fixtures hold no form url, so the test above never reaches the refused
    # branch; this is the population that does.
    form = "https://jobs.lever.co/acme/0ec3/apply"
    for connector in CONNECTORS:
        offer = build_offer(connector, list_fields={"text": "A job."}, url=form)
        assert offer.url != form, connector.site


@pytest.mark.parametrize(
    "url",
    [
        "https://boards.greenhouse.io/embed/job_app?for=acme&token=123",
        "https://jobs.lever.co/blablacar/0ec3b691-9abe-4365-8d1d-6733ffd68b91/apply",
        "https://jobs.ashbyhq.com/oyster/e926bced-b09b-4f2b-a3da-37b2a634ac91/application",
        "https://apply.workable.com/acme/j/ABC123/apply/",
        "https://acme.teamtailor.com/jobs/123-eng/applications/new",
        "https://acme.example/careers/applications/new",
        "HTTPS://JOBS.LEVER.CO/x/1/APPLY",
        "https://jobs.lever.co/x/1/ap%70ly",
        "https://jobs.lever.co/x/1/apply;jsessionid=1",
        f"{HOSTED_EU}/apply",
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
        "https://himalayas.app/companies/micro1/jobs/microbiologist-59050287",
        EMPLOYER,
        HOSTED,
        HOSTED_EU,
        "https://acme.example/",
        "",
        None,
    ],
)
def test_an_advert_page_is_not_taken_for_a_form(url: str | None) -> None:
    assert not is_application_form_url(url)


def test_the_hosted_greenhouse_page_is_kept_when_nothing_better_is_given() -> None:
    assert advert_url([HOSTED]) == HOSTED
    assert advert_url([HOSTED_EU]) == HOSTED_EU
    offer = build_offer(_greenhouse(), list_fields={"text": "A job."}, url=HOSTED_EU)
    assert offer.url == HOSTED_EU


def test_the_employers_own_advert_is_preferred_over_the_form() -> None:
    form = "https://boards.greenhouse.io/embed/job_app?token=4012345"
    assert advert_url([form, EMPLOYER]) == EMPLOYER
    assert advert_url([EMPLOYER, form]) == EMPLOYER


def test_a_form_fragment_is_dropped_from_an_advert_page() -> None:
    assert advert_url([f"{HOSTED_EU}#app"]) == HOSTED_EU
    assert advert_url([f"{HOSTED_EU}?gh_src=x#application"]) == f"{HOSTED_EU}?gh_src=x"
    assert advert_url([f"{HOSTED_EU}#details"]) == f"{HOSTED_EU}#details"


@pytest.mark.parametrize(
    ("form", "advert"),
    [
        ("https://jobs.lever.co/blablacar/0ec3/apply", "https://jobs.lever.co/blablacar/0ec3"),
        (
            "https://jobs.ashbyhq.com/oyster/e926/application?utm=x",
            "https://jobs.ashbyhq.com/oyster/e926",
        ),
        ("https://apply.workable.com/acme/j/ABC/apply/", "https://apply.workable.com/acme/j/ABC"),
        (
            "https://acme.teamtailor.com/jobs/123-eng/applications/new",
            "https://acme.teamtailor.com/jobs/123-eng",
        ),
    ],
)
def test_a_form_on_a_known_ats_host_is_rewritten_to_its_advert(form: str, advert: str) -> None:
    assert advert_url([form]) == advert


def test_a_form_on_an_unknown_host_is_not_rewritten_to_its_parent_path() -> None:
    # `/careers/apply` on a company site: the parent may be a careers index.
    assert advert_url(["https://acme.example/careers/apply"]) is None
    assert advert_url(["https://acme.example/products/application"]) is None
    assert advert_url(["https://boards.greenhouse.io/embed/job_app?token=1"]) is None
    assert advert_url([None, ""]) is None


# --- the other constructors: a form url arriving by search or paste ----------


@pytest.mark.parametrize(
    "arriving",
    [f"{HOSTED_EU}/apply", f"{HOSTED_EU}#app", "https://jobs.lever.co/acme/0ec3/apply"],
)
def test_a_search_hit_that_is_the_form_does_not_keep_it_as_the_advert(arriving: str) -> None:
    offer = build_search_offer(text="A job.", url=arriving)
    assert not is_application_form_url(offer.url)
    assert offer.url != arriving


def test_a_search_hit_that_is_the_advert_keeps_its_url() -> None:
    assert build_search_offer(text="A job.", url=HOSTED_EU).url == HOSTED_EU
    assert build_search_offer(text="A job.", url=None).url is None


def test_a_pasted_form_url_does_not_become_the_advert() -> None:
    assert connect_manual("A job.", url=f"{HOSTED_EU}#app").url == HOSTED_EU
    assert connect_manual("A job.", url="https://acme.example/careers/apply").url is None


# --- what dropping the hosted link would have broken (B1) --------------------


def _greenhouse_offer(text: str) -> Offer:
    return build_offer(
        _greenhouse(),
        list_fields={"text": text, "title": "Engineer", "company": "Anthropic"},
        url=HOSTED,
    )


def test_a_second_copy_of_a_greenhouse_offer_is_still_caught_as_a_duplicate(
    tmp_path: Path,
) -> None:
    create_profile(tmp_path, "Fixture", handle="fixture", language="en", fiction=True)
    store = ProfileStore(tmp_path, "fixture")
    at = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    first = collect_offer(store, _greenhouse_offer("A job, first wording."), at=at)
    second = collect_offer(store, _greenhouse_offer("A job, reworded between searches."), at=at)
    assert first.added_as_new
    assert not second.added_as_new
    assert second.duplicate_of == first.offer_id


def test_a_greenhouse_offer_is_still_a_permitted_live_stimulus() -> None:
    offer = _greenhouse_offer("A job.").model_copy(update={"fetched_at": "2026-01-01T00:00:00Z"})
    check_stimulus(offer)
