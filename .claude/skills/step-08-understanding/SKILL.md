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

**Reads:** `offers/*.json` (loop over the store with `integral.offers.load_offers`, which skips and reports an unreadable record rather than aborting, T230); `dimensions/*.yaml`; previous extractions. For the local annotation pass only: `profile/constraints.json` and `profile/weights.json` — read on this machine and never sent with the advert.

## Protocol — the manner, not the mechanism

- **Automatic — no conversation.** The model is the last resort, not the first: normalise the advert, take what patterns and keyword rules can take outright (salary, contract type, hours, location, technologies), and send to a model only the dimensions those could not settle.
- **Salary is looked for before an offer is called silent.** `integral.salary_recovery.recover_all` runs up to four lookups. Two always run: the advert's own body, then a canonical duplicate that states a band. The other two run **only when the caller supplies that route's seam** — the board's detail route needs `detail_reader`, the approximation needs `estimator`, and both default to `None`, so a call that passes neither performs two lookups and not four. It reports which routes were tried for each offer it could not price, and an offer dropped for having no salary must have been through every route that was available to it (T92) — which means supplying the seams, not counting the two that run for free. An estimate it returns is `Salary(stated=False)` and carries its basis; never write one into a stated field.
- **Read which skills each advert requires (T229) — this is the model's job, never a pattern's.** Alongside the dimensions, fill `skills` on the extraction: for every technology the advert names, one reading `{skill, role, span}`. **`skill` is the technology's plain name as `integral.stack_fit.VOCABULARY` spells it** (`Go`, `Python`, `Kubernetes`) — one technology, no parentheses, versions or glosses (not `Go (Golang)`, `Go 1.21`, `Go language`); two technologies are two readings. `span` is `{start, end, quote}`: the advert's own words for **that skill**, copied exactly, with `start`/`end` their character offsets in the advert as the extraction cites it — the title, one newline, then the text (NFC) — so `cited[start:end] == quote`, and the quote must itself name the skill (a real quote about Python does not ground a reading of Go). A reading names **exactly one technology**: `Java/Go`, `Go, Python o Java` and `Kotlin or Java` are refused, so write one reading per technology. A reading that names none or several technologies, whose span does not name its skill or is not in the advert, with an unknown `role`, or with no span is refused when stored and, if it ever reaches the store anyway, is ignored: the advert is then treated as unread.
  - **Store them with** `uv run python -m integral.skill_requirement store --handle <handle> --offer <offer_id> --readings <file.json>` (a JSON list of readings; `[]` for an advert that names no skill). It validates every reading against the stored advert, writes nothing and exits 2 if any fails, and otherwise sets `skills` in `extractions/<offer_id>.json`, creating that record if the dimension pass has not, and leaving every other field alone. This is the only step that fills `skills`; until it has run for an advert, that advert is unread.
  `role` is one of `required`, `alternative`, `plus`, `optional`. A candidate who rules out a skill they lack (`skill:go`) loses an advert **only** when you wrote `required` for it, so a wrong `required` hides a job and a wrong other role shows one the candidate cannot do. Read the sentence, not its heading or its keywords:
  - **`required`** only when the advert holds the candidate to that skill: "3+ years of Go", "Go required", "Imprescindible Go", a bare "Experience with Go" in the list of what the candidate must bring, or the title naming it alone ("Golang Developer", "Desarrollador GO").
  - **`alternative`** when it is one option among several: "Java, Go or Python", "Java/Go" (in the title too), "at least one of", "Go or similar", "any modern language: Go, Rust, Kotlin", "and/or". A skill alone in its clause is not an alternative because the advert also names others it lists with "and".
  - **`plus`** for anything the advert welcomes without needing it: nice to have, a bonus, "se valora", "valorable", "deseable", "no excluyente", "no imprescindible", "preferred", "ideally", "even better if", "things that set you apart", "Go a plus" in a title. Soft wording **under a requirements heading** is still a plus ("Requirements we'd love to see", "Additional qualifications"): the sentence decides, not the heading above it.
  - **`optional`** for a skill the advert names without asking for it: an example ("languages such as Go"), the company's own stack ("our platform runs on Go"), a benefit or training offer ("a chance to learn Go"), learning wording ("we will teach you", "willing to learn"), and a **negated need** ("no prior Go needed", "you don't need to know Go", "no se requiere").
  - **A cue binds to its own skill.** "You must be fluent in Python, and our backend team writes Go" requires Python, not Go. "Python is required to work with our Go services" requires Python. "Customers need fast APIs, which we build in Go" is not a requirement of the candidate at all: **everyday "need" is not a requirement.** "Go is essential to our platform, but we will teach you" is `optional`: the learning wording overrides the cue.
  - **Go the verb is not the language.** "Ready to Go?", "go the extra mile", "Go to market experience" name no skill: write no reading for them. The same holds for any word that is also a technology's name in its ordinary sense.
  - **One skill, one role.** If the advert says both ("Go required" in one place, "Go a plus" in another), the stronger demand wins, and the span quotes it. An advert that names no skill gets `skills: []` (read, nothing named) — never leave `skills` unset on an advert you read: unset means *not read yet*, and a candidate's `skill:` exclusion is then shown as pending, not applied.
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

`extractions/<offer_id>.json` — per dimension a score, evidence spans, a provenance marker, plus `skills` (the skill readings above; `null` until read); candidate-independent. `annotations/<offer_id>.json` — the same offer read against this candidate, derived, never shared.

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
"Read the fourteen new ones. Three don't say anything about how they work, which is itself worth knowing. I'd go straight to the ranking, because reading fourteen adverts one at a time is what the order is meant to save you. Shall I?"
```

Writes `last_activity`.

If the conversation is already long, `CLAUDE.md`, section "Suggest compacting once, at a step boundary", says whether and how to suggest compacting here.

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
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

**`extraction_macro_f1` is not built, so this checkpoint exits 3 at best.** Say so when presenting this
step's output: the artefacts are there, and nothing has measured whether they are any good.

The script writes its result to the candidate's own tree at `session/checkpoint-understanding.json`, never to a shared or
global path.

## Gotchas

- Re-extracting an unchanged offer against an unchanged dimension model spends money to reproduce a result — replace only what changed or whose extraction predates the current model version.
- Annotations are cheaper and staler than extractions: recomputed whenever constraints or weights move, without re-reading the advert.
