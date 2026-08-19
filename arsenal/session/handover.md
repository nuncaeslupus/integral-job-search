# Session handover — 2026-08-19 (arsenal v0.26.0 → v0.29.0; D-2 done)

## Read this first

**The board's local workaround is gone, and the plain `--issues` path works.**
`CLAUDE.md` no longer tells you to derive a state map with `jobsearch.board_state`
— that module is deleted. Run the protocol as written:

```bash
# MCP list_issues, labels=["arsenal:task"], open AND closed,
# fields number/body/state/labels → $ISSUES
python3 claude-arsenal/scripts/query_status.py --issues "$ISSUES"
python3 claude-arsenal/scripts/task_select.py  --issues "$ISSUES"
```

claude-arsenal v0.28.0 stopped keying task identity on an HTML comment (a body
resolves via a visible `arsenal-task: <id>` token **or** the
`arsenal/tasks/<id>.md` payload link), which is exactly what the workaround
existed to do. Verified: 27 issues, 5 tasks selected, **zero warnings**.

## State

| what | where |
|------|-------|
| PR #74 — arsenal v0.26.0 → v0.29.0, board verified, workaround deleted | **merged** as `e87c243` |
| PR #75 — D-2 (`lo-77a6`), gold provenance | **open**, gates green locally |
| D-2 (`lo-77a6`) | claimed (`arsenal/claims/lo-77a6`), implemented, PR #75 |
| Bundle | **v0.29.0** — v0.29.1 is tagged upstream and **not yet pulled** |

## Do this next

1. **Pull v0.29.1.** `make arsenal-upgrade REF=v0.29.1`. It was tagged while
   this session was running and has not been looked at.
2. **T14 (`lo-3100`) needs an owner decision, not a worker run.** Its payload
   recommends folding it into T15 as the rules stage rather than gating it
   against a corpus that cannot support one. That is a scope call. The other
   unblocked tasks are T53 (`lo-803e`), T55 (`lo-9f72`), T9 (`lo-b422`).

## Three things that will bite you

### Never squash an arsenal upgrade PR

This is now written above `arsenal-upgrade` in the Makefile, with the check.
`git subtree pull --squash` records where the pull landed as a
`git-subtree-split:` trailer on its own commit; a squash merge rewrites the
branch into one commit and the trailer goes with it, so the **next** pull
cannot find where the last one stopped.

It already happened: before this session `origin/main` recorded exactly one
split, `f84b4ef` (the original `git subtree add`), because the v0.26.0 upgrade
was squash-merged as #44. The v0.27.0 pull therefore replayed v0.25→v0.27 onto
a tree already at v0.26 and conflicted on twelve files. #74 was merged with a
**merge commit** and main now records all four splits, so v0.29.1 should pull
clean. Check with:

```bash
git log origin/main --format=%H | while read c; do git cat-file -p $c | grep git-subtree-split:; done
```

### `claim_task.sh` cannot claim on this surface

`github_channel.sh --detect` prints `rest` on the strength of a `GET
/rate_limit` probe, but this proxy refuses API writes, so the script exits **2**
(`error:`) — which the protocol says to halt the loop over — instead of falling
back to its `manual` path. Filed as **claude-arsenal#163**, still open.

Claim by hand instead: the MCP `create_branch` tool with branch
`arsenal/claims/<task-id>`, which is the same compare-and-swap the script does
(201 = won, 422 = lost). Then label the issue `arsenal:claimed`, self-assign,
and comment the session id.

### CI cannot pass, and `merge-policy` now says what to do about it

Still out of runner minutes: every job on every head fails in 2–5s with
`runner_id: 0` and `runner_name: ""`. Diagnosed per head this session on
`c72d7c7`, `bd550bf` and `3974c13`. `main`'s own HEAD fails identically.

`arsenal/config.toml` is now `merge-policy = "after-ci-and-review"`, with a
note defining what the two words mean while the outage lasts:

* **ci** — the five gates run locally on the PR head (`make lint test evidence
  verify-subtree verify-gates`, i.e. `make ci`). Quote the results on the PR.
* **review** — the Qodo review has landed and every comment is fixed or
  answered. An unread bot review is not a review.

Delete that note when runners return. The enum has no value for "review
required, CI unavailable" — filed as **claude-arsenal#166**.

## What D-2 settled, and what it deliberately did not

`extraction.gold` entries now carry `derived_from: cue | human`, required with
no default. All **69** committed examples are `cue`. `evaluation_gold()` returns
only the human half and is the single function T15 may score over.

**T15 (`lo-25b1`) is bound by this**: call `evaluation_gold`, report `n` beside
any score, and refuse to emit `extraction_macro_f1` below a per-dimension label
floor, naming the dimensions it could not score. With `evaluation_gold_count`
at **0**, that refusal is currently the only correct output — no dimension can
be scored for extraction at all. Do not "fix" that by relabelling cue gold as
human; the empty result is the finding.

`unmatched_gold` now applies to cue-derived gold only. The old unscoped rule
would have failed the T3 gate on the first human label the cues did not
anticipate — the most valuable evidence in the set read as a defect.

## Upstream issues filed this session

| # | state | what |
|---|-------|------|
| claude-arsenal#161 | **closed, fixed in v0.29.0** | `init.py` corrupted `CLAUDE.md` on every upgrade from a pre-0.27 install |
| claude-arsenal#162 | **closed, fixed in v0.29.0** | `check_update.sh` conflated the subtree prefix with the bundle dir |
| claude-arsenal#163 | open | `github_channel.sh` detects `rest` from a read-only probe, then hard-errors on writes |
| claude-arsenal#166 | open | `merge-policy` has no value for "review required, CI unavailable" |

## Environment

```bash
make lint && make test && make evidence && make verify-subtree && make verify-gates
```

Five gates, all green on `3974c13`: ruff+mypy clean over 86 files, 907 passed,
no evidence drift, 0 diverging subtree assets, 51/51 terminal gates asserted.
Upstream's own suite passes 15/15 against the vendored bundle.
