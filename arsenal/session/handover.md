# Session handover — 2026-08-20 (D-16 merged-pending; PR #112)

## Board

- **D-16 (`t-221adf32`, #92) is done and open in PR #112**, archived to
  `_history/` with `status: merged` and `Closes #92` in both the commit message
  and the PR body. It closes and unblocks by itself on merge.
- D-21's PR #111 **merged** since the last handover; #91 is closed and the
  "archived as merged but #91 is still open" flag has cleared.
- `task_select.py` next returns **`t-6f52a4b9` (D-17, "ranked offers must carry
  their URL", priority 9, S)** — check it yourself, the queue is the truth.
- One pre-existing board flag, unchanged: mixed-priority-convention — 27 tasks
  on the size scale [10, 5, 1, 0] and 2 on other values [70, 60].

## What D-16 was

A test session at step 7 ran a general `WebSearch`, fetched two hits and
presented seven adverts. `integral.connectors` was never called, and nothing
said so — the candidate had to ask whether that part was implemented. Seven
adverts arrive either way; only one of the two searched their market.

Three pieces, all measured by `undisclosed_connectorless_sourcing == 0`:

- **The disclosure is a rule with a remedy attached.** `spec-v2-steps.md` §7
  requires it and `step-07-sourcing` carries a `## Coverage` section. Both
  remedies — build a connector for a named portal, drive the candidate's own
  browser session — are part of the measurement, because a disclosure naming no
  way out is a dead end.
- **An example is not coverage.** `assess_coverage` discounts a package whose
  site is under a reserved TLD (`.test`, `.example`, `.invalid`, `.localhost` —
  RFC 2606 / 6761). That is a rule, not a blocklist: it stays true for the next
  example somebody commits.
- **A search result stays legible as one.** `build_search_offer` always stamps
  `source: web_search`, `Connector` refuses that name, and `offer_provenance`
  reads it back as `connector`, `search`, or `unattributed`.

The reading is `src/integral/connector_coverage.py`; the two tests the plan
named are in `tests/test_connectors.py`. **Read the plan row before naming a
metric** — that lesson from D-21 held again here, and cost nothing this time
because the row was read first.

## Two things worth knowing before touching this area

**Probing "markets" needs the undeclared one.** The situations probed are every
market the installed library declares *plus* the market no package declares.
Without that second one, a library that happened to cover every market it names
would report a true zero while the disclosure rule quietly rotted — the same
vacuous-pass shape as D-21, one level along.

**`make lint` does not check formatting.** It runs `ruff check` and `mypy`,
never `ruff format --check`, so format drift accumulates unnoticed: a repo-wide
`ruff format` here rewrapped `step_certification.py` and its test, untouched
work from the previous session. That was reverted in `fca469e` rather than
ridden along on D-16. **Format only the files you touched**, or seed a task for
the drift — do not sweep it into an unrelated PR.

## Left open (carried forward)

- **Format drift is unenforced** — `make lint` has no `ruff format --check`.
  New, and not seeded.
- **`connectors/` still holds no connector for a real board.** That is T12, not
  D-16: this task was about saying so. The first real package makes
  `connectors_usable` non-zero and turns the ES reading covered.
- **`verify-gates` asserts a fenced gate block is *present*, never that the
  command inside resolves.** The general form of D-21, and of T55 before it.
  Still not seeded.
- **`claude-arsenal#182`** (false `rest`), **`#183`** (`check_update.sh` on a
  missing remote), **`#188`** (`outline.sh` parsing), **`#189`**
  (`context_budget.py` scores a missing `AGENTS.md` as 0 and passes). All still
  open upstream.
- **A permissions edit only the owner can make**: `Bash(gh run list:*)` and
  `Bash(gh run view:*)` in `.claude/settings.json`.
- **D-12 (`t-e1ca8374`, #83) still waits on the owner.** Resolution B has
  existed since v0.33.0 (`gate: unmeasured`).
- **`tools/profile_guard.sh` matches a candidate path mentioned in *prose***,
  not only one being opened. Still not seeded.
- **D-22's host half is actionable**: a `make gate` target running all five, for
  `host-gate` to point at. (Note `make gate` already exists and means something
  else — it records `lint_typecheck_exit_code`. That name is taken.)
- **Steps 5, 6, 10, 11, 12 are still `not_implemented`**, and say so out loud.
- **The GitHub repo has not been renamed.** Owner's to do.

## The gate, run locally (CI has no runner minutes)

Still true, re-diagnosed on PR #112 rather than assumed: the `pytest` job was
created 21:39:45, completed 21:39:48, `runner_id: 0`, `runner_name: ""` — three
seconds, no runner ever assigned. All five jobs, same signature. Do not read a
red CI here as a signal about the code.

All five run locally and pass on this branch:

```bash
make lint           # ruff + strict mypy — clean, 105 source files
make test           # 1184 passed, 1 skipped
make evidence       # no drift
make verify-subtree # 0 diverging, 34 assets compared
make verify-gates   # 63 terminal tasks, 63 gates asserted
```

`status/evidence/T55.json`'s `files_scanned` moved 464 → 465. Note the scan
counts **tracked** files only: regenerating evidence before `git add` gave 463
and looked like drift. Stage first, then `make evidence`.

## Surface facts

Unchanged, all in `CLAUDE.md`: `--detect` prints a false `rest`, REST is dead
here (`403 GitHub access is not enabled for this session` — do not probe
again), `claim_task.sh` returns `manual POST` and `create_branch` on
`arsenal/claims/<id>` is the compare-and-swap (201 won, 422 lost),
`open_task_pr.sh` cannot be used, and merging goes through the MCP tool.

One addition: **editing `status/spec-v2-steps.md` requires `make reader-steps`.**
`test_regenerating_the_reader_produces_no_diff` fails until
`docs/spec-v2-steps/` is regenerated and committed — it is not obvious from the
failure that a spec edit is what caused it.
