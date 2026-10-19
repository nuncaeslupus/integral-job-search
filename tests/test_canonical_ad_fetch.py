"""Issue #875 — fetch the employer's posting when an aggregator copy has one. No network."""

from __future__ import annotations

import email.message
import http.client
import json
import urllib.request
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from integral.canonical_ad import (
    CanonicalResult,
    RedirectRefused,
    Response,
    _GuardedRedirects,
    load_result,
    primary_offer,
    resolve_canonical,
)
from integral.employer_brief import load_brief, record_brief, save_brief
from integral.identity import ProfileStore, create_profile
from integral.lifecycle import (
    _append_tombstone,
    build_tombstone,
    load_lifecycle_offer,
    save_lifecycle_offer,
    track_new_offer,
    transition,
)
from integral.offers import connect_manual, load_offer, load_offers, save_offer
from integral.robots import Robots

URL = "https://careers.real.example/jobs/42"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
AT = "2026-10-19T09:00:00Z"


def _page(posting: Mapping[str, object] | None, extra: str = "") -> str:
    ld = f'<script type="application/ld+json">{json.dumps(posting)}</script>' if posting else ""
    head = f"<title>Backend Engineer</title>{ld}"
    return f"<html><head>{head}</head><body><h1>Backend Engineer</h1>{extra}</body></html>"


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
    offer = connect_manual("Backend en Barcelona.", title="Backend Engineer", company="Aggregator")
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
    bare = {
        "@type": "JobPosting",
        "hiringOrganization": "Real SL",
        "title": "Backend Engineer",
        "description": "Plain description of the role.",
    }
    _run(store, agg_id, Response(200, _page(bare), URL))
    employer = primary_offer(store, agg_id)
    assert employer.id != agg_id
    assert employer.title == "Backend Engineer" and employer.company == "Real SL"


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
        (
            Response(
                200,
                _page(
                    {
                        "@type": "JobPosting",
                        "hiringOrganization": "Real SL",
                        "title": "Backend Engineer",
                    }
                ),
                URL,
            ),
            "parse_failure",
        ),
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
    offer = connect_manual("Backend en Barcelona.", title="Backend Engineer", company="Aggregator")
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


OTHER = {**POSTING, "title": "Office Manager", "hiringOrganization": {"name": "Other Corp"}}


def _fell_back(store: ProfileStore, agg_id: str, result: CanonicalResult, reason: str) -> None:
    assert result.outcome == "fallback" and result.reason == reason, result
    assert primary_offer(store, agg_id).id == agg_id


def test_b1_a_different_job_or_employer_is_not_promoted(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    page = _page({**POSTING, "title": "Senior Data Scientist"}, "")
    result, _ = _run(store, agg_id, Response(200, page, URL))
    _fell_back(store, agg_id, result, "mismatch")
    other_org = {**POSTING, "hiringOrganization": {"name": "Other Corp"}}
    result, _ = _run(store, agg_id, Response(200, _page(other_org), URL))
    _fell_back(store, agg_id, result, "mismatch")


def test_b1_the_page_must_mention_the_advert_title(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    page = "<html><body>Listings</body></html>" + _page(POSTING).replace("Backend", "Other")
    result, _ = _run(store, agg_id, Response(200, page, URL))
    _fell_back(store, agg_id, result, "not_confirmed_live")


def test_b2_the_matching_posting_is_chosen_among_several(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    graph = {"@graph": [OTHER, POSTING]}
    result, _ = _run(store, agg_id, Response(200, _page(graph), URL))
    assert result.outcome == "canonical"
    assert primary_offer(store, agg_id).title == "Backend Engineer"


def test_b2_an_ambiguous_page_is_not_promoted(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    twin = {**POSTING, "description": "<p>The same role, listed twice.</p>"}
    result, _ = _run(store, agg_id, Response(200, _page({"@graph": [POSTING, twin]}), URL))
    _fell_back(store, agg_id, result, "mismatch")
    result, _ = _run(store, agg_id, Response(200, _page({"@graph": [OTHER]}), URL))
    _fell_back(store, agg_id, result, "mismatch")


def test_b3_each_redirect_hop_is_checked_against_robots() -> None:
    robots = _robots("User-agent: *\nDisallow: /private\n")
    sleeps: list[float] = []
    handler = _GuardedRedirects(robots, sleeps.append, 0.0)
    req = urllib.request.Request(URL)
    headers = email.message.Message()
    ok = handler.redirect_request(
        req, None, 302, "Found", headers, "https://careers.real.example/jobs/43"
    )
    assert ok is not None and ok.full_url.endswith("/jobs/43")
    with pytest.raises(RedirectRefused):
        handler.redirect_request(
            req, None, 302, "Found", headers, "https://careers.real.example/private/x"
        )
    with pytest.raises(RedirectRefused):
        handler.redirect_request(req, None, 302, "Found", headers, "http://careers.real.example/x")


def test_b3_a_refused_redirect_is_recorded_as_robots_refused(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(store, agg_id, RedirectRefused("robots.txt disallows the redirect target"))
    _fell_back(store, agg_id, result, "robots_refused")


@pytest.mark.parametrize(
    "notice",
    [
        "Applications for this role have closed.",
        "This position has been filled.",
        "The position has been filled",
    ],
)
def test_b4_closed_notices_on_a_page_with_json_ld_are_closed(tmp_path: Path, notice: str) -> None:
    store, agg_id = _setup(tmp_path)
    page = _page(POSTING, f"<p>{notice}</p>")
    result, _ = _run(store, agg_id, Response(200, page, URL))
    _fell_back(store, agg_id, result, "closed")


def test_b5_the_aggregator_copy_leaves_the_new_pool_and_the_employer_copy_is_briefed(
    tmp_path: Path,
) -> None:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert result.canonical_id
    aggregator = load_offer(store, agg_id)
    assert aggregator.status == "archived" and aggregator.duplicate_of == result.canonical_id
    assert aggregator.text == "Backend en Barcelona."
    live = [o.id for o in load_offers(store).offers if o.status == "new"]
    assert live == [result.canonical_id]
    brief = load_brief(store, result.canonical_id)
    assert brief is not None and brief.source_posting_url == URL


def test_b5_a_tripped_exclusion_means_no_fetch(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    brief = load_brief(store, agg_id)
    assert brief is not None
    save_brief(store, brief.model_copy(update={"exclusions_tripped": ("logistics",)}))
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert calls == []
    _fell_back(store, agg_id, result, "brief_excluded")


def test_a_started_application_is_not_replaced(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    offer, record = load_lifecycle_offer(store, agg_id)
    offer, record = transition(offer, record, "shortlisted", at=AT)
    save_lifecycle_offer(store, offer, record)
    result, calls = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert calls == []
    _fell_back(store, agg_id, result, "already_in_progress")


def test_n1_an_unreadable_valid_through_is_not_promoted(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    page = _page({**POSTING, "validThrough": "1 October 2026"})
    result, _ = _run(store, agg_id, Response(200, page, URL))
    _fell_back(store, agg_id, result, "parse_failure")


def test_n2_a_date_only_valid_through_of_today_is_open(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(
        store, agg_id, Response(200, _page({**POSTING, "validThrough": "2026-10-19"}), URL)
    )
    assert result.outcome == "canonical"
    other, _ = _setup(tmp_path / "y")
    yesterday = {**POSTING, "validThrough": "2026-10-18"}
    result, _ = _run(other, _, Response(200, _page(yesterday), URL))
    assert result.reason == "closed"


def test_n3_a_protocol_error_is_a_fetch_error(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(store, agg_id, http.client.IncompleteRead(b"x"))
    _fell_back(store, agg_id, result, "fetch_error")


def _second_aggregator(store: ProfileStore) -> str:
    offer = connect_manual("Backend, otra copia.", title="Backend Engineer", company="Aggregator2")
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
        source_posting_url=URL,
    )
    return offer.id


def test_r1_an_applied_employer_copy_is_not_reset_by_a_second_aggregator(tmp_path: Path) -> None:
    store, first = _setup(tmp_path)
    employer_id = _run(store, first, Response(200, _page(POSTING), URL))[0].canonical_id
    assert employer_id
    offer, record = load_lifecycle_offer(store, employer_id)
    offer, record = transition(offer, record, "shortlisted", at=AT)
    offer, record = transition(offer, record, "applied", at=AT)
    save_lifecycle_offer(store, offer, record)

    second = _second_aggregator(store)
    result, _ = _run(store, second, Response(200, _page(POSTING), URL))
    assert result.outcome == "canonical" and result.canonical_id == employer_id
    kept, kept_record = load_lifecycle_offer(store, employer_id)
    assert kept.status == "applied" and len(kept_record.history) == 3
    assert load_offer(store, second).duplicate_of == employer_id
    assert load_offer(store, second).status == "archived"


def test_r1_a_tombstoned_employer_copy_is_not_recreated(tmp_path: Path) -> None:
    store, first = _setup(tmp_path)
    employer_id = _run(store, first, Response(200, _page(POSTING), URL))[0].canonical_id
    assert employer_id
    offer, record = load_lifecycle_offer(store, employer_id)
    _append_tombstone(store, build_tombstone(offer, record, purged_at=AT))
    store.path("offers", f"{employer_id}.json").unlink()
    store.path("offers", "lifecycle", f"{employer_id}.json").unlink()

    second = _second_aggregator(store)
    result, _ = _run(store, second, Response(200, _page(POSTING), URL))
    assert result.outcome == "fallback" and result.reason == "tombstoned"
    assert not store.path("offers", f"{employer_id}.json").exists()
    assert primary_offer(store, second).id == second


def _promotes(tmp_path: Path, posting: dict[str, object]) -> bool:
    store, agg_id = _setup(tmp_path)
    result, _ = _run(store, agg_id, Response(200, _page(posting), URL))
    return result.outcome == "canonical"


def test_r2_an_advert_with_no_title_promotes_nothing(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    save_offer(store, load_offer(store, agg_id).model_copy(update={"title": None}))
    result, _ = _run(store, agg_id, Response(200, _page(POSTING, "Backend Engineer"), URL))
    _fell_back(store, agg_id, result, "mismatch")


def test_r3_a_title_is_matched_whole_not_by_substring(tmp_path: Path) -> None:
    assert not _promotes(tmp_path / "a", {**POSTING, "title": "Backend Engineer Sales Lead"})
    assert not _promotes(tmp_path / "b", {**POSTING, "title": "Engineer"})
    assert _promotes(tmp_path / "c", {**POSTING, "title": "backend  ENGINEER"})


def test_r3_an_employer_is_matched_whole_not_by_prefix(tmp_path: Path) -> None:
    for i, name in enumerate(["Real Estate Staffing Agency", "Re", "Realty SL"]):
        assert not _promotes(tmp_path / str(i), {**POSTING, "hiringOrganization": {"name": name}})
    assert _promotes(tmp_path / "ok", {**POSTING, "hiringOrganization": {"name": "Real, S.L."}})


def test_r5_a_second_run_keeps_the_existing_promotion(tmp_path: Path) -> None:
    store, agg_id = _setup(tmp_path)
    first, _ = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert first.outcome == "canonical"
    second, _ = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert second.outcome == "canonical" and second.canonical_id == first.canonical_id
    record = load_result(store, agg_id)
    assert record and record["outcome"] == "canonical"
    assert primary_offer(store, agg_id).id == first.canonical_id != agg_id


def test_r6_an_aggregator_copy_with_no_lifecycle_record_leaves_the_new_pool(
    tmp_path: Path,
) -> None:
    store, agg_id = _setup(tmp_path)
    store.path("offers", "lifecycle", f"{agg_id}.json").unlink()
    result, _ = _run(store, agg_id, Response(200, _page(POSTING), URL))
    assert result.outcome == "canonical"
    kept, record = load_lifecycle_offer(store, agg_id)
    assert kept.status == "archived" and kept.duplicate_of == result.canonical_id
    assert record.current_status == "archived"
