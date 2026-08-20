---
name: step-08-understanding
description: Step 8 (`understanding`) of the candidate process — extracts dimension values and verbatim evidence spans from new offers. Do NOT use for ordering offers for presentation — that is step 9, which reads this step's extractions.
---

# step-08-understanding

The candidate gets offers described in the same vocabulary as their profile, with the ad's own words as evidence.

CANARY: step-08-understanding-loaded-2026-08-18-f42ed484-c21eedd944b4adae

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 8 (`understanding`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `understanding` as where this candidate should
be. Phase: **loop**.

If the runtime (`integral.step_runtime.offered`) is not offering `understanding` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

New or changed offers to read, and a dimension model that loads and validates. A model that fails validation stops this step rather than extracting against a broken vocabulary.

**Reads:** `offers/*.json`; `dimensions/*.yaml`; previous extractions. For the local annotation pass only: `profile/constraints.json` and `profile/weights.json` — read on this machine and never sent with the advert.

## Protocol — the manner, not the mechanism

- **Automatic — no conversation.** The model is the last resort, not the first: normalise the advert, take what patterns and keyword rules can take outright (salary, contract type, hours, location, technologies), and send to a model only the dimensions those could not settle.
- Handle negation as inversion, not absence — "no on-call" is evidence *against*, not missing evidence.
- **Annotate the offer against the candidate immediately afterwards, locally** — a second pass, on this machine, that the model never sees. The annotation is a distinct, recomputed artefact, never a field inside the extraction.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Reading those adverts properly — a moment while I go through them."
…then, once the work is finished…
"That's them read. …"
```

**Never:**

- Never send the candidate's profile with the advert — extraction reads only the advert text; the annotation pass runs afterwards, locally, with no model call.
- Never cite an outside-source fact (a review site, a company page) as though the employer wrote it — mark it as not from the advert.

## Stop rule

Every new or changed offer has an extraction. **Hard cap: a per-run extraction budget**, since this is the step that costs model calls.

## When declined

Not applicable — nothing is asked. A candidate may skip outside-information lookups as a standing preference, recorded in `constraints.json`.

## Outputs

`extractions/<offer_id>.json` — per dimension a score, evidence spans, a provenance marker; candidate-independent. `annotations/<offer_id>.json` — the same offer read against this candidate, derived, never shared.

## Boundary

**Invite forward; never close by offering to end the session.** Leaving is always allowed and
never the suggestion — the exit is offered only when the session has actually run long, or the
candidate sounds tired, and never as the standard close of this step. Naming it every time asks
someone who has answered four steps four separate times whether they would rather leave.
This governs the **exit** alone. §3.3's *offered skip* — "we can stop here and go look at real
jobs with what I have" — is a move **forward** to a provisional ranking, not a way out, and is
offered at the end of every first-run step exactly as that section requires.

Usually silent, folded into step 9's presentation. When run alone, it says:

```text
"Read the fourteen new ones. Three don't say anything about how they work, which is itself worth knowing."
```

Writes `last_activity`.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`extraction_macro_f1 >= 0.75`**,
owned by **T15**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `understanding` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide. Exit 0 means that half is satisfied; exit 1 means it is not (still open, or blocked on
a missing input); exit 2 means the candidate or step could not be read. The script writes its
result to the candidate's own tree at `session/checkpoint-understanding.json`, never to a shared or
global path.

## Gotchas

- Re-extracting an unchanged offer against an unchanged dimension model spends money to reproduce a result — replace only what changed or whose extraction predates the current model version.
- Annotations are cheaper and staler than extractions: recomputed whenever constraints or weights move, without re-reading the advert.
