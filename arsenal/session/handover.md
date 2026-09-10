# Session handover

**2026-09-10.** Continuation of the overnight run. **Four PRs merged**, `main`
broken by the merges and repaired. `origin/main` is at the #436 merge plus the
repair in #444.

## 1. What merged

| PR | what it actually was |
|---|---|
| #438 | previous handover + the task file for the `verified_gate.sh` false-CI line |
| #442 | the T159 split — three follow-up tasks (#439, #440, #441), docs-only |
| #434 | **T154**: `?page=1&page={page}` loaded and was certified, so a duplicated query key defeated the pagination capture rule. The placeholder-carrying key is now counted per reading rather than by `param`'s declared spelling. |
| #435 | **T156**: approved-CV-line matching compared `_words()` output, which deletes every non-word character, so a paraphrase differing only in punctuation passed. Replaced with NFC casefold + whitespace collapse on both sides. |
| #436 | **T159**: the floor sweep, landed deliberately bounded — see §3. |

Each carries a `verified_gate.sh` PASS block on its own head, quoted in its merge
commit, with CI green on the same SHA.

## 2. The merges broke `main`, and that is the finding of the day

`make host-gate` was **red on `main` at 18372e3**, and neither branch was wrong.

- #436 committed `MINIMUM_FLOORS_SWEPT = 73` against a population of 73, zero slack.
- #434 added a floor of its own, `pagination_capture.MINIMUM_QUERY_KEY_OCCURRENCES_SCANNED`.

Both green in isolation, both green on their own merge refs. The merged tree
sweeps **74**, so #436's zero-slack claim became false **without either side
editing it**. `stale_margin_claim`. Fixed in #444 by regenerating against the
merged tree, per CLAUDE.md's rule.

**The part worth carrying forward:** no reviewer could have caught this, because
the collision is in neither diff. It surfaced only because the gate was re-run
against `main` *after* merging. Nothing in the protocol asks for that run.
CLAUDE.md's census-collision section describes two branches writing the *same*
value; this is the sibling case — two branches writing *different* things that
only collide once combined — and it is the one CI cannot see, since CI tests each
PR's merge ref against a `main` that does not yet have the other.

## 3. #436 landed bounded, and the honest number is 73 of 73

Round 5's reader showed the sweep's metric mutates a floor's **value** while
holding its **comment** fixed. Nobody lowers a floor that way — a real regression
edits both. Under the realistic mutation the settable count is **73 of 73 in
every round**, not the 26 of 73 the series 33/67 → 30/76 → 26/73 suggested. The
apparent convergence was an artefact of the mutation being weaker than the
threat. So the module states 73 of 73 and the rest is #439/#440/#441.

## 4. Review debt merged knowingly

Merged on the owner's explicit instruction with these open, recorded on each PR
and in each merge commit:

- **#434 round 7, unfixed**: the per-reading key count is applied to the query
  axis but not the body axis; the seven `.casefold()` sites are pinned in
  aggregate rather than per site (so reverting one can be answered by another —
  a known face of the family); two comment claims unpinned.
- **#435 round 8, incomplete**: the reader was killed mid-read, so that head has
  neither a BLOCK nor a clearance. The round-8 *fix* it was reading did complete
  and was mutation-verified.
- All three: `review_reader check` reads **exit 2** and always will here. Every
  session authenticates as `nuncaeslupus`, the PRs' own author, so the identity
  comparison cannot distinguish an independent reader. The owner chose option (c)
  — merge on the reader's verdict, record the check as unsatisfiable on this
  surface rather than imply it passed. **That is now the standing answer**; do
  not re-ask it.

## 5. Round totals

~19 second-reader rounds across the three code PRs; **not one empty**. Every
finding sat behind a green `make host-gate`, a PASS verdict block and green CI.

**The avoidable cost was dispatch, not review.** Workers repeatedly ended their
turn parked on a `Monitor` instead of polling — at least five agents, several
times each. `make host-gate` is ~3.5 minutes, longer than any poll interval. Put
in every brief: *poll the output file inside a single shell command with an
until-loop; never end your turn on a monitor.*

## 6. Pick up here

1. **Merge #444** if it is still open — it is what makes `main` green.
2. **Re-run `make host-gate` against `main` after any batch of merges.** §2 is
   the reason. Consider making it a step rather than a habit.
3. Open, unclaimed: **#437** (the hardcoded false "CI is unavailable" line in
   every verdict block), **#439/#440/#441** (the floor-audit split), **#420**,
   **#427**, **#426**, **#314**. **#412** still needs egress this environment
   does not have.
4. Not an oversight, already argued: T156's undecidable state fires for **208 of
   208** unapproved episodes on the real corpus. Disclosed in the docstring as an
   accepted risk; worth a task, not a bug.
