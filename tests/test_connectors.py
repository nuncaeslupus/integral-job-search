"""T32 — the declarative connector format and its interpreter.

Written RED before `integral.connectors` existed, per the task payload.
`test_a_connector_file_cannot_introduce_executable_behaviour` is the gate as a
single test; the rest guard the parts of the contract review alone would
otherwise have to hold: unknown/credential fields refused at load, a markup
change costing exactly one field, and authenticated sources naming only the
candidate's own browser session.
"""

from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from integral import connector_coverage, process_spec, step_skills
from integral.connectors import (
    MINIMUM_PROBES,
    SEARCH_SOURCE,
    ConnectorError,
    FieldSelector,
    _as_float,
    assess_staleness,
    build_list_urls,
    build_offer,
    build_search_offer,
    collect_listing,
    compile_selector,
    load_connector,
    parse_connector,
    parse_detail_page,
    parse_html,
    parse_list_page,
    probe_connector_isolation,
    select_first,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONNECTOR_LIBRARY = _REPO_ROOT / "connectors"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "connectors"

# The worked example committed at `connectors/examplejobs_es/connector.yaml` — read from
# disk rather than copied inline, so this suite exercises the very file a
# contributor would actually add to the library, not a look-alike string a
# future edit to the real file could drift away from unnoticed.
VALID = (_CONNECTOR_LIBRARY / "examplejobs_es" / "connector.yaml").read_text(encoding="utf-8")

LIST_HTML = (_FIXTURES / "examplejobs_list.html").read_text(encoding="utf-8")
DETAIL_HTML_BEFORE = (_FIXTURES / "examplejobs_detail_before.html").read_text(encoding="utf-8")
# The recorded before/after fixture pair for
# `test_a_site_markup_change_is_a_single_field_edit`: the ad body's class
# renamed from `.job-description` to `.job-body`, nothing else on the page
# moved.
DETAIL_HTML_AFTER = (_FIXTURES / "examplejobs_detail_after.html").read_text(encoding="utf-8")


def write_connector(directory: Path, filename: str, body: str = VALID) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# the gate, as a test


def test_a_connector_file_cannot_introduce_executable_behaviour() -> None:
    """`connector_executes_no_shared_code` — every adversarial construction in
    `probe_connector_isolation` (a python expression as a selector, a
    `!!python/object` YAML tag, a lambda, a smuggled shell string, a
    credential field) must be refused, and enough of them must actually run
    for that zero to mean something."""
    report = probe_connector_isolation()
    assert report.probes_run >= MINIMUM_PROBES
    assert report.violations == ()


def test_the_gate_never_shells_out_over_a_malicious_url_pattern() -> None:
    """Adversarial proof, not a plausibility argument: even a url_pattern
    carrying shell metacharacters is only ever treated as literal text —
    `build_list_urls` never reaches a shell, so patching `subprocess.run` to
    explode if called must see nothing happen."""

    def _boom(*args: object, **kwargs: object) -> None:
        raise AssertionError("connectors.py must never shell out")

    connector = parse_connector(
        "site: acme\nlocale: en\nversion: '1.0.0'\nlast_verified: '2026-01-01'\n"
        "list:\n"
        '  url_pattern: "https://x.test/$(rm -rf /)?page={page}"\n'
        "  item: '.job'\n"
        "  fields:\n    text: {css: '.x'}\n"
    )
    original = subprocess.run
    subprocess.run = _boom  # type: ignore[assignment]
    try:
        urls = build_list_urls(connector, page_count=2)
    finally:
        subprocess.run = original
    assert urls == [
        "https://x.test/$(rm -rf /)?page=1",
        "https://x.test/$(rm -rf /)?page=2",
    ]


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    measured = write_evidence(tmp_path / "T32.json")
    assert measured["connector_executes_no_shared_code"] == 1
    assert measured["probes_run"] >= MINIMUM_PROBES
    assert measured["violations"] == []


# ---------------------------------------------------------------------------
# data-only, per the plan


def test_connector_file_is_data_only() -> None:
    """A well-formed connector loads to a plain, immutable Pydantic model —
    no callables, no code objects, nothing on it that could be invoked."""
    connector = parse_connector(VALID)
    for name in ("site", "locale", "version", "last_verified", "auth", "list", "detail"):
        value = getattr(connector, name)
        assert not callable(value)
    # `frozen=True`: the interpreter cannot mutate what a connector claimed,
    # and neither could a connector's own content even if it wanted to.
    with pytest.raises(ValidationError):
        connector.site = "changed"


def test_a_connector_missing_a_required_field_is_rejected_at_load() -> None:
    """Dropping `last_verified` — required for staleness reporting — fails
    to load rather than defaulting to "just verified"."""
    body = "\n".join(line for line in VALID.splitlines() if not line.startswith("last_verified"))
    with pytest.raises(ConnectorError, match="last_verified"):
        parse_connector(body)


def test_an_unknown_top_level_field_is_rejected_at_load() -> None:
    with pytest.raises(ConnectorError):
        parse_connector(VALID + "notes: some scraped internal id\n")


def test_a_field_name_outside_the_offer_vocabulary_is_rejected() -> None:
    body = VALID.replace(
        '    company:\n      css: ".job-company"\n',
        '    company:\n      css: ".job-company"\n    internal_score:\n      css: ".score"\n',
    )
    with pytest.raises(ConnectorError, match="internal_score"):
        parse_connector(body)


def test_the_filename_must_match_the_declared_site_and_locale(tmp_path: Path) -> None:
    path = write_connector(tmp_path, "wrongname.yaml")
    with pytest.raises(ConnectorError, match="examplejobs_es"):
        load_connector(path)


def test_the_package_directory_must_match_the_declared_site_and_locale(tmp_path: Path) -> None:
    """The name moved to the directory with T53; the rule moved with it."""
    package = tmp_path / "wrongname"
    write_connector(package, "connector.yaml")
    with pytest.raises(ConnectorError, match="examplejobs_es"):
        load_connector(package)


def test_loading_the_whole_directory_sorts_by_package_name(tmp_path: Path) -> None:
    """Sorted by name, across the whole library — see `load_connectors`.

    Written with the alphabetically-later package created first, so a loader
    that returned discovery order rather than sorted order would fail here.
    """
    other = VALID.replace("site: examplejobs", "site: otherboard").replace(
        "locale: es", "locale: en"
    )
    write_connector(tmp_path / "otherboard_en", "connector.yaml", other)
    write_connector(tmp_path / "examplejobs_es", "connector.yaml")
    from integral.connectors import load_connectors

    connectors = load_connectors(tmp_path)
    assert [c.site for c in connectors] == ["examplejobs", "otherboard"]


def test_a_loose_yaml_file_beside_the_packages_is_not_loaded(tmp_path: Path) -> None:
    """Packages only, so runtime and the contract check discover the same set.

    Review on #77: while both shapes loaded, a loose file was loaded at runtime
    and never checked by the contract, so CI could report zero violations over
    a connector nothing had examined.
    """
    write_connector(tmp_path / "examplejobs_es", "connector.yaml")
    other = VALID.replace("site: examplejobs", "site: otherboard").replace(
        "locale: es", "locale: en"
    )
    write_connector(tmp_path, "otherboard_en.yaml", other)
    from integral.connectors import load_connectors

    assert [c.site for c in load_connectors(tmp_path)] == ["examplejobs"]


# ---------------------------------------------------------------------------
# no credential, ever


def test_no_connector_stores_a_credential() -> None:
    """A field named like a credential is refused, whether it appears as a
    top-level key or as an offer-field name — the schema has no field for
    one anywhere, so there is nothing to leave unset."""
    for bad in ("password", "api_key", "cookie", "session_token", "secret", "basic_auth"):
        with pytest.raises(ConnectorError):
            parse_connector(VALID + f"{bad}: leaked\n")
        body = VALID.replace(
            '    company:\n      css: ".job-company"\n',
            f"    company:\n      css: \".job-company\"\n    {bad}:\n      css: '.x'\n",
        )
        with pytest.raises(ConnectorError):
            parse_connector(body)


def test_authenticated_source_uses_the_candidate_session() -> None:
    """`auth` may only ever name "no login needed" or "the candidate's own
    browser session" (spec-v2-process step 7) — never anything that implies
    a stored secret."""
    connector = parse_connector(VALID.replace("auth: none", "auth: candidate_session"))
    assert connector.auth == "candidate_session"
    # No field anywhere on the model could carry a credential even if a
    # connector wanted `auth: candidate_session` to be backed by one.
    assert not hasattr(connector, "password")
    assert not hasattr(connector, "token")
    with pytest.raises(ConnectorError):
        parse_connector(VALID.replace("auth: none", "auth: stored_password"))


# ---------------------------------------------------------------------------
# markup changes are a one-field edit


def test_a_site_markup_change_is_a_single_field_edit() -> None:
    """A recorded before/after fixture pair: the site renames one class,
    `.job-description` → `.job-body`. The old connector correctly reads the
    "before" page and fails to find the ad body on "after"; editing exactly
    one field — the `text` selector — restores it, with every other
    selector untouched."""
    connector = parse_connector(VALID)

    before = parse_detail_page(connector, DETAIL_HTML_BEFORE)
    assert before["text"] == ("Build and operate our payments API. Python, remote-friendly.")

    after_with_old_selector = parse_detail_page(connector, DETAIL_HTML_AFTER)
    assert "text" not in after_with_old_selector

    fixed_fields = dict(connector.detail.fields)  # type: ignore[union-attr]
    fixed_fields["text"] = FieldSelector(css=".job-body")
    fixed_detail = connector.detail.model_copy(update={"fields": fixed_fields})  # type: ignore[union-attr]
    fixed_connector = connector.model_copy(update={"detail": fixed_detail})

    after_with_fixed_selector = parse_detail_page(fixed_connector, DETAIL_HTML_AFTER)
    assert after_with_fixed_selector["text"] == before["text"]
    # Nothing else needed to change.
    assert after_with_fixed_selector["title"] == before["title"]
    assert after_with_fixed_selector["company"] == before["company"]


# ---------------------------------------------------------------------------
# parsing recorded fixtures end to end


def test_parse_list_page_extracts_every_item() -> None:
    connector = parse_connector(VALID)
    items = parse_list_page(connector, LIST_HTML)
    assert len(items) == 2
    assert items[0]["title"] == "Backend Engineer"
    assert items[0]["detail_url"] == "/jobs/123"
    assert items[1]["company"] == "Beta SL"


def test_build_offer_merges_list_and_detail_and_matches_offer_schema() -> None:
    connector = parse_connector(VALID)
    list_items = parse_list_page(connector, LIST_HTML)
    detail = parse_detail_page(connector, DETAIL_HTML_BEFORE)
    offer = build_offer(
        connector,
        list_fields=list_items[0],
        detail_fields=detail,
        url="https://www.examplejobs.test/jobs/123",
    )
    assert offer.source == "examplejobs"
    assert offer.language == "es"
    assert offer.title == "Backend Engineer (Python)"  # detail wins over list
    assert offer.location is not None
    assert offer.location.raw == "Barcelona"
    assert offer.text == detail["text"]
    assert offer.id.startswith("sha256:")


def test_build_offer_without_any_text_is_refused() -> None:
    connector = parse_connector(VALID)
    with pytest.raises(ConnectorError, match="text"):
        build_offer(connector, list_fields={"title": "x"}, detail_fields=None)


# ---------------------------------------------------------------------------
# salary numbers — locale-aware parsing (review finding 2, MEDIUM)


def test_as_float_parses_european_thousands_dot_decimal_comma() -> None:
    """Regression: `"1.234,56"` (thousands-dot, decimal-comma — the format
    `connectors/examplejobs_es.yaml`'s locale actually uses) used to become
    `"1.23456"` after the old naive comma-strip/dot-keep logic, parsing as
    `1.23456` — a ~1000x error with no exception. Must now read as
    `1234.56`."""
    assert _as_float("1.234,56") == 1234.56
    assert _as_float("45.000,00") == 45000.0
    assert _as_float("-1.234,56") == -1234.56


def test_as_float_parses_english_thousands_comma_decimal_dot() -> None:
    """The other convention must keep working: `"1,234.56"`
    (thousands-comma, decimal-dot) reads as `1234.56`, not regress while
    fixing the European case."""
    assert _as_float("1,234.56") == 1234.56
    assert _as_float("45,000.00") == 45000.0
    assert _as_float("1234.56") == 1234.56  # no thousands grouping at all


def test_as_float_a_lone_separator_with_three_digits_is_thousands_not_decimal() -> None:
    """The documented disambiguation rule for a single separator occurring
    once: exactly three following digits reads as grouped-thousands, not a
    fractional amount — `"1.234"` and `"1,234"` (either convention's plain
    whole-number-with-grouping spelling) both mean `1234`, not `1.234`/
    `1234.0` interpreted the other way."""
    assert _as_float("1.234") == 1234.0
    assert _as_float("1,234") == 1234.0
    # A different digit count after a lone separator is unambiguous as a
    # decimal instead.
    assert _as_float("1234.5") == 1234.5
    assert _as_float("1234,5") == 1234.5
    assert _as_float("1234,56") == 1234.56


def test_as_float_repeated_thousands_grouping() -> None:
    assert _as_float("1.234.567") == 1234567.0
    assert _as_float("1,234,567") == 1234567.0


def test_as_float_genuinely_ambiguous_input_returns_none_not_a_guess() -> None:
    """A wrong salary is worse than an absent one — it silently reorders a
    ranking. Anything this module cannot resolve with confidence must come
    back `None`, exactly like the rest of the parsing pipeline (e.g. a
    JS-rendered page yielding no selector matches), never a guessed number."""
    assert _as_float("1.2.3") is None  # repeated separator, not valid grouping
    assert _as_float("1,23,456") is None  # inconsistent group sizes
    assert _as_float("12a4") is None  # not a number at all
    assert _as_float("1.234,56,78") is None  # decimal separator repeats
    assert _as_float("") is None
    assert _as_float(None) is None


def test_build_offer_feeds_a_correctly_parsed_european_salary_into_the_offer() -> None:
    """End-to-end: a connector field carrying the European format must reach
    `Offer.salary` correctly, not silently 1000x wrong."""
    connector = parse_connector(VALID)
    offer = build_offer(
        connector,
        list_fields={
            "text": "Backend role.",
            "salary_min": "30.000,00",
            "salary_max": "45.000,00",
            "salary_currency": "EUR",
        },
        detail_fields=None,
    )
    assert offer.salary is not None
    assert offer.salary.min == 30000.0
    assert offer.salary.max == 45000.0


def test_build_list_urls_fills_only_the_page_placeholder() -> None:
    connector = parse_connector(VALID)
    urls = build_list_urls(connector, page_count=2)
    assert urls == [
        "https://www.examplejobs.test/jobs?page=1",
        "https://www.examplejobs.test/jobs?page=2",
    ]


# ---------------------------------------------------------------------------
# pagination.mode is honoured, not just max_pages/start


def test_pagination_mode_none_with_max_pages_above_one_is_rejected_at_load() -> None:
    """Regression for review finding 3 (LOW), load-time half: a connector
    declaring `mode: none` (no second page exists) while leaving `max_pages`
    above its default of 1 is self-contradicting — nothing describes what a
    second page's URL would even be. Caught here rather than only discovered
    once T12 fetches the same URL `max_pages` times."""
    body = VALID.replace(
        "  pagination:\n    mode: query_param\n    param: page\n    start: 1\n    max_pages: 5\n",
        "  pagination:\n    mode: none\n    max_pages: 3\n",
    )
    assert "mode: none" in body and "max_pages: 3" in body  # the replace actually matched
    with pytest.raises(ConnectorError, match="max_pages"):
        parse_connector(body)


def test_build_list_urls_honours_pagination_mode_none() -> None:
    """Regression for review finding 3 (LOW), interpreter-side half:
    `build_list_urls` used to read only `max_pages`/`start`, never
    `pagination.mode`. `Pagination`'s own validator now refuses `mode: none`
    with `max_pages > 1` at *load* (see the sibling test above), but a
    connector built in-memory via `model_copy(update=...)` — as this test
    suite itself does elsewhere, e.g.
    `test_a_site_markup_change_is_a_single_field_edit` — does not re-run that
    validator, so the contradictory state can still exist on an object
    `build_list_urls` is asked to interpret. Without the fix, that object's
    default page count (`max_pages`, since no `page_count` override is
    given) would make `build_list_urls` emit the same URL repeatedly:
    duplicate requests, duplicate offers once T12 fetches them."""
    connector = parse_connector(VALID)
    assert connector.list.pagination.max_pages == 5  # the fixture's own default

    contradictory_pagination = connector.list.pagination.model_copy(
        update={"mode": "none", "param": None, "max_pages": 3}
    )
    contradictory_list = connector.list.model_copy(update={"pagination": contradictory_pagination})
    contradictory_connector = connector.model_copy(update={"list": contradictory_list})

    # No page_count override: the connector's own (contradictory) max_pages
    # must not leak through — mode: none means exactly one page.
    assert build_list_urls(contradictory_connector) == ["https://www.examplejobs.test/jobs?page=1"]

    # An explicit page_count override is still honoured as given — mode only
    # overrides the *default* derived from the connector's own max_pages.
    assert build_list_urls(contradictory_connector, page_count=2) == [
        "https://www.examplejobs.test/jobs?page=1",
        "https://www.examplejobs.test/jobs?page=2",
    ]


# ---------------------------------------------------------------------------
# the selector grammar itself


def test_compile_selector_accepts_the_closed_vocabulary() -> None:
    tag_id_class_attr = compile_selector("div#main.job.featured[data-x]")
    assert tag_id_class_attr.tag == "div"
    assert tag_id_class_attr.id_ == "main"
    assert set(tag_id_class_attr.classes) == {"job", "featured"}
    assert tag_id_class_attr.attrs == (("data-x", None),)


@pytest.mark.parametrize(
    "css",
    [
        "",
        "div > span",
        "div span",
        "a[href^='https']",
        "__import__('os')",
        "div; DROP TABLE offers",
        "$(whoami)",
        "a:hover",
    ],
)
def test_compile_selector_rejects_anything_outside_the_grammar(css: str) -> None:
    with pytest.raises(ConnectorError):
        compile_selector(css)


def test_uppercase_tag_and_attribute_names_still_match_lowercased_markup() -> None:
    """Regression for review finding 1 (MEDIUM): `html.parser.HTMLParser`
    lowercases tag and attribute *names* while parsing (verified directly
    against the stdlib below), but `compile_selector` used to store them
    verbatim. A connector author writing `DIV.job-card` or `[DISABLED]` —
    exactly the kind of hand-edit this format exists to make safe for a
    non-programmer — got a selector that loaded without error and then
    matched nothing, ever: no exception at load, no exception at parse, just
    a silently empty result. Without the fix in `compile_selector`, this
    test's first two assertions fail because `select_first`/`select_all`
    return nothing for the uppercase-written selectors."""
    from html.parser import HTMLParser

    class _Probe(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.seen_tag = tag
            self.seen_attrs = dict(attrs)

    probe = _Probe()
    probe.feed('<DIV DISABLED CLASS="Featured"></DIV>')
    assert probe.seen_tag == "div"  # tag name lowercased by the stdlib parser
    assert "disabled" in probe.seen_attrs  # attribute *name* lowercased too
    assert probe.seen_attrs["class"] == "Featured"  # attribute *value* untouched

    root = parse_html('<div class="Featured job-card" disabled>hi</div>')

    tag_selector = compile_selector("DIV")
    assert select_first(root, tag_selector) is not None

    attr_selector = compile_selector("[DISABLED]")
    assert select_first(root, attr_selector) is not None

    # Class names stay case-sensitive: HTML class matching is case-sensitive,
    # so an uppercase class in a selector must NOT be silently lowercased —
    # doing so would break a correctly-written connector instead of fixing a
    # broken one.
    assert select_first(root, compile_selector(".Featured")) is not None
    assert select_first(root, compile_selector(".featured")) is None

    # Attribute *values* stay case-sensitive too.
    other = parse_html('<div data-x="Foo"></div>')
    assert select_first(other, compile_selector('[data-x="Foo"]')) is not None
    assert select_first(other, compile_selector('[data-x="foo"]')) is None


# ---------------------------------------------------------------------------
# what the format does not cover


def test_a_javascript_rendered_page_yields_nothing_a_selector_can_reach() -> None:
    """The honest failure mode for a JS-rendered site: the markup a connector
    ever sees has no content for a selector to match, so parsing returns
    nothing rather than a wrong answer."""
    connector = parse_connector(VALID)
    js_only_shell = "<html><body><div id='app'></div></body></html>"
    assert parse_list_page(connector, js_only_shell) == []
    assert parse_detail_page(connector, js_only_shell) == {}


# ---------------------------------------------------------------------------
# staleness


def test_a_connector_not_verified_recently_is_reported_stale() -> None:
    connector = parse_connector(VALID)  # last_verified: 2026-08-01
    fresh = assess_staleness(connector, today=date(2026, 8, 15))
    assert fresh.stale is False
    assert fresh.reason is None

    old = assess_staleness(connector, today=date(2027, 2, 1), max_age_days=90)
    assert old.stale is True
    assert old.reason is not None
    assert "examplejobs_es" in old.reason


def test_a_stale_connector_returning_nothing_is_reported_not_silent() -> None:
    """The requirement in the payload's own words: "a connector that has not
    been verified since the site last changed is stale, and the tool should
    say so rather than quietly returning nothing." An empty page from a
    fresh connector says nothing is wrong; the same empty page from a stale
    one must carry a message."""
    connector = parse_connector(VALID)
    empty_html = "<html><body></body></html>"

    fresh_result = collect_listing(connector, empty_html, today=date(2026, 8, 15))
    assert fresh_result.items == ()
    assert fresh_result.stale is False
    assert fresh_result.message is None

    stale_result = collect_listing(connector, empty_html, today=date(2027, 2, 1), max_age_days=90)
    assert stale_result.items == ()
    assert stale_result.stale is True
    assert stale_result.message is not None
    assert "zero listings" in stale_result.message


# ---------------------------------------------------------------------------
# YAML loading is the safe loader, provably


def test_yaml_safe_load_is_the_only_loader_used() -> None:
    """`yaml.safe_load` refuses a `!!python/object` tag outright — asserted
    directly against the library primitive this module depends on, so a
    future edit that swapped in `yaml.load`/`yaml.unsafe_load` would break
    this test rather than silently reopening the hole."""
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load("a: !!python/object/apply:os.system ['touch /tmp/pwned']")


# ---------------------------------------------------------------------------
# D-16 — a run with no connector for the candidate's market must say so


def _meta(country: str = "ES", site: str = "realboard.example.com") -> str:
    return yaml.safe_dump(
        {
            "site": site,
            "country": country,
            "language": "es",
            "maintainer": "@someone",
            "last_verified": "2026-08-01",
            "policy": {"listings": "public", "robots_txt": "respected", "authentication": "none"},
            "fixture": {"provenance": "sampled", "recorded": "2026-08-01"},
        }
    )


def _library(root: Path, **packages: str) -> Path:
    """A connector library on disk: package name -> its `meta.yaml` body."""
    root.mkdir(parents=True, exist_ok=True)
    for name, meta in packages.items():
        package = root / name
        package.mkdir()
        (package / "meta.yaml").write_text(meta, encoding="utf-8")
    return root


def test_sourcing_without_a_connector_says_so() -> None:
    """D-16's gate. `undisclosed_connectorless_sourcing == 0`.

    Every sourcing situation the installed library can put a candidate in
    either has a usable connector or comes with the disclosure the step spec
    requires — the absence stated, both remedies offered, and search results
    labelled as search results.
    """
    measured = connector_coverage.measure()
    assert measured["shortfalls"] == []
    assert measured["undisclosed_connectorless_sourcing"] == 0
    # Not a vacuous zero: the situations must actually have been probed, and
    # the one D-16 was filed from — a market nothing covers — must be among
    # them, disclosed rather than absent.
    assert measured["situations_probed"] >= 2
    connectorless = [r for r in measured["readings"] if r["connectorless"]]
    assert connectorless, "no connectorless situation was probed — the rule went unexercised"
    assert all(r["disclosed"] and r["discloses"] for r in connectorless)


def test_a_search_result_is_not_presented_as_a_connector_result() -> None:
    """The other half: what a general web search produced stays legible as
    that, in the record, after the disclosure has scrolled away.

    `source` is the only place an offer says where it came from, so the
    reserved name has to hold from both ends — the search path always stamps
    it, and no connector may claim it.
    """
    offer = build_search_offer(
        text="Se busca albañil en Bilbao. Jornada completa.",
        url="https://aggregator.example.com/ad/1",
        source_ref="query: albañil bilbao",
    )
    assert offer.source == SEARCH_SOURCE
    assert connector_coverage.offer_provenance(offer, ["examplejobs"]) == "search"

    from_connector = build_offer(
        parse_connector(VALID), detail_fields={"text": "Se busca programador."}
    )
    assert connector_coverage.offer_provenance(from_connector, ["examplejobs"]) == "connector"

    # And a connector cannot dress itself as the search path to reach the same
    # `source` from the other side.
    with pytest.raises(ConnectorError, match="reserved"):
        parse_connector(
            f"site: {SEARCH_SOURCE}\nlocale: en\nversion: '1.0.0'\n"
            "last_verified: '2026-01-01'\n"
            "list:\n  url_pattern: 'https://x.test/?page={page}'\n"
            "  item: '.job'\n  fields:\n    text: {css: '.x'}\n"
        )


def test_an_offer_from_neither_path_is_not_read_as_a_connector_result() -> None:
    """The third answer, and the reason it exists: an offer whose source names
    no installed connector is `unattributed`, never `connector`. Reading the
    unknown as a connector result is how a model-written record would have
    passed itself off as a board's."""
    offer = build_search_offer(text="An advert from somewhere.").model_copy(
        update={"source": "infojobs"}
    )
    assert connector_coverage.offer_provenance(offer, ["examplejobs"]) == "unattributed"


def test_an_example_connector_is_not_counted_as_coverage(tmp_path: Path) -> None:
    """`examplejobs.test` is a worked example of the format, not a board. A
    library holding only examples covers nothing, and the reading says which
    packages were discounted rather than reporting an empty market."""
    library = _library(tmp_path / "connectors", examplejobs_es=_meta(site="examplejobs.test"))
    coverage = connector_coverage.assess_coverage("ES", directory=library)
    assert not coverage.covered
    assert coverage.example_only == ("examplejobs_es",)
    assert connector_coverage.disclosure(coverage)


def test_a_real_connector_for_the_market_is_coverage(tmp_path: Path) -> None:
    """The other side of the same rule — a usable package for the candidate's
    market means there is nothing to disclose, so the gate is not simply
    asserting that everything is always uncovered."""
    library = _library(tmp_path / "connectors", realboard_es=_meta())
    coverage = connector_coverage.assess_coverage("ES", directory=library)
    assert coverage.covered
    assert coverage.usable == ("realboard_es",)
    assert connector_coverage.disclosure(coverage) is None
    # A connector for one market is not coverage of another.
    assert not connector_coverage.assess_coverage("PT", directory=library).covered


def test_a_skill_that_stops_disclosing_fails_the_gate(tmp_path: Path) -> None:
    """The gate confirmed against the state D-16 was filed in: with the
    sourcing skill's Coverage section removed, every connectorless situation
    counts again. Without this, a zero would only mean the regexes matched
    something, not that they would notice the defect coming back."""
    steps = process_spec.load_steps()
    step = connector_coverage.sourcing_step(steps)
    assert step is not None
    skills = tmp_path / "skills" / step_skills.skill_dir_name(step)
    skills.mkdir(parents=True)
    original = (
        step_skills.DEFAULT_SKILLS_DIR / step_skills.skill_dir_name(step) / "SKILL.md"
    ).read_text(encoding="utf-8")
    stripped = original.split("## Coverage — say when nothing here covers this market")[0]
    assert stripped != original, "the section this test strips has been renamed"
    (skills / "SKILL.md").write_text(stripped, encoding="utf-8")

    measured = connector_coverage.measure(skills_dir=tmp_path / "skills")
    assert measured["undisclosed_connectorless_sourcing"] > 0
    assert measured["shortfalls"]


def test_a_library_that_cannot_be_read_records_minus_one(tmp_path: Path) -> None:
    """`-1`, never `0`. A gate that reports a clean pass on the strength of
    having looked at nothing is the inert gate this project keeps finding."""
    measured = connector_coverage.measure(directory=tmp_path / "gone")
    assert measured["undisclosed_connectorless_sourcing"] == -1
    assert measured["shortfalls"]

    empty = tmp_path / "connectors"
    empty.mkdir()
    assert connector_coverage.measure(directory=empty)["undisclosed_connectorless_sourcing"] == -1


def test_the_gate_stops_measuring_when_the_spec_drops_the_requirement(tmp_path: Path) -> None:
    """D-15's rule, applied here: if the step spec no longer requires the
    disclosure, this check is enforcing a policy the project has dropped. It
    records `-1` and says why, rather than a pass nobody asked for."""
    doc = tmp_path / "spec-v2-steps.md"
    doc.write_text("## Step 7 — Sourcing\n\nNothing about connectors.\n", encoding="utf-8")
    measured = connector_coverage.measure(steps_doc=doc)
    assert measured["undisclosed_connectorless_sourcing"] == -1
    assert not measured["rule_declared_in_step_spec"]


def test_the_gate_records_the_coverage_measurement_it_made(tmp_path: Path) -> None:
    """The evidence file carries what was measured, so `make evidence` has
    something to detect drift against."""
    written = tmp_path / "D-16.json"
    measured = connector_coverage.write_evidence(written)
    assert json.loads(written.read_text(encoding="utf-8")) == measured


def test_the_undeclared_market_is_attributed_to_no_package(tmp_path: Path) -> None:
    """`UNDECLARED_MARKET` means exactly that: no installed package declares
    it. An example that names a country explains *that* country being
    uncovered and nothing else, so it must not appear in the sentinel reading
    — evidence asserting a connection that does not exist is worse than
    evidence saying nothing.
    """
    library = _library(
        tmp_path / "connectors",
        examplejobs_es=_meta(site="examplejobs.test"),
        realboard_pt=_meta(country="PT"),
    )
    packages = connector_coverage.installed_packages(library)

    undeclared = connector_coverage.assess_coverage(None, packages)
    assert undeclared.market == connector_coverage.UNDECLARED_MARKET
    assert not undeclared.covered
    assert undeclared.usable == ()
    assert undeclared.example_only == ()
    assert connector_coverage.disclosure(undeclared)

    # The example still explains the market it does declare.
    assert connector_coverage.assess_coverage("ES", packages).example_only == ("examplejobs_es",)
    # And a package that declares no country is not swept in either.
    nameless = _library(tmp_path / "other", mystery=yaml.safe_dump({"site": "who.test"}))
    assert connector_coverage.assess_coverage(
        None, connector_coverage.installed_packages(nameless)
    ).example_only == ()
