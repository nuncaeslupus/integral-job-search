# Session handover — 2026-08-20 (T55 open as #108; bundle on v0.36.1)

## Read this first

- **T55 (`lo-9f72`, #49) is done and open as
  [#108](https://github.com/nuncaeslupus/job-search/pull/108)**, not merged.
  The task file is already archived at `arsenal/tasks/_history/lo-9f72.md` with
  `status: merged` inside that same diff, so merging #108 closes #49, archives
  the task and unblocks its dependents in one act.
- **The GitHub repository is still named `job-search`.** That rename is an owner
  action and nothing in this repo can do it. `README.md`'s clone URL and
  `docs/distribution.md` §7 now name `nuncaeslupus/integral-job-search`, which
  GitHub redirects to the moment the owner renames — and does not resolve until
  then. It is the only part of the sweep that is not live.

## What T55 changed

`src/jobsearch/` → `src/integral/` (49 modules), distribution →
`integral-job-search`, `uv.lock` regenerated, 170 files touched. The gate is a
reference count in `src/integral/naming.py` writing `status/evidence/T55.json`,
picked up by `make evidence` like every other module's gate.

**The counter refuses three lookalikes**, and this is the part worth knowing
before anyone widens it:

| spelled the same | what it is | swept? |
|---|---|---|
| `ai-job-search` | the external precedent `status/specification.md` compares against | no |
| `job-search process` | the thirteen-step process the step skills are named after | no |
| `job-search-spec-v1:` | the `localStorage` key the generated readers save annotations under | no — rewriting orphans saved annotations |

`arsenal/` is allowlisted from the count: the ledger's historical rows say what
they said at the time. So is `naming.py` itself and its test — a counter has to
name what it counts.

## Surface facts (unchanged, re-confirmed this session)

- **`github_channel.sh --detect` prints `rest`, and `rest` does not work here.**
  Confirmed again: `--api GET /repos/…/issues` returns **HTTP 403** "GitHub
  access is not enabled for this session". Upstream `claude-arsenal#182`. The
  practical cost is not the failure, it is that the board JSON must then be
  **hand-written from the MCP result** — ~2k output tokens every session, spent
  re-typing data already in context.
- **`claim_task.sh` returns `manual POST`**; `create_branch` on
  `arsenal/claims/<id>` is the compare-and-swap. 201 = won, 422 = lost.
- **`open_task_pr.sh` still cannot be used** — it cuts a branch off the default
  branch and this surface only permits pushes to the session's designated
  branch. Archive the task file, put `Closes #<issue>` in both the commit and
  the PR body, and open the PR by hand.
- **CI is still out of runner minutes.** Not re-diagnosed this session; the
  gate was run locally instead, all five green.

## Left open (carried forward)

- **`claude-arsenal#188`, `#189`, `#182`, `#183`** all still open upstream.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Still not seeded.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has
  existed since v0.33.0 (`gate: unmeasured`).
- **`claude-arsenal#180`** — `open_task_pr.sh` reads `host-gate` from the git
  root and runs it in the cwd. Inert here while `host-gate` is unset.
- **D-22's host half is actionable**: a `make gate` target running all five, for
  `host-gate` to point at.
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and steps 8 and 9
  certify over unbuilt gates until D-21 lands.
- **One pre-existing board flag**: mixed-priority-convention — 29 tasks use the
  size scale [10, 5, 1, 0] and 2 use other values [70, 60].

## The gate

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

Latest: `make test` **1140 passed / 1 skipped** (was 1126; +14 in
`tests/test_naming.py`) · `make evidence` no drift · `make verify-subtree` 0
diverging, 34 assets · `make verify-gates` **61** terminal tasks, 61 gates
asserted, 0 without a fenced block.
