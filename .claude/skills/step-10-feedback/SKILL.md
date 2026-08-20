---
name: step-10-feedback
description: Triggered by a candidate's session at step 10 (`feedback`) of the job-search process (`status/spec-v2-steps.json`) — captures what the candidate thinks of the ranked offers and re-ranks. Do NOT use for writing an application document from what was said here — a rejection reason given in this step is never quoted to any employer.
---

# step-10-feedback

The candidate says what they think of the offers in front of them, and watches the list move because of it.

CANARY: step-10-feedback-loaded-2026-08-18-f42ed484-06b10b617d49b456

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 10 (`feedback`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `feedback` as where this candidate should
be. Phase: **loop**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `feedback` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

A ranking has been presented. Nothing else — this step exists to catch what someone says while looking at real jobs, the most informative moment in the process.

**Reads:** The current `rankings/<timestamp>.json` and the offers it names, with their extractions; `profile/weights.json`, which this step's output revises.

## Protocol — the manner, not the mechanism

- Follow, do not survey. Most feedback arrives unprompted; the step's main job is to be listening when it does.
- When prompting, prompt once and lightly — is there anything here worth ruling out straight away? Never work down the list asking for an opinion on each.
- Capture their words, extract afterwards, and **show the consequence immediately** — which offer moved, and which sentence caused it.
- **Expect the conversation to leave the list.** A discovered preference or a new search is the most valuable outcome here — take it, and run a fresh search rather than steering back to the screen.

**Never:**

- Never infer an offer status from silence — `screened_out` and `shortlisted` are recorded from what the candidate actually said.
- Never work down the list item by item asking for an opinion on each — that is a survey, not following.

## Stop rule

The candidate stops talking about the offers, or every offer they raised has a recorded reaction. **Hard cap: no prompt is issued more than twice in a session.**

## When declined

Offered, and the most declinable step in the process — decline is recorded so the prompt does not return next session. Unprompted feedback is still captured, because that is them volunteering it.

## Outputs

Evidence rows of kind `reaction` and `outcome`; offer status changes with `status_changed_at`; a recomputed ranking.

## Boundary

**Invite forward; never close by offering to stop.** Stopping is always allowed and never the
suggestion — the exit is offered only when the session has actually run long, or the candidate
sounds tired, and never as the standard close of this step. Naming it every time asks someone who
has answered four steps four separate times whether they would rather leave.

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Noted — agencies out. That dropped three of them and pushed the Girona role to the top. Anything else jump out?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`feedback_traceability == 1.0`**,
owned by **T21**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `feedback` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-feedback.json`, never to a shared or
global path.

## Gotchas

- A rejection reason recorded here triggers a weight refit (step 6) — this step's output is an input to an earlier one, and that loop is the product, not a defect.
- A rejection reason given here is the candid version and never leaves the machine — different from one given to an employer.
