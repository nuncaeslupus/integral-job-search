"""T224 — what makes two stored copies the same advert.

An offer's id is a hash of its text, and a list row's text changes between
searches, so one advert was stored once per search: 139 canonical urls held
378 extra copies in one candidate's tree. A rule-out, a rejection or a
tombstone recorded against one id then missed every other copy, and the
candidate was shown, the next day, two adverts he had discarded.

**The identity of an advert is its canonical url**, with the query string cut
down to the parameters its connector *declares* as identity
(`Connector.identity_query`). Declared, never inferred, and the two ways to be
wrong are not symmetric:

* keeping a parameter that is not identity splits one advert into several —
  fail-open, the ruled-out advert returns (JobFluent's `?result=21`, which is
  a position in the search, changes on every search);
* dropping a parameter that is identity merges several adverts into one —
  the second is never shown (talent.com's advert is `/view?id=<n>`).

So an undeclared connector keeps the whole query (what
`lifecycle.canonicalize_url` always did), and a declaration is re-checked
against every committed fixture in `tests/test_advert_identity.py`.

This module holds only the connector lookup and the query restriction.
`lifecycle.advert_identity` composes it with `canonicalize_url`.
"""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _host(url: str) -> str:
    """The host an advert url names, lowercased and without a leading `www.`.
    A protocol-relative or unparseable url has the host it has, or `""`."""
    try:
        host = urlsplit(url if "//" in url else f"//{url}").hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


@lru_cache(maxsize=1)
def _declarations() -> tuple[dict[str, tuple[str, ...] | None], dict[str, tuple[str, ...] | None]]:
    """(`site` -> declaration, `host` -> declaration) over every committed connector.

    A host several connectors serve adverts from takes the **conservative**
    reading of their declarations: `None` if any keeps the whole query,
    otherwise the union of the names they keep. Imported here rather than at
    module level: `connectors` is the larger module and nothing else in the
    offer path needs it loaded.
    """
    from integral.connectors import load_connectors

    by_site: dict[str, tuple[str, ...] | None] = {}
    by_host: dict[str, tuple[str, ...] | None] = {}
    seen: set[str] = set()
    for connector in load_connectors():
        by_site[connector.site] = connector.identity_query
        pattern = (
            connector.list.url_pattern.replace("{page}", "1")
            .replace("{query}", "q")
            .replace("{employer}", "a0")
        )
        for host in {_host(pattern), *(_host(h) for h in connector.serves_from)} - {""}:
            if host not in seen:
                seen.add(host)
                by_host[host] = connector.identity_query
                continue
            current = by_host[host]
            declared = connector.identity_query
            by_host[host] = (
                None
                if current is None or declared is None
                else tuple(sorted({*current, *declared}))
            )
    return by_site, by_host


def identity_query_for(url: str, source: str) -> tuple[str, ...] | None:
    """What the connector that owns `url`'s host declares.

    Resolved by the **board the url belongs to**, never by `Offer.source`: a
    `connect_manual` paste or a `web_search` hit of a JobFluent advert carries
    `?result=21` and is the same advert as the connector's copy. `source` is
    only the fallback for a url whose host no connector names. `None` (keep the
    whole query) is the answer for everything else — the direction that cannot
    hide an advert.
    """
    by_site, by_host = _declarations()
    host = _host(url)
    if host in by_host:
        return by_host[host]
    return by_site.get(source)


def restrict_query(canonical_url: str, names: Sequence[str] | None) -> str:
    """`canonical_url` with only the query parameters in `names` kept.

    `None` leaves the url alone. The input is already canonical (scheme and
    host lowercased, tracking removed, query sorted), so this only filters.
    """
    if names is None:
        return canonical_url
    parts = urlsplit(canonical_url)
    # Keys are folded to the declared lowercase spelling: `?ID=5` and `?id=5`
    # are one advert.
    kept = sorted(
        (k.lower(), v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() in names
    )
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
