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


@lru_cache(maxsize=1)
def _declarations() -> dict[str, tuple[str, ...] | None]:
    """`site` -> `identity_query`, for every committed connector.

    Imported here rather than at module level: `connectors` is the larger
    module and nothing else in the offer path needs it loaded.
    """
    from integral.connectors import load_connectors

    return {connector.site: connector.identity_query for connector in load_connectors()}


def identity_query_for(source: str) -> tuple[str, ...] | None:
    """What `source`'s connector declares, or `None` for a source no connector
    declares — `manual`, `web_search`, a board with no package. `None` keeps the
    whole query: the conservative direction is the one that cannot hide an
    advert."""
    return _declarations().get(source)


def restrict_query(canonical_url: str, names: Sequence[str] | None) -> str:
    """`canonical_url` with only the query parameters in `names` kept.

    `None` leaves the url alone. The input is already canonical (scheme and
    host lowercased, tracking removed, query sorted), so this only filters.
    """
    if names is None:
        return canonical_url
    parts = urlsplit(canonical_url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() in names]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), ""))
