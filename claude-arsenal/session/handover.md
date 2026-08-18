# Session Handover

<!-- Written at session end. A new session reading this file can resume without additional context. -->

## Next session starts here

**M2's first half is merged** (PR #23, `841ba57`), and **PR #24 is open** with S9
and T7. The board reads 31 merged, 37 open. `make ci` is green across five jobs.

**The one thing that matters most is not code: T5 has not run.** The corpus has
100 ads and zero labels, and it is `[HUMAN]` — only the owner can do it. Every
remaining M2 task chains off it:

```
T14 ← T5
T15 ← T5, T14
T16 T17 T42 T18 ← T15        T19 ← T18        T44 ← T18, T19
```

So there is no path to a ranked list — the thing a candidate would actually
look at — until the labelling happens. A labelling aid was being built this
session to make it as fast as possible; check whether it landed.

## What landed

**PR #23 — nine tasks.** T24/T41 (constraints schema and step engine), D-6
(refusals surviving a rebuild), T11/T32 (offer schema, connectors as data),
T13/S5 (dedup, lifecycle with tombstones), T33 (net pay), S7 (thirteen step
skills), and **CI, which did not exist before**.

**PR #24 — open.** S9 (claude-arsenal is a real subtree at `vendor/`, the
`ARSENAL_SHA` pin deleted), T7 (question bank generated from the dimension
model), and the S11 seed.

## Three defects the gates structurally could not see

Worth carrying forward as a pattern, because all three were invisible to a
passing gate and none was found by reading code:

1. **T33's shipped tax files claimed a human verification nobody performed.**
   The gate measured that *generated* rule sets carry their mark — entirely
   inside a temp directory — so a committed file wearing `verified` passed
   untouched, and `verified` is the label that clears `approximate`.
2. **A majority duplicate cluster erased its own evidence.** Three copies of one
   ad in a batch of five put their shared body over the boilerplate line; all
   three pairs scored **0.000**. `dedup_precision` measures precision and
   deliberately not recall, so nothing would ever have flagged it.
3. **Tax rule paths were built from unvalidated country and region.**

**The lesson each time was the same: the fix went into the probe, not only into
a test.** A property guarded only by a unit test is one the gate cannot see, and
this repository has now been bitten by that three times in one session.

## Decisions taken this session

1. **`verified` means a person checked it, and nothing else may wear it.** The
   shipped ES/DE tax files are marked `generated`; promoting one back is a job
   for somebody with the tax code in front of them, and the gate refuses it
   until then.
2. **A subtree at `claude-arsenal/` is impossible** — `git subtree` maps a prefix
   onto the upstream *root*, the bundle lives several directories down, and host
   state (`queue/`, 68 files) lives inside the same directory. Upstream is at
   `vendor/claude-arsenal/`; the bundle is assembled from it and the assembly is
   verified. `vendor/` is excluded from ruff and mypy.
3. **Dedup counts a listing once, not once per copy.** Boilerplate frequency is
   computed over cluster representatives, so an ad collected many times
   contributes one entry.
4. **Expiry refuses a naive timestamp** rather than assuming UTC — guessing a
   zone expires a listing a day early for anyone outside it.
5. **A step's `gate.task` names whoever writes the metric**, since that field
   only locates an evidence file. The constraints step named T24 while T41
   measures it, so the register read it as not-implemented while it passed at
   1.0.

## Review

Qodo raised 16 findings on #23; **all 13 code findings resolved**, each with a
regression test confirmed failing against the previous code. Three rule
violations declined with reasoning on the thread — one checks for a `size` field
the queue schema does not have (size is encoded in `priority`), two ask for the
PR to be split, which the one-branch session constraint forbids.

On #24 Qodo weighed filtered-subtree, submodule and clone-and-copy alternatives
and recommended keeping the separate-prefix subtree.

## Waiting on the owner, not on work

- **T5** (label the corpus) and **T25** — `[HUMAN]`.
- **T12** — `[LAPTOP]`; needs a real browser.
- **S10** — the skill listing budget is 8,000 chars and the library is at
  **11,140**. Not S7 being wasteful: its 13 descriptions average 318 chars
  against the existing average of 369, and the pre-existing 19 skills use 88% of
  the cap alone. The payload records three options with a preference (load only
  the step in play). **Needs a decision, not a trim.**
- **S11** — test mode, design deliberately left open.
- **T29** — product shape.

## Environment notes

- `gh` is unavailable; PRs go through the GitHub MCP tools, and `done` →
  `merged` flips through `claude-arsenal/scripts/update_task_row.py`.
- **The `PreToolUse` guard blocks its own commit messages** when they quote the
  paths it protects. Pass messages through a file (`git commit -F`).
- `update_task_row.py` rewrites every line it touches; restore the untouched
  ones verbatim or a status change reads as a 64-line diff.
- After a merge the remote branch is deleted, so `--force-with-lease` fails with
  "stale info" — push plainly.
- `make arsenal-upgrade REF=v0.x.y` pulls, reassembles and verifies in one step.
- Worker fan-out worked well: `isolation: worktree`, each worker copies a named
  disjoint file set back, orchestrator re-verifies and commits. Workers cut from
  an older base more than once — tell them to fetch and fast-forward first.

## Surface profile at handover

Cloud session (`CLAUDE_CODE_REMOTE=true`), so `laptop`-tagged tasks cannot be
released `done` from here.
