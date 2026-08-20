# Session handover — 2026-08-20 (D-16 merged; D-20 merged-pending, PR #113)

## Board

- **D-16 (`t-221adf32`, #92) merged** as PR #112 → `429733c`. Board clean:
  #92 closed, task archived on `main`, no lingering flag.
- **D-20 (`t-6f79e090`, #94) is done and open in PR #113**, archived to
  `_history/` with `status: merged` and `Closes #94` in both the commit message
  and the PR body. It closes and unblocks by itself on merge.
- D-21's PR #111 also merged earlier in the session.
- **The selector, not the guess.** This handover previously predicted D-17
  would come next; the selector actually returned D-20. Run
  `task_select.py` and believe it — the queue is the truth, and the line above
  is a snapshot.
- One pre-existing board flag, unchanged: mixed-priority-convention — 26 tasks
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
work from the previous session. **Format only the files you touched** —
`ruff format <paths-you-changed>`, never `ruff format src tests`. This was
reverted twice in one session (`fca469e`, then `b3fcc8f`) because the second
`make`-style sweep re-did it. Or seed a task for the drift; do not sweep it
into an unrelated PR.

**A `meta.yaml` is not a connector.** The first cut of `read_package` decided
`usable` from metadata alone, so a directory holding a plausible `meta.yaml`
and nothing that fetches reported as covering its market and suppressed the
disclosure outright — D-16's own failure, through the back door of its own fix.
It now calls `load_connector`, the runtime's own definition of loadable, which
also brings the directory-name contract along for free. **When a check asks
"does X exist", make it ask the loader, not the filesystem.** Found by
CodeRabbit on #112, reproduced before fixing.

## What D-20 was

The candidate said "I can move, but in the province of Barcelona, or maximum to
Girona or Tarragona — I want to sleep home each day", and none of T24's ten
pinned fields could hold it, so the most filtering sentence of the session
became quote text while the filter kept offering Sevilla.

It went into **`Location.commutable_regions`, not an eleventh field** —
`Location` already owned "the on-site work they'll do without moving", and
`accepts_onsite_in_country` was that question asked as one bool over a whole
country. **Growing a field per sentence is how a pinned contract stops being
one**; prefer narrowing an existing field whose semantics already fit.

`unfilterable_stated_constraints` (`src/integral/stated_constraints.py`) probes
all ten pinned fields, each with an offer the constraint must remove *and* one
it must keep. The second failure mode is the one that matters: a field that
accepts a value and changes no offer's fate looks answered from every angle
while the candidate sees the same list either way.

**The plan row named `tests/test_candidate.py`, which does not exist** — the
candidate tests are in `tests/test_candidate_attributes.py`. The plan's *test
names* were honoured; the path was stale. Check the file exists before trusting
a plan row's path, the same way you check the metric name.

## Left open (carried forward)

- **Format drift is unenforced** — `make lint` has no `ruff format --check`.
  Not seeded.
- **A commute radius is a region list, not a distance.** "Within 50km" still has
  nowhere to go; converting kilometres to regions needs a gazetteer this repo
  does not have. Not seeded.
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
make lint           # ruff + strict mypy — clean, 106 source files
make test           # 1191 passed, 1 skipped
make evidence       # no drift
make verify-subtree # 0 diverging, 34 assets compared
make verify-gates   # 64 terminal tasks, 64 gates asserted
```

`status/evidence/T55.json`'s `files_scanned` moved 465 → 466. Note the scan
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
