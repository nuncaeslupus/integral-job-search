---
name: step-11-application
description: Triggered by a candidate's session at step 11 (`application`) of the job-search process (`status/spec-v2-steps.json`) — drafts a CV and letter for one specific shortlisted offer. Do NOT use for preparing for the interview that follows an application — that is step 12, which reads this step's generated documents.
---

# step-11-application

The candidate gets a CV and a covering letter written for one specific advert, drawn only from things they actually said.

CANARY: step-11-application-loaded-2026-08-18-f42ed484-1acb16a96c555ddf

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 11 (`application`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `application` as where this candidate should
be. Phase: **per_opportunity**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `application` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

An offer with status `shortlisted`, and `cv/master.json` with enough in it to draw on. With a thin store, say what is missing and offer Intake or History rather than producing a padded document.

**Reads:** `cv/master.json`; the offer and its extraction; `profile/stories.jsonl`; previous versions in `cv/generated/<offer_id>/`.

## Protocol — the manner, not the mechanism

- Select from the store against what the advert asks for, draft, and show the candidate what was chosen and what was left out — omissions are as much a decision as inclusions. **Every claim traces to a store entry.**
- Use the advert's own language, with restraint, only over ground the candidate actually holds — mirroring a phrase the candidate cannot back is a lie with good vocabulary.
- Where the advert asks for something they lack, say so and offer the options honestly: apply anyway and address the gap in the letter, or leave this one.
- **This is where personal details are collected** — the name to print, contact details, whatever this employer's form requires — asked for the document being produced, not gathered speculatively months earlier.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Drafting the CV and the letter for this one — this takes a moment."
…then, once the work is finished…
"Thanks for waiting — here's the draft. …"
```

**Never:**

- Never claim a qualification, a year of experience or a language the store does not hold — the generated document is the candidate's word, the one thing here that reaches a stranger.
- Never include a story-bank episode without per-use approval — recounting a failure to the tool was never consent to send it to a company.

## Stop rule

A CV and a letter exist for this offer and the candidate has approved them, or has parked them. **Hard cap: three regeneration rounds per offer**, after which the useful move is to talk about what is wrong rather than generate a fourth.

## When declined

Offered per offer. Declining generates nothing and leaves the offer `shortlisted`. A candidate who wants to write their own letter and only use the CV gets exactly that.

## Outputs

`cv/generated/<offer_id>/v<N>/` — CV and letter, versioned, plus a manifest of which store entries each claim came from. On send, `applications/<offer_id>/` records what went and when, immutable thereafter.

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
"That's the CV and letter for the Girona role. I've led with the migration work and left out the teaching — say if that's wrong. Ready to send, or sit on it?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`cv_generation_traceability == 1.0`**,
owned by **S4**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `application` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-application.json`, never to a shared or
global path.

## Gotchas

- **Never overwrites.** A regeneration writes `v<N+1>` and preserves every earlier version — an earlier one may already be with an employer.
- The tool stops one step short of sending: the documents or the text to paste. The candidate presses send.
