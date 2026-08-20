---
name: step-02-constraints
description: Triggered by a candidate's session at step 2 (`constraints`) of the job-search process (`status/spec-v2-steps.json`) — settles what would rule a job out — residence, pay floor, mobility, permits. Do NOT use for a candidate volunteering trait or history content mid-conversation — capture it and route to step 3 or 4, do not force it into a constraint field.
---

# step-02-constraints

The candidate settles what would rule a job out — and sees it as a short list they can correct, not a form they filled in.

CANARY: step-02-constraints-loaded-2026-08-18-f42ed484-9c81575b4c43384b

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 2 (`constraints`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `constraints` as where this candidate should
be. Phase: **first_run**.

If the runtime (`jobsearch.step_runtime.offered`) is not offering `constraints` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

A resolved handle. Runs whether or not Intake did; this step is required and Intake is not, so it can never depend on Intake's output existing.

**Reads:** `cv/master.json` and its claims — optional. `constraints.json` from a previous run — optional.

## Protocol — the manner, not the mechanism

- With claims available, open by showing what was inferred and ask for corrections; with none, ask directly.
- Cover residence and currency, work authorisation per country, languages and level, hours and availability, pay floor, employment mode, mobility (remote, commute, relocation, cross-border), and notice period. Ask warmly and one thing at a time.
- **Employment mode is a status or a preference, never a menu of arrangements.** The two modes that can be recorded are payroll employment and genuine self-employment (`employed`, `contracting`). Ask which one they are on now, or which one they would rather be on — "are you set up as autónomo?", or "would you consider going autónomo, or would you rather be on payroll?" — and record the answer against those two.
- Ask about the things that quietly rule out whole employers — sectors, causes, employer kinds, countries — using the prepared list of *usual suspects* as material to draw from, never a checklist to read aloud.
- An unconfirmed claim stays `unknown`; unknown neither passes nor vetoes, and surfaces later as something still owed.

**Never:**

- Never leave a field blank — every constraint field ends the step `stated`, `declined` or `unknown`, and a blank field is indistinguishable from a question nobody asked.
- Never read the usual-suspects list out as a checklist — pick what fits what they already said, and ask it as curiosity.
- Never offer *falso autónomo* as a mode the candidate might want: it is an illegal arrangement — being engaged as self-employed while working under an employer's direction and hours — and not one of the two recordable modes. It may be asked about as something happening to them now, and named when warning them off an advert; it is never put to them as a choice.

## Stop rule

Every constraint field is `stated`, `declined` or `unknown` — never blank. **Hard cap: 14 questions**, after which whatever is unresolved stays `unknown` and the step ends.

## When declined

A declined field records `declined`, distinct from `unknown`: it means do not ask again. The step continues to the next field. A candidate who declines everything still leaves with a valid constraints file in which nothing filters.

## Outputs

`profile/constraints.json` (derived), evidence rows for each answer. Unknowns are shown as unknowns, never hidden.

## Boundary

What the tool says out loud when the step ends, verbatim — the settled example from the spec:

```text
"Right — remote or Barcelona, nothing under €45k, and you'd rather not do defence work. That's already enough to search on. Carry on, or shall I show you a first pass now?"
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`constraint_field_resolution == 1.0`**,
owned by **T24**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `constraints` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-constraints.json`, never to a shared or
global path.

## Gotchas

- **Pre-sourcing starts here.** Once country, field and reach are settled, connector work can begin in the background while the conversation continues — nothing is shown and nothing waits on it.
- `declined` survives a re-run — declining is an answer, not a gap to re-ask.
