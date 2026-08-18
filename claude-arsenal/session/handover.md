# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**Plan v2 is written and the queue is reconciled against it.** `status/plan.md`
is now the build order for specification v2; `status/plan-v1.md` keeps the v1
plan unedited as the record of what it planned and why. The whole board — 62
tasks — is in one table with a measurable gate on every row, and a checker
(`jobsearch.plan_v2`, gate `plan_queue_task_drift == 0`) fails if the plan and
the queue ever disagree again.

Read in this order:

1. `status/plan.md` — six layers, the task table by layer, four milestones, the
   risk register, and the reconciliation with v1.
2. `status/spec-v2-process.md` (v2.1) and `status/spec-v2-steps.md` (v1.1) —
   unchanged; the plan builds against them and re-decides nothing.

### The recommended next task

**M1, the spine** — the milestone that makes everything else possible, and the
only one not paced by the [HUMAN] corpus labelling (T5):

| order | task | id | what |
|-------|------|-----|------|
| 1 | S3 | `lo-a4bf` | profile tree, handle resolution, the `PreToolUse` hook |
| 2 | T6 | `lo-e0fa` | append-only evidence log + deterministic rebuild |
| 3 | T35 | `lo-4730` | session state + the five-rule resumption order |
| 4 | T30 → T34 | `lo-c5ad`, `lo-485e` | declared step inputs, then the runtime that reads them |
| 5 | T37 → T36, T39 | `lo-67f4`, `lo-5080`, `lo-99de` | revision + staleness, then triggers and scoring points |
| — | T38, T40, T48 | `lo-dddd`, `lo-da9c`, `lo-bd03` | retraction/deletion, decline ledger, gate-state register |

**S7 is deliberately not next**, and the previous handover recommended it. Each
of its thirteen skills carries a checkpoint *script* that reads session state
and writes gate evidence; none of that exists until T35 and T34 land. S7's
payload now records the dependency.

**T5 (`lo-d2b2`, [HUMAN]) still paces everything measured on the evaluation
split** — `extraction_macro_f1`, `elicitation_eval_overlap`, `rank_spearman` —
and nothing in M1 touches the corpus. The two run in parallel.

## Decisions taken this session

1. **`status/plan.md` is rewritten as v2 rather than added beside v1.** One
   plan, one task table, one namespace; the arsenal seeding protocol reads
   `status/plan.md` by name. v1 is archived at `status/plan-v1.md` with a
   superseded banner and is not to be added to.
2. **Two new layers.** RUNTIME (identity, session state, step graph, freshness,
   revision, retraction, scoring triggers, decline ledger, the step skills) and
   DOCUMENT (the CV store, generated documents, applications, interviews). The
   v1 four-layer architecture had no home for either, which is why fourteen
   process-spec requirements had no task.
3. **Four milestones.** M1 the spine · M2 an L1 ranking end to end · M3 the full
   first run at L2 · M4 per-opportunity documents and interviews. Required steps
   first, so an unbuilt offered step is a declined step rather than a hole.
4. **Fifteen new tasks (T34–T48) and S8.** Seeded with payloads carrying an
   evidence gate each. Nothing was invented to fill the table: every row traces
   to a numbered requirement in the process or step specifications.

Everything in the previous handover's "do not re-litigate" list still stands and
was not touched: the eight owner decisions of 2026-08-17, the three corrections
of 2026-08-18, and the standing constraints on what may leave the machine.

## What was done this session

| artefact | what | gate |
|----------|------|------|
| `status/plan-v1.md` | v1 plan archived unedited, banner added | — |
| `status/plan.md` | plan v2: six layers, 62-row task table, milestones, risks, reconciliation | `plan_queue_task_drift == 0` |
| `src/jobsearch/plan_v2.py` + `tests/test_plan_v2.py` | the drift checker, 11 tests | recorded in `status/evidence/S8.json` |
| queue | 15 new tasks seeded with payloads; 12 existing payloads annotated with their scope change; ledger synced from `arsenal-queue` | `queue_doctor` 0/0/0 |

**Reconciliation, in short.** Refined: T24 (pins the `constraints.json` field
set; gains step 7's reach and legality fields), T27 (owns
`trait_evidence_sufficiency`), T9 (live stimuli, corpus as fallback), T13
(similarity dedup; the hash is the cheap half), T15 (staged, model last;
candidate-independent), T18 (records revision + level), T21 (moves lifecycle
status too), T29 (partly delivered; what remains is the distribution decision),
S4 (narrowed to the store — generation splits to T45), S6 (narrowed — the mock
splits to T47), S3 (narrowed — session state splits to T35), S7 (now depends on
T34/T35). Superseded: the `story_failure_fraction` floor (D-3 reconciles the v1
documents) and the step table in `docs/product-shape.md`.

## The review round on #20

Qodo found three real classes of drift the first draft of the S8 checker could
not see, and each is now measured rather than argued about:

1. **Dependency drift.** The plan's `Depends` cells and the queue's blocking
   `deps` disagreed on 27 edges. `queue_batch.sh` dispatches from the queue
   alone, so **S7 could have been dispatched before T34 and T35** — the exact
   out-of-order build the milestones exist to prevent. Reconciled as the union
   of both sides, cycle-checked, and now gated.
2. **Gate drift.** Eight plan rows named a different metric from the `gate`
   block in the task's own payload — including T32 (`== 0` against `== 1`, a
   polarity flip). The rule now is that **the plan's Gate column mirrors the
   payload**, because `gate_run.sh` executes the payload. S4's payload was the
   one changed instead: its gate moved to T45 with the generation work.
3. **A settled specification contradicted.** The plan had reassigned
   `trait_evidence_sufficiency` to T27; `spec-v2-process.md` §9 and
   `spec-v2-steps.json` assign it to T28. Seeded as **D-4** (`lo-4ca5`) rather
   than edited: §9 names T28 (continuous capture), the two-episode floor that
   produces the measurement is specified in T27, and neither task's own gate is
   the step metric. The plan now records §9's answer and points at D-4.

Also fixed: the checker crashed on a JSONL line parsing to `null`, a list or a
scalar (breaking its own "reports, never raises" contract); it collapsed labels
into sets, so a duplicated row read as agreement; and its column state was
cleared only by a blank line, which made the Evidence-log trap safe by
typography rather than by logic.

Declined, with the reasons already on #7, #9, #12–#18: placeholder gate blocks
on unstarted tasks, a `size` field the queue schema does not carry, docs-and-code
in one change set, and a gate-result field on `merged` rows that `release.sh`
already enforces at the choke point. The inline-numeric-gate rule was declined
too — the prose names which task owns a *step's* metric, and every payload still
carries exactly one fenced gate block.

## Findings worth carrying forward

- **The drift checker read the Evidence log as a task table.** It has a `T#`
  column and a `Gate` column of its own, so its rows satisfied the plan side of
  the check — a task that had been *measured* but never sequenced would have
  scored zero drift, which is the one thing the gate exists to catch. Fixed by
  requiring `Description` in the header, and the test names the reason.
- **The gate column was read by index and every gate looked malformed.** The
  plan groups tasks into one table per layer; the column is found from each
  table's own header now.
- **The default branch's task ledger was nine rows and eight statuses behind**
  `arsenal-queue`. Synced additively (no payload was overwritten — main's
  payload text is newer than the coordination branch's).

## Queue state

63 tasks: 10 merged, 53 open, 0 `in_progress`, 0 `escalated`. S8 is this
round's own row and stays `open` until the orchestrator releases it against
this PR; **D-4** was seeded by the review round.
`queue_doctor.sh`: 0 error, 0 warn, 0 info. New rows are on this feature branch,
so the next orchestrator session must run `queue_sync.sh` to port them onto
`arsenal-queue` before dispatching workers.

## Environment notes that cost time to rediscover

- Pushes go to the designated session branch only, and **GitHub deletes it on
  merge**. After a PR lands: `git fetch --prune origin && git checkout -B
  <branch> origin/main`, then `git branch --unset-upstream`.
- `gh` is unavailable in the cloud session; merge PRs through the GitHub MCP
  tools and flip `done` → `merged` with
  `claude-arsenal/scripts/update_task_row.py`.
- Queue rows authored on a feature branch are invisible to the orchestrator
  until `queue_sync.sh` runs. That is the documented path and the one used here,
  because the coordination branch cannot be pushed from this session.
- `gate_run.sh` takes a **task id**, not a payload path.
- **Regenerate the readers after any spec edit**: `make reader-process` or
  `make reader-steps`. No spec was edited this session, so neither was run.

## Qodo review notes

Three platform rules have been declined with reasons on #7, #9, #12, #13, #15,
#16, #17 and #18 — docs-and-code in one change set, the
`test_<what>_<condition>_<result>` naming convention, and placeholder gate blocks
on freshly seeded tasks. Reuse those arguments rather than re-deriving them; this
PR is the same shape (the plan is the deliverable and the checker exists only to
gate it). Qodo's *bug* findings have been right nearly every time.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12,
T25) cannot be released `done` from here. Ran solo; no worker fan-out.
