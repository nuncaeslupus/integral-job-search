---
name: step-01-intake
description: Step 1 (`intake`) of the candidate process — captures the candidate's CV or working history into the store, with provenance. Do NOT use for a step that already has claimed_facts and only needs a correction pass on residence or pay — that is Constraints (step 2), not Intake.
---

# step-01-intake

The candidate sees their working life written down — from the CV they already have, or built with them if they have none — and can correct it.

CANARY: step-01-intake-loaded-2026-08-18-f42ed484-23a819c5a700052e

**Offered.** May be declined at any time; declining never blocks a required step downstream (§2.5).

## When to load

Load when the candidate's session is at step 1 (`intake`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `intake` as where this candidate should
be. Phase: **first_run**.

If the runtime (`integral.step_runtime.offered`) is not offering `intake` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

A resolved handle (step 0). Nothing else: someone with no document, no recent CV and no idea where to start is expected here, and it must work for them without apology.

**Reads:** `cv/source/*` if the candidate supplies a PDF or DOCX; `cv/master.json` if a previous run built one. Both optional.

## Protocol — the manner, not the mechanism

- Say what this is for — that everything captured makes the search better, that it stays on this machine, and that the tool is on their side rather than assessing them.
- Take whatever exists: a document to parse, or a conversation. Parsing writes **claims with provenance**, never established facts — "Barcelona" from a CV header is what the document says, not where they live.
- With no document, work backwards from the last job through the ones before, asking for what a CV would carry, and stop when the shape of a career is there, not when a form is full.
- Establish where they live — it decides currency, work authorisation, commutable borders and how a foreign employer would tax them.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Let me read that properly and pull out what's in it — one moment."
…then, once the work is finished…
"Thanks for waiting — that's your history in. …"
```

**Say what the document did not give you, before moving on.** `import_document` returns
what happened to the file — it may be a format nothing here reads, a scan with no text
layer, a corrupt archive, or a document that imported and yielded no contact address
and no year. Every one of those is ordinary and none of them is a reason to stop. What
is not allowed is carrying on as though the read succeeded: the candidate then answers
questions their own CV already answered, and has no way to know why.

Say it in one line, in their language, then continue by conversation for the part the
document did not cover:

```text
"That file didn't open here — I'll take it the long way instead, if that's all right."
"I've got your history, but no email address came out of the file. What's the best one?"
```

Then record that you said it:

```python
from integral.cv_store import acknowledge_read_problems, unreported_read_problems
```

`unreported_read_problems(store)` is the list; `acknowledge_read_problems(store)` marks
them told. **Until it is called, `run_checkpoint.py` will not report this step covered**
— that is the enforcement, and it is deliberately reporting rather than repairing (T97).
Never call it before saying them.

**Never:**

- Never ask here for a legal name, an address, a telephone number, an identity number, a date of birth or a photograph — none improve a *search*. They are collected by step 11, for the document that actually needs them, when it needs them.
- Never produce a document here — no PDF, no DOCX. A CV written before there is an advert to write it for is worse than what step 11 produces.

## Stop rule

Every role in the supplied document is represented, or — with no document — the current or last role plus at least two earlier ones, or the candidate says that is enough. **Hard cap: 12 questions** — a CV parses in seconds and a career sketches in a handful of exchanges; past that this stops feeling like help.

## When declined

Intake is offered, and declining it is ordinary: skip to Constraints, which then asks from scratch instead of confirming. Say what is lost in one line — the search will lean more on questions later — and never repeat it.

## Outputs

`cv/master.json` — roles, tools, certifications, languages, every claim's provenance; `profile/evidence.jsonl` rows for everything said. No document is produced here.

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
"That's your history down — twelve years, four roles, and the Catalan I nearly missed. Next is what would rule a job out — the quickest way to stop me showing you things you'd never take. Shall we?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`intake_field_provenance == 1.0`**,
owned by **S4**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `intake` produces is present, nothing is
left outstanding in the recorded position, and no document read that fell short is still
unsaid (T97) — never by asking the model to eyeball the transcript and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

The script writes its result to the candidate's own tree at `session/checkpoint-intake.json`, never to a shared or
global path.

## Gotchas

- A newer CV **adds** claims and marks superseded ones rather than overwriting — a role removed from a candidate's public CV survives in the store, because the store is the CV plus everything it omits.
- `cv/source/*` is stored unmodified and never sent anywhere; `master.json` is never transmitted as-is, to a model or an employer.
