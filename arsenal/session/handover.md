# Session handover — 2026-08-20 (D-14 worked; the board is unchanged otherwise)

## Read this first

**D-14 is done and merged.** PR
[#100](https://github.com/nuncaeslupus/job-search/pull/100) landed as `71b3bb9`
and closed [#90](https://github.com/nuncaeslupus/job-search/issues/90); the task
file is archived at `arsenal/tasks/_history/t-05892c87.md` with
`status: merged`. Nothing is owed on it. All five gates were re-run on `main`
after the merge and pass.

The previous handover's list of ten divergences (#90–#99) stands, minus D-14.
`task_select.py` returns **D-15** (`t-65ecce18`, #93) next — nine divergences
are still open, all at priority 10, so read the selector rather than the numeric
order of the D-labels.

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

## Which divergences are ours, and which are upstream's (carried from the previous handover)

Checked deliberately, because a fix to the vendored tree gets overwritten by the
next `make arsenal-upgrade` and fails `make verify-subtree` in the meantime.

**Nine of the ten are host-owned** — `.claude/skills/step-*` (D-13, D-14, D-15,
D-17, and `run_checkpoint.py` for D-21), `src/jobsearch/*` (D-18, D-19, D-20,
D-21), `dimensions/` and `connectors/` (D-16, D-19). Nothing under
`claude-arsenal/`. **D-14 is now done** — it was one of the nine.

**D-22 was mixed, and is already split** (that split landed on `main` as
`4987514`, while this session was working). Its bundle half —
`claude-arsenal/agents/worker.md` step 4 asks a worker to "run the host lint
gate if one exists" and no script enforces it, while `open_task_pr.sh` re-runs
`gate_run.sh` and never asks about the repo gate — is filed upstream as
**`claude-arsenal#175`**. The host half stays here: a `make gate` target
running all five, for upstream's proposed `host-gate` config key to point at.

`keyword-guard` firing only on `arsenal/**` is **correct** and was ruled out,
not filed: a PR that is not a task PR should not need `Closes #<issue>`.

## Context cost — one upstream issue filed, two fixes landed here

Token consumption was audited this session. Fixed here (in this PR): `.rgignore`
excluding the vendored and generated trees from every ripgrep-backed search, and
a `CLAUDE.md` section on searching the corpus — a line in `corpus/*/ads.jsonl`
is a whole advert, the longest **15,640 characters**, so an unbounded content
search across both files returns ~100KB in one result.

**Filed upstream: `claude-arsenal#177`.** `AGENTS.md` is **762 lines / ~14.7k
tokens**, imported into every consumer repo's `CLAUDE.md`, so it is resident on
every turn of every session — 85% of this repo's whole memory-file budget, and
five times its own `CLAUDE.md`. It exceeds the chunking rules the same plugin
ships (`references-and-chunking.md`: split past 400 lines, or when a section
over 100 lines is loaded only for a subset of tasks — the worker loop is 138
lines and the two queue-seeding sections are 66% identical to each other). The
proposal is the shape skill-creator asks of skills: ~150-line body plus six
`references/*.md`, worth ~11.7k tokens per turn everywhere.

Still the owner's to do: turn off MCP connectors this repo never uses
(Gmail/Calendar/Drive were ~40k of a 63.7k catalogue; they dropped out of the
session on their own late on), and decide the Actions billing question below.

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
