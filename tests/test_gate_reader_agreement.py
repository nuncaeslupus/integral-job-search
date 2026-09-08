"""T122 — the two gate readers, held to agreeing about what declaring a gate is.

Every expected verdict below is derived from the **checker's stated grammar** —
`gate_evidence.py` searches from the first ``##\\s+Acceptance gate`` heading to
the next ``##`` and reads the first ``gate`` fence inside that span — and not
from what either reader currently returns. That is the circularity these cases
exist to break: a fixture written by running the code describes the code.

The five unread arrangements were measured against the unmodified `origin/main`
verifier before the fix and every one of them scored a divergence: counted among
"gate(s) asserted", checked by a reader that read nothing, and green over an
evidence file that does not exist. The two controls were red then and must stay
red now, because a fix that stopped counting *everything* would zero the metric
while asserting nothing at all.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from integral.gate_reader_agreement import (
    ARRANGEMENTS,
    MINIMUM_ARRANGEMENTS_PROBED,
    MINIMUM_GATES_COMPARED,
    UNGATED_ARRANGEMENT,
    Arrangement,
    Probe,
    floor_breaches,
    measure,
    probe,
    record,
)
from integral.task_gate import gate_declaration

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "tools" / "verify_gates.py"
EVIDENCE = REPO_ROOT / "status" / "evidence" / "T122.json"

UNREADABLE = tuple(a for a in ARRANGEMENTS if not a.carries_a_readable_gate)
READABLE = tuple(a for a in ARRANGEMENTS if a.carries_a_readable_gate)


def _ids(arrangements: tuple[Arrangement, ...]) -> list[str]:
    return [a.name for a in arrangements]


@pytest.mark.parametrize("arrangement", UNREADABLE, ids=_ids(UNREADABLE))
def test_a_fence_the_grammar_does_not_reach_is_not_counted_as_asserted(
    arrangement: Arrangement,
) -> None:
    """The five ways a fence is present and unread, each end to end.

    The assertion is the *consequence*, not the classification: the fixture
    declares an evidence file that does not exist, so a verifier that counted
    the gate and still returned green asserted nothing. That is the exact
    reading `t-2a30f58a` and `t-246f6dde` got on #334.
    """
    result = probe(arrangement, VERIFIER)
    assert result.counted_as_asserted == 0, arrangement.why
    assert not result.counted_but_never_read


@pytest.mark.parametrize("arrangement", READABLE, ids=_ids(READABLE))
def test_a_fence_the_grammar_does_reach_is_still_asserted(arrangement: Arrangement) -> None:
    """The controls. A fix that counts nothing zeroes the metric and is not a fix."""
    result = probe(arrangement, VERIFIER)
    assert result.counted_as_asserted == 1, arrangement.why
    assert not result.green, "a gate whose evidence file is missing must fail, not pass"
    assert not result.stopped_asserting


def test_a_payload_with_no_fence_is_reported_as_carrying_none() -> None:
    """`t-62612ae0`'s shape: an executable gate is not a fault to refuse."""
    result = probe(UNGATED_ARRANGEMENT, VERIFIER)
    assert result.reported_ungated == 1
    assert result.counted_as_asserted == 0
    assert result.green


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("## Acceptance gate\n\n```gate\nm == 0\n```\n", "readable"),
        ("**Acceptance gate**\n\n```gate\nm == 0\n```\n", "unreadable"),
        ("## Acceptance gate\n\n```bash\npytest\n```\n", "absent"),
        ("no headings, no fences", "absent"),
    ],
)
def test_gate_declaration_separates_a_missing_gate_from_an_unreachable_one(
    text: str, expected: str
) -> None:
    """Three outcomes, because conflating the last two is the whole defect."""
    assert gate_declaration(text) == expected


def test_the_verifier_refuses_a_fence_it_cannot_read_rather_than_tallying_it(
    tmp_path: Path,
) -> None:
    """An unreachable fence is a failure, not a quieter line in the report.

    Counting it among "carry no fenced gate block" would be honest arithmetic
    and a silent outcome: the author declared a gate, and nothing enforces it.
    """
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "t-bold.md").write_text(
        '---\nid: t-bold\ntitle: "bold"\nstatus: merged\n---\n\n'
        "**Acceptance gate**\n\n```gate\nm == 0\nevidence: status/evidence/absent.json\n"
        "key: m\n```\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--queue",
            str(tasks),
            "--payload-dir",
            str(tasks),
            "--report-json",
            str(report),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 1
    assert "no reader reaches" in result.stderr
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["unreadable_fences"] == ["t-bold"]
    assert payload["ungated"] == 0
    assert payload["counted_as_asserted"] == 0


def test_the_board_and_the_fixtures_agree_today() -> None:
    """The gate itself, over the real board plus every arrangement."""
    measured = measure()
    assert measured["gate_reader_agreement_status"] == "measured"
    assert measured["gates_counted_as_asserted_but_never_read"] == 0, measured["divergent"]
    assert measured["readable_gates_the_verifier_stopped_asserting"] == 0, measured[
        "stopped_asserting"
    ]
    assert measured["ungated_tasks_refused_as_faulty"] == 0, measured["refused_as_faulty"]
    assert measured["gates_compared"] >= MINIMUM_GATES_COMPARED
    assert len(measured["arrangements_probed"]) >= MINIMUM_ARRANGEMENTS_PROBED


def test_a_thin_scan_is_a_floor_breach_rather_than_a_clean_zero() -> None:
    """Zero divergences over nothing compared is the vacuous pass, not a pass."""
    thin = {
        "gates_counted_as_asserted_but_never_read": 0,
        "gates_compared": 3,
        "arrangements_probed": ["bold_label"],
    }
    breaches = floor_breaches(thin)
    assert len(breaches) == 2
    assert any("payload(s) compared" in breach for breach in breaches)
    assert any("arrangement(s) probed" in breach for breach in breaches)


def test_the_record_commits_the_floor_and_not_the_census() -> None:
    """T100's precedent: a count committed exactly goes stale on someone else's merge."""
    committed = record(
        {
            "gates_counted_as_asserted_but_never_read": 0,
            "gates_compared": 174,
            "arrangements_probed": ["bold_label"],
        }
    )
    assert "gates_compared" not in committed
    assert committed["gates_compared_at_least"] == MINIMUM_GATES_COMPARED
    assert committed["arrangements_probed"] == ["bold_label"], (
        "the fixture set is named in the record, not just counted"
    )


def test_the_committed_evidence_names_every_arrangement_the_module_probes() -> None:
    """A fixture deleted from the module must be visible in the evidence diff.

    `make evidence` refuses drift, so this is not the drift check; it is the
    one assertion that the *committed* record still carries the fixture set by
    name rather than a count somebody could have reached with fewer of them.
    """
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    expected = {a.name for a in ARRANGEMENTS} | {UNGATED_ARRANGEMENT.name}
    assert set(committed["arrangements_probed"]) == expected
    assert committed["gates_compared_at_least"] == MINIMUM_GATES_COMPARED


def _verifier_module() -> ModuleType:
    """`tools/verify_gates.py` loaded in-process, so its checker can be stubbed.

    Every other case here drives the verifier as a subprocess, which is the
    honest way to measure it. This one needs the checker replaced, and the
    checker is a module-level path rather than an argument.
    """
    spec = importlib.util.spec_from_file_location("t122_verify_gates", VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("arrangement", UNREADABLE, ids=_ids(UNREADABLE))
def test_every_unread_arrangement_really_carries_the_fence_it_is_about(
    arrangement: Arrangement,
) -> None:
    """Each unread fixture is `unreadable`, never `absent`.

    Without this the ten cases above are satisfiable the wrong way: a payload
    carrying no fence at all is also never counted and also never green over a
    missing evidence file, so a fixture that lost its fence in an edit would go
    on passing while measuring nothing. `unreadable` is the classification each
    is derived from — the substring is present and the grammar does not reach
    it — so it is the classification asserted.
    """
    assert "```gate" in arrangement.body, arrangement.why
    assert gate_declaration(arrangement.body) == "unreadable", arrangement.why


def test_a_counted_gate_whose_checker_printed_nothing_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The end-to-end catch, made load-bearing.

    `gate_evidence.py` exits 0 in exactly two states: it read a block and the
    measurement cleared the threshold, in which case it says so on stdout, or
    it found no block and returned silently. So a counted gate whose checker
    printed nothing was not asserted, whatever the grammar on this side thinks
    — which is the half of the fix that survives any future drift between the
    two readers.

    The second reader on #425 measured this branch as free to delete: all
    eighty-eight tests and the gate metric stayed green without it. A stub
    checker that exits 0 and prints nothing is what makes it die.
    """
    verify_gates = _verifier_module()
    mute_checker = tmp_path / "mute_checker.py"
    mute_checker.write_text("import sys\n\nsys.exit(0)\n", encoding="utf-8")
    monkeypatch.setattr(verify_gates, "GATE_EVIDENCE", mute_checker)

    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "t-mute.md").write_text(
        '---\nid: t-mute\ntitle: "mute"\nstatus: merged\n---\n\n'
        "## Acceptance gate\n\n```gate\nfixture_metric == 0\n"
        "evidence: status/evidence/absent-fixture.json\nkey: fixture_metric\n```\n",
        encoding="utf-8",
    )
    report = tmp_path / "report.json"
    status = verify_gates.main(
        [
            "--queue",
            str(tasks),
            "--payload-dir",
            str(tasks),
            "--report-json",
            str(report),
        ]
    )

    assert status == 1, "a silent pass is not a measurement"
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["counted_as_asserted"] == 1
    assert payload["counted_as_asserted_but_never_read"] == ["t-mute"]


def test_the_reported_signal_alone_catches_a_verifier_that_is_red() -> None:
    """A verifier that drifted back to a substring rule and reports it honestly.

    It names the divergence and exits 1, so the run is **not** green and the
    exit-status signal is silent. This is the shape a plain revert of the fix
    produces — and it is the whole of why `counted_but_never_read` reads what
    the run says as well as what it did.
    """
    honest_but_wrong = Probe(
        name="drifted_verifier",
        counted_as_asserted=1,
        exit_status=1,
        reported_ungated=0,
        reported_never_read=1,
    )
    assert not honest_but_wrong.green
    assert honest_but_wrong.counted_but_never_read


def test_the_exit_status_signal_alone_catches_a_verifier_that_reports_nothing() -> None:
    """A verifier whose own report is empty, and which is green anyway.

    The fixture declares an evidence file that does not exist, so a checker
    that read the block must fail. Green while counting a gate is therefore the
    divergence with nothing else it can be — and it is all that is left when
    the verifier's self-report has stopped being trustworthy, which is the case
    a number reported about itself cannot cover.
    """
    silent_and_green = Probe(
        name="mute_verifier",
        counted_as_asserted=1,
        exit_status=0,
        reported_ungated=0,
        reported_never_read=0,
    )
    assert silent_and_green.counted_but_never_read


def test_a_substring_verifier_that_reports_nothing_is_caught_end_to_end(
    tmp_path: Path,
) -> None:
    """The same signal, driven by a verifier rather than asserted about one.

    This stub *is* the pre-fix reader: it counts the fence by substring, never
    runs a checker, writes an empty `counted_as_asserted_but_never_read`, and
    exits 0. Its report is clean and its verdict is wrong, so the first signal
    cannot see it. If the exit-status signal were dropped, this run would read
    as agreement.
    """
    substring_verifier = tmp_path / "substring_verifier.py"
    substring_verifier.write_text(
        "import argparse\n"
        "import json\n"
        "from pathlib import Path\n"
        "\n"
        "parser = argparse.ArgumentParser()\n"
        'parser.add_argument("--queue", type=Path)\n'
        'parser.add_argument("--payload-dir", type=Path)\n'
        'parser.add_argument("--report-json", type=Path)\n'
        "args = parser.parse_args()\n"
        "counted = sum(\n"
        "    1\n"
        '    for payload in sorted(args.payload_dir.glob("*.md"))\n'
        '    if "```gate" in payload.read_text(encoding="utf-8")\n'
        ")\n"
        "args.report_json.write_text(\n"
        "    json.dumps(\n"
        "        {\n"
        '            "counted_as_asserted": counted,\n'
        '            "ungated": 0,\n'
        '            "counted_as_asserted_but_never_read": [],\n'
        "        }\n"
        "    )\n"
        '    + "\\n",\n'
        '    encoding="utf-8",\n'
        ")\n",
        encoding="utf-8",
    )

    result = probe(UNREADABLE[0], substring_verifier)

    assert result.counted_as_asserted == 1
    assert result.green, "the stub reproduces the pre-fix reader, which passed these"
    assert result.reported_never_read == 0, "its own report is clean; that is the point"
    assert result.counted_but_never_read, UNREADABLE[0].why
