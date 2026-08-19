"""The CI gate-verifier, held to the standard it exists to enforce.

`tools/verify_gates.py` is the check that stops a task recorded `done` from
keeping that status after a later commit breaks its gate. A check that cannot
fail protects nothing, so these drive it against a queue built to break it —
a terminal task whose evidence violates its threshold, one whose evidence file
is gone, one whose payload is missing — and require a refusal each time.

The passing case is deliberately the *last* thing asserted. A verifier that
returns 0 on everything would satisfy a green-path test on its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFIER = REPO_ROOT / "tools" / "verify_gates.py"

GATED_PAYLOAD = """# X1: a task with a mechanical gate

## Acceptance gate

```gate
{metric} == 1.0
evidence: {evidence}
key: {metric}
```
"""


def _queue(tmp_path: Path, rows: list[dict[str, object]]) -> Path:
    queue = tmp_path / "tasks.jsonl"
    queue.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )
    return queue


def _run(tmp_path: Path, queue: Path) -> subprocess.CompletedProcess[str]:
    """Drive the verifier against a fixture board.

    It takes `--queue` and `--payload-dir` precisely so this is possible: a
    verifier whose only input is the real board could only ever be tested on a
    board that already passes, which would prove nothing about its refusals.
    """
    return subprocess.run(
        [
            sys.executable,
            str(VERIFIER),
            "--queue",
            str(queue),
            "--payload-dir",
            str(queue.parent),
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def _write_gated_task(
    tmp_path: Path, task_id: str, *, metric: str, measured: float | None
) -> dict[str, object]:
    evidence = tmp_path / f"{task_id}-evidence.json"
    if measured is not None:
        evidence.write_text(json.dumps({metric: measured}), encoding="utf-8")
    (tmp_path / f"{task_id}.md").write_text(
        GATED_PAYLOAD.format(metric=metric, evidence=evidence), encoding="utf-8"
    )
    return {"id": task_id, "status": "done", "payload": f"{task_id}.md"}


def test_a_done_task_whose_evidence_violates_its_gate_is_refused(tmp_path: Path) -> None:
    """The failure the whole check exists for: the ledger says `done`, the
    measurement says otherwise, and nothing else in the repository would
    notice. `gate_run.sh` ran once at release time against a tree that no
    longer exists."""
    row = _write_gated_task(tmp_path, "x1", metric="leaks_prevented", measured=0.5)
    result = _run(tmp_path, _queue(tmp_path, [row]))
    assert result.returncode == 1
    assert "x1" in result.stderr


def test_a_done_task_with_no_evidence_file_is_refused(tmp_path: Path) -> None:
    """A deleted or never-written evidence file must not read as "nothing to
    check, therefore fine". Vacuous passing is how a gate layer goes inert
    without anyone noticing — one consumer audit found every gate in a repo
    had been doing exactly that."""
    row = _write_gated_task(tmp_path, "x2", metric="leaks_prevented", measured=None)
    result = _run(tmp_path, _queue(tmp_path, [row]))
    assert result.returncode == 1


def test_a_done_task_with_no_payload_file_is_refused(tmp_path: Path) -> None:
    """A terminal status pointing at a payload that is not there is a broken
    board, not a passing one. Skipping it would let a task be marked done and
    then have its evidence quietly deleted along with its payload."""
    queue = _queue(tmp_path, [{"id": "x3", "status": "done", "payload": "gone.md"}])
    result = _run(tmp_path, queue)
    assert result.returncode == 1
    assert "x3" in result.stderr


def test_an_open_task_without_evidence_is_not_a_failure(tmp_path: Path) -> None:
    """A task nobody has started has nothing to measure. Demanding evidence
    from it would make the board red from the first commit and keep it red,
    and a check that is permanently failing is one nobody reads — which costs
    more than it protects. Terminal status is what turns a declared gate into
    a promise."""
    row = _write_gated_task(tmp_path, "x4", metric="leaks_prevented", measured=None)
    row["status"] = "open"
    result = _run(tmp_path, _queue(tmp_path, [row]))
    assert result.returncode == 0


def test_an_unreadable_queue_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """A ledger that will not parse must exit 2, distinctly from 0. Reducing
    the board to the rows that happened to be readable would silently stop
    checking whatever the broken line described."""
    queue = tmp_path / "tasks.jsonl"
    queue.write_text('{"id": "x5", "status": "done"}\nnot json at all\n', encoding="utf-8")
    result = _run(tmp_path, queue)
    assert result.returncode == 2


def test_a_done_task_whose_evidence_satisfies_its_gate_passes(tmp_path: Path) -> None:
    """Asserted last, and only after the refusals above: a verifier that
    returned 0 unconditionally would satisfy this test on its own."""
    row = _write_gated_task(tmp_path, "x6", metric="leaks_prevented", measured=1.0)
    result = _run(tmp_path, _queue(tmp_path, [row]))
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("target", ["evidence", "verify-gates", "ci"])
def test_the_makefile_exposes_the_targets_ci_invokes(target: str) -> None:
    """CI calls `make evidence`, `make verify-gates` and `make ci` by name. A
    renamed or dropped target turns those jobs into a red build that says
    nothing about the code, so the workflow and the Makefile are pinned to
    each other here rather than discovered to disagree on a push."""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert f"\n{target}:" in makefile
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert target in workflow


def _board(tmp_path: Path, task_id: str, *, status: str, measured: float | None) -> Path:
    """A board in the post-migration shape: a directory of front-matter files."""
    board = tmp_path / "tasks"
    history = board / "_history"
    history.mkdir(parents=True, exist_ok=True)
    evidence = tmp_path / f"{task_id}-evidence.json"
    if measured is not None:
        evidence.write_text(json.dumps({"coverage": measured}), encoding="utf-8")
    front_matter = (
        f"---\nid: {task_id}\n"
        f'title: "{task_id.upper()}: a finished task"\n'
        f"status: {status}\n---\n\n"
    )
    (history / f"{task_id}.md").write_text(
        front_matter + GATED_PAYLOAD.format(metric="coverage", evidence=evidence),
        encoding="utf-8",
    )
    return board


def test_a_terminal_task_on_the_migrated_board_still_has_its_gate_asserted(
    tmp_path: Path,
) -> None:
    """The migration moves finished tasks out of the ledger. If the verifier
    only understood the ledger, that move would retire every assertion it makes
    while still exiting 0 — the board would look green because nothing was
    being checked, which is the exact failure this file exists to prevent."""
    board = _board(tmp_path, "h1", status="merged", measured=0.0)
    result = _run(tmp_path, board)
    assert result.returncode == 1, result.stdout
    assert "h1" in result.stderr


def test_a_task_file_with_no_id_is_an_error_not_a_pass(tmp_path: Path) -> None:
    """Same standard as a malformed ledger line: exit 2, not a quiet skip."""
    board = _board(tmp_path, "h2", status="merged", measured=1.0)
    (board / "_history" / "broken.md").write_text("---\ntitle: no id\n---\n", encoding="utf-8")
    result = _run(tmp_path, board)
    assert result.returncode == 2


def test_a_live_task_on_the_board_is_not_required_to_have_evidence(tmp_path: Path) -> None:
    """A task nobody has finished legitimately has no measurement. Live task
    files carry no `status`, so demanding one would make the board red from the
    first commit — a check that always fails is a check nobody reads."""
    board = _board(tmp_path, "h3", status="merged", measured=1.0)
    (board / "h4.md").write_text(
        '---\nid: h4\ntitle: "H4: unstarted"\n---\n\nno gate here\n', encoding="utf-8"
    )
    result = _run(tmp_path, board)
    assert result.returncode == 0, result.stderr


def test_a_board_whose_gates_all_hold_passes(tmp_path: Path) -> None:
    """Asserted last, for the reason given above."""
    board = _board(tmp_path, "h5", status="merged", measured=1.0)
    result = _run(tmp_path, board)
    assert result.returncode == 0, result.stderr
