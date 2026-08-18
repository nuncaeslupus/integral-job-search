# Session handover — 2026-08-18

## State

**Board: 47 merged, 26 open. No open PRs. The cloud-doable queue is empty.**

Every remaining unblocked task is gated on the owner:

| task | id | blocker |
|------|-----|---------|
| T29 | `lo-2293` | product-shape decision — plugin packaging, phasing |
| T5  | `lo-d2b2` | `[HUMAN]` — label the collected ads |
| T25 | `lo-1af2` | `[LAPTOP]` — broaden the corpus |
| T12 | `lo-277b` | `[LAPTOP]` — live portal connector |
| S10 | `lo-5efb` | upstream `claude-arsenal#143` (hardcoded LISTING_BUDGET_CHARS) |

Nothing is claimable by a cloud session. Do not seed make-work; ask the owner.

## Merged this session

| PR | tasks |
|----|-------|
| #28 | S4 (CV store), D-8 (evidence subject) |
| #29 | T50 (intake capture driver) |
| #30 | D-9 (non-insistence on the intake write path) |
| #31 | S12 (free-text capability in the step model) |

## What this session was actually about

One theme, found four separate times: **a green check that had stopped
measuring anything.**

- A task recorded `done` whose payload carried no fenced ` ```gate ` block, so
  `verify_gates.py` skipped it — 38 of 39 asserted, invisible in a green run.
  All 47 now carry one.
- `cv_store.py` was the only free-text writer never consulting `DeclineLedger`,
  so a declined subject was recorded anyway (D-9). The gate above it read 1.0
  throughout.
- The S12 gate counted only *absent* declarations, on the documented grounds
  that a non-boolean would already have failed loading. Pydantic's lax `bool`
  made that false — `"yes"` became a declaration, `2` did not, so exactly the
  values that look deliberate got through.
- `D3.json` pins a citation by line number into `spec-v2-steps.md`. A three-line
  note shifted it. Every per-task gate and `verify_gates.py` passed; only
  `make evidence` caught it.

**Lesson for the next session: run `make evidence` before every push.** The
per-task gates each assert their own metric and none of them notices a prose
edit moving a number another task recorded. It is not covered by
`verify_gates.py`.

## Divergences seeded, not left in prose

D-9 (`lo-6c2f`) was found while wiring T50 and seeded as a queue task + plan row
before it could be forgotten. Both fixed and merged in #30.

## Traps that cost time — read before touching these

1. **`claude-arsenal/queue/tasks.jsonl` has mixed formatting** — 69 rows compact
   (`"id":"x"`), 4 spaced (`"id": "x"`). A compact-only sed pattern *silently
   no-ops*; re-serialising the whole file reformats all 73 lines. Parse each
   line and preserve that line's own separators.
2. **`isolation: worktree` does not work on this surface**, and not in the way
   the arsenal docs describe. Worktrees *are* created — 17 accumulated under
   `.claude/worktrees/` this session — but workers run in the main tree anyway
   (`git rev-parse --show-toplevel` returns the orchestrator's root). So:
   **one worker at a time**, and **never `git add -A` while one is running**.
   Filed upstream as `claude-arsenal#147` with the evidence.
3. **A worker once reverted an orchestrator commit**, believing it was stray
   automation. Worker prompts now say explicitly: do not run git write commands.
4. **The plan's Step column is 0-indexed** against `spec-v2-steps.json`
   (`identify`=0, `intake`=1 … `reactions`=5). A task's *priority* is not its
   step; conflating them put D-9 on the wrong step until review caught it.
5. **`plan_v2.measure()` checks existence and deps only.** It does not check
   that a Step number matches the step register, or that an open task reaches a
   milestone list — review caught both. Worth widening; not done.

## Upstream issues filed (all open)

`claude-arsenal` #142 (the owner's own request: the queue should read GitHub
issues, since stacked issues get forgotten), #143, #144, #145 (`queue_doctor`
never opens a payload, so a gateless `done` is invisible), #146 (two
incompatible `priority` conventions — 26 of 72 rows are build-order rank, whose
floor outranks the size convention's ceiling, so dispatch order reflects
authorship date), #147 (worktree isolation false positive, with the evidence in
point 2).

## Next action

Ask the owner which of T29 / T5 / T25 / T12 they want to unblock. T29 is the
only one that needs a decision rather than hardware or labelling time, and it
gates the M4 remainder.
