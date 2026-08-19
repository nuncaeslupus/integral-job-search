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
<!-- /claude-arsenal: auto-managed -->

<!-- host-owned: not managed by claude-arsenal -->
## Reading the board — the plain `--issues` path works again

`claude-arsenal` v0.28.0 stopped keying task identity on an HTML comment. A body
now resolves via a visible `arsenal-task: <id>` token **or** the ordinary
`arsenal/tasks/<id>.md` payload link, so the marker this surface's GitHub MCP
tools strip is no longer load-bearing, and the whole local workaround
(`jobsearch.board_state` plus `--state`) is gone with it. Verified on this
surface: 27 issues fetched, `task_select.py --issues` returns the same five
tasks with **zero** warnings, and `query_status.py --issues` reports one real
problem instead of 27 spurious "no issue handle" lines.

Steps 3 and 4 of the protocol above are therefore correct as written:

```bash
# fetch with MCP list_issues, labels=["arsenal:task"], open AND closed,
# fields number/body/state/labels; save to $ISSUES
python3 claude-arsenal/scripts/query_status.py --issues "$ISSUES"
python3 claude-arsenal/scripts/task_select.py  --issues "$ISSUES"
```

If a future selection ever comes back empty or unwarned when it should not be,
v0.28.0 says so out loud: `state_from_issues` warns when issues were fetched and
**none** resolved to a task, which is the "an empty map looks healthy" failure
that used to pass silently.

**Parking a task needs the `arsenal:cancelled` label.** `state_reason` is not
available through these MCP tools, so upstream reads any closed issue as `done`
unless that label is on it. Closing a task issue to park it, without the label,
silently releases everything downstream. Prefer keeping it **open** and holding
it out of selection with `requires:` — that is what #71 does — and use the label
only for work genuinely abandoned.

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
