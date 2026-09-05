"""T127 — a probe that names the same offers as its fixture compares nothing.

`assess_package` calls a parser healthy when the fixture and the probe both
yield offers. That is only a check if the two pages carry **different** offers:
a probe holding the same adverts exercises the same markup, so a parser that
broke on anything new would still be called healthy.

`connector_health.py`'s own header records this being fixed once, in the code —
an earlier revision pointed the probe at `fixture/list.html`. The data was
never checked, and two packages were still tautological when this was written:
`ticjob_es` (byte-identical) and `getmanfred_es` (14 bytes apart, naming the
same three offers, which no byte comparison would have caught).

The controls matter more than the measurement here. A count of tautologies is
satisfied by returning zero, so three of these tests assert that the module
*can* report a defect, and that it refuses to score one where it read nothing.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from integral.connector_health import (
    MINIMUM_PROBES_COMPARED,
    list_references,
    measure_probe_divergence,
    probe_divergence,
    write_divergence_evidence,
)
from integral.connectors import DEFAULT_CONNECTORS_DIR, load_connector

REAL = DEFAULT_CONNECTORS_DIR / "tecnoempleo_es"


def _copy(package: Path, destination: Path) -> Path:
    """A copy of a real package, so a mutated case never drifts from the original."""
    target = destination / package.name
    shutil.copytree(package, target)
    return target


def test_the_committed_library_has_no_tautological_probe() -> None:
    measured = measure_probe_divergence()
    assert measured["connectors_whose_probe_repeats_its_fixture"] == 0, measured[
        "tautological_probes"
    ]
    assert measured["gate_status"] == "measured"
    assert measured["probes_compared"] >= MINIMUM_PROBES_COMPARED


def test_a_probe_copied_from_its_fixture_is_reported(tmp_path: Path) -> None:
    """The control. Without it a zero means nothing — this is `ticjob_es` restored."""
    package = _copy(REAL, tmp_path)
    shutil.copyfile(package / "fixture" / "list.html", package / "probe" / "list.html")

    reading = probe_divergence(package, load_connector(package / "connector.yaml"))

    assert reading["compared"] is True
    assert reading["repeats_the_fixture"] is True
    assert reading["overlap"] == 1.0
    assert reading["byte_identical"] is True


def test_a_probe_naming_the_same_offers_is_reported_though_the_bytes_differ(
    tmp_path: Path,
) -> None:
    """`getmanfred_es`: 14 bytes apart, same three offers. A byte check passes it."""
    package = _copy(REAL, tmp_path)
    probe = package / "probe" / "list.html"
    # One byte of whitespace, in no field this connector maps.
    probe.write_text(
        (package / "fixture" / "list.html").read_text(encoding="utf-8") + "\n<!-- -->",
        encoding="utf-8",
    )

    reading = probe_divergence(package, load_connector(package / "connector.yaml"))

    assert reading["byte_identical"] is False, "the premise: the files are not equal"
    assert reading["repeats_the_fixture"] is True, "and the check catches it anyway"


def test_one_new_offer_is_enough_to_have_compared_something(tmp_path: Path) -> None:
    """The boundary is one, not a threshold — a probe adding an advert does compare."""
    package = _copy(REAL, tmp_path)
    real_probe = load_connector(package / "connector.yaml")
    fixture_html = (package / "fixture" / "list.html").read_text(encoding="utf-8")
    probe_html = (package / "probe" / "list.html").read_text(encoding="utf-8")
    shared = list_references(real_probe, fixture_html) & list_references(real_probe, probe_html)
    assert not shared, "the committed pair already diverges; this test needs that"

    reading = probe_divergence(package, real_probe)
    assert reading["repeats_the_fixture"] is False
    assert reading["overlap"] == 0.0


def test_a_probe_that_parses_to_nothing_is_unmeasured_not_a_tautology(tmp_path: Path) -> None:
    """The fail-open control.

    Scoring an empty parse as 100% overlap would report the parser's own
    failure as a tautology and send a reader to re-capture a probe that was
    fine. `shared == probe_refs` is true for two empty sets, so this is the
    reading the naive expression gives.
    """
    package = _copy(REAL, tmp_path)
    (package / "probe" / "list.html").write_text("<html><body></body></html>", encoding="utf-8")

    reading = probe_divergence(package, load_connector(package / "connector.yaml"))

    assert reading["compared"] is False
    assert "parsed no offers" in reading["reason"]
    assert "repeats_the_fixture" not in reading


def test_a_missing_probe_is_not_counted_as_a_pass(tmp_path: Path) -> None:
    package = _copy(REAL, tmp_path)
    shutil.rmtree(package / "probe")

    reading = probe_divergence(package, load_connector(package / "connector.yaml"))

    assert reading["compared"] is False
    assert reading["reason"] == "no probe"


def test_a_library_with_too_few_probes_is_unmeasured(tmp_path: Path) -> None:
    """A floor, so a clean zero cannot rest on an empty scan.

    A library that lost every probe would otherwise report zero tautologies and
    pass — which is the exact reading this must not be able to give.
    """
    _copy(REAL, tmp_path)

    measured = measure_probe_divergence(tmp_path)

    assert measured["probes_compared"] == 1
    assert measured["gate_status"] == "unmeasured"
    assert measured["connectors_whose_probe_repeats_its_fixture"] == 0, (
        "zero is the honest count of a library holding one good probe — "
        "it is `gate_status` that must refuse to call it a measurement"
    )


def test_the_evidence_file_records_which_packages(tmp_path: Path) -> None:
    written = write_divergence_evidence(tmp_path / "T127.json")
    assert (tmp_path / "T127.json").exists()
    assert written["tautological_probes"] == []
    assert {r["package"] for r in written["readings"]} >= {"ticjob_es", "getmanfred_es"}


@pytest.mark.parametrize("package_name", ["ticjob_es", "getmanfred_es"])
def test_the_two_packages_this_task_re_captured_now_diverge(package_name: str) -> None:
    package = DEFAULT_CONNECTORS_DIR / package_name
    reading = probe_divergence(package, load_connector(package / "connector.yaml"))
    assert reading["compared"] is True
    assert reading["shared_offers"] == 0
