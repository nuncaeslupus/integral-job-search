# Session handover — 2026-08-20 (D-14 worked; the board is unchanged otherwise)

## Read this first

**D-14 is done and waiting on a merge.** PR
[#100](https://github.com/nuncaeslupus/job-search/pull/100) closes
[#90](https://github.com/nuncaeslupus/job-search/issues/90); the task file is
already archived to `arsenal/tasks/_history/t-05892c87.md` with
`status: merged` inside that same diff, so merging it closes the issue and
archives the task in one act. Nothing is owed afterwards.

The previous handover's list of ten divergences (#90–#99) stands, minus D-14.
`task_select.py` returns **D-13** (`t-bd59e70b`, #97) next.

## What D-14 turned out to be

Not a bad sentence in a skill — an **absent** one. `step-02-constraints`
required every constraint field to end the step `stated`, `declined` or
`unknown`, listed what to cover, and left employment mode off that list. The
field still had to be resolved, so the phrasing was improvised, and the
improvisation offered an illegal arrangement.

That shaped the gate. A string search for "falso autónomo" would have read
**0** on the day the defect happened, because nothing had written the bad
question down. So `skills_offering_an_illegal_employment_mode` counts two
limbs, and the second is the one that bites:

1. prose naming an unlawful arrangement without ruling it out;
2. the skill that must resolve `employment_mode` carrying no rule at all.

`jobsearch.employment_mode` is a module of its own rather than a flag on
`step_skills` because **`make evidence` runs each module once with no
arguments** — a gate reachable only behind a flag is a gate whose drift nothing
notices. That is already true of D-4's and D-7's numbers today
(`step_gates --owners` / `--traits`), and worth seeding if it bites again.

## The board, read this session

`query_status.py`: 91 tasks — open 14, claimed 0, done 1, cancelled 1,
blocked 19, merged 56. One flag, and it is the pre-existing one:

> mixed-priority-convention: 32 task(s) use the size scale [10, 5, 1, 0] and 2
> use other values [70, 60]

Not from this session. `handle_sync.py` reports every task has an issue handle.

## Two surface facts worth not rediscovering

**`github_channel.sh --detect` prints `rest`, and `rest` does not work here.**
The probe is a `GET /rate_limit`, which the proxy answers 200; every real call
answers **403 "GitHub access is not enabled for this session"**. So the channel
is effectively `none` on this surface: fetch the issues with the MCP
`list_issues` tool and hand-write the JSON the scripts read
(`number`, `state`, `body` carrying `arsenal-task: <id>`, `labels`,
`assignees`). `claim_task.sh` therefore exits 5 with a `manual POST` line —
make that call with `mcp__github__create_branch` (201 = won, 422 = lost).

**`open_task_pr.sh` was not used.** It cuts `arsenal/<id>-<slug>` off the
default branch, and this surface restricts pushes to the session's own
designated branch. The archive, the `Closes #90` in both the commit and the PR
body, and the PR itself were done by hand to the same shape. A session with the
same restriction should expect to do that too — and must not skip the archive,
which is what makes merging complete the task.

## CI is still out of runner minutes (unchanged, and now re-confirmed)

Every job on PR #100 failed **3 seconds** after starting, with empty
`output.text` — no runner was ever assigned. `main`'s own runs are identically
red: #249 (`f5985908`), #250 (`75d19ff0`), #252 (`49875147`), each failing in
5 seconds. It is not the diff. Do not push speculative fixes for it.

All five gates were run locally and pass:

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

`make test` 1080 passed / 1 skipped · `make evidence` no drift ·
`make verify-gates` 58 terminal tasks, 58 gates asserted, 0 without a fenced
block · `make verify-subtree` 0 diverging.

That the repo gate runs only because somebody asks is **D-22**, still open.

## Left open (carried forward, untouched this session)

- **A permissions edit the owner has to make**: `Bash(gh pr merge:*)`,
  `Bash(gh run list:*)`, `Bash(gh run view:*)` in `.claude/settings.json`.
  A session cannot widen its own permissions.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Not seeded yet; decide whether the guard should
  inspect the tool's target rather than the whole command string.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B exists
  since arsenal v0.33.0 (`gate: unmeasured`).
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and steps 8 and 9
  still certify over unbuilt gates until D-21 lands.
