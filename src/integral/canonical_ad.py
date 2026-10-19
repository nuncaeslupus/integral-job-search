"""Fetch the employer's own posting when a brief has resolved one (issue #875).

`employer_brief` records `source_posting_url` for an aggregator copy. This module
goes and reads that page, through the same pieces every other fetch uses: the
`integral.robots` check under `USER_AGENT`, the site's crawl-delay, and
`liveness.read_response` for the live/closed verdict. `guarded_fetch` is `urllib`
with the honest agent and nothing else.

When the page is a live posting with a parseable `JobPosting` (schema.org JSON-LD),
the employer copy is stored as a new offer (`source_kind="employer"`) and becomes
the primary one: the aggregator copy keeps its record, points `duplicate_of` at it,
and is named in `offers/canonical/<aggregator id>.json` as provenance. Fields the
employer page states (salary, location, full text) are the ones the later steps
read; fields it omits are filled from the aggregator copy. Any other outcome keeps
the aggregator copy primary and records the reason in the same file.

    primary_offer(store, offer_id)   # the employer copy if one was fetched, else the offer
"""

from __future__ import annotations

import html
import http.client
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import ValidationError

from integral.employer_brief import load_brief, save_brief
from integral.identity import IdentityError, ProfileStore
from integral.lifecycle import (
    LifecycleError,
    collect_offer,
    load_lifecycle_offer,
    save_lifecycle_offer,
    transition,
)
from integral.liveness import read_response
from integral.offers import Location, Offer, Salary, compute_offer_id, load_offer, save_offer
from integral.robots import USER_AGENT, Robots, RobotsError
from integral.salary_period import normalize_period

Outcome = Literal["canonical", "fallback"]
Reason = Literal[
    "no_source_url",
    "robots_refused",
    "fetch_error",
    "gone",
    "closed",
    "not_confirmed_live",
    "parse_failure",
    "mismatch",
    "brief_excluded",
    "already_in_progress",
    "tombstoned",
]

DEFAULT_DELAY_FLOOR = 1.0
_BREAK = re.compile(r"</(p|div|li|ul|ol|h[1-6]|tr)>|<br\s*/?>", re.IGNORECASE)
_ITEM = re.compile(r"<li\b[^>]*>", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]*>")
_LD_JSON = re.compile(
    r"<script\b[^>]*type\s*=\s*[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Response:
    status: int | None
    body: str | None
    final_url: str | None = None


Fetch = Callable[[str], Response]


class RedirectRefused(OSError):
    """A redirect hop that robots.txt, or the https-only rule, does not allow."""


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Check every redirect hop like a first request: https only, robots, crawl-delay."""

    def __init__(self, robots: Robots, sleep: Callable[[float], None], floor: float) -> None:
        self._robots, self._sleep, self._floor = robots, sleep, floor

    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> Any:
        if urlsplit(newurl).scheme != "https":
            raise RedirectRefused(f"redirect off https refused: {newurl}")
        try:
            allowed = self._robots.allows(newurl)
        except RobotsError as exc:
            raise RedirectRefused(f"robots.txt unreadable for redirect {newurl}: {exc}") from exc
        if not allowed:
            raise RedirectRefused(f"robots.txt disallows the redirect target {newurl}")
        wait = self._robots.delay(newurl, self._floor)
        if wait > 0:
            self._sleep(wait)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_fetch(
    robots: Robots, sleep: Callable[[float], None] = time.sleep, floor: float = 1.0
) -> Fetch:
    """A plain GET with the honest agent, whose redirects are each checked against robots.txt."""
    opener = urllib.request.build_opener(_GuardedRedirects(robots, sleep, floor))

    def fetch(url: str, timeout: float = 20.0) -> Response:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with opener.open(request, timeout=timeout) as reply:
                return Response(reply.status, reply.read().decode("utf-8", "replace"), reply.url)
        except urllib.error.HTTPError as exc:
            return Response(exc.code, None, url)

    return fetch


@dataclass(frozen=True)
class CanonicalResult:
    aggregator_id: str
    outcome: Outcome
    canonical_id: str | None
    reason: Reason | None
    detail: str
    url: str | None
    checked_at: str

    @property
    def primary_id(self) -> str:
        return self.canonical_id or self.aggregator_id


def _parts(offer_id: str) -> tuple[str, str, str]:
    return ("offers", "canonical", f"{offer_id}.json")


def _postings(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [p for item in node for p in _postings(item)]
    if not isinstance(node, dict):
        return []
    kind = node.get("@type")
    kinds = kind if isinstance(kind, list) else [kind]
    found = [node] if "JobPosting" in kinds else []
    return found + _postings(node.get("@graph"))


def _job_postings(body: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for block in _LD_JSON.findall(body):
        try:
            found += _postings(json.loads(block))
        except ValueError:
            continue
    return found


def _norm(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _same_employer(posting: dict[str, Any], employer: str) -> bool:
    org = posting.get("hiringOrganization")
    name = _norm(_text(org.get("name") if isinstance(org, dict) else org) or "")
    want = _norm(employer)
    return bool(name and want and (name == want or name.startswith(want) or want.startswith(name)))


def _same_title(posting: dict[str, Any], title: str | None) -> bool:
    mine, theirs = _norm(title or ""), _norm(_text(posting.get("title")) or "")
    return not mine or (bool(theirs) and (mine in theirs or theirs in mine))


def _text(value: Any) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _salary(base: Any) -> Salary | None:
    value = base.get("value") if isinstance(base, dict) else None
    if not isinstance(value, dict):
        return None
    low, high = value.get("minValue", value.get("value")), value.get("maxValue")
    nums = [x for x in (low, high) if isinstance(x, int | float) and not isinstance(x, bool)]
    if not nums:
        return None
    unit = value.get("unitText")
    return Salary(
        min=float(min(nums)),
        max=float(max(nums)),
        currency=_text(base.get("currency")),
        period=normalize_period(unit) if isinstance(unit, str) else None,
        stated=True,
    )


def _location(posting: dict[str, Any]) -> Location | None:
    place = posting.get("jobLocation")
    place = place[0] if isinstance(place, list) and place else place
    address = place.get("address") if isinstance(place, dict) else None
    parts: list[str] = []
    country = None
    if isinstance(address, dict):
        parts = [
            s
            for k in ("streetAddress", "addressLocality", "addressRegion")
            if (s := _text(address.get(k)))
        ]
        c = address.get("addressCountry")
        country = _text(c.get("name") if isinstance(c, dict) else c)
    remote = "remote" if posting.get("jobLocationType") == "TELECOMMUTE" else None
    if not parts and not country and not remote:
        return None
    raw = ", ".join(parts + ([country] if country else [])) or None
    return Location(raw=raw, country=country, remote=remote)


def _open_until(posting: dict[str, Any], now: datetime) -> bool | None:
    """Whether `validThrough` leaves the posting open: None when it is stated but unreadable."""
    until = _text(posting.get("validThrough"))
    if until is None:
        return True
    try:
        if len(until) == 10:  # a date: schema.org's last valid day, so today is still open
            return datetime.fromisoformat(until).date() >= now.date()
        stamp = datetime.fromisoformat(until.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=UTC)) >= now


def _plain(markup: str) -> str:
    """Advert HTML as readable text: case kept, one line per block, list items dashed."""
    marked = _BREAK.sub("\n", _ITEM.sub("- ", markup))
    lines = (" ".join(line.split()) for line in _TAG.sub(" ", marked).splitlines())
    return "\n".join(line for line in lines if line)


def _employer_offer(posting: dict[str, Any], url: str, agg: Offer, now: datetime) -> Offer | None:
    """The employer's copy as an `Offer`, gaps filled from the aggregator's; None if no text."""
    description = _text(posting.get("description"))
    if description is None:
        return None
    unescaped = html.unescape(description)
    body = _plain(unescaped)
    title = _text(posting.get("title")) or agg.title
    text = f"{title}\n\n{body}" if title else body
    org = posting.get("hiringOrganization")
    company = _text(org.get("name") if isinstance(org, dict) else org) or agg.company
    try:
        return Offer(
            id=compute_offer_id(text),
            source=f"employer:{urlsplit(url).netloc}",
            source_kind="employer",
            url=url,
            fetched_at=now.isoformat(),
            title=title,
            company=company,
            location=_location(posting) or agg.location,
            salary=_salary(posting.get("baseSalary")) or agg.salary,
            language=agg.language,
            text=text,
            expires_at=_text(posting.get("validThrough")),
            language_requirement=agg.language_requirement,
        )
    except ValidationError:
        return None


def _record(store: ProfileStore, result: CanonicalResult) -> CanonicalResult:
    store.write_json(
        {
            "aggregator_offer_id": result.aggregator_id,
            "outcome": result.outcome,
            "canonical_offer_id": result.canonical_id,
            "reason": result.reason,
            "detail": result.detail,
            "source_posting_url": result.url,
            "checked_at": result.checked_at,
        },
        *_parts(result.aggregator_id),
    )
    return result


def load_result(store: ProfileStore, offer_id: str) -> dict[str, Any] | None:
    try:
        raw = store.read_json(*_parts(offer_id))
    except IdentityError:
        return None
    return raw if isinstance(raw, dict) else None


def primary_offer(store: ProfileStore, offer_id: str) -> Offer:
    """The offer later steps should read: the employer copy when one was fetched."""
    record = load_result(store, offer_id)
    if record and record.get("outcome") == "canonical" and record.get("canonical_offer_id"):
        try:
            return load_offer(store, str(record["canonical_offer_id"]))
        except Exception:  # an unreadable employer copy falls back to the original
            pass
    return load_offer(store, offer_id)


def resolve_canonical(
    store: ProfileStore,
    offer_id: str,
    *,
    fetch: Fetch | None = None,
    robots: Robots | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: datetime | None = None,
    delay_floor: float = DEFAULT_DELAY_FLOOR,
) -> CanonicalResult:
    """Fetch the brief's `source_posting_url` and make it primary if it is a live posting."""
    at = now or datetime.now(UTC)
    stamp = at.isoformat()
    aggregator = load_offer(store, offer_id)
    brief = load_brief(store, offer_id)
    url = (brief.source_posting_url or "").strip() if brief else ""

    def fallback(reason: Reason, detail: str) -> CanonicalResult:
        return _record(
            store,
            CanonicalResult(offer_id, "fallback", None, reason, detail, url or None, stamp),
        )

    if brief is None or not url:
        return fallback("no_source_url", "the brief names no source posting")
    if brief.exclusions_tripped:
        return fallback("brief_excluded", "the brief tripped an exclusion: nothing is fetched")
    if aggregator.status != "new":
        return fallback("already_in_progress", f"the advert is already {aggregator.status}")
    checker = robots or Robots()
    try:
        allowed = checker.allows(url)
    except RobotsError as exc:
        return fallback("robots_refused", f"robots.txt could not be read: {exc}")
    if not allowed:
        return fallback("robots_refused", "robots.txt disallows the posting for this tool")
    wait = checker.delay(url, delay_floor)
    if wait > 0:
        sleep(wait)
    get = fetch or guarded_fetch(checker, sleep, delay_floor)
    try:
        reply = get(url)
    except RedirectRefused as exc:
        return fallback("robots_refused", str(exc))
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return fallback("fetch_error", f"the fetch failed: {exc}")

    check = read_response(
        offer_id,
        reply.status,
        reply.body,
        advert_url=url,
        final_url=reply.final_url,
        title=aggregator.title,
    )
    if check.liveness == "dead":
        reason: Reason = "gone" if reply.status in (404, 410) else "closed"
        return fallback(reason, check.reason)
    if check.liveness != "live" or reply.body is None:
        return fallback("not_confirmed_live", check.reason)
    postings = _job_postings(reply.body)
    if not postings:
        return fallback("parse_failure", "the page carries no schema.org JobPosting")
    matching = [
        p
        for p in postings
        if _same_employer(p, brief.real_employer) and _same_title(p, aggregator.title)
    ]
    if len(matching) != 1:
        return fallback(
            "mismatch",
            f"{len(matching)} of {len(postings)} postings match {brief.real_employer!r}"
            f" and {aggregator.title!r}",
        )
    posting = matching[0]
    still_open = _open_until(posting, at)
    if still_open is None:
        return fallback("parse_failure", f"validThrough {posting.get('validThrough')!r} unreadable")
    if not still_open:
        return fallback("closed", f"validThrough {posting.get('validThrough')} has passed")
    employer = _employer_offer(posting, url, aggregator, at)
    if employer is None or employer.id == offer_id:
        return fallback("parse_failure", "the JobPosting has no usable description")

    # The §7.4 gate, never a bare save: an employer copy already tracked (possibly applied)
    # must keep its status and history, and a tombstoned one must not be re-created.
    collected = collect_offer(store, employer, at=stamp)
    if collected.matched_tombstone is not None:
        return fallback(
            "tombstoned", f"the employer copy was purged: {collected.matched_tombstone}"
        )
    kept_id = employer.id if collected.added_as_new else collected.duplicate_of or employer.id
    if load_brief(store, kept_id) is None:
        save_brief(store, brief.model_copy(update={"offer_id": kept_id}))
    _retire_aggregator(store, aggregator, kept_id, stamp)
    return _record(
        store,
        CanonicalResult(offer_id, "canonical", kept_id, None, check.reason, url, stamp),
    )


def _retire_aggregator(store: ProfileStore, aggregator: Offer, employer_id: str, at: str) -> None:
    """Keep the aggregator copy as provenance, out of the live `new` pool."""
    linked = aggregator.model_copy(update={"duplicate_of": employer_id})
    try:
        _, record = load_lifecycle_offer(store, aggregator.id)
        archived, record = transition(
            linked, record, "archived", at=at, reason=f"canonical copy {employer_id}"
        )
    except LifecycleError:
        save_offer(store, linked)
        return
    save_lifecycle_offer(store, archived, record)
