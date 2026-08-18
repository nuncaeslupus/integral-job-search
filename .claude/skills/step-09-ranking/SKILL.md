---
name: step-09-ranking
description: Triggered by a candidate's session at step 9 (`ranking`) of the job-search process (`status/spec-v2-steps.json`) — presents the live offers in order, each position's reason cited from the ad. Do NOT use for collecting the candidate's opinion of what they see — that belongs to step 10, which follows this one.
---

# step-09-ranking

The candidate sees the live offers in order, each with the reason it sits where it does, in words from the advert and numbers in their currency.

CANARY: step-09-ranking-loaded-2026-08-18-f42ed484-59789561a5c8873b

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 9 (`ranking`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `ranking` as where this candidate should
be. Phase: **loop**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `ranking` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

Extractions for the live offers, and `profile/constraints.json`. Weights are optional: without them the ranking is L1 and says so.

**Reads:** `extractions/*`; `profile/constraints.json`; `profile/weights.json` — optional; `profile/traits.json` where a dimension is trait-side.

## Protocol — the manner, not the mechanism

- No questions — this step presents. **Presentation is half the specification**, not a rendering detail. Show a handful at a time, not forty.
- Lead with the offer and the one thing that most moved it, not with a score. A card: title and employer, facts as bullets (pay gross and net-equivalent, hours, location, contract), then one line of what actually matters — including the bad part.
- Where the list is rendered as a page, it is a template filled from the normalised offer JSON — never a paragraph assembled by a model.
- Where an offer is out of reach today but reachable, say what it would take and ask whether that is of interest, rather than assigning homework.

**Never:**

- Never show what is unknown about an offer as neutral — an advert silent on hours is not an advert promising good ones.
- Never assemble the card's prose a paragraph at a time by a model — it is a template filled from the normalised JSON.

## Stop rule

A ranking is produced and presented. **Hard cap: the number shown at once**, so the list stays readable; the rest are available on request.

## When declined

A candidate can ask not to see rankings for now; the run still computes and stores one, so it is there when they come back.

## Outputs

`rankings/<timestamp>.json`, pinned to the `profile_revision` and the sufficiency level that produced it.

## Boundary

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Here are the top five. The Girona one is first mostly because they say 'we don't do on-call' outright, which is worth about €400 a month to you. Want to react to any of these?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`explained_fraction == 1.0`**,
owned by **T19**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `ranking` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-ranking.json`, never to a shared or
global path.

## Gotchas

- Every ranked offer must cite at least one verbatim span per contributing dimension (`explained_fraction == 1.0`) — calibrated against a blind manual ranking (`rank_spearman >= 0.60`).
- A ranking whose pinned revision is behind the current one is shown as out of date with a one-click recompute, not silently served stale.
