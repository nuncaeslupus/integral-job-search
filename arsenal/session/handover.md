# Session handover

**2026-09-08.** Board: **199 tasks** — 30 open, 164 merged, 3 done, 2 blocked.
`origin/main` at the merge of #408. Fourteen PRs merged: #396, #397, #398, #399,
#400, #401, #402, #403, #404, #405, #406, #407, #409, #411 — eleven of them task
PRs. #410 was still open at the end, on its fifth review round.

An unattended overnight run: one orchestrator holding the GitHub API, workers in
linked worktrees, and a second-reader session per pull request.

## 1. The number this session exists to record

Six task PRs were opened at once. **All six passed `make host-gate` and all six
passed `tools/verified_gate.sh`.** An independent second reader then read each
one, and **five of the six were blocked, every finding fail-open.**

| PR | what a green gate did not catch |
|---|---|
| T108 | the new gate scored 0 on `status_asserted`, the most likely next bad name — and it measured a probe row without asserting the code emits that row |
| T123 | a floor breach writes no file, so the exit code was its only alarm and nothing asserted it: one character switched the gate off with 24/24 tests green |
| T111 | `record()` wrote a floor claim the run never met over truthful evidence, on a zero-package scan |
| T138 | at L1 both the pay rule and its guard went inert — 27 of 70 comparable pairs inverted while the auditor reported 0 |
| T118 | cleared, but five accepted cases were absent from the fixtures and the floor equalled the row count |

CLAUDE.md says "a green gate is necessary and is not sufficient". That is now
**6 of 6 green, 5 of 6 defective**, measured on one night's batch.

## 2. D-28 proved its own thesis five times — #408

`review_reader` makes the review half of `merge-policy` checkable: a report bound
to the head commit, where a missing report never reads as a pass. It was blocked
**five times**, each round the same fail-open one layer deeper, **every one
behind a green gate**:

1. a **blank** comment author cleared the PR — reason literally "a second reader
   () cleared";
2. the fix normalised blankness but the comparison stayed raw and
   case-sensitive — `NuncaEsLupus` cleared, GitHub logins being case-insensitive;
3. invisibles deleted, **visibles** not — `@nuncaeslupus` cleared, and the
   capture is hand-written so that is a transcription habit, not malice;
4. NFKC + `[A-Za-z0-9-]` applied as a **deletion filter**, so decoration spelled
   *inside* the alphabet was welded on: `nuncaeslupus (OWNER)` became a different
   identity and therefore counted as somebody else;
5. — closed by changing the **quantifier**.

**The lesson, and it generalises past this file.** Rounds 1–4 each enlarged an
enumeration, and an enumeration has no last element. Round 5 stopped
*transforming* a string into an identity and started *validating* whether it
already is one — a closed grammar, with no next category to discover.

Round 4 also wrote a false safety claim into CLAUDE.md — "the transform only ever
merges strings" — refuted by its own example: `straße` becomes `strae`, not
`strasse`. Corrected there.

**Why four rounds each stopped one layer short is structural, and worth
remembering: there was no control anywhere in which the PR *author* field was
decorated.** Every round decorated the comment side, so every fix was shaped to
half the problem.

The regression ladder is now **committed as a test** — each historical rule
re-run against the current controls, a rung scoring 0 failing — so a future fix
that regresses to any earlier rule is caught rather than rediscovered.

## 3. What the reviewers did that made them worth the cost

Not "read the diff and comment". The reports that found things did one of these:

- **Attacked the invariant rather than confirming it.** T113's reviewer stuffed
  `?page=2` and `Pager` into the probe *and* the fixture, then smuggled the key
  into `captured.json` as a response field. Still a finding every time — so
  "nothing reads a response" is established, not asserted.
- **Measured the excluded cases.** T150's fixer said four evidence keys were
  unmoved by an added file; the reviewer measured all four rather than accepting
  it, then went further — added 8 real `.md` files across every top-level
  Markdown directory and ran `make evidence` over the whole committed set. The
  goal holds in fact, not just where the gate looks.
- **Re-derived a claim instead of reading it.** T120's reviewer audited all 49
  RFC case verdicts, and later re-ran a fuzz with its own classification, because
  comparing canonical pattern strings *hides* a precedence flip.
- **Caught a fix reproducing its own defect one line away** — twice.

## 4. Three traps met, so they are not met again

**A stale board JSON produces false flags.** `query_status.py` re-run late in a
session against a session-start fetch reported ten merged tasks as "archived but
the issue is still open". All ten had closed correctly; the JSON was the
snapshot, not the truth. **Re-fetch before believing that flag.** Two `lo-*`
flags are a different false positive — title-collision in the issue-to-task
resolution, both files long since archived.

**`files_checked` cost this session a merge conflict and two red checks before
T150 fixed it.** Two branches each read 465 and were individually correct while
the PR's *merge ref* — what `pull_request` CI actually checks out — had 467.
T150 makes it a floor and adds a check that catches any evidence key moving when
a file is added. That whole class should now be gone.

**A task's gate must carry a fenced bash block, not only the metric block.**
T152, T153 and T154 were seeded this session with the metric block alone, so
nothing would have run them — the inert-gate defect, committed while filing
findings about inert gates. Fixed here; `query_status.py` is what caught it.

## 5. Environment: three recorded facts were wrong

**The repository is PUBLIC** as of 2026-09-07 (`visibility: public`, MIT). That
one change is behind everything below, and CLAUDE.md was describing the private
repository's constraints.

**CI has runner minutes again** — measured at 95 and 133 seconds concluding
`success`, against 4–9 second failures the day before. Actions is free and
unmetered on public repositories, which is what CLAUDE.md itself had predicted
would fix the outage. **Not a billing rollover**: a rollover recurs, going public
holds.

**CodeRabbit is back**, on the OSS tier, skipping only the *automatic* review
below 10 stars and answering `@coderabbitai review`. It found one real thing
(PR CI checks `refs/pull/N/merge`, not the head — so CI and `verified_gate.sh`
assert different things, which is a better reason to require both than the
redundancy first written). It is not a standing reviewer and does not satisfy the
review half.

## 6. Open, and what to pick up

**#410 (T120)** is the only PR left open, on its fifth review round. Its second
reader is a 53-row RFC 9309 case table written before any implementation was
opened, honestly marked `RECOLLECTED` because egress to rfc-editor.org is blocked
here. Four rounds each found the encode rule too narrow in a **different
dimension** — the octet set, then the side (pattern vs target), then the position
within a pattern, then the region (query vs path). The open question at handover
is whether 4,564 precedence-driven loosenings in the reviewer's corpus B are
RFC-mandated consequences of encoding path octets before comparison.

**`repo_matcher_verdicts_against_the_rfc` reads 9, not 3** — and that is not a
regression in `integral.robots`. The second reader's coverage widened from the
query to the path; the cause is one `_CHUNK_SAFE` allowlist consulted in two
regions, so one fix closes all nine. **T151** (`t-7b3ac419`, priority 10) is
scoped to exactly that and is the next thing the selector returns.

Five tasks were filed rather than folded into the diff that found them:
**T152** (pythonorg's six adverts need one robots-adjudicated GET — this
environment's proxy answers 403 to the CONNECT for python.org, so it needs a
session with egress, and fabricating the capture was correctly refused),
**T153** (`provenance` is advisory, so a fabricated capture claiming `live`
passes), **T154** (`?page=1&page={page}` is certified while sending the key
twice), **T155** (one unresolvable marker author vetoes a real second reader),
and T151 above.

**T155's gate was itself vacuous** under one of its two answers — "and" in the
task file where the plan row said "or" — caught by the last review. Under the
conjunction, one answer scored zero with no change at all. The defect this
repository keeps meeting had reached the task filed to record one.
