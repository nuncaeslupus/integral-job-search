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

import pytest

from integral import connector_health
from integral.connector_health import (
    MAX_PROBE_ATTEMPTS,
    PROBE_CAPTURE_FILE,
    assess,
    assess_package,
    default_fetch,
    free_signals,
    measure,
    on_portal_host,
    probe_captured_at,
    probe_fetch,
    undecoded_entities,
)
from integral.connectors import DEFAULT_CONNECTORS_DIR, PROBE_DIRNAME, load_connector

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


def test_an_explicit_port_is_the_same_host() -> None:
    """`netloc` carries the port, so comparing it directly reads
    `trabajos.com:443` as a different site. `hostname` does not."""
    assert on_portal_host("https://trabajos.com:443/ofertas/123/", _SITE) is True
    assert on_portal_host("https://www.trabajos.com:8080/x", _SITE) is True
    assert on_portal_host("https://tracker.example:443/x", _SITE) is False


def test_a_malformed_url_is_off_host_and_does_not_raise() -> None:
    """`urlsplit` raises on a malformed authority. A connector emitting one is
    the rot this module catches, so it must be a signal, not an exception that
    aborts the whole measurement."""
    assert on_portal_host("https://[::1", _SITE) is False

    items = [{"company": "Acme", "detail_url": "https://[::1"}]
    reasons = free_signals(items, _SITE)

    assert any("do not point at" in reason for reason in reasons)


def test_an_opaque_scheme_is_not_a_relative_url() -> None:
    """`mailto:` and `javascript:` also parse to an empty `netloc`, so a
    bare emptiness test waves them through as on-host. They are neither
    relative nor on the portal."""
    assert on_portal_host("mailto:jobs@example.com", _SITE) is False
    assert on_portal_host("javascript:void(0)", _SITE) is False


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


def test_the_real_library_never_reports_measured_without_full_probe_coverage() -> None:
    """The invariant over the real library, not today's snapshot of it.

    An earlier version of this test asserted `connector_runs_probed == 0`,
    which pinned the repository's *current* lack of a capture. Capturing
    `connectors/trabajos_es/probe/list.html` on the laptop is the documented
    step that finishes T72 — so that assertion would have failed at exactly
    the moment the task was completed, and the completion step would have
    looked like a regression.

    What must hold in both states is the relationship: a connector that was
    not probed cannot be counted as measured, because the rot stage did not
    run for it."""
    measured = measure()

    evaluated = measured["connector_runs_evaluated"]
    probed = measured["connector_runs_probed"]

    assert evaluated >= 1
    assert 0 <= probed <= evaluated
    assert measured["gate_status"] == ("measured" if probed == evaluated else "unmeasured")
    assert measured["silent_connector_failures"] == 0


def test_the_default_probe_never_reads_the_baseline_fixture(tmp_path: Path) -> None:
    """The regression that matters most. `default_fetch` reading the same
    `fixture/list.html` that `assess` uses as its baseline made the whole
    module compare a string with itself: `silent_connector_failures` could
    only ever be 0, while the evidence recorded `gate_status: measured`.

    A package carrying a fixture and no probe must therefore raise, not
    return the fixture."""
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "list.html").write_text(_LIST_HTML, encoding="utf-8")

    with pytest.raises(OSError):
        default_fetch(tmp_path)

    assert probe_fetch(tmp_path) is None


def test_a_captured_probe_is_what_default_fetch_returns(tmp_path: Path) -> None:
    """And the positive half: a probe capture beside the fixture is read,
    and it is that file's bytes rather than the fixture's."""
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "list.html").write_text(_LIST_HTML, encoding="utf-8")
    (tmp_path / PROBE_DIRNAME).mkdir()
    (tmp_path / PROBE_DIRNAME / "list.html").write_text("<html>today</html>", encoding="utf-8")

    assert default_fetch(tmp_path) == "<html>today</html>"


def test_an_unprobed_reading_cannot_report_rot() -> None:
    """With no probe, the regression branch must not fire — and must not be
    faked green either. The reading is marked unprobed, and that is what
    `measure` reads to withhold `measured`."""
    reading = assess(_CONNECTOR, _SITE, baseline_html=_LIST_HTML, probe_html=None)

    assert reading.probed is False
    assert reading.probe_items == 0
    assert reading.baseline_items > 0
    assert not any("recorded previously" in reason for reason in reading.reasons)


def test_free_signals_still_run_over_the_baseline_when_unprobed() -> None:
    """A defect visible in the recorded evidence costs no request to see, so
    the free pass must still reach a verdict with no probe — that is the task
    payload's "the free pass runs first and must be able to reach a verdict
    alone". Here every `detail_url` is redirected off the portal's own host."""
    rotted = _LIST_HTML.replace("https://www.trabajos.com/ofertas/", "https://scraped.example/o/")

    reading = assess(_CONNECTOR, _SITE, baseline_html=rotted, probe_html=None)

    assert reading.probed is False
    assert reading.health == "broken"
    assert any("do not point at" in reason for reason in reading.reasons)


def test_a_detected_violation_fails_even_when_another_connector_is_unprobed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`unmeasured` is only honest when there is nothing to report.

    Testing it first meant one unprobed connector turned every real finding on
    every other connector into exit 3, which `make evidence` records as
    "unmeasured (recorded)" and walks past — the module built to catch a
    connector failing silently, failing silently."""
    payload = {
        "silent_connector_failures": 2,
        "connector_runs_evaluated": 2,
        "connector_runs_probed": 1,
        "gate_status": "unmeasured",
        "readings": [
            {"connector": "a", "probed": True, "reasons": ["every row has a null company"]},
            {"connector": "b", "probed": False, "reasons": []},
        ],
    }
    monkeypatch.setattr(connector_health, "write_evidence", lambda path: payload)

    assert connector_health._main(["--path", str(tmp_path / "T72.json")]) == 1


def test_an_unmeasured_run_with_nothing_found_still_exits_three(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The honest third outcome survives the fix above."""
    payload = {
        "silent_connector_failures": 0,
        "connector_runs_evaluated": 1,
        "connector_runs_probed": 0,
        "gate_status": "unmeasured",
        "readings": [{"connector": "a", "probed": False, "reasons": []}],
    }
    monkeypatch.setattr(connector_health, "write_evidence", lambda path: payload)

    assert connector_health._main(["--path", str(tmp_path / "T72.json")]) == 3


def test_a_probe_that_is_not_valid_utf8_reads_as_no_probe(tmp_path: Path) -> None:
    """`read_text` raises UnicodeDecodeError, which is a ValueError and not an
    OSError. Catching OSError alone let it escape past `write_evidence`, so a
    corrupt capture produced no evidence at all rather than an unmeasured gate."""
    probe = tmp_path / PROBE_DIRNAME
    probe.mkdir()
    (probe / "list.html").write_bytes(b"\xff")

    assert connector_health.probe_fetch(tmp_path) is None


@pytest.mark.parametrize(
    "url",
    ["https://trabajos.com:not-a-port/x", "https://trabajos.com:65536/x"],
)
def test_a_malformed_port_is_off_host(url: str) -> None:
    """`urlsplit` defers port validation to attribute access, so these parse
    fine and leave `hostname` intact — reading as on-host and raising no signal."""
    assert connector_health.on_portal_host(url, "trabajos.com") is False


def test_a_valid_explicit_port_is_still_on_host() -> None:
    """The fix above must not make every ported URL off-host."""
    assert connector_health.on_portal_host("https://trabajos.com:443/x", "trabajos.com") is True


def _package_with_probe(tmp_path: Path, *, captured: str | None) -> Path:
    """A connector package whose probe is a real second capture of the baseline."""
    (tmp_path / "connector.yaml").write_text(
        (_PACKAGE / "connector.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "list.html").write_text(_LIST_HTML, encoding="utf-8")
    (tmp_path / PROBE_DIRNAME).mkdir()
    (tmp_path / PROBE_DIRNAME / "list.html").write_text(_LIST_HTML, encoding="utf-8")
    if captured is not None:
        (tmp_path / PROBE_DIRNAME / PROBE_CAPTURE_FILE).write_text(captured, encoding="utf-8")
    return tmp_path


def test_the_evidence_records_when_the_probe_was_captured(tmp_path: Path) -> None:
    """A committed probe says how current it is, or the verdict cannot be dated."""
    package = _package_with_probe(tmp_path, captured='{"captured_at": "2026-08-28"}')

    reading = assess_package(package, _CONNECTOR, _SITE)

    assert reading.probed is True
    assert reading.probe_captured_at == "2026-08-28"


def test_the_real_library_dates_every_probe_it_reports_as_measured() -> None:
    """The committed probe must carry its date, or `measured` cannot be read."""
    measured = measure()

    if measured["gate_status"] != "measured":
        pytest.skip("no probe captured in this checkout")
    dated = [r for r in measured["readings"] if r["probed"]]
    assert dated, "a measured gate probed something"
    assert all(r["probe_captured_at"] for r in dated), measured["readings"]


@pytest.mark.parametrize(
    "captured",
    [
        None,
        "not json at all",
        "{}",
        '{"captured_at": ""}',
        "[]",
    ],
)
def test_an_undated_probe_reports_no_date_rather_than_raising(
    tmp_path: Path, captured: str | None
) -> None:
    """Every way of failing to say when is the same answer: it does not say."""
    package = _package_with_probe(tmp_path, captured=captured)

    assert probe_captured_at(package) is None
    assert assess_package(package, _CONNECTOR, _SITE).probe_captured_at is None


def test_an_unprobed_reading_carries_no_capture_date(tmp_path: Path) -> None:
    """Dating a rot stage that never ran would claim a read nobody took."""
    (tmp_path / "connector.yaml").write_text(
        (_PACKAGE / "connector.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "fixture").mkdir()
    (tmp_path / "fixture" / "list.html").write_text(_LIST_HTML, encoding="utf-8")
    (tmp_path / PROBE_DIRNAME).mkdir()
    (tmp_path / PROBE_DIRNAME / PROBE_CAPTURE_FILE).write_text(
        '{"captured_at": "2026-08-28"}', encoding="utf-8"
    )

    reading = assess_package(tmp_path, _CONNECTOR, _SITE)

    assert reading.probed is False
    assert reading.probe_captured_at is None


def test_the_capture_date_is_read_from_the_file_not_the_filesystem(tmp_path: Path) -> None:
    """A checkout does not preserve mtimes; a date derived from one would differ
    per clone and drift `make evidence` on a file nobody edited."""
    package = _package_with_probe(tmp_path, captured='{"captured_at": "1999-01-01"}')

    assert probe_captured_at(package) == "1999-01-01"
