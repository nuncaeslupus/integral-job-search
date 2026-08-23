# Session handover — 2026-08-23 (T16 and T45 merged; T59 seeded)

## Board

- **T16 (`lo-bd02`, #56) merged** as PR #125 → `76f2768`. Issue closed, task archived.
- **T45 (`lo-2a7e`, #67) merged** as PR #126 → `9165c4e`. Issue closed, task archived.
- **T59 (`lo-4b17`) is new**, issue **#124** created by hand. Blocked on T25
  (`lo-1af2`) + T26 (`lo-9e41`) — the same two corpus tasks T56 waits on.
- Board after both: 95 tasks, 72 merged, 6 open, 15 blocked (was 17).
- **All claim refs pruned — 0 remain.** Four were stale (two from this session,
  `lo-0300` and `lo-5db0` from earlier ones). They accumulate one per task ever
  claimed; prune at the end of a session that merges anything.
- One pre-existing flag, unchanged: mixed-priority-convention — 20 tasks on the
  size scale [10, 5, 1, 0] and 2 on other values [70, 60].

## `merge-policy: after-review` means *bots*, not the owner

The owner corrected this mid-session. `after-review` is satisfied when the
review bots have run **and their findings are addressed** — then the agent
merges. It does not mean waiting for a human.

**CodeRabbit is the only bot on this repo**, confirmed against PRs #120, #121
and #123. So "after review" here is CodeRabbit, and the loop is: open, wait for
its pass, fix or push back on every finding with a reply on the thread, merge.

`gh` works on this surface — issue list/create, PR create/merge, `git push` to
any branch, `claim_task.sh` returning `won`/`lost`. The "MCP tools only /
manual POST" section in `CLAUDE.md` describes the web surface. Detect first.

## What T16 was, and why its gate changed

Negation scope. `_is_negated` searched a flat 40-character window back from a
cue with no notion of where the negator's clause ends, and two committed adverts
were being read backwards:

- `manfred-8392` — `…sin ambigüedades. **El inglés fluido` read as a *negated*
  English requirement, across a full stop.
- `remotive-2091075` — a `not` in one bullet inverted the next, across a blank line.

`_negation_scope` now cuts the window at the last `.!?;` or newline. **A comma is
deliberately not a boundary** — `manfred-8389`'s "no harás guardias" must still
negate, and `test_negator_still_reaches_across_a_comma` stops the fix passing by
negating nothing. 4 true negations kept, both false positives gone.

**The filed gate was unmeasurable and was split, on the owner's decision.**
`extraction_negation_recall >= 0.80` is defined over the corpus subset labelled
as negated. That subset is **2 labels, both on `tecnoempleo-98201f7d…`**, against
a floor of 10. T16 closed on `negation_scope_leaks == 0`; the number is T59.

Two things worth carrying forward from it:

- **T16 could not borrow T15's trick.** T15 split cleanly because
  `prefilter_suppressed_positives` was a real second property over 36 positives.
  That counter **skips every negated label** — a denial on a unipolar scale is
  class 0, and it only checks positives. Do not assume a split always has a
  measurable half; T16's gate is openly a *regression* gate and the task file
  says so.
- **`negation_window_only_count` is the number that shows the fix did something**
  (2 matches the raw window negates and the clause rule does not). The gate
  metric itself is 0 by construction.

## What T45 was

Per-advert CV and letter generation, gate `cv_generation_traceability == 1.0`.

**The design decision is the whole task**: documents are assembled *from* store
entries, so a claim cannot exist without one. `render_entry` is the single source
of a claim's wording, and `traceability` re-renders each entry from the store and
reads the **files on disk**, so it sees a line however it got there. A generator
that free-writes and traces afterwards can always invent a plausible citation.

Measured over all 100 labelled corpus adverts against a fixture candidate in
`tests/fixtures/generation/master.json`: **1800 claim lines, 0 untraced, 0
unused, 200 gaps named.**

Deliberately not built, and named in the PR rather than guessed at:

- `asks` comes from the caller that read the advert. No requirement-extraction
  NLP here — a guess between the advert and the gap list is the wrong place.
- Episodes are modelled but not drafted into the letter: the spec requires
  **per-use approval** per episode, and this module has no channel for it.

## CodeRabbit found eight things on #126, and six were real

All of one species — **a line the gate structurally could not see**:

1. `backed` was a `set`, so one manifest row backed any number of identical
   lines. A duplicated true sentence was free. Now a `Counter`, consumed per line.
2. The headline was written as `# …` and `_claim_lines` exempted every `#` line.
   Candidate prose escaped measurement, and anything typed after a `#` inherited
   it. **This is the 1600 → 1800 claim count: 200 lines previously invisible.**
   Exemption is now a closed set — four `_SCAFFOLD` sentences plus fixed `##`
   headings.
3. `"Java"` matched `"JavaScript"` — a store holding JavaScript answered an
   advert asking for Java, so the gap went unnamed. The module's own stated
   failure mode via a cheap substring test. `_mentions` requires a whole term,
   and `_select` had the same bug (its "also applies to" was right).
4. Two writers could take the same version. Exclusive `mkdir` makes allocation a
   compare-and-swap.
5. A document with no claims exited 0 — null traceability with an empty untraced
   list read as a met gate. Now requires exactly 1.0.
6. Deleting a claim line kept the metric at 1.0 — correctly, since survivors
   still trace. Gave the divergence its own number, `claims_unused`, rather than
   distorting the fraction. Took the cheap half of the suggestion: byte-for-byte
   re-rendering would make every formatting change a gate failure.

**Declined one**, with reasons on the thread: "run `make lint`/`test`/`evidence`/
`verify-subtree`/`verify-gates` in every task's gate block". `verify-subtree` is
not a target in this Makefile, `make gate` here means something else (T1's lint
exit code), and the repo convention is that a task's block regenerates *that
task's* evidence while `make host-gate` is the separate repo gate — which
`integral.repo_gate` already enforces reaches all four targets.

The eighth was the S4/T45 owner inconsistency, below.

## Traps this session hit — read before touching a gate

**A gate's evidence must be written by the argument-free entry point.**
`make evidence` discovers modules by `def _main` and runs each with **no
arguments**. `write_negation_evidence` was reachable only behind `--negation`, so
`T16.json` was a committed number the drift check never regenerated. If you add a
second evidence file to a module, write it from `_main` unconditionally.

**A step's gate state lives in five places, not four.** The previous handover
said four. Moving step 11 to `implemented` also required
`.claude/skills/step-11-application/SKILL.md`. `test_step_certification` and
`test_step_gates` name each one — trust them over any list, including this one.

**Editing any `SKILL.md` is blocked until `skill-workshop` is loaded**, and the
hook keys on *what a command writes*, not what it names — `sed -i`, heredocs and
`python3 -c` all trip it. `validate.py` flags `description.trigger` on
step-11-application, but **every `step-*` skill fails it identically**; it is
pre-existing and not yours to fix in an unrelated task.

**Task numbers are not the same as task ids.** `T57` was already taken (the T17
ontology split) when I filed the negation-recall task as T57. Check
`grep -o "^| T[0-9]\+" status/plan.md` before choosing; it became T59.

**`make evidence` compares against *committed* evidence**, so a legitimate new
measurement reads as drift until committed. Two rounds per session is normal.
`T55.json`'s `files_scanned` moves with every added or archived file (445 → 448
for T45's three).

**Rebase conflicts in `status/evidence/` are resolved by regenerating, never by
hand-merging.** #126 conflicted with #125 on `D12.json` and `T55.json`; take
either side, then `make evidence` and commit what it writes.

**`ruff` is not on PATH** — `uv run --extra dev ruff …`. Strict mypy rejects
re-exported names: import `DEFAULT_STORE_PATH` from `integral.harness`, not from
`integral.extraction`.

## Environment

**GitHub Actions is still out of runner minutes.** Every job fails in 2–5s with
`runner_id: 0` and an empty `runner_name`. Both PRs merged red on that basis
after `make host-gate` passed locally, which is what CI would run. Diagnose once:
`runner_id: 0` plus a sub-5-second duration means this, not the diff.

`main` at `9165c4e`: `make host-gate` exits 0 — 1235 passed, 1 skipped,
`evidence: no drift`, `verify-gates: 73 terminal task(s); 73 gate(s) asserted`.
