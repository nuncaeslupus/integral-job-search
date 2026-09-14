"""T110: what `integral.bodyless_post` measures, and what it refuses to call a pass.

`tests/test_connectors.py` holds the behaviour — a POST and a body imply each
other, in both directions. What is here is the *measurement*: that its zero is
not reachable by an empty scan, by a probe table somebody emptied, by refusing
every shape, or by a report that dies rather than reporting.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from integral import bodyless_post, connectors
from integral.connectors import JSON_CONTENT_TYPE


def test_the_committed_measurement_is_a_measured_zero() -> None:
    """The gate itself. Named after the wrong outcome — a *request* built, not
    a document accepted — so it cannot be satisfied by there being no such
    documents."""
    measured = bodyless_post.measure()
    assert measured["bodyless_posts_sent_without_a_content_type"] == 0
    assert measured["legal_shapes_refused"] == 0
    assert measured["disagreements"] == []
    assert measured["gate_status"] == "measured"
    assert measured["packages_checked"] >= bodyless_post.MINIMUM_PACKAGES
    assert measured["probes_checked"] >= bodyless_post.MINIMUM_PROBES


def test_every_shipped_package_is_the_denominator(tmp_path: Path) -> None:
    """The library is enumerated from disk, so a package added later is covered
    without anybody remembering to list it — and a scan that found nothing is
    reported as unmeasured rather than as a clean zero, which is the vacuous
    pass a floor exists to refuse (T100's precedent)."""
    empty = tmp_path / "connectors"
    empty.mkdir()
    measured = bodyless_post.measure(directory=empty)
    assert measured["packages_checked"] == 0
    assert measured["gate_status"] == "unmeasured"
    assert "floor" in measured["unmeasured_reason"]
    # The floor is a guard, not a decoration: it has to sit under what the
    # repository actually carries.
    live = bodyless_post.measure()
    assert live["packages_checked"] >= bodyless_post.MINIMUM_PACKAGES


def test_an_emptied_probe_table_is_not_a_pass() -> None:
    """The other denominator. Zero disagreements over two probes is what a
    table somebody trimmed also reports."""
    measured = bodyless_post.measure(probes=bodyless_post.PROBES[:2])
    assert measured["gate_status"] == "unmeasured"
    assert measured["probes_checked"] == 2
    assert measured["probes_at_least"] == bodyless_post.MINIMUM_PROBES


def test_a_deliberately_wrong_probe_table_is_reported() -> None:
    """Each verdict in the table is load-bearing: invert one and the
    measurement must name it. A table whose rows can be flipped without the
    metric moving is a table that is not being read."""
    table = bodyless_post.PROBES
    for index, probe in enumerate(table):
        wrong = (
            bodyless_post.BUILDS
            if probe.verdict != bodyless_post.BUILDS
            else bodyless_post.REFUSED_AT_LOAD
        )
        flipped = (*table[:index], replace(probe, verdict=wrong), *table[index + 1 :])
        measured = bodyless_post.measure(probes=flipped)
        named = {row["probe"] for row in measured["disagreements"]}
        assert named == {probe.name}, probe.name


def test_refusing_a_legal_shape_is_counted_separately() -> None:
    """Zero bodyless POSTs is trivially reached by refusing every request, and
    "a GET with no body" is the shape twenty of the twenty-one committed
    packages have. The fail-closed overreach therefore has its own count, and
    a probe the rule says must build and does not lands in it."""
    legal = next(p for p in bodyless_post.PROBES if p.verdict == bodyless_post.BUILDS)
    # A GET whose body is declared is refused at load — a legal-shape probe
    # pointed at an illegal document, which is what the overreach looks like
    # from this module's side.
    over_refused = replace(
        legal, name="over-refused", method="GET", body_json={"Keyword": "python"}
    )
    measured = bodyless_post.measure(probes=(*bodyless_post.PROBES, over_refused))
    assert measured["legal_shapes_refused"] == 1
    assert measured["bodyless_posts_sent_without_a_content_type"] == 0
    assert [row["direction"] for row in measured["disagreements"]] == ["fail-closed"]


def test_a_package_that_stops_building_is_reported_not_skipped(tmp_path: Path) -> None:
    """A committed package is a legal shape by construction, so a refusal is
    the fail-closed finding and not a package to pass over. Skipping it would
    let "widen the load check until nothing loads" report zero offenders;
    letting the exception escape would abort the run and write no evidence at
    all."""
    library = tmp_path / "connectors"
    (library / "broken_en").mkdir(parents=True)
    (library / "broken_en" / "connector.yaml").write_text("site: broken\n", encoding="utf-8")
    offenders, refused, checked = bodyless_post.library_offenders(library)
    assert (offenders, checked) == ([], 1)
    assert len(refused) == 1 and refused[0].startswith("broken_en: ")


def test_a_broken_scaffold_is_not_reported_as_a_verdict_about_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unvalidated probe borrows a scaffold — a legal GET with no body — and
    a refusal of *that* is a defect in the harness, not a verdict about the
    shape under test. Both are refusals at load, so only the message tells them
    apart, and a finding attributed to the wrong input is the one error a
    reader of this record cannot correct for."""
    broken = dict(bodyless_post._DOCUMENT)
    broken["list"] = {**broken["list"], "url_pattern": ""}
    monkeypatch.setattr(bodyless_post, "_DOCUMENT", broken)
    probe = next(p for p in bodyless_post.PROBES if not p.validated)
    verdict, requests, refusal = bodyless_post._built(probe)
    assert (verdict, requests) == (bodyless_post.REFUSED_AT_LOAD, [])
    assert refusal.startswith("the probe scaffold itself was refused: ")


def test_the_metric_counts_a_request_and_not_a_document() -> None:
    """`_offending` is the metric's definition, in one place. All three
    conditions matter: a POST carrying `Content-Type` over an empty body is a
    different (and stranger) defect than T110's, and reporting it as this one
    would misname what was measured."""

    class _Request:
        def __init__(self, method: str, body: bytes | None, headers: dict[str, str]) -> None:
            self.method, self.body, self.headers = method, body, headers

    assert bodyless_post._offending([_Request("POST", None, {})]) == 1
    # Case-insensitively, because RFC 9110 §5.1 says a field name is.
    assert bodyless_post._offending([_Request("POST", None, {"content-type": "x"})]) == 0
    assert bodyless_post._offending([_Request("POST", b"{}", {})]) == 0
    assert bodyless_post._offending([_Request("GET", None, {})]) == 0


def test_every_rule_clause_is_cited_by_a_probe() -> None:
    """A clause nothing cites is a rule nothing checks. `RULE` is the text the
    verdicts are derived from — the spec read first, never a description of
    what the code already does — so an unused clause means either a missing
    probe or a rule the module has stopped keeping."""
    cited = {probe.clause for probe in bodyless_post.PROBES}
    for clause in bodyless_post.RULE:
        name = clause.split(":", 1)[0]
        if name == "R1":
            # R1 is the premise the others are argued from — where
            # `Content-Type` comes from — and is asserted through R5's probes
            # rather than by a shape of its own.
            continue
        assert name in cited, clause


def test_the_record_is_written_where_the_evidence_lives(tmp_path: Path) -> None:
    """`make evidence` regenerates and diffs; this is what it writes."""
    target = tmp_path / "T110.json"
    bodyless_post.write_evidence(target)
    committed = json.loads(target.read_text(encoding="utf-8"))
    assert committed["bodyless_posts_sent_without_a_content_type"] == 0
    assert committed["packages_checked_at_least"] == bodyless_post.MINIMUM_PACKAGES
    assert bodyless_post.DEFAULT_EVIDENCE_PATH.name == "T110.json"


def test_adding_a_connector_package_does_not_change_any_committed_value(
    tmp_path: Path,
) -> None:
    """T100's rule, at the point where it bites. `make evidence` diffs
    `status/evidence/` byte for byte, so an exact package count committed here
    would be regenerated with a new value by any PR that adds a connector and
    would redden that PR's gate over a change that is not a finding —
    `status/evidence/T89.json`'s analogous count has already drifted once
    (T111). The floor does the denominator's real job, which is to refuse a
    zero resting on an empty scan, and it does not move."""
    library = tmp_path / "connectors"
    library.mkdir()
    for package in connectors.connector_packages(bodyless_post.DEFAULT_CONNECTORS_DIR):
        target = library / package.name
        target.mkdir()
        shutil.copy(package / "connector.yaml", target / "connector.yaml")
    before_measured = bodyless_post.measure(directory=library)
    before = bodyless_post.record(before_measured)

    # One more package, built from an existing one so it really loads.
    donor = library / "examplejobs_es"
    grown = library / "zzexample_es"
    grown.mkdir()
    (grown / "connector.yaml").write_text(
        (donor / "connector.yaml")
        .read_text(encoding="utf-8")
        .replace("site: examplejobs", "site: zzexample"),
        encoding="utf-8",
    )
    after_measured = bodyless_post.measure(directory=library)
    # Against the live count, not the floor: pinning `floor + 2` made this
    # test itself package-sensitive, and it went red when T144 added five.
    assert after_measured["packages_checked"] == before_measured["packages_checked"] + 1, (
        "the live count must move, or this test is asserting nothing"
    )
    assert bodyless_post.record(after_measured) == before
    assert "packages_checked" not in before


@pytest.mark.parametrize("probe", bodyless_post.PROBES, ids=lambda probe: probe.name)
def test_a_post_that_builds_always_carries_the_json_content_type(
    probe: bodyless_post.Probe,
) -> None:
    """R5, asserted per probe rather than only inside `measure`, so the header
    is checked by `make test` and not only by the evidence run."""
    verdict, requests, _ = bodyless_post._built(probe)
    if verdict != bodyless_post.BUILDS:
        pytest.skip("this probe is refused, which is its verdict")
    for request in requests:
        if request.method == "POST":
            assert request.headers["Content-Type"] == JSON_CONTENT_TYPE
        else:
            assert "Content-Type" not in request.headers
