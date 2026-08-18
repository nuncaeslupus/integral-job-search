# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**Plan v2 is merged (#20, `548c3a2`) and the queue is ready to be worked.**
Nothing is in flight: no open PR, no `in_progress` task, `queue_doctor` 0/0/0,
`plan_queue_task_drift == 0`.

The intent for the next session is a **long worker-loop run against M1**. Start
it with:

```bash
/continue m1
```

That sets `LOOP_TAGS=m1`, and `queue_batch.sh` then returns only M1's unblocked
tasks. **Do not run a bare `/continue`** for this stretch: the selector orders by
priority alone, so it hands back T29 (M4) and `[LAPTOP]` T25 alongside S3 on the
very first round.

Read before dispatching:

1. `status/plan.md` — six layers, the 63-row task table, four milestones, the
   risk register, the reconciliation with v1, and the Step gate ownership table.
2. `status/spec-v2-process.md` (v2.1) and `status/spec-v2-steps.md` (v1.1) — the
   settled specifications. The plan builds against them and re-decides nothing.

### M1, the spine — what the loop will work through

Ten tasks. The first round returns **S3** (`lo-a4bf`) and **T30** (`lo-c5ad`);
everything else unblocks behind them.

| order | task | id | what |
|-------|------|-----|------|
| 1 | S3 | `lo-a4bf` | profile tree, handle resolution, the `PreToolUse` guard |
| 1 | T30 | `lo-c5ad` | declared step inputs/outputs, required-subset closure |
| 2 | T6 | `lo-e0fa` | append-only evidence log + deterministic rebuild |
| 3 | T35 | `lo-4730` | session state + the five-rule resumption order |
| 4 | T34 | `lo-485e` | the step graph runtime, and L0/L1/L2 |
| 4 | T37 | `lo-67f4` | profile revision + staleness across the three classes |
| 5 | T36 | `lo-5080` | freshness triggers, each an offer and never an action |
| — | T38, T40, T48 | `lo-dddd`, `lo-da9c`, `lo-bd03` | retraction/deletion, decline ledger, gate-state register |

**T39** (scoring triggers, `lo-99de`) is *not* in this run. It depends on T37,
which is M1, but the plan schedules it in **M3** alongside the traits and
weights it exists to pace — there is nothing to defer scoring of until they
exist. `/continue m1` will not return it, and that is correct.

**Why M1 first.** It is the only milestone not paced by T5 (`lo-d2b2`,
`[HUMAN]` corpus labelling), which gates everything measured on the evaluation
split — `extraction_macro_f1`, `elicitation_eval_overlap`, `rank_spearman`.
Nothing in M1 touches the corpus, so the spine and the labelling run in
parallel.

**S7 is deliberately not next**, and an older handover recommended it. Its
thirteen skills each carry a checkpoint *script* that reads session state and
writes gate evidence; none of that exists until T35 and T34 land. The queue now
enforces this — S7 blocks on `lo-485e` and `lo-4730` as well as S2r.

## Before the first dispatch

1. `export ARSENAL_QUEUE_DIR="$(claude-arsenal/bin/queue_branch.sh)"` — the
   coordination worktree is at `/home/user/job-search-arsenal-queue-wt` and
   **pushes to `arsenal-queue` work from a cloud session** (verified this
   session, four pushes).
2. `queue_sync.sh` is **already done** for the v2 round. Note its one limit,
   which cost time here: it ports rows that are *absent*, and never updates a
   row that already exists. The dependency reconciliation therefore did not
   travel with it and had to be ported by hand — if a future round changes
   `deps`, `status` or `tags` on existing rows on main, port those fields
   explicitly.
3. The main working tree must be clean before the loop starts, and must stay
   clean while it runs — `worker_postcheck.sh` is destructive by design.
4. `worktree_probe.sh` reports **available** here, so dispatch a lone first
   worker and check the postcheck result before ramping to `ARSENAL_MAX_WORKERS`.

## Decisions taken — do not re-litigate

All of the owner's earlier decisions stand untouched: the eight of 2026-08-17,
the three corrections of 2026-08-18, and the standing constraints on what may
leave the machine (profile store never sent as-is, per-use approval for story
episodes, no autonomous outward action, advert text only to a model, connectors
are data and never credentials, `profiles/` gitignored, unknown ≠ satisfied).

From the planning round (#20):

1. **`status/plan.md` is the v2 plan**; `status/plan-v1.md` is the archived v1
   and is not to be added to.
2. **Six layers.** RUNTIME and DOCUMENT are new — a process specification needs
   a process engine, and generated documents rebuild under different rules from
   a derived profile.
3. **The plan's Gate column mirrors the payload's `gate` block.** `gate_run.sh`
   executes the payload; the plan is what a human reads. A disagreement is drift
   and fails S8's gate.
4. **Milestones are queue tags** (`m1`…`m4`, `cross`), because the selector
   orders by priority and knows nothing about build order.
5. **A settled specification is never overridden from the plan.** Where the work
   disagrees with it, seed a `D-N` divergence — which is what **D-4** is.

## Open questions for the owner

- **D-4** (`lo-4ca5`): `spec-v2-process.md` §9 assigns `trait_evidence_sufficiency`
  to T28 (continuous capture); the two-episode floor that produces the
  measurement is specified in T27 (the interview protocol); and neither task's
  own gate is the step metric. Three candidate fixes are in the payload. The
  same shape holds for `constraint_field_resolution` (T24 owns it, T41 resolves
  the fields), so a decision here probably settles both.
- **T29** (`lo-2293`): the distribution question at process spec §11.5 is still
  open. It blocks nothing today and blocks everything the first time someone
  other than the owner installs this.

## What was done this session

| PR | what | gate |
|----|------|------|
| #20 | plan v2, 63-row task table, 16 new tasks, 12 payload scope notes, queue reconciled | `plan_queue_task_drift == 0` |

Post-merge, on `arsenal-queue`: the 17 new rows synced, the 16 reconciled
dependency edges ported by hand, payload scope notes copied across, S8 released
`merged`, and every task tagged with its milestone.

## Findings worth carrying forward

- **`queue_sync.sh` only ports absent rows.** The v2 dependency reconciliation
  sat on main while `queue_batch.sh` — which dispatches from `arsenal-queue`
  alone — still had S7 blocked only on S2r. A plan that reconciles the queue is
  not reconciled until the coordination ref carries it.
- **A drift checker that compares membership is not comparing agreement.**
  Review found 27 dependency edges and 8 gate metrics disagreeing between the
  plan and the queue while the first draft of `plan_queue_task_drift` reported
  zero. It now measures membership, gate and dependency.
- **The Evidence log has a `T#` column and a `Gate` column**, so a plan parser
  reads it as a task table unless it also requires `Description` — and a task
  that was *measured* but never sequenced would then score zero drift.
- **`gate_run.sh` takes a task id, not a payload path.**
- Regenerate the readers after any spec edit: `make reader-process` or
  `make reader-steps`. No specification was edited this session.

## Queue state

63 tasks: 11 merged, 52 open, 0 `in_progress`, 0 `escalated`. `queue_doctor.sh`
0 error, 0 warn, 0 info. No open PRs.

By milestone: **m1** 10 · **m2** 16 · **m3** 14 · **m4** 10 · **cross** 3.
Also tagged: `human` (T5, T20) and `laptop` (T4b, T12, T25).

## Environment notes that cost time to rediscover

- Pushes go to the designated session branch **and** to `arsenal-queue`; both
  work. GitHub deletes the session branch on merge — afterwards
  `git fetch --prune origin && git checkout -B <branch> origin/main`, then
  `git branch --unset-upstream`.
- `gh` is unavailable in the cloud session. Merge PRs through the GitHub MCP
  tools and flip `done` → `merged` with
  `claude-arsenal/scripts/update_task_row.py <id> merged <queue> <pr> ""`.
- A cloud session (`CLAUDE_CODE_REMOTE=true`) cannot release a `laptop`-tagged
  task `done` — T4b, T12, T25. `[HUMAN]` tasks T5 and T20 carry
  `requires: surface:human`, so the selector never returns them.
- `gate_run.sh` runs with a hardened PATH that has no `uv`, so tests needing it
  skip there and run under `make test`. Check the skip count.

## Qodo review notes

Its **bug** findings have been right nearly every time, including the three that
reshaped #20. Its **platform-rule** findings have been declined with reasons on
#7, #9, #12–#18 and #20, consistently: docs-and-code in one change set (the
document is the deliverable and the checker exists only to gate it); the
`test_<what>_<condition>_<result>` naming convention; placeholder gate blocks on
freshly seeded tasks; a `size` field the queue schema does not carry; and a
gate-result field on `merged` rows that `release.sh` already enforces at the
choke point. Reuse those arguments rather than re-deriving them.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`). `worktree_probe.sh`: **available**.
Ran solo; no worker fan-out this session.
