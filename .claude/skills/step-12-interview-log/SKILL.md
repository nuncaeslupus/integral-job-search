---
name: step-12-interview-log
description: Step 12 (`interview_log`) of the candidate process — prepares for, then records, one candidate interview. Do NOT use for drafting the application itself — that is step 11, which this step reads but never regenerates.
---

# step-12-interview-log

The candidate walks in prepared, and afterwards turns what happened into better preparation for the next one.

CANARY: step-12-interview-log-loaded-2026-08-18-f42ed484-11721cfebdaa3515

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 12 (`interview_log`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `interview_log` as where this candidate should
be. Phase: **per_opportunity**.

If the runtime (`integral.step_runtime.offered`) is not offering `interview_log` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

An offer with status `applied` and an interview arranged, for the preparation half; a completed interview for the recording half. Either half runs without the other.

**Reads:** The offer and its extraction; `cv/generated/<offer_id>/`; `profile/stories.jsonl`; `interviews/*` from earlier interviews, including for other offers.

## Protocol — the manner, not the mechanism

- *Before:* work out what this employer is likely to press on — from the advert's emphases, the application's claims, previous interviews — and rehearse the episodes that answer it, using the bank rather than inventing.
- **The mock interview is a role-play, and it is strict.** Say so before it starts: from that point the tool is the interviewer and nothing else — no coaching mid-answer, no breaking character. It ends when it ends, then the ordinary voice comes back with the feedback. Offer dictation.
- *After:* record what was actually asked, what went well, what they wish they had said, and the outcome when it comes — and **give the feedback then**, while it is fresh.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Writing that up while it's fresh — one moment."
…then, once the work is finished…
"That's it recorded. …"
```

**Never:**

- Never break character mid-rehearsal to coach or reassure — the discomfort of an unhelped answer is the entire exercise.
- Never press for a real interview's details when the candidate clearly does not want to relive it — ask once, gently, later, never twice.

## Stop rule

*Before:* the likely questions have an answer each, or the candidate says they are ready. **Hard cap: 10 rehearsed questions.** *After:* the questions asked and the outcome are recorded, or the candidate stops.

## When declined

Both halves are offered. Declining preparation is common and fine. Declining to log an interview loses the lesson and nothing else; ask once, later, never twice.

## Outputs

`interviews/<offer_id>/` — preparation notes, questions asked, outcome, lessons — immutable, and exempt from purge regardless of the offer's status.

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
"Logged. They pushed hard on on-call and you didn't have much — worth building that into a story before the next one. How did it feel?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`interview_lesson_linkage == 1.0`**,
owned by **S6**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `interview_log` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-interview_log.json`, never to a shared or
global path.

## Gotchas

- A later interview for the same offer is a new, immutable record, not an edit of the old one — preparation notes are the only part of this step ever replaced.
- Interview records never leave the machine and never reach a future employer-bound document without per-use approval; a rejection reason is never quoted back to any employer.
