# Session handover — 2026-08-24, the rename tidied and iterative sourcing designed

A worker session on the laptop, following the human sitting recorded in the
previous handover. Six PRs merged. The queue was empty of worker-takeable work for
most of it; the design pass at the end refilled it.

## Start here — the queue has ten new tasks and T60 is first

`design` ran over `status/specs/iterative-sourcing.md` (#164), producing its
sections 5–6 and the split **T60–T69**. The selector offers **T60** — small, no
deps, `gate: true`. Every other sourcing row depends on it, because a graph edge
nobody traverses is documentation rather than a feature.

Read `status/specs/iterative-sourcing.md` §5 before starting: the contracts are
settled there and several are load-bearing in ways the task titles do not carry
(step 7's new inputs must be `optional: true`; proposal symmetry is enforced in
the type, not in prose).

**T69 is `[HUMAN]`** and carries `requires: [surface:human]`. Its prerequisite is
the exhaustion signal having been *watched on a real cycle*, which a dep on T68
cannot express — a dep resolves when T68 merges. Do not remove `requires` to
unblock the queue.

## What merged

| PR | What | Gate |
|---|---|---|
| #159 | `make test` runs the `collect` extra | — (7 tests stopped skipping) |
| #158 | T26b — the four candidate-trait dimensions | `trait_dimensions_ready = 4 >= 4` |
| #160 | D-19 — a silent vocabulary is refused, not reported as understanding | `markets_with_no_applicable_dimension_reported_as_extracted == 0` |
| #161 | this handover | — |
| #162 | claude-arsenal **v2.4.2** — the placeholder-gate fix this repo filed | — (91 gates still assert) |
| #163 | what the labelling round actually costs | — (docs) |
| #164 | `design` over iterative sourcing: contracts, risks, T60–T69 | — (design) |

Board: 107 tasks — **open 5, claimed 0, blocked 9, merged 90**. `make host-gate`
green on `main`.

## The by-hand PR workaround is over

`open_task_pr.sh` refused any task shipped with the fail-on-purpose placeholder
gate: it reads the gate from the default branch, and only the refused PR could
replace the placeholder. Filed as `claude-arsenal#217`; upstream shipped
`#218` the same day and this repo picked it up in #162.

The assertion still resolves from the default branch — that is what
self-certification would target. Only the ```bash command defers, and only when
the default branch's is the shipped placeholder. **T60–T69 all carry that
placeholder deliberately**, so each implementing PR defines its own measurement
and opens normally.

One gap, reported upstream: detection covers `# arsenal:gate-placeholder` and a
command reducing to bare `false`, but **not** the older
`echo "no gate command defined…" >&2; exit 1` form. No live task carries it.

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

## The four older open tasks are still blocked on people and data

Unchanged by this session, and still true. None is workable by a worker:

| Task | Blocker, measured 2026-08-24 |
|---|---|
| T59 (`lo-4b17`) | 2 negated labels, floor 10 |
| T56 (`lo-6f53`) | floor is 10 **per dimension**; all 25 have ≤1 (14 labels total) |
| T57 (`lo-7c14`) | 828 concepts read, none from a source that can report an *unmapped* one |
| T20 (`lo-c48f`) | `requires: [surface:human]` — the candidate personally |

**T59, T56 and T57 unblock on one labelling round**, and `corpus/labelled/README.md`
now costs it (#163): **236 labels short**, floor is 10 *per dimension*, eleven
dimensions at zero.

The finding that changes the plan: **`suggestions.json` predates T25's broadening**.
Pre-marking covers programming only — 84 of 100 — and **zero** of the 108 ads across
trades, healthcare, administrative, hospitality, teaching and retail. Those would be
labelled blind, and they are the ads the broadening existed to add.

**One action serves both T56 and T57**: regenerate that read over all 208 ads with the
reader allowed to name what it cannot map. It restores confirm-and-move for T56 *and*
produces the top-level `unmapped` key T57 waits on. The new pass must **not** be
briefed with the dimension list — the 2026-08-19 one was, which is exactly why its
828-mapped/0-unmapped is a property of the briefing rather than of the ads.

T59 is no longer what the selector offers; T60 is. Do not claim T59 expecting to
finish it — its dep resolves, but its *data* does not.

**T20 was attempted.** The owner did sort the twenty adverts, and confirms they were
only loosely targeted. No ordering reached the profile store — `ivan` has no
`calibration/` directory and `rank_spearman` is still `null` — because T20a's harness
merged after the sitting. Re-running it is worth doing *after* iterative sourcing can
draw a better-targeted twenty, which is the whole reason T60–T69 exist.

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
- **The queue workflow could not open the ten new handles** — same runner-minutes
  exhaustion, `runner_id: 0` and a 3-second failure. They were created by hand from
  `handle_sync.py`'s output (#165–#174), and `query_status.py` now reports the board
  clean. **Expect this for every future task file**: the workflow that opens handles
  cannot run, so `handle_sync.py` + `gh issue create` is the path until runners return.

- **CI remains out of runner minutes.** Every job still fails in 3–5s with
  `runner_id: 0` and an empty `runner_name`, on `main` as much as any branch. The
  local `make host-gate` is the real gate. Diagnose once with the `runner_id` check
  before suspecting a diff.
