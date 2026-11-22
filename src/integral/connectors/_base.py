"""Declarative connector format, and the interpreter that runs it (T32).

"A hundred candidates each writing a scraper for the same job board is a
collective waste" (owner, 2026-08-18). The fix the owner chose is a library
people can borrow from, and the property that makes borrowing safe is the
title of this module: **a connector is data, not code.** One YAML file per
site names a list URL pattern, a detail URL pattern, pagination, and a
selector per normalised `Offer` (T11) field. *We* interpret it — a connector
file never runs.

## Why data and not a plugin

Borrowing a plugin means running a stranger's code on the machine where a
candidate's whole profile lives. Borrowing a connector file means running
**our** interpreter over **their** selectors, and the worst a malicious
contribution can do is return wrong text. `connector_executes_no_shared_code`
is the assertion, made mechanical the same way `dimensions.py` makes "a
dimension may not invent fields" mechanical: a closed, `extra="forbid"`
schema, plus — beyond what a dimension needs — a hand-rolled selector grammar
that is matched against, never evaluated. Concretely, nothing in this module
ever calls `eval`, `exec`, `compile`, `__import__`, `getattr` on a
connector-supplied name, or a subprocess/shell function with connector-
supplied text; `yaml.safe_load` is the only loader used, so a `!!python/…`
tag is refused before it can construct anything; and neither of the two
connector-controlled brace grammars ever reaches `str.format`, because a
connector-controlled format string is its own attribute-access injection
vector even though it never reaches `eval` — a `url_pattern`'s only
placeholder is substituted with `str.replace`, and a `detail_url_template`'s
slots are found with a regex, each one checked against the same `JSON_PATH`
every other path in the file must satisfy, and the values spliced in by hand
(`_templated_url`), with a leftover brace refused at load either way.
`probe_connector_isolation`
below tries each of these routes and asserts every one is refused — "the
gate is the reason" this module exists in this shape.

## What a connector may not do

* **Invent a field.** `Connector.model_config = extra="forbid"`, at every
  nesting level, is the same rule dimensions.py enforces on `dimensions/*.yaml`
  (§5.2's "connectors may not invent fields") — a typo'd or smuggled key is a
  load-time `ConnectorError`, never a silently-ignored setting. The selector
  fields themselves are further restricted to a fixed vocabulary
  (`ALLOWED_OFFER_FIELDS`) naming the `Offer` fields a markup selector could
  plausibly produce, plus `salary_text` for the phrase a band is stated in,
  so a field named `password` or `api_key` is
  rejected for not being one of them — before it is ever asked whether it
  *looks* like a credential.
* **Carry a credential.** There is no field anywhere in this schema for one.
  Authenticated sources drive the candidate's own browser session instead
  (spec-v2-process §2's step 7, Sourcing) — `auth: candidate_session` records
  that a site needs a signed-in session, and nothing more; see
  `AuthMode` and `test_authenticated_source_uses_the_candidate_session`.
  Two places in the schema are free-form enough to carry one anyway — a POST
  body's keys and a URL's query string — and `names_a_credential` lints both.
  For a long time it linted only the body, which is half a request: the
  board that motivated the rule, idealist.org, puts its credentials in the
  query string.
* **Run.** See above.

## What the format does not cover

Selectors run against markup that is already in the response. A site that
renders its listing or its ad body with JavaScript after load — many modern
boards — has nothing in that markup for a selector to match; this format
cannot reach it, and pretending otherwise would mean silently returning
nothing from a page that plainly has content. Such a site needs a heavier
mechanism (a headless browser) to justify itself later; it is not something a
connector file, however cleverly written, can be made to cover.

## Fetching is not this module's job

T12 is `[LAPTOP]` and owns turning a connector into HTTP requests against a
live site (a cloud session cannot reach one — 403 at the egress proxy,
confirmed 2026-08-15, per T11's module docstring). Everything here operates
on markup already in hand — a recorded fixture in a test, or, in T12's world,
a page T12 already fetched — via `parse_list_page` and `parse_detail_page`.

## Staleness

Every connector carries `version` and `last_verified`. `assess_staleness` and
`collect_listing` are how a caller learns that a connector has gone quiet
because nobody re-checked it, rather than because a search genuinely came back
empty — spec-v2-process's requirement that a stale connector is *reported*
stale rather than "quietly returning nothing".
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import SplitResult, parse_qsl, urlsplit

from pydantic import BaseModel, ConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"
# The one filename inside a connector package. Fixed, not derived: the package
# directory already carries the site name, and repeating it inside would give
# two places for it to disagree.
CONNECTOR_FILENAME = "connector.yaml"
META_FILENAME = "meta.yaml"
FIXTURE_DIRNAME = "fixture"

#: The connector's *second* capture of the same query, taken on a later day.
#: Beside `FIXTURE_DIRNAME` and never inside it: they are two reads at two
#: times, and one directory was the tautology `connector_health` exists to
#: avoid. Defined here so the contract and the health check cannot disagree
#: about what the directory is called.
PROBE_DIRNAME = "probe"
DEFAULT_EVIDENCE_PATH = _REPO_ROOT / "status" / "evidence" / "T32.json"

# A placeholder, not a policy: 90 days is a starting point the owner did not
# fix a number for. Kept as a parameter everywhere (never read as a bare
# constant deep in a call chain) so a future step spec can supply its own
# without this module changing.
DEFAULT_STALE_AFTER_DAYS = 90


class ConnectorError(Exception):
    """A connector file does not fit the declarative format, or cannot be
    interpreted safely — a load-time refusal, never a runtime crash deep in
    someone else's selector."""


class Strict(BaseModel):
    """Unknown keys are an error everywhere in this schema — see the module
    docstring's "may not invent a field"."""

    model_config = ConfigDict(extra="forbid", frozen=True)


SITE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")

# The `source` an offer carries when a general web search produced it rather
# than a connector (D-16). It is a reserved word in the `site` vocabulary, not
# merely a convention: `Connector` refuses it below, so no connector can ever
# claim the name, and `source` therefore stays a reliable answer to "where did
# this advert actually come from". Without the reservation, a connector called
# `web_search` would make the two indistinguishable in the stored record —
# which is the same confusion, one layer down, that D-16 is about.
SEARCH_SOURCE = "web_search"

# The whole vocabulary of things a connector may claim to extract: the fields
# `integral.offers.Offer` (T11) can hold, flattened for the nested
# `location`/`salary` objects, and one that is not an `Offer` field at all
# (`salary_text`, noted where it is listed). Anything else — `password`, `cookie`, a
# scraper's own internal bookkeeping — is rejected at load by the field
# validators below, not merely left unused.
ALLOWED_OFFER_FIELDS = frozenset(
    {
        "title",
        "company",
        "url",
        "source_ref",
        "text",
        "location_raw",
        "location_country",
        "location_remote",
        "salary_min",
        "salary_max",
        "salary_currency",
        "salary_period",
        # Not an `Offer` field: the element a board states its band *in*, for
        # the boards that print it as a phrase rather than as four values.
        # `tecnoempleo_es` writes "30.000\u20ac - 36.000\u20ac b/a" in a text node
        # sharing its element with the posting date, so `take: range_low` sees
        # five numbers and refuses — correctly, and to no one's benefit. What
        # reads that phrase is `salary_recovery.band_in_text`, which this module
        # cannot call (`salary_recovery` imports `_as_float` from here), so
        # `sourcing._offer_from` reads it on the way in and hands `build_offer`
        # the four values. Declaring it alongside `salary_min` is unsupported
        # and is NOT checked at load: `_with_stated_band` guards on the
        # *extracted* fields, so on a row where the mapped band fields extract
        # nothing the phrase would be read for that row alone, and on a row
        # where they extract it is ignored. No connector declares both.
        "salary_text",
    }
)
# `detail_url` is not an `Offer` field — it is the pointer from a list item to
# where the full ad lives — so it is added only for the list page's vocabulary.
LIST_FIELD_NAMES = ALLOWED_OFFER_FIELDS | {"detail_url"}

# The page's list-URL placeholder. Filled by `build_list_urls` via
# `str.replace`, never `str.format` — a connector-controlled format string
# would let `{0.__class__.__mro__[...]}`-style attribute access run before any
# `eval` is in the picture, so the placeholder is validated to be the only
# brace in the string and substituted literally.
PAGE_PLACEHOLDER = "{page}"

# The candidate's own search terms. Same substitution posture as `{page}` —
# `str.replace`, never `str.format` — and percent-encoded with `safe=""` at
# substitution so one encoder is correct whether the slot sits in a path
# segment or a query string. Without this a board's query is whatever its
# `url_pattern` was written with, so every candidate gets the same search.
QUERY_PLACEHOLDER = "{query}"

#: RFC 3986 §3.3's two dot-segments. `quote(value, safe="")` escapes every
#: reserved character, so a substituted value lands as one opaque segment,
#: except for these two: `.` is unreserved and survives whole. §5.2.4 then
#: removes the segment and moves the URL around it. Both builders that
#: substitute into a path refuse them: `_templated_url` for a record's value
#: and `build_list_urls` for the candidate's query.
DOT_SEGMENTS = frozenset({".", ".."})
# ponytail: URL slot only. `list.body_json` still admits `{page}` alone, so a
# POST board carrying its search in the body (only `usajobs_en` today) cannot
# be steered yet — widen `_body_uses_only_the_page_placeholder` when a second
# one lands.

# T144. One employer on an ATS host — Greenhouse, Lever, Ashby — whose boards
# all share one URL shape, so one connector reaches every employer it lists.
# Same substitution posture as the two above. Allowed in the URL **path** only,
# never the host: a slot in the host would make every employer its own origin,
# and the one robots verdict a package records would stop covering them.
EMPLOYER_PLACEHOLDER = "{employer}"
#: What an employer's slug may be before it is percent-encoded into the path.
#: Leading alphanumeric, so neither `.` nor `..` can be a whole segment.
EMPLOYER_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_KNOWN_PLACEHOLDER = re.compile(r"\{(?:page|query|employer)\}")
#: One request per employer per page, so the list is also a request count.
# ponytail: a fixed cap; per-run budgeting across packages if lists grow.
MAX_EMPLOYERS = 200


def safe_urlsplit(url: str) -> SplitResult | None:
    """`urlsplit(url)`, or `None` when `url` is not a parseable URL.

    `urlsplit` raises `ValueError` on a handful of malformed inputs — an
    unmatched IPv6 bracket (`https://[::1`) is the one every caller here has
    hit — rather than treating them as an ordinary parse failure. A bare call
    at the point of use ends the whole run instead of naming the one board,
    pattern or capture that sent it (#445 second reader, N6). One place reads
    the exception so no caller re-spells the try/except.
    """
    try:
        return urlsplit(url)
    except ValueError:
        return None


def _employer_slot_problem(pattern: str, method: str) -> str | None:
    """Why `{employer}` may not sit in `pattern`, or `None` when it may.

    Asked at load (`ListPage`) and again where URLs are built (`_list_targets`),
    because a `model_copy(update=...)` object never met the validator.
    The URL must be http(s) with a host of its own before the slot is
    trusted to sit in the path: `urlsplit` files a slot in the scheme, or
    before a bare host, under `path` (#445, second reader F8).
    """
    if pattern.count(EMPLOYER_PLACEHOLDER) != 1:
        return f"list.url_pattern may carry {EMPLOYER_PLACEHOLDER} once"
    if method != "GET":
        # `build_list_requests` numbers a POST's pages by request position,
        # which several employers would shift.
        return f"{EMPLOYER_PLACEHOLDER} is supported on a GET listing only"
    filled = safe_urlsplit(pattern.replace(EMPLOYER_PLACEHOLDER, "a0"))
    parsed = safe_urlsplit(pattern)
    if filled is None or parsed is None:
        return "list.url_pattern is not a URL"
    path = parsed.path
    hostname = filled.hostname
    # In the path, one origin serves every employer; as the host's first label
    # (Teamtailor), each employer is its own origin and sourcing asks each one's
    # robots.txt, so a refusal skips that employer alone.
    if (
        filled.scheme in ("http", "https")
        and hostname
        and (EMPLOYER_PLACEHOLDER in path or employer_in_host(pattern))
    ):
        return None
    return (
        f"{EMPLOYER_PLACEHOLDER} must sit in the path of an http(s) URL with a fixed "
        f"host, or be the whole first label of that host ({EMPLOYER_PLACEHOLDER}.example.com)"
    )


def employer_in_host(pattern: str) -> bool:
    """Whether `pattern` is `scheme://{employer}.<fixed domain>/…`.

    The slot must be the whole leftmost label, with at least two fixed labels
    after it, no port and no userinfo — so a filled slug can only ever name a
    subdomain of the one declared domain.
    """
    parsed = safe_urlsplit(pattern)
    if parsed is None or parsed.scheme not in ("http", "https"):
        return False
    prefix = EMPLOYER_PLACEHOLDER + "."
    netloc = parsed.netloc
    if not netloc.startswith(prefix):
        return False
    suffix = netloc[len(prefix) :]
    labels = suffix.split(".")
    return len(labels) >= 2 and all(_DNS_LABEL.fullmatch(label) for label in labels)


#: One DNS label (RFC 1123): what a slug must be when it fills a host.
_DNS_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


#: The `Content-Type` a JSON request body implies. Derived from the body's
#: declared form (`ListPage.body_json`) rather than being a header a connector
#: may set: a connector that could name headers could name `Authorization`,
#: and "a connector may not carry a credential" is a rule this schema keeps by
#: having nowhere to write one. See `build_list_requests`.
JSON_CONTENT_TYPE = "application/json"

#: Key names a request body may not use. Everywhere else in this schema "a
#: connector may not carry a credential" is kept structurally — there is no
#: field to write one in — but `body_json` is by necessity free-form data (a
#: board's search payload is the board's own vocabulary), so the rule needs a
#: check rather than an absence. This is admission lint and not a sandbox, the
#: same honesty `connector_contract`'s import allowlist states about itself: it
#: refuses a key that says what it is, and a determined contributor can call a
#: token `q`. What it does stop is the accident and the shrug — a board whose
#: payload really does want an `api_key` is a board this tool may not read, and
#: the refusal says so at load instead of after the secret is committed.
# ponytail: a name list, not a secret detector; entropy scanning of values is
# the upgrade path if a real key ever gets past this.
CREDENTIAL_KEY_TOKENS = frozenset(
    {
        "apikey",
        "auth",
        "authorization",
        "bearer",
        "cookie",
        "credential",
        "credentials",
        "csrf",
        "key",
        "pass",
        "passphrase",
        "passwd",
        "password",
        "pwd",
        "secret",
        "session",
        "token",
        "xsrf",
        # A signature or a one-time value is a credential the same way a token
        # is: possession of it is the whole authorisation.
        "hmac",
        "jwt",
        "nonce",
        "otp",
        "salt",
        "sig",
        "signature",
        # The identifier half of a credential *pair*. On its own it authorises
        # nothing, which is exactly why it reads as harmless and gets committed
        # — idealist.org's Algolia call carries an application id beside its
        # search key, and both were lifted from someone else's capture.
        "appid",
        "applicationid",
        "clientid",
        # Session cookies whose names are their own documentation.
        "aspxauth",
        "jsessionid",
        "phpsessid",
        "sessid",
    }
)

#: Words that are not a credential on their own but name one when they are
#: concatenated with a token above — `apitoken`, `privatekey`, `sessionid`.
#: Kept apart from the tokens so that a key called `id` or `user` is not
#: refused for existing.
CREDENTIAL_KEY_QUALIFIERS = frozenset(
    {
        "access",
        "api",
        "app",
        "client",
        "id",
        "private",
        "public",
        "refresh",
        "user",
        "x",
    }
)

#: `api_key`, `api-key`, `X-Api-Key`, `apiKey` — the separators a payload key
#: actually uses, plus the lowercase→uppercase boundary camelCase puts between
#: two words. A run of capitals (`SECRETKEY`) has no boundary to find, and
#: `apitoken` has no separator at all, which is what `_spells_a_credential`
#: below is for.
_KEY_SEPARATORS = re.compile(r"[^A-Za-z0-9]+|(?<=[a-z0-9])(?=[A-Z])")


@lru_cache(maxsize=4096)
def _spells_a_credential(word: str) -> bool:
    """Does this lowercase run of letters spell out a credential?

    A key may concatenate its words with nothing between them — `apitoken`,
    `secretkey`, `SECRETKEY` — so a separator-only split reads the whole thing
    as one unknown word and lets it through. `apikey` was already in the token
    list, which is the same class of hole patched one member at a time; this
    breaks the word instead.

    The break must be **total**: every piece has to be a word this module
    knows, and at least one of them a credential. That is what keeps `monkey`
    (`mon` is not a word here) and `keywords` (`words` is not) accepted while
    `secretkey` is refused — the alternative, a substring search, refuses
    every one of them.
    """
    vocabulary = CREDENTIAL_KEY_TOKENS | CREDENTIAL_KEY_QUALIFIERS
    # `broken[i]` — the ways `word[:i]` breaks cleanly into known words, as
    # "did any piece name a credential". Two states, so the walk stays linear
    # in the number of breakpoints rather than exploring every decomposition.
    broken: list[set[bool]] = [{False}] + [set() for _ in word]
    for end in range(1, len(word) + 1):
        for start in range(end):
            piece = word[start:end]
            if broken[start] and piece in vocabulary:
                names_one = piece in CREDENTIAL_KEY_TOKENS
                broken[end] |= {seen or names_one for seen in broken[start]}
    return True in broken[len(word)]


def names_a_credential(key: str) -> bool:
    """Does this key name a credential?

    Every contiguous run of the key's own words is tested, so a credential
    spelled across separators (`app_id`, `x-algolia-application-id`) is caught
    as well as one spelled inside a single word (`apitoken`).
    """
    words = [part for part in _KEY_SEPARATORS.split(key) if part]
    return any(
        _spells_a_credential("".join(words[start:end]).lower())
        for start in range(len(words))
        for end in range(start + 1, len(words) + 1)
    )


def credential_keys(node: Any) -> list[str]:
    """Every key anywhere in a parsed structure that names a credential."""
    if isinstance(node, dict):
        named = [key for key in node if isinstance(key, str) and names_a_credential(key)]
        return named + [key for value in node.values() for key in credential_keys(value)]
    if isinstance(node, list):
        return [key for item in node for key in credential_keys(item)]
    return []


def credential_query_keys(url: str) -> list[str]:
    """Every query-string key in `url` that names a credential.

    `url_pattern` is the *other* place a board's request can carry one, and
    for a long time nothing looked: the whole rule rested on `body_json`,
    which is only half of a request. idealist.org is the case that shows the
    half missing — its Algolia call puts both the application id and the
    search key in the query string, so a connector naming that URL carried a
    lifted credential past every check this module makes.
    """
    return [
        key
        for key, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True)
        if names_a_credential(key)
    ]
