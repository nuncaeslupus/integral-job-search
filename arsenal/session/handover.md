# Session handover — 2026-08-22 (D-12 and T15 both merged; T56 seeded)

## Board

- **D-12 (`t-e1ca8374`, #83) merged** as PR #116 → `bcaf87c`. Issue closed, task
  archived. This is the one that had been held for an owner decision.
- **T15 (`lo-25b1`, #52) merged** as PR #118. Issue closed, task archived,
  claim released. It needed no new code — the extractor had been complete since
  2026-08-20 and only its gate held it open.
- **T56 (`lo-6f53`) is new**, with issue **#117** created by hand — Actions has
  no runner minutes, so `arsenal-queue.yml` cannot open handles. Check for
  missing handles with `handle_sync.py` after every session that adds a task.
- Board after both: 92 tasks, 67 merged, 8 open, 15 blocked (was 19).
- One pre-existing flag, unchanged: mixed-priority-convention — 23 tasks on the
  size scale [10, 5, 1, 0] and 2 on other values [70, 60].

## THIS SURFACE HAS `gh` — the CLAUDE.md note is stale

`github_channel.sh --detect` prints **`gh`**, and `gh` works: issue list, issue
create, PR create, PR merge, `git push` to any branch. The "no scriptable GitHub
channel / MCP tools only / manual POST" section in `CLAUDE.md` describes the web
surface, not this one. **Detect before believing it.** Everything this session
did went through `gh` and ordinary `git push`, including `claim_task.sh`, which
returns `won`/`lost` here rather than `manual POST`.

`open_task_pr.sh` still was not used — archiving by hand and opening with
`gh pr create` is two commands and needs no `ARSENAL_*` overrides.

## What D-12 was

D-2 binds an extraction score to three outcomes — a number, a failure, or
**unmeasured** — and the gate layer had two. `extraction_macro_f1: null` beside
`extraction_status: "unmeasured"` landed in `gate_evidence`'s "not numeric"
branch and read as a hard failure, so T15 could not reach terminal and fifteen
tasks sat behind it.

**Resolution A + B, on the owner's decision.**

- **B's upstream half had already landed.** `claude-arsenal#168` shipped in the
  vendored bundle before the task was picked up: `gate_evidence.py` takes a
  `status-key:` line and exits 3 for a metric the evidence file *positively
  asserts* is unmeasured; `gate_run.sh` prints `gate: unmeasured`. Nothing
  vendored was edited. **Read the vendored script before designing around its
  absence** — the payload's "What the code does" section was two weeks stale.
- **B alone would have unblocked nothing.** Exit 3 is still a hard stop in
  `open_task_pr.sh:116` and in `tools/verify_gates.py:127` (`returncode == 0`),
  both deliberately. The third outcome makes a state *recordable*, never
  *terminal*. That distinction is the whole finding.
- **So the split is the half that moved the queue.** T15's gate became
  `prefilter_suppressed_positives == 0` (already 0 over 36 positives);
  `extraction_macro_f1 >= 0.75` became T56, blocked on T25 + T26, with
  `status-key: extraction_status` so waiting for labels records as unmeasured.

`src/integral/task_gate.py` measures the **disease**: `unrecordable_task_gates`
counts any task gate whose evidence holds a non-numeric value at its key with no
`status-key` to say why. **1 of 67 before the split, 0 of 68 after.** Only a
positively asserted status counts — a `status-key` naming a key the evidence file
does not carry is a typo, not a third outcome.

Splitting T15's gate moved step 8's gate owner, which D-7's ownership check
enforces across **four** places: `status/spec-v2-steps.json`,
`status/spec-v2-steps.md`, `docs/spec-v2-steps/spec-annotated.md` (regenerate
with `make reader-steps`, do not hand-edit), and `status/evidence/D-21.json`.

## What T15 was

**No new code.** The extractor has been complete since 2026-08-20; only the gate
held it open. The work was correcting the payload's `## Tests` section — it still
named macro-F1 as T15's test, which is now T56's — and flipping the plan
checkbox to ☑, which merging does not do by itself.

`test_extraction_matches_corpus_labels` stays in T15 and asserts the **refusal**
(null, unmeasured, dimensions named). When the corpus grows past the floor that
test is what should start failing, and that is T56's signal to implement scoring.

## Claim refs had accumulated — 14 of them, 13 for merged tasks

`claim_task.sh lo-25b1` returned **`lost`** and it was a **stale lock**: issue #52
was open, unassigned and carried no `arsenal:claimed` label, and the ref pointed
at a commit merged two days earlier. `claiming-internals.md` says claim refs
accumulate roughly one per task ever claimed and should be pruned from a CLI
session occasionally — nothing had ever pruned them here.

**Diagnose a `lost` before obeying it, and never route around it.** The check is
the issue, not the ref: assignee + `arsenal:claimed` label is the system's own
visible record of who holds a task. All 14 refs are now pruned; a fresh claim
won cleanly.

## Lessons worth keeping

**`make evidence` compares against *committed* evidence**, so a legitimate new
measurement reads as drift until it is committed. Commit, then re-run
`host-gate`. Two rounds of this per session is normal, not a bug.

**`T55.json`'s `files_scanned` moves with every added or archived file** — the
naming scan reads `arsenal/tasks/*.md` and not `_history/`. Adding three files
took it 468 → 471; archiving one payload took it 471 → 470. Expect to commit it.

**`ruff` is not on PATH** — `uv run --extra dev ruff format <paths>`. Format only
the files you touched; `make lint` still does not check formatting.

**`test_naming` also fails on an untracked directory, not only on a reference.**
A stale `__pycache__/` sat under a `src/` directory named for the pre-T55 package;
it was never committed, so CI never saw it and only the local gate went red. The
check asserts that directory does not exist, so removing it is the whole fix.

**And it scans this file.** Writing the old package name here — even to describe
that bug — trips the same check. Name the rename, not the path.

## Left open (carried forward)

- **T15's merge freed the queue.** It has **15** live transitive dependents,
  four of them ready now — **T16** (negation), **T17** (`ontology_hit_rate`),
  **T42** (local annotation), **T45** (CV/letter generation) — and eleven still
  behind other deps: T18, T19, T20, T21, T22, T43, T44, T46, T47, S6, D-17.
  The selector returns T17. (D-12's payload said "fifteen" but listed fourteen;
  the missing one is D-17.)
- **Nothing fetches the advert page yet** — D-18 built the liveness verdict, not
  the request. Needs T12's egress. Not seeded.
- **The worker half of D-22 is upstream's and still open** (`claude-arsenal#175`):
  `open_task_pr.sh` re-runs the payload gate and never the repo gate.
