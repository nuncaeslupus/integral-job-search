# Session handover

**2026-09-09 → 10, overnight.** Three tasks taken, three PRs open, **none merged**.
Eleven second-reader rounds run; **not one came back empty.** The session ended on
the account's 5-hour limit at 01:14 UTC (resets 02:40), which killed three agents
mid-flight.

`origin/main` is unchanged at the #433 merge. Everything below is on branches.

## 1. State of the three PRs — all green, all reviewed, all still blocked

| PR | task | issue | head | rounds | where it stands |
|---|---|---|---|---|---|
| #434 | T154 `t-e6f2d418` | #414 | `7807824b` | 4 fix / 3 review | **awaiting round-4 review** (reader killed at start) |
| #435 | T156 `t-3ca8f7b1` | #419 | `fd633ac5` | 5 fix / 4 review | **round-5 push is UNVERIFIED — see §4** |
| #436 | T159 `t-6f2b9c14` | #429 | `639371b6` | 3 fix / 2 review | **awaiting round-3 review** (reader killed at start) |

CI is green on all three heads and `mergeable_state` is `clean` on all three. Green
is not the question — every finding this session sat behind a green gate.

## 2. Eleven rounds, zero empty ones, and the family held

Round counts by PR: #434 → 6, 5, 7 findings. #435 → 5, 2, 1, 1. #436 → 6, 9.
**Thirty-two findings; the large majority fail-open.**

Last session named the family and this session did not dent it:

> **A check pinned against a proxy for the property, rather than against the
> property.**

Two new faces worth adding to the list, both of which cost a full round:

- **A checker whose accept-set is seeded by its own trigger word.**
  `floor_sweep._zero_slack_claim_contradicts` scanned a window *including* the
  matched phrase, and `_spelled_out_numbers("zero slack") == {0}` — so `claimed`
  always contained `0` and `literal_value == 0` was never a contradiction. **16 of
  19 floors could be set to 0 with the metric still reading 0.** Written as the
  remedy for floors that cannot fail.
- **An exemption whose scope is set by what keeps a fixture green.** #434's
  `path_segment` carve-out was defended on a premise contradicted twice — a
  loadable config with *no path segment in it*, and Rails' `params`, which the
  diff's own error string names as a merging namespace. The reader's diagnosis is
  the sentence to carry forward: *extending the mirror to `path_segment` breaks
  only `page_placeholder`'s probe.* In the same round a **fixture's expected
  verdict was changed to accommodate the new rule** while still citing R7 — inside
  a module whose stated standard is "derived from the rule's text, never from
  running the code", and whose metric is named `…_resolved_inconsistently`.

**A category is not a classification if nothing in it is ever checked.** #436's
round 1 said the arithmetic branch had 11 of 46 members; round 2 broadened the
sweep to 57 and the branch still had **exactly 11**. Every newly-swept floor landed
in `dynamic`, where no margin was computed. Round 3 finally attacked that.

**What worked, again, was the pre-push self-scan.** It caught, by the implementer
rather than a reviewer: a drafted `"fail_open": len(defects)` field (a numerator
restated as a second measurement); an `episodes_withheld` that would have become a
metric independent of its own inputs, deleted rather than patched; three of a
worker's own new tests asserting "no finding" without asserting the sweep saw
anything; and — the best of the night — a first-draft comment claiming a narrowing
"can only ever move an episode out of this branch, never the reverse", traced,
found false via `_words()`'s treatment of `\n`, and **softened rather than shipped,
in a PR whose whole subject was false justification comments.**

**What worked for reviewers: demanding the reviewer's own populations.** #435's
readers each built their own paraphrases and innocents rather than reusing the
implementer's, and the numbers moved 0/8 and 21/30 → 8/8 and 12/12 → 9/9 and 30/30.

## 3. `tools/verified_gate.sh:143` prints a false line in every verdict block

`echo "commit ... CI is unavailable; this is the substitute CLAUDE.md names"` is
**hardcoded**, not a live check. It is a leftover from the 2026-09-04 outage and has
been false since the 7th, so every verdict block pasted on a PR since then carries
a false claim about CI. Found independently by two workers and confirmed at source.

**Not yet filed as a task — do that first thing.** CLAUDE.md's § *Known environment
state* is the section with a perfect record of going stale, and this is that
staleness leaking into the evidence artefact itself.

## 4. The killed round left an unverified push — treat it as unsourced

**#435's head `fd633ac5` was pushed by an agent that died before running
`verified_gate.sh` and before reporting.** CI is green on it, but no verdict block
exists, no mutation results were reported, and no self-scan was run. Per CLAUDE.md's
rule after a mid-round kill: **treat every number it left as unsourced until
regenerated**, and grep its diff for figures stated as measured that no committed
artefact supports. The intended round-5 content was: filter `unbacked` by
`if line not in approved`, add both routes as probe states, and add a
`status/plan.md` row naming `intact`'s seam. Verify what actually landed.

The other two killed agents (readers for #434 and #436) died in their first tool
call and left nothing.

## 5. Merging is blocked by an identity fact, not by the reviews

**Every session on this surface posts as `nuncaeslupus`, which is also the PR
author.** So `review_reader check` reads exit 2 for every one of these heads: a
marker written by the PR's own author never counts. The reviews are genuinely
independent — separate sessions, spec read before implementation, own mutations,
own populations — but the mechanism compares logins and cannot see that.

Both readers that reached the end flagged this unprompted. It is D-28's remaining
gap, and it now blocks three mergeable PRs.

**Open question for the owner, asked and not yet answered:** (a) a separate
identity for reader sessions, (b) `review_reader` extended to attest something
other than a login, or (c) merges proceed on the reader's verdict with the identity
check recorded honestly as unsatisfiable on this surface. The owner's instruction
this session ("merge when CI green") reads as (c), and the intent was to say so in
the merge commit rather than imply the check passed.

## 6. Pacing — the 2–3 worker rule held, the per-agent cost did not

Concurrency stayed at 3 and never exceeded it. The limit was still hit at 01:14.
Per-agent totals ran **270k–530k tokens**, well above the 135k–280k the last session
recorded, because every PR went to four or five rounds and each round re-ran
mutations. The orchestrator's own context was again barely touched.

Two concrete costs worth removing next time:

- **Workers repeatedly ended their turn parked on a `Monitor` instead of polling.**
  Four separate agents did this, several times each; every one needed a nudge to
  read the output file it was already waiting on. `make host-gate` is ~3 minutes
  (pytest alone ~170s), which is longer than a poll interval — say so in the brief
  and tell them to poll the file, never to stop on a monitor.
- **Handing a fix round to the original implementer past ~450k tokens is a false
  economy.** Fresh workers took over #434, #435 and #436 mid-stream and were
  cheaper than resuming, because the brief carried the findings anyway.

## 7. Pick up here

1. **File the `verified_gate.sh:143` task** (§3). Nothing else depends on it, and it
   is corrupting every verdict block in the meantime.
2. **Resolve the identity question** (§5) — three PRs wait on it.
3. **Regenerate #435's unverified round-5 numbers** (§4) before reviewing it.
4. **Dispatch the three outstanding reader rounds**: #434 round 4 on `7807824b`,
   #436 round 3 on `639371b6`, #435 round 5 on whatever its head is once §4 is done.
   Briefs for all three are in this session's transcript; the standing questions are
   #434's case-insensitivity widening (a fail-closed cost to weigh, not assume) and
   #436's new dependency on committed evidence files (a floor checked against a
   recorded number is only as good as that record).
5. Untouched and unclaimed: **T157** (#420), **T158** (#427), **D-30** (#426),
   **D-29** (#314). **T152** (#412) still needs egress this environment does not have.

**One thing not to re-derive:** on the real corpus T156's undecidable state fires
for **100% of unapproved episodes (208/208)**. It is disclosed in the docstring as
an accepted risk and a reader declined to raise it. A state that always fires
carries no discriminating information, so it is worth a task — but it is a known,
argued position, not an oversight.
