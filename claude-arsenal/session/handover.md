# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**Specification v2 is finished, reviewed twice, and merged.** The process (S1,
S1r) and all thirteen step specifications (S2, S2r) are on `main` at `83032bb`.
Nothing is in flight: no open PR, no `in_progress` task, working tree clean,
`queue_doctor` 0/0/0.

Read in this order:

1. `status/spec-v2-process.md` (v2.1) — the process: steps, the dependency
   graph, artefact classes, resumption, offer lifecycle, manner rules.
2. `status/spec-v2-steps.md` (v1.1) — one specification per step, twelve fields
   each, with the owner's two review rounds folded in.
3. `status/spec-v2-steps.json` — the same step list, machine-readable.
   `step_count` is 13 and is the divisor any completeness metric must use.

### The recommended next task

**S7 (`lo-9ff0`) — one skill per step, thirteen of them**, built with
`skill-creator`, each carrying a checkpoint **script** rather than prose. It was
blocked on S2r and is now unblocked. This is what turns the specification from
something to read into something that runs, and it is why S3–S5 get easier
afterwards: each step gains a checkpoint that says whether it finished.

If the owner wants running code instead, these are unblocked and now have step
specifications to build against:

| task | id | what | maps to |
|------|-----|------|---------|
| S3 | `lo-a4bf` | Multi-user tree, identify-at-session-start, session state | step 0 |
| S4 | `lo-cb1c` | CV store: import pdf/docx, build-from-nothing, per-ad generation | steps 1 and 11 |
| S5 | `lo-a95d` | Offer lifecycle: status, purge, tombstones, retention | process §7 + step 7 |
| S6 | `lo-1f98` | Interview: preparation, then the log and its lessons | step 12 |

They rest on T24 (candidate attributes, `lo-b876`), T6 (profile store) and T11
(offer schema). **T5 remains `[HUMAN]`** and still paces every extraction and
ranking gate.

Smaller open work seeded from the review rounds: **T30** (`lo-c5ad`, make the
required-subset closure mechanical), **T31** (`lo-eb2d`, detect note-key
rebinding), **T32** (`lo-9073`, declarative connector format), **T33**
(`lo-3265`, net-from-gross pay), **D-3** (`lo-ee7d`, reconcile the superseded
`story_failure_fraction` floor in `status/specification.md` and
`docs/METHODS.md`).

## Decisions taken — do not re-litigate

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
   name later. Not a legal name, and it carries no obligation to match the name
   printed on a CV.
7. **Cross-profile deletion is permitted** after confirming the target by name.
8. **Five steps are required** — Identify, Constraints, Sourcing, Understanding,
   Ranking. The other eight are offered.

From the owner, 2026-08-18 (second review round, the three that were corrections
rather than preferences):

9. **Personal details are collected at the point of use, not banned.** Date of
   birth, address and telephone don't improve a *search*, so Intake still doesn't
   ask — but step 11 does, because the document it produces requires them.
10. **The caps were too high.** History 40 → **18**, Intake 25 → **12**, with a
    check-in halfway rather than a march to the cap. The framing is inverted
    throughout: a step ends by saying what the next one buys the candidate and
    asking whether to carry on, not by offering the exit.
11. **History must not over-weight failure.** How someone reached a thing they
    are proud of evidences their traits just as precisely, and is pleasanter to
    tell. The `story_failure_fraction` floor is superseded — both kinds present
    once there are ≥4 episodes, fraction reported not floored. **D-3 reconciles
    the v1 documents**; it was seeded rather than edited silently.

Decided by me and flagged in the documents as mine, so they can be overturned:
the two-episode/two-occasion trait floor; retraction rows rather than deletion
for a single fact; revival of a tombstoned offer; the per-step hard caps (marked
as first settings, not findings); the 20-row batch threshold for trait scoring.

**The non-insistence rule outranks every coverage target** (process §5.4): when
cooperation drops, stop asking. Better a worse job than a person who felt
interrogated. Marking five steps required is what makes it safe to obey rather
than merely kind.

## Standing constraints the specifications encode

These are not preferences; a change to any of them is a change to what the tool
is allowed to be.

- The profile store, `master.json`, `evidence.jsonl` and `stories.jsonl` are
  **never sent anywhere as-is**.
- Story-bank episodes reach an employer-bound document only with **per-use
  approval**.
- **No autonomous outward action.** Nothing applies, emails or contacts an
  employer without explicit per-item approval; the default is to stop one step
  short of sending.
- Extraction sends **advert text only, never profile data**. Relating an offer
  to the candidate happens in a **local annotation pass** writing
  `annotations/<offer_id>.json`.
- Connector files are **data, never code**, and never contain credentials — they
  drive the candidate's own browser session instead.
- `profiles/` stays gitignored. A `PreToolUse` hook should refuse reads and
  writes under another handle's tree (assigned to S3, alongside
  `cross_user_leaks`); it must be written so correct operation never trips it.
- Unknown ≠ satisfied. Evidence is append-only with the profile derived from it.
  `elicitation_eval_overlap == 0`.

## What was done this session

| PR | task | what | gate |
|----|------|------|------|
| #15 | S1 | the whole process: 13 steps, connections, tree, lifecycle, resumption | `process_spec_complete` 1 |
| #16 | S1r | the owner's 16 review annotations folded in | `process_spec_complete` 1 |
| #17 | S2 | thirteen step specifications, twelve fields each | `step_specs_complete_fraction` 1.0 |
| #18 | S2r | the owner's 12 step-spec annotations folded in | `step_specs_complete_fraction` 1.0 |

All four are merged. 11 tasks merged, 35 open.

Findings worth carrying forward, because each survived a green check:

- **The required-only path was broken in the PR that introduced the graph.**
  Constraints is required and read `claimed facts`, which only the *offered*
  Intake produces — so the first candidate to decline Intake, the person with no
  CV, hits a required step with a missing input. Optional inputs are marked `?`
  now, and the closure property is stated in both §2.5 and §3.1. **T30 makes it
  mechanical**; until then it is prose and can rot.
- **`steps_with_named_gate_metric` restated its own denominator** — hardcoded to
  `step_count`, so the field meant to say *which* step lacks a metric would have
  said all of them had one. A gate metric must be counted, never restated.
- **The S2 checker promised "Reports, never raises" and did not.** A malformed
  step list produced a traceback and no evidence file — indistinguishable from a
  run that never happened.
- **Two `## Step N` headings collapsed to the second one.** A duplicate whose
  earlier copy was a stub still scored 13/13.
- **A renumbered section silently re-bound the owner's note** to a section they
  had never commented on. Fixed by hand; T31 makes it detectable.
- **The reader-staleness test found a flaw in itself.** The committed reader
  carries seeded notes, so regenerating into an empty directory diffed against
  itself. It seeds identically now, and was re-verified by editing the source and
  watching it go red.
- **The evidence log cited each PR's base commit, not its merge.** `0a64da9` has
  no `spec-v2-process.md` and `258b2de` has no `spec-v2-steps.md`, so neither row
  could have measured what stood beside it. Corrected, and each row re-verified
  by materialising the commit and running the checker it shipped with.

## Queue state

46 tasks: 11 merged, 35 open, 0 `in_progress`, 0 `escalated`. `queue_doctor.sh`:
0 error, 0 warn, 0 info. No open PRs.

## Environment notes that cost time to rediscover

- Pushes go to the designated session branch only, and **GitHub deletes it on
  merge**. After a PR lands: `git fetch --prune origin && git checkout -B
  <branch> origin/main`, then `git branch --unset-upstream`, or the next push is
  rejected. Local `main` goes stale — it is not the checked-out branch.
- `gh` is unavailable in the cloud session. Flip `done` → `merged` with
  `claude-arsenal/scripts/update_task_row.py <id> merged <queue> "" ""` and
  commit on `arsenal-queue`; merge PRs through the GitHub MCP tools.
- Queue rows live on `arsenal-queue` (worktree at
  `/home/user/job-search-arsenal-queue-wt`); a task authored on a feature branch
  is invisible to the orchestrator until mirrored there.
- `gate_run.sh` runs with a hardened PATH that has no `uv`, so the reader
  staleness test skips under it and runs under `make test`. That is the
  `skipif` doing its job, not a silent hole — but check the skip count.
- **Regenerate the readers after any spec edit**: `make reader-process` or
  `make reader-steps` (not `make reader`, which restamps the document you did
  not touch). A test fails if you forget.

## Qodo review notes

Three platform rules have been declined with reasons, consistently, and Qodo now
reports them as previously rejected here: docs-and-code in one change set (the
specification *is* the deliverable and the checker exists only to gate it —
splitting produces a document whose gate cannot run and a checker with nothing to
check); the `test_<what>_<condition>_<result>` naming convention; and placeholder
gate blocks on freshly seeded tasks, where an unwritten gate command is the
honest state of unstarted work. Reuse those arguments rather than re-deriving
them — they are on #7, #9, #12, #13, #15, #16, #17 and #18.

Qodo's bug findings, by contrast, have been right nearly every time this session.
Most of the real defects above came from it.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12,
T25) cannot be released `done` from here. GitHub work goes through MCP tools.
Ran serialised in-place; no worker fan-out.
