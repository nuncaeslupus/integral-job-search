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

from integral import gate_reader_agreement
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
    write_evidence,
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


def test_the_floor_is_sized_to_the_set_it_is_read_against() -> None:
    """The floor counts the probed list — the arrangements *plus* the ungated shape.

    `floor_breaches` compares `MINIMUM_ARRANGEMENTS_PROBED` against
    `len(measured["arrangements_probed"])`, and `measure` builds that list from
    `ARRANGEMENTS` **and** `UNGATED_ARRANGEMENT`. Sized to `ARRANGEMENTS` alone
    the constant sat one under the population it guards, so the first deleted
    fixture cleared it (#425, round three).

    The committed record is a census of a real run, so it is the honest
    statement of that population, and reading the constant against it is what
    makes an *added* arrangement raise the floor instead of widening the slack —
    the half of the rule the constant's own comment says is easy to skip.
    """
    committed = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert len(committed["arrangements_probed"]) == MINIMUM_ARRANGEMENTS_PROBED


def test_the_floor_fires_on_the_first_deleted_fixture() -> None:
    """One arrangement short of the committed set is a breach, not a pass.

    The boundary case, and it is a *pair*: the full set must be clean and the
    set minus one must not be. Only the pair discriminates — without it
    ``probed < MINIMUM_ARRANGEMENTS_PROBED - 1`` passes every other case in this
    file, which is how one unit of slack survived a round of review inside the
    guard whose own message is that "a clean zero reached by deleting the
    fixtures is the defect, not the fix".
    """
    probed = sorted(json.loads(EVIDENCE.read_text(encoding="utf-8"))["arrangements_probed"])
    full = {"gates_compared": MINIMUM_GATES_COMPARED, "arrangements_probed": probed}
    assert floor_breaches(full) == [], "the committed set is what a healthy run probes"

    one_short = {"gates_compared": MINIMUM_GATES_COMPARED, "arrangements_probed": probed[:-1]}
    assert any("arrangement(s) probed" in breach for breach in floor_breaches(one_short)), (
        "a fixture deleted from the module must breach the floor, not merely leave "
        "a diff line in the evidence for somebody to notice"
    )


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


#: A verifier that is wrong in every direction `measure` has a finding for, and
#: whose own report is clean about all of it except one task it names honestly.
#:
#: It exists because **every finding this module reports reads zero on the real
#: board**, and a number only ever observed at zero is not observed at all: each
#: line in `measure` that turns a probe into a finding can be deleted, and a
#: metric of 0 with every test green is what comes back. The stub is the state
#: in which all three findings are non-zero at once, so the tests below can
#: assert that the reported numbers are *read from* the probes and the board
#: rather than merely being 0 beside them.
#:
#: * it counts a fence by substring and runs no checker, so every unreadable
#:   arrangement comes back counted and **green** over an evidence file that
#:   does not exist — the divergence, by the second signal;
#: * being green, it also fails both controls, which is `stopped_asserting`;
#: * it reports `ungated: 0` whatever it was handed, so the payload carrying no
#:   fence at all is refused as faulty — the over-reach finding;
#: * and it names, in its own report, any payload carrying `_DRIFT_MARKER`,
#:   which is the board half: a verifier honest enough to say it counted a gate
#:   its checker never read.
_DRIFT_MARKER = "t122-stub-report-this-one-as-never-read"

_STUB_VERIFIER = f"""
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--queue", type=Path)
parser.add_argument("--payload-dir", type=Path)
parser.add_argument("--report-json", type=Path)
args = parser.parse_args()

payloads = sorted(args.payload_dir.glob("*.md"))
texts = {{p.stem: p.read_text(encoding="utf-8") for p in payloads}}
args.report_json.write_text(
    json.dumps(
        {{
            "compared": len(payloads),
            "counted_as_asserted": sum(1 for t in texts.values() if "```gate" in t),
            "ungated": 0,
            "counted_as_asserted_but_never_read": sorted(
                stem for stem, t in texts.items() if {_DRIFT_MARKER!r} in t
            ),
        }}
    )
    + "\\n",
    encoding="utf-8",
)
"""


def _stub_board(tmp_path: Path) -> tuple[Path, Path]:
    """A two-task board and the stub verifier, ready to hand to `measure`.

    One of the two payloads carries the drift marker, so the stub's own report
    names it. That is the only way the board half of the metric can ever be
    non-empty, and it is the half that guards the residual mirror between
    `task_gate`'s grammar and `gate_evidence.py`'s.
    """
    verifier = tmp_path / "stub_verifier.py"
    verifier.write_text(_STUB_VERIFIER, encoding="utf-8")

    board = tmp_path / "tasks"
    board.mkdir()
    gate = (
        "## Acceptance gate\n\n```gate\nm == 0\n"
        "evidence: status/evidence/absent.json\nkey: m\n```\n"
    )
    (board / "t-drifted.md").write_text(
        f'---\nid: t-drifted\ntitle: "drifted"\nstatus: merged\n---\n\n'
        f"<!-- {_DRIFT_MARKER} -->\n\n" + gate,
        encoding="utf-8",
    )
    (board / "t-clean.md").write_text(
        '---\nid: t-clean\ntitle: "clean"\nstatus: merged\n---\n\n' + gate,
        encoding="utf-8",
    )
    return board, verifier


def test_every_finding_measure_reports_is_read_from_its_inputs(tmp_path: Path) -> None:
    """The metric, and its two siblings, driven to a state where each is non-zero.

    **The class this closes, rather than the two spellings that revealed it.**
    `measure` reads a board report and thirteen probes and turns them into three
    findings. On the real board all three are 0 — which is the pass — so every
    line that performs that turn is severable with nothing red: replace the
    fixture branch with `elif False`, or the board comprehension with `[]`, or
    the control loop's `if`, or the over-reach expression with `[]`, and the
    committed `gates_counted_as_asserted_but_never_read: 0` that
    `make verify-gates` re-asserts for the life of this task becomes a constant
    that no fixture feeds. `make evidence` sees no drift, because the
    regenerated value is still 0.

    Two of those four were found by the second reader on #425 as surviving
    mutants; the other two are the same shape and are pinned here for the same
    reason. Every assertion below is an exact set, not a count, so a finding
    that is populated from the wrong source is as red as one populated from
    nothing.
    """
    board, verifier = _stub_board(tmp_path)
    measured = measure(tasks=board, verifier=verifier)

    # The board half: the verifier's own report of a gate it counted and never
    # read, carried into the metric under a `board:` prefix that says so.
    assert "board:t-drifted" in measured["divergent"]

    # The fixture half: every arrangement the checker's grammar does not reach,
    # counted and green over an evidence file that does not exist.
    assert measured["divergent"] == sorted(["board:t-drifted"] + [a.name for a in UNREADABLE])
    assert measured["gates_counted_as_asserted_but_never_read"] == len(UNREADABLE) + 1

    # The controls, which stop the metric being bought by counting nothing.
    assert measured["stopped_asserting"] == sorted(a.name for a in READABLE)
    assert measured["readable_gates_the_verifier_stopped_asserting"] == len(READABLE)

    # The other direction: a payload declaring no gate, refused as though it had.
    assert measured["refused_as_faulty"] == [UNGATED_ARRANGEMENT.name]
    assert measured["ungated_tasks_refused_as_faulty"] == 1

    # And the denominator, which is the board's census plus the probes actually run.
    assert measured["gates_compared"] == 2 + len(ARRANGEMENTS) + 1


def test_the_probed_set_is_the_set_that_was_probed(tmp_path: Path) -> None:
    """`arrangements_probed` and `gates_compared` name what ran, not a constant.

    Both are what the floors are read from, so a hard-coded pair would let a run
    that probed two arrangements clear a floor of twelve. Driving `measure` with
    a subset is the only way to tell the two apart: the fixture set is otherwise
    always the same thirteen names, which a constant reproduces exactly.
    """
    board, verifier = _stub_board(tmp_path)
    subset = ARRANGEMENTS[:2]
    measured = measure(tasks=board, verifier=verifier, arrangements=subset)

    assert measured["arrangements_probed"] == sorted(
        [a.name for a in subset] + [UNGATED_ARRANGEMENT.name]
    )
    assert measured["gates_compared"] == 2 + len(subset) + 1
    assert floor_breaches(measured), "three probes is under the floor, and must say so"


def _clean_measurement() -> dict[str, object]:
    """A measurement with every finding at zero and every floor cleared."""
    return {
        "gates_counted_as_asserted_but_never_read": 0,
        "readable_gates_the_verifier_stopped_asserting": 0,
        "ungated_tasks_refused_as_faulty": 0,
        "divergent": [],
        "stopped_asserting": [],
        "refused_as_faulty": [],
        "gates_compared": MINIMUM_GATES_COMPARED,
        "arrangements_probed": [f"a{n}" for n in range(MINIMUM_ARRANGEMENTS_PROBED)],
        "gate_reader_agreement_status": "measured",
    }


@pytest.mark.parametrize(
    ("finding", "names"),
    [
        ("gates_counted_as_asserted_but_never_read", "divergent"),
        ("readable_gates_the_verifier_stopped_asserting", "stopped_asserting"),
        ("ungated_tasks_refused_as_faulty", "refused_as_faulty"),
    ],
)
def test_each_finding_the_module_reports_makes_the_run_red(
    finding: str, names: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every finding is wired to the exit status, one at a time.

    Same class one level out: `_main` turns three numbers into an exit code, and
    on a healthy board all three are 0, so each `return 1` is deletable with the
    suite green. What `make evidence` and `make verify-gates` actually read is
    that exit code, so a finding that does not reach it is a finding nobody is
    told about.
    """
    measured = _clean_measurement()
    measured[finding] = 1
    measured[names] = ["something the run found"]
    monkeypatch.setattr(gate_reader_agreement, "measure", lambda *a, **k: measured)

    assert gate_reader_agreement._main(["prog", "--check"]) == 1


def test_a_clean_measurement_is_the_only_green_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control for the three above: zero findings over cleared floors is 0.

    Without it they are satisfiable by a `_main` that returns 1 unconditionally,
    which is the same vacuous shape read the other way round.
    """
    monkeypatch.setattr(gate_reader_agreement, "measure", lambda *a, **k: _clean_measurement())
    assert gate_reader_agreement._main(["prog", "--check"]) == 0


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda m: m.update({"gates_compared": MINIMUM_GATES_COMPARED - 1}), 1),
        (lambda m: m.update({"arrangements_probed": ["one"]}), 1),
        (lambda m: m.update({"gate_reader_agreement_status": "unmeasured"}), 3),
    ],
    ids=["thin_census", "deleted_fixtures", "unmeasured"],
)
def test_a_run_that_measured_too_little_is_not_a_pass(
    mutate: object, expected: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A floor breach is exit 1 and an unmeasured tree is exit 3, not a clean zero."""
    measured = _clean_measurement()
    mutate(measured)  # type: ignore[operator]
    monkeypatch.setattr(gate_reader_agreement, "measure", lambda *a, **k: measured)
    assert gate_reader_agreement._main(["prog", "--check"]) == expected


def test_a_floor_breach_writes_no_evidence_file(tmp_path: Path) -> None:
    """The record a thin run could write is one whose floors claim they held.

    `write_evidence` is the only caller that both measures and commits, so the
    guard lives there and nothing else can be asked about it. The stub board is
    two payloads, which is under `gates_compared`'s floor by two orders.
    """
    board, verifier = _stub_board(tmp_path)
    evidence = tmp_path / "written" / "T122.json"
    measured = write_evidence(evidence=evidence, tasks=board, verifier=verifier)

    assert floor_breaches(measured), "the stub board is deliberately thin"
    assert not evidence.exists(), "a breaching run must leave no artefact behind"


def test_a_deleted_fixture_cannot_be_laundered_by_regenerating_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The committed-name check dissolves on regeneration. The floor must not.

    Round three on #425 measured the whole sequence: delete one arrangement, run
    the module the way `make evidence` runs it (no `--check`), and
    `test_the_committed_evidence_names_every_arrangement_the_module_probes` is
    green again over a record naming twelve. It worked only because the floor
    was silent by one, so nothing stopped the write.

    The case above and this one are different halves: that one says the
    arrangements floor fires, this one says firing it is *sufficient* to refuse
    the record, with every other denominator healthy. `write_evidence` reads
    `floor_breaches` before it writes for exactly this reason.
    """
    one_short: dict[str, object] = dict(_clean_measurement())
    probed = sorted(json.loads(EVIDENCE.read_text(encoding="utf-8"))["arrangements_probed"])
    one_short["arrangements_probed"] = probed[:-1]
    breaches = floor_breaches(one_short)
    assert not any("payload(s) compared" in breach for breach in breaches), (
        "only the fixture set is thin here — the board census is untouched"
    )
    monkeypatch.setattr(gate_reader_agreement, "measure", lambda *a, **k: one_short)

    evidence = tmp_path / "T122.json"
    gate_reader_agreement.write_evidence(evidence=evidence)
    assert not evidence.exists(), (
        "a run that lost a fixture must not be allowed to rewrite the record that "
        "names the fixtures"
    )


def test_the_default_run_is_the_one_that_rewrites_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`make evidence` runs this module with no `--check`, so that path must write.

    Found by looking for the class one more time before pushing: every case
    above drives `_main` through `--check`, which measures and reports. The path
    CI actually takes is the other one, and a `_main` that called `measure` on
    both branches would leave `status/evidence/T122.json` frozen at whatever was
    committed while `git diff` stayed clean and `make evidence` said "no drift".
    The value would then be a number nothing recomputes — this pull request's
    subject, one layer out from the two mutants it was opened to close.
    """
    measured = _clean_measurement()
    measured["divergent"] = []
    monkeypatch.setattr(gate_reader_agreement, "measure", lambda *a, **k: measured)

    written = tmp_path / "T122.json"
    assert gate_reader_agreement._main(["prog", "--write-evidence", str(written)]) == 0
    assert json.loads(written.read_text(encoding="utf-8")) == record(measured)
