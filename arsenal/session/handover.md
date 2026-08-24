# Session handover — 2026-08-24, the rename tidied and three PRs landed

A worker session on the laptop, following the human sitting recorded in the
previous handover. Three PRs merged; the queue is now empty of anything a worker
can take.

## What merged

| PR | What | Gate |
|---|---|---|
| #159 | `make test` runs the `collect` extra | — (7 tests stopped skipping) |
| #158 | T26b — the four candidate-trait dimensions | `trait_dimensions_ready = 4 >= 4` |
| #160 | D-19 — a silent vocabulary is refused, not reported as understanding | `markets_with_no_applicable_dimension_reported_as_extracted == 0` |

Board: 97 tasks — **open 4, claimed 0, merged 90**. `make host-gate` green on `main`.

## The rename, finished

The owner moved the clone to `~/dev/integral-job-search`. Three things it left:

- **Six worktrees**, all clean with every branch pushed. Deleted; branches kept.
  `git worktree repair` was a no-op — paths already resolved.
- **The main tree was on a detached HEAD** at the tip of `connectors-sources-repo`,
  19 commits behind `origin/main`. Returned to `main`.
- **`.venv` console scripts still carried an absolute shebang pointing at the
  pre-rename directory**, which no longer exists. `uv run pytest` was silently
  falling through to system Python 3.14 instead of the venv's 3.12, so the whole
  suite looked broken. Recreated the venv with `rm -rf .venv && uv sync`.
  **If a future session sees a mass ImportError, run `head -1 .venv/bin/pytest`
  and check it points inside this checkout, before believing the diff.**

## The queue is blocked on people and data, not code

All four open tasks. None is workable by a worker today:

| Task | Blocker, measured 2026-08-24 |
|---|---|
| T59 (`lo-4b17`) | 2 negated labels, floor 10 |
| T56 (`lo-6f53`) | floor is 10 **per dimension**; all 25 have ≤1 (14 labels total) |
| T57 (`lo-7c14`) | 828 concepts read, none from a source that can report an *unmapped* one |
| T20 (`lo-c48f`) | `requires: [surface:human]` — the candidate personally |

**T59, T56 and T57 unblock on one labelling round.** That round is the highest-value
thing anyone can do for this repo right now: it is the single input three gates wait on.

The selector still offers T59 first. It is not workable — its dep resolves, but its
*data* does not. Do not claim it expecting to finish it.

## D-21 is masking D-19, and that ends when T56 lands

Step 8's acceptance gate (`extraction_macro_f1 >= 0.75`, owned by T56) is
`not_implemented`, so `checkpoint_exit` already returns 3 rather than 0 for that
checkpoint — for a reason unrelated to D-19. The day T56 builds that gate, the
masking disappears.

So D-19's refusal (`step_gates.VOCABULARY_SILENT`, exit 4) is asserted
**independently of gate state**, and that independence is one of its gate's own
claims. Removing the two-line refusal makes the gate report 2, naming exactly this.
Nothing needs doing now; it is why the fix was written the way it was.

## A finding about the dimension model's reach

`markets_with_no_applicable_dimension_reported_as_extracted` measures reach per
`job_family` over the committed corpus. Measured now:

| family | ads | ads reached | applicable dimensions |
|---|---|---|---|
| programming | 100 | 96 | 23 |
| healthcare | 18 | 14 | 10 |
| administrative | 18 | 14 | 9 |
| teaching | 18 | 13 | 9 |
| retail | 18 | 17 | 8 |
| hospitality | 18 | 10 | 6 |
| trades | 18 | 11 | 5 |

**No family has zero reach — trades included.** D-19's "0 of 25 on seven construction
adverts" was on *live sourced* offers; T25 added the trades corpus slice afterwards,
and against that slice the model does reach. The refusal is therefore a guard that
does not currently fire, which is why a broken refusal counts toward the metric on
its own — otherwise the zero rests on the corpus happening to be covered.

The market, not the advert, is the unit: 33 of 208 individual ads settle nothing at
the rules stage, which is ordinary — stage 3 asks a model for the rest.

## A claude-arsenal bug, filed — and the workaround it forces

**`nuncaeslupus/claude-arsenal#217`.** A task filed with the fail-on-purpose
placeholder gate command **cannot open its own PR**. `open_task_pr.sh` runs the gate
with `ARSENAL_GATE_FROM_DEFAULT=1`, reading the task file from `main` — correctly, so
a worker cannot certify itself — but on `main` the `bash` block is still the
placeholder that exits 1. Only the refused PR can replace it.

Both T26b and D-19 hit this. **Both PRs were opened by hand**, on the owner's
instruction: archive the task file to `_history/` with `status: merged`, put
`Closes #<issue>` in the commit message *and* the body, run `make host-gate` locally
first, then `gh pr create`. The gate *assertion* block was unchanged from `main` and
passed against it in both cases; only the regenerator command was missing.

`ARSENAL_ALLOW_UNLINKED_PR=1` is **not** the answer — it opens a PR that closes
nothing. Landing the gate command in a prerequisite PR is not either, while
`merge-policy` is `after-review`.

## Decisions settled this session, not to relitigate

- **D-19 is an honest refusal, not a sector-scoped dimension set.** Widening was
  already retired by the owner's 2026-08-19 scope change — dimensions are coined
  when a live session turns one up, not by a corpus sweep. The refusal was built;
  the coining conversational path was deliberately *not*, and is not filed.
- **`VOCABULARY_SILENT` gets its own exit code (4).** Reusing D-21's `UNCERTIFIABLE`
  would conflate "the gate nobody built" with "the gate is fine and the words do not
  fit this trade" — owed by different people.
- **Presence and reach stay separate.** An extraction that settled nothing is not a
  missing artefact; reporting it absent would read as "still working".
- **Trait dimensions are excluded from ad-side reporting.** Four whole-model tests
  and two evidence fields (`T3.dimensions_without_cues_or_gold`,
  `T5.dimensions_without_labels`) were scoped to `ad_side()`, because a trait can
  never close those gaps. `T15.dimensions_below_floor` was already ad-side, so T56's
  floor cannot be made unsatisfiable by coining a trait.

## Still open elsewhere

- **The arsenal bundle is v2.4.0; v2.4.1 is out.** `check_update.sh --check-only`
  reports it. Not urgent, not done here.
- **CI remains out of runner minutes.** Every job still fails in 3–5s with
  `runner_id: 0` and an empty `runner_name`, on `main` as much as any branch. The
  local `make host-gate` is the real gate. Diagnose once with the `runner_id` check
  before suspecting a diff.
