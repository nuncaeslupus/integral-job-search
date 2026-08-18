# Session handover — 2026-08-18

## State

| | |
|---|---|
| Board | 45 merged · 1 done (D-9, pending #30) · 27 open |
| Open PR | **#30** (D-9) — CI running at handover, Qodo reviewing |
| Branch | `claude/spec-2-implementation-44lflb`, clean, pushed |
| Merged this session | #24–#29 |

## Next actions

1. **Drive #30 to green and merge.** Then reset the branch from main
   (`git fetch origin main && git checkout -B claude/spec-2-implementation-44lflb origin/main`
   — the remote branch is deleted on merge, so push fresh rather than force-pushing)
   and flip `lo-6c2f` to `merged`.
2. **S12 (`lo-9261`) is then the last cloud-doable task.**
3. Dispatch **ONE** worker only — see the isolation note below.

## Owner-blocked (not dispatchable)

- **T29** (`lo-2293`) — product-shape decision
- **T5** (`lo-d2b2`) — `[HUMAN]` corpus labelling
- **T25** (`lo-1af2`), **T12** (`lo-277b`) — `[LAPTOP]`
- **S10** (`lo-5efb`), **S11** — wait on upstream claude-arsenal #143

## Traps this session actually hit — read before repeating them

- **`isolation: worktree` does not work here.** Workers report the
  orchestrator's own `git rev-parse --show-toplevel`. One worker at a time;
  never `git add -A` while one is running. Every git problem this session
  traced to two things sharing one tree — including a worker that reverted an
  orchestrator commit believing it was stray automation.
- **`tasks.jsonl` has mixed formatting**: 69 rows compact (`"id":"x"`), 4
  spaced (`"id": "x"`). A compact-only pattern edit **silently no-ops and
  reports success**; re-serialising the whole file reformats all 73 lines for a
  1-line change. Parse per line, preserve that line's own separators.
- **Use `get_check_runs`, not `get_status`.** Actions populates check runs;
  `get_status` returns `total_count: 0` regardless. Misread twice.
- **Check Qodo findings against current HEAD.** It reviews the cumulative diff
  and re-surfaced an already-fixed finding on #28.
- **Verify workers, don't trust reports.** The T50 worker claimed 3 tests went
  red; the real number was 6. Correct direction, understated.

## Known gap worth a task

`plan_v2.measure()` checks that plan and queue agree on **which tasks exist and
what they depend on** — it caught D-9 twice during seeding. It does **not**
check that a row's Step number matches `spec-v2-steps.json`, nor that an open
task appears in a milestone list. Both slipped past it on #29 and were caught by
review instead. The plan states outright that "every open task appears in
exactly one milestone", so it is mechanically checkable. Not seeded yet —
deliberately, to avoid folding it into an unrelated PR.

Note the Step column is **0-indexed**: `identify`=0, `intake`=1, `constraints`=2,
`history`=3, `traits`=4, `reactions`=5.

## Upstream issues filed (claude-arsenal), all open

- **#142** — session protocol only reads the queue, so open GitHub issues are
  invisible work *(the user's own request)*
- **#143**, **#144** — earlier findings
- **#145** — `queue_doctor` never opens a payload, so a gateless `done` is
  invisible to the audit
- **#146** — two incompatible `priority` conventions; the rank floor sits above
  the size ceiling, so rank-encoded tasks unconditionally outrank size-encoded
  ones in `queue_batch.sh`
- **#147** — `worker_postcheck.sh` infers isolation from "HEAD didn't move"; its
  false positive records `available`, which is what *enables* parallel fan-out
