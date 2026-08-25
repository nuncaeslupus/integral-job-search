"""T72 — a connector whose selectors no longer match its own markup is
reported broken, never a quiet zero.

Written RED before `integral.connector_health` existed, per the task
payload. `assess` is exercised directly, against the real, committed
`trabajos_es` connector and its own recorded fixture — the same reason
`test_connector_contract.py` breaks a *copy* of the real package rather than
a hand-built look-alike: a fixture nobody re-derives from the real one
drifts away from it unnoticed.
"""

from __future__ import annotations

from pathlib import Path

from integral.connector_health import (
    MAX_PROBE_ATTEMPTS,
    assess,
    free_signals,
    measure,
    on_portal_host,
    probe_fetch,
    undecoded_entities,
)
from integral.connectors import DEFAULT_CONNECTORS_DIR, load_connector

_PACKAGE = DEFAULT_CONNECTORS_DIR / "trabajos_es"
_CONNECTOR = load_connector(_PACKAGE)
_SITE = "trabajos.com"
_LIST_HTML = (_PACKAGE / "fixture" / "list.html").read_text(encoding="utf-8")


def test_a_healthy_connector_over_its_fixture_reads_ok() -> None:
    """The unmutated, committed fixture is what `trabajos_es` actually
    parses today — nothing here should read as breakage."""
    reading = assess(_CONNECTOR, _SITE, baseline_html=_LIST_HTML, probe_html=_LIST_HTML)

    assert reading.health == "healthy"
    assert reading.reasons == ()
    assert reading.baseline_items == reading.probe_items > 0


def test_a_connector_whose_selectors_no_longer_match_is_reported_broken() -> None:
    """Mutate the recorded fixture's markup — the exact class the item
    selector matches, `oferta` — and the connector must not read a restyled
    page as a clean, empty result."""
    mutated = _LIST_HTML.replace("oferta", "posting")

    reading = assess(_CONNECTOR, _SITE, baseline_html=_LIST_HTML, probe_html=mutated)

    assert reading.health == "broken"
    assert reading.probe_items == 0
    assert reading.baseline_items > 0
    assert any("recorded previously" in reason for reason in reading.reasons)


def test_zero_yield_from_a_portal_that_never_yielded_is_not_breakage() -> None:
    """An empty market is not a rotted parser: if the baseline itself never
    yielded anything, a probe that also finds nothing is not a regression."""
    empty = "<html><body>no listings today</body></html>"

    reading = assess(_CONNECTOR, _SITE, baseline_html=empty, probe_html=empty)

    assert reading.health == "healthy"
    assert reading.baseline_items == reading.probe_items == 0


def test_the_gate_does_not_pass_on_an_empty_input_set(tmp_path: Path) -> None:
    """A directory with no installed connectors must not read as a clean
    pass — `connector_runs_evaluated` (and its spec-named twin) must be
    written and non-zero for `gate_status` to say `measured`."""
    measured = measure(directory=tmp_path)

    assert measured["silent_connector_failures"] == 0
    assert measured["connector_runs_evaluated"] == 0
    assert measured["silent_connector_failures_evaluated"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_company_null_on_every_row_is_a_free_signal() -> None:
    items = [{"title": "A", "company": ""}, {"title": "B", "company": ""}]

    assert free_signals(items, _SITE) == ["company is null on every row"]


def test_a_single_populated_row_clears_the_company_signal() -> None:
    items = [{"title": "A", "company": ""}, {"title": "B", "company": "Acme"}]

    assert free_signals(items, _SITE) == []


def test_undecoded_entities_in_titles_is_a_free_signal() -> None:
    assert undecoded_entities(["Café &amp; Bar", "Clean title"]) == ["Café &amp; Bar"]
    assert undecoded_entities(["Clean title"]) == []


def test_detail_url_off_portal_host_is_a_free_signal() -> None:
    items = [{"company": "Acme", "detail_url": "https://tracker.example/x"}]

    reasons = free_signals(items, _SITE)

    assert any("do not point at" in reason for reason in reasons)


def test_a_relative_detail_url_is_not_off_host() -> None:
    """`trabajos_es` links absolutely, but a connector need not — a bare
    path is implicitly on the portal's own host."""
    assert on_portal_host("/ofertas/123/", _SITE) is True
    assert on_portal_host("https://www.trabajos.com/ofertas/123/", _SITE) is True
    assert on_portal_host("https://tracker.example/x", _SITE) is False


def test_probe_retries_once_before_giving_up(tmp_path: Path) -> None:
    calls: list[int] = []

    def flaky(_package: Path) -> str:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("transient")
        return "<html>ok</html>"

    result = probe_fetch(tmp_path, fetch=flaky)

    assert result == "<html>ok</html>"
    assert len(calls) == 2
    assert len(calls) == MAX_PROBE_ATTEMPTS


def test_probe_gives_up_after_the_bounded_number_of_attempts(tmp_path: Path) -> None:
    calls: list[int] = []

    def always_fails(_package: Path) -> str:
        calls.append(1)
        raise OSError("still down")

    result = probe_fetch(tmp_path, fetch=always_fails)

    assert result is None
    assert len(calls) == MAX_PROBE_ATTEMPTS


def test_the_real_library_measures_clean() -> None:
    """The gate as it stands today: the one real, non-example connector
    reads healthy over its own committed fixture."""
    measured = measure()

    assert measured["gate_status"] == "measured"
    assert measured["connector_runs_evaluated"] >= 1
    assert measured["silent_connector_failures"] == 0
