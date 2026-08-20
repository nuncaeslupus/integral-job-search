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

## `handle_sync.py` is safe again — v0.33.0 fixed it

This file used to say "do NOT create the handles `handle_sync.py` proposes",
because `missing_handles` iterated every task `load_tasks` returns — including
`_history/` — and filtered only on "has an issue", never on `status`. On this
repo it printed **51** proposals, every one for work that merged weeks ago.
Following protocol step 4 literally would have opened 51 issues for finished
tasks, each then reading as open, unclaimed work.

**Fixed upstream in v0.33.0** (`claude-arsenal#169`): it filters terminal
tasks. Verified here — 1 line, `handle_sync: every task has an issue handle`.

So step 4 of the protocol is correct as written again: run it, and open an
issue for anything it prints.

## `make arsenal-remote` reports; `make arsenal-upgrade REF=…` upgrades

`check_update.sh` without `--check-only` performs the subtree merge **and
commits**, and the upgrade it performs is incomplete: it re-runs `init.py`,
which assembles the bundle from `.claude/skills/init/assets/` — refreshed only
by `make update-skills` — so the bundle is rebuilt from the pre-upgrade assets
and stays a version behind while reporting success. That happened here on
2026-08-20 (subtree v0.30.0, bundle v0.29.1, `verify-subtree` failing).

`arsenal-remote` now passes `--check-only`, so reading the version no longer
writes history. Upgrade deliberately, with `make arsenal-upgrade REF=v0.x.y`,
which runs all four steps. **`claude-arsenal#170` is fixed in v0.33.0** — the
script re-vendors skills after a subtree update and refuses to report success
while the bundle version is still stale, which is the half that used to lie.
The `--check-only` habit is kept anyway: reading a version should not write
history even when the write would be correct.

**After any upgrade, run `make reader` and `make evidence`.** v0.33.0 changed
`create_reader.py`, which left both generated spec readers stale, and grew the
bundle from 22 assets to 26, which moved S9's evidence. Both are caught by the
suite (`test_regenerating_the_reader_produces_no_diff`, the `make evidence`
drift check) — the point is that they are *expected* after an upgrade and are
fixed with the repo's own tooling, never by hand.

## The skill listing budget lives in `arsenal/config.toml`

`listing-budget = 13000` (S10). `jobsearch.skill_budget` reads it, and since
v0.33.0 so does `skill-creator`'s `audit_library.py` — `claude-arsenal#143`
landed, so the auditor no longer hardcodes 8,000 and both read the same key.

`jobsearch.skill_budget` is still the gate: it refuses a budget that is not a
round multiple of 1,000 or that leaves under 400 chars of headroom, records
where the number came from, and reports `-1` — not a clean zero — when the
library is inside a budget that was overridden, fell back, or was fitted to the
measurement.

The audit's remaining "within 10% of 13000" warning is the budget working: 862
chars spare, revisit at roughly three more skills. **Do not silence it by
raising the number.**

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
