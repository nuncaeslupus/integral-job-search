# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**The job is specification v2, not code.** Read `status/spec-v2-brief.md` first
— it carries the owner's decisions, the requirements they imply, a proposed
twelve-step process to argue with, and the template each step's specification
must fill.

Then work **S1 before S2**: the whole process first, then one specification per
step. A step specified before the process is settled gets the wrong boundaries.
Both are to be delivered as **reviewable HTML documents** (plus Markdown
source), which the owner asked for explicitly.

| task | id | what |
|------|-----|------|
| S1 | `lo-6928` | Whole process: steps, connections, artefact tree, lifecycle, resumption |
| S2 | `lo-aa45` | One spec per step, filling the template (depends S1) |
| S3 | `lo-a4bf` | Multi-user tree, identify-at-session-start, session state |
| S4 | `lo-cb1c` | CV store: import pdf/docx, build-from-nothing, per-ad generation |
| S5 | `lo-a95d` | Offer lifecycle: status, purge, tombstones, retention |

S1 has two questions to settle that the brief deliberately left open: whether
Intake and Constraints merge (a parsed CV answers several constraint questions
already), and whether Traits is its own step or folds into History with its own
coverage requirement.

## Decisions taken this session — do not re-litigate

1. **Several short conversations, one per step**, each with a clear goal and an
   end, and the ability to go back to an earlier step with new information. Going
   back **revises** later outputs rather than discarding them.
2. **Traits update continuously** — with capture (cheap, always on) separated
   from scoring (potentially LLM-backed, at defined points, never per message).
3. **Multi-user from day one.** A directory tree per person; the user is
   identified at the start of every session before anything is read or written.
   A handful of users, not a multi-tenant service.

Also settled earlier and inherited: dimension `side` (T23, merged); unknown ≠
satisfied; evidence append-only with the profile derived; cue-derived gold is
not evaluation data (D-2); the corpus broadens before the model widens.

## What was done this session

Seven PRs, all merged, each through a Qodo review round.

| PR | what | gate |
|----|------|------|
| #7 | **T2** dimension schema, loader, `methods_ref` anchor resolution | `dimension_schema_violations` 0 |
| #8 | **T3** 22-dimension model v0 with ES/EN/CA cues and corpus-verified gold | `dimension_extractor_coverage` 1.0 |
| #9 | **T4** corpus harness: labelled store, stratified splits, labelling CLI, self-agreement | `corpus_harness_roundtrip_loss` 0 |
| #10 | session handover, D-2 ported to `main` | — |
| #11 | scope extension recorded: T23–T28 seeded | — |
| #12 | **T23** dimension `side` — matched / candidate fact / candidate trait | `side_coverage_violations` 0 |
| #13 | dimension catalogue (~100 entries) and product shape | — |

Findings worth carrying forward, because each passed every green check before
someone looked:

- **T3's cues matched words, not claims about the role.** "Startup culture" at a
  1982 multinational scored as early-stage; a staffing marketplace's "product
  teams" as own-product; a required ISTQB certificate as employer-funded
  learning. Eight of them, all with gold examples demonstrating their own error,
  because the gold was mined from cue hits. Coverage read 1.0 throughout.
- **T4's split put 1 of 15 Catalan ads in evaluation.** The aggregate 49/51
  looked healthy. Catalan extraction would have been measured on one ad.
- **T4's `_cmd_init` preserved labels but not splits.** `assign_splits` supports
  stability and a test proved it — but the command nobody could avoid running
  did not pass the argument, so the guarantee was true of the function and false
  of the tool.
- **T23's coverage metric would have penalised traits.** Adding `ambition`
  lowered `dimension_extractor_coverage`, quietly pressuring a future author to
  delete traits to keep a gate green.

## Queue state

37 tasks: 6 merged (T1, T4b, T2, T3, T4, T23), 31 open.
`queue_doctor.sh`: 0 error, 0 warn, 0 info.

Unblocked and machine-workable if the owner wants code rather than specs: T24
(candidate attributes, including the six-part cross-border cluster), T6 (profile
store), T11 (offer schema). **T5 is `[HUMAN]`** and remains the pacing item for
every extraction and ranking gate — dimensions, splits and a labelling CLI all
exist for it now: `uv run python -m jobsearch.harness next --language es`.

## Environment notes that cost time to rediscover

- Pushes go to the designated session branch only, and **GitHub deletes it on
  merge**. After a PR lands: `git fetch --prune origin && git checkout -B
  <branch> origin/main`, or the next push is rejected with stale-info.
- `gh` is unavailable in the cloud session, so `reconcile_merged.sh` cannot run.
  Flip `done` → `merged` with `claude-arsenal/scripts/update_task_row.py` and
  commit on the coordination branch.
- Queue rows live on `arsenal-queue`; new tasks authored on a feature branch
  must be mirrored there or the orchestrator never sees them.
- Qodo re-reviews on every push and marks resolved findings struck through.
  Three of its platform rules were declined with reasons on the threads
  (structured logging for a local gate CLI; a test-naming convention that
  conflicts with names `status/plan.md` fixes verbatim; seeded-task conventions
  where a placeholder gate and a missing evidence file are the point). Those
  arguments are on #7, #9, #12 and #13 — reuse them rather than re-deriving.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12,
T25) cannot be released `done` from here. GitHub work goes through MCP tools.
`worktree_probe.sh` reported `available`, but the loop ran serialised in-place
rather than fanning out workers.
