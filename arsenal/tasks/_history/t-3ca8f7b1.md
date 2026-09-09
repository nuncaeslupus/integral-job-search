---
id: t-3ca8f7b1
title: "T156: a paraphrase walks past the eight-word shingle, and the sweep reports the story as withheld rather than as undecidable"
priority: 10
deps: [t-6d3fac96]
tags: [APPROVAL]
workspace: BACKEND
status: merged
---

## Acceptance gate

```gate
paraphrased_substance_reported_as_withheld == 0
evidence: status/evidence/T156.json
key: paraphrased_substance_reported_as_withheld
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_substance_sweep.py -q
uv run --extra dev python -m integral.approval
```

## The defect

`approval._carries` decides whether a generated document carries an episode's
substance by **normalised eight-word shingles**. Its own docstring is honest
about the limit:

> It does not beat a genuine paraphrase, and nothing cheap does; the upgrade
> path is an embedding comparison, at a model call per episode per document.

Found as **C3** by the second reader on #409, which verified it behaves
identically on `origin/main` and correctly refused to widen T114's diff to it.
The case: an episode never approved and never named in the manifest, its
substance **paraphrased** into the CV headline. The paraphrase reaches the
employer; the sweep does not see it.

**It is fail-open**, and in the one direction §6.2 will not take: substance
going out that no per-use approval backs. T114 closed the *manifest-trusting*
half of this — that the sweep read `disclosed` from the manifest rather than
from the documents — and this is the half T114's scope sentence explicitly does
not cover.

## The question this task has to settle

**It is open, and this file does not answer it.** What must not survive is the
sweep reporting a confident **"not disclosed"** over a document it is not
equipped to adjudicate. A matcher that cannot beat paraphrase is a fine matcher;
a matcher that cannot beat paraphrase *and says the story was withheld* is a
false negative wearing a verdict.

Two defensible answers, and the task is to choose one, argue it from `approval`'s
own module docstring and CLAUDE.md § *Fixtures for a correctness-critical gate*,
and write the argument down next to the choice:

1. **Detect more.** Take the docstring's named upgrade path, or a cheaper
   approximation of it that runs offline in the gate. Anything chosen here must
   be measured against **over-refusal** as hard as against under-refusal: a
   matcher that flags every document sharing vocabulary with an episode blocks
   every draft, and a blocked draft is a regeneration the candidate pays for.
   The existing over-refusal controls
   (`test_an_untouched_draft_of_two_overlapping_episodes_is_clean`) are the floor,
   not the ceiling.
2. **Report undecidability.** Keep the shingle matcher and stop it *speaking for*
   the cases it cannot reach: where an episode's substance is plausibly present
   but not shingle-matched, the sweep returns a third state — not `disclosed`,
   not `withheld` — and `payload.json` and the boundary refusal are told which
   one they got. This is the cheaper answer and it is not the weaker one: it
   converts a silent fail-open into a visible one, which is what this repository
   has repeatedly found to be the durable half of a fix.

Whichever is chosen, **the losing branch's risk is recorded in the module
docstring next to the choice**, in the idiom the five #408 rounds established.

## What the metric counts

`paraphrased_substance_reported_as_withheld` is the number of constructed states
in which an episode's substance reaches a generated document **in paraphrase**
— rewritten, reordered, or synonym-substituted such that no normalised eight-word
window survives — and the sweep's outcome is not the one the chosen rule
requires.

The states evaluated are the denominator, asserted as a **floor** in the
`naming.MINIMUM_SCANNED` style (T100), so a control list that shrank to nothing
cannot score a serene zero.

**Verify the metric is non-zero under today's unmodified behaviour before
writing a line of the fix.** Under answer 2 in particular it is easy to write a
gate that today's code already satisfies — the exact defect the second reader
caught in T155's own gate, where a conjunction let one of the two answers score
zero with no change at all.

## Scope

* Whatever is added must keep `episode_approval_coverage`'s existing meaning and
  must not relabel the corpus to make a number fall.
* `manifest_disclosures_compared` (212) and `T46.detection_probes` (19) are
  committed with floors; a change here must not lower either.
* Every accepted case is **committed into the fixtures**, not answered in a
  comment — CLAUDE.md's rule, and the reason T114's first review round blocked.

Filed from the second-reader report on #409 (C3), which named it rather than
widening that diff.
