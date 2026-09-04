---
id: t-6d3fac96
title: "T114: D-25: the substance sweep trusts the manifest, so a deleted line whose substance survives in a headline is invisible"
priority: 5
---

## Acceptance gate

```gate
disclosures_unbacked_by_a_generated_document == 0
evidence: status/evidence/T114.json
key: disclosures_unbacked_by_a_generated_document
```

Transcribed from `status/plan.md`'s row for this task, which declared this
metric before the task was imported. The name is the plan's, not a new one:
inventing a second name for a declared metric is a mistake this repository has
made four times, and `test_the_committed_plan_and_queue_agree` fails it.

Imported from issue #306

Found while implementing D-24 (#253, PR #305). Out of scope there — it is T46's behaviour, not the retraction path — so recording it rather than widening that diff.

## What is wrong

T46's substance sweep skips any text listed in `disclosed`, and `disclosed` comes from the **manifest**, not from the documents that were actually generated.

So: delete an episode line from `letter.md` while a headline still carries its substance, and neither T46 nor D-24 flags it. The manifest still lists the episode as disclosed, the sweep skips its text, and the substance goes out inside a headline with nothing backing it.

## Why it is worth doing

It is the same shape as the defect D-24 just closed — a record that outlives the thing it describes — but on the other axis. D-24 fixed *approval outliving its evidence*. This is *disclosure outliving its document*.

It is genuinely fail-open: the sweep exists to catch unbacked substance reaching an employer, and this is a route past it that looks clean.

## Not urgent

It behaves identically before and after a retraction, which is why it is not D-24's. Nothing is known to be hitting it today.

## Scope

Read `disclosed` from the generated documents rather than the manifest, or reconcile the two and treat a divergence as a finding. Whichever is chosen, the accepted cases go into T46's fixtures and its denominator rises.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
