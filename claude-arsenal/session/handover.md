# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**Five PRs merged this session** (#24–#27) and **#28 is open** with S4. The board
reads **42 merged, 1 done, 28 open**. `make ci` is green across five jobs, 693
tests, **42 of 42 terminal gates asserted**.

**Six of thirteen steps now read `implemented`** with zero register drift:
constraints, history, identify, intake, sourcing, traits.

**T5 is still the one thing that matters most, and it is not code.** The corpus
has 100 ads and zero labels, and it is `[HUMAN]`. Every remaining M2 task chains
off it:

```
T14 ← T5        T15 ← T5, T14
T16 T17 T42 T18 ← T15        T19 ← T18        T44 ← T18, T19
```

The labelling aid is built and committed (`tools/labelling_page.py` writes a
self-contained `corpus/labelled/label.html`). **Read `corpus/labelled/README.md`
first** — D-1 landed a warning there that the Catalan ads are *not* all remote.

## What landed

| PR | tasks |
|----|-------|
| #24 | S9 (arsenal as a real subtree), T7, T31, D-3, D-4/D-7 via **T49** |
| #25 | T8 (answers → episodes), T27 (the interview), D-1 (Catalan slice) |
| #26 | T49 (trait sufficiency) |
| #27 | T28 (continuous capture); seeded **D-8** and **S12** |
| #28 | S4 (CV store) — open |

## Cloud-doable work still on the board

**D-8** and **S12**, both seeded this session. Everything else is blocked on the
owner (see below). Do these before reporting the queue empty.

## The pattern this session kept hitting: green is not measured

Nearly every real defect was invisible to a passing check, and several were found
only by **degrading the environment** rather than by reading code.

- **A shallow CI checkout made two checks stop measuring rather than fail.**
  `actions/checkout` clones at depth 1; the subtree check reported "cannot tell"
  and skipped, and T31's note check found only the tip commit so all 28 notes
  trivially read `unchanged`. Neither turned a job red. Every job now checks out
  full history, pinned by a test.
- **A task was recorded `done` with no ```gate block**, so `verify_gates.py`
  skipped it entirely — 38 of 39 asserted, with the missing one invisible in a
  green run.
- **A denial and an affirmation of the same subject came out byte-identical**
  until the sign was carried beside the link.
- **A validator accepted any non-empty evidence tuple**, so a reading claiming
  two episodes while naming one row passed.
- **The quota-never-voiced check was a word list**, but a leaked quota is usually
  a number: "1 of 2 required examples" passed it.

**Prefer degrading the environment — shallow clone, empty directory, missing
extra, hand-built violation — over re-reading the code.** And put the fix in the
*probe*, not only in a test.

## Decisions taken this session

1. **The Traits gate got a task, not an edit (T49).** Neither T27 nor T28 is
   measured on `trait_evidence_sufficiency`, so no reassignment between them
   could make the register true.
2. **`story_failure_fraction` is reported, never gated on (D-3).**
3. **The Catalan slice is Catalan IT ads, stated as such (D-1).** Six of fifteen
   mention teletreball/remot but only **two** offer it; four use the word for
   remote support *delivered to users*, and one is explicitly on-site. A keyword
   filter would have called six remote.
4. **Test mode's four questions are answered** (`lo-5530.md`); only the marker is
   open — recommendation `[[...]]` / `[[! ...]]`, meta parsing suspended inside a
   paste.
5. **The listing budget is to be raised (S10), upstream.** **Do not patch it
   under `vendor/`** — the next subtree pull reverts it silently.
6. **PDF import sits behind an optional `cv` extra; DOCX is stdlib** (S4). The
   gate runs green without extras, and a missing importer *reports* unavailable
   rather than returning an empty store.

## Filed upstream (nuncaeslupus/claude-arsenal)

- **#142** — the queue never reads GitHub issues (owner's request).
- **#143** — `LISTING_BUDGET_CHARS` is not configurable. **Blocks S10 and S11.**
- **#144** — the bundle cannot be consumed as a subtree.

## Review

Qodo reviewed #24–#28. Real findings were fixed with a test confirmed failing
first; the rest were declined with reasoning on each thread. Two declines worth
carrying forward, because they will be raised again:

- **"The gate measures a synthetic probe, not production data."** That is the
  repo-wide convention and deliberate — `profile`, `constraints_step` and
  `identity` all measure in throwaway trees, and `identity` says why: doing it to
  a real candidate's tree *"would be its own kind of leak"*. There is also no
  real profile to measure until T5 runs.
- **`size` field / split the PR / housekeeping mixed.** The queue schema has no
  `size` (it is encoded in `priority`), and the one-branch constraint forbids a
  second PR. Leaving merged work reading `open` is worse — that gap already had
  to be repaired once.

## Environment notes

- `gh` is unavailable; PRs go through the GitHub MCP tools, and `done` →
  `merged` flips through `claude-arsenal/scripts/update_task_row.py`.
- **`isolation: worktree` does NOT take on this surface.** Confirmed: a worker
  reported `git rev-parse --show-toplevel` as the main tree. **Run one worker at
  a time** — two concurrent workers clobbered each other earlier.
- **While a worker shares the tree: stage explicit paths, never `git add -A`.**
  It swept a worker's unfinished files into a housekeeping commit.
- **Re-check `git log` before committing after any push.** An automated reset
  moved HEAD past a just-pushed commit (`reset: moving to HEAD^` in the reflog),
  so the next commit built on the wrong parent and the push was rejected.
  Recovery: verify by sha256 that the remote holds the work, then reset to it.
- **Do not `git checkout <path>` to undo a scratch experiment** on a file you
  have edited but not committed — it reverts to the committed version.
- **The `PreToolUse` guard blocks its own commit messages** when they quote the
  paths it protects. Pass messages through a file (`git commit -F`).
- `update_task_row.py` rewrites every line it touches; restore the untouched ones
  verbatim or a status change reads as a 71-line diff.
- After a merge the remote branch is deleted, so `--force-with-lease` fails with
  "stale info" — push plainly.
- **Check the ledger against merged PRs, not memory.** S9 and T7 sat `open` after
  merging because nobody wrote the rows back.
- A step whose evidence satisfies its gate while `spec-v2-steps.json` still says
  `not_implemented` is **expected** drift after landing a step-owning task. Flip
  both the JSON and the prose, then `make reader-steps`.

## Waiting on the owner, not on work

- **T5** (label the corpus) and **T25** — `[HUMAN]`.
- **T12** — `[LAPTOP]`; needs a real browser.
- **S10 / S11** — need upstream #143 to land first.
- **T29** — product shape.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks cannot be
released `done` from here.
