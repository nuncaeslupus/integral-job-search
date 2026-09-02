#!/usr/bin/env python3
"""Collect real, verbatim job ads into corpus/raw/ads.jsonl.

Ads must be real and carry a resolvable source URL (spec risk register: a corpus of
invented ads makes every numeric gate pass while measuring nothing). Nothing here
generates text — every record is fetched from a live board and stored verbatim.

T4b built the remote-programming slice; T25 broadens it to the other job families,
whose advertising vocabulary is not guessable from programming ads.

Usage:
    python tools/collect_ads.py --target-es 60 --target-en 25 --target-ca 15 \\
                               --target-family 15

Re-running merges into the existing file by `id`, so collection can happen in
several sittings and across sources.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

import py3langid
import requests
from bs4 import BeautifulSoup

from integral.connector_policy import DEFAULT_LEDGER_PATH, refusals
from integral.corpus import (
    LANGUAGES,
    classify_family,
    job_family_counts,
    language_counts,
    load_ads,
    save_ads,
    write_evidence,
    write_family_evidence,
)
from integral.corpus_scope import load_draws
from integral.robots import USER_AGENT, Robots

# The host each named source fetches from, so the plan below can be put through the
# policy ledger by name. A source with no host here is refused too: an unrecorded host
# cannot be checked against a refusal, and "not checkable" must not read as "allowed".
SOURCE_HOSTS = {
    "manfred": "getmanfred.com",
    "tecnoempleo": "tecnoempleo.com",
    "weworkremotely": "weworkremotely.com",
    "remoteok": "remoteok.com",
    "remotive": "remotive.com",
    "feinaactiva": "feinaactiva.gencat.cat",
}


def plan_refusals(sources: Iterable[str], ledger: Path = DEFAULT_LEDGER_PATH) -> dict[str, str]:
    """Why each named source may not be collected from, by name. Empty is a clean plan.

    `connectors/ruled-out.yaml` is the record of which boards were surveyed and refused,
    and this collector is the one thing in the repo that fetches a board in bulk. Both
    kinds of refusal bind it. An `access` refusal removes the board outright; a `volume`
    refusal is the owner's line between "a candidate looking at a handful of adverts"
    and "a tool ingesting a board", and a corpus draw is unambiguously the second.

    This is a check rather than a deletion so the *next* refused source is caught the
    day it is added, and so overturning a refusal in the ledger re-enables the source
    without anyone having to remember this file. A refused source is dropped from the
    plan and the reason printed — adding it to a draw's `sources:` axis instead would
    turn a refusal into a specification, which is the move T98 exists to prevent.
    """
    refused = {row.site: row for row in refusals(ledger) if row.site}
    found: dict[str, str] = {}
    for name in sources:
        host = SOURCE_HOSTS.get(name)
        if not host:
            found[name] = "no host recorded in SOURCE_HOSTS, so no refusal can be checked"
            continue
        for site, row in refused.items():
            if host == site or host.endswith(f".{site}"):
                found[name] = (
                    f"{host} is in connectors/ruled-out.yaml `policy_refused` "
                    f"(refuses {row.refuses or 'unstated'}, decided by "
                    f"{row.decided_by or 'unstated'} on {row.decided_on or 'no date'})"
                )
                break
    return found


def url_refusals(urls: Iterable[str], ledger: Path = DEFAULT_LEDGER_PATH) -> dict[str, str]:
    """Why each hand-supplied URL may not be fetched, by URL. Empty is a clean list.

    `plan_refusals` binds the fixed plan; this binds `--ca-urls`, which reached
    `from_urls` without passing the ledger at all. A `remoteok.com` URL in that file was
    fetched in bulk despite the owner's `refuses: volume` ruling — the refusal routed
    around by the one input a person types by hand, which is the input least likely to
    have been checked against anything.

    A host `SOURCE_HOSTS` does not record is refused as well, the same fail-closed rule
    the plan path follows: a board nothing surveyed cannot be put through the ledger,
    and "not checkable" reading as "allowed" is how the refused board got fetched the
    first time. Overturning that costs one line in `SOURCE_HOSTS`, which is also where
    the *next* reader looks to find out whether a board was considered at all.
    """
    refused = plan_refusals(SOURCE_HOSTS, ledger)
    found: dict[str, str] = {}
    for url in urls:
        host = (urlsplit(url).hostname or "").lower()
        name = next(
            (
                source
                for source, known in SOURCE_HOSTS.items()
                if host == known or host.endswith(f".{known}")
            ),
            None,
        )
        if name is None:
            found[url] = (
                f"host {host or '(none)'} is not recorded in SOURCE_HOSTS, so no refusal "
                f"can be checked"
            )
        elif name in refused:
            found[url] = refused[name]
    return found


def permitted_urls(urls: list[str], ledger: Path = DEFAULT_LEDGER_PATH) -> list[str]:
    """The supplied URLs the ledger allows, with every refusal printed.

    Filtering happens here rather than inside `from_urls` so a refused URL is dropped
    *before* a session ever sees it: "refused" has to mean no request left the process,
    not that the record was discarded after the fetch.
    """
    refused = url_refusals(urls, ledger)
    for url, why in sorted(refused.items()):
        print(f"{url}: not fetched — {why}", file=sys.stderr)
    return [url for url in urls if url not in refused]


# ponytail: no rate-limit machinery — a floor, and whatever the site asks for,
# whichever is slower.
#
# 1.0, not 0.4, and the reason is a parser limitation worth knowing about.
# `remoteok.com` carries *two* `User-agent: *` groups — a Cloudflare-managed one
# and its own, and only the second states `Crawl-delay: 1`. `RobotFileParser`
# keeps the first group it matches, so `ROBOTS.delay()` reports nothing there.
# Rather than hand-roll a merging parser to read one number, the floor is set to
# the slowest thing any board we read asks for. Raise it, never lower it.
POLITENESS_FLOOR = 1.0

# One robots.txt per host, read once, and the identity it is answered for.
# This used to send a Chrome string. A board's robots.txt is addressed to
# whoever the client says it is, so a browser string is not compliance with the
# file, it is evasion of it — and it bought nothing: both boards allow
# `User-agent: *` on their listings. Being nameable is also the only way a board
# can ask this to stop.
ROBOTS = Robots()

# ponytail: title regex, not an LLM classifier. Recall over precision — a wrong-role ad
# is dropped by hand at labelling (T5), a missed one is invisible.
ROLE_RE = re.compile(
    r"\b(develop\w*|desarroll\w*|desenvolup\w*|programad\w*|inform[àa]tic\w*|engineer|enginy\w*|ingenier\w*|"
    r"backend|back-end|frontend|front-end|fullstack|full-stack|software|devops|sre|"
    r"data engineer|machine learning|android|ios|mobile|web|python|java|javascript|"
    r"typescript|golang|rust|php|\.net|react|node)\b",
    re.I,
)
NOT_ROLE_RE = re.compile(
    r"\b(comercial|ventas|sales|recruit\w*|marketing|dise[ñn]\w*|designer|"
    r"account manager|teacher|professor|profesor\w*|service desk|help ?desk|"
    r"soporte|suport|support|becari\w*|intern|cnc|plc|cam|autocad)\b",
    re.I,
)


def is_programming_role(title: str) -> bool:
    return bool(ROLE_RE.search(title)) and not NOT_ROLE_RE.search(title)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def clean(text: str) -> str:
    """HTML (or markdown) to plain text, verbatim apart from whitespace collapsing."""
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "lxml").get_text("\n")
    text = text.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def detect_language(text: str) -> str:
    """Restricted to the three corpus languages; anything else is not collectable here."""
    py3langid.set_languages(list(LANGUAGES))
    lang, _ = py3langid.classify(text)
    return str(lang)


MAX_REDIRECTS = 5


def get(session: requests.Session, url: str, **kw: Any) -> requests.Response:
    """Fetch `url`, or refuse because the policy ledger or the site's robots.txt says not to.

    The check is here rather than in each board adapter because every fetch
    goes through here: a rule that has to be remembered at each call site is a
    rule that is one new adapter away from not applying.

    **Redirects are followed by hand, one hop at a time.** `requests` follows
    them itself, which would check the first URL and fetch the last — so a
    board that redirects a permitted path onto a disallowed one, or onto
    another host entirely, would walk straight through the check. Every hop is
    a fetch, so every hop is put through the refusal ledger, asks that origin's
    own robots.txt and waits for that origin's own crawl delay.
    """
    for _ in range(MAX_REDIRECTS + 1):
        if urlsplit(url).scheme != "https":
            raise PermissionError(f"the collector reads https only, not {url!r}")
        # The ledger, before robots and before the request leaves the process. The plan
        # is filtered before it is walked and `--ca-urls` before it is read; neither
        # reaches a redirect target, which is the one URL nobody typed — an allowed
        # first hop landing on a refused board is the refusal routed around by the
        # board itself. Asking robots.txt first would put a question to a board we may
        # not fetch at all. `url_refusals` is the same reader the other two paths use,
        # so there is still exactly one parser of `connectors/ruled-out.yaml`.
        refused = url_refusals([url])
        if url in refused:
            raise PermissionError(f"the policy ledger refuses {url} — {refused[url]}")
        if not ROBOTS.allows(url):
            raise PermissionError(f"robots.txt disallows {USER_AGENT} on {url}")
        # Before, not after: a delay that only follows the final response does
        # not pace the redirect chain that led to it.
        time.sleep(ROBOTS.delay(url, POLITENESS_FLOOR))
        r = session.get(
            url, timeout=30, headers={"User-Agent": USER_AGENT}, allow_redirects=False, **kw
        )
        if not r.is_redirect:
            r.raise_for_status()
            return r
        url = urljoin(url, r.headers["Location"])
    raise RuntimeError(f"more than {MAX_REDIRECTS} redirects fetching {url!r}")


# T98: the draw this run is executing, set once from `--draw` and stamped onto every row
# it produces. A module-level value rather than an eighth parameter threaded through
# eight call sites, because one run *is* one draw — and `record` refuses to build a row
# while it is empty, so the collector cannot write a corpus nothing can account for.
DRAW = ""


def record(
    ad_id: str, source: str, url: str, title: str, company: str, text: str, job_family: str
) -> dict[str, Any] | None:
    if not DRAW:
        raise RuntimeError("no draw set — collect against a draw declared in corpus/draws.yaml")
    if len(text) < 400:  # a stub, not an ad
        return None
    return {
        "id": ad_id,
        "source": source,
        "source_url": url,
        "fetched_at": now(),
        "language": detect_language(text),
        "title": title.strip(),
        "company": company.strip(),
        "job_family": job_family,
        "draw": DRAW,
        "text": text,
    }


def jobposting_ld(html: str) -> dict[str, Any] | None:
    """schema.org JobPosting block — the one parser that works across most boards."""
    soup = BeautifulSoup(html, "lxml")
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return None


# --------------------------------------------------------------------------- sources


def from_manfred(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """getManfred — Spanish board, full-remote flag and long-form ad text."""
    offers = get(session, "https://www.getmanfred.com/api/v2/public/offers?lang=ES").json()
    picked = [
        o
        for o in offers
        if o.get("remotePercentage") == 100
        and o.get("status") == "ACTIVE"
        and is_programming_role(o.get("position", ""))
    ]
    for offer in picked[:limit]:
        detail = get(
            session, f"https://www.getmanfred.com/api/v2/public/offers/{offer['id']}?lang=ES"
        ).json()
        sections = [
            "introduction",
            "whatWillYouDo",
            "howWillYouDoIt",
            "whenWillDoIt",
            "whereWillDoIt",
            "whoWillDoItWith",
            "whatTheyAskFor",
            "whatOffering",
            "inOneMonth",
            "inThreeMonths",
            "inSixMonths",
        ]
        text = clean("\n\n".join(str(detail.get(s) or "") for s in sections))
        url = f"https://www.getmanfred.com/ofertas-empleo/{offer['id']}/{offer['slug']}"
        rec = record(
            f"manfred-{offer['id']}",
            "manfred",
            url,
            detail.get("position", ""),
            (detail.get("company") or {}).get("name", ""),
            text,
            "programming",
        )
        if rec:
            yield rec


def from_tecnoempleo(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """Tecnoempleo — Spanish IT board; its `teletrabajo` listing is already remote-only."""
    seen: set[str] = set()
    count = 0
    for page in range(1, 12):
        if count >= limit:
            return
        html = get(
            session, f"https://www.tecnoempleo.com/ofertas-trabajo/teletrabajo?pagina={page}"
        ).text
        urls = [
            u
            for u in dict.fromkeys(
                re.findall(r"https://www\.tecnoempleo\.com/[^\"']*?/rf-[a-z0-9]+", html)
            )
            if u not in seen
        ]
        if not urls:
            return
        for url in urls:
            if count >= limit:
                return
            seen.add(url)
            posting = jobposting_ld(get(session, url).text)
            if not posting or not is_programming_role(str(posting.get("title", ""))):
                continue
            rec = record(
                f"tecnoempleo-{url.rsplit('rf-', 1)[1]}",
                "tecnoempleo",
                url,
                str(posting.get("title", "")),
                str((posting.get("hiringOrganization") or {}).get("name", "")),
                clean(str(posting.get("description", ""))),
                "programming",
            )
            if rec:
                count += 1
                yield rec


def from_remotive(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """Remotive — English remote board, full description in its public JSON API."""
    jobs = get(
        session, "https://remotive.com/api/remote-jobs?category=software-dev&limit=200"
    ).json()["jobs"]
    count = 0
    for job in jobs:
        if count >= limit:
            return
        if not is_programming_role(job.get("title", "")):
            continue
        rec = record(
            f"remotive-{job['id']}",
            "remotive",
            job["url"],
            job.get("title", ""),
            job.get("company_name", ""),
            clean(job.get("description", "")),
            "programming",
        )
        if rec:
            count += 1
            yield rec


def from_weworkremotely(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """We Work Remotely — English; its programming RSS carries the whole ad body."""
    feeds = (
        "https://weworkremotely.com/categories/remote-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
        "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    )
    count = 0
    for feed in feeds:
        if count >= limit:
            return
        soup = BeautifulSoup(get(session, feed).text, "xml")
        for item in soup.find_all("item"):
            if count >= limit:
                return
            raw_title = item.title.get_text() if item.title else ""
            company, _, title = raw_title.partition(":")
            if not title:
                company, title = "", raw_title
            if not is_programming_role(title):
                continue
            url = item.link.get_text().strip() if item.link else ""
            rec = record(
                f"wwr-{url.rstrip('/').rsplit('/', 1)[-1]}",
                "weworkremotely",
                url,
                title,
                company,
                clean(item.description.get_text() if item.description else ""),
                "programming",
            )
            if rec:
                count += 1
                yield rec


def from_remoteok(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """RemoteOK — English; public JSON feed, first element is the licence notice."""
    jobs = get(session, "https://remoteok.com/api").json()[1:]
    count = 0
    for job in jobs:
        if count >= limit:
            return
        if not is_programming_role(job.get("position", "")):
            continue
        rec = record(
            f"remoteok-{job['id']}",
            "remoteok",
            job.get("url", ""),
            job.get("position", ""),
            job.get("company", ""),
            clean(job.get("description", "")),
            "programming",
        )
        if rec:
            count += 1
            yield rec


# Natively-Catalan *programming* ads are a thin market: a full sweep of Feina Activa
# yields well under 15. For Catalan the role filter therefore widens to IT roles at
# large (sysadmin, data, cybersecurity, TIC consulting) — the point of the Catalan
# slice is ontology coverage of Catalan job-ad vocabulary, and a substantive real ad
# serves that far better than a four-line public-sector stub would. Flagged as a
# deliberate divergence from the T4b line in status/plan.md.
CA_ROLE_RE = re.compile(
    r"(program|desenvolup|develop|software|inform[àa]tic|web|java|python|php|fullstack|"
    r"full stack|backend|frontend|devops|sistemes|dades|ciberseg|tecnol[òo]g|\bTIC\b|analista)",
    re.I,
)
CA_NOT_ROLE_RE = re.compile(
    r"\b(plc|cnc|cam|rob[òo]tica|comercial|vendes|ventas|sales|formador\w*|professor\w*|"
    r"borsa de treball|pla[çc]a de|docent|psic[òo]leg|psic[òo]loga|compressors|"
    r"instal·lador\w*|electr[òo]nics)\b|captaci[óo] de fons|de persones i talent|"
    r"inserci[óo]|relaci[óo] amb",
    re.I,
)
CA_MIN_CHARS = 600  # drops the CIDO/public-sector one-paragraph stubs

FEINA_ACTIVA_KEYWORDS = (
    "programador",
    "desenvolupador",
    "informatica",
    "software",
    "desenvolupament web",
    "aplicacions",
    "java",
    "python",
    "php",
    "javascript",
    "fullstack",
    "backend",
    "frontend",
    "analista programador",
    "devops",
    "teletreball informatica",
    "enginyer informatic",
    "programacio",
    "desenvolupador web",
    "angular",
    "react",
    "sql",
    "erp",
    "cloud",
    "dades",
    "ciberseguretat",
    "sistemes",
    "tecnic informatic",
    "base de dades",
    "xarxes",
    "servidors",
    "microinformatica",
    "aplicacions mobils",
    "intelligencia artificial",
    "helpdesk",
    "IT",
)


def from_feinaactiva(session: requests.Session, limit: int) -> Iterator[dict[str, Any]]:
    """Feina Activa (Servei d'Ocupació de Catalunya) — the one board whose ads are
    natively written in Catalan. Its public search API pages 20 at a time."""
    base = "https://feinaactiva.gencat.cat/api/offers"
    refs: dict[str, str] = {}
    for keyword in FEINA_ACTIVA_KEYWORDS:
        for offset in range(0, 200, 20):
            page = get(session, f"{base}/list?keywords={keyword}&limit=20&offset={offset}").json()
            hits = page.get("included", [])
            for offer in hits:
                title = offer["content"]["title"]
                if CA_ROLE_RE.search(title) and not CA_NOT_ROLE_RE.search(title):
                    refs[offer["reference"]] = title
            if len(hits) < 20:
                break
    count = 0
    for ref in refs:
        if count >= limit:
            return
        title, company, text = feinaactiva_detail(session, ref)
        rec = record(
            f"feinaactiva-{ref}",
            "feinaactiva",
            f"https://feinaactiva.gencat.cat/search/offers/detail/{ref}",
            title,
            company,
            text,
            "programming",
        )
        if rec and rec["language"] == "ca" and len(rec["text"]) >= CA_MIN_CHARS:
            count += 1
            yield rec


# --------------------------------------------------------- T25: other job families

# The corpus started as 100 remote-programming ads and the dimensions were written from
# them. Feina Activa is the one board in reach that advertises *every* family natively in
# the corpus's own languages, so the breadth slice comes from there rather than from the
# remote boards, whose non-tech categories are only more flavours of office work.
#
# ponytail: keyword search finds candidates, title regexes decide the family — no
# classifier. Recall over precision within a family, as with ROLE_RE; but a title that
# matches *two* families is dropped rather than guessed, because a miscategorised ad
# teaches the dimension model the wrong vocabulary for both.
FAMILY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hospitality": ("cambrer", "cuiner", "ajudant de cuina", "hostaleria", "recepcionista hotel"),
    "healthcare": ("infermer", "auxiliar infermeria", "fisioterapeuta", "cuidador", "gerocultor"),
    "trades": ("electricista", "lampista", "fuster", "soldador", "paleta", "mecanic"),
    # Retail needed the longest keyword list: the shop-counter roles are advertised
    # under their trade name ("carnisser", "peixater") far more often than under a
    # generic "dependent", and the five obvious terms alone returned 11.
    "retail": (
        "dependent",
        "caixer",
        "venedor botiga",
        "reposador",
        "comerc",
        "botiga",
        "supermercat",
        "carnisser",
        "peixater",
        "xarcuter",
        "encarregat botiga",
        "venedor",
    ),
    "teaching": (
        "professor",
        "mestre",
        "educador",
        "monitor",
        "docent",
        "professor angles",
        "professor particular",
        "academia",
        "educador infantil",
        "monitor de lleure",
        "monitor menjador",
        "formador",
        "professor autoescola",
        "tecnic educacio infantil",
    ),
    "administrative": ("administratiu", "comptable", "secretari", "auxiliar administratiu"),
}


def feinaactiva_detail(session: requests.Session, ref: str) -> tuple[str, str, str]:
    """One Feina Activa offer as (title, company, verbatim text)."""
    detail = get(session, f"https://feinaactiva.gencat.cat/api/offers/{ref}").json()
    text = clean(
        "\n\n".join(
            [
                str(detail.get("description") or ""),
                str(detail.get("job") or ""),
                *[str(x) for x in detail.get("requirements") or []],
                *[str(x) for x in detail.get("conditions") or []],
            ]
        )
    )
    return str(detail.get("title", "")), str((detail.get("business") or {}).get("name", "")), text


def from_feinaactiva_family(
    session: requests.Session,
    family: str,
    limit: int,
    known: set[str] | None = None,
    known_texts: set[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Ads for one non-programming family, found by keyword and confirmed by title.

    `known` is the ids already in the corpus and `known_texts` the texts. Skipping both
    here rather than letting the caller drop them as duplicates is what makes a top-up run
    add anything: `limit` counts records **yielded**, so a record the caller will refuse
    still consumes the budget. `known` alone was not enough — `absorb` rejects on equal
    text as well as equal id (a cross-source repost keeps the board's own new reference),
    so a family could stop at its limit having added nothing.
    """
    base = "https://feinaactiva.gencat.cat/api/offers"
    refs: list[str] = []
    seen: set[str] = set()
    for keyword in FAMILY_KEYWORDS[family]:
        for offset in range(0, 100, 20):
            page = get(session, f"{base}/list?keywords={keyword}&limit=20&offset={offset}").json()
            hits = page.get("included", [])
            for offer in hits:
                ref = offer["reference"]
                if ref not in seen and classify_family(offer["content"]["title"]) == family:
                    seen.add(ref)
                    refs.append(ref)
            if len(hits) < 20:
                break
    count = 0
    for ref in refs:
        if count >= limit:
            return
        if known and f"feinaactiva-{ref}" in known:
            continue
        title, company, text = feinaactiva_detail(session, ref)
        # The list title is a summary; the detail title is the one the ad is filed under,
        # so the family is confirmed against that before the record is kept.
        if classify_family(title) != family:
            continue
        rec = record(
            f"feinaactiva-{ref}",
            "feinaactiva",
            f"https://feinaactiva.gencat.cat/search/offers/detail/{ref}",
            title,
            company,
            text,
            family,
        )
        if rec and (known_texts is None or rec["text"] not in known_texts):
            count += 1
            yield rec


def from_urls(session: requests.Session, urls: list[str], source: str) -> Iterator[dict[str, Any]]:
    """Any board that publishes schema.org JobPosting — used for the hand-picked CA ads."""
    for url in urls:
        posting = jobposting_ld(get(session, url).text)
        if not posting:
            print(f"  no JobPosting block: {url}", file=sys.stderr)
            continue
        slug = re.sub(r"\W+", "-", url.rstrip("/").rsplit("/", 1)[-1])[:60]
        rec = record(
            f"{source}-{slug}",
            source,
            url,
            str(posting.get("title", "")),
            str((posting.get("hiringOrganization") or {}).get("name", "")),
            clean(str(posting.get("description", ""))),
            "programming",
        )
        if rec:
            yield rec


def main() -> int:
    global DRAW
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--draw",
        required=True,
        help="id of the draw being executed, declared in corpus/draws.yaml (T98)",
    )
    ap.add_argument("--target-es", type=int, default=60)
    ap.add_argument("--target-en", type=int, default=25)
    ap.add_argument("--target-ca", type=int, default=15)
    ap.add_argument(
        "--target-family",
        type=int,
        default=15,
        help="ads per non-programming family (T25's floor is 15)",
    )
    ap.add_argument("--ca-urls", type=Path, help="file of Catalan ad URLs, one per line")
    ap.add_argument("--evidence", type=Path, default=Path("status/evidence/T4b.json"))
    ap.add_argument("--family-evidence", type=Path, default=Path("status/evidence/T25.json"))
    args = ap.parse_args()

    # Declared first, collected against second. Accepting an undeclared id here would put
    # the specification after the fact, which is how a harvest acquires a draw's name.
    declared = load_draws()
    if args.draw not in declared:
        print(
            f"draw {args.draw!r} is not declared in corpus/draws.yaml "
            f"(declared: {', '.join(sorted(declared)) or 'none'})",
            file=sys.stderr,
        )
        return 2
    DRAW = args.draw

    ads = {ad["id"]: ad for ad in load_ads()}
    texts = {ad["text"] for ad in ads.values()}
    session = requests.Session()

    def absorb(name: str, it: Iterator[dict[str, Any]]) -> None:
        added = 0
        for ad in it:
            if ad["id"] in ads or ad["text"] in texts:  # cross-source duplicate
                continue
            ads[ad["id"]] = ad
            texts.add(ad["text"])
            added += 1
        print(f"{name}: +{added}")

    plan = [
        ("es", "manfred", from_manfred, args.target_es),
        ("es", "tecnoempleo", from_tecnoempleo, args.target_es),
        ("en", "weworkremotely", from_weworkremotely, args.target_en),
        ("en", "remoteok", from_remoteok, args.target_en),
        ("en", "remotive", from_remotive, args.target_en),
        ("ca", "feinaactiva", from_feinaactiva, args.target_ca),
    ]
    # Policy before politeness: robots is asked per fetch inside `get()`, but a board
    # the ledger refuses is never planned in the first place.
    refused = plan_refusals(name for _, name, _, _ in plan)
    for name, why in sorted(refused.items()):
        print(f"{name}: not planned — {why}", file=sys.stderr)
    plan = [row for row in plan if row[1] not in refused]

    for lang, name, fetch, target in plan:
        missing = target - language_counts(list(ads.values()))[lang]
        if missing > 0:
            absorb(name, fetch(session, missing))

    for family in FAMILY_KEYWORDS:
        have = job_family_counts(list(ads.values())).get(family, 0)
        if have < args.target_family:
            absorb(
                family,
                from_feinaactiva_family(
                    session, family, args.target_family - have, set(ads), texts
                ),
            )

    if args.ca_urls and args.ca_urls.exists():
        lines = args.ca_urls.read_text().splitlines()
        urls = [u.strip() for u in lines if u.strip().startswith("http")]
        absorb("ca-urls", from_urls(session, permitted_urls(urls), "ca"))

    all_ads = list(ads.values())
    save_ads(all_ads)
    counts = language_counts(all_ads)
    print(f"total={len(all_ads)} {counts}")

    print(f"families={job_family_counts(all_ads)}")

    write_evidence(args.evidence, all_ads)
    write_family_evidence(args.family_evidence, all_ads)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
