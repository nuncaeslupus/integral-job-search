# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**Specification v2 is written.** The process (S1, S1r) and all thirteen step
specifications (S2) are done and gated. What remains is the three S-tasks the
specifications describe but do not build, and the T-series they depend on.

Read in this order:

1. `status/spec-v2-process.md` (v2.1) — the process: steps, the dependency
   graph, artefact classes, resumption, offer lifecycle, manner rules.
2. `status/spec-v2-steps.md` — one specification per step, twelve fields each.
3. `status/spec-v2-steps.json` — the same step list, machine-readable.
   `step_count` is 13 and is the divisor any completeness metric must use.

| task | id | what | blocked on |
|------|-----|------|-----------|
| S3 | `lo-a4bf` | Multi-user tree, identify-at-session-start, session state | — |
| S4 | `lo-cb1c` | CV store: import pdf/docx, build-from-nothing, per-ad generation | — |
| S5 | `lo-a95d` | Offer lifecycle: status, purge, tombstones, retention | — |
| S6 | `lo-1f98` | Interview: preparation, then the log and its lessons | — |
| T30 | `lo-c5ad` | Step inputs/outputs in JSON, gated on required-subset closure | S2 |
| T31 | `lo-eb2d` | Detect note-key rebinding when spec sections renumber | — |

S3/S4/S5 were seeded before the specifications existed and now have step
specifications to build against: S3 is step 0, S4 is steps 1 and 11, S5 is the
retention and purge rules in `spec-v2-process.md` §7 plus step 7. Their payloads
predate that and should be read alongside the step specs, not instead of them.

**If the owner wants code rather than more specification**, T24 (candidate
attributes), T6 (profile store) and T11 (offer schema) are unblocked and are
what S3–S5 rest on. **T5 remains `[HUMAN]`** and still paces every extraction
and ranking gate.

## Decisions taken this session — do not re-litigate

From the owner, 2026-08-17:

1. **Intake and Constraints stay separate.** Constraints is confirm-and-fill:
   it consumes what Intake inferred and asks only what a CV cannot state.
2. **Traits is its own step** — and the tool must notice on its own when what it
   knows has aged, and reopen the right earlier step.
3. **No automatic early ranking.** The default is the full first run, explained,
   with an *offered* skip to a provisional search. The candidate elects it.
4. **Reactions is its own onboarding step**, with stimuli fetched live from
   multiple sources. The corpus is fallback, not primary.
5. **Purge at 60 days** for an advert never shortlisted.
6. **Identification is a handle the candidate chooses**, confirmed by display
   name later. Not a legal name.
7. **Cross-profile deletion is permitted** after confirming the target by name.
8. **Five steps are required** — Identify, Constraints, Sourcing, Understanding,
   Ranking. The other eight are offered.

Decided by me and flagged in the documents as mine, so they can be overturned:
the two-episode/two-occasion trait floor; retraction rows rather than deletion
for a single fact; revival of a tombstoned offer; the per-step hard caps (marked
as first settings, not findings); the 20-row batch threshold for trait scoring.

**The non-insistence rule outranks every coverage target** (process §5.4): when
cooperation drops, stop asking. Better a worse job than a person who felt
interrogated. Marking five steps required is what makes it safe to obey rather
than merely kind.

## What was done this session

| PR | task | what | gate |
|----|------|------|------|
| #15 | S1 | the whole process: 13 steps, connections, tree, lifecycle, resumption | `process_spec_complete` 1 |
| #16 | S1r | the owner's 16 review annotations folded in | `process_spec_complete` 1 |
| #17 | S2 | thirteen step specifications, twelve fields each | `step_specs_complete_fraction` 1.0 |

**#15 and #16 are merged. #17 is open, clean, and Qodo-green** — it was left for
the owner to merge rather than self-merged.

Findings worth carrying forward, because each survived a green check:

- **The required-only path was broken in the PR that introduced the graph.**
  Constraints is required and read `claimed facts`, which only the *offered*
  Intake produces — so the first candidate to decline Intake, the person with no
  CV, hits a required step with a missing input. Optional inputs are marked `?`
  now, and the closure property is stated in both §2.5 and §3.1. **T30 makes it
  mechanical**; until then it is prose and can rot.
- **`steps_with_named_gate_metric` restated its own denominator** — hardcoded to
  `step_count`, so the field meant to say *which* step lacks a metric would have
  said all of them had one.
- **The S2 checker promised "Reports, never raises" and did not.** A malformed
  step list produced a traceback and no evidence file — indistinguishable from a
  run that never happened.
- **Two `## Step N` headings collapsed to the second one.** A duplicate whose
  earlier copy was a stub still scored 13/13.
- **A renumbered section silently re-bound the owner's note** to a section they
  had never commented on. Fixed by hand; T31 makes it detectable.

## Queue state

41 tasks: 8 merged, 1 done (S2, pending #17), 32 open. `queue_doctor.sh`:
0 error, 0 warn, 0 info.

## Environment notes that cost time to rediscover

- Pushes go to the designated session branch only, and **GitHub deletes it on
  merge**. After a PR lands: `git fetch --prune origin && git checkout -B
  <branch> origin/main`, then `git branch --unset-upstream`, or the next push is
  rejected.
- `gh` is unavailable in the cloud session. Flip `done` → `merged` with
  `claude-arsenal/scripts/update_task_row.py` and commit on `arsenal-queue`.
- Queue rows live on `arsenal-queue`; a task authored on a feature branch is
  invisible to the orchestrator until mirrored there.
- `gate_run.sh` runs with a hardened PATH that has no `uv`, so the reader
  staleness test skips under it and runs under `make test`. That is the
  `skipif` doing its job, not a silent hole — but check the skip count.
- **Regenerate the readers after any spec edit**: `make reader`. A test fails if
  you forget, which is the only reason this is not a recurring trap.

## Qodo review notes

Three platform rules have been declined with reasons, consistently, and Qodo now
reports them as previously rejected here: docs-and-code in one change set (the
specification *is* the deliverable and the checker exists only to gate it —
splitting produces a document whose gate cannot run and a checker with nothing to
check); the `test_<what>_<condition>_<result>` naming convention; and placeholder
gate blocks on freshly seeded tasks, where an unwritten gate command is the
honest state of unstarted work. Reuse those arguments rather than re-deriving
them — they are on #7, #9, #12, #13, #15, #16 and #17.

Qodo's bug findings, by contrast, have been right nearly every time this session.
Four of the five real defects above came from it.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12,
T25) cannot be released `done` from here. GitHub work goes through MCP tools.
Ran serialised in-place; no worker fan-out.
