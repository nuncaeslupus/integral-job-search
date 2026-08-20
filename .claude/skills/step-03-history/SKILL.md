---
name: step-03-history
description: Step 3 (`history`) of the candidate process — builds the candidate's story bank of episodes from past roles. Do NOT use for scoring or presenting traits — that is step 4, which reads this step's evidence but never asks the candidate to rate themselves.
---

# step-03-history

The candidate tells the story of the work they have done — including what went wrong — and ends with a story bank they own and can see.

CANARY: step-03-history-loaded-2026-08-18-f42ed484-76b243ddb405a4f1

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 3 (`history`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `history` as where this candidate should
be. Phase: **first_run**.

If the runtime (`integral.step_runtime.offered`) is not offering `history` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

A resolved handle. Better with Intake behind it, and does not require it: with no CV the step asks about roles as it goes.

**Reads:** `cv/master.json` — optional, used to ask about specific roles rather than in general. `profile/stories.jsonl` from previous runs.

## Protocol — the manner, not the mechanism

- Ask about one role at a time, starting with the most recent: what the work actually was, what went well, what went badly, and why it ended.
- **Successes carry as much as failures.** Ask what they are proudest of and how they got there; take the failure when it comes rather than digging for it.
- Follow the candidate rather than the checklist — someone who starts talking about the manager who left is handing over the episode already; take it.
- **Every negative episode gets a follow-up about what was learned or what they would do differently** — never a judgement.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Let me write that one down before we carry on — a moment."
…then, once the work is finished…
"That's it written down. …"
```

**Never:**

- Never press a candidate who does not want to discuss a departure — a job ending badly is already useful without the details.
- Never ask why a gap exists in a tone that requires an excuse — ask what they were doing then.
- Never dig for a failure to hit a quota — the v1 floor requiring a third of episodes to be failures is **superseded** and must not be re-introduced (see Gotchas).

## Stop rule

The current or last role plus two earlier ones have an episode each, or the candidate says that is enough. **Hard cap: 8 episodes or 18 questions, whichever first.** Halfway to the cap, check in rather than pressing on.

## When declined

History is offered. A candidate who does not want to tell stories keeps a working profile — traits will read `insufficient` and the ranking leans on constraints and stated preferences, worse but not broken. Say that once, drop it.

## Outputs

`profile/stories.jsonl` (derived episodes, each linked to what it evidences), evidence rows including trait evidence.

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
"That's a good bank — seven episodes, and the one about the failed migration will earn its keep the first time someone asks how you handle pressure. Traits next — carry on?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`story_dimension_linkage == 1.0`**,
owned by **T8**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `history` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

The script writes its result to the candidate's own tree at `session/checkpoint-history.json`, never to a shared or
global path.

## Gotchas

- **`story_failure_fraction >= 0.33` is superseded and must not be gated on.** The concern behind it is sound — a bank of only rehearsed successes reveals little — but a floor makes the tool dig for failures to satisfy a number, which the protocol above forbids. Once a bank holds four or more episodes it should contain both kinds; the fraction is *reported*, never *floored*.
- Episodes default to `disclosure: private` — recounting a failure to the tool is not consent to send it to a company; no episode reaches an employer-bound document without per-use approval (step 11).
