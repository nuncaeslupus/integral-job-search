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

from integral import connector_coverage, connector_transport, process_spec, step_skills
from integral.connectors import (
    JSON_CONTENT_TYPE,
    MINIMUM_PROBES,
    SEARCH_SOURCE,
    ConnectorError,
    FieldSelector,
    ListPage,
    _as_float,
    accepts_query,
    assess_staleness,
    build_list_requests,
    build_list_urls,
    build_offer,
    build_search_offer,
    collect_listing,
    compile_path,
    compile_selector,
    dig,
    dig_container,
    load_connector,
    load_connectors,
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


def _connector_yaml(name: str) -> str:
    """A minimal loadable `connector.yaml` for a package directory `<site>_<locale>`."""
    site, _, locale = name.rpartition("_")
    return (
        f"site: {site}\nlocale: {locale}\nversion: '1.0.0'\nlast_verified: '2026-08-01'\n"
        "list:\n"
        "  url_pattern: 'https://x.test/jobs?page={page}'\n"
        "  item: '.job'\n"
        "  fields:\n    text: {css: '.body'}\n"
    )


def _library(root: Path, **packages: str) -> Path:
    """A connector library on disk: package name -> its `meta.yaml` body.

    Each package also gets a loadable `connector.yaml`, because that is what
    makes it a package — metadata alone declares a maintainer, not a way to
    fetch anything. `_metadata_only` is how a test asks for the other case.
    """
    root.mkdir(parents=True, exist_ok=True)
    for name, meta in packages.items():
        package = root / name
        package.mkdir()
        (package / "meta.yaml").write_text(meta, encoding="utf-8")
        (package / "connector.yaml").write_text(_connector_yaml(name), encoding="utf-8")
    return root


def _metadata_only(root: Path, name: str, meta: str) -> Path:
    """A directory holding `meta.yaml` and nothing that can fetch."""
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
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
    nameless = _metadata_only(tmp_path / "other", "mystery", yaml.safe_dump({"site": "who.test"}))
    assert (
        connector_coverage.assess_coverage(
            None, connector_coverage.installed_packages(nameless)
        ).example_only
        == ()
    )


def test_metadata_alone_is_not_coverage(tmp_path: Path) -> None:
    """`meta.yaml` says who maintains a package; `connector.yaml` is the only
    thing that can fetch anything. A directory of plausible metadata reporting
    as coverage would suppress the disclosure outright — D-16's own failure,
    reached through the back door — so a package counts only when the runtime
    could actually load it.
    """
    library = _metadata_only(tmp_path / "connectors", "fakeboard_es", _meta(site="fakeboard.com"))
    coverage = connector_coverage.assess_coverage("ES", directory=library)
    assert not coverage.covered
    assert coverage.usable == ()
    assert coverage.unreadable == ("fakeboard_es",)
    assert connector_coverage.disclosure(coverage)

    # A package whose connector.yaml contradicts its directory name cannot be
    # loaded at runtime either, so it is not coverage however good its meta is.
    misnamed = tmp_path / "misnamed" / "realboard_es"
    misnamed.mkdir(parents=True)
    (misnamed / "meta.yaml").write_text(_meta(), encoding="utf-8")
    (misnamed / "connector.yaml").write_text(_connector_yaml("otherboard_en"), encoding="utf-8")
    assert not connector_coverage.assess_coverage("ES", directory=tmp_path / "misnamed").covered


# ---------------------------------------------------------------------------
# the JSON route
#
# Several boards keep their cleanest data in JSON and render a messier HTML view
# of the same facts. These tests are written against schema.org's `JobPosting`
# shape — the thing actually on the page — and they lean on the *fail-open*
# side, because a path that quietly resolves to the wrong node is worse than one
# that resolves to nothing: `build_offer` turns any salary key into
# `Salary(stated=True)`.

JOB_POSTING = json.dumps(
    {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": "Mid Data Platform Engineer",
        "description": "We build data pipelines.",
        "employmentType": "FULL_TIME",
        "baseSalary": {
            "@type": "MonetaryAmount",
            "currency": "PLN",
            "value": {
                "@type": "QuantitativeValue",
                "unitText": "MONTH",
                "minValue": 15000,
                "maxValue": 21500,
            },
        },
        "hiringOrganization": {"@type": "Organization", "name": "QED.ai"},
        "jobLocation": {
            "@type": "Place",
            "address": {
                "@type": "PostalAddress",
                "addressCountry": "PL",
                "addressLocality": "Warszawa",
            },
        },
    }
)
BREADCRUMBS = json.dumps(
    {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [{"name": "Python"}],
    }
)


def _ld(*blocks: str) -> str:
    body = "".join(f'<script type="application/ld+json">{b}</script>' for b in blocks)
    return f"<html><head>{body}</head><body><p>rendered later</p></body></html>"


JSON_DETAIL_CONNECTOR = """
site: jsonboard
locale: en
version: "1.0.0"
last_verified: "2026-08-30"
list:
  url_pattern: "https://jsonboard.test/jobs?page={page}"
  from_json:
    embedded_in: 'script[type="application/ld+json"]'
    match:
      "@type": CollectionPage
    items: hasPart
    fields:
      detail_url: url
detail:
  from_json:
    embedded_in: 'script[type="application/ld+json"]'
    match:
      "@type": JobPosting
    fields:
      title: title
      text: description
      company: hiringOrganization.name
      salary_min: baseSalary.value.minValue
      salary_max: baseSalary.value.maxValue
      salary_currency: baseSalary.currency
      salary_period: baseSalary.value.unitText
      location_raw: jobLocation.address.addressLocality
      location_country: jobLocation.address.addressCountry
"""


@pytest.mark.parametrize(
    "path",
    [
        "title",
        "baseSalary.value.minValue",
        "hiringOrganization.name",
        "@type",
        "a-b.c_d",
    ],
)
def test_a_json_path_of_plain_dotted_keys_compiles(path: str) -> None:
    assert compile_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "",
        "a[0]",
        "a.*",
        "a..b",
        "a.",
        ".a",
        "a b",
        "a['b']",
        "$.a",
        "a/b",
        "__class__.__mro__",
        "a()",
    ],
)
def test_a_json_path_outside_the_grammar_is_refused(path: str) -> None:
    """The same 'too small to smuggle anything through' rule as the selector
    grammar: refusal is a whole-string match, never an evaluator."""
    if path == "__class__.__mro__":
        # It matches the grammar's shape, and that is fine — it is looked up as
        # two ordinary dict keys and finds nothing. Nothing is ever `getattr`ed.
        assert dig({"a": 1}, compile_path(path)) is None
        return
    with pytest.raises(ConnectorError):
        compile_path(path)


# Every path `connectors/justjoin_en/connector.yaml` declares on its detail
# route, with the value the schema.org document above holds at it. This is the
# audit that is independent of the connector file: `check_fixture` proves the
# package parses *its own* fixture, which a mistyped path can still do by
# resolving to nothing on a board that often omits the field. Here the document
# is known and every declared path must land on its known value.
#
# It covered `minValue` and `hiringOrganization.name` and nothing else, so a
# path wrong for the ceiling, the currency, the period or either half of the
# location would have gone unnoticed — and a salary with a floor and no ceiling
# is exactly the shape this route was built to stop (#260 review).
JUSTJOIN_DECLARED_PATHS = {
    "title": "Mid Data Platform Engineer",
    "description": "We build data pipelines.",
    "hiringOrganization.name": "QED.ai",
    "baseSalary.value.minValue": "15000",
    "baseSalary.value.maxValue": "21500",
    "baseSalary.currency": "PLN",
    "baseSalary.value.unitText": "MONTH",
    "jobLocation.address.addressLocality": "Warszawa",
    "jobLocation.address.addressCountry": "PL",
}


@pytest.mark.parametrize(("path", "expected"), sorted(JUSTJOIN_DECLARED_PATHS.items()))
def test_dig_returns_the_scalar_at_the_end_of_the_path(path: str, expected: str) -> None:
    assert dig(json.loads(JOB_POSTING), compile_path(path)) == expected


def test_the_path_audit_covers_every_path_the_shipped_connector_declares() -> None:
    """An audit that lags the connector it audits is not an audit.

    Two of the nine paths were covered when this was written, so the table is
    pinned against the shipped file rather than left to be extended by whoever
    remembers. A new field on justjoin's detail route fails here until it has a
    known-value assertion above.
    """
    shipped = yaml.safe_load(
        (_CONNECTOR_LIBRARY / "justjoin_en" / "connector.yaml").read_text(encoding="utf-8")
    )
    declared = set(shipped["detail"]["from_json"]["fields"].values())
    assert declared == set(JUSTJOIN_DECLARED_PATHS)


@pytest.mark.parametrize(
    "path",
    [
        "baseSalary",
        "baseSalary.value",
        "hiringOrganization",
        "jobLocation.address",
        "missing",
        "baseSalary.missing.minValue",
    ],
)
def test_dig_treats_a_container_or_a_miss_as_no_value(path: str) -> None:
    """Landing on an object must read as *absent*, not as `str({...})`.

    This is the fail-open case the whole route is shaped around: a salary key
    holding a Python repr still makes `build_offer` construct
    `Salary(stated=True)`, so the candidate is told the employer stated a wage
    when nobody stated anything.
    """
    assert dig(json.loads(JOB_POSTING), compile_path(path)) is None


def test_dig_refuses_a_boolean() -> None:
    """JSON's `true` is not a title, a body or a wage."""
    assert dig({"remote": True}, compile_path("remote")) is None
    assert dig({"n": 0}, compile_path("n")) == "0"


def test_dig_container_wants_an_array_and_a_scalar_is_the_miss() -> None:
    assert dig_container({"hasPart": [{"url": "/a"}]}, compile_path("hasPart")) == [{"url": "/a"}]
    assert dig_container({"hasPart": "not a list"}, compile_path("hasPart")) == []
    assert dig_container({}, compile_path("hasPart")) == []


def test_a_json_list_page_reads_its_items_out_of_the_embedded_document() -> None:
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    page = _ld(
        BREADCRUMBS,
        json.dumps(
            {
                "@type": "CollectionPage",
                "hasPart": [
                    {"url": "https://jsonboard.test/job/1"},
                    {"url": "https://jsonboard.test/job/2"},
                ],
            }
        ),
    )
    assert parse_list_page(connector, page) == [
        {"detail_url": "https://jsonboard.test/job/1"},
        {"detail_url": "https://jsonboard.test/job/2"},
    ]


def test_match_picks_the_right_document_when_a_page_carries_several() -> None:
    """A page serving a BreadcrumbList beside its JobPosting must not have the
    breadcrumbs read as the advert."""
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    record = parse_detail_page(connector, _ld(BREADCRUMBS, JOB_POSTING))
    assert record["title"] == "Mid Data Platform Engineer"
    assert record["company"] == "QED.ai"


def test_one_broken_json_block_does_not_lose_the_others() -> None:
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    record = parse_detail_page(connector, _ld("{not json,", JOB_POSTING))
    assert record["title"] == "Mid Data Platform Engineer"


def test_a_json_salary_reaches_the_offer_as_real_numbers() -> None:
    """The point of the route: `minValue` is a number, so nothing has to be
    split out of a string, and `Salary` carries figures rather than a `stated`
    flag with nothing behind it."""
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    offer = build_offer(
        connector,
        detail_fields=parse_detail_page(connector, _ld(JOB_POSTING)),
        url="https://jsonboard.test/job/1",
    )
    assert offer.salary is not None
    assert (offer.salary.min, offer.salary.max) == (15000.0, 21500.0)
    assert (offer.salary.currency, offer.salary.period) == ("PLN", "MONTH")
    assert offer.salary.stated is True


def test_a_salary_path_that_lands_on_the_object_produces_no_salary_at_all() -> None:
    """Rather than `Salary(stated=True, min=None, max=None)` — the failure this
    library has already hit six times with unsplittable HTML strings."""
    connector = parse_connector(
        JSON_DETAIL_CONNECTOR.replace(
            "salary_min: baseSalary.value.minValue", "salary_min: baseSalary"
        )
        .replace("      salary_max: baseSalary.value.maxValue\n", "")
        .replace("      salary_currency: baseSalary.currency\n", "")
        .replace("      salary_period: baseSalary.value.unitText\n", "")
    )
    offer = build_offer(
        connector,
        detail_fields=parse_detail_page(connector, _ld(JOB_POSTING)),
        url="https://jsonboard.test/job/1",
    )
    assert offer.salary is None


def test_a_json_document_is_never_evaluated() -> None:
    """`json.loads` cannot construct an object, so a string that looks like code
    stays a string. The YAML loader's `!!python/…` route is closed the same way
    (`yaml.safe_load`) — this is the JSON half of the same promise."""
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    hostile = json.dumps(
        {"@type": "JobPosting", "title": "__import__('os').system('id')", "description": "body"}
    )
    record = parse_detail_page(connector, _ld(hostile))
    assert record["title"] == "__import__('os').system('id')"


def test_a_page_that_declares_both_routes_is_refused() -> None:
    both = JSON_DETAIL_CONNECTOR.replace(
        "  from_json:\n    embedded_in: 'script[type=\"application/ld+json\"]'\n"
        '    match:\n      "@type": CollectionPage\n    items: hasPart\n'
        "    fields:\n      detail_url: url\n",
        '  item: ".card"\n  fields:\n    detail_url:\n      css: "a.link"\n      attr: href\n'
        "  from_json:\n    embedded_in: 'script[type=\"application/ld+json\"]'\n"
        '    match:\n      "@type": CollectionPage\n    items: hasPart\n'
        "    fields:\n      detail_url: url\n",
    )
    with pytest.raises(ConnectorError, match="exactly one"):
        parse_connector(both)


def test_a_list_page_json_source_must_name_its_items() -> None:
    with pytest.raises(ConnectorError, match="items is required"):
        parse_connector(JSON_DETAIL_CONNECTOR.replace("    items: hasPart\n", "", 1))


def test_a_detail_page_json_source_may_not_name_items() -> None:
    with pytest.raises(ConnectorError, match="items is not allowed"):
        parse_connector(
            JSON_DETAIL_CONNECTOR.replace(
                '    match:\n      "@type": JobPosting\n',
                '    match:\n      "@type": JobPosting\n    items: results\n',
            )
        )


def test_a_json_field_outside_the_offer_vocabulary_is_refused() -> None:
    with pytest.raises(ConnectorError, match="api_key"):
        parse_connector(
            JSON_DETAIL_CONNECTOR.replace(
                "      title: title\n", "      api_key: token\n      title: title\n"
            )
        )


def test_a_json_host_selector_outside_the_grammar_is_refused() -> None:
    with pytest.raises(ConnectorError):
        parse_connector(
            JSON_DETAIL_CONNECTOR.replace(
                "embedded_in: 'script[type=\"application/ld+json\"]'",
                'embedded_in: "head > script"',
            )
        )


def test_the_root_path_names_a_document_that_is_itself_the_array() -> None:
    """An API whose response *is* the list of adverts has no key to name."""
    assert compile_path("$") == ()
    assert dig_container([{"url": "/a"}, {"url": "/b"}], compile_path("$")) == [
        {"url": "/a"},
        {"url": "/b"},
    ]
    # …and it is still a miss when the document is not an array.
    assert dig_container({"jobs": []}, compile_path("$")) == []


def test_item_alone_beside_from_json_is_refused() -> None:
    """The gap CodeRabbit found on #259: `item` without `fields` read as "no
    markup route", so the exclusivity check passed and the declared selector
    was silently ignored in favour of the JSON one."""
    both = JSON_DETAIL_CONNECTOR.replace(
        "  from_json:\n    embedded_in:", '  item: ".card"\n  from_json:\n    embedded_in:', 1
    )
    with pytest.raises(ConnectorError, match="exactly one"):
        parse_connector(both)


def test_fields_alone_beside_from_json_is_refused() -> None:
    both = JSON_DETAIL_CONNECTOR.replace(
        "  from_json:\n    embedded_in:",
        '  fields:\n    title:\n      css: "h2.t"\n  from_json:\n    embedded_in:',
        1,
    )
    with pytest.raises(ConnectorError, match="exactly one"):
        parse_connector(both)


def test_the_markup_route_needs_both_halves() -> None:
    """And `item` alone with no `from_json` at all is not a working page either
    — it selects containers nothing is read out of."""
    with pytest.raises(ConnectorError, match="needs both"):
        parse_connector(
            """
site: halfaroute
locale: en
version: "1.0.0"
last_verified: "2026-08-30"
list:
  url_pattern: "https://halfaroute.test/jobs"
  item: ".card"
detail:
  fields:
    text:
      css: "div.body"
"""
        )


def test_an_embedded_document_is_read_unchanged() -> None:
    """`text_content` collapses runs of whitespace, which is right for prose
    read out of markup and wrong for a `<script>` holding JSON: whitespace
    between tokens does not matter, whitespace *inside a string value* does,
    and an advert body is a string value.

    Caught by review on the PR that introduced this route — the first
    implementation reflowed every body it parsed.
    """
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    body = "Line one.\n\nLine  two with  double  spaces, and a trailing run.   "
    posting = json.dumps({"@type": "JobPosting", "title": "T", "description": body})
    record = parse_detail_page(connector, _ld(posting))
    assert record["text"] == body


def test_raw_text_concatenates_and_text_content_still_collapses() -> None:
    node = parse_html("<div><span>a  b</span>\n<span>c   d</span></div>")
    div = select_first(node, compile_selector("div"))
    assert div is not None
    assert div.raw_text() == "a  b\nc   d"
    assert div.text_content() == "a b c d"


def test_an_ampersand_in_an_embedded_document_survives() -> None:
    """HTMLParser treats `script` as CDATA, so `&amp;` inside the JSON is not
    decoded on the way in and `json.loads` sees what the board sent."""
    connector = parse_connector(JSON_DETAIL_CONNECTOR)
    posting = json.dumps({"@type": "JobPosting", "title": "T", "description": "R&amp;D at AT&T"})
    record = parse_detail_page(connector, _ld(posting))
    assert record["text"] == "R&amp;D at AT&T"


# ---------------------------------------------------------------------------
# T89 — a board whose search is a POST


# A board whose search is a POST — read from
# `tests/fixtures/connectors/post_board.yaml` rather than written inline, so
# this suite and T89's acceptance gate exercise the same bytes rather than two
# copies that can drift apart.
POST_BOARD = (_FIXTURES / "post_board.yaml").read_text(encoding="utf-8")

# The one line every adversarial case below swaps out.
PAGE_LINE = '    Page: "{page}"'
KEYWORD_LINE = "    Keyword: python"


def post_board(old: str, new: str) -> str:
    """`POST_BOARD` with one line swapped — one edit per adversarial case."""
    assert old in POST_BOARD, old
    return POST_BOARD.replace(old, new)


def test_a_list_page_may_declare_a_post_method_and_a_literal_body() -> None:
    """T89's first property. A board whose search is a POST is expressible:
    the method is declared, the body is declared as data, and the engine
    issues both. `Content-Type` follows from the body's declared form rather
    than being a third thing to get wrong — there is no header field in the
    schema for a connector to set, which is also what keeps "a connector may
    not carry a credential" true of the transport."""
    connector = parse_connector(POST_BOARD)
    assert connector.list.method == "POST"
    assert connector.list.body_json == {
        "Keyword": "python",
        "ResultsPerPage": 25,
        "Page": "{page}",
    }

    requests = build_list_requests(connector)
    assert len(requests) == 3
    first = requests[0]
    assert first.method == "POST"
    assert first.url == "https://boards.test/Search/ExecuteSearch"
    assert first.headers == {"Content-Type": JSON_CONTENT_TYPE}
    assert isinstance(first.body, bytes) and first.body

    # The default did not move: a connector that says nothing is a GET with no
    # body and no headers, exactly as before T89.
    plain = build_list_requests(parse_connector(VALID))[0]
    assert (plain.method, plain.body, plain.headers) == ("GET", None, {})

    # A POST board's pages are the *same* URL — which is why `build_list_urls`
    # alone stopped being enough and this seam exists at all.
    assert len({request.url for request in requests}) == 1
    assert len({request.body for request in requests}) == 3


def test_a_templated_request_body_is_refused_at_load() -> None:
    """T89's contract for a literal body, case by case, each derived from the
    task text rather than from what the code happens to do.

    "Literal body" and "substitute the page" are only compatible because the
    exception is written down: one placeholder, `{page}`, only as a complete
    value, only in a value. Everything else is refused at load — the posture
    `url_pattern` already takes, and what stops general templating coming back
    one convenience at a time."""
    refused = {
        # A brace in the middle of a string. The task allows either passing it
        # through untouched or refusing; this implementation refuses, because
        # a brace that quietly does nothing is indistinguishable from a
        # placeholder that silently stopped working.
        "an interpolated string": '    Page: "page {page} of many"',
        # A brace anywhere else at all.
        "a stray opening brace": '    Page: "{page}"\n    Note: "a{b"',
        "a stray closing brace": '    Page: "{page}"\n    Note: "a}b"',
        # A key may not be a placeholder: only values substitute, and a body
        # whose *shape* varies by page is not a literal body.
        "a placeholder as a key": '    "{page}": 1',
        "a brace inside a key": "    Pa{ge}: 1",
        # Nested, because a walk that only looked at the top level would let
        # every one of these through.
        "a template nested in an object": '    Page: "{page}"\n    Filters:\n      q: "{query}"',
        "a template nested in an array": '    Page: "{page}"\n    Tags:\n      - "{page}x"',
        # `str.format`'s attribute-traversal surface, which is the reason
        # `url_pattern` refuses braces in the first place.
        "an attribute traversal": '    Page: "{0.__class__.__mro__}"',
    }
    for label, replacement in refused.items():
        with pytest.raises(ConnectorError, match="body_json") as raised:
            parse_connector(post_board(PAGE_LINE, replacement))
        assert "brace" in str(raised.value), label

    # The one form that is *not* refused, so the block above is not simply
    # "every body is refused": a whole-value placeholder, and strings carrying
    # no brace at all.
    assert parse_connector(POST_BOARD).list.body_json is not None


def test_the_page_placeholder_substitutes_as_a_json_number() -> None:
    """The substitution is on the parsed structure, never on the serialised
    text, so `"{page}"` becomes a JSON *number* and the body's shape cannot
    vary by page. Asserting only that the literal `{page}` is gone would pass
    a body that dropped the field, or set it to the wrong page, or set it to
    the string `"1"` — so name the field, the value and the type."""
    connector = parse_connector(POST_BOARD)
    requests = build_list_requests(connector)
    field_name = connector.list.pagination.param
    assert field_name is not None

    for offset, request in enumerate(requests):
        assert request.body is not None
        paged = json.loads(request.body.decode("utf-8"))
        assert field_name in paged
        assert paged[field_name] == connector.list.pagination.start + offset
        assert type(paged[field_name]) is int
        assert "{page}" not in json.dumps(paged)
        # Every other value is passed through unchanged — the placeholder is
        # the only thing that moves, and nothing is added or dropped.
        assert paged["Keyword"] == "python"
        assert paged["ResultsPerPage"] == 25
        assert sorted(paged) == ["Keyword", "Page", "ResultsPerPage"]

    # `start` is honoured, not assumed to be 1.
    from_zero = parse_connector(POST_BOARD.replace("start: 1", "start: 0"))
    body = build_list_requests(from_zero)[0].body
    assert body is not None
    assert json.loads(body.decode("utf-8"))["Page"] == 0


def test_the_post_search_the_ledger_recorded_is_expressible_as_a_connector() -> None:
    """T89's third property, and the one the other two cannot supply: a real
    board, not a string this file wrote.

    `connectors/ruled-out.yaml` carries usajobs.gov under `corrected` with a
    measured `retest:` command — a bare `curl -X POST` under this tool's own
    product token, no key and no cookie, that returned 25 rows. The engine's
    request is compared against *that*, field by field. A test asserting "the
    POST I built is the POST I meant" would prove nothing; the curl line was
    written before this code existed, from a response nobody here produced."""
    posts, scanned = connector_transport.recorded_post_boards()
    assert scanned >= connector_transport.MINIMUM_LEDGER_ENTRIES
    assert [recorded.site for recorded in posts] == ["usajobs.gov"]

    recorded = posts[0]
    assert recorded.url == "https://www.usajobs.gov/Search/ExecuteSearch"
    assert recorded.headers["Content-Type"] == "application/json"
    assert json.loads(recorded.body or "") == {"Keyword": "python", "ResultsPerPage": 25}
    assert connector_transport.why_unreadable(recorded) == []


def test_the_usajobs_package_parses_its_fixture_to_offers() -> None:
    """T89's third property, against the board the task was written for.

    usajobs.gov is the live example the ledger carries: a POST search, no key
    and no cookie, that nothing in this repository could reach. The package is
    here now, and this asserts the whole path — the request the engine issues,
    the rows its recorded response parses to, and an `Offer` built from one of
    them — because each of those can be green while the others are broken.

    The salary assertions are the ones with teeth. `connectors/ruled-out.yaml`
    test 4 exists because remoteok stamped ONE invented band onto 48 of 50
    adverts, and ticjob and weworkremotely both publish a sentinel zero that a
    naive reader coerces into "the employer stated 0". So this counts the
    spread rather than checking that a number arrived."""
    package = _CONNECTOR_LIBRARY / "usajobs_en"
    connector = load_connector(package)

    # The request. A POST, a JSON body, and a URL that carries no page — two
    # pages of this board differ only in the payload.
    request = build_list_requests(connector)[0]
    assert request.method == "POST"
    assert request.url == "https://www.usajobs.gov/Search/ExecuteSearch"
    assert request.headers == {"Content-Type": JSON_CONTENT_TYPE}
    assert request.body is not None
    assert json.loads(request.body.decode("utf-8")) == {
        "Keyword": "python",
        "ResultsPerPage": 25,
        "Page": 1,
    }

    rows = parse_list_page(connector, (package / "fixture" / "list.html").read_text("utf-8"))
    assert len(rows) == 25
    for row in rows:
        assert row["title"]
        assert row["company"]
        assert row["detail_url"].startswith("https://www.usajobs.gov")

    # The salary spread, over every row and not a sample. A board publishing
    # one figure everywhere is publishing a sentinel, and mapping it would
    # stamp an invented wage across the whole board.
    minimums = [row["salary_min"] for row in rows if "salary_min" in row]
    assert len(minimums) == len(rows), "a row with no MinimumRange"
    assert len(set(minimums)) >= 10, sorted(set(minimums))
    assert all(float(value) > 0 for value in minimums), "a sentinel zero"
    assert max(float(v) for v in minimums) > 3 * min(float(v) for v in minimums)
    # "Starting at $X" is a floor. Nothing may invent the other end of it.
    assert not any("salary_max" in row for row in rows)

    # The detail page, which is where the advert body comes from — a list row
    # carries none, so a connector without this block could not produce `text`
    # at all and `_something_produces_the_offer_text` would refuse it.
    detail = parse_detail_page(connector, (package / "fixture" / "detail.html").read_text("utf-8"))
    assert detail["title"] == "Python Developer"
    assert "Duties" in detail["text"]

    offer = build_offer(
        connector,
        list_fields=rows[0],
        detail_fields=detail,
        url=rows[0]["detail_url"],
        source_ref=f"{connector.site}:{connector.locale}",
    )
    assert offer.salary is not None
    assert offer.salary.min == 143913.0
    assert offer.salary.max is None, "the board states a floor, never a range"
    assert offer.language == "en"


def test_the_transport_gate_reports_a_post_the_engine_cannot_issue() -> None:
    """The measurement has teeth, which a clean zero on its own never shows.

    A board whose search is a form POST is *not* readable by this engine — the
    only body form the schema declares is JSON — and the gate must say so
    rather than reporting the zero it reports for a board it can read."""
    form_post = connector_transport.RecordedRequest(
        site="formboard.test",
        url="https://formboard.test/search",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body='{"q": "python"}',
    )
    reasons = connector_transport.why_unreadable(form_post)
    assert reasons and all(reason.startswith("formboard.test:") for reason in reasons)

    assert connector_transport.why_refused(form_post) == []

    # And the plain JSON POST the engine *can* issue reports nothing, so the
    # case above is a discrimination and not a matcher that says no to
    # everything.
    fine = connector_transport.RecordedRequest(
        site="other.test",
        url="https://other.test/search",
        method="POST",
        headers={"Content-Type": JSON_CONTENT_TYPE},
        body='{"q": "python"}',
    )
    assert connector_transport.why_unreadable(fine) == []
    assert connector_transport.why_refused(fine) == []


def test_a_lowercase_content_type_is_compared_not_skipped() -> None:
    """HTTP header names are case-insensitive (RFC 9110 §5.1), and a recorded
    command is written by a person.

    `parse_curl` keeps whatever case the `-H` was typed in, so a recording of
    `-H 'content-type: application/x-www-form-urlencoded'` used to make the
    lookup return `None` — and the comparison was then skipped rather than
    failed. `why_unreadable` returning `[]` reads as "the engine can issue this
    request", so a form POST the engine cannot send was reported as a board with
    no gap: the check said yes because it could not find the header (#295 review).
    """
    lowercased = connector_transport.RecordedRequest(
        site="lowerboard.test",
        url="https://lowerboard.test/search",
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        body='{"q": "python"}',
    )
    reasons = connector_transport.why_unreadable(lowercased)
    assert any("Content-Type" in reason for reason in reasons), reasons

    # The negative control: matching content types in different cases are the
    # same header, so a lookup that lowercases both must not invent a mismatch.
    mixed_case = connector_transport.RecordedRequest(
        site="mixedboard.test",
        url="https://mixedboard.test/search",
        method="POST",
        headers={"CONTENT-TYPE": JSON_CONTENT_TYPE},
        body='{"q": "python"}',
    )
    assert connector_transport.why_unreadable(mixed_case) == []


def test_a_board_refused_on_policy_is_not_a_board_readable_only_by_post(tmp_path: Path) -> None:
    """A credential refusal is this tool declining a board, not an engine gap.

    Counting the two together made the gate go permanently red on a
    *legitimate* ledger addition. `ruled-out.yaml`'s own test 3 tells the next
    surveyor to record the curl a capture revealed; recording idealist.org's
    Algolia call — a POST whose query string, headers and payload all carry a
    key — turned `boards_readable_only_by_post` to 1 with the message "the
    schema cannot express the recorded request: … names a credential". The
    only route back to green was deleting a measured `retest:` line, which is
    the one thing that file exists to prevent."""
    algolia = connector_transport.RecordedRequest(
        site="idealist.org",
        url=(
            "https://nsv3auess7-dsn.algolia.net/1/indexes/jobs/query"
            "?x-algolia-api-key=abc&x-algolia-application-id=NSV3AUESS7"
        ),
        method="POST",
        headers={"Content-Type": JSON_CONTENT_TYPE, "X-Algolia-API-Key": "abc"},
        body='{"apiKey": "abc", "params": "query=python"}',
    )
    # All three places a credential can ride, each named separately.
    refused = connector_transport.why_refused(algolia)
    assert len(refused) == 4, refused
    assert any("x-algolia-api-key" in reason for reason in refused)
    assert any("x-algolia-application-id" in reason for reason in refused)
    assert any("X-Algolia-API-Key" in reason for reason in refused)
    assert any("apiKey" in reason for reason in refused)

    # And the ledger it is patched into stays green, with the board counted
    # under its own heading rather than as an engine failure. Patched into a
    # copy of the *real* ledger, because the whole failure was about what
    # happens when a surveyor follows the documented process on this file.
    curl = (
        "curl -s -X POST -H 'Content-Type: application/json' "
        "-H 'X-Algolia-API-Key: abc' "
        '-d \'{"apiKey":"abc","params":"query=python"}\' '
        f"'{algolia.url}'"
    )
    ledger = yaml.safe_load(connector_transport.DEFAULT_LEDGER_PATH.read_text(encoding="utf-8"))
    for entry in connector_transport._entries(ledger):
        if entry["site"] == "idealist.org":
            entry["retest"] = curl
    patched = tmp_path / "ruled-out.yaml"
    patched.write_text(yaml.safe_dump(ledger), encoding="utf-8")

    measured = connector_transport.measure(patched)
    assert measured["gate_status"] == "measured"
    assert measured["boards_readable_only_by_post"] == 0
    assert measured["boards_refused_on_policy"] == 1
    assert measured["boards_readable_only_by_post_evaluated"] == 1
    assert measured["unreadable"] == []

    # The denominator stays honest in the other direction too: refuse every
    # POST board and there is nothing left to ask the engine about, so the
    # gate says `unmeasured` rather than reporting the zero it would report
    # for a board it can read.
    for entry in connector_transport._entries(ledger):
        if isinstance(entry.get("retest"), str) and " -X POST" in entry["retest"]:
            entry["retest"] = curl
    patched.write_text(yaml.safe_dump(ledger), encoding="utf-8")
    assert connector_transport.measure(patched)["gate_status"] == "unmeasured"


def test_a_retest_command_with_a_broken_quote_is_unmeasured_not_a_crash(
    tmp_path: Path,
) -> None:
    """`parse_curl` tokenises with `shlex`, and `shlex.split` raises
    `ValueError: No closing quotation` on an unmatched quote. `measure` caught
    `OSError` and `yaml.YAMLError` and not that, so one mistyped `retest:` in
    the ledger took down `make evidence` instead of recording that the ledger
    could not be read (#295 review).

    The direction matters: a crash is fail-closed and loses nothing, but the
    gate's own contract is that an input it cannot read is `unmeasured` — a
    module that dies instead never gets to say so, and the drift check reports
    a traceback rather than a missing measurement.
    """
    ledger = yaml.safe_load(connector_transport.DEFAULT_LEDGER_PATH.read_text(encoding="utf-8"))
    for entry in connector_transport._entries(ledger):
        if isinstance(entry.get("retest"), str):
            entry["retest"] = "curl -s 'https://boards.test/search?q=python"
            break
    patched = tmp_path / "ruled-out.yaml"
    patched.write_text(yaml.safe_dump(ledger), encoding="utf-8")

    measured = connector_transport.measure(patched)
    assert measured["gate_status"] == "unmeasured"


def test_parse_curl_raises_on_an_unmatched_quote_rather_than_guessing() -> None:
    """The refusal above is only meaningful if the tokeniser really does fail
    here — a `parse_curl` that silently recovered would make the guard dead
    code. Pinned so the guard cannot become decorative.
    """
    with pytest.raises(ValueError, match="No closing quotation"):
        connector_transport.parse_curl("curl -s 'https://boards.test/a")


def test_every_committed_connector_still_builds_a_plain_get() -> None:
    """A POST route that quietly changed what a GET connector sends would
    break every existing package silently, and T89's own count of POST-only
    boards would still read zero. Enumerated from disk, so a package added
    after this test was written is covered without anybody remembering."""
    packages = sorted(_CONNECTOR_LIBRARY.glob("*/connector.yaml"))
    assert len(packages) >= 10
    for path in packages:
        connector = load_connector(path)
        if connector.list.method != "GET":
            continue
        for request in build_list_requests(connector, query="python"):
            assert request.method == "GET", path.parent.name
            assert request.body is None, path.parent.name
            assert request.headers == {}, path.parent.name


def test_a_get_may_not_declare_a_body() -> None:
    """The default stays honest: a connector declaring a body without
    declaring the method has contradicted itself, and is told so at load
    rather than getting a body nothing sends."""
    for swap in ("  method: GET\n", ""):
        with pytest.raises(ConnectorError, match="only a POST carries a request body"):
            parse_connector(post_board("  method: POST\n", swap))


def test_the_page_field_and_the_body_placeholder_must_name_each_other() -> None:
    """Both directions, because the two failures differ and both are real.

    Too narrow and a real paginating board is rejected; too broad and the page
    number lands in a field nothing declared, so a caller reading
    `pagination.param` is told the wrong thing varies."""
    # A placeholder the pagination does not claim.
    with pytest.raises(ConnectorError, match="mode: body_field"):
        parse_connector(post_board("    mode: body_field", "    mode: query_param"))
    # `body_field` over a body with nothing to vary — every page the same
    # request, which is the duplicate fetch `mode: none` already guards.
    with pytest.raises(ConnectorError, match="nothing would vary"):
        parse_connector(post_board(PAGE_LINE, "    Page: 1"))
    # The placeholder is at a key other than the one the pagination names.
    with pytest.raises(ConnectorError, match="carrying the page number"):
        parse_connector(post_board(PAGE_LINE, '    Offset: "{page}"'))
    # Nested rather than top level: `pagination.param` names a top-level key,
    # so a placeholder buried in a sub-object is refused rather than left
    # silently unreachable to a caller that reads `param`.
    with pytest.raises(ConnectorError, match="carrying the page number"):
        parse_connector(post_board(PAGE_LINE, '    Paging:\n      Page: "{page}"'))


def test_a_request_body_may_not_name_a_credential() -> None:
    """`body_json` is the one free-form structure in this schema, so the rule
    the rest of the format keeps by having no field for a secret needs a check
    here instead. Admission lint, not a sandbox — a determined author can call
    a token `q` — but a board whose search needs a key is a board this tool
    may not read, and that is said at load rather than after the commit."""
    for bad in ("api_key", "apiKey", "X-Api-Key", "token", "accessToken", "sessionId", "secret"):
        with pytest.raises(ConnectorError, match="names a credential"):
            parse_connector(post_board(KEYWORD_LINE, f"    {bad}: leaked"))
    # Nested just as much as top level.
    with pytest.raises(ConnectorError, match="names a credential"):
        parse_connector(post_board(KEYWORD_LINE, "    Filters:\n      apiKey: leaked"))


def test_every_committed_credential_key_case_is_judged_the_way_the_rule_says() -> None:
    """The audit's cases, committed as the gate's own fixtures.

    `tests/fixtures/connectors/credential_keys.yaml` holds both directions and
    the gate counts them, so the token list cannot regress behind a green
    suite: `credential_key_cases_checked` is a number `make evidence` records.

    Nearly every `refused` entry was ADMITTED before this — the splitter could
    break neither a capital run (`SECRETKEY`) nor a lowercase concatenation
    (`apitoken`), and a dozen ordinary words for a secret were absent from the
    list (`passwd` was in it; `pwd` and `pass` were not)."""
    misjudged, checked = connector_transport.credential_key_misjudgements()
    assert misjudged == []
    assert checked >= connector_transport.MINIMUM_CREDENTIAL_CASES

    # Both lists are non-trivial, so "no misjudgements" is not a report over
    # an empty half — a matcher refusing everything, or nothing, fails one.
    table = yaml.safe_load((_FIXTURES / "credential_keys.yaml").read_text(encoding="utf-8"))
    assert len(table["refused"]) >= 40
    assert len(table["accepted"]) >= 40

    # And the refusal reaches a load, not just the predicate: three shapes the
    # old splitter could not see, refused in a real connector file.
    for bad in ("apitoken", "SECRETKEY", "pwd", "app_id", "X-Signature"):
        with pytest.raises(ConnectorError, match="names a credential"):
            parse_connector(post_board(KEYWORD_LINE, f"    {bad}: leaked"))


def test_a_credential_in_the_url_query_is_refused_the_same_as_one_in_the_body() -> None:
    """A request has two halves and the rule was applied to one of them.

    `connectors/ruled-out.yaml` claimed idealist.org's Algolia payload "cannot
    be written into a connector even by accident". That was true of
    `body_json` and false of `url_pattern` — where the ledger's own entry says
    those credentials actually live: "carries an application id plus a search
    key in the query string"."""
    algolia = (
        "https://nsv3auess7-dsn.algolia.net/1/indexes/jobs/query"
        "?x-algolia-api-key=abc&x-algolia-application-id=NSV3AUESS7"
    )
    with pytest.raises(ConnectorError, match="name a credential") as raised:
        parse_connector(post_board("https://boards.test/Search/ExecuteSearch", algolia))
    # Both halves of the pair are named, not just the one spelled "key".
    assert "'x-algolia-api-key'" in str(raised.value)
    assert "'x-algolia-application-id'" in str(raised.value)

    # An ordinary query string is untouched — this is a credential check, not
    # a ban on query strings.
    fine = "https://boards.test/search?q=python&page={page}&sort=date"
    assert (
        parse_connector(
            post_board("https://boards.test/Search/ExecuteSearch", fine)
        ).list.url_pattern
        == fine
    )

    # Every committed package still loads, which is the other direction: a
    # check this aggressive would have taken the library down with it.
    assert len(load_connectors()) >= 10


def test_a_body_value_with_no_json_spelling_is_refused_at_load() -> None:
    """The same YAML/JSON divergence the `date` case catches, one level down.

    A `date` is a *type* JSON has no spelling for, and that was caught. `.nan`
    and `.inf` are *values* it has no spelling for, and they were not: they
    loaded, and `json.dumps` emitted the bare words `NaN` and `Infinity`
    — invalid JSON, on the wire, under a `Content-Type` this engine derived
    itself. Enumerating members is how the second one got through behind the
    first, so the class is asserted here too: whatever loads must serialise.
    """
    for spelling in (".nan", ".inf", "-.inf"):
        with pytest.raises(ConnectorError, match="no JSON spelling"):
            parse_connector(post_board(KEYWORD_LINE, f"    Score: {spelling}"))
    # Nested and in an array, because a top-level-only walk would miss both.
    with pytest.raises(ConnectorError, match="no JSON spelling"):
        parse_connector(post_board(KEYWORD_LINE, "    Filters:\n      Score: .nan"))
    with pytest.raises(ConnectorError, match="no JSON spelling"):
        parse_connector(post_board(KEYWORD_LINE, "    Scores:\n      - .inf"))

    # The rest of the class, each a value that passes every per-node check and
    # then cannot be put on the wire. A lone surrogate is the one no type
    # check can see: it is an ordinary `str`.
    for label, line in {
        "a lone surrogate": '    Note: "\\uD800"',
        "binary": "    Note: !!binary aGk=",
        "a set": "    Note: !!set {a, b}",
    }.items():
        with pytest.raises(ConnectorError) as raised:
            parse_connector(post_board(KEYWORD_LINE, line))
        assert "body_json" in str(raised.value), label

    # A finite number is still a number, so the block above is a refusal of
    # three values and not of the type.
    body = parse_connector(post_board(KEYWORD_LINE, "    Score: 1.5")).list.body_json
    assert body is not None and body["Score"] == 1.5


def test_a_connector_cannot_declare_its_own_headers() -> None:
    """`Content-Type` follows from the body's declared form. There is no
    header field anywhere in the schema, which is what makes "no connector
    carries a credential" structural for the transport rather than a lint: an
    `Authorization` has nowhere to be written."""
    with pytest.raises(ConnectorError):
        parse_connector(post_board("  method: POST\n", "  method: POST\n  headers:\n    X: y\n"))
    assert "headers" not in ListPage.model_fields


def test_a_request_body_may_hold_only_json_values() -> None:
    """`yaml.safe_load` produces a `date` for an unquoted date, and
    `json.dumps` cannot serialise one. Refused at load, where the connector's
    author is still in the room, rather than at request-build time."""
    with pytest.raises(ConnectorError, match="not a JSON value"):
        parse_connector(post_board(KEYWORD_LINE, "    Since: 2026-08-31"))
    # A body must be an object. An array top level is refused by the declared
    # type, so there is no shape for a connector to smuggle in.
    with pytest.raises(ConnectorError):
        parse_connector(
            post_board(
                '  body_json:\n    Keyword: python\n    ResultsPerPage: 25\n    Page: "{page}"\n',
                "  body_json:\n    - 1\n",
            ).replace("    mode: body_field", "    mode: query_param")
        )


def test_the_transport_evidence_records_both_denominators(tmp_path: Path) -> None:
    """`boards_readable_only_by_post == 0` over zero POST boards is what a
    check that never ran also reports, so the record carries what was scanned
    and refuses to call itself measured when there was nothing to scan."""
    measured = connector_transport.write_evidence(tmp_path / "T89.json")
    assert measured["gate_status"] == "measured"
    assert measured["boards_readable_only_by_post"] == 0
    assert measured["boards_readable_only_by_post_evaluated"] >= 1
    assert measured["ledger_entries_scanned"] >= connector_transport.MINIMUM_LEDGER_ENTRIES
    assert measured["get_connectors_evaluated"] >= 10
    assert measured["get_connectors_still_plain_gets"] == measured["get_connectors_evaluated"]
    assert measured["boards_refused_on_policy"] == 0
    assert measured["credential_key_misjudged"] == 0
    assert measured["credential_key_cases_checked"] >= connector_transport.MINIMUM_CREDENTIAL_CASES
    assert json.loads((tmp_path / "T89.json").read_text(encoding="utf-8")) == measured

    empty = tmp_path / "empty.yaml"
    empty.write_text("corrected: []\n", encoding="utf-8")
    thin = connector_transport.measure(empty)
    assert thin["gate_status"] == "unmeasured"
    assert thin["boards_readable_only_by_post_evaluated"] == 0


# ---------------------------------------------------------------------------
# `detail_url_template` — a board that publishes an id and a slug, not a URL.
#
# The adversarial half of this coverage (percent-encoding equivalence, host
# escape, every shape of malformed template) is owed to a session other than
# the one that wrote the builder, per CLAUDE.md's "fixtures for a
# correctness-critical gate are written by a second session". What is here is
# the implementer's own reading, which is exactly what that rule says is not
# sufficient on its own.

TEMPLATE_CONNECTOR = """
site: templateboard
locale: en
version: "1.0.0"
last_verified: "2026-09-01"
list:
  url_pattern: "https://templateboard.test/api/jobs"
  from_json:
    items: "$"
    detail_url_template: "https://templateboard.test/jobs/{id}/{slug}"
    fields:
      title: position
detail:
  from_json:
    fields:
      text: description
"""


def test_a_detail_url_is_composed_from_the_records_own_fields() -> None:
    connector = parse_connector(TEMPLATE_CONNECTOR)
    body = json.dumps([{"id": 8451, "slug": "senior-python-engineer", "position": "Senior Python"}])
    (row,) = parse_list_page(connector, body)
    assert row["detail_url"] == "https://templateboard.test/jobs/8451/senior-python-engineer"


def test_a_substituted_value_cannot_leave_the_host_the_template_names() -> None:
    """The template is reviewed; the values are a remote response and are not.

    `quote(..., safe="")` is what keeps a value one opaque segment, so a slug
    of `//elsewhere/x` becomes a path component rather than the authority of a
    protocol-relative URL.
    """
    connector = parse_connector(TEMPLATE_CONNECTOR)
    body = json.dumps([{"id": 1, "slug": "//elsewhere.test/x?a=b#c", "position": "P"}])
    (row,) = parse_list_page(connector, body)
    assert row["detail_url"] == (
        "https://templateboard.test/jobs/1/%2F%2Felsewhere.test%2Fx%3Fa%3Db%23c"
    )
    assert row["detail_url"].startswith("https://templateboard.test/jobs/")


def test_a_record_missing_a_named_field_gets_no_detail_url_rather_than_a_broken_one() -> None:
    """A URL with a hole in it is worse than none on any board that answers 200
    to an unknown id — getmanfred, the board this was written for, renders a
    page with no offer in it rather than a 404."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    body = json.dumps([{"id": 7, "position": "P"}])
    (row,) = parse_list_page(connector, body)
    assert "detail_url" not in row
    assert row["title"] == "P"


@pytest.mark.parametrize(
    "record",
    [
        pytest.param({"id": 7, "slug": "", "position": "P"}, id="empty-slug"),
        pytest.param({"id": "", "slug": "s", "position": "P"}, id="empty-id"),
        pytest.param({"id": 7, "slug": "   ", "position": "P"}, id="blank-slug"),
    ],
)
def test_an_empty_or_blank_value_gets_no_detail_url_either(record: dict[str, object]) -> None:
    """Second-reader audit on #264, D2: the guard was `value is None`, so these
    three rows composed `…/jobs/7/`, `…/jobs//s` and `…/jobs/7/%20%20%20` — the
    hole the docstring promises never to build, on a board that answers 200 to
    the holed path. `_json_record` already read `""` as absent for every mapped
    field; `_present` is now the one rule both of them read."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    (row,) = parse_list_page(connector, json.dumps([record]))
    assert "detail_url" not in row
    assert row["title"] == "P"


@pytest.mark.parametrize("value", ["..", "."])
def test_a_dot_segment_is_refused_rather_than_left_to_steer_the_url(value: str) -> None:
    """Second-reader audit on #264, D3: `.` is unreserved, so `quote(safe="")`
    leaves `..` intact and "one opaque segment" was false for exactly two
    strings. The consequence is measurable against this repo's own robots
    matcher, which answers `True` to `https://www.dice.com/x/../jobs?q=python`
    and `False` to `https://www.dice.com/jobs?q=python` — a remote value
    steering a fetch past the check built to refuse it."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    (row,) = parse_list_page(connector, json.dumps([{"id": value, "slug": "x", "position": "P"}]))
    assert "detail_url" not in row


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Quoting happens before the check, so a percent-encoded spelling of
        # `..` arrives double-encoded and is a segment like any other: the
        # guard refuses two strings, not a family of near-misses.
        ("%2e%2e", "%252e%252e"),
        ("%2E%2E", "%252E%252E"),
        ("...", "..."),
        ("..x", "..x"),
        (".hidden", ".hidden"),
    ],
)
def test_a_value_that_merely_resembles_a_dot_segment_still_composes(
    value: str, expected: str
) -> None:
    """The other half of D3: a guard that over-refused would cost real rows
    their `detail_url`, which is the same silent loss in the other direction."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    (row,) = parse_list_page(connector, json.dumps([{"id": 1, "slug": value, "position": "P"}]))
    assert row["detail_url"] == f"https://templateboard.test/jobs/1/{expected}"


@pytest.mark.parametrize(
    "template",
    [
        "https://b.test/jobs/{0.__class__}",
        "https://b.test/jobs/{}",
        "https://b.test/jobs/{id}{",
        "https://b.test/jobs/{{id}}",
        "https://b.test/jobs/every-row-the-same",
        # Second-reader audit on #264, D7. `{$}` compiled to the empty path and
        # `dig(record, ())` is `None` for any dict row, so the template named no
        # field and silently gave every row no `detail_url` while the "names no
        # field" guard never fired. Fail-closed, and still a template whose
        # author would never learn it did nothing.
        "https://b.test/jobs/{$}",
    ],
)
def test_a_template_outside_the_grammar_is_refused_at_load(template: str) -> None:
    text = TEMPLATE_CONNECTOR.replace(
        'detail_url_template: "https://templateboard.test/jobs/{id}/{slug}"',
        f'detail_url_template: "{template}"',
    )
    with pytest.raises(ConnectorError):
        parse_connector(text)


def test_a_list_may_not_both_map_and_compose_its_detail_url() -> None:
    text = TEMPLATE_CONNECTOR.replace(
        "      title: position",
        "      title: position\n      detail_url: link",
    )
    with pytest.raises(ConnectorError, match="detail_url_template"):
        parse_connector(text)


def test_a_detail_page_may_not_carry_a_detail_url_template() -> None:
    detail_block = "  from_json:\n    fields:\n      text: description"
    with_template = (
        '  from_json:\n    detail_url_template: "https://b.test/{id}"'
        "\n    fields:\n      text: description"
    )
    text = TEMPLATE_CONNECTOR.replace(detail_block, with_template)
    with pytest.raises(ConnectorError, match="detail_url_template"):
        parse_connector(text)


# ---------------------------------------------------------------------------
# Zero is not a wage.


@pytest.mark.parametrize("figure", ["0", "0.0", "-1", "-50000"])
def test_a_salary_figure_of_zero_or_less_is_absent_rather_than_stated(figure: str) -> None:
    """getmanfred's list API sends `salaryFrom: 0` on ten of twenty-one live
    offers beside a real `salaryTo`. Zero there means "no floor stated"; passed
    through it would rank the offer as the worst-paid job on the board."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    offer = build_offer(
        connector,
        list_fields={"salary_min": figure, "salary_max": "65000", "salary_currency": "EUR"},
        detail_fields={"text": "A body long enough to be an advert." * 3},
    )
    assert offer.salary is not None
    assert offer.salary.min is None
    assert offer.salary.max == 65000.0
    assert offer.salary.stated is True


def test_a_currency_with_no_surviving_figure_is_no_salary_at_all() -> None:
    """Second-reader audit on #264, D6. `_as_wage` nulls both figures while the
    old guard asked only whether any salary KEY was present, so a 0/0 advert
    that also sent a currency yielded `Salary(stated=True)` carrying no numbers
    — `ruled-out.yaml`'s caveat: "worse than no salary at all, because the
    ranking uses it". No shipped fixture reaches it today; weworkremotely's
    JSON-LD `minValue '0' / maxValue '0'` is one connector-change away."""
    connector = parse_connector(TEMPLATE_CONNECTOR)
    offer = build_offer(
        connector,
        list_fields={"salary_min": "0", "salary_max": "0", "salary_currency": "EUR"},
        detail_fields={"text": "A body long enough to be an advert." * 3},
    )
    assert offer.salary is None


def test_a_real_floor_still_survives() -> None:
    connector = parse_connector(TEMPLATE_CONNECTOR)
    offer = build_offer(
        connector,
        list_fields={"salary_min": "50000", "salary_max": "60000"},
        detail_fields={"text": "A body long enough to be an advert." * 3},
    )
    assert offer.salary is not None
    assert (offer.salary.min, offer.salary.max) == (50000.0, 60000.0)


def test_getmanfreds_thousands_scale_salary_never_reaches_the_offer() -> None:
    """The board publishes the same band twice, in two units.

    `offer.salaryMin`/`salaryMax` on a Manfred advert page are `50` and `60`
    where its list API says `50000` and `60000`. `build_offer` lets detail win
    on overlap, so a connector mapping the detail figures would publish a
    fifty-euro job and pass every gate — nothing in the schema knows what a
    euro is.

    The package's answer is to declare no salary on the detail route at all, so
    the only figures for this board are the ones already in euros. The fixture
    keeps `salaryMin`/`salaryMax` on purpose; this is the test that could not
    exist without them.
    """
    package = _CONNECTOR_LIBRARY / "getmanfred_es"
    connector = load_connector(package / "connector.yaml")
    detail_bytes = (package / "fixture" / "detail.html").read_text(encoding="utf-8")
    assert '"salaryMin": 50' in detail_bytes and '"salaryMax": 60' in detail_bytes

    detail = parse_detail_page(connector, detail_bytes)
    assert not any(name.startswith("salary") for name in detail)

    rows = parse_list_page(
        connector, (package / "fixture" / "list.html").read_text(encoding="utf-8")
    )
    row = next(r for r in rows if r["salary_min"] != "0")
    offer = build_offer(connector, list_fields=row, detail_fields=detail, url=row["detail_url"])
    assert offer.salary is not None
    assert offer.salary.min is not None and offer.salary.min >= 1000
    assert offer.salary.max is not None and offer.salary.max >= 1000


def test_getmanfreds_detail_urls_are_composed_and_stay_on_the_portal() -> None:
    package = _CONNECTOR_LIBRARY / "getmanfred_es"
    connector = load_connector(package / "connector.yaml")
    rows = parse_list_page(
        connector, (package / "fixture" / "list.html").read_text(encoding="utf-8")
    )
    assert rows
    for row in rows:
        assert row["detail_url"].startswith("https://www.getmanfred.com/ofertas-empleo/")


def test_a_recorded_curl_that_authenticates_is_refused_and_its_secret_is_not_kept() -> None:
    """`-u` and `-b` are credentials curl puts on the wire by itself.

    Neither reaches the URL's query, a `-H` header or the body, so all three of
    `why_refused`'s checks looked and found nothing. The parser consumed both
    options and dropped them, so a board answering only to HTTP Basic parsed
    into a request carrying no credential — and the gate counted it as a board
    the engine could read once it learned to POST. It cannot: `build_list_requests`
    sends neither (#295 review).

    The second assertion is the other half of the rule. A refusal has to name
    the option, and it may not carry the secret: `connectors.py`'s line is that
    a connector may not carry a credential, and a ledger value copied into a
    dataclass and then into an evidence file is exactly that.
    """
    for option, secret in (("-u", "surveyor:hunter2"), ("-b", "session=abc123")):
        recorded = connector_transport.parse_curl(
            f"curl -s -X POST {option} '{secret}' "
            "-H 'Content-Type: application/json' "
            '-d \'{"q":"python"}\' '
            "'https://boards.test/api/search'"
        )
        assert recorded is not None
        refused = connector_transport.why_refused(recorded)
        assert len(refused) == 1, refused
        assert option in ("-u", "-b")
        assert ("--user" if option == "-u" else "--cookie") in refused[0]
        assert secret not in repr(recorded), "the value was kept, not just the option name"
        assert secret not in refused[0]


def test_the_long_spellings_of_the_credential_options_are_refused_too() -> None:
    """`--user` and `--cookie` are the same wire behaviour spelled out, and a
    surveyor pasting a captured command may use either. Matching only the short
    form would leave the fail-open open for half the ways of writing it."""
    for option in ("--user", "--cookie"):
        recorded = connector_transport.parse_curl(
            f"curl -X POST {option} 'x' -d '{{}}' 'https://boards.test/api/search'"
        )
        assert recorded is not None
        assert recorded.credential_options == (option,)
        assert connector_transport.why_refused(recorded) != []


# ---------------------------------------------------------------------------
# `{query}` — the candidate's own search terms reaching the board's search box.


def _with_query_slot() -> str:
    """The worked example, its listing URL given a `{query}` slot."""
    connector = parse_connector(VALID)
    return VALID.replace(
        connector.list.url_pattern,
        connector.list.url_pattern + "&q={query}",
    )


def test_a_query_slot_is_filled_with_the_candidates_terms() -> None:
    connector = parse_connector(_with_query_slot())
    assert accepts_query(connector)
    urls = build_list_urls(connector, page_count=1, query="python")
    assert urls[0].endswith("&q=python")


def test_a_query_is_percent_encoded_rather_than_pasted() -> None:
    """One encoder, `safe=""`, so the slot is correct in a path or a query
    string. A space must not arrive as a space, and `&` must not start a
    parameter the candidate did not ask for."""
    connector = parse_connector(_with_query_slot())
    url = build_list_urls(connector, page_count=1, query="ingeniero de datos & ML")[0]
    assert url.endswith("&q=ingeniero%20de%20datos%20%26%20ML")
    assert " " not in url


def test_a_board_that_asks_what_to_search_for_is_not_searched_for_nothing() -> None:
    """Substituting an empty query would fetch the board's unfiltered list and
    present it as the candidate's search — the silent wrong answer, not an
    empty one."""
    connector = parse_connector(_with_query_slot())
    for nothing in (None, "", "   "):
        with pytest.raises(ConnectorError):
            build_list_urls(connector, page_count=1, query=nothing)


def test_a_board_with_no_query_slot_reports_that_rather_than_pretending() -> None:
    connector = parse_connector(VALID)
    assert not accepts_query(connector)
    assert build_list_urls(connector, page_count=1, query="python") == build_list_urls(
        connector, page_count=1
    )


def test_the_second_placeholder_does_not_reopen_the_first_ones_hole() -> None:
    """`{query}` is a second *literal*, not permission for a template."""
    connector = parse_connector(VALID)
    for hostile in ("{0.__class__}", "{query!r}", "{}", "{QUERY}"):
        body = VALID.replace(connector.list.url_pattern, connector.list.url_pattern + hostile)
        with pytest.raises((ConnectorError, ValidationError, ValueError)):
            parse_connector(body)


def test_every_shipped_connector_that_takes_a_query_still_builds_a_url() -> None:
    """The library's own packages, not a fixture: a `{query}` written into a
    committed `url_pattern` must be reachable through the real builder."""
    steered = []
    for package in sorted(_CONNECTOR_LIBRARY.iterdir()):
        if not (package / "connector.yaml").is_file():
            continue
        connector = parse_connector((package / "connector.yaml").read_text(encoding="utf-8"))
        if not accepts_query(connector):
            continue
        steered.append(package.name)
        url = build_list_urls(connector, page_count=1, query="ingeniero de datos")[0]
        assert "{query}" not in url and "%20" in url
    assert steered, "no shipped connector takes a query — the aim is baked in again"
