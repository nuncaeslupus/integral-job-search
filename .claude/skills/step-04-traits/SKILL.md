---
name: step-04-traits
description: Step 4 (`traits`) of the candidate process — scores traits from accumulated evidence — never a personality quiz. Do NOT use for deriving weights or presenting a ranked list — those read `traits.json`, they do not produce it.
---

# step-04-traits

The candidate sees how they work — described from what they have said rather than from a personality quiz — with the episodes behind each line.

CANARY: step-04-traits-loaded-2026-08-18-f42ed484-730ac2a6d1508a06

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 4 (`traits`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `traits` as where this candidate should
be. Phase: **first_run**.

If the runtime (`integral.step_runtime.offered`) is not offering `traits` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

Trait evidence exists, which History normally supplies. With no evidence at all, say so and offer History instead of asking a person to rate themselves out of ten.

**Reads:** `profile/evidence.jsonl` rows bearing on trait dimensions; `profile/stories.jsonl`; `traits.json` from a previous scoring run.

## Protocol — the manner, not the mechanism

- Score first, ask second — most of the work is already done, and the candidate should see that before being asked anything.
- Present the scored traits with their evidence, invite disagreement, then ask about the traits still below the floor: **two independent episodes recorded on two separate occasions.** Ask for those by asking for another situation, never by announcing a quota.
- **Weight recent and relevant experience above the rest** — episodes carry `occurred_at`, so age is computable; evidence from long ago or a field the candidate has left counts for less and is never the sole support for a score.
- A candidate who disagrees with a score is right by default — record the disagreement as evidence and rescore.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Scoring what you've told me against the traits — bear with me a moment."
…then, once the work is finished…
"Thanks for waiting. Here's what came out of that: …"
```

**Never:**

- Never voice a judgement about whether an inference sounds like a stereotype — make it silently and act on it by asking a better question.
- Never assume an average score for a declined or unscored trait — that is an invented person.

## Stop rule

Every trait is either scored or explicitly `insufficient` with its count, and the candidate has seen the profile. **Hard cap: 10 questions.**

## When declined

Traits is offered, and the step people are most likely to find odd. Declining leaves every trait `insufficient`, which the ranking handles by not weighting them.

## Outputs

`profile/traits.json` (derived) — per trait a score with evidence row ids, or `insufficient` with a count. Phrased so it could survive into a letter: "works well under pressure", never `stress_tolerance: 0.72`.

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
"That's what I've got: you like a lot of autonomy, you're happier fixing than launching, and I don't have enough yet on how you take pressure. Next I'll put some real adverts in front of you and see what you make of them — that's where this starts paying off."
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`trait_evidence_sufficiency == 1.0`**,
owned by **T28**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `traits` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-traits.json`, never to a shared or
global path.

## Gotchas

- Scoring also triggers outside this step: at any step boundary, on request, or when the batch threshold of **20** new trait-bearing evidence rows is reached — this step's checkpoint may find scoring already current on entry.
- Trait scores never appear in a generated CV or letter, and never leave the machine.
