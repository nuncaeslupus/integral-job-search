---
id: t-b99c84ad
title: "T289: Exclusion backfill skips advert-tied refusals, so steps 5 and 10 surface almost nothing"
priority: 5
requires: [human:gate]
---

Imported from issue #668

Found by the second reader on #667 (T220), non-blocking there.

`sourcing_exclusions` skips rows with `about.kind == "offer"`. But the writers for steps 5 and 10 always tag the advert: `capture_offer_decision_reason` (step 10 `rule_out`, `profile_capture.py:333-343`) and `reaction_elicit` (`:653-673`). So a topic refusal given as a rejection reason — e.g. "no me enseñéis más bancos" — is never surfaced; only hand-captured untagged rows are.

The code comment's rationale is half wrong: `record` can cover such a row; the real obstacle is that an acknowledgement cannot close an advert-tied row, and most rejection reasons contain a refusal cue, so listing them would block the backfill from clearing.

Proposed: list advert-tied refusals and let an acknowledgement close one by its whole text. Also out of T220's scope: steps 1, 11, 12 take free text and are not covered (F2); `process_spec.py` comment claims a runtime check that is actually a test (F3).

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
