<!-- claude-arsenal: auto-managed -->
## Automatic session protocol

Every session, without waiting to be asked:

1. Read `arsenal/session/handover.md` for the previous session's context.
2. List the repository's issues labelled `arsenal:task` — **open and closed** — and
   save the JSON. Use whatever GitHub access this surface has; run
   `claude-arsenal/bin/github_channel.sh --detect` to find out which. Request
   `number`, `title`, `state`, `labels`, `assignees` and **not `body`** — the bodies
   are the bulk of that fetch and nothing downstream reads them.
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

## This surface has no scriptable GitHub channel

`github_channel.sh --detect` prints `rest`, **and REST does not work here**: the
proxy answers `403 GitHub access is not enabled for this session`
(`claude-arsenal#182`). Don't probe it again — the MCP GitHub tools are the only
channel, so every GitHub step above is performed with them, and the board JSON the
scripts read is written to disk by hand from the tool result.

- `claim_task.sh` returns `manual POST`; `create_branch` on `arsenal/claims/<id>`
  is the compare-and-swap. **201 = won, 422 = lost.**
- `open_task_pr.sh` cannot be used — it cuts a branch off the default branch, and
  pushes here are restricted to the session's designated branch. Archive the task
  file, put `Closes #<issue>` in **both** the commit message and the PR body, and
  open the PR with the MCP tool.
- Merging works via the MCP `merge_pull_request` tool.

Steps 3 and 4 of the protocol need no workaround — run them as written. Since the
fetch drops `body`, issues resolve to tasks by **title**; v0.36.1 made that robust
and `query_status.py` names anything that still fails to resolve. Trust that list
over `handle_sync.py`'s proposals — only one of the two is wired to an action.

## Spending the context window deliberately

`.rgignore` excludes the vendored and generated trees from every ripgrep-backed
search, for the same reason `pyproject.toml` excludes them from ruff and mypy: they
are not ours to change. Search one deliberately with `rg -u --no-ignore-vcs`.

**The corpus is not excluded, and it is the expensive one.** A line of
`corpus/{raw,labelled}/ads.jsonl` is a whole advert — the longest is 15,640
characters — so one content match returns the whole thing. Count or list first
(`rg -c`, `rg -l`, any `output_mode` but `content`), then read the one record with
`python3 -c` and `json.loads`, projecting only the fields you need. Same for
`suggestions.json` and any `status/evidence/*.json`: project the key, never print
the file.

Three more costs, each measured here:

- **`rg -l` with no path scans ~500 files.** Name a directory.
- **Reading a module to learn its shape costs its whole length.** Use
  `bash claude-arsenal/bin/outline.sh <file>`; reserve a full read for code you are
  about to change.
- **A review bot's PR summary lands in context whole** — Qodo's on #108 was ~14k
  tokens and changed nothing. Skim it for findings and move on.

## Known environment state

**GitHub Actions is out of runner minutes until the next billing period** (noted
2026-08-19). Every job fails in 3–5 seconds with `runner_id: 0` and an empty
`runner_name` — no runner is ever assigned — on `main` as much as any branch, so it
is not caused by any diff. Do not treat a red CI here as a signal about the code,
and do not push speculative fixes for it. Diagnose once: `runner_id: 0` plus a
sub-5-second duration means this. Remove this section once runs show real durations.

**Run the gate locally instead.** These are what CI would run, and all five must
pass before a merge:

```bash
make lint           # ruff + strict mypy
make test           # pytest
make evidence       # regenerate every measurement, fail on drift
make verify-subtree # the arsenal bundle matches its subtree
make verify-gates   # every done/merged task can still show its measurement
```

## Read on demand — `docs/repo-playbook.md`

Upgrading the vendored bundle, the skill-listing budget, parking a task, and the
board's title-matching history live there. Each is needed at one moment in a
session, not on every turn, so it is a path to open — not an import.
