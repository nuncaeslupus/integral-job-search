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
import re
import shutil
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
import yaml

from integral.connector_contract import (
    _FLAT_JSON_OBJECT,
    _LEADING_RUN,
    _PAIR,
    _RUN_WINDOW,
    _SCALAR_KEY_SITE,
    _TRAILING_RUN,
    ADDRESS_BEARING_KEYS,
    DEFAULT_EVIDENCE_PATH,
    MINIMUM_PACKAGES,
    OPTIONAL_ENTRIES,
    PARSE_FILENAME,
    REQUESTER_OBJECT_KEYS,
    REQUIRED_ENTRIES,
    _is_address_bearing,
    _key_spelling,
    _main,
    check_capture_redaction,
    check_library,
    check_package,
    evidence_target,
    measure,
    requester_location_blocks,
    scrub_requester_location,
    unaudited_requester_sites,
    write_evidence,
)
from integral.connector_shape import measure as shape_measure
from integral.connectors import DEFAULT_CONNECTORS_DIR, PROBE_DIRNAME
from integral.pagination_capture import measure as pagination_measure
from integral.repo_gate import PROBE_BASENAME

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


def test_every_pagination_key_a_package_sends_appears_in_a_capture() -> None:
    """T113's gate, beside T53's, because it is the same kind of claim: a rule
    every shipped package must satisfy, asserted over the whole library.

    A page key named after something read out of a **response** — usajobs's
    `Pager.CurrentPageIndex` — says the board reports a page index, not that it
    accepts one in a request under that spelling. Only a recorded request
    certifies a request key, and if the board ignores an unknown one then page 2
    duplicates page 1 and the fetcher collects duplicate offers with nothing to
    report it.

    `paginated_request_keys_checked` is asserted beside the zero because a
    library where nothing paginates reports the same zero as a library whose
    every page key is measured, and those are two different facts. The rule
    itself, mode by mode, is `tests/test_pagination_capture.py`.
    """
    measured = pagination_measure(_LIBRARY)

    assert measured["findings"] == []
    assert measured["paginated_request_keys_no_capture_measured"] == 0
    assert measured["gate_status"] == "measured"
    assert measured["paginated_request_keys_checked"] >= 5


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


def test_a_parse_module_is_refused_however_well_behaved_it_is(package: Path) -> None:
    """D-10 (#78) — the rule *is* now "no parse.py", and this is where it changed.

    This test previously asserted the opposite, under the docstring "the rule is
    not 'no parse.py' — the exception has to remain usable". It was not usable:
    §5 advertised the hatch and nothing in `src/integral` ever executed one, so
    a connector for a site the declarative form cannot express passed every rule
    here and still could not work.

    The module below is the strongest case for the old behaviour — inside the
    allowlist, no import that reaches out, exactly the shape §5 described. It is
    refused anyway, and by rule 1 rather than rules 3/4: the objection is not
    that this file might misbehave, it is that no file of this kind runs at all.
    """
    (package / "parse.py").write_text(
        "import re\n\n\ndef parse(text: str) -> str:\n    return re.sub(r'\\s+', ' ', text)\n",
        encoding="utf-8",
    )
    violations = check_package(package).violations
    assert any(v.startswith("rule 1: parse.py is no longer part") for v in violations), violations
    assert not any("rule 3/4" in v for v in violations), "refused by shape, not by lint"


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
    """ "Everything in the directory is the connector" is what makes review finite.

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


def test_the_contributors_command_leaves_our_committed_evidence_alone(tmp_path: Path) -> None:
    """D-11 — `--connectors <theirs>` measures theirs and records nothing of ours.

    `docs/distribution.md` §5 hands this exact invocation to a contributor to
    run over their own directory, on their own machine. Recording was
    unconditional, so it wrote *our* `status/evidence/T53.json` with a
    `packages_checked` about theirs. `make evidence` then reported drift, and
    committing the number would have broken T53's gate — a merged task — for a
    reason nothing in the diff explained.

    An empty directory is the sharpest form: it measures 0 packages where the
    committed file says 1, so a regression cannot hide behind a copy of our own
    library happening to measure the same number. Both of the command's other
    exits are covered too, since each returns by a different route.
    """
    before = DEFAULT_EVIDENCE_PATH.read_bytes()

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _main(["x", "--connectors", str(empty)]) == 3, "nothing checked is not a pass"
    assert DEFAULT_EVIDENCE_PATH.read_bytes() == before

    theirs = tmp_path / "theirs"
    shutil.copytree(_REFERENCE, theirs / _REFERENCE.name)
    assert _main(["x", "--connectors", str(theirs)]) == 0, "an unbroken copy conforms"
    assert DEFAULT_EVIDENCE_PATH.read_bytes() == before

    (theirs / _REFERENCE.name / "meta.yaml").unlink()
    assert _main(["x", "--connectors", str(theirs)]) == 1, "a broken copy violates"
    assert DEFAULT_EVIDENCE_PATH.read_bytes() == before


def test_the_foreign_write_metric_is_measured_over_the_real_decision(tmp_path: Path) -> None:
    """D-11's gate asks `evidence_target` itself, not a copy of the rule.

    A gate that restates the rule agrees with prose the code has stopped
    following — the shape of every hole review found on #77. So the number comes
    from the same function `_main` calls, and this pins both of its answers.
    """
    assert measure()["evidence_writes_for_a_foreign_library"] == 0

    # The contributor's shape: a foreign library, no destination named.
    assert evidence_target((), own_library=False) is None
    # Our own library, no destination: `make evidence`'s invocation, which must
    # still record or the evidence file freezes at whatever it last said.
    assert evidence_target((), own_library=True) == DEFAULT_EVIDENCE_PATH
    # A named destination is a deliberate instruction, foreign library or not.
    named = tmp_path / "elsewhere.json"
    assert evidence_target((str(named),), own_library=False) == named
    assert evidence_target((str(named),), own_library=True) == named


def test_the_gate_still_records_when_the_caller_names_a_destination(tmp_path: Path) -> None:
    """The other half of D-11: suppressing the accident must not suppress the gate.

    `make evidence` runs the bare form over this repository's own library, and
    that must still write — a fix that quietly stopped recording would leave the
    evidence file frozen at whatever it last said.
    """
    evidence = tmp_path / "T53.json"
    assert _main(["x", str(evidence)]) == 0
    measured = json.loads(evidence.read_text(encoding="utf-8"))
    assert measured["packages_checked"] >= MINIMUM_PACKAGES
    assert measured["connector_contract_violations"] == 0


# ---------------------------------------------------------------------------
# the boundary the AST check does *not* provide


def test_every_file_named_in_the_shared_shape_has_a_runtime_or_is_not_advertised() -> None:
    """D-10 (#78) — the shape §5 documents and the shape the code runs agree.

    The defect this closes: §5 advertised `parse.py` as the escape hatch for
    sites the declarative form cannot express, and nothing executed it. A
    connector for such a site could be written, could pass all six rules, and
    could not work — the conformance check said yes to something the runtime had
    no way to honour.

    Both directions are asserted, because the disagreement can point either way:
    a file advertised with no runtime (the original defect), and a file
    advertised that rule 1 refuses (the same defect after a careless fix to only
    one of the two places).

    The measurement lives in `integral.connector_shape` so `make evidence`
    re-derives it on every run; this asserts it from the suite as well, since a
    gate only CI re-checks is one a local run can break without noticing.
    """
    measured = shape_measure()
    assert measured["advertised_connector_mechanisms_without_a_runtime"] == 0, (
        f"§5 advertises {measured['mechanisms_without_a_runtime']}, which nothing executes"
    )
    assert measured["advertised_but_not_admitted_by_rule_1"] == [], (
        f"§5 advertises {measured['advertised_but_not_admitted_by_rule_1']}, which rule 1 refuses"
    )
    assert PARSE_FILENAME not in measured["advertised_entries"], (
        "parse.py is back in §5 — it needs a runtime under process isolation before it can be"
    )
    assert PARSE_FILENAME not in (REQUIRED_ENTRIES | OPTIONAL_ENTRIES)


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
    for module in sorted((_REPO_ROOT / "src" / "integral").glob("*.py")):
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


# ---------------------------------------------------------------------------
# review on #77 — each finding, as the test that would have caught it


def test_a_dotfile_in_the_package_is_rejected_like_any_other_stray(package: Path) -> None:
    """`.env` is the case rule 1 exists for, and it was the one getting through.

    The layout check filtered dotfiles before comparing against the allowlist,
    so "exactly these files" quietly meant "exactly these files, plus anything
    hidden" — and the conventional name for a committed credential file starts
    with a dot.
    """
    (package / ".env").write_text("TOKEN=hunter2\n", encoding="utf-8")
    violations = check_package(package).violations
    assert any(".env" in v for v in violations), violations


@pytest.mark.parametrize(
    "source",
    [
        "reader = open\n\n\ndef parse(t):\n    return reader('/etc/passwd')\n",
        "loader = __import__\n\n\ndef parse(t):\n    return loader('os')\n",
        "def parse(t):\n    return [eval][0]('1')\n",
    ],
)
def test_a_forbidden_builtin_reached_through_an_alias_is_rejected(
    package: Path, source: str
) -> None:
    """Naming the builtin is the violation, not calling it directly.

    Matching only the call target let `reader = open` then `reader(path, 'w')`
    through, which certified a file the contract says cannot touch the
    filesystem.
    """
    (package / "parse.py").write_text(source, encoding="utf-8")
    violations = check_package(package).violations
    assert any("rule 3/4" in v for v in violations), violations


def test_a_declared_detail_page_without_a_recorded_response_is_rejected(package: Path) -> None:
    """A declared selector with no fixture is unproven, not exempt.

    The check parsed the detail page only when the file happened to exist, so a
    connector whose listing alone yields a valid offer passed with its detail
    selectors never once run.
    """
    (package / "fixture" / "detail.html").unlink()
    violations = check_package(package).violations
    assert any("detail.html" in v for v in violations), violations


def test_a_verification_date_that_disagrees_with_the_connector_is_rejected(package: Path) -> None:
    """One fact, two files: the borrower-facing copy cannot be the flattering one.

    `assess_staleness` judges on `connector.yaml`, so a `meta.yaml` advertising
    a fresher date would have told a borrower the connector was maintained more
    recently than the runtime believed.
    """
    _edit_meta(package, lambda m: m.__setitem__("last_verified", "2026-08-19"))
    violations = check_package(package).violations
    assert any("last_verified" in v for v in violations), violations


def test_a_parse_module_that_is_not_valid_utf8_is_a_violation_not_a_crash(package: Path) -> None:
    """Contributor bytes must not be able to stop the gate writing its evidence."""
    (package / "parse.py").write_bytes(b"\xff\xfe\x00invalid")
    violations = check_package(package).violations
    assert any("rule 3/4" in v for v in violations), violations


def test_meta_that_is_not_valid_utf8_leaves_the_command_with_a_documented_status(
    tmp_path: Path,
) -> None:
    """A documented status and a message, never a traceback.

    **1**, not 3: bytes nobody can decode are a fault in *that package*, so it
    is reported beside any other violation and the rest of the library is still
    checked. Exit 3 is reserved for the library itself being unreachable, where
    there is nothing to report about.
    """
    library = tmp_path / "connectors"
    shutil.copytree(_REFERENCE, library / _REFERENCE.name)
    (library / _REFERENCE.name / "meta.yaml").write_bytes(b"\xff\xfe\x00invalid")
    evidence = tmp_path / "T53.json"

    assert _main(["x", str(evidence), "--connectors", str(library)]) == 1
    measured = json.loads(evidence.read_text(encoding="utf-8"))
    assert measured["connector_contract_violations"] == 1
    assert "could not be read" in measured["violations"][0]


#: The only globally routable dotted quads the repository may carry, each with
#: why it is not an address. Checked in both directions: a pair that no longer
#: occurs fails too, so this cannot outlive what it excuses. Written as octets
#: so this file does not itself carry the literal it excuses.
_NOT_ADDRESSES = {
    ("src/integral/robots.py", ".".join(map(str, (124, 0, 0, 0)))): (
        "Chrome's version in a browser User-Agent"
    ),
}


def _quads_in_every_file() -> dict[tuple[str, str], None]:
    """Every globally routable IP literal in every file the repository ships
    or is about to — tracked, plus untracked and not ignored, so a capture that
    is written but not yet staged is read as well.

    Read as bytes decoded latin-1, which cannot fail. A UTF-8-only read skipped
    an ISO-8859-1 page whole, and those are the encodings the non-English
    boards on the wanted list still serve. Three spellings are read: a dotted
    quad (octets normalised, so `037.018.…` is the address it names), the
    dashed form a reverse-DNS hostname carries, and IPv6. On the tree this
    landed on, the dashed and IPv6 readings found nothing that is not an
    address, so reading them costs no exceptions."""
    repo = _LIBRARY.parent
    return _quads_in(repo, _listed_files(repo))


def _listed_files(repo: Path) -> list[str]:
    """What git says the repository ships right now: tracked, plus untracked and
    not ignored — git's answer verbatim, never reconciled with the filesystem.

    This filtered to `is_file()` for one round, and that filter was a second
    place a listed name could be dropped with nothing saying so. It is not even
    a race: `rm` a tracked file and do not stage the deletion, and the index
    still ships it while `is_file()` is deterministically false — so the name
    reached neither the scan nor the rule that refuses a dropped file, and an
    indexed file carrying a live literal passed green. Whether a listed name may
    go unread is now decided in exactly one place, the `except` in `_quads_in`,
    and a directory or a broken link raising there is the same fail-closed
    answer this gate already chose one line further on."""
    import subprocess

    listed = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    return [name for name in listed.split("\0") if name]


def _quads_in(repo: Path, names: list[str]) -> dict[tuple[str, str], None]:
    """The scanning half, split out so the two rules it ends with can be pinned
    against a `names` list a test chooses rather than against the live tree.

    That split is what makes the race testable honestly: a name that is not on
    disk *is* a file git listed a moment before it went away, so the case needs
    no patched builtin and no writing into the working tree."""
    import ipaddress

    v4 = re.compile(r"(?<![\w.])(\d{1,3})([.-])(\d{1,3})\2(\d{1,3})\2(\d{1,3})(?![\w-])")
    v6 = re.compile(r"(?<![\w:])[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7}(?![\w:])")
    found: dict[tuple[str, str], None] = {}
    skipped: list[str] = []
    for name in names:
        try:
            text = (repo / name).read_bytes().decode("latin-1")
        except FileNotFoundError:
            # Listed, gone by the time it is read. Which files may do that is
            # decided below, not here — a permission error is not this race and
            # still raises.
            skipped.append(name)
            continue
        for match in v4.finditer(text):
            if text[max(0, match.start() - 2) : match.start()].rstrip().endswith("§"):
                continue  # `§2.3.1.3`: an RFC section number, however many are cited
            octets = [int(match.group(i)) for i in (1, 3, 4, 5)]
            if max(octets) > 255:
                continue  # SVG coordinates, not an address
            if ipaddress.IPv4Address(".".join(map(str, octets))).is_global:
                found[(name, ".".join(map(str, octets)))] = None
        for match in v6.finditer(text):
            try:
                address = ipaddress.IPv6Address(match.group())
            except ValueError:
                continue
            if address.is_global:
                found[(name, str(address))] = None
    # Two rules, and neither implies the other.
    #
    # The floor is whether the scan ran at all, and its denominator is what was
    # READ. Listing and reading were the same number until the `continue` above
    # existed; now a defect that made every read raise would leave git's listing
    # at its usual 1126 and the scan at zero.
    scanned = len(names) - len(skipped)
    assert scanned > 1000, (
        f"git listed {len(names)} files and {scanned} were read — the scan did not run"
    )
    # The second is whether that `continue` stayed narrow, and it is a rule
    # rather than a count because a count cannot say it. `repo_gate`'s
    # evidence-stability measurement writes probe files into the live tree and
    # unlinks them again, and under `make test`'s parallelism that happens on
    # another worker while this scan is running — nothing the repository ships.
    # Any OTHER file that is listed and then gone is a git operation racing the
    # scan, or a defect, and a gate whose whole job is to refuse committed IP
    # literals must not drop a file and report a clean pass.
    unexpected = sorted(n for n in skipped if Path(n).name != PROBE_BASENAME)
    assert not unexpected, f"listed, then unreadable, and not evidence probes: {unexpected}"
    return found


def test_no_committed_file_carries_an_ip_address() -> None:
    """A recorded page can contain the recording machine's own address.

    `trabajos.com` writes one into every response as
    `<!-- IP: 203.0.113.7 - CODPAIS:100 -->` (an RFC 5737 documentation address
    here), which is the *client's* address, not the server's. So a page saved
    verbatim publishes the home IP of whoever recorded it, both to this
    repository and to the sources repository `tools/publish_connectors.py`
    copies the whole package into. Nothing about the connector needs it, and no
    later deletion reaches a clone, so the check is here rather than in a
    reviewer's habits.

    **Every file, not every directory.** This scanned `fixture/*.html` alone
    until `probe/` was committed, and the first probe ever captured carried a
    live client IP. Widening it to `connectors/**/*.html` then missed T166's
    no-hit page under `tests/fixtures/`, the same board's page one directory
    over again. And the second reader on #447 showed that naming
    `tests/fixtures/` as well still missed a page under any third directory,
    or a `.json` capture. Each widening named one more place, which is an
    enumeration with no last element. So the population is now what git
    lists, whatever the path or extension. Only a globally routable address
    counts, so documentation, private and loopback ranges pass, and so does a
    quad with an octet above 255, and so does one written after `§`, which is an
    RFC section number: T144 cited five of them the day this landed. The one
    remaining literal that is not an address is named in `_NOT_ADDRESSES` with
    the reason.
    """
    found = _quads_in_every_file()
    offenders = sorted(key for key in found if key not in _NOT_ADDRESSES)
    stale = sorted(key for key in _NOT_ADDRESSES if key not in found)
    assert not offenders, f"files carry IP addresses: {offenders}"
    assert not stale, f"_NOT_ADDRESSES excuses literals that no longer occur: {stale}"


def test_the_listing_is_gits_answer_and_not_the_filesystems(tmp_path: Path) -> None:
    """The population is what git ships, and git ships what is in its index. A
    tracked file deleted without staging the deletion is still shipped, still
    carries whatever it carries, and is not on disk — so a listing reconciled
    with the filesystem drops it before the scan can read it and before the rule
    below can refuse it. That was the fail-open the second reader measured on
    `d85b242`: one `git add`, one plain `rm`, and the gate went from red to green
    over an indexed file carrying a live address.

    Built rather than described, because the only state that tells the two
    readings apart is an index and a worktree that disagree, and this repository
    is not the place to make one."""
    import subprocess

    def git(*argv: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *argv], capture_output=True, check=True)

    git("init")
    (tmp_path / "staged-then-deleted.md").write_text("x\n", encoding="utf-8")
    git("add", "staged-then-deleted.md")
    (tmp_path / "staged-then-deleted.md").unlink()

    assert _listed_files(tmp_path) == ["staged-then-deleted.md"]


def test_the_scan_survives_a_probe_file_that_vanishes_between_listing_and_reading() -> None:
    """`repo_gate`'s evidence-stability measurement writes probe files into the
    live working tree and unlinks them again. `make test` puts that file and
    this one on different xdist workers, so a probe can be listed here and be
    gone before it is read — a state the serial suite could not reach.

    Pinned rather than trusted: the remedy is one `except` clause, the run it
    protects goes red a few times in a hundred, and a green suite is therefore
    the expected outcome whether the clause is there or not. Being right is not
    being pinned.

    The vanished name is sited where no writer can reach, and the absence is
    asserted rather than assumed. `docs/<PROBE_BASENAME>` is one of the eight
    paths `repo_gate` really writes, so appending *that* gave a case that stopped
    being a case exactly when the writer was mid-run on another worker — the file
    resolves, nothing is skipped, and the only assertion left is one the live
    gate already makes. Measured by the second reader at ~2.7s of a ~20.7s
    `tests/test_repo_gate.py` run: a fixture whose execution path need not
    arrive."""
    repo = _LIBRARY.parent
    vanished = f"docs/never-written/{PROBE_BASENAME}"
    assert not (repo / vanished).exists(), "the case needs a name no writer can reach"
    names = [*_listed_files(repo), vanished]

    found = _quads_in(repo, names)

    sentinel = next(iter(_NOT_ADDRESSES))
    assert sentinel in found, "the scan stopped at the vanished probe instead of continuing"


def test_a_file_that_vanishes_and_is_not_a_probe_is_not_silently_skipped(
    tmp_path: Path,
) -> None:
    """The `except` above is for one known writer of one known filename. A file
    that is listed and then gone for any other reason is a git operation racing
    the scan, or a defect — and a gate whose whole job is to refuse committed IP
    literals cannot drop a file and still report a clean pass. Widening the
    clause to every vanished path is the reflex the first time this goes red in
    CI, and it is the fail-open direction.

    One case could not say that, and a second case would not either. The reader
    widened the predicate by a single clause — `and not n.startswith("corpus/")`,
    exempting the directory where whole job adverts live, the files likeliest to
    carry an address — and the whole file stayed green, because the only case it
    had named a path in `docs/`. A third case moves the surviving mutation to a
    fourth directory. So the axis is derived from the tree rather than named: one
    vanished name per top-level entry git lists, all in one scan, and every one
    of them has to appear in the refusal. A directory added later is covered
    without anyone remembering to.

    Deriving the axis was only half of it, and the other half was a proxy for
    two rounds running. First `name in str(refusal.value)` read the rendered
    list as a haystack, so a point that is a suffix of another was never
    observable — `arsenal/…` sits inside `claude-arsenal/…`, and the `.` top's
    bare `vanished-mid-scan.md` inside all fifteen others. Recovering that list
    and comparing sets fixed the comparison and left the observable alone, and
    the observable was the trouble: a message is not a decision. `unexpected` is
    rendered by the f-string and tested by the assert's condition, two
    independent expressions over one variable. Widen the condition alone and the
    message still names all sixteen points — so a check reading the message
    stays green — while the scan returns a hit and refuses nothing. Measured,
    not argued. So each point is now its own scan and the observation is whether
    `_quads_in` raised at all, which is the decision itself and has no rendering
    to read.

    The population is synthetic for cost: sixteen scans of the real tree are
    19.8s, and 1001 empty files in a `tmp_path` are 0.3s — cheaper than the one
    real scan this test used to do, while still clearing the floor inside
    `_quads_in`."""
    repo = _LIBRARY.parent
    tops = {name.partition("/")[0] if "/" in name else "." for name in _listed_files(repo)}
    vanished = sorted(str(Path(top) / "vanished-mid-scan.md") for top in tops)
    # Its own denominator: an axis derived from an empty listing is no axis, and
    # the emptiness would otherwise read as every point passing.
    assert len(vanished) > 5, f"the axis collapsed to {vanished}"

    population = [f"f{index}.md" for index in range(1001)]
    for name in population:
        (tmp_path / name).write_bytes(b"")

    # The control, and it is load-bearing rather than a courtesy: every refusal
    # below is observed as "an AssertionError came out", and the floor assert is
    # an AssertionError too. If the population failed to clear it, all sixteen
    # points would "refuse" for the wrong reason and the loop would be vacuous.
    _quads_in(tmp_path, population)

    unrefused = []
    for name in vanished:
        try:
            _quads_in(tmp_path, [*population, name])
        except AssertionError:
            continue
        unrefused.append(name)
    assert not unrefused, f"vanished, and the scan returned instead of refusing: {unrefused}"


def test_the_floor_counts_the_files_read_and_not_the_files_listed() -> None:
    """The floor's denominator is the whole of its value, and counting git's
    listing was green over a scan that read nothing at all. The two came apart
    the moment a read could be skipped: a tree whose every listed file has gone
    satisfies the narrowness rule above completely — they are all probes — so
    the listing floor passes too, and the IP gate certifies a clean pass having
    opened zero files."""
    repo = _LIBRARY.parent
    names = [f"docs/d{i}/{PROBE_BASENAME}" for i in range(1200)]

    with pytest.raises(AssertionError, match="the scan did not run"):
        _quads_in(repo, names)


def test_the_scan_still_raises_on_a_file_it_may_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard above catches `FileNotFoundError` and not `OSError`, and a
    narrowness that lives in a comment is a narrowness nobody checks. Widening
    it is the reflex the first time this raises in CI — and a scan whose whole
    job is to refuse committed IP literals, skipping the files it could not
    read, is fail-open in a gate."""

    def refuse(self: Path) -> bytes:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "read_bytes", refuse)

    with pytest.raises(PermissionError):
        _quads_in(_LIBRARY.parent, ["README.md"])


def test_a_probe_that_is_a_regular_file_is_rejected(package: Path) -> None:
    """Review on #256: `probe` joined OPTIONAL_ENTRIES and inherited the
    exemption from "unexpected entry" without inheriting `fixture`'s type check,
    so a regular file named `probe` passed rule 1 — while `connector_health`
    expects a directory to read `list.html` out of."""
    shutil.rmtree(package / PROBE_DIRNAME, ignore_errors=True)
    (package / PROBE_DIRNAME).write_text("not a directory", encoding="utf-8")

    violations = check_package(package).violations

    assert any(PROBE_DIRNAME in v and "directory" in v for v in violations), violations


def test_a_package_with_no_probe_at_all_is_still_valid(package: Path) -> None:
    """Optional means optional: a connector nobody has captured a probe for is
    reviewable, and `connector_health` reports `unmeasured` rather than broken."""
    shutil.rmtree(package / PROBE_DIRNAME, ignore_errors=True)

    assert not check_package(package).violations


# ---------------------------------------------------------------------------
# rule 7 — a capture carries the board's response, never who asked for it

# The shape talent.com serves, trimmed to what the rule reads: a flat object of
# scalars carrying an address, the pairs repeated immediately before it, and an
# advert's own location elsewhere in the same file spelling the same words.
# Escaped, because that is how a Next.js flight payload stores it and a plain
# `"lat":` pattern silently matches nothing there.
_REQUESTER_PAYLOAD = (
    '<script>self.__next_f.push([1,"'
    '\\"prefilledLocation\\":\\"Barcelona, ES\\",\\"userData\\":null,'
    '\\"location\\":{\\"prefilledLocation\\":\\"Barcelona, ES\\",'
    '\\"lat\\":41.4085,\\"lon\\":2.1904,\\"timeZone\\":\\"Europe/Madrid\\",'
    '\\"city\\":\\"Barcelona\\",\\"zip_code\\":\\"08001\\",'
    '\\"state\\":\\"Catalonia\\",\\"ipLocation\\":\\"203.0.113.9\\"},'
    '\\"ip\\":\\"203.0.113.9\\""])</script>'
)
_ADVERT_PAYLOAD = (
    '<script>self.__next_f.push([1,"'
    '\\"source_location\\":\\"Barcelona, Catalonia, ES\\",'
    '\\"enrich_geo_city\\":\\"Barcelona\\",\\"enrich_geo_region1\\":\\"Catalonia\\",'
    '\\"enrich_geo_lat\\":41.3873974"])</script>'
)


def _with_payload(package: Path, payload: str) -> Path:
    """Append a payload to the package's listing capture and return its path."""
    listing = package / "fixture" / "list.html"
    listing.write_text(listing.read_text(encoding="utf-8") + payload, encoding="utf-8")
    return listing


def test_a_capture_carrying_the_requesters_own_address_is_rejected(package: Path) -> None:
    """The board writes who fetched into the page; the package must not ship it."""
    _with_payload(package, _REQUESTER_PAYLOAD)

    violations = check_package(package).violations
    assert any("rule 7" in v and "ipLocation" in v for v in violations), violations


def test_every_field_the_board_puts_beside_the_address_is_reached(package: Path) -> None:
    """Derived over the block's own keys, so a field added later is covered.

    This is the test the first redaction of `talent_es` would have failed. That
    one scanned for "an IPv4 and an IPv6 literal", found both, replaced both and
    said so in `meta.yaml` — and left `lat` and `lon` two keys away, because a
    scan for the fields somebody remembered cannot reach the one they did not.
    Listing the fields here would repeat the mistake in the gate, so the cases
    are read off the block instead: whatever the board puts in that object is
    what gets varied.
    """
    clean, _ = scrub_requester_location(_REQUESTER_PAYLOAD)
    (start, end), *_ = requester_location_blocks(clean)
    pairs = [
        (m.group(1), m.group(2))
        for m in _PAIR.finditer(clean, start, end)
        if m.group(2) not in {"true", "false", "null"}
    ]
    assert len(pairs) >= 8, pairs

    unreached = []
    for key, value in pairs:
        leaked = '\\"203.0.113.9\\"' if key in ADDRESS_BEARING_KEYS else "41.4085"
        pair = '\\"' + key + '\\":'
        dirtied = clean.replace(pair + value, pair + leaked, 1)
        assert dirtied != clean, key
        listing = _with_payload(package, dirtied)
        if not any(key in v for v in check_capture_redaction(package)):
            unreached.append(key)
        listing.write_text(
            listing.read_text(encoding="utf-8").replace(dirtied, ""), encoding="utf-8"
        )
    assert not unreached, unreached


@lru_cache(maxsize=1)
def _committed_blocks() -> tuple[str, ...]:
    """Every requester block the board actually ships, as raw slices.

    Read off a committed capture rather than built here. Sliced, because the
    capture is half a megabyte and the point is the board's *keys*, not a
    second scan of its adverts — and cached, because finding them costs seconds.
    """
    capture = (_LIBRARY / "talent_es" / "probe" / "list.html").read_text(encoding="utf-8")
    return tuple(capture[start:end] for start, end in requester_location_blocks(capture))


def _scalar_pairs(text: str) -> list[tuple[str, str]]:
    return [
        (m.group(1), m.group(2))
        for m in _PAIR.finditer(text)
        if m.group(2) not in {"true", "false", "null"}
    ]


def test_the_varied_population_is_the_boards_and_not_this_files() -> None:
    """The population a test varies has to be the one the board writes.

    `_REQUESTER_PAYLOAD` is this file's literal, and a test that derives its
    cases from it derives them from what somebody remembered to type — the
    exact shape the docstring above disclaims while doing it. The committed
    capture carries keys that literal does not, and every one of them is a
    field the board puts beside the requester's address.

    So the check is a containment: whatever the board ships is reached. If the
    board ships a key this file never imagined, that is the case that matters.
    """
    blocks = _committed_blocks()
    assert blocks, "the committed capture has no requester block to derive from"

    unreached = []
    for block in blocks:
        for key, value in _scalar_pairs(block):
            leaked = '\\"203.0.113.9\\"' if _is_address_bearing(key) else "41.4085"
            pair = '\\"' + key + '\\":'
            dirtied = block.replace(pair + value, pair + leaked, 1)
            if dirtied == block:
                continue
            cleaned, changed = scrub_requester_location(dirtied)
            if changed == 0 or leaked.strip('\\"') in cleaned:
                unreached.append(key)
    assert not unreached, unreached


def test_the_board_ships_keys_this_files_literal_does_not() -> None:
    """The denominator behind the test above — and why it is not decorative.

    If the committed capture's keys were a subset of `_REQUESTER_PAYLOAD`'s,
    the containment check would be satisfied by the literal and would be
    measuring nothing. It is not: the board writes fields nobody here typed.
    """
    board = {key for block in _committed_blocks() for key, _ in _scalar_pairs(block)}
    literal = {key for key, _ in _scalar_pairs(_REQUESTER_PAYLOAD)}
    assert board - literal, sorted(board)


def test_a_scalar_written_before_the_block_is_reached(package: Path) -> None:
    """Clause 3's left edge, pinned — it had no test at all.

    Removing the run from `_LEADING_RUN` (its `)*` to `){0}`) left all of this
    file green, because every other case varies pairs *inside* the object and
    the span still starts at the object's own key. The pairs the clause exists
    for are the ones written before it, so those are what this varies.
    """
    head = _REQUESTER_PAYLOAD.split('\\"location\\":', 1)[0]
    before = [key for key, _ in _scalar_pairs(head)]
    assert before, head

    for key in before:
        assert any(key in v for v in check_capture_redaction(package)) or key in _reached_keys(
            package, key
        ), key


def _reached_keys(package: Path, key: str) -> set[str]:
    """Whether the sweep reaches `key` when the board leaks it."""
    pair = '\\"' + key + '\\":'
    dirtied = _REQUESTER_PAYLOAD.replace(pair + '\\"Barcelona, ES\\"', pair + '\\"41.4085\\"', 1)
    listing = _with_payload(package, dirtied)
    try:
        return {key} if any(key in v for v in check_capture_redaction(package)) else set()
    finally:
        listing.write_text(
            listing.read_text(encoding="utf-8").replace(dirtied, ""), encoding="utf-8"
        )


def test_a_scalar_written_after_a_requester_object_is_reached() -> None:
    """Clause 3's right edge — the ordering axis, generated rather than listed.

    Which side of a nested member the board writes a scalar on is its choice,
    and it can change it in a redeploy. So the case is every rotation of the
    same members, not the one order that happens to be committed today: under
    each, nothing of the requester survives.
    """
    members = [
        '\\"userID\\":\\"u-8821f0ab\\"',
        '\\"locale\\":\\"es-ES\\"',
        '\\"customIDs\\":{\\"nuuid\\":\\"n-77\\",\\"stableID\\":\\"s-31\\"}',
    ]
    secrets = ("u-8821f0ab", "es-ES", "n-77", "s-31")
    for rotation in range(len(members)):
        ordered = members[rotation:] + members[:rotation]
        payload = "{" + ",".join(ordered) + "}"
        scrubbed, changed = scrub_requester_location(payload)
        assert changed, (rotation, payload)
        assert not [s for s in secrets if s in scrubbed], (rotation, scrubbed)


def test_a_key_spelled_another_way_is_the_same_key() -> None:
    """Separator and casing are not a vocabulary, so they are closed here.

    Derived from the committed set: every address-bearing key, re-spelled every
    way the same word can be written, still seeds. `client-ip` did not before —
    `_KEY` could not even match a hyphen — so the sweep returned nothing at all
    and the gate stayed green over a leaked address.
    """
    for key in sorted(ADDRESS_BEARING_KEYS):
        spelling = _key_spelling(key)
        variants = {key, spelling, spelling.upper(), spelling.capitalize()}
        if len(spelling) > 2:
            variants |= {spelling[:-2] + "-" + spelling[-2:], spelling[:-2] + "." + spelling[-2:]}
        for variant in sorted(variants):
            payload = '{"' + variant + '":"203.0.113.9","city":"Barcelona","lat":41.4085}'
            scrubbed, changed = scrub_requester_location(payload)
            assert changed, variant
            assert "203.0.113.9" not in scrubbed, variant
            assert "41.4085" not in scrubbed, variant


def test_an_escape_in_a_neighbouring_value_does_not_hide_the_block() -> None:
    """A string grammar that stops at a backslash cannot see an accented city.

    `_VALUE` matched `[^"\\]*`, so one `\\u00f1` anywhere in the requester's own
    object dropped the seed and the whole block survived. These captures carry
    roughly nine hundred such escapes apiece, so this is the requester living
    in A Coruña rather than an exotic input.
    """
    for city in (r"A Coru\u00f1a", r"A Coru\\u00f1a", "A Coruna"):
        payload = '{"ip":"203.0.113.9","city":"' + city + '","lat":43.3623,"zip":"15001"}'
        scrubbed, changed = scrub_requester_location(payload)
        assert changed, city
        assert not [s for s in ("203.0.113.9", "43.3623", "15001") if s in scrubbed], city


def test_every_committed_file_is_scanned_and_not_only_the_html(package: Path) -> None:
    """The extension was a proxy for "the capture", and it was the wrong one.

    `probe/captured.json` records the URL that was fetched, and this board
    answers 307 by appending the city it geolocated the requester to — so the
    one committed file that names a URL was the one file never scanned.
    """
    probe = package / PROBE_DIRNAME / "captured.json"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        json.dumps({"url": "https://example.test/jobs", "ip": "203.0.113.9"}),
        encoding="utf-8",
    )

    violations = check_capture_redaction(package)
    assert any("rule 7" in v and "captured.json" in v for v in violations), violations


def test_the_boards_own_rows_are_not_swept_with_the_requesters(package: Path) -> None:
    """The fail-open direction has a fail-closed twin, and it is just as wrong.

    An advert in the same city spells the same words — `Barcelona`, `Catalonia`,
    a latitude — and a sweep by key name or by value takes the board's data with
    the requester's. Measured on the real captures: `city` occurs seven times and
    exactly one of them is whose fetched it. The object boundary is the only
    thing in the text that tells them apart.
    """
    _with_payload(package, _ADVERT_PAYLOAD)

    assert not check_capture_redaction(package)
    assert not requester_location_blocks(_ADVERT_PAYLOAD)
    assert scrub_requester_location(_ADVERT_PAYLOAD) == (_ADVERT_PAYLOAD, 0)


def test_an_html_attribute_repeating_a_removed_value_goes_with_it() -> None:
    """The board renders what it geolocated into the search box, too.

    Whole attribute values only: the board's own rows read `Barcelona,
    Barcelona, ES`, so a substring sweep would cut an advert's location in half.
    """
    page = _REQUESTER_PAYLOAD + '<input name="keyword" value="Barcelona, ES"/>'
    page += '<span class="loc">Barcelona, Barcelona, ES</span>'
    scrubbed, _ = scrub_requester_location(page)

    assert 'value="redacted"' in scrubbed
    assert "Barcelona, Barcelona, ES" in scrubbed


def test_the_committed_captures_carry_nobody_who_fetched_them() -> None:
    """Over the real library — the check `meta.yaml`'s `client_ip` line now has.

    That line said the captures had been "re-scanned for an IPv4 and an IPv6
    literal". It was true, it was written by the session that did the scanning,
    and nothing read it: `connector_exchange.py` prints it in a table row.
    """
    offenders = {
        package.name: violations
        for package in sorted(p for p in _LIBRARY.iterdir() if p.is_dir())
        if (violations := check_capture_redaction(package))
    }
    assert not offenders, offenders


def test_the_run_window_clears_the_widest_block() -> None:
    """The window's margin, measured rather than asserted in a comment.

    `_RUN_WINDOW` bounds how far a run of scalar pairs is followed. A window
    that has quietly shrunk under what the committed captures actually need
    would leave a requester run partly unredacted, and nothing else here would
    say so — the blocks would still be found, just cut short. So the margin is
    re-derived from the captures on every run.
    """
    widest = max(
        end - start
        for path in sorted((_LIBRARY / "talent_es").rglob("*"))
        if path.is_file()
        for start, end in requester_location_blocks(
            path.read_text(encoding="utf-8", errors="replace")
        )
    )
    assert widest < _RUN_WINDOW, f"widest committed block is {widest}, window is {_RUN_WINDOW}"
    assert widest * 2 < _RUN_WINDOW, (
        f"the window has no margin left: widest block {widest} against a "
        f"{_RUN_WINDOW}-character window"
    )


# Every escape JSON defines, rather than the ones that were thought of: the
# axis is generated so an escape nobody listed is varied too.
_JSON_ESCAPES = (*'"\\/bfnrt', "u0041")


def _captures_carrying_an_escape() -> list[tuple[str, str]]:
    """One capture per (escape x spelling x position), as (label, raw bytes).

    The escape is placed at the end of a value, at the start, and in the
    middle, because the defect this pins is positional: an alternative that
    over-consumes only matters when what it eats is the terminator.
    """
    out = []
    for escape in _JSON_ESCAPES:
        for position in ("end", "start", "middle"):
            body = {"end": f"C:\\{escape}", "start": f"\\{escape}C:", "middle": f"C\\{escape}:"}[
                position
            ]
            for spelling in ("plain", "doubly-escaped"):
                q = '"' if spelling == "plain" else '\\"'
                b = body if spelling == "plain" else body.replace("\\", "\\\\")
                raw = (
                    f"{{{q}path{q}:{q}{b}{q},{q}ip{q}:{q}203.0.113.9{q},"
                    f"{q}zip_code{q}:{q}08001{q}}}"
                )
                out.append((f"{escape!r}/{position}/{spelling}", raw))
    return out


def test_rule_7_is_never_silent_about_a_capture_it_cannot_read() -> None:
    """A capture carrying an address key is redacted, or reported — never clean.

    The grammar cannot read every escape spelling and is not claimed to: the
    property is that a capture it *fails* on is a violation rather than a pass.
    Pinning the grammar's coverage instead would be an enumeration, and the
    next spelling nobody listed would fail open exactly as this one did.
    """
    silent = []
    for label, raw in _captures_carrying_an_escape():
        _, changed = scrub_requester_location(raw)
        if changed == 0 and not unaudited_requester_sites(raw):
            silent.append(label)
    assert not silent, (
        f"{len(silent)} captures carry the requester's address and rule 7 says "
        f"nothing about them — neither redacted nor reported: {silent}"
    )


def test_the_axis_reaches_the_grammar_hole_it_was_built_for() -> None:
    """Non-vacuity: the axis must contain captures the grammar really fails on.

    Without this the test above passes just as well over an axis the grammar
    handles perfectly, which would make it a check that cannot fail.
    """
    unread = [
        label for label, raw in _captures_carrying_an_escape() if unaudited_requester_sites(raw)
    ]
    assert unread, "the axis exercises no capture the pair grammar fails to read"


def test_a_capture_the_grammar_cannot_read_fails_the_rule(package: Path) -> None:
    """The wiring, not the helper — `check_capture_redaction` must say it.

    `unaudited_requester_sites` being right changes nothing on its own: the rule
    is what the gate runs, and a helper nobody calls is the green fixture over
    a live defect this repository keeps meeting. So this asserts the violation
    comes back out of the rule, over a capture written into a real package.
    """
    probe = package / PROBE_DIRNAME / "captured.json"
    probe.parent.mkdir(parents=True, exist_ok=True)
    # A value ending in an escaped backslash: the escape alternative consumes
    # the closing quote, and possessively, so the scan cannot back out of it.
    probe.write_text('{"path":"C:\\\\","ip":"203.0.113.9","zip_code":"08001"}', encoding="utf-8")

    violations = check_capture_redaction(package)
    assert any("rule 7" in v and "cannot read" in v for v in violations), violations


def _address_bearing_separator_spellings() -> list[str]:
    """`client<sep>ip` for every separator `_key_spelling` normalises away.

    The set is derived from that function rather than listed, so a character it
    starts or stops folding is varied here without anyone remembering to. `"`
    and `\\` are excluded because they end the key rather than sit inside it.
    """
    return [
        f"client{chr(code)}ip"
        for code in range(0x20, 0x7F)
        if chr(code) not in '"\\' and _key_spelling(f"client{chr(code)}ip") == "clientip"
    ]


def test_the_key_locator_covers_the_grammar_it_audits() -> None:
    """The locator's domain is `_PAIR`'s, not an identifier class.

    This is the round-4 defect stated as a check. That round located key sites
    with `[A-Za-z_][A-Za-z0-9_.-]*`, on the argument that a JSON key is an
    identifier — true of the keys a board happens to serve, false of the keys
    `_key_spelling` normalises over, which is the population the rule audits.
    Every one of the spellings below is address-bearing by that function's own
    definition, and `_PAIR` reads every one of them; an audit that cannot see
    them reports a capture it failed on as a capture with nothing in it.
    """
    invisible = []
    for key in _address_bearing_separator_spellings():
        raw = f'{{"{key}":"203.0.113.9"}}'
        assert _PAIR.search(raw), key  # non-vacuity: the grammar really reads it
        if not any(m.group(1) == key for m in _SCALAR_KEY_SITE.finditer(raw)):
            invisible.append(key)
    assert not invisible, (
        f"{len(invisible)} of {len(_address_bearing_separator_spellings())} "
        f"address-bearing spellings are reachable by the pair grammar and "
        f"invisible to the locator that audits it: {invisible}"
    )


def test_every_requester_seed_is_audited() -> None:
    """Clause 1's seeds are read off the frozenset, never spelled out again.

    A key-level audit is structurally blind to this: a `custom` block needs no
    address-bearing key in it, so every key inside one can be reachable while
    the object the sweep depends on is not. A seed added to
    `REQUESTER_OBJECT_KEYS` later is covered here because the axis is that set.
    """
    for seed in sorted(REQUESTER_OBJECT_KEYS):
        # A block the grammar cannot span: the value swallows its terminator.
        raw = f'{{"{seed}":{{"a":"C:\\\\","ip":"203.0.113.9"}}}}'
        found = unaudited_requester_sites(raw)
        assert any("in no matched block" in what for _, what in found), (seed, found)
        intact = f'{{"{seed}":{{"ip":"203.0.113.9"}}}}'
        assert not unaudited_requester_sites(intact), (seed, intact)


def test_an_object_the_grammar_loses_is_reported_though_every_key_is_read() -> None:
    """The reading a key-level audit cannot make, and the reason there are three.

    Here `_PAIR` reads all three keys and the locator sees all three sites, so
    the key-level reading is silent by construction — and the sweep still fails,
    because it works on *objects*: with no block located, the postcode beside
    the address is never touched. The control is the same capture without the
    escape, where the sweep reaches all three values.
    """
    lost = '{"path":"C:\\\\\\"","ip":"203.0.113.9","zip_code":"08001"}'
    read = '{"path":"C:","ip":"203.0.113.9","zip_code":"08001"}'

    assert [m.start(1) for m in _PAIR.finditer(lost)] == [
        m.start(1) for m in _SCALAR_KEY_SITE.finditer(lost)
    ], "the premise is gone: this capture now has an unreached key site"
    assert "08001" in scrub_requester_location(lost)[0], "the sweep now reaches it"
    assert "08001" not in scrub_requester_location(read)[0], lost

    assert any("lost to a mis-read value" in what for _, what in unaudited_requester_sites(lost))
    assert not unaudited_requester_sites(read)


def test_the_escape_axis_varies_every_escape_json_defines() -> None:
    """Breadth, not merely non-vacuity: trimming the axis must go red.

    The test above only needs *one* capture the grammar fails on, so an axis
    cut down to the single escape that happens to break it would still pass —
    and the next spelling nobody listed would fail open, which is the shape
    this whole block exists to stop.
    """
    varied = {label.rsplit("/", 2)[0] for label, _ in _captures_carrying_an_escape()}
    assert varied == {repr(escape) for escape in _JSON_ESCAPES}
    assert set('"\\/bfnrt') <= set(_JSON_ESCAPES), _JSON_ESCAPES
    assert len(_captures_carrying_an_escape()) == len(_JSON_ESCAPES) * 3 * 2


def _unreached_trailing_keys() -> dict[str, list[str]]:
    """Per capture, the keys in the trailing run the asymmetry does not reach."""
    out: dict[str, list[str]] = {}
    for package in sorted(p for p in DEFAULT_CONNECTORS_DIR.iterdir() if p.is_dir()):
        if not (package / "connector.yaml").exists():
            continue
        for path in sorted(p for p in package.rglob("*") if p.is_file()):
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for match in _FLAT_JSON_OBJECT.finditer(raw):
                lead = _LEADING_RUN.search(raw, max(0, match.start() - _RUN_WINDOW), match.start())
                if (lead.group(3) if lead else "") in REQUESTER_OBJECT_KEYS:
                    continue  # the trailing run does fire for these
                if not any(_is_address_bearing(k) for k, _ in _PAIR.findall(match.group(0))):
                    continue
                trail = _TRAILING_RUN.match(raw, match.end(), match.end() + _RUN_WINDOW)
                if trail and trail.group(0).strip():
                    key = f"{package.name}/{path.relative_to(package)}"
                    out[key] = [k for k, _ in _PAIR.findall(trail.group(0))]
    return out


def test_the_unreached_trailing_run_is_still_what_was_adjudicated() -> None:
    """The asymmetry is fail-open by design; this makes a change to it visible.

    `requester_location_blocks` does not extend right from an address-seeded
    block, so the scalars written after one are unreached. That was adjudicated
    against what is *in* them — and the adjudication is only as good as the
    list, which the board can reorder at any time. Without this, such a
    reordering moves a requester key into the blind spot with nothing
    observable changing: the pair count does not even fall.

    So this is the docstring's own list, re-measured from the committed bytes.
    A red here is not necessarily a leak — it means the run changed and the
    asymmetry has to be re-argued against what is in it now.
    """
    expected = [
        "ip",
        "userAppliedJobs",
        "userJobAlertData",
        "protocol",
        "host",
        "isDefaultLanguage",
        "children",
    ]
    measured = _unreached_trailing_keys()
    assert measured, "no address-seeded block has an unreached trailing run — the check is vacuous"
    assert all(keys == expected for keys in measured.values()), measured
    leaking = [k for keys in measured.values() for k in keys if _is_address_bearing(k)]
    assert set(leaking) == {"ip"}, (
        f"an address-bearing key other than the adjudicated `ip` is in the unreached "
        f"run: {leaking} — `ip` is swept by _pairs_to_redact wherever it sits, and "
        "that argument was made about `ip` alone"
    )
