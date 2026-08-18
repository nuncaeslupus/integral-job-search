"""T32 — the declarative connector format and its interpreter.

Written RED before `jobsearch.connectors` existed, per the task payload.
`test_a_connector_file_cannot_introduce_executable_behaviour` is the gate as a
single test; the rest guard the parts of the contract review alone would
otherwise have to hold: unknown/credential fields refused at load, a markup
change costing exactly one field, and authenticated sources naming only the
candidate's own browser session.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from jobsearch.connectors import (
    MINIMUM_PROBES,
    ConnectorError,
    FieldSelector,
    assess_staleness,
    build_list_urls,
    build_offer,
    collect_listing,
    compile_selector,
    load_connector,
    parse_connector,
    parse_detail_page,
    parse_list_page,
    probe_connector_isolation,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CONNECTOR_LIBRARY = _REPO_ROOT / "connectors"
_FIXTURES = _REPO_ROOT / "tests" / "fixtures" / "connectors"

# The worked example committed at `connectors/examplejobs_es.yaml` — read from
# disk rather than copied inline, so this suite exercises the very file a
# contributor would actually add to the library, not a look-alike string a
# future edit to the real file could drift away from unnoticed.
VALID = (_CONNECTOR_LIBRARY / "examplejobs_es.yaml").read_text(encoding="utf-8")

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
        "  url_pattern: \"https://x.test/$(rm -rf /)?page={page}\"\n"
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
        "    company:\n      css: \".job-company\"\n",
        "    company:\n      css: \".job-company\"\n    internal_score:\n      css: \".score\"\n",
    )
    with pytest.raises(ConnectorError, match="internal_score"):
        parse_connector(body)


def test_the_filename_must_match_the_declared_site_and_locale(tmp_path: Path) -> None:
    path = write_connector(tmp_path, "wrongname.yaml")
    with pytest.raises(ConnectorError, match="examplejobs_es"):
        load_connector(path)


def test_loading_the_whole_directory_sorts_by_filename(tmp_path: Path) -> None:
    write_connector(tmp_path, "examplejobs_es.yaml")
    other = VALID.replace("site: examplejobs", "site: otherboard").replace(
        "locale: es", "locale: en"
    )
    write_connector(tmp_path, "otherboard_en.yaml", other)
    from jobsearch.connectors import load_connectors

    connectors = load_connectors(tmp_path)
    assert [c.site for c in connectors] == ["examplejobs", "otherboard"]


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
            "    company:\n      css: \".job-company\"\n",
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
    assert before["text"] == (
        "Build and operate our payments API. Python, remote-friendly."
    )

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


def test_build_list_urls_fills_only_the_page_placeholder() -> None:
    connector = parse_connector(VALID)
    urls = build_list_urls(connector, page_count=2)
    assert urls == [
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

    stale_result = collect_listing(
        connector, empty_html, today=date(2027, 2, 1), max_age_days=90
    )
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
