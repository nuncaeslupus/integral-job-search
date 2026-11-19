"""Ending a test session requires a recorded decision for every note (T213)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from integral.test_mode import NoteLedger, NoteRow, SessionRow, TallyRow, ledger_path

SCRIPT = Path(__file__).resolve().parents[1] / ".claude/skills/test-mode/scripts/query_notes.py"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--id", "s1", "--input-dir", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _session(root: Path, notes: int = 2) -> None:
    ledger = NoteLedger(ledger_path(root, "s1"))
    ledger.open_session(SessionRow(session_id="s1", simulated=True, at="t"))
    for n in range(1, notes + 1):
        ledger.append(NoteRow(n=n, text=f"note {n}", step="step-00-identify", at="t"))


def test_undecided_note_fails_check_and_is_listed(tmp_path: Path) -> None:
    _session(tmp_path)
    result = _run(tmp_path, "--check")
    assert result.returncode == 1
    assert "1. note 1" in result.stderr and "2. note 2" in result.stderr


def test_check_passes_once_every_note_is_decided(tmp_path: Path) -> None:
    _session(tmp_path)
    assert _run(tmp_path, "--decide", "1", "seeded", "--task", "t-abc").returncode == 0
    assert _run(tmp_path, "--check").returncode == 1
    assert _run(tmp_path, "--decide", "2", "discarded", "--reason", "already known").returncode == 0
    assert _run(tmp_path, "--check").returncode == 0


def test_second_decision_is_refused(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    assert _run(tmp_path, "--decide", "1", "seeded", "--task", "t-abc").returncode == 0
    again = _run(tmp_path, "--decide", "1", "discarded", "--reason", "changed my mind")
    assert again.returncode == 2
    assert "already has a decision" in again.stderr
    assert "seeded as t-abc" in _run(tmp_path).stdout


def test_decision_shows_in_the_review(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    _run(tmp_path, "--decide", "1", "discarded", "--reason", "already known")
    assert "discarded: already known" in _run(tmp_path).stdout


def test_unknown_note_number_is_refused(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    result = _run(tmp_path, "--decide", "9", "seeded", "--task", "t-abc")
    assert result.returncode == 2
    assert "no note 9" in result.stderr


def test_decision_needs_its_task_or_reason(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    assert _run(tmp_path, "--decide", "1", "seeded").returncode == 2
    assert _run(tmp_path, "--decide", "1", "discarded").returncode == 2


def test_lost_marker_does_not_block_a_fully_decided_session(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    NoteLedger(ledger_path(tmp_path, "s1")).append_tally(TallyRow(unparsed_markers=1, at="t"))
    assert _run(tmp_path, "--check").returncode == 1
    # --decide prints the review, which still exits 1 for the lost marker; only --check ends.
    _run(tmp_path, "--decide", "1", "discarded", "--reason", "already known")
    assert _run(tmp_path, "--check").returncode == 0


def test_malformed_decision_row_exits_2(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    with ledger_path(tmp_path, "s1").open("a", encoding="utf-8") as stream:
        stream.write('{"kind": "decision", "n": 1, "decision": "discarded"}\n')
    assert _run(tmp_path, "--check").returncode == 2


def test_blank_task_id_is_refused(tmp_path: Path) -> None:
    _session(tmp_path, notes=1)
    assert _run(tmp_path, "--decide", "1", "seeded", "--task", "  ").returncode != 0
    assert _run(tmp_path, "--check").returncode == 1
