---
id: t-12ffda4f
title: "T257: 28 adverts from a robots-blocked board are reachable as elicitation stimuli"
priority: 5
requires: [human:gate]
---

Imported from issue #339

Found by the independent second read of #307 (T98), F7. Not that PR's defect — `reaction_elicit.py`'s diff there is docstring-only — but #307 is what makes the path candidate-facing and `corpus/draws.yaml` is what newly declares the source a legitimate draw. Filed so the finding does not live only in a PR comment.

## The defect

`reaction_elicit.check_stimulus` early-returns for `source == "corpus"`, so the permitted-source check is skipped entirely for a corpus-drawn stimulus.

`tecnoempleo` is listed in that same module's `BLOCKED_SOURCES` — its robots.txt is `Disallow: /` for ClaudeBot. **53 raw corpus rows come from it, and 28 of those are in the `elicitation` split**, so `corpus_stimuli` will put an advert from a board we refuse to fetch live in front of a candidate.

The tool declines to read that board at the moment, and then shows the candidate what it read from it earlier. Whether that is acceptable is the owner's ruling, not the code's — what is wrong today is that nothing states the answer and nothing checks it.

## Also flagged in the same read, same module

`stimulus_from_record` accepts `source == "corpus"` with no url and bypasses the evaluation-split check entirely, because `collect_stimuli` calls only `check_stimulus`, which early-returns. **Not reachable today** — there is no production caller of `stimulus_from_record` outside the module, and it is pre-existing on `main` — but it is the same early return, and a future caller inherits both holes at once.

## What a fix has to decide

1. Does a stored advert from a blocked board remain showable as a stimulus? The ban is on *fetching*; the corpus row was fetched before the block was recorded. Either answer is defensible and neither is written down.
2. Whichever it is, the check has to run for `source == "corpus"` rather than being skipped by the early return — including the evaluation-split half, which is what `corpus_scope`'s `stimulus_pool_evaluation_overlaps` measures from the other side.

## Suggested gate

`blocked_source_adverts_reachable_as_stimuli == 0` — named after the wrong outcome rather than after a category, per T123. The denominator (adverts examined) is a floor, because zero over an empty pool is the vacuous pass.

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
