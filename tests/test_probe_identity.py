"""T117 — the byte-identity census: a probe equal to its fixture compares nothing.

The count is over every shipped package and compares bytes, so no parser, and
no connector's own idea of what an offer is, can hide an identical pair.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from integral.connector_health import (
    MINIMUM_PACKAGES_BYTE_COMPARED,
    measure_probe_identity,
    write_identity_evidence,
)
from integral.connectors import DEFAULT_CONNECTORS_DIR, connector_packages


def test_no_shipped_package_probes_its_own_fixture() -> None:
    measured = measure_probe_identity()
    assert measured["probes_identical_to_their_fixture"] == 0, measured["identical_packages"]
    assert measured["gate_status"] == "measured"
    assert measured["packages_byte_compared"] >= MINIMUM_PACKAGES_BYTE_COMPARED


def _library(
    tmp_path: Path, *, restore_identity: str | None = None, keep: int | None = None
) -> Path:
    packages = connector_packages(DEFAULT_CONNECTORS_DIR)
    for package in packages[:keep]:
        shutil.copytree(package, tmp_path / package.name)
    if restore_identity:
        target = tmp_path / restore_identity
        shutil.copyfile(target / "fixture" / "list.html", target / "probe" / "list.html")
    return tmp_path


def test_the_control_an_identical_pair_is_counted_and_named(tmp_path: Path) -> None:
    measured = measure_probe_identity(_library(tmp_path, restore_identity="tecnoempleo_es"))
    assert measured["probes_identical_to_their_fixture"] == 1
    assert measured["identical_packages"] == ["tecnoempleo_es"]


def test_one_byte_of_difference_is_not_identity(tmp_path: Path) -> None:
    library = _library(tmp_path)
    probe = library / "tecnoempleo_es" / "probe" / "list.html"
    shutil.copyfile(library / "tecnoempleo_es" / "fixture" / "list.html", probe)
    probe.write_bytes(probe.read_bytes() + b"\n")
    assert measure_probe_identity(library)["probes_identical_to_their_fixture"] == 0


def test_a_scan_under_the_floor_is_unmeasured_not_a_clean_zero(tmp_path: Path) -> None:
    measured = measure_probe_identity(_library(tmp_path, keep=MINIMUM_PACKAGES_BYTE_COMPARED - 1))
    assert measured["probes_identical_to_their_fixture"] == 0
    assert measured["gate_status"] == "unmeasured"


def test_a_package_without_a_probe_is_named_not_passed(tmp_path: Path) -> None:
    library = _library(tmp_path)
    (library / "tecnoempleo_es" / "probe" / "list.html").unlink()
    measured = measure_probe_identity(library)
    assert "tecnoempleo_es" in measured["packages_not_compared"]


def test_the_evidence_file_records_the_key(tmp_path: Path) -> None:
    target = tmp_path / "T117.json"
    measured = write_identity_evidence(target)
    assert '"probes_identical_to_their_fixture": 0' in target.read_text(encoding="utf-8")
    assert measured["gate_status"] == "measured"
