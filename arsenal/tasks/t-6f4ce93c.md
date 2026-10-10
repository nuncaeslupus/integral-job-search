---
id: t-6f4ce93c
title: "T286: Retraction still leaks into advice and drafts: held-skill gaps, ATS keywords, draft rendering, and the episodes probe"
priority: 5
requires: [human:gate]
---

Imported from issue #660

Follow-up to T186 (#508, PR #658). These are the non-blocking findings from the round-3 second read. Sending is already guarded; these are the remaining gaps.

1. **S3: advice is fail-open (spec §4.1, "suppressed everywhere derived").** A skill whose only provenance turn is retracted is still treated as held.
   - `generate` mirrors the ask and reports `gaps: ()`.
   - `ats.classify_keyword` returns `missing (have it)`.
   - Fix: make the "holds" rules (`generate._holds`, `ats`) consult `withdrawn_turn_ids(store)`.
2. **S4: drafts render retracted entries.** `generate._select` writes retracted master entries into `cv.md` and `letter.md`, so `prepare` then always refuses.
   - Fix: have `_select` omit entries that `claim_is_backed` would refuse.
3. **S2: wrong refusal cause.** A retracted non-episode line is refused with "no per-use approval backs this line". The message should name the retraction instead.
4. **S1: episodes branch unpinned.** The episodes branch of the `claim_is_backed` guard has no pin: skipping it leaves 261 tests green. Add an approved episode on a withdrawn turn to `retracted_claims_still_traced()`'s probe.

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
