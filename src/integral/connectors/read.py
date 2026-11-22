"""Loading connectors, interpreting recorded markup with one, and staleness.

Split out of `integral.connectors` unchanged (#928); the package re-exports every name.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import yaml
from pydantic import ValidationError

from integral.advert_link import advert_url
from integral.connectors._base import (
    _DNS_LABEL,
    CONNECTOR_FILENAME,
    DEFAULT_CONNECTORS_DIR,
    DEFAULT_STALE_AFTER_DAYS,
    DOT_SEGMENTS,
    EMPLOYER_PLACEHOLDER,
    EMPLOYER_SLUG,
    JSON_CONTENT_TYPE,
    PAGE_PLACEHOLDER,
    QUERY_PLACEHOLDER,
    SEARCH_SOURCE,
    ConnectorError,
    _employer_slot_problem,
    employer_in_host,
)
from integral.connectors.markup import (
    Node,
    SimpleSelector,
    compile_selector,
    parse_html,
    select_all,
    select_first,
)
from integral.connectors.model import (
    _CURRENCIES,
    Connector,
    FieldSelector,
    _as_float,
    _json_documents,
    _json_record,
    _present,
    _take,
    client_headers,
    compile_path,
    dig_container,
    serialise_body,
)
from integral.dimensions import Language
from integral.offers import Location, Offer, Salary, SourceKind, compute_offer_id
from integral.salary_period import normalize_period

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
    return [url for url, _ in _list_targets(connector, page_count=page_count, query=query)]


def _list_targets(
    connector: Connector, *, page_count: int | None, query: str | None
) -> list[tuple[str, str | None]]:
    """`build_list_urls`, each URL paired with the employer name it reads.

    Employer-major, so one employer's pages stay together (T144). With no
    employers the name is `None` and this is the page loop it always was.
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
        encoded = quote(query, safe="")
        # The same refusal, for the same outcome: in a path, §5.2.4 removes a
        # dot-segment query, so `…/ofertas-trabajo/../barcelona` is fetched as
        # `…/barcelona` and its unfiltered answer reads as a search. `urlsplit`
        # decides the component. In the query string `..` is a literal search.
        if encoded in DOT_SEGMENTS and QUERY_PLACEHOLDER in urlsplit(pattern).path:
            raise ConnectorError(
                f"{connector.site}: the query {query!r} is a dot-segment in "
                f"url_pattern's path, which RFC 3986 removes, so the request would "
                "carry no search terms"
            )
        pattern = pattern.replace(QUERY_PLACEHOLDER, encoded)
    if EMPLOYER_PLACEHOLDER in pattern:
        # Repeated from `ListPage` for the reason the clamp above is: a
        # `model_copy(update=...)` object never met the validator.
        problem = _employer_slot_problem(connector.list.url_pattern, connector.list.method)
        slug_shape = _DNS_LABEL if employer_in_host(connector.list.url_pattern) else EMPLOYER_SLUG
        bad = [s for s in connector.list.employers if not slug_shape.fullmatch(s)]
        if problem or bad:
            raise ConnectorError(f"{connector.site}: {problem or f'bad employer slug(s) {bad!r}'}")
    per_employer: list[tuple[str, str | None]] = (
        [
            (pattern.replace(EMPLOYER_PLACEHOLDER, quote(slug, safe="")), name)
            for slug, name in connector.list.employers.items()
        ]
        if EMPLOYER_PLACEHOLDER in pattern
        else [(pattern, None)]
    )
    return [
        (url.replace(PAGE_PLACEHOLDER, str(start + offset)), name)
        for url, name in per_employer
        for offset in range(pages)
    ]


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
    #: T144. The display name of the employer this request reads, from
    #: `list.employers` — never sent; the offer's `company` when the record
    #: names none. `None` for every board that is not an ATS host.
    employer: str | None = None
    #: The connector's declared `charset`: what the fetcher decodes the answer with
    #: (`decode_body`, refusing rather than replacing). Never sent.
    charset: str = "utf-8"


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

    The bodyless branch is a GET branch and says so (T110). It used to be
    reached by `method: POST` with no `body_json` as well, and emitted a POST
    with no `Content-Type` — a request no connector meant to describe.
    `_a_post_and_a_body_imply_each_other` now refuses that document at load,
    and the clamp is repeated here for the reason `build_list_urls` repeats
    its own: an object built with `model_copy(update=...)` never met a
    validator, so a property this module is asked to keep is kept where the
    request is actually made and not only where the file is read.
    """
    page = connector.list
    targets = _list_targets(connector, page_count=page_count, query=query)
    urls = [url for url, _ in targets]
    if page.body_json is None:
        if page.method != "GET":
            raise ConnectorError(
                f"{connector.site}: list.method is {page.method!r} with no list.body_json — "
                "the body is what a Content-Type is derived from, so this request would go "
                "out with none; declare body_json, or say method: GET"
            )
        derived = client_headers(page.client, page.client_target)
        return [
            ListRequest(
                url=url,
                method=page.method,
                headers=derived,
                body=None,
                employer=name,
                charset=connector.charset,
            )
            for url, name in targets
        ]
    if page.method != "POST":
        # The other half of the same clamp (T110). `_a_post_and_a_body_imply_each_other`
        # refuses this document too, and repeating only the bodyless-POST half here
        # would have left the validator symmetric and the builder not: an object made
        # with `model_copy(update=...)` could still reach this branch as a GET and be
        # issued with a body and a `Content-Type` — a request in a shape no connector
        # can declare, which is precisely what the clamp exists to make unreachable.
        raise ConnectorError(
            f"{connector.site}: list.body_json is declared but list.method is "
            f"{page.method!r} — only a POST carries a request body"
        )
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
            charset=connector.charset,
        )
        for offset, url in enumerate(urls)
    ]


def _select_after_text(root: Node, compiled: SimpleSelector, label: str) -> Node | None:
    """First node matching `compiled` whose previous element sibling's text is `label`."""
    for parent in (root, *root.iter_descendants()):
        elements = [c for c in parent.children if isinstance(c, Node)]
        for previous, current in pairwise(elements):
            if current.matches(compiled) and previous.text_content() == label:
                return current
    return None


def _extract(node: Node, selector: FieldSelector, compiled: SimpleSelector) -> str | None:
    if selector.after_text is not None:
        match = _select_after_text(node, compiled, selector.after_text)
    else:
        match = select_first(node, compiled)
    if match is None:
        return None
    if selector.attr is not None:
        value = match.attrs.get(selector.attr)
    elif selector.take == "first_text_node":
        # T305: the mirror image. foorilla's card puts the place first and a
        # marker span (`[R]`, `[WH]`) after it, so the first piece is the place.
        pieces = [piece.strip() for piece in match._iter_text() if piece.strip()]
        value = " ".join(pieces[0].split()) if pieces else None
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


def source_kind_of(connector: Connector) -> SourceKind | None:
    """What this connector's results are, relative to their employer (T172).

    Only what `connector.yaml` declares in `source_kind`. Nothing is inferred
    from the URL or its `{employer}` slot, and an undeclared board is `None`,
    never a guessed `"aggregator"`.
    """
    return connector.source_kind


def _declares(connector: Connector, field: str) -> bool:
    """Whether any of this connector's four field maps names `field`.

    "The board was asked for this and said nothing" is a different fact from
    "nobody asked", and `merged` cannot tell them apart: a `take` that refuses
    its value omits the key exactly as an unmapped field does.
    """
    for source in (connector.list, connector.detail):
        if source is None:
            continue
        if field in source.fields:
            return True
        if source.from_json is not None and field in source.from_json.fields:
            return True
    return False


def _outside_annual_bound(period: str | None, currency: str | None, *figures: float | None) -> bool:
    """A band with no period is bounded as annual — the rule `salary_recovery`
    already applies to a recovered band (`_band_defect`), now on the connector
    route too. `Salary(period=None)` is unlabelled on the card and uncomparable
    to a floor (`bulk_filter._below_pay_floor` skips it), so `9 € - 13 €` or
    `105 - 115 PLN` with the `/ h` left unread would be shown as the employer's
    own annual-looking number with its unit deleted. A connector whose board
    states the period declares `salary_period` and is unaffected.

    T214: the bound is the currency's own (`salary_recovery.bounds_for`), so an
    INR band is not refused for being a hundred times a euro one, and a
    currency whose scale is not on record is refused outright. A band that
    names **no** currency keeps the base scale — `usajobs_en` is the one
    package that maps a band and declares none.
    """
    if period is not None:
        return False
    from integral.salary_recovery import bounds_for  # late: salary_recovery imports this module

    # A board sends its own spelling (`€`, `eur`, or the code `take: currency`
    # already resolved, `BRL`); `_CURRENCIES` says which code that is, and a
    # spelling it does not list is a currency nobody can scale.
    code: str | None = "EUR"
    if currency and _present(currency):
        token = currency.strip().upper()
        code = _CURRENCIES.get(token) or (token if token in _CURRENCIES.values() else None)
    bounds = bounds_for(None, code)
    if bounds is None:
        return any(figure is not None for figure in figures)
    low, high = bounds
    return any(figure is not None and not low <= figure <= high for figure in figures)


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
    #
    # T170: `raw_period` is normalised to `offers.SalaryPeriod` here, once, for
    # every connector. A period the board *stated* but this vocabulary cannot
    # represent (Lever's `one-time`, or any label `salary_period.normalize_period`
    # does not recognise) is not "no period" — it is a wage this system refuses
    # to guess the unit of, so the whole salary is dropped rather than kept with
    # a blanked-out period. An *absent* `salary_period` field is unaffected:
    # `period` stays `None`, exactly as it did before this table existed.
    salary = None
    raw_period = merged.get("salary_period")
    period = normalize_period(raw_period)
    if _present(raw_period) and period is None:
        pass  # a stated, unrepresentable period — no salary at all (see above)
    else:
        minimum = _as_wage(merged.get("salary_min"))
        maximum = _as_wage(merged.get("salary_max"))
        currency = merged.get("salary_currency")
        # The period rule above, applied to the currency, and for the reason the
        # `_CURRENCIES` table was always documented as having: a connector that
        # asks for a currency and gets nothing back was told something its
        # closed table does not recognise, and a figure with no unit is not a
        # smaller error than no salary — it is a number a ranking will compare
        # against a band in euros. (`R$170K - R$190K` from an Ashby board was
        # this comment's worked example until T200 added `R$` to the table and
        # the example became a row that reads. The rule did not change; the
        # table did, which is the only way to stop dropping a real band.) A
        # connector
        # that declares no currency field at all is unaffected — `usajobs_en`
        # maps `MinimumRange` and no currency, and keeps reading it. (This
        # sentence named `ticjob_es` and `nofluffjobs_en` until T200 measured
        # it. It named the wrong pair: `ticjob_es` maps no band, and
        # `nofluffjobs_en` maps one now and declares its currency, so neither
        # is in that position. `usajobs_en` is the only package in the library
        # that is.)
        if not _present(currency) and _declares(connector, "salary_currency"):
            pass  # a stated, unreadable currency — no salary at all
        elif (minimum is not None or maximum is not None) and not _outside_annual_bound(
            period, currency, minimum, maximum
        ):
            salary = Salary(
                min=minimum,
                max=maximum,
                currency=currency,
                period=period,
                stated=True,
            )
    try:
        return Offer(
            id=compute_offer_id(text),
            source=connector.site,
            source_kind=source_kind_of(connector),
            source_ref=source_ref or merged.get("source_ref"),
            # T252: never the application form — see `advert_link`.
            url=advert_url([url, merged.get("url")]),
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
            url=advert_url([url]),  # T252: a search hit may be the form
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
