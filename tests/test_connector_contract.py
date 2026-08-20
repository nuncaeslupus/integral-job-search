"""T53 — what a connector must satisfy to be shared, and the check that says so.

Written against the committed package at `connectors/examplejobs_es/` rather
than against strings built inline, for the reason `test_connectors.py` gives
about the connector file itself: a look-alike fixture drifts away from the real
one, unnoticed, the first time somebody edits the real one.

Every negative test **breaks a copy of the real package**. That is the shape
that matters here: the check has to fail on something that was passing a moment
ago, for the one reason the test changed. A hand-built broken package can fail
for a reason nobody intended — a missing key the check happens to look at first
— and still look like proof.
"""

from __future__ import annotations

import ast
import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from jobsearch.connector_contract import (
    MINIMUM_PACKAGES,
    _main,
    check_library,
    check_package,
    write_evidence,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LIBRARY = _REPO_ROOT / "connectors"
_REFERENCE = _LIBRARY / "examplejobs_es"


@pytest.fixture
def package(tmp_path: Path) -> Path:
    """A byte-for-byte copy of the committed package, for a test to break."""
    target = tmp_path / "connectors" / _REFERENCE.name
    shutil.copytree(_REFERENCE, target)
    return target


def _edit_meta(package: Path, mutate: Callable[[dict[str, Any]], object]) -> None:
    meta_path = package / "meta.yaml"
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    mutate(meta)
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# the gate, as a test


def test_the_committed_library_conforms() -> None:
    """The gate: every package in the library satisfies all six rules.

    And it is checked over something — `packages_checked` is asserted too,
    because "0 violations" over an empty directory reads exactly like
    "0 violations" over a directory that was examined.
    """
    report = check_library(_LIBRARY)
    assert report.violations == []
    assert len(report.packages) >= MINIMUM_PACKAGES


def test_the_reference_package_is_the_one_the_library_ships() -> None:
    """The tests break a copy of the real package, not a look-alike."""
    assert _REFERENCE.is_dir()
    assert check_package(_REFERENCE).violations == ()


# ---------------------------------------------------------------------------
# rule 2 — a fixture is present, and the connector's output over it is an offer


def test_a_connector_without_a_fixture_is_rejected(package: Path) -> None:
    """No fixture, no merge. A connector nobody can check offline is unreviewable."""
    shutil.rmtree(package / "fixture")
    violations = check_package(package).violations
    assert any("fixture" in v for v in violations), violations


def test_an_empty_fixture_directory_is_rejected_like_a_missing_one(package: Path) -> None:
    """A directory that exists and holds nothing is the same claim, worse made."""
    for recorded in (package / "fixture").iterdir():
        recorded.unlink()
    assert any("fixture" in v for v in check_package(package).violations)


def test_a_fixture_the_connector_cannot_read_is_rejected(package: Path) -> None:
    """A recorded response the selectors select nothing from disproves itself.

    This is the failure a present-but-unchecked fixture hides: the file is
    there, review sees a fixture, and the connector has not matched a single
    item since the site was redesigned.
    """
    (package / "fixture" / "list.html").write_text(
        "<html><body><p>nothing a selector here reaches</p></body></html>",
        encoding="utf-8",
    )
    violations = check_package(package).violations
    assert any("selects nothing" in v for v in violations), violations


def test_a_fixture_carrying_candidate_provenance_is_rejected(package: Path) -> None:
    """A fixture must be a sampled listing, never an advert the candidate read.

    Adverts are public; the *set* of adverts a person reads is not, and a
    fixture in a public repository carries whatever made it forever. So the
    declaration is checked rather than trusted.
    """
    _edit_meta(package, lambda m: m["fixture"].__setitem__("provenance", "candidate_session"))
    violations = check_package(package).violations
    assert any("provenance" in v for v in violations), violations


def test_a_fixture_that_declares_no_provenance_at_all_is_rejected(package: Path) -> None:
    """Silence is not a declaration — the default must not be the safe reading."""
    _edit_meta(package, lambda m: m.pop("fixture"))
    assert any("fixture" in v for v in check_package(package).violations)


# ---------------------------------------------------------------------------
# rules 3 and 4 — no network, no filesystem, no subprocess, no environment


@pytest.mark.parametrize(
    ("source", "why"),
    [
        ("import socket\n", "a socket of its own"),
        ("import urllib.request\n", "an HTTP client of its own"),
        ("import requests\n", "a third-party HTTP client"),
        ("import subprocess\n", "another process"),
        ("import os\n", "the environment and the filesystem"),
        ("from os import environ\n", "the environment by another name"),
        ("import importlib\n", "anything at all, indirectly"),
        ("import ctypes\n", "the C library"),
        ("from . import helper\n", "code smuggled beside it"),
    ],
)
def test_a_connector_that_opens_its_own_socket_is_rejected(
    package: Path, source: str, why: str
) -> None:
    """Rule 3/4, over the routes a blocklist is most likely to miss.

    The check reads `parse.py` as an AST and never imports it — by the time an
    import has run, a module-level `socket.connect` has already happened, so
    "run it and see" is not available to a check that exists to prevent it.
    """
    (package / "parse.py").write_text(source, encoding="utf-8")
    violations = check_package(package).violations
    assert any("rule 3/4" in v for v in violations), (why, violations)


@pytest.mark.parametrize("call", ["open('/etc/passwd')", "eval('1')", "__import__('os')"])
def test_a_parse_module_that_reaches_out_by_builtin_is_rejected(package: Path, call: str) -> None:
    """Imports are not the only way out; the builtins that are get named too."""
    (package / "parse.py").write_text(f"def parse(text):\n    return {call}\n", encoding="utf-8")
    assert any("rule 3/4" in v for v in check_package(package).violations)


def test_a_parse_module_within_the_allowlist_is_accepted(package: Path) -> None:
    """The rule is not "no parse.py" — the exception has to remain usable."""
    (package / "parse.py").write_text(
        "import re\n\n\ndef parse(text: str) -> str:\n    return re.sub(r'\\s+', ' ', text)\n",
        encoding="utf-8",
    )
    assert check_package(package).violations == ()


def test_a_parse_module_that_does_not_parse_is_rejected_not_skipped(package: Path) -> None:
    """A file the checker cannot read is not a file the checker may ignore."""
    (package / "parse.py").write_text("def parse(:\n", encoding="utf-8")
    assert any("rule 3/4" in v for v in check_package(package).violations)


# ---------------------------------------------------------------------------
# rule 5 — meta.yaml complete, including last_verified


@pytest.mark.parametrize("key", ["site", "country", "language", "maintainer", "last_verified"])
def test_an_incomplete_meta_is_rejected(package: Path, key: str) -> None:
    """Each required field, dropped one at a time.

    Parametrised rather than dropping them all at once: a check that only
    notices when everything is missing passes the realistic case, which is one
    forgotten field.
    """
    _edit_meta(package, lambda m: m.pop(key))
    violations = check_package(package).violations
    assert any(key in v for v in violations), violations


def test_a_last_verified_nobody_can_parse_is_the_same_as_none(package: Path) -> None:
    """`last_verified` is the field that decays, so an unreadable one is a lie."""
    _edit_meta(package, lambda m: m.__setitem__("last_verified", "sometime last spring"))
    violations = check_package(package).violations
    assert any("last_verified" in v for v in violations), violations


def test_a_missing_meta_file_is_rejected(package: Path) -> None:
    (package / "meta.yaml").unlink()
    assert any("meta.yaml" in v for v in check_package(package).violations)


# ---------------------------------------------------------------------------
# rule 6 — public listings, robots.txt, no authentication


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("listings", "members_only"),
        ("robots_txt", "ignored"),
        ("authentication", "required"),
    ],
)
def test_a_package_whose_policy_is_not_the_shareable_one_is_rejected(
    package: Path, key: str, value: str
) -> None:
    """The policy is the part a reviewer cannot check by reading selectors."""
    _edit_meta(package, lambda m: m["policy"].__setitem__(key, value))
    violations = check_package(package).violations
    assert any(f"policy.{key}" in v for v in violations), violations


def test_a_package_with_no_policy_block_is_rejected(package: Path) -> None:
    """Undeclared is not the same as compliant."""
    _edit_meta(package, lambda m: m.pop("policy"))
    assert any("rule 6" in v for v in check_package(package).violations)


# ---------------------------------------------------------------------------
# rule 1 — one connector, one directory, exactly those files


def test_a_stray_file_in_the_package_is_rejected(package: Path) -> None:
    """"Everything in the directory is the connector" is what makes review finite.

    A `notes.txt` today is a `credentials.env` tomorrow, and the reviewer who
    waved the first one through has no principle left to refuse the second.
    """
    (package / "credentials.env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    violations = check_package(package).violations
    assert any("credentials.env" in v for v in violations), violations


def test_a_package_without_a_connector_file_is_rejected(package: Path) -> None:
    (package / "connector.yaml").unlink()
    assert any("connector.yaml" in v for v in check_package(package).violations)


# ---------------------------------------------------------------------------
# the command


def test_the_check_runs_offline(package: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The conformance command makes no network call.

    Enforced by removing the ability rather than by observing that none
    happened: `socket.socket` is replaced with something that raises, so any
    attempt — direct, or inside a library the check imports — fails the test
    instead of silently succeeding on a machine that happens to be online.
    """
    import socket

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the conformance check opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert check_package(package).violations == ()


def test_the_gate_records_the_measurement_it_made(tmp_path: Path) -> None:
    evidence = tmp_path / "T53.json"
    measured = write_evidence(evidence, _LIBRARY)
    assert evidence.is_file()
    assert measured["connector_contract_violations"] == 0
    assert measured["packages_checked"] >= MINIMUM_PACKAGES


def test_the_command_refuses_a_clean_result_over_no_packages(tmp_path: Path) -> None:
    """Exit 3, not 0. An empty library measured nothing; it did not pass.

    This is the one outcome a conformance command must never confuse, because
    an empty directory and a conforming directory produce the same
    `connector_contract_violations: 0` and only the exit code separates them.
    """
    empty = tmp_path / "connectors"
    empty.mkdir()
    evidence = tmp_path / "T53.json"

    assert _main(["x", str(evidence), "--connectors", str(empty)]) == 3
    assert json.loads(evidence.read_text(encoding="utf-8"))["packages_checked"] == 0


def test_the_command_exits_non_zero_when_a_package_violates(tmp_path: Path) -> None:
    """A violation must reach the shell, or CI reports a pass over a failure."""
    library = tmp_path / "connectors"
    shutil.copytree(_REFERENCE, library / _REFERENCE.name)
    evidence = tmp_path / "T53.json"
    assert _main(["x", str(evidence), "--connectors", str(library)]) == 0, "the copy conforms"

    (library / _REFERENCE.name / "parse.py").write_text("import socket\n", encoding="utf-8")
    assert _main(["x", str(evidence), "--connectors", str(library)]) == 1
    assert json.loads(evidence.read_text(encoding="utf-8"))["connector_contract_violations"] > 0


def test_the_command_reports_a_missing_directory_rather_than_passing(tmp_path: Path) -> None:
    """A path that is not there is not an empty library — it is a broken call."""
    evidence = tmp_path / "T53.json"
    assert _main(["x", str(evidence), "--connectors", str(tmp_path / "absent")]) == 3


# ---------------------------------------------------------------------------
# the boundary the AST check does *not* provide


def test_nothing_in_the_codebase_executes_a_contributed_parse_module() -> None:
    """The property that actually holds the line: `parse.py` is never run.

    Rules 3 and 4 are admission lint. A static allowlist cannot bound what
    Python *would* do if it ran — an attribute chain off a literal reaches
    `object.__subclasses__`, and a name can be assembled from strings — so
    reading them as "contributed code is safe to execute" is wrong in the
    direction that matters.

    What makes that irrelevant today is that nothing executes it. This asserts
    it rather than leaving it a fact somebody could undo in a later commit
    without noticing what it cost.

    Matched on the AST, not on the text: grepping for "importlib" flags
    `bootstrap.py`, which reads installed *distributions* via
    `importlib.metadata` and loads no code, and flags this file's own prose.
    A check that cries wolf on two honest uses is a check somebody deletes.

    Raised by review on PR #77.
    """
    # Attribute calls: `importlib.import_module(...)`, `loader.exec_module(...)`.
    loaders = {"import_module", "spec_from_file_location", "exec_module", "SourceFileLoader"}
    # Bare calls only. `compile` as an *attribute* is `re.compile`, which every
    # other module here uses for regexes; matching the name rather than the
    # binding flagged 59 honest regex compiles and nothing else.
    builtins_that_run_text = {"exec", "eval", "compile", "__import__"}
    offenders: list[str] = []
    for module in sorted((_REPO_ROOT / "src" / "jobsearch").glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in loaders:
                offenders.append(f"{module.name}:{node.lineno} calls .{func.attr}()")
            elif isinstance(func, ast.Name) and func.id in (loaders | builtins_that_run_text):
                offenders.append(f"{module.name}:{node.lineno} calls {func.id}()")
    assert offenders == [], (
        "code-loading machinery appeared in the package — if a runner now executes a "
        f"contributed parse.py, the contract check is not what makes that safe: {offenders}"
    )
