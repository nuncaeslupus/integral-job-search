---
name: step-06-preferences
description: Triggered by a candidate's session at step 6 (`preferences`) of the job-search process (`status/spec-v2-steps.json`) — turns reactions into salary-equivalent weights via forced pairwise choices. Do NOT use for presenting the ranked offer list itself — that is step 9, which reads `weights.json` as an optional input.
---

# step-06-preferences

The candidate sees what each thing is worth to them per month, in their own currency, as a list they can argue with.

CANARY: step-06-preferences-loaded-2026-08-18-f42ed484-db4e7c0c9cb5aa76

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 6 (`preferences`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `preferences` as where this candidate should
be. Phase: **first_run**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `preferences` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

Reaction evidence, or enough constraint and history evidence to seed the choices. With neither, explain that it would be guessing and offer Reactions instead.

**Reads:** Reaction evidence rows; `profile/constraints.json` for currency and pay floor; `weights.json` from a previous fit.

## Protocol — the manner, not the mechanism

- Forced pairwise choices between two realistic packages that differ on a few dimensions — never sliders, never "rate how important autonomy is out of ten", both of which measure what someone believes about themselves.
- Draw the pairs from what reactions suggested is contested. Dress them as real jobs rather than attribute lists — two plausible offers, described the way an advert would.
- Keep it moving, say what the answers are revealing as they go, and stop early when the fit is identifiable rather than running the full set for completeness.
- When a choice contradicts a stated preference, do not correct them — record both and let the fit reconcile it.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Turning those into weights now — one moment."
…then, once the work is finished…
"All set — that's your weights. …"
```

**Never:**

- Never use a slider or a 1-to-10 rating — both measure self-belief, not revealed preference.
- Never correct a candidate whose choice contradicts something they said earlier — record both.

## Stop rule

Enough choices for the part-worths to be identifiable, or the candidate stops. **Hard cap: 20 choices.**

## When declined

Offered. Without weights the ranking is L1: hard filters and defaults, explicitly labelled provisional. That is a real result, and saying so is more honest than implying the list is worthless.

## Outputs

`profile/weights.json` (derived) — part-worths in salary-equivalent terms, in the candidate's currency.

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
"So a shorter commute is worth about €200 a month to you, and remote about €600. Does that sound like you? We can look at real jobs now."
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`weight_salary_equivalent_roundtrip_error <= 0.01`**,
owned by **T10**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `preferences` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-preferences.json`, never to a shared or
global path.

## Gotchas

- Converting a dimension to currency and back must recover the part-worth within 1% (`weight_salary_equivalent_roundtrip_error <= 0.01`) — the number the candidate is shown has to be the number the ranking actually uses.
- Weights are derived, local and never transmitted. A salary expectation may only be shared with an employer through step 11, per-item approved.
