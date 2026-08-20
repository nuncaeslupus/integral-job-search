---
name: step-05-reactions
description: Triggered by a candidate's session at step 5 (`reactions`) of the job-search process (`status/spec-v2-steps.json`) — captures reactions to real adverts to learn what the candidate actually values. Do NOT use for fitting weights from a completed reaction set — that is step 6's job, which reads this step's evidence rows.
---

# step-05-reactions

The candidate reads real adverts and says what they make of them — and discovers what they actually care about, including things they would not have thought to state.

CANARY: step-05-reactions-loaded-2026-08-18-f42ed484-47771742655cf796

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 5 (`reactions`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `reactions` as where this candidate should
be. Phase: **first_run**.

If the runtime (`integral.step_runtime.offered`) is not offering `reactions` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

`constraints.json` exists, because stimuli must be adverts that could plausibly be theirs. Without constraints the step does not run.

**Reads:** `profile/constraints.json`. Stimuli — fetched live from multiple sources by preference; the corpus elicitation split as fallback when fetching is unavailable.

## Protocol — the manner, not the mechanism

- Show adverts and fragments of adverts, and ask open questions rather than ratings — what repels here, what would be worth knowing, which of two roles looks like the better fit and why.
- Mix whole adverts with fragments — the interesting reactions are often to one part.
- Vary the question; the same prompt fifteen times reads as a form.
- Capture their words verbatim and extract afterwards — never ask them to categorise their own reaction.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Pulling up a handful of real adverts for you to react to — one moment."
…then, once the work is finished…
"Right, that's a handful ready. …"
```

**Never:**

- **Stimuli are never invented.** An imagined advert reads plausibly and represents nothing — this is how wrong cues once entered the dimension model with gold examples demonstrating their own error.

## Stop rule

Fifteen stimuli reacted to, or the candidate stops. **Hard cap: 25 stimuli** — past that, reactions get shorter and less useful, which is worse than fewer of them.

## When declined

Offered. Declining means weights are fitted from forced choices alone (step 6) or not at all, and the ranking says it is working from less. This is also the step to stop early without comment — one-word answers mean someone has finished, whatever the count says.

## Outputs

Evidence rows of kind `reaction`, each tied to the offer id of its stimulus; fetched stimuli enter `offers/` as ordinary offers with status `new`.

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
"That's telling. You didn't mention money once, and you flinched at every mention of 'fast-paced'. Want to turn that into weights? It's what lets me put a number on a shorter commute."
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`elicitation_eval_overlap == 0`**,
owned by **T9**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `reactions` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-reactions.json`, never to a shared or
global path.

## Gotchas

- No advert used to elicit preferences is ever one the ranking is later scored against (`elicitation_eval_overlap == 0`) — without that split, `rank_spearman` would measure memorisation and pass while the ranking is worthless.
- Fetching stimuli sends a search shaped by constraints only — a role, a location, a salary band — never a profile, an episode or a trait.
