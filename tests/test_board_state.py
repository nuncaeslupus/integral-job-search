"""The bridge that keeps the board's state readable on this surface.

`task_select.py --issues` finds a task by an HTML-comment marker in the issue
body, and the GitHub MCP server strips HTML from bodies before returning them.
The failure is silent: every task defaults to `open`, so a board where nothing
has been finished yet looks perfectly healthy, and the damage only appears once
a task is closed and gets handed out a second time.

These drive `tools/board_state.py` against bodies shaped exactly as that surface
returns them, and require it to recover the identity and the state that
`state_from_issues` loses. The passing case is asserted last, for the usual
reason: a resolver that returned something plausible for every input would
satisfy a green-path test on its own.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jobsearch.board_state import board_state, state_of, task_id_of

REPO_ROOT = Path(__file__).resolve().parents[1]

# What the MCP server actually returns: the `<!-- arsenal-task: … -->` marker
# gone, the ordinary markdown payload link intact.
STRIPPED_BODY = (
    "\n\n**workspace** ONTOLOGY · **priority** 5 · **tags** m3\n\n"
    "The task payload lives at [`arsenal/tasks/lo-77a6.md`]"
    "(https://github.com/nuncaeslupus/job-search/blob/main/arsenal/tasks/lo-77a6.md).\n"
)


def _issue(**overrides: object) -> dict[str, object]:
    issue: dict[str, object] = {
        "number": 45,
        "state": "OPEN",
        "body": STRIPPED_BODY,
        "labels": ["arsenal:task"],
    }
    issue.update(overrides)
    return issue


def test_upstream_marker_is_preferred_when_it_survives() -> None:
    """The fallback must not take over where the real marker is present, so
    this keeps working unchanged the day the stripping is fixed — and keeps
    reading the marker as authoritative where two ids disagree."""
    body = "<!-- arsenal-task: lo-real -->\n\n[`arsenal/tasks/lo-decoy.md`](x)"
    assert task_id_of(_issue(body=body)) == "lo-real"


def test_a_task_is_recovered_from_the_payload_link_when_the_marker_is_stripped() -> None:
    assert task_id_of(_issue()) == "lo-77a6"


def test_an_issue_naming_no_task_is_reported_not_guessed() -> None:
    """Skipping it loudly is the point. Guessing an id would attach some other
    task's state to this issue, which is worse than having no state at all."""
    state, warnings = board_state([_issue(body="a plain issue, unrelated to the board")])
    assert state == {}
    assert len(warnings) == 1 and "#45" in warnings[0]


def test_a_history_payload_link_resolves_to_its_task() -> None:
    assert task_id_of(_issue(body="[`arsenal/tasks/_history/lo-d2b2.md`](x)")) == "lo-d2b2"


def test_a_closed_issue_with_no_closing_pr_is_cancelled_not_done() -> None:
    """The rule this file exists to get right. `state_reason` is unavailable on
    this surface, and upstream defaults a missing one to `completed` — so an
    issue closed to *park* a task would read `done` and release everything
    waiting on it. Absent a closing PR, the close is not evidence of work."""
    assert state_of(_issue(state="CLOSED")) == "cancelled"


def test_a_closed_issue_is_done_only_when_a_pull_request_closed_it() -> None:
    """`done` means a concrete PR landed, which is what the retired
    `release.sh <id> done --pr <url>` required before writing a terminal
    status. The evidence, not the button, is what makes it terminal."""
    closed_by_pr = _issue(state="CLOSED", closed_by_pull_requests={"total_count": 1})
    assert state_of(closed_by_pr) == "done"


def test_an_assigned_or_labelled_issue_reads_as_claimed() -> None:
    assert state_of(_issue(labels=["arsenal:task", "arsenal:claimed"])) == "claimed"
    assert state_of(_issue(assignee={"login": "someone"})) == "claimed"


def test_the_cli_emits_a_state_map_task_select_can_consume(tmp_path: Path) -> None:
    """Asserted last: the whole point is a map `task_select.py --state` reads."""
    issues = tmp_path / "issues.json"
    issues.write_text(json.dumps([_issue()]), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "jobsearch.board_state", "--issues", str(issues)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"lo-77a6": "open"}
