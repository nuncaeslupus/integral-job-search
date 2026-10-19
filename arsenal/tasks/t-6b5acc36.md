---
id: t-6b5acc36
title: "Ranked-view close: wording pins and stale copies left open by the T233 review"
priority: 5
requires: [human:gate]
---

Imported from <https://github.com/nuncaeslupus/integral-job-search/issues/791>

Non-blocking findings left open by the second reader on #790 (T233), rounds 1–3. None is fail-open on the merged head; each is a pin or a stale copy.

- `step-09-ranking`: "never ask the candidate for salary" is prose only (the code half is pinned).
- The ask-before-ranking wording check passes a contradiction appended after the rule sentence (one without the word "rank" in step-07, one containing "not" in step-09).
- `status/spec-v2-steps.md`: the quoted closing line runs straight to "Want to?" with no list marker; only the following sentence carries the rule.
- Stale copies of the old ask-whether-to-rank question: `docs/spec-v2-steps/spec-annotated.md` (~line 684) and `spec-reader.html` (~line 767).
- `step-08-understanding` standalone close ("…Shall I?") asks a question before the ranking.
- L1 with distinct salaries and no weights returns nothing missing; whether "weights missing" is said hinges on an exact tie.
- The gate's counterfactual tries one fixed answer at a time, so units with two causes score `spurious = 1` outside the single-axis grid although the claim is true (four inputs listed in https://github.com/nuncaeslupus/integral-job-search/pull/790#issuecomment-6042846452).

Reports: https://github.com/nuncaeslupus/integral-job-search/pull/790#issuecomment-6040138136 , #issuecomment-6041742709 , #issuecomment-6042846452

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
