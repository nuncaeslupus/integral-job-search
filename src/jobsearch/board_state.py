#!/usr/bin/env python3
"""Derive the board's `{task_id: state}` map from GitHub issues, on this surface.

`task_select.py --issues` is the documented path, and it does not work here.
It finds a task by an HTML-comment marker in the issue body:

    TASK_MARKER_RE = re.compile(r"<!--\\s*arsenal-task:\\s*([A-Za-z0-9._-]+)\\s*-->")

The GitHub MCP server this session reads issues through **strips HTML from
issue bodies** before returning them — the marker, and any other angle-bracket
token, is simply gone. `state_from_issues` then matches nothing and returns an
empty map for all 27 issues.

An empty map is not obviously broken, which is what makes it dangerous. Every
task defaults to `open`, so selection looks right while no task has ever been
finished. The first closed issue is where it bites: its task keeps reading
`open`, stays selectable forever, and the work is handed out again.

So this rebuilds the map from what the surface *does* return:

* **Identity** — the marker when it survives, else the `arsenal/tasks/<id>.md`
  payload link, which is ordinary markdown and comes through intact. Preferring
  the marker means this keeps working unchanged if the stripping is fixed.

* **State** — `open`, or `claimed` when the claim label or an assignee is
  present, matching `state_from_issues`. A **closed** issue is `done` only when
  a merged pull request closed it, and `cancelled` otherwise.

That last rule is deliberately *not* what upstream does. `state_from_issues`
reads `state_reason` and defaults a missing one to `completed` — but the MCP
`list_issues` tool cannot return `state_reason` at all, so upstream's default
would read every closed issue as `done`, including one closed as *not planned*
to park it (claude-arsenal#155). Keying on the closing PR instead is both
available here and stricter: it is the "a concrete PR closed this" evidence the
old `release.sh done --pr <url>` required before writing a terminal status.

`closed_by_pull_requests` comes from `issue_read`, not `list_issues`, so only
closed issues need the extra call — there are normally very few.

Exit: 0 with the JSON map on stdout; 2 if the issues file cannot be read.
Unresolvable issues are named on stderr and left out of the map rather than
guessed at.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

MARKER_RE = re.compile(r"<!--\s*arsenal-task:\s*([A-Za-z0-9._-]+)\s*-->")
PAYLOAD_RE = re.compile(r"arsenal/tasks/(?:_history/)?([A-Za-z0-9._-]+)\.md")
CLAIMED_LABEL = "arsenal:claimed"


def task_id_of(issue: dict[str, Any]) -> str | None:
    """The task an issue carries the state of, or None if it names no task."""
    body = str(issue.get("body") or "")
    marker = MARKER_RE.search(body)
    if marker:
        return marker.group(1)
    payload = PAYLOAD_RE.search(body)
    return payload.group(1) if payload else None


def _labels(issue: dict[str, Any]) -> set[str]:
    return {
        label["name"] if isinstance(label, dict) else str(label)
        for label in (issue.get("labels") or [])
    }


def state_of(issue: dict[str, Any]) -> str:
    """One of `open`, `claimed`, `done`, `cancelled`."""
    if str(issue.get("state", "")).lower() == "closed":
        closed_by = issue.get("closed_by_pull_requests") or {}
        if isinstance(closed_by, dict) and closed_by.get("total_count"):
            return "done"
        return "cancelled"
    if CLAIMED_LABEL in _labels(issue) or issue.get("assignee") or issue.get("assignees"):
        return "claimed"
    return "open"


def board_state(issues: list[dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    """The state map, and a warning for each issue naming no task."""
    state: dict[str, str] = {}
    warnings: list[str] = []
    for issue in issues:
        task_id = task_id_of(issue)
        if task_id is None:
            warnings.append(f"issue #{issue.get('number', '?')} names no task — skipped")
            continue
        state[task_id] = state_of(issue)
    return state, warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", type=Path, required=True, help="JSON list of issues")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        payload = json.loads(args.issues.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"board-state: cannot read {args.issues} — {exc}", file=sys.stderr)
        return 2
    if isinstance(payload, dict):
        payload = payload.get("issues", [])
    if not isinstance(payload, list):
        print("board-state: expected a JSON list of issues", file=sys.stderr)
        return 2
    state, warnings = board_state([i for i in payload if isinstance(i, dict)])
    for warning in warnings:
        print(f"board-state: {warning}", file=sys.stderr)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
