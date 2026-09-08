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

import json
import subprocess
import sys
from pathlib import Path

import pytest

from integral.gate_reader_agreement import (
    ARRANGEMENTS,
    MINIMUM_ARRANGEMENTS_PROBED,
    MINIMUM_GATES_COMPARED,
    UNGATED_ARRANGEMENT,
    Arrangement,
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
