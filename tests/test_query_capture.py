"""T171: a steerable connector's query must sit where a capture recorded one."""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

import pytest

from integral import query_capture as qc
from integral.connectors import DEFAULT_CONNECTORS_DIR, accepts_query, load_connector

_STEERABLE = tuple(
    package.name
    for package in sorted(DEFAULT_CONNECTORS_DIR.iterdir())
    if (package / "connector.yaml").is_file() and accepts_query(load_connector(package))
)


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "connectors"
    shutil.copytree(DEFAULT_CONNECTORS_DIR, root)
    return root


def _swap_query_key(package: Path) -> str:
    """Move `{query}` to a URL position no capture carried; return the new pattern.

    A query-string key gets a suffix. A path segment gets a prefix. Either way
    the connector still loads and sends the terms, only somewhere else.
    """
    yaml_path = package / "connector.yaml"
    text = yaml_path.read_text(encoding="utf-8")
    pattern = load_connector(package).list.url_pattern
    swapped, keys = re.subn(r"([?&][^=&?#]+)=\{query\}", r"\1_swapped={query}", pattern)
    if not keys:
        swapped = pattern.replace("{query}", "swapped-{query}")
    assert swapped != pattern
    assert text.count(pattern) == 1
    yaml_path.write_text(text.replace(pattern, swapped), encoding="utf-8")
    assert load_connector(package).list.url_pattern == swapped
    return swapped


def test_the_library_is_clean_and_meets_the_floor() -> None:
    measured = qc.measure()
    assert measured["findings"] == []
    assert measured["gate_status"] == "measured"
    assert measured["steerable_packages_checked"] == len(_STEERABLE)
    assert len(_STEERABLE) >= qc.MINIMUM_STEERABLE_PACKAGES_CHECKED


@pytest.mark.parametrize("name", _STEERABLE)
def test_swapping_a_steerable_packages_query_key_fails_it_by_name(library: Path, name: str) -> None:
    """The second reader's mutation on #447, derived from the library, not listed."""
    _swap_query_key(library / name)
    measured = qc.measure(library)
    assert [row["package"] for row in measured["findings"]] == [name]
    assert "did not load" not in measured["findings"][0]["reason"]


def test_jobfluents_pre_fix_probe_is_named(library: Path) -> None:
    """The live instance on `main` before T171: a probe that never carried `q`."""
    capture = library / "jobfluent_es" / "probe" / "captured.json"
    record = json.loads(capture.read_text(encoding="utf-8"))
    record["url"] = "https://www.jobfluent.com/es/empleos-barcelona?page=2"
    capture.write_text(json.dumps(record), encoding="utf-8")
    assert [row["package"] for row in qc.measure(library)["findings"]] == ["jobfluent_es"]


def test_a_steerable_package_with_no_capture_is_named(library: Path) -> None:
    name = _STEERABLE[0]
    (library / name / "probe" / "captured.json").unlink()
    assert [row["package"] for row in qc.measure(library)["findings"]] == [name]


def test_an_unreadable_package_is_named_not_skipped(library: Path) -> None:
    """Whether it is steerable is unknown, so it cannot be scored as clean."""
    name = _STEERABLE[0]
    (library / name / "connector.yaml").write_text("list: [", encoding="utf-8")
    measured = qc.measure(library)
    assert [row["package"] for row in measured["findings"]] == [name]
    assert "did not load" in measured["findings"][0]["reason"]


@pytest.mark.parametrize(
    ("pattern", "captured", "measured"),
    [
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=python&page=2", True),
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q=product+manager", True),
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?page=2", False),
        # Empty asks for nothing, so the board's answer is its whole list.
        ("https://b.test/jobs?q={query}&page={page}", "https://b.test/jobs?q=&page=2", False),
        # `url_pattern` copied into the capture with the placeholder unfilled.
        ("https://b.test/jobs?q={query}", "https://b.test/jobs?q={query}", False),
        # A fixed duplicate of the key: the capture must carry both.
        ("https://b.test/jobs?q=all&q={query}", "https://b.test/jobs?q=python", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/python/", True),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs//", False),
        ("https://b.test/jobs/{query}/", "https://b.test/jobs/python/extra/", False),
        ("https://b.test/jobs/{query}/", "https://b.test/other/python/", False),
        ("https://b.test/jobs?q={query}", None, False),
    ],
)
def test_query_measured(pattern: str, captured: str | None, measured: bool) -> None:
    assert qc.query_measured(pattern, captured) is measured


def test_below_the_floor_reads_unmeasured_writes_nothing_and_exits_1(
    library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in _STEERABLE[: len(_STEERABLE) - qc.MINIMUM_STEERABLE_PACKAGES_CHECKED + 1]:
        shutil.rmtree(library / name)
    evidence = tmp_path / "T171.json"
    assert qc.write_evidence(evidence, library)["gate_status"] == "unmeasured"
    assert not evidence.exists()
    monkeypatch.setattr(qc, "DEFAULT_CONNECTORS_DIR", library)
    assert qc._main(["query_capture", str(evidence)]) == 1


def test_a_finding_exits_1(library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _swap_query_key(library / _STEERABLE[0])
    monkeypatch.setattr(qc, "DEFAULT_CONNECTORS_DIR", library)
    assert qc._main(["query_capture", str(tmp_path / "T171.json")]) == 1


def test_the_floor_is_a_literal_and_is_what_the_evidence_commits() -> None:
    """T122's pin, read over every assignment (`ast.walk`, per T160)."""
    tree = ast.parse(Path(qc.__file__).read_text(encoding="utf-8"))
    bound = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "MINIMUM_STEERABLE_PACKAGES_CHECKED"
            for t in node.targets
        )
    ]
    assert len(bound) == 1
    assert isinstance(bound[0], ast.Constant)
    assert isinstance(bound[0].value, int)
    committed = json.loads(qc.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))
    assert committed["steerable_packages_checked_at_least"] == bound[0].value
    assert "steerable_packages_checked" not in committed
