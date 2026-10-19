"""Issue #875 — fetch the employer's posting when an aggregator copy has one. No network."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral.canonical_ad import (
    CanonicalResult,
    Response,
    load_result,
    primary_offer,
    resolve_canonical,
)
from integral.employer_brief import record_brief
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import save_lifecycle_offer, track_new_offer
from integral.offers import connect_manual, load_offer
from integral.robots import Robots

URL = "https://careers.real.example/jobs/42"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
AT = "2026-10-19T09:00:00Z"


def _page(posting: Mapping[str, object] | None, extra: str = "") -> str:
    ld = f'<script type="application/ld+json">{json.dumps(posting)}</script>' if posting else ""
    return (
        f"<html><head><title>Backend</title>{ld}</head><body><h1>Backend</h1>{extra}</body></html>"
    )


POSTING: dict[str, object] = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Backend Engineer",
    "description": "<p>Build logistics APIs.</p><ul><li>5 years Python</li></ul>",
    "hiringOrganization": {"@type": "Organization", "name": "Real SL"},
    "jobLocation": {
        "@type": "Place",
        "address": {"addressLocality": "Barcelona", "addressCountry": "ES"},
    },
    "baseSalary": {
        "@type": "MonetaryAmount",
        "currency": "EUR",
        "value": {"minValue": 50000, "maxValue": 60000, "unitText": "YEAR"},
    },
}


def _robots(text: str = "User-agent: *\nAllow: /\n") -> Robots:
    return Robots(fetch=lambda _url: text, retry_delays=(), sleep=lambda _s: None)


def _setup(tmp_path: Path, url: str | None = URL) -> tuple[ProfileStore, str]:
    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    store = ProfileStore(tmp_path, identity.handle)
    offer = connect_manual("Backend en Barcelona.", title="Backend", company="Aggregator")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=AT))
    record_brief(
        store,
        offer.id,
        real_employer="Real SL",
        resolved_via="apply_link",
        live_at_source="unknown",
        checked_at="2026-10-19T08:00:00Z",
        what_they_do="logistics software",
        sector="logistics",
        pay="not published",
        hires_in_candidate_country="true",
        source_posting_url=url,
    )
    return store, offer.id


def _run(
    store: ProfileStore,
    offer_id: str,
    response: Response | Exception,
    robots: Robots | None = None,
    sleeps: list[float] | None = None,
) -> tuple[CanonicalResult, list[str]]:
    calls: list[str] = []

    def fetch(url: str) -> Response:
        calls.append(url)
        if isinstance(response, Exception):
            raise response
        return response

    result = resolve_canonical(
        store,
        offer_id,
        fetch=fetch,
        robots=robots or _robots(),
        sleep=(sleeps.append if sleeps is not None else (lambda _s: None)),
        now=NOW,
    )
    return result, calls


def test_live_employer_page_becomes_primary_and_aggregator_is_provenance(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert calls == [URL]
    assert result.outcome == "canonical" and result.canonical_id
    employer = primary_offer(store, agg_id)
    assert employer.id == result.canonical_id != agg_id
    assert employer.source_kind == "employer" and employer.url == URL
    assert employer.company == "Real SL"
    assert "5 years Python" in employer.text and "<p>" not in employer.text
    # the aggregator copy is kept, pointing at the employer one
    assert load_offer(store, agg_id).duplicate_of == employer.id
    record = load_result(store, agg_id)
    assert record and record["aggregator_offer_id"] == agg_id and record["reason"] is None


def test_employer_only_fields_reach_the_primary_offer(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    assert load_offer(store, agg_id).salary is None
    _run(store, agg_id, Response(200, _page(POSTING), URL))
    employer = primary_offer(store, agg_id)
    assert employer.salary is not None
    assert (employer.salary.min, employer.salary.max) == (50000.0, 60000.0)
    assert employer.salary.currency == "EUR" and employer.salary.period == "year"
    assert employer.location is not None and employer.location.raw == "Barcelona, ES"


def test_missing_employer_fields_are_filled_from_the_aggregator(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    bare = {"@type": "JobPosting", "description": "Plain description of the role."}
    _run(store, agg_id, Response(200, _page(bare), URL))
    employer = primary_offer(store, agg_id)
    assert employer.id != agg_id
    assert employer.title == "Backend" and employer.company == "Aggregator"


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (Response(404, None, URL), "gone"),
        (Response(410, None, URL), "gone"),
        (Response(200, _page(POSTING, "<p>This job is no longer available</p>"), URL), "closed"),
        (
            Response(200, _page({**POSTING, "validThrough": "2026-10-01T00:00:00Z"}), URL),
            "closed",
        ),
        (Response(200, _page(None), URL), "parse_failure"),
        (Response(200, _page({"@type": "JobPosting"}), URL), "parse_failure"),
        (Response(403, None, URL), "not_confirmed_live"),
        (Response(200, _page(POSTING), "https://careers.real.example/jobs"), "not_confirmed_live"),
        (OSError("connection reset"), "fetch_error"),
    ],
)
def test_fallback_keeps_the_aggregator_copy_and_records_why(
    tmp_path: Path, response: Response | Exception, reason: str
) -> None:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(store, agg_id, response)
    assert result.outcome == "fallback" and result.reason == reason
    assert primary_offer(store, agg_id).id == agg_id
    assert load_offer(store, agg_id).duplicate_of is None
    record = load_result(store, agg_id)
    assert record and record["reason"] == reason and record["canonical_offer_id"] is None


def test_robots_refusal_never_fetches(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    robots = _robots("User-agent: *\nDisallow: /jobs\n")
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL), robots)
    assert calls == []
    assert result.reason == "robots_refused" and primary_offer(store, agg_id).id == agg_id


def test_unreadable_robots_is_a_refusal(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)

    def broken(_url: str) -> str:
        raise OSError("down")

    robots = Robots(fetch=broken, retry_delays=(), sleep=lambda _s: None)
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL), robots)
    assert calls == [] and result.reason == "robots_refused"


def test_crawl_delay_is_honoured_before_the_fetch(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    sleeps: list[float] = []
    robots = _robots("User-agent: *\nCrawl-delay: 7\n")
    _run(store, agg_id, Response(200, _page(POSTING), URL), robots, sleeps)
    assert sleeps == [7.0]


def test_brief_without_a_source_url_falls_back_without_fetching(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path, url=None)
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert calls == [] and result.reason == "no_source_url"


def test_brief_cli_fetches_so_the_downstream_reader_sees_employer_fields(
    tmp_path: Path,
) -> None:
    from integral.employer_brief import _main

    identity = create_profile(tmp_path, "Candidate", handle="candidate")
    store = ProfileStore(tmp_path, identity.handle)
    offer = connect_manual("Backend en Barcelona.", title="Backend", company="Aggregator")
    save_lifecycle_offer(store, offer, track_new_offer(offer, at=AT))
    calls: list[str] = []

    def fetch(url: str) -> Response:
        calls.append(url)
        return Response(200, _page(POSTING), url)

    args = ["record", "--id", "candidate", "--root", str(tmp_path), "--offer", offer.id]
    args += ["--employer", "Real SL", "--resolved-via", "apply_link", "--live", "unknown"]
    args += ["--checked-at", "2026-10-19T08:00:00Z", "--what", "x", "--sector", "y"]
    args += ["--pay", "n/a", "--hires", "true", "--source-url", URL]
    assert _main(args, fetch=fetch, robots=_robots()) == 0
    assert calls == [URL]
    seen = primary_offer(store, offer.id)
    assert seen.id != offer.id and seen.salary is not None and seen.salary.min == 50000.0
