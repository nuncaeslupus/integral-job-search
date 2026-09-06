---
name: step-09-ranking
description: Step 9 (`ranking`) of the candidate process — presents the live offers in order, each position's reason cited from the ad. Do NOT use for collecting the candidate's opinion of what they see — that belongs to step 10, which follows this one.
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

If the runtime (`integral.step_runtime.offered`) is not offering `ranking` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

Extractions for the live offers, and `profile/constraints.json`. Weights are optional: without them the ranking is L1 and says so.

**Reads:** `extractions/*`; `profile/constraints.json`; `profile/weights.json` — optional; `profile/traits.json` where a dimension is trait-side.

## Protocol — the manner, not the mechanism

- No questions — this step presents. **Presentation is half the specification**, not a rendering detail. Show a handful at a time, not forty.
- Lead with the offer and the one thing that most moved it, not with a score. A card: title and employer, facts as bullets (pay gross and net-equivalent, hours, location, contract), then one line of what actually matters — including the bad part.
- Where the list is rendered as a page, it is a template filled from the normalised offer JSON — never a paragraph assembled by a model.
- Where an offer is out of reach today but reachable, say what it would take and ask whether that is of interest, rather than assigning homework.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Scoring and ordering them against what you've told me — one moment."
…then, once the work is finished…
"Thanks for waiting — here's the order, and why. …"
```

**Never:**

- Never show what is unknown about an offer as neutral — an advert silent on hours is not an advert promising good ones.
- Never assemble the card's prose a paragraph at a time by a model — it is a template filled from the normalised JSON.

## Record what was shown, and say what was held back

Showing a batch is itself a fact, and it is the one that later turns into a
question worth asking. Two calls, around the list:

```python
from integral.presentation_log import partition, present, withheld_line

show, held = partition(store, ranked_ids)      # never `show` alone
present(store, show, at=now, phrase=phrase)
```

**Say the withheld count and the reason, every time.** `withheld_line(held)`
puts it in the shape the owner asked for — *"4 descartadas porque «son de
investigación»"*. A filter nobody is told about is indistinguishable from a
thin market, which is the same failure `step-07-sourcing` names for liveness,
arriving by a different route.

## Stop rule

A ranking is produced and presented. **Hard cap: the number shown at once**, so the list stays readable; the rest are available on request.

## When declined

A candidate can ask not to see rankings for now; the run still computes and stores one, so it is there when they come back.

## Outputs

`rankings/<timestamp>.json`, pinned to the `profile_revision` and the sufficiency level that produced it.

## Boundary

**Invite forward; never close by offering to end the session.** Leaving is always allowed and
never the suggestion — the exit is offered only when the session has actually run long, or the
candidate sounds tired, and never as the standard close of this step. Naming it every time asks
someone who has answered four steps four separate times whether they would rather leave.
This governs the **exit** alone. §3.3's *offered skip* — "we can stop here and go look at real
jobs with what I have" — is a move **forward** to a provisional ranking, not a way out, and is
offered at the end of every first-run step exactly as that section requires.

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Here are the top five. The Girona one is first mostly because they say 'we don't do on-call' outright, which is worth about €400 a month to you. I'd react to a couple of these before anything else, because what you say about them is what moves the order next time. Want to?"
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
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

**`explained_fraction` is built (T19), so exit 0 is reachable here.** What it measures is
that every ranked offer cites the advert's own words for each dimension that moved its
position — not that the order is right. `rank_spearman` is the gate for that, and it is
T20's, still open: a step that explains itself well has not thereby been shown to rank well.

The script writes its result to the candidate's own tree at `session/checkpoint-ranking.json`, never to a shared or
global path.

## Gotchas

- Every ranked offer must cite at least one verbatim span per contributing dimension (`explained_fraction == 1.0`) — calibrated against a blind manual ranking (`rank_spearman >= 0.60`).
- A ranking whose pinned revision is behind the current one is shown as out of date with a one-click recompute, not silently served stale.
