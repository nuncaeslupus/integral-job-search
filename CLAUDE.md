<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

Every session, without waiting to be asked:

1. Read `arsenal/session/handover.md` for the previous session's context.
2. List the repository's issues labelled `arsenal:task` — **open and closed** — and
   save the JSON. Use whatever GitHub access this surface has; run
   `claude-arsenal/bin/github_channel.sh --detect` to find out which.
3. Run `python3 claude-arsenal/scripts/query_status.py --issues <that file>` for the
   board, and report anything it flags.
4. Pick up work: `python3 claude-arsenal/scripts/task_select.py --issues <that file>`
   returns the next unblocked task, then
   `bash claude-arsenal/bin/claim_task.sh <id>` takes it (see `@claude-arsenal/AGENTS.md`).
   - **Nothing returned + workspace plans exist** → seed tasks from each plan.
   - **Nothing at all** → ask what to work on.
5. Open each task's PR with `Closes #<issue>` so merging it closes the task by itself.
6. After any session with tasks: update `arsenal/session/handover.md`.

@claude-arsenal/AGENTS.md

<!-- host-owned: not managed by claude-arsenal -->
## Reading the board on this surface — do this instead of `--issues`

Steps 3 and 4 of the protocol above pass `--issues <file>` to `query_status.py`
and `task_select.py`. **That does not work here, and it fails silently.** Those
scripts identify a task by an HTML-comment marker in the issue body, and the
GitHub MCP server strips HTML from bodies before returning them, so the marker
never arrives. `state_from_issues` matches nothing and returns an empty map for
every issue.

An empty map looks healthy: every task defaults to `open`, so selection is
right up until the first task is finished — whose issue is closed, whose state
is still read as `open`, and whose work is therefore handed out again.

So derive the state map first, and pass it as `--state`:

```bash
# 1. fetch the issues (MCP: list_issues, labels=["arsenal:task"], open AND closed,
#    fields number/body/state/labels) and save the JSON to $ISSUES.
#    For each CLOSED issue also call issue_read and keep its
#    `closed_by_pull_requests` — that is what distinguishes done from parked.
uv run python -m jobsearch.board_state --issues "$ISSUES" > "$STATE"
python3 claude-arsenal/scripts/task_select.py --tasks-dir arsenal/tasks --state "$STATE"
```

`jobsearch.board_state` recovers each task from the `arsenal/tasks/<id>.md` link in the
body (ordinary markdown, unstripped), prefers the real marker wherever it
survives, and reports rather than guesses at an issue it cannot resolve. It also
treats a closed issue with **no closing PR** as `cancelled` rather than `done`,
because `state_reason` is unavailable on this surface and upstream's default
would read a deliberately parked task as finished (claude-arsenal#155).

Drop this section once the marker survives the round trip — check with
`task_select.py --issues` returning a non-empty selection and no warnings.


## Known environment state

**GitHub Actions is out of runner minutes until the next billing period
(noted 2026-08-19).** Every job on every workflow run fails in 3–5 seconds with
`runner_id: 0` and `runner_name: ""` — no runner is ever assigned. This affects
`main` as much as any branch: run #142 on `ba7c980` (main's own HEAD) failed
identically, while the last green run was #137. It is not caused by any diff.

Do not treat a red CI on this repository as a signal about the code, and do not
push speculative "fixes" for it. Diagnose it once by checking a failed job for
`runner_id: 0` plus a sub-5-second duration; if both hold, it is this.

**Run the gate locally instead** — these are exactly what CI would run, and all
five must pass before a merge:

```bash
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-subtree # the arsenal bundle matches its subtree
make verify-gates   # every done/merged task can still show its measurement
```

Remove this section once runs are completing with real durations again.
