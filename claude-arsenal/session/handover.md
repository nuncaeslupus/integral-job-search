# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Last task

- **ID**: lo-e16f
- **Title**: T4: Corpus harness — ad store, labelling CLI, split assignment, self-agreement report
- **Status at handover**: merged (PR #9)

## What was done this session

Cloud session, serialised in-place (no worker fan-out). The coordination branch
`arsenal-queue` did not exist on the remote and was created by `queue_branch.sh`;
`queue_sync.sh` ported the task rows from `main`. Three tasks completed, three
PRs merged, each through a Qodo review round.

**T2 (`lo-3f5e`) — merged, PR #7.** `src/jobsearch/dimensions.py`: the §5.1
dimension contract as strict Pydantic models, all three corpus languages
required on labels and question texts, cue regexes compiled at load, cue values
bounded by polarity, and `methods_ref` resolved against the real headings in
`docs/METHODS.md` — the mechanism T22's `undocumented_methods == 0` rests on.
`load_dimensions` raises; `collect_violations` counts. Review fixed three:
anchor resolution had been opt-in on the default load path; `OSError` /
`UnicodeDecodeError` escaped the "never raises" audit path; a duplicated
`LANGUAGES` tuple had already drifted from `jobsearch.corpus`.

**T3 (`lo-2774`) — merged, PR #8.** 22 dimensions in `dimensions/*.yaml`, built
against the 100 real ads. Each carries a behavioural question and cues in
es/en/ca plus ≥1 gold example verified verbatim against the ad it cites.
Gate `dimension_extractor_coverage` = **1.0** over 22 dimensions, 56 gold.
Review found eight cues matching a *word* without requiring it applied to the
role or employer — and since the v0 gold was mined from cue hits, each bad cue
shipped with a gold example demonstrating its own error. All corrected against
the full ad text. Two checks now keep the class visible: `unmatched_gold`, and
`language_slices_with_no_corpus_hit` in the evidence (11 of 66 slices are
silent, mostly because the Catalan ads are public-sector/health IT).

**T4 (`lo-e16f`) — merged, PR #9.** `src/jobsearch/harness.py`: labelled store
(`corpus/labelled/ads.jsonl`, 100 ads, unlabelled), stratified stable splits,
labelling CLI, Cohen's-kappa self-agreement, and
`corpus_harness_roundtrip_loss` = **0**. Two defects found while building:
per-ad hash splitting had put 1 of 15 Catalan ads in evaluation (now 30/30 ES,
12/13 EN, 7/8 CA), and kappa needed to report *undefined* rather than 1.0 when
both passes use one category. Review found five more, the worst being that
`_cmd_init` preserved labels but not splits — the stability guarantee was true
of `assign_splits` and false of the command anyone actually runs.

## What remains

- **D-2 (`lo-77a6`) is on `arsenal-queue` only, not on `main`.** The v0 gold
  examples are cue-derived, so `extraction_macro_f1` (T15) must be measured
  against T5's hand labels alone. Port the row and payload to `main` in a
  housekeeping commit.
- **T5 (`lo-d2b2`, `human` tag) is now fully unblocked** — dimensions, splits
  and a labelling CLI all exist. It is the pacing item for every extraction and
  ranking gate. Start with `uv run python -m jobsearch.harness next`.
- **Next unblocked for a worker**: T6 (`lo-e0fa`, PROFILE, profile store),
  T11 (`lo-5c8c`, SUPPLY, offer schema). T12 is `laptop`-tagged.
- **Two Qodo findings were declined, both on the same platform rule**
  (2730555, housekeeping vs implementation): replacing a task payload's
  placeholder gate command is the task's deliverable, and splitting it from the
  code it measures would leave `main` with a gate that measures absent code or
  passes on a placeholder. Reasoning is on the threads of #7, #8 and #9. A
  test-naming convention (2730732) was also declined as inconsistent with the
  repo's existing test names, several of which `status/plan.md` fixes verbatim.

## How to continue

1. Read `claude-arsenal/AGENTS.md` for the worker loop algorithm.
2. `export ARSENAL_QUEUE_DIR="$(claude-arsenal/bin/queue_branch.sh)"`, then
   `claude-arsenal/bin/queue_eval.sh`.
3. Branch mechanic in this environment: pushes go to the designated session
   branch only, and GitHub deletes it on merge. After a PR lands run
   `git fetch --prune origin && git checkout -B <branch> origin/main` before the
   next task, or the next push is rejected with stale-info.
4. `gh` is unavailable here, so `reconcile_merged.sh` cannot run; flip
   `done` → `merged` with `claude-arsenal/scripts/update_task_row.py` and commit
   on the coordination branch.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks (T4b, T12)
cannot be released `done` from here. GitHub work goes through the MCP tools.
`worktree_probe.sh` reported `available`, but the loop ran serialised in-place
rather than fanning out workers.

## Queue snapshot at handover

25 tasks — 5 merged (T1, T4b, T2, T3, T4), 20 open.
`queue_doctor.sh`: 0 error, 0 warn, 0 info.
