# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Last task

- **ID**: lo-2774
- **Title**: T3: Dimension model v0 — 20–25 dimensions with ES/EN/CA cues and elicitation questions
- **Status at handover**: done (PR #8 open; flips to `merged` on landing)

## What was done this session

Cloud session, serialised in-place (no worker fan-out). The coordination branch
`arsenal-queue` did not exist on the remote and was created by `queue_branch.sh`;
`queue_sync.sh` ported the task rows from `main`.

**T2 (`lo-3f5e`) — merged, PR #7.** `src/jobsearch/dimensions.py`: the §5.1
dimension contract as strict Pydantic models (unknown keys refused), all three
corpus languages required on labels and question texts, cue regexes compiled at
load, cue values bounded by polarity, and `methods_ref` resolved against the real
headings in `docs/METHODS.md` — the mechanism T22's `undocumented_methods == 0`
will rest on. Two entry points by design: `load_dimensions` raises,
`collect_violations` counts. Qodo raised four findings; three were fixed in
b3d5358 (anchor resolution was opt-in on the default load path; `OSError` /
`UnicodeDecodeError` escaped the "never raises" audit path; a duplicated
`LANGUAGES` tuple had already drifted from `jobsearch.corpus`). The fourth — a
compliance rule against mixing a task payload edit with implementation — was
declined with reasons on the thread: the payload's placeholder gate command is
the task's deliverable, and splitting it would leave `main` in a state where the
gate measures absent code or passes on a placeholder.

**T3 (`lo-2774`) — done, PR #8 open.** 22 dimensions in `dimensions/*.yaml`,
written against the 100 real ads from T4b. Each carries a behavioural question
and extractor cues in es/en/ca, plus ≥1 gold example: a verbatim ad excerpt
verified byte-for-byte by `verify_gold`. Schema additions are additive
(`extraction.gold`, `dimension_extractor_coverage`).
Gate: **1.0** ≥ 0.90 over 22 dimensions, 56 gold examples, 0 gold violations.
`dimensions/README.md` documents the model and the gold provenance caveat.

## What remains

- **PR #8 needs to land.** Qodo review was in progress at handover. Once merged,
  flip `lo-2774` to `merged` (`update_task_row.py`, or `reconcile_merged.sh` if
  `gh` is available — it is not in the cloud session).
- **D-2 (`lo-77a6`) seeded on `arsenal-queue`, not yet on `main`.** The v0 gold
  examples are cue-derived: each span was found by searching the corpus for text
  the dimension's own cues already match. They are real, but not independent, so
  `extraction_macro_f1` (T15) must be measured against T5's hand labels only.
  The row and payload live on the coordination branch; port them to `main` in a
  housekeeping commit.
- **Next unblocked**: T4 (`lo-e16f`, ONTOLOGY, corpus harness), T6 (`lo-e0fa`,
  PROFILE, profile store), T11 (`lo-5c8c`, SUPPLY, offer schema). T5 is `human`
  tagged and gated on T3+T4; T12 is `laptop` tagged.

## How to continue

1. Read `claude-arsenal/AGENTS.md` for the worker loop algorithm.
2. `export ARSENAL_QUEUE_DIR="$(claude-arsenal/bin/queue_branch.sh)"`, then
   `claude-arsenal/bin/queue_eval.sh`.
3. Branch constraint in this environment: pushes go to the designated session
   branch only, and GitHub deletes it on merge — after a PR lands, run
   `git fetch --prune origin && git checkout -B <branch> origin/main` before the
   next task, or the next push fails with a stale-info rejection.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12)
cannot be released `done` from here. `gh` is unavailable; GitHub work goes
through the MCP tools. `worktree_probe.sh` reported `available`, but the loop ran
serialised in-place rather than fanning out workers.

## Queue snapshot at handover

25 tasks — 3 merged (T1, T4b, T2), 1 done (T3, PR #8), 21 open.
`queue_doctor.sh`: 0 error, 0 warn, 0 info.
