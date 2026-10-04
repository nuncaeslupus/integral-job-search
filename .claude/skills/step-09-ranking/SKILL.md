---
name: step-09-ranking
description: Step 9 (`ranking`) of the candidate process — presents the live offers in order, each position's reason cited from the ad. Do NOT use for collecting the candidate's opinion of what they see — that belongs to step 10, which follows this one.
---

# step-09-ranking

The candidate sees the live offers in order, each with the reason it sits where it does, in words from the advert and numbers in their currency.

CANARY: step-09-ranking-loaded-2026-08-18-f42ed484-59789561a5c8873b

**Required.** No candidate reaches a ranking without this step — §2.5 promises every *offered* step may be declined, and this is not one of those.

## When to load

Load when the candidate's session is at step 9 (`ranking`) of the thirteen-step
process (`status/spec-v2-steps.md`) — the previous step finished, or the step runtime's
`offered()`/`decide_resumption()` (T34/T35) names `ranking` as where this candidate should
be. Phase: **loop**.

If the runtime (`integral.step_runtime.offered`) is not offering `ranking` for this candidate, defer to whichever step it does offer instead of running this one out of turn.

## Preconditions and inputs

Extractions for the live offers, and `profile/constraints.json`. Weights are optional: without them the ranking is L1 and says so.

**Reads:** `extractions/*`; `profile/constraints.json`; `profile/weights.json` — optional; `profile/traits.json` (every dimension with evidence is priced or named as unpriced, T243); `cv/master.json` and the skill statements in `profile/evidence.jsonl`, through `integral.stack_fit` (T219) and `integral.fit` (T244).

## Protocol — the manner, not the mechanism

- No questions — this step presents. **Presentation is half the specification**, not a rendering detail. Show a handful at a time, not forty.
- Lead with the offer and the one thing that most moved it, not with a score. A card: title and employer, facts as bullets (pay gross and net-equivalent, hours, location, contract), then one line of what actually matters — including the bad part.
- Where the list is rendered as a page, it is a template filled from the normalised offer JSON — never a paragraph assembled by a model.
- Where an offer is out of reach today but reachable, say what it would take and ask whether that is of interest, rather than assigning homework.

**Say what is happening before a silence.** Work the candidate waits through — creating their profile, running a check, saving what they have just said — is named **before** it starts, in one short line, and closed when it finishes. Acknowledge the person first, then do the work, then come back to them; never open a run of tool calls on someone who has just answered. An unexplained pause is indistinguishable from a tool that has hung, and the candidate has no way to ask.

In this step that sounds like:

```text
"Scoring and ordering them against what you've told me — one moment."
…then, once the work is finished…
"Thanks for waiting — here's the order, and why. …"
```

**Never:**

- Never show what is unknown about an offer as neutral — an advert silent on hours is not an advert promising good ones.
- Never assemble the card's prose a paragraph at a time by a model — it is a template filled from the normalised JSON.

## Pay reaches the ranking converted, or the offer is refused

`Candidate.salary_per_month` has no currency, so never build a `Candidate` with a bare
number. Go through `integral.pay_normalise`, which converts into the weights' currency
per month with a dated, sourced rate you pass in (never fetch one), re-reads the advert
when `salary` is empty, and raises `PayNormaliseError` rather than compare an unconverted
figure. `rank` refuses a point with no band in the ranking's currency.

```python
from integral.pay_normalise import DatedRate, RateTable, annotate, candidate_for

# The target is the weights' currency, or with no weights (L1) the candidate's own,
# `salary.currency` in `profile/constraints.json`. A ranking with no currency at all
# is refused when its pay points are unlabelled or disagree.
target = (weights or {}).get("currency") or constraints["salary"]["currency"]
table = RateTable(target, (DatedRate("USD", 0.9, "2026-10-01", "<source>"),))
candidate, reading = candidate_for(offer, extraction, dimensions=dims, table=table)
ranking = annotate(rank(candidates, ..., currency=table.target), readings, table)
```

- An offer with no published pay is ordered among the unpaid ones and `unpaid_offers`
  names it: say so on the card, and never present that order as a pay verdict.
- No rate for a currency means the pay is refused: tell the candidate, do not guess one.

## The candidate's stack is data, not a question

What the candidate knows is already on disk: `cv/master.json` (`skills` with levels,
`experience`, `episodes`) and any skill statement they made — an evidence row with a
`skill` stance. *"odio Java"* is `{technology: java, averse: true}`; *"Kubernetes no sé
cómo funciona"* is `{technology: kubernetes, level: none}`. A statement overrides the
CV's level (it is later, and said to us rather than to employers); aversion does not
change the level, so the CV stays true for an application document.

```python
from integral.stack_fit import fits_for_store, summary_line

stack = fits_for_store(store, offer_ids)
ranking = rank(candidates, ..., stack=stack)       # carried under `stack_fit` for the card
line = summary_line(stack[offer_id])               # the card's stack line, from data
```

- Each card states the fit in the technology's own name — *"no consta en tu CV: Go,
  TypeScript; nivel bajo: Kubernetes"*. A `mismatch` is part of the bad part the card's
  one line must not hide.
- Asking which technologies the candidate knows, or whether they built something, when
  the CV already says so, tells them the tool did not read what they gave it — that is
  the complaint this section exists for. The one stack question worth asking names a
  technology in `missing`, where the CV is silent.
- When the candidate states a level or an aversion, record it as a `statement` row with
  `skill=SkillStance(...)`, their words in `text`. The next ranking reads it.
- `unknown` means the advert named no technology — say so; it is not a fit.

## Whether they can do the job moves the order (T244)

Three readings against the candidate enter the ranking as their own axes: the stack
(`stack_fit`), the level the advert asks for against the last role held (the CV's titles), and
the advert's English against the CV's English level. Each is a shortfall, never a bonus, and
each is unknown on its own when the advert (or the profile) is silent — an advert that states
nothing about the level is not a match, and the others still compare.

```python
from integral.fit import fit_candidates
from integral.rank import FIT_DIMENSIONS

candidates = fit_candidates(store, candidates)             # the three components, or an admitted unknown
ranking = rank(candidates, dimensions=[*dims, *FIT_DIMENSIONS], ...)
```

- Only a level the rules stage read from the advert counts; a model-stage level is how a plain
  title becomes "mid", which is silence. Say "the advert doesn't say" for an unknown component.
- Dominance compares the components both offers state; the order breaks a tie between offers
  that state the same ones. Fit is never priced — what it is worth against money is T10's.

## What the candidate said is priced, or named as unpriced (T243)

The weights price only what step 6's choices reached; a candidate's traits can carry
evidence on thirty dimensions. Never rank on the weights alone and say nothing of the rest.

```python
from integral.rank import rankable_dimensions, weights_for_currency
from integral.stated_pricing import pricing_inputs, record_stated_price

traits, weights = pricing_inputs(store)                   # rebuilt from the log
dims = rankable_dimensions(dimensions, weights, currency)  # a stated price is a ranked axis too
ranking = rank(candidates, dimensions=dims, ..., weights=weights, traits=traits, currency=currency)
explain(ranking, candidates, weights_for_currency(weights, currency))   # stated drivers say so
ranking["unpriced_trait_dimensions"]               # {"checked", "dimensions", "reasons"}
```

`currency` is the candidate's own (`profile/constraints.json`). A stated price in any other
currency, or any stated price when no currency is known, is skipped and named (`stated_in_another_currency`) —
a sentence never decides what the ranking is denominated in.

- **Say the unpriced dimensions by name**, in the candidate's words for them, every time the
  list is non-empty: *"what you told me about spoken English doesn't move the order yet —
  it's not priced."* `checked: false` means the traits were not handed over; fix the call.
- **A stated trait is a route, not a quiz.** When they say "spoken English costs me" or "I want
  a mentor", record it: `record_stated_price(store, dimension=..., direction="less"|"more",
  strength="slight"|"clear"|"strong", currency=..., text=<their words>, at=now)`. No euro
  figure is asked for; the rung becomes a coarse part-worth under `stated_part_worths`, and a
  fitted one from step 6 outranks it. The next ranking moves.
- `priced_by` says which dimensions were priced by choices and which by statements; say so when
  a card's reason rests on a stated one.

## Record what was shown, and say what was held back

Showing a batch is itself a fact, and it is the one that later turns into a
question worth asking. Two calls, around the list:

```python
from integral.presentation_log import partition, present, unchecked_line, withheld_line

show, held = partition(store, ranked_ids)      # never `show` alone
present(store, show, at=now, phrase=phrase)
```

`partition` also withholds the same vacancy under another board's wording (same employer, similar title) when a copy was ever shown, shortlisted, applied to, rejected or archived after any of those. Each kind is its own reason in `withheld_line`. An offer with no employer cannot be compared and is shown: say so with `unchecked_line(store, show)` (empty when there is none).

`partition` also withholds any stored offer on a topic the candidate ruled out (`search/exclusions.json`), including offers stored before they said it.

**Say the withheld count and the reason, every time.** `withheld_line(held)`
puts it in the shape the owner asked for — *"4 descartadas porque «son de
investigación»"*. A filter nobody is told about is indistinguishable from a
thin market, which is the same failure `step-07-sourcing` names for liveness,
arriving by a different route.

## Stop rule

A ranking is produced and presented. **Hard cap: the number shown at once**, so the list stays readable; the rest are available on request.

## When declined

A candidate can ask not to see rankings for now; the run still computes and stores one, so it is there when they come back.

## Outputs

`rankings/<timestamp>.json`, pinned to the `profile_revision` and the sufficiency level that produced it.

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
"Here are the top five. The Girona one is first mostly because they say 'we don't do on-call' outright, which is worth about €400 a month to you. I'd react to a couple of these before anything else, because what you say about them is what moves the order next time. Want to?"
```

Writes `last_activity`.

If the conversation is already long, `CLAUDE.md`, section "Suggest compacting once, at a step boundary", says whether and how to suggest compacting here.

## Checkpoint — the number, not the prose

The step's acceptance gate is **`explained_fraction == 1.0`**,
owned by **T19**. That gate is a build-time measurement over evidence this step's
conversation produces; it is not computed here, and this skill's prose never asserts it passed.

What this skill checks, mechanically, before ending the step: run
`${CLAUDE_SKILL_DIR}/scripts/run_checkpoint.py --id <handle> [--input-dir <profiles-root>]`,
this skill's own checkpoint script. It reads the candidate's
`session/state.json` (T35) and profile tree (T34) and reports whether this step's *machine-visible*
half of the stop rule is met — every artefact `ranking` produces is present, and nothing is
left outstanding in the recorded position — never by asking the model to eyeball the transcript
and decide.

Exit 0 means that half is satisfied *and* this step's acceptance gate is built, so the run
may be read as the step having passed. Exit 1 means coverage is not met (still open, or
blocked on a missing input). Exit 2 means the candidate or step could not be read. Exit 3
means coverage is met but the gate is not built, so the step cannot be certified — a
covered step is not a passed one (D-21).

**`explained_fraction` is built (T19), so exit 0 is reachable here.** What it measures is
that every ranked offer cites the advert's own words for each dimension that moved its
position — not that the order is right. `rank_spearman` is the gate for that, and it is
T20's, still open: a step that explains itself well has not thereby been shown to rank well.

**A list shown with no `present()` row is not coverage (T226).** The script also reads the latest `rankings/<run_id>.json` against `search/presentations.jsonl` (`integral.presentation_audit.unpresented_ranking`): when no presentation row at or after that run shows any of its offers, it reports them under `unpresented_ranking` and `coverage_met` is false. Call `present()` and re-run it.

The script writes its result to the candidate's own tree at `session/checkpoint-ranking.json`, never to a shared or
global path.

## Gotchas

- Every ranked offer must cite at least one verbatim span per contributing dimension (`explained_fraction == 1.0`) — calibrated against a blind manual ranking (`rank_spearman >= 0.60`).
- A ranking whose pinned revision is behind the current one is shown as out of date with a one-click recompute, not silently served stale.
