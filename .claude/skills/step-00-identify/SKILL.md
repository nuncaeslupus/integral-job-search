---
name: step-00-identify
description: Step 0 (`identify`) of the candidate process — resolves who the candidate is, before any file under profiles/ is touched. Do NOT use for a session already past identification (current_step is already recorded and not `identify`) — resume there instead via the process runtime.
---

# step-00-identify

The candidate is greeted by name, told when they were last here and where they stopped, and can carry on without re-explaining themselves.

CANARY: step-00-identify-loaded-2026-08-18-f42ed484-4826385d60392bea

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 0 (`identify`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `identify` as where this candidate should
be. Phase: **first_run**.

## Preconditions and inputs

None — this is the one step with no preconditions, because every other step depends on this one. Nothing under `profiles/` is read or written before it completes, including on a question that seems to need no identity.

**Reads:** `profiles/*/identity.json` — display names only, to offer a list. No other file in any profile opens until a handle resolves.

## Protocol — the manner, not the mechanism

- Open by asking who this is, in one short friendly line.
- Resolve in order: an explicit handle or name; exactly one profile exists — name it and ask for confirmation, never assume; otherwise list display names and ask; no match — offer to create a profile.
- On a first run, ask what they would like to be called and derive a directory-safe handle from the answer. A nickname is fine; a legal name is not required and is not asked for. The name they choose is the identifier, unless it is already taken.
- Record the language they wrote in — the rest of the process happens in it.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Nice to meet you, Marcos. Let me get your profile set up — one moment."
…then, once it is done…
"Thanks for waiting. Here's how this works: …"
```

**Never:**

- Never read or write anything under `profiles/` before a handle resolves — not even to answer a question that seems to need no identity.
- Never guess an identity from one profile existing — confirm it, always.
- Never invent a suffix (`-2`) to resolve a handle collision — ask for something that tells the two people apart.

## Stop rule

A handle is resolved and confirmed, or a new profile is created. **Hard cap: three attempts** — past that, say plainly that who this is cannot be told, and stop rather than guess.

## When declined

A candidate who will not identify themselves cannot be served, and this is the one place where that is true — say so plainly and without pressure, and offer to answer general questions that touch no stored data. No evidence row is written for an unidentified session.

## Outputs

`identity.json` (handle, display name, language, locale, created_at) on a first run; `session/state.json` touched on every run.

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
"Hello again, Marcos — last time we were partway through your work history, about three weeks ago. Pick up there, or something else?"
```

Writes `last_activity` immediately, before any other step begins.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`cross_user_leaks == 0`**,
owned by **S3**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `identify` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-identify.json`, never to a shared or
global path.

## Gotchas

- **Enforce the boundary below the tool, not only inside it.** A `PreToolUse` hook (S3) refuses any `profiles/` read or write outside the identified handle, regardless of what the conversation believes it is doing — a rule the process cannot violate is stronger than one it is asked to respect.
- Display names are the only cross-profile data any session ever reads, and only to offer a choice — nothing else leaves the machine.
