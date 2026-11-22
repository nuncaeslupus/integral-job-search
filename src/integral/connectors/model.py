"""The connector schema, the JSON path vocabulary and character encodings.

Split out of `integral.connectors` unchanged (#928); the package re-exports every name.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date
from html import unescape
from typing import Any, Final, Literal
from urllib.parse import quote, unquote, urlsplit

from pydantic import Field, field_validator, model_validator

from integral.connectors._base import (
    _DNS_LABEL,
    _KNOWN_PLACEHOLDER,
    ALLOWED_OFFER_FIELDS,
    DOT_SEGMENTS,
    EMPLOYER_PLACEHOLDER,
    EMPLOYER_SLUG,
    LIST_FIELD_NAMES,
    MAX_EMPLOYERS,
    PAGE_PLACEHOLDER,
    SEARCH_SOURCE,
    SITE_NAME,
    VERSION,
    ConnectorError,
    Strict,
    _employer_slot_problem,
    credential_query_keys,
    employer_in_host,
    names_a_credential,
)
from integral.connectors.markup import (
    compile_selector,
    parse_html,
    select_all,
)
from integral.dimensions import Language
from integral.offers import SourceKind
from integral.salary_period import normalize_period

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
#: The two markup members (T169) are a different kind of partial extraction
#: from the three above: they do not pick a *part* of a value, they read the
#: value in the encoding the board published it in. `html_text` says the value
#: IS markup — greenhouse, workable, rippling, himalayas, workingnomads and
#: weworkremotely all publish an advert body as HTML inside a field — and
#: yields its text through the same `parse_html`/`text_content` an HTML
#: connector already reads an element with, so a JSON field and a CSS field
#: over the same markup produce the same string. `escaped_html_text` says the
#: value is HTML-*escaped* HTML (`&lt;p&gt;…&amp;nbsp;`), which is what
#: boards-api.greenhouse.io serves, and unescapes exactly once first.
#:
#: They are two members rather than one "unescape, then strip" member because
#: unescaping markup that was never escaped is lossy in a way no caller can
#: see: an advert saying `experience with &lt;canvas&gt;` is raw HTML carrying
#: an escaped literal, and unescaping it first turns that literal into a tag
#: and deletes the word.
Take = Literal[
    "range_low",
    "range_high",
    "currency",
    "period",
    "first_text_node",
    "last_text_node",
    "html_text",
    "escaped_html_text",
]

_TEXT_NODE_TAKES = ("first_text_node", "last_text_node")

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
    # T200. `ashby_en` publishes "R$170K - R$190K" and the two numbers were
    # already being read; only the currency was missing, and `build_offer`
    # drops a whole band whose declared currency did not resolve — so a board
    # that states its pay plainly was contributing none. Safe to add because
    # the guards this table already has do the work: the token is longer than
    # `$` so it is tried first, the lookbehind below blocks the bare `$` inside
    # it either way, and `_take`'s distinct-set rule collapses the two
    # occurrences to one. `bulk_filter` never compares a band against a floor
    # in another currency, so nothing downstream reads BRL as anything else.
    "R$": "BRL",
    # T200 second-reader round. `foorilla_en`'s cards print `INR 3000K-5000K` on
    # thirteen rows, and because the code was absent the audit's own detector —
    # derived from this table — could not see that those cards publish money, so
    # a wildcard verdict passed over a figure in a currency nothing could name.
    # The bounded-token guards above apply unchanged.
    "INR": "INR",
    "RON": "RON",
}

#: A currency token, bounded by ASCII letters on both sides. Substring matching
#: is what a closed table cannot afford: `CAD` inside `CADENCE` is a real figure
#: in the wrong currency — worse than the silence `take: currency` gives an
#: unknown one. The same guard is what lets `R$` and `$` coexist above: at the
#: `$` of `R$170K` the lookbehind sees an ASCII letter and refuses, so the bare
#: symbol cannot claim a Brazilian figure as dollars. Longest token first, so
#: `USD$` resolves once rather than twice and `R$` is tried before `$`.
_CURRENCY_TOKEN = re.compile(
    "|".join(
        rf"(?<![A-Z]){re.escape(token)}(?![A-Z])"
        for token in sorted(_CURRENCIES, key=len, reverse=True)
    )
)

#: A run that could be one number in either thousands convention, with an
#: optional magnitude suffix. Deliberately not anchored to a currency: boards
#: write `€50.000`, `50.000€` and `50.000 EUR`, and the number is the same in
#: all three.
_NUMBER = re.compile(r"(\d[\d.,]*)\s*(?:([KkMm])(?!\w))?")

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
    if take in ("html_text", "escaped_html_text"):
        # `unescape` exactly once, and only for the escaped member. Twice would
        # decode an advert's own escaped literal (`&amp;lt;canvas&amp;gt;`
        # arrives here meaning the text `&lt;canvas&gt;`), which is the same
        # deletion the single-member design was rejected for.
        markup = unescape(value) if take == "escaped_html_text" else value
        # The module's own reader, not a second HTML implementation: whatever
        # `text_content` does about whitespace, void tags and entities, a
        # markup-carrying JSON field now does identically to a CSS field over
        # the same markup. That identity is what the dedup margin rests on.
        text = parse_html(markup).text_content()
        # Fail-closed like every other member: markup that yields no text is
        # not a body, and `build_offer` drops an offer with no `text` rather
        # than showing the candidate a row of tags.
        return text or None
    if take == "currency":
        seen = {_CURRENCIES[token] for token in _CURRENCY_TOKEN.findall(value.upper())}
        # One currency, or none. A text naming two is a conversion or a
        # comparison, and either way nobody can say which one the pay is in.
        return seen.pop() if len(seen) == 1 else None
    if take == "period":
        # The word the card puts after `/` or `per` (`105 - 115 PLN / h`), and
        # only a word `normalize_period`'s closed table already accepts. One
        # distinct word or none: `/ h` beside `/ month` is two readings, and
        # two readings mean no reading. Returned as the board's own word, so
        # the one place a word becomes a period stays `normalize_period`.
        # Working time is not pay: `40 h/week`, `2 days per week`. The recovery
        # route's own `_WORKING_TIME` blanks the numbered forms; the bare
        # `days per week` is blanked here.
        from integral.salary_recovery import _WORKING_TIME  # late: circular import

        value = _BARE_WORKING_TIME.sub(" ", _WORKING_TIME.sub(" ", value))
        words = {w.casefold() for w in _PERIOD_AFTER_SLASH.findall(value)}
        words = {w for w in words if normalize_period(w) is not None}
        return words.pop() if len(words) == 1 else None
    return value


_BARE_WORKING_TIME = re.compile(
    r"\b(?:h|hrs?|hours?|days?)\s*(?:/|per|a)\s*(?:week|wk)\b", re.IGNORECASE
)

_PERIOD_AFTER_SLASH = re.compile(r"(?:/|\bper\b)\s*([A-Za-z]+)(?![A-Za-z])", re.IGNORECASE)


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
    #: T234. Why a selector that names a **build-generated class** is kept
    #: anyway. Absent, `ListPage` and `DetailPage` refuse such a selector at
    #: load (`generated_classes`); present, it is a stated, reviewable
    #: exception — the reason is the whole value and may not be blank.
    build_hash_accepted: str | None = Field(default=None, min_length=1)
    #: T254. Match only an element whose immediately preceding element sibling's
    #: text is exactly this label. For a page whose body carries no tag, id or
    #: data attribute but follows a stable human-readable heading.
    after_text: str | None = Field(default=None, min_length=1)

    @field_validator("build_hash_accepted")
    @classmethod
    def _the_reason_is_not_blank(cls, reason: str | None) -> str | None:
        if reason is not None and not reason.strip():
            raise ValueError("build_hash_accepted must say why, not be blank")
        return reason

    @field_validator("after_text")
    @classmethod
    def _the_label_is_in_normal_form(cls, label: str | None) -> str | None:
        # `Node.text_content()` collapses whitespace, so a label that is blank
        # or padded can never equal it: the connector would load and read nothing.
        if label is not None and label != " ".join(label.split()):
            raise ValueError(
                "after_text must be non-blank with single spaces and no padding, "
                "the form Node.text_content() gives"
            )
        return label

    @model_validator(mode="after")
    def _take_and_attr_are_compatible(self) -> FieldSelector:
        if self.take in _TEXT_NODE_TAKES and self.attr is not None:
            raise ValueError(
                f"take: {self.take} reads the element's text, so it cannot be "
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


#: T234. Class names a build tool generates, so any redeploy that touches the
#: stylesheet renames them and a selector built on one stops matching with no
#: error anywhere. Three families, each a closed shape rather than a guess:
#: styled-components (`sc-f4dbceab-10`), CSS modules (`JobCard_title__X32Qk`)
#: and emotion (`css-1a2b3c4`), plus styled-jsx (`jsx-1234567890`, a numeric
#: hash). Not covered, deliberately: styled-components v5's `sc-bdVaJa` and
#: emotion's labelled `css-xxxx-MuiBox-root` have no shape that cannot also be a
#: legitimate stable name (`sc-header`, `css-loader`), so a pattern for them would
#: refuse good selectors; they are left to review.
_GENERATED_CLASS = re.compile(
    r"^(?:sc-[A-Za-z0-9]{5,}-\d+|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9-]+__[A-Za-z0-9_-]{5}"
    r"|css-[a-z0-9]{5,8}|jsx-\d{6,})$"
)


def generated_classes(css: str) -> tuple[str, ...]:
    """The build-generated class names a selector is built on, in order.

    Read from `.class` tokens **and** from `[class="…"]` values: the attribute
    spelling names the same class, and checking only one spelling lets the other
    through unnoticed.
    """
    compiled = compile_selector(css)
    names = list(compiled.classes)
    for attr, value in compiled.attrs:
        if attr == "class" and value is not None:
            names.extend(value.split())
    return tuple(c for c in names if _GENERATED_CLASS.match(c))


def _refuse_unaccepted_generated_classes(
    section: str, selectors: dict[str, FieldSelector], item: str | None = None
) -> None:
    """Refuse, at load, any selector in `section` built on a generated class
    that does not carry `build_hash_accepted`. Derived from the selectors
    themselves, so a field added later is covered without anyone listing it."""
    found: list[str] = []
    for name, selector in selectors.items():
        if selector.build_hash_accepted is None and (hashed := generated_classes(selector.css)):
            found.append(f"{name}: {', '.join(hashed)}")
    if item is not None and (hashed := generated_classes(item)):
        found.append(f"item: {', '.join(hashed)}")
    if found:
        raise ValueError(
            f"{section} selector(s) built on a build-generated class, which the next redeploy "
            f"renames: {'; '.join(found)} — use a tag, id or data attribute, or state why "
            "not with `build_hash_accepted`"
        )


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

    "Rather than raising" is why the digit count is compared **before**
    `int(segment)`. CPython refuses to convert a decimal string of more than
    `sys.get_int_max_str_digits()` digits and raises `ValueError`, so an index
    of 4301 nines compiled cleanly and then blew up inside a walk whose whole
    contract is that out of range is a miss. The comparison needs no limit
    constant to be right: leading zeros are refused by the grammar, so a
    segment of more digits than `len(node)` has is necessarily larger than any
    index into `node`, and one of at most that many digits is small enough to
    convert.
    """
    node: Any = document
    for segment in path:
        if _INDEX_SEGMENT.fullmatch(segment):
            if not isinstance(node, list) or len(segment) > len(str(len(node))):
                return _MISSING
            index = int(segment)
            if index >= len(node):
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
        if encoded in DOT_SEGMENTS:
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


class JsonField(Strict):
    """One JSON field's rule: which path, and what to do with what it finds.

    The long form of a `fields` value. A plain string stays legal and means
    this with no `take` — every connector written before T169 is unchanged,
    and a file only grows a mapping where it has something more to say.
    """

    path: str = Field(min_length=1)
    #: The same closed vocabulary `FieldSelector.take` names, minus the one
    #: member that is about markup structure rather than about a value.
    take: Take | None = None

    @field_validator("path")
    @classmethod
    def _path_compiles(cls, path: str) -> str:
        try:
            compile_path(path)
        except ConnectorError as exc:
            raise ValueError(str(exc)) from exc
        return path

    @model_validator(mode="after")
    def _take_is_one_a_json_value_can_answer(self) -> JsonField:
        if self.take in _TEXT_NODE_TAKES:
            # It reads *one text piece of an element*, and a JSON scalar
            # has no elements. Refused at load rather than silently returning
            # the whole string at parse time, which would look exactly like a
            # `take` nobody asked for.
            raise ValueError(
                f"take: {self.take} reads a markup element's own text piece, and a "
                "JSON value has no elements — use html_text or escaped_html_text if the "
                "value carries markup"
            )
        return self


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
    #: name → path, or name → `{path, take}`. `_as_json_fields` widens the
    #: short form before anything else sees it, so there is one shape below.
    fields: dict[str, JsonField] = Field(min_length=1)

    @field_validator("fields", mode="before")
    @classmethod
    def _as_json_fields(cls, fields: Any) -> Any:
        if not isinstance(fields, dict):
            return fields
        return {
            name: {"path": value} if isinstance(value, str) else value
            for name, value in fields.items()
        }

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
    for name, field_ in source.fields.items():
        value = dig(document, compile_path(field_.path))
        if value is not None and field_.take is not None:
            # After `dig` and before `_present`: a `take` that answers nothing
            # leaves the field absent, the same as a path that found nothing.
            value = _take(field_.take, value)
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


def _query_key_position(key: str) -> str:
    """How a query-string key is named in a `url_pattern` position report.

    One function so the position the validator *wants* and the positions it
    *found* are spelled by the same code. Two format strings that have to agree
    is the drift `_page_placeholder_paths` was written to end on the body side.
    """
    return f"query key {key!r}"


#: How a `{page}` that is not a query-string value is named. There is no key to
#: name it by, which is precisely why `mode: path_segment` is certified by
#: matching the whole captured URL against the pattern instead.
_PAGE_OUTSIDE_QUERY = "outside the query string (the path, host or fragment)"

#: A `{page}` spelled into a query-string key's *own name*. Legal to
#: `_pattern_uses_only_the_page_placeholder`, and it makes the key itself vary
#: per page — so `pagination.param` can never name it and no capture can carry
#: it under a fixed spelling.
_PAGE_AS_QUERY_KEY_NAME = "a query-string key's own name"


#: `application/x-www-form-urlencoded`'s own pair separator — WHATWG URL
#: Standard §5, the parser behind `urllib.parse.parse_qsl`'s default, and the
#: reading a real request `build_list_urls` sends is actually parsed under.
#: `_url_page_positions` splits on this one alone, never on
#: `_QUERY_PAIR_SEPARATORS` below — see that constant's own docstring for why
#: sharing one reading between the two was round 2's regression.
_STRICT_QUERY_PAIR_SEPARATOR = re.compile(r"&")

#: Both `&` and `;` split a query string into `name=value` pairs, **for
#: counting occurrences of a name** — `query_pair_names`'s own reading, used
#: by route 4's duplicate-key check
#: (`_a_page_placeholder_and_a_query_key_imply_each_other`) and nothing else.
#:
#: RFC 3986 §3.4 draws no line on this: its ABNF for `query` is
#: `*( pchar / "/" / "?" )`, and it calls "key=value" pairs only a frequent
#: *usage*, never a grammar — `;` is simply a `sub-delim` the production
#: admits as ordinary query data. The pair grammar this file actually
#: depends on is `application/x-www-form-urlencoded`, which recognises only
#: `&` — `;` was HTML 4.01 Appendix B.2.2's documented historical alternate, and the
#: asymmetry is not merely historical: `urllib.parse.parse_qsl` itself grew a
#: `separator` parameter over exactly this ambiguity (CVE-2021-23336, a
#: parameter-injection weakness reachable precisely because callers disagreed
#: on which characters end a pair), so `;` is not a fringe reading invented
#: here — it is the one the standard library's own maintainers had to name.
#: This engine cannot know which reading a given board's server takes, and
#: `?page=1;page={page}` is a harm either way: a server that splits on `;`
#: sees `page` sent twice (T154's certified-duplicate harm), and one that
#: does not sees the single value `1;page=1` / `1;page=2` — never a page
#: number, so `page` never actually varies (T113 route 3's "identical
#: request" harm). Recognising both here, **for counting**, refuses the
#: shape under either reading rather than picking one, which is this file's
#: usual posture toward an ambiguous request (see `read_provenance` in
#: `pagination_capture` for another instance of the same choice).
#:
#: **"A wider count only ever finds more occurrences, never fewer" stood here
#: until round 5 (F3), and it is false — measured, not merely doubted.**
#: `query_pair_names` used to run a single split over this one pattern and
#: nothing else, and a single blended split does not just add match
#: candidates: splitting *on* a character also **fragments** any key name
#: that contains that character, which can only ever lose matches for that
#: name, never gain them. `?a;b=1&a;b={page}` with `pagination.param: "a;b"`
#: is the measured counter-example: splitting on `[&;]` cuts the literal key
#: `a;b` into two pieces, `a` and `b`, neither of which is `a;b`, so a name
#: that occurs **twice** in the real, `&`-only request counts as **zero**
#: occurrences under the permissive split alone — undercounting, not
#: overcounting, and the load-time rule missed the duplicate entirely.
#: `_query_key_occurrences` is the fix: it runs the strict and the permissive
#: readings **separately**, over the unmodified `query_pair_names`, and takes
#: the larger of the two counts, so a name the permissive split fragments is
#: still caught under the strict one that never touches it. Two independent
#: counts taken as a maximum are monotonic in the way one blended split is
#: not.
#:
#: **That safety argument does not carry to `_url_page_positions` (round 3,
#: R2 — a regression, not a design choice).** Deciding *where* the
#: placeholder sits is a single, committed reading, not a count: the
#: permissive union re-parses `?filter=a;page={page}` as two keys, `filter`
#: and `page` — exactly the shape an `&`-spelled capture of the real request
#: would show — while the wire request `build_list_urls` actually sends
#: still holds one key, `filter`, whose value is the literal text
#: `a;page=1` (no server this engine cannot assume splits on `;` ever sees a
#: second key). Sharing this constant with `_url_page_positions` let that
#: reading reach position-matching too: `?filter=a;page={page}` was refused
#: by route 1 at 42edcb7 and loaded at 53fb771, and against an `&`-spelled
#: capture of the real request, `pagination_capture.measure()`'s reading of
#: the identical connector moved from 1 (refused) to 0 (certified). So
#: `_query_pairs` takes the separator pattern as a parameter, defaulting to
#: `_STRICT_QUERY_PAIR_SEPARATOR`; only `query_pair_names` passes this one.
#:
#: **Taking the larger of the two counts of `param`'s own spelling is still
#: not the same claim as "the duplicate is always caught" (round 6, R3).**
#: `_query_key_occurrences`'s own docstring now says why in full:
#: `?a;b=1;a;b={page}` — no `&` at all — has the permissive reading fragment
#: `param: "a;b"` into `a` and `b`, and the placeholder lands on `b`, which
#: repeats; counting occurrences of the literal string `a;b` under either
#: reading reads **zero**, because that count was never asking about the key
#: the placeholder actually lands on.
#: `_placeholder_carrying_query_key_occurrences` counts that instead.
_QUERY_PAIR_SEPARATORS = re.compile(r"[&;]")


def _query_pairs(
    pattern: str, separators: re.Pattern[str] = _STRICT_QUERY_PAIR_SEPARATOR
) -> list[tuple[str, str]]:
    """`url_pattern`'s query string as raw `(name, value)` pairs.

    Split on `separators`, on the **raw** text — never on `parse_qsl`'s
    decoded values, for `_url_page_positions`'s reason: a percent-encoded
    separator or placeholder does not vary anything `build_list_urls`
    (`str.replace`) would actually substitute. Neither half of a pair is
    decoded here; a caller decodes whichever half it needs.

    Defaults to `_STRICT_QUERY_PAIR_SEPARATOR` (`&` alone) because that
    default is `_url_page_positions`'s own call — position-matching commits
    to one reading and may not use the permissive union
    (`_QUERY_PAIR_SEPARATORS`'s own docstring explains why, under "round 3,
    R2"). `query_pair_names` is the one caller that passes the permissive
    pattern explicitly.
    """
    query = urlsplit(pattern).query
    if not query:
        return []
    pairs: list[tuple[str, str]] = []
    for chunk in separators.split(query):
        raw_name, _, raw_value = chunk.partition("=")
        pairs.append((raw_name, raw_value))
    return pairs


def query_pair_names(
    pattern: str, *, separators: re.Pattern[str] = _QUERY_PAIR_SEPARATORS
) -> list[str]:
    """Every query-string key name in `pattern`, one entry per occurrence —
    percent-decoded the way `pagination.param` and `pagination_capture`'s
    `query_keys` both spell a name.

    Occurrences, **not** a set: a name repeated is exactly the phenomenon
    `_a_page_placeholder_and_a_query_key_imply_each_other`'s route 4 exists to
    count, so collapsing duplicates here would erase the numerator from the
    very function a caller measures a denominator over it with.

    Defaults to `_QUERY_PAIR_SEPARATORS` (the permissive `[&;]` union) — the
    default caller (route 4's occurrence count) reads under both readings
    separately (round 5, F3; see `_query_key_occurrences`) rather than
    trusting this one split alone, so `separators` exists to let that caller
    ask for the **strict** `&`-only reading too, over the same function
    rather than a second, drifting copy of it.
    """
    return [
        unquote(raw_name.replace("+", " ")) for raw_name, _ in _query_pairs(pattern, separators)
    ]


def _url_page_positions(pattern: str) -> list[str]:
    """Every position in `url_pattern` holding `{page}`, one entry per occurrence.

    The URL half of `_page_placeholder_paths`, and it exists for the same
    reason: "is the placeholder anywhere" is not the question. `build_list_urls`
    substitutes with `str.replace`, so it varies **every** occurrence — while
    `pagination.param` names exactly one query key and
    `integral.pagination_capture` certifies exactly that one against a recorded
    request. Any other occurrence is a page number going out in a field no
    capture measured, which is the fail-open shape T109 found in the body.

    Counted on the **raw** query text, never on `parse_qsl`'s decoded values:
    `?page=%7Bpage%7D` decodes to the placeholder but `build_list_urls` would
    never substitute it, so reading it as a page slot would bless a pattern that
    in fact issues the identical URL every time. Key *names* are decoded,
    because that is the spelling `pagination.param` and `pagination_capture`'s
    `query_keys` both use, and a name that only matches before decoding is not
    the key a capture carries.

    Split on `_STRICT_QUERY_PAIR_SEPARATOR` (`_query_pairs`'s default) —
    `&` alone, never the permissive `[&;]` union `query_pair_names` uses —
    because a *position* is a single committed reading of the query string,
    not a count: widening it here was round 2's regression (round 3, R2; see
    `_QUERY_PAIR_SEPARATORS`'s own docstring).
    """
    positions: list[str] = []
    accounted = 0
    for raw_name, raw_value in _query_pairs(pattern):
        name = unquote(raw_name.replace("+", " "))
        in_value = raw_value.count(PAGE_PLACEHOLDER)
        in_name = raw_name.count(PAGE_PLACEHOLDER)
        positions.extend([_query_key_position(name)] * in_value)
        positions.extend([_PAGE_AS_QUERY_KEY_NAME] * in_name)
        accounted += in_value + in_name
    positions.extend([_PAGE_OUTSIDE_QUERY] * (pattern.count(PAGE_PLACEHOLDER) - accounted))
    return positions


def _query_key_occurrences(pattern: str, folded_name: str) -> int:
    """How many times `folded_name` (already case-folded) names a query key
    **by its literal spelling** in `pattern`, measured under both readings of
    the pair separator and reported as the larger — round 5's fix for F3, and
    the reason `_QUERY_PAIR_SEPARATORS`'s docstring was wrong.

    A single split of the query string on the permissive `[&;]` union
    **fragments** any key name that itself contains `;` — `a;b` splits into
    `a` and `b`, neither of which is `a;b` — so a name spelled with a `;`
    could occur twice in the real, `&`-only request and count as zero under
    that one split. Running the strict `&`-only reading separately, over the
    same `query_pair_names`, never fragments that name (there is nothing to
    split it on), so a literal occurrence of `folded_name` there is not lost
    the way it can be under the permissive split alone. Taking the larger of
    the two is *monotonic* relative to a single blended split — it can only
    ever find a literal occurrence a blended split missed, never lose one a
    blended split found — but monotonic is not the same claim as *complete*.

    **What this still cannot see (round 6, R3): which key a given reading
    actually hands the placeholder to.** This function only ever asks "does
    the literal string `folded_name` occur," under each reading, in
    isolation from where `{page}` lands. When a reading fragments
    `folded_name` itself, the placeholder does not vanish — it lands on
    whatever fragment holds it, and that fragment can repeat under the exact
    same reading without ever being spelled `folded_name`
    (`?a;b=1;a;b={page}` with `folded_name` = `"a;b"`: the permissive
    reading's four pairs are `a`, `b`, `a`, `b` — `folded_name` occurs zero
    times, and the placeholder lands on `b`, which occurs **twice**). So a
    caller checking "is the key that will actually carry `{page}` under some
    reading duplicated under that reading" needs
    `_placeholder_carrying_query_key_occurrences` as well as this function;
    this one still answers a real, different question — "does `param`'s own
    declared spelling occur as a literal query key more than once" — which is
    exactly the question the modes with no legitimate query occurrence at all
    (`none`, `body_field`, `path_segment`) are asking.

    Compared case-insensitively (`folded_name` is expected pre-folded) for
    the reason `_a_page_placeholder_and_a_query_key_imply_each_other`'s own
    docstring gives: this library's POST-paginated boards are ASP.NET-shaped,
    and ASP.NET's `NameValueCollection` compares keys with an ordinal,
    case-insensitive comparer.
    """
    return max(
        sum(1 for name in query_pair_names(pattern) if name.casefold() == folded_name),
        sum(
            1
            for name in query_pair_names(pattern, separators=_STRICT_QUERY_PAIR_SEPARATOR)
            if name.casefold() == folded_name
        ),
    )


def _placeholder_carrying_query_key_occurrences(pattern: str) -> int:
    """How many times the query-string key that actually **carries
    `{page}`** repeats, measured once per reading of the pair separator and
    reported as the larger — round 6's fix for R3.

    `_query_key_occurrences` counts occurrences of `pagination.param`'s own
    *declared* spelling. That is the wrong measurement whenever a reading
    fragments that spelling: `?a;b=1;a;b={page}` with `pagination.param`
    `"a;b"` splits, under the permissive `[&;]` reading, into four pairs
    named `a`, `b`, `a`, `b` — none of them spelled `a;b`, so
    `_query_key_occurrences` reads **zero** under that reading. But the
    placeholder itself, under that identical reading, lands on the key `b` —
    and `b` occurs **twice**, once fixed (`b=1`), once varying (`b={page}`).
    That is the exact defect route 4 exists to refuse, invisible to a count
    of the wrong string: the measurement was of `param`'s name, but which key
    actually carries the placeholder is itself reading-dependent, and the two
    only coincide when a reading happens not to fragment `param`'s spelling.

    So this counts a different thing, independently for each reading: find
    whichever pair holds `{page}` under *that* reading (there is at most one
    such key per reading — the placeholder text itself contains none of the
    separator characters a reading could split on, so it is never itself torn
    across pairs), take that pair's decoded key name, and count how many
    pairs in that *same* reading share it, case-insensitively (`.casefold()`,
    for the comparator reason
    `_a_page_placeholder_and_a_query_key_imply_each_other`'s own docstring
    gives). A reading whose query does not carry the placeholder at all
    contributes nothing. The maximum across readings is what "the key that
    actually delivers the placeholder repeats, under some plausible reading
    of the request" requires — and unlike `_query_key_occurrences`, it never
    depends on `param`'s literal spelling surviving the split, because it
    never looks at `param` at all.
    """
    best = 0
    for separators in (_STRICT_QUERY_PAIR_SEPARATOR, _QUERY_PAIR_SEPARATORS):
        pairs = _query_pairs(pattern, separators)
        names = [unquote(raw_name.replace("+", " ")).casefold() for raw_name, _ in pairs]
        placeholder_keys = {
            names[index]
            for index, (raw_name, raw_value) in enumerate(pairs)
            if PAGE_PLACEHOLDER in raw_name or PAGE_PLACEHOLDER in raw_value
        }
        for key in placeholder_keys:
            best = max(best, names.count(key))
    return best


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
#:
#: T173 — `browser`. Some boards serve their listing only to a client that runs
#: their JavaScript check. Measured 2026-09-10 on infojobs.net: every search and
#: advert GET from this tool answers a 200 "No podemos identificar tu navegador"
#: page from the CDN edge, whatever the headers, while a real browser on the
#: same network passes the same check silently and renders the listing. No
#: header set can express that, and replaying the browser's token from a plain
#: client would be evading the check. So `browser` sends nothing from here:
#: `integral.sourcing` never hands such a board to the plain fetch at all, and
#: reads it only from a page the candidate's own browser rendered.
Client = Literal["htmx", "browser"]

#: The id `client_target` may hold: what an HTML `id` attribute looks like, and
#: nothing that could terminate a header or start a second one.
CLIENT_TARGET = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,63}$")


def client_headers(client: Client | None, target: str | None) -> dict[str, str]:
    """The fixed header set one named client sends. Empty for no client.

    Every name here is a literal in this module. A caller cannot reach this
    with a name of its own, which is the whole property being preserved.
    """
    if client is None or client == "browser":
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
        if self.client == "browser" and self.method != "GET":
            # T173. A browser capture is one page per URL, and a POST search's
            # pages share one URL — one capture would answer all of them.
            raise ValueError("client: browser reads saved pages, one per URL — only a GET")
        return self

    url_pattern: str = Field(min_length=1)
    #: The HTTP method the engine issues for this listing. `GET` by default,
    #: so every connector written before T89 is unchanged — a board whose
    #: search is a POST was simply unreachable, however public it was.
    #:
    #: `POST` and `body_json` imply each other, in both directions
    #: (`_a_post_and_a_body_imply_each_other`): a body without a POST cannot be
    #: sent, and a POST without a body has no declared form to derive a
    #: `Content-Type` from, so it would go out with none. There is therefore no
    #: legal bodyless POST — T110.
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

    @model_validator(mode="after")
    def _no_unaccepted_generated_classes(self):  # type: ignore[no-untyped-def]
        _refuse_unaccepted_generated_classes("list", self.fields, self.item)
        return self

    #: JSON route — for a board whose listing carries no advert markup at all.
    #: Named `from_json` rather than `json` because `json` is an attribute
    #: pydantic's `BaseModel` already defines.
    from_json: JsonSource | None = None
    #: T144. Slug → display name, one per employer an ATS host serves; the
    #: slug fills `{employer}`. The name is the offer's `company` when the
    #: record names none — Lever's and Ashby's postings never do. Data, not
    #: code: adding an employer is one line here.
    employers: dict[str, str] = Field(default_factory=dict)

    @field_validator("employers")
    @classmethod
    def _employers_are_slugs_with_names(cls, employers: dict[str, str]) -> dict[str, str]:
        if len(employers) > MAX_EMPLOYERS:
            raise ValueError(
                f"list.employers names {len(employers)} employers; at most {MAX_EMPLOYERS} — "
                "each one is a request on every run"
            )
        folded: set[str] = set()
        for slug, name in employers.items():
            if not EMPLOYER_SLUG.fullmatch(slug):
                raise ValueError(
                    f"list.employers slug {slug!r} must start with a letter or digit and hold "
                    "only letters, digits, . _ or - (at most 100)"
                )
            if slug.casefold() in folded:
                raise ValueError(
                    f"list.employers names {slug!r} twice, differing only in case — one "
                    "board fetched twice"
                )
            folded.add(slug.casefold())
            if not isinstance(name, str) or not name.strip() or len(name) > 120:
                raise ValueError(
                    f"list.employers[{slug!r}] needs a display name of 1-120 characters"
                )
        return employers

    @model_validator(mode="after")
    def _an_employer_slot_and_employers_imply_each_other(self) -> ListPage:
        # Both directions, as with `{page}`: a slot with no employers cannot be
        # filled, and employers with no slot are one URL fetched N times.
        slots = self.url_pattern.count(EMPLOYER_PLACEHOLDER)
        if bool(slots) != bool(self.employers):
            raise ValueError(
                f"list.url_pattern {'carries' if slots else 'lacks'} {EMPLOYER_PLACEHOLDER} "
                f"but list.employers is {'empty' if slots else 'not'} — each implies the other"
            )
        problem = _employer_slot_problem(self.url_pattern, self.method) if slots else None
        if problem:
            raise ValueError(problem)
        if slots and employer_in_host(self.url_pattern):
            bad = [s for s in self.employers if not _DNS_LABEL.fullmatch(s)]
            if bad:
                raise ValueError(
                    f"list.employers {bad!r} cannot fill a host: each must be one DNS label"
                )
        return self

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
        # One pass over all three, never a chain of `.replace`: removing one
        # placeholder can splice another out of what is left — `{emp{query}loyer}`
        # became `{employer}` and was then removed too, leaving a brace behind.
        bare = _KNOWN_PLACEHOLDER.sub("", pattern)
        if bare.count("{") or bare.count("}"):
            raise ValueError(
                "url_pattern may only use the literal {page}, {query} and {employer} "
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
    def _a_post_and_a_body_imply_each_other(self) -> ListPage:
        # Both directions, because the schema having an opinion about one of
        # them and none about the other is what T110 found. The default did
        # not move: a GET connector sends no body, and one that declares a
        # body has contradicted its own method rather than quietly getting a
        # body it cannot send.
        if self.body_json is not None and self.method != "POST":
            raise ValueError(
                f"list.body_json is declared but list.method is {self.method!r} — only a "
                "POST carries a request body"
            )
        # The other direction (T110). `Content-Type` is derived from the
        # declared body form and from nothing else — that is what stops a
        # connector naming a header — so a POST with no `body_json` is the one
        # shape this schema can express and the engine cannot send properly:
        # `build_list_requests` took its bodyless branch and produced
        # `method="POST"` with no `Content-Type`, which several back ends
        # answer 400 or 415 to. Refused rather than blessed: a body is what
        # makes a POST a POST here, so a POST without one is a connector file
        # that means a GET, and the cost of being wrong that way is a
        # contributor reading one error message. Blessing it would have meant
        # inventing a second content type for a request with no content.
        if self.method == "POST" and self.body_json is None:
            raise ValueError(
                "list.method is 'POST' but no list.body_json is declared — a POST carries a "
                "body, and its Content-Type is derived from that body, so a bodyless POST "
                "would go out with none; declare body_json, or say method: GET"
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

    @model_validator(mode="after")
    def _a_page_placeholder_and_a_query_key_imply_each_other(self) -> ListPage:
        """The URL half of the validator above — the half that was missing.

        `_a_page_placeholder_and_a_body_field_imply_each_other` binds
        `pagination.param` to the body key that actually varies. Nothing bound
        it to the **URL** key, and a request has two halves: found by the
        second-reader round on #406, which named three routes by which a package
        could send a page key `integral.pagination_capture` reads as measured
        while the gate reports zero. Each is reproduced as a probe in
        `pagination_capture.URL_SIDE_PROBES` and as a test fixture. A fourth
        route (T154) was found and deliberately kept out of that same diff so
        the first three could be verified on their own; it is checked first,
        below, before the per-mode dispatch that gave three routes their cover.

        1. **`param` naming a key the URL does not hold.**
           `?p={page}` with `param: page` over a capture of `?page=1` — the
           gate looks for `page` in the captured URL, finds it, and reports
           measured, while every request goes out carrying `p`. The certified
           key and the sent key were never required to be the same key.
        2. **`mode: none` with `{page}` still in the pattern.** `mode: none`
           short-circuits the gate ("the package sends no page key, so there is
           nothing to certify") — but `build_list_urls` substitutes on the text,
           so the connector still fetches `?page=1`, wholly unchecked.
        3. **`query_param` with no `{page}` anywhere.** Nothing varies, so the
           connector issues the *identical* URL `max_pages` times: the duplicate
           request, and then the duplicate offers, that `mode: none`'s own
           `max_pages` guard and `body_field`'s "nothing would vary" arm each
           already refuse one layer down.
        4. **The named key sent twice, or sent once where it has no business
           being sent at all — over every mode that names one, `none`
           included.** `?page=1&page={page}` under `mode: query_param` sends a
           second, wholly literal pair under the identical name; a capture of
           the request this issues still carries that name (that is what the
           literal pair supplies), so `pagination_capture.query_keys` — a
           *set* of names, not a count — certifies it regardless of which of
           the two positions a server actually reads. The first version of
           this check lived inside `if mode == "query_param":`, which is
           itself route 4's own shape one axis over: a POST board can name its
           **body** field `Page` while its **URL** happens to repeat `Page` in
           the query (`?Page=1&Page=2` beside `body_json: {Page: "{page}"}`),
           and a framework that merges query and body namespaces
           (`$_REQUEST`, Flask's `request.values`, Rails' `params`) may honour
           the fixed query occurrence over the varying body one — the same
           harm, reached because `mode: body_field` returned before this
           check was ever reached.

           **A *second* occurrence is only the `query_param` threshold, and
           treating it as the threshold for every mode was round 2's own gap
           (round 3, R1).** `query_param` is the one mode whose **one**
           legitimate occurrence lives in the query string — routes 1-3 below
           verify it is the placeholder itself — so a second one there is the
           defect. `body_field`'s legitimate occurrence lives in the *body*
           (`_a_page_placeholder_and_a_body_field_imply_each_other` requires
           exactly one); the query has no legitimate occurrence of that name
           at all under this mode, so `?Page=1` beside
           `body_json: {Page: "{page}"}` is the identical merged-namespace
           harm at a *single* occurrence, not two, and counting "more than
           one" missed it. The mirror is symmetric: a `query_param` board
           whose *body* carries a fixed, non-placeholder field spelling the
           same name (`body_json: {page: "1"}` beside `?page={page}`) puts the
           identical fixed value on the other half of a POST whose query
           already pages correctly, and nothing before this bound `param` to
           "at most one body key of that name" the way it already bound it to
           "at most one query occurrence." So the query-side count that
           matters is not "more than one" uniformly; it is **more occurrences
           than the declared mode accounts for**, checked once, ahead of the
           per-mode dispatch.

           **The body-side mirror covers `path_segment` too now, and round
           3's own scoping of it to `query_param` alone was unsound (round 4,
           NF2/NF3) — not a design choice this file can still defend.** Round
           3's premise was "`path_segment` binds `param` to a URL *position*
           a merged namespace never sees." That premise fails twice.
           First, nothing about `mode: path_segment` requires the sole
           `{page}` occurrence to actually sit outside the query string —
           the validator below only counts positions, so
           `url_pattern: .../jobs?o={page}` with `mode: path_segment` loads
           exactly as readily as one where `{page}` sits in the path, and the
           varying element there **is** a query-string value a merged
           namespace plainly does see. Second, even a *genuine* path segment
           is not the isolated position the premise claimed: Rails' `params`
           — named two paragraphs up as one of the merging namespaces this
           rule already guards against — merges `path_parameters` into the
           same hash as the query and body, so a router consuming a path
           segment "before any such merge happens" is not how Rails actually
           works. `page_placeholder`'s own R7 already treats `query_param`
           and `path_segment` as one case ("under any other mode —
           `query_param`, `path_segment` — it names a URL key"), and this
           rule must not draw a distinction R7 itself does not draw. A
           `body_json` field fixed at `param`'s name is therefore refused
           under `path_segment` exactly as it is under `query_param`; R7's
           own point — that the *builder* leaves such a field untouched —
           stays true and simply never gets exercised for a shape route 4
           refuses first, the same way it already doesn't for `query_param`.

           **The occurrence count on both halves is case-insensitive**
           (round 4, NF7), a second deliberate decision rather than an
           oversight. This library's POST-paginated boards are
           ASP.NET-shaped (`list.py`'s own scaffold document pages a field
           named `Page` against a `.../Search/ExecuteSearch`-style
           endpoint), and ASP.NET's own query and form collections
           (`NameValueCollection`) compare keys with an ordinal,
           case-**insensitive** comparer — so `?Page=1&page={page}` is the
           identical duplicate-key harm route 4 exists to catch, read by the
           one server family this rule is shaped for. Deciding otherwise —
           comparing `param` case-sensitively — would leave that exact shape
           loading, for a saving of nothing: the fail-closed cost of
           comparing case-insensitively is one contributor correction on a
           connector that never needed the second casing at all, which this
           file weighs below the fail-open cost everywhere else in this
           rule. `query_pair_names` and `body_json` keys are both compared
           this way; a case difference is not a different key here.

           **The comparator is `.casefold()`, not `.lower()` (round 6,
           R1/R2, reverting round 5's own swap).** Round 5 argued `.lower()`
           was "the closer match" to `NameValueCollection`'s ordinal,
           case-insensitive comparer because `.casefold()` merges
           `"straße"`/`"strasse"`, an equality `StringComparer
           .OrdinalIgnoreCase` does not hold. That argument was
           one-directional and the direction it skipped is the one that
           bit: `.lower()` does not merge `"ς"` (U+03C2, GREEK SMALL LETTER
           FINAL SIGMA) with `"\u03c3"` (U+03C3, GREEK SMALL LETTER SIGMA), while
           the cited comparer *does* — .NET's `ToUpperInvariant` sends both
           to `"Σ"`, and Unicode's own `CaseFolding.txt` lists `03C2; C;
           03C3;` (a *common* fold, not a `.casefold()`-only "full" one) —
           so `?ς=1&\u03c3={page}` with `pagination.param: "\u03c3"` loaded under
           `.lower()`, certified by a capture of either page's request,
           while the server this rule is modelled on reads `ς` and `\u03c3` as
           one key. `.lower()` is therefore not "the closer match" in
           general; it is narrower than the citation at `ς`/`\u03c3` (fail-open,
           the defect above) and *wider* than it at `İ`/`i`+U+0307 (both
           `.lower()` and `.casefold()` expand `"İ"` the identical way,
           fail-closed, and neither comparator escapes that one) — it
           differs from `NameValueCollection` in both directions, not one.

           **No Python builtin equals `OrdinalIgnoreCase`.** `.upper()`
           fares no better than `.casefold()` on the same axis it was meant
           to fix: `"straße".upper() == "STRASSE"`, the identical
           `ß`→`ss`-shaped merge `ToUpperInvariant` does not perform, so
           reaching for `.upper()` instead would not have been the honest
           fix either. Given that no built-in comparator is exactly
           `OrdinalIgnoreCase`, this file picks `.casefold()` and says so
           plainly: **the fold is deliberately wider than the cited
           comparer**, not a claimed match to it — and "wider," here, is
           checked against the cases this file has actually measured
           (`ς`/`\u03c3`, `ß`/`ss`, `İ`/`i`+U+0307), never asserted as a proven
           property of every Unicode codepoint. In each of those, `.casefold()`
           grants every equivalence `.lower()` does and at least one more —
           it has not been found to *miss* one `.lower()` catches, which is
           `.lower()`'s own failure mode at `ς`/`\u03c3`. That is a record of
           what has been checked, not a claim that no codepoint anywhere
           could invert it; a future finding that it does would be the next
           round, the same way this one was. The wider
           equivalences it grants beyond the citation cost one contributor
           correction on a connector that never needed the extra casing at
           all — a smaller, already-accepted fail-closed cost, not a new
           category of one, and pinned below (round 6) rather than argued
           over unpinned prose the way round 5's choice was (R2).

           **The named key sent twice inside `body_field`'s own body is now
           refused too (round 5, F1).** The check above used to ask only
           `any(...)` — "is a key of this name present in the body at all" —
           which is exactly the wrong question for `mode: body_field`
           itself: its own certified key is *always* present (that is what
           makes it certified), so membership could never tell that one
           legitimate occurrence apart from a second, differently-cased key
           fixed beside it. `body_json: {"Page": "{page}", "page": "1"}`
           loaded under that membership test — the paginating occurrence and
           a `page` fixed at `"1"` are the identical key to the
           `NameValueCollection` this rule already cites, and which one
           wins is exactly the ambiguity route 4 exists to refuse on the
           query side. Counting occurrences on the body half the same way
           the query half always did — and weighing the count against what
           each mode legitimately accounts for there (one for `body_field`,
           zero for `query_param` and `path_segment`) — replaces the
           membership test everywhere, so `body_field` is covered by the
           same check rather than by a mode exclusion that could never see
           its own duplicate.

           Query occurrences are counted by **occurrences of the name**
           (`query_pair_names`, over `&`- and `;`-separated pairs — see
           `_QUERY_PAIR_SEPARATORS`), not by positions of the placeholder: RFC
           3986 §3.4 does not define a `name=value` pair grammar at all (its
           `query` ABNF is `*( pchar / "/" / "?" )`, and it calls pairs only a
           frequent *usage*); the pair grammar this rests on is
           `application/x-www-form-urlencoded`, as `query_pair_names`
           implements it — see `_QUERY_PAIR_SEPARATORS`'s own docstring for
           why `;` is included beside the `&` that grammar alone would use,
           and for why that reading is **route 4's own reading and not
           `_url_page_positions`'s** (round 3, R2).

           **That count is now two readings, maxed, not one blended split
           (round 5, F3).** `_QUERY_PAIR_SEPARATORS`'s own docstring said a
           wider split "only ever finds more occurrences to refuse, never
           fewer" — false, measured: `?a;b=1&a;b={page}` with
           `pagination.param: "a;b"` splits the literal key `a;b` into `a`
           and `b` under the permissive union, so neither piece is `a;b` and
           a name that occurs **twice** in the real, `&`-only request counts
           as **zero**. `_query_key_occurrences` runs the strict and the
           permissive readings independently and takes the larger, so a name
           the permissive split fragments is still caught by the strict one.

           **Counting occurrences of `param`'s own spelling is still the
           wrong measurement for `mode: query_param` (round 6, R3) —
           `_query_key_occurrences`'s own docstring now says why, and it is
           not another reading added to the two above.** Which key a given
           reading hands the placeholder to is itself reading-dependent, and
           only coincides with `param`'s literal spelling when the reading
           does not fragment it: `?a;b=1;a;b={page}` — joined by `;` alone,
           no `&` anywhere — has the *permissive* reading fragment `a;b`
           into `a` and `b`, land the placeholder on `b`, and repeat `b`
           **twice**, while counting occurrences of the literal string
           `a;b` there reads zero (nothing is spelled `a;b`) and the
           *strict* reading, having no `&` to split on, treats the entire
           string as a single pair named `a;b` — matching `param` exactly
           once, which is legitimate on its own. Neither single count
           catches this: `param`'s occurrence count is 1 under the reading
           that has a duplicate and 0 under the one that does not, when the
           duplicate is actually there, under the permissive reading, on a
           *different* spelling of the key. `query_param`'s check is
           therefore the **max of two different measurements**, not one:
           `_query_key_occurrences` (does `param`'s own spelling repeat) and
           `_placeholder_carrying_query_key_occurrences` (does *whichever*
           key a reading actually attaches `{page}` to repeat, under that
           same reading) — the second needs no agreement with `param` at
           all, because the harm it catches (a fixed occurrence beside the
           varying one) does not depend on the varying key being spelled the
           way the connector's author wrote it.

           **Route 1, three routes up, did not follow NF7's widening, and
           now does (round 5).** It bound `pagination.param` to a query key
           by building the literal label `_query_key_position(param)` and
           checking it for membership in the placeholder's observed
           positions — a case-sensitive string comparison — so `param:
           "page"` against `url_pattern: ".../jobs?Page={page}"` was refused
           there as "not in a query-string value under that key" while route
           4, four paragraphs up, would treat `Page` and `page` as the one
           key an ASP.NET board reads them as. A rule-set cannot assert both
           that two spellings are the same key and that they differ; the
           direction is route 4's, because reverting it would restore the
           exact NF7 fail-open gap this file already chose to close, while
           bringing route 1 to case-insensitive costs only the shapes this
           section already accepted the cost of: a connector whose `param`
           casing happens to differ from its URL's, on a board that does not
           actually distinguish them, now loads instead of being refused for
           a difference the server it is modelled on does not see.

        Fail-closed in every direction, and it costs a contributor one error
        message in the file they just wrote.
        """
        positions = _url_page_positions(self.url_pattern)
        mode = self.pagination.mode
        param = self.pagination.param

        # Route 4 (T154), ahead of the per-mode dispatch below: an occurrence
        # of `param`'s own name anywhere in the merged query/body namespace
        # other than the one slot the declared mode actually binds it to is a
        # defect of the request, which every mode that names one (`none`
        # included) shares — it does not belong inside any one mode's branch,
        # and it is not just "more than one" uniformly (round 3, R1 — see the
        # docstring's item 4).
        if param is not None:
            # Compared case-insensitively (round 4, NF7; round 6 reverted
            # round 5's `.casefold()` -> `.lower()` swap — see the
            # docstring's paragraph on why): this library's POST boards
            # are ASP.NET-shaped, and ASP.NET's `NameValueCollection` compares
            # both its query and its form collections ordinally,
            # case-insensitively — so `?Page=1&page={page}` is the identical
            # duplicate-key harm this route exists to catch, and a
            # case-sensitive count would miss it for the one server family
            # this rule is modelled on. See the docstring's own paragraph on
            # this decision for the reasoning weighed against fail-closed.
            folded_param = param.casefold()
            # Two independent readings, maxed (round 5, F3) — see
            # `_query_key_occurrences`'s own docstring and
            # `_QUERY_PAIR_SEPARATORS`'s corrected one for why a single
            # blended `[&;]` split undercounts a `param` that itself contains
            # `;`.
            query_occurrences = _query_key_occurrences(self.url_pattern, folded_param)
            # The body-side mirror, by **count** now rather than membership
            # (round 5, F1): `any(...)` only ever answered "is `param` present
            # at all", which is exactly wrong for `mode: body_field` itself —
            # its own certified key is *always* present in the body, so a
            # membership test could never distinguish that one legitimate
            # occurrence from a second, differently-cased body key fixed
            # beside it (`body_json: {"Page": "{page}", "page": "1"}`, ASP.NET
            # reading both as the same form field). Counting occurrences and
            # weighing the count against what each mode legitimately accounts
            # for — the same shape the query half already used — closes that
            # gap without needing a mode exclusion at all.
            body_occurrences = sum(
                1
                for key in (self.body_json if isinstance(self.body_json, dict) else {})
                if isinstance(key, str) and key.casefold() == folded_param
            )
            if mode == "none":
                # `none` never varies at all, so there is no "legitimate
                # occurrence" to protect and no fixed value anywhere could be
                # honoured over a varying one that does not exist — a
                # *repeated* name in the query, or in the body, is still
                # refused, simply because two literal pairs sharing a name is
                # never a sensible connector, not for the merged-namespace
                # reason the other modes guard against. This branch is only
                # ever reached when `pagination.param` is set at all, which
                # `mode: none` never requires (round 4, NF5) — a `mode: none`
                # connector naming no `param` is untouched by this check,
                # however many times any query or body key repeats, so the
                # claim below is scoped to "the key `pagination.param`
                # names," never to query or body keys in general.
                if query_occurrences > 1:
                    raise ValueError(
                        f"list.url_pattern's query string names {param!r} "
                        f"{query_occurrences} times while pagination.mode is 'none' — "
                        "pagination.param names a key nothing under this mode ever varies, "
                        "so a repeated occurrence of it is a malformed request on its own, "
                        "independent of the merged-namespace reasoning below"
                    )
                if body_occurrences > 1:
                    raise ValueError(
                        f"list.body_json's top-level keys name {param!r} "
                        f"{body_occurrences} times while pagination.mode is 'none' — "
                        "pagination.param names a key nothing under this mode ever varies, "
                        "so a repeated occurrence of it is a malformed request on its own, "
                        "independent of the merged-namespace reasoning below"
                    )
            else:
                # The one legitimate query occurrence: `query_param` binds
                # `param` to a query key (routes 1-3, below, verify it is the
                # placeholder itself), so it accounts for exactly one; every
                # other mode binds `param` to something that is not a query
                # key at all (`body_field`'s body, or `path_segment`'s
                # position, which has no key), so the query has zero
                # legitimate occurrences under either.
                allowed_in_query = 1 if mode == "query_param" else 0
                # `query_param`'s own occurrence count is the max of two
                # different measurements, not one (round 6, R3 — see the
                # docstring's paragraph on why `_query_key_occurrences` alone
                # is not enough): `query_occurrences` asks whether `param`'s
                # own declared spelling repeats; `placeholder_key_occurrences`
                # asks, independently of `param`'s spelling, whether whichever
                # key some reading actually hands `{page}` to repeats under
                # that same reading. Only `query_param` has a legitimate
                # query occurrence to protect at all, so only it needs the
                # second measurement — `body_field` and `path_segment` are
                # covered by `query_occurrences` alone, exactly as before.
                placeholder_key_occurrences = (
                    _placeholder_carrying_query_key_occurrences(self.url_pattern)
                    if mode == "query_param"
                    else 0
                )
                effective_query_occurrences = max(query_occurrences, placeholder_key_occurrences)
                if effective_query_occurrences > allowed_in_query:
                    raise ValueError(
                        f"list.url_pattern's query string names {param!r} "
                        f"{effective_query_occurrences} time"
                        f"{'s' if effective_query_occurrences != 1 else ''}, "
                        f"but pagination.mode {mode!r} accounts for {allowed_in_query} "
                        "there (counting '&'- and ';'-separated pairs, under both "
                        "readings, and — for query_param — under whichever key a reading "
                        "actually hands the placeholder to) — a fixed occurrence no "
                        "capture ever measures decides the request instead of, or "
                        "alongside, the one that actually varies"
                    )
                # The body-side mirror, symmetric with the query check above
                # (round 5, F1) — `body_field`'s own certified occurrence
                # accounts for exactly one there; every other mode has none:
                # `query_param` binds `param` to a query key and
                # `path_segment` to a URL position, neither of which is a
                # body key at all.
                allowed_in_body = 1 if mode == "body_field" else 0
                if body_occurrences > allowed_in_body:
                    if mode == "body_field":
                        # The harm is now *within* the body's own top-level
                        # keys, not a second namespace: a second, merely
                        # differently-cased key beside the one
                        # `_a_page_placeholder_and_a_body_field_imply_each_other`
                        # already certified as holding the placeholder.
                        raise ValueError(
                            f"list.body_json's top-level keys name {param!r} "
                            f"{body_occurrences} times (counting case-insensitively), but "
                            f"pagination.mode {mode!r} accounts for {allowed_in_body} there "
                            "— a second, differently-spelled key sharing the certified "
                            "one's name is a fixed occurrence no capture ever measures, "
                            "decided by whichever a framework's merged form-field reading "
                            "honours"
                        )
                    # `query_param` / `path_segment`: a board whose POST body
                    # also carries a *fixed* (non-placeholder) field of the
                    # exact same name puts a value in the merged namespace
                    # that no capture ever measured, on the other half of the
                    # request — the harm F1 fixed for `body_field`'s own
                    # query occurrence, reached from the opposite direction.
                    # Covers `path_segment` beside `query_param` (round 4,
                    # NF2/NF3 — round 3 scoped this to `query_param` alone on
                    # a premise this file no longer defends; see the
                    # docstring's own paragraph on why).
                    raise ValueError(
                        f"list.body_json also declares {param!r}, fixed, alongside the "
                        f"occurrence pagination.mode {mode!r} already accounts for — a "
                        "framework that merges query and body namespaces ($_REQUEST, "
                        "Flask's request.values, Rails' params, which also merges "
                        "path parameters) may honour the body's fixed value over the "
                        "one that actually varies"
                    )

        if mode in {"none", "body_field"}:
            # Route 2, and its `body_field` mirror: a POST board declares that
            # the page number lives in the body, so a second one in the URL is
            # a substitution nothing declared — T109's finding, on the other
            # half of the request.
            if positions:
                raise ValueError(
                    f"list.url_pattern carries {PAGE_PLACEHOLDER} at "
                    f"{', '.join(sorted(positions))} but pagination.mode is {mode!r} — a URL "
                    "that paginates must say so with mode: query_param (or path_segment), "
                    f"and nothing certifies a page key sent under mode {mode!r}"
                )
            return self
        if mode == "query_param":
            wanted = _query_key_position(param) if param is not None else None
            if not positions:
                # Route 3.
                raise ValueError(
                    f"pagination.mode is 'query_param' but no {PAGE_PLACEHOLDER} placeholder "
                    "appears in list.url_pattern — nothing would vary from page to page, so "
                    "the identical URL would be requested max_pages times"
                )
            # Case-insensitive (round 5): route 4, three paragraphs of this
            # docstring up, treats `Page` and `page` as the same key so a
            # duplicate under either casing is caught — this route must agree
            # rather than treat them as different keys, or the rule-set would
            # assert both at once (round 5's finding: it did, until now). The
            # comparison is `.casefold()`, not `.lower()` (round 6 reverted
            # round 5's swap) — the docstring's paragraph on the comparator
            # says why.
            folded_wanted = wanted.casefold() if wanted is not None else None
            matches = [
                position
                for position in positions
                if folded_wanted is not None and position.casefold() == folded_wanted
            ]
            if not matches:
                # Route 1.
                raise ValueError(
                    f"pagination.param is {param!r} but {PAGE_PLACEHOLDER} sits at "
                    f"{', '.join(sorted(positions))} in list.url_pattern, not in a "
                    f"query-string value under that key — the key carrying the page number "
                    "is the one the pagination must name, and it is the one a capture is "
                    "read for"
                )
            extra = sorted(positions)
            extra.remove(matches[0])
            if extra:
                raise ValueError(
                    f"list.url_pattern holds {PAGE_PLACEHOLDER} at {', '.join(extra)} as well "
                    f"as at {wanted} — the key carrying the page number is the only one that "
                    "may hold the placeholder, so a second occurrence is a substitution "
                    "nothing declared"
                )
            return self
        # `path_segment`: the page number is positional, so there is no key to
        # bind `param` to and the capture rule is a whole-URL match instead
        # (`pagination_capture._path_segment_measured`). What still has to hold
        # is that something varies, and that only one thing does.
        if not positions:
            raise ValueError(
                f"pagination.mode is 'path_segment' but no {PAGE_PLACEHOLDER} placeholder "
                "appears in list.url_pattern — nothing would vary from page to page, so "
                "the identical URL would be requested max_pages times"
            )
        if len(positions) > 1:
            raise ValueError(
                f"list.url_pattern holds {PAGE_PLACEHOLDER} {len(positions)} times "
                f"({', '.join(sorted(positions))}) — a page number occupies one position, "
                "so a second occurrence is a substitution nothing declared"
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

    @model_validator(mode="after")
    def _no_unaccepted_generated_classes(self):  # type: ignore[no-untyped-def]
        _refuse_unaccepted_generated_classes("detail", self.fields)
        return self

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


#: RFC 1123 §2.1 labels, two or more of them. Spelled here rather than imported
#: from `reaction_elicit`, which answers the neighbouring question (what host does
#: this URL name) and may not import this module at all — `corpus_scope` bounds what
#: it reaches. `test_connectors` pins the two in two pieces, because they are two
#: rules: the label alphabet is asserted **equal as a string** to
#: `reaction_elicit._LABEL_RE.pattern`, and the compositions — a fullmatch here,
#: a split-and-count there — are compared over a population generated from the
#: grammar's axes. A list of boundary cases was round 4's finding: it left the
#: 63-octet cap and §2.1's alphabetic top-level label drifting one-sidedly and
#: green. The RFC 2606 reserved-TLD rule below is this module's alone, by design.
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
_SERVED_HOST_RE: Final = re.compile(rf"{_LABEL}(?:\.{_LABEL})+")

#: RFC 2606 §2. Reserved for documentation and testing; nothing is served from one.
RESERVED_TLDS: Final = frozenset({"test", "example", "invalid", "localhost"})


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
    #: T172. What this board is, relative to the employers whose adverts it
    #: carries: `employer` for the employer's own board. Declared, never
    #: inferred (T75). An `{employer}` slot alone does not say it, because a job
    #: board's company page takes one too (#462 second reader, F1).
    source_kind: SourceKind | None = None
    #: #558. Hosts this board serves its ADVERTS from, when an advert url does
    #: not name the host the listing was fetched from. An ATS lists from
    #: `api.ashbyhq.com` and returns advert urls on `jobs.ashbyhq.com`, so host
    #: equality against the list host refuses every ATS advert there is.
    #: `reaction_elicit.check_stimulus` matches an offer's url host against this
    #: set plus the list host; an undeclared host reads as forgery and is
    #: refused. Declared, never inferred (T75) — deriving it by allowing one
    #: label of slack off the list host admits `boards.greenhouse.io`, which
    #: `connectors/ruled-out.yaml` files under `robots_refused`. Whether robots
    #: permits a given advert url is a separate question, answered per url at
    #: fetch time by `sourcing._may_fetch`; this field is only about provenance.
    serves_from: tuple[str, ...] = ()
    #: T224. Which query parameters of an advert url are part of the advert's
    #: **identity**. `None` (undeclared) keeps the whole query, as
    #: `lifecycle.canonicalize_url` always has. `()` declares that nothing in
    #: the query names the advert (JobFluent's `?result=21` is a list position),
    #: so the identity is the url without it. `("id",)` keeps only that
    #: parameter (talent.com's advert is `/view?id=<n>`). Declared per
    #: connector, never inferred: dropping an identity parameter merges two
    #: adverts into one and hides the second, so the declaration is a claim
    #: about the board and `tests/test_advert_identity.py` re-checks it against
    #: every committed fixture.
    identity_query: tuple[str, ...] | None = None
    #: T236. Declares that adverts on this board may carry **no employer name**,
    #: and says why. `None` (the default) is the claim that every advert the
    #: board serves names its employer, and `tests/test_employer_published.py`
    #: re-checks it against every committed fixture: a connector whose own
    #: fixture yields an empty `company` fails unless it declares this, and one
    #: that declares it with no empty row left in its fixture fails too, so the
    #: declaration cannot outlive its cause. The reason is a sentence for the
    #: next reader; it must say whether the board genuinely withholds the name
    #: or the parser has not reached it yet. Sourcing counts the offers built
    #: with no employer per board either way (`BoardOutcome.no_employer`).
    employer_unpublished: str | None = None
    #: T236. The other way to have rows with no employer: the board DOES name
    #: one and this connector does not read it yet. Never an exemption — it
    #: names the open task (`T<n>`) that owns the fix, sourcing reports the
    #: board as a connector fault while it stands, and
    #: `tests/test_employer_published.py` fails once that task is merged so the
    #: key cannot outlive it. Mutually exclusive with `employer_unpublished`:
    #: a board either omits the employer or is missing a selector.
    employer_gap: str | None = None
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

    @field_validator("serves_from")
    @classmethod
    def _serves_from_are_already_hostnames(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        # A validator, never a repair. A declared
        # host reaches `reaction_elicit.check_stimulus` as a member of the set an
        # offer's url host is matched against, and that host arrives from
        # `urlparse(...).hostname`: lowercased, port stripped, scheme gone. So
        # anything that is not already in that spelling can never match, and the
        # two ways to be wrong point opposite ways. `https://jobs.lever.co`
        # silently matches nothing, which reads as "declared, still refused" and
        # sends the next session looking in the wrong module. Repairing it — strip
        # a scheme, drop a path, casefold — is the other direction and worse: what
        # a repair welds onto the string is a host nobody declared, and the field's
        # whole job is provenance. Refuse both here, where the file is loaded and
        # the error names the connector.
        for host in hosts:
            if host != host.lower() or _SERVED_HOST_RE.fullmatch(host) is None:
                raise ValueError(
                    f"serves_from: {host!r} is not a hostname — declare the host exactly as "
                    "an advert url spells it, lowercased and with no scheme, port or path"
                )
            if host.rsplit(".", 1)[-1] in RESERVED_TLDS:
                raise ValueError(
                    f"serves_from: {host!r} is under a reserved TLD (RFC 2606 §2) and resolves "
                    "nowhere — no advert is served from it"
                )
        return hosts

    @field_validator("employer_unpublished")
    @classmethod
    def _employer_unpublished_gives_a_reason(cls, reason: str | None) -> str | None:
        # A validator, never a repair: a bare `true`-shaped declaration is the
        # exemption with nothing behind it. Blank is refused, not defaulted.
        if reason is not None and not reason.strip():
            raise ValueError(
                "employer_unpublished: give the reason — a blank one exempts the "
                "board from the employer check and says nothing about why"
            )
        return reason

    @field_validator("employer_gap")
    @classmethod
    def _employer_gap_names_a_task(cls, task: str | None) -> str | None:
        # A validator, never a repair: `t235`, `T235 ` or a sentence would read
        # as a task and match nothing the plan can be checked against.
        if task is not None and re.fullmatch(r"T[0-9]+", task) is None:
            raise ValueError(
                f"employer_gap: {task!r} is not a task id — name the open task that owns "
                "the fix, as `T<n>`; a gap with no owner is just an exemption"
            )
        return task

    @model_validator(mode="after")
    def _a_board_omits_or_is_missing_a_selector(self) -> Connector:
        if self.employer_gap is not None and self.employer_unpublished is not None:
            raise ValueError(
                "employer_gap and employer_unpublished are exclusive: the board either "
                "does not publish an employer or this connector does not read it"
            )
        return self

    @field_validator("identity_query")
    @classmethod
    def _identity_query_names_are_parameter_names(
        cls, names: tuple[str, ...] | None
    ) -> tuple[str, ...] | None:
        # A validator, never a repair: a name that is not already a lowercase,
        # non-blank parameter name could never match the key it was meant for,
        # and a parameter that silently fails to match is dropped from the
        # identity — the merge this field exists to make deliberate.
        for name in names or ():
            if not name or name != name.strip().lower() or "=" in name or "&" in name:
                raise ValueError(
                    f"identity_query: {name!r} is not a lowercase query-parameter name"
                )
        return names

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
