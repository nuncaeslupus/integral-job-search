# Specification v2 — the whole process

**Date**: 2026-08-17
**Author**: nuncaeslupus
**Supersedes**: the step table in `docs/product-shape.md`
**Source**: `status/spec-v2-brief.md` (owner's decisions), owner's answers of 2026-08-17
**Companion**: `status/spec-v2-steps.json` — the same step list, machine-readable

This document specifies the **process**: which steps exist, where their
boundaries fall, how they connect forwards and backwards, what is on disk, how
an interrupted candidate is picked back up, and when an offer dies. It does not
specify any individual step — that is S2, and a step specified before the
process is settled gets the wrong boundaries.

Contracts inherited from `status/specification.md` §5 (dimension model, offer
schema, extraction output, ranking output) are unchanged and not restated here.

---

## 1. What this settles

The brief left two questions open and the owner answered four. All four answers
are decisions now, not proposals.

| # | Question | Decision |
|---|----------|----------|
| 1 | Do Intake and Constraints merge, since a parsed CV answers several constraint questions? | **Separate.** Constraints becomes confirm-and-fill: it consumes what Intake inferred and asks only for what a CV cannot state. |
| 2 | Is Traits its own step, or folded into History with a coverage requirement? | **Its own step** — and the tool must additionally notice, on its own, when what it knows has gone out of date, and reopen the right earlier step. §5. |
| 3 | When does the candidate first see a ranked list? | **After the full first run, by default** — but the tool explains the sequence and *offers* to skip ahead and search with what it has. The candidate elects the shortcut; the tool never takes it silently. §3.3. |
| 4 | Where does reacting to real ads live? | **Its own onboarding step (5)**, with stimuli fetched live from multiple sources so the candidate reacts to ads that could plausibly be theirs. The committed corpus is the fallback, not the primary. §2.3. |
| 5 | Purge horizon for an ad never shortlisted | **60 days** from collection. §7.3. |

Two consequences worth stating up front, because they change the brief:

- **The step count is 13, not 12.** Reactions is a step of its own, and the
  loop's feedback step is a different instrument from it — different stimuli,
  different consequences — so they are not merged. §3.3.
- **Some of the tool's work is not a step at all.** Noticing that a profile has
  aged, or that a life event just landed in the conversation, is a mechanism
  that *chooses* which step to reopen. It is specified in §5 and belongs to no
  step.

---

<!-- required-item: step-list -->
## 2. The step list

Thirteen steps. Each is a short directed conversation or an automatic pass with
one goal, one visible output, and one named gate metric. Numbered as **steps**
— the candidate's journey — and deliberately not aligned with the delivery
phases in `status/plan.md`, which are about build order.

| step | name | goal | visible output | gate metric |
|------|------|------|----------------|-------------|
| 0 | **Identify** | know whose tree we are in, and where they left off | a greeting naming them, their last activity, and where they stopped | `cross_user_leaks == 0` |
| 1 | **Intake** | the CV that exists, or a first one built with someone who has none | a parsed CV, every fact showing where it came from | `intake_field_provenance == 1.0` |
| 2 | **Constraints** | the facts that filter, confirmed rather than re-asked | a constraints summary they correct in place | `constraint_field_resolution == 1.0` |
| 3 | **History** | the last job and the ones before: what they did, what went wrong, why they left | a story bank of episodes | `story_dimension_linkage == 1.0` |
| 4 | **Traits** | score what the evidence supports, ask only about what it does not | a trait profile with `insufficient` where it belongs | `trait_evidence_sufficiency == 1.0` |
| 5 | **Reactions** | real ads and ad fragments, and what the candidate makes of them | their own words against each stimulus | `elicitation_eval_overlap == 0` |
| 6 | **Preferences** | reactions and forced choices become weights | what each dimension is worth per month, in euros | `weight_salary_equivalent_roundtrip_error <= 0.01` |
| 7 | **Sourcing** | offers in, deduped, stale ones retired | what arrived, what duplicated, what expired | `offer_schema_violations == 0` |
| 8 | **Understanding** | extract dimensions and evidence spans (automatic) | per offer, what the ad was found to say | `extraction_macro_f1 >= 0.75` |
| 9 | **Ranking** | order the live offers and explain every position | a ranked list citing the ad's own words | `explained_fraction == 1.0` |
| 10 | **Feedback** | what they think of the offers in front of them | a re-ordered list, and why it moved | `feedback_traceability == 1.0` |
| 11 | **Application** | a CV and letter targeted at one offer | the documents, versioned per offer | `cv_generation_traceability == 1.0` |
| 12 | **Interview log** | what happened, turned into preparation for the next one | questions asked, and what to rehearse | `interview_lesson_linkage == 1.0` |

Steps **0–6** are the first run. Steps **7–10** are the loop the candidate
lives in afterwards. Steps **11–12** run per opportunity, any number of times,
in parallel across offers.

Every step writes evidence (T28). The profile therefore deepens throughout,
rather than only during onboarding.

### 2.1 Why Intake and Constraints stay separate

A CV states where someone lived and what they have done. It does not state the
salary they will refuse, whether they hold a work permit for a neighbouring
country, whether they would cross a border daily, or how many hours they can
actually work now. Those are precisely the constraints that veto an offer, and
none of them can be parsed.

Merging would produce one step whose first half is document handling and whose
second half is an interview, with a stop rule that has to cover both. Keeping
them separate makes each short — and makes Constraints *shorter than it would
otherwise be*, because it opens by showing what Intake already established and
asks the candidate to correct it rather than restate it.

**The rule that makes this work:** Intake writes facts with provenance, never
inferences. "Barcelona" extracted from a CV header is a claim the document
makes, not an established residence. Constraints promotes claims to confirmed
facts by asking, and anything the candidate does not confirm stays `unknown` —
which, per the inherited rule, neither passes nor vetoes.

### 2.2 Why Traits is its own step

Trait *capture* is continuous and happens in every step, History most of all.
Trait *scoring* is potentially LLM-backed and cannot run per utterance (§7).
Those two facts together define what the Traits step is for:

1. it is the defined point where scoring runs over everything accumulated; and
2. it asks only about traits the evidence cannot yet support.

Folded into History, the step would have no stop rule other than "keep telling
stories until coverage" — which is the interrogation the owner asked to avoid.
As its own step it is short by construction: with a good History behind it, most
traits are already scored and it asks about the few that are not.

A trait is scored only from **at least two independent episodes recorded on at
least two separate occasions**. Below that it reports `insufficient`, with the
count, and the step may ask for another episode. A trait scored from a single
anecdote is a stereotype, and the profile would be confidently wrong in exactly
the way that makes a person distrust the whole tool.

> **Owner decision needed if this is wrong.** Two episodes on two occasions is
> my number, not the owner's. It is the one threshold in this document that was
> not given to me.

### 2.3 Why Reactions is a step and not part of Preferences

Preferences fits weights. Reactions produces the material weights are fitted
from, and it produces more besides: how an employer's phrasing lands, which
perks read as insulting, what "if you don't match everything, apply anyway"
signals about a company. That is profile evidence in its own right, useful even
if no weight is ever fitted from it.

**Stimuli come from a live, quick, multi-source fetch of ads plausibly relevant
to this candidate**, chosen using the constraints already established. The
committed corpus is the fallback for when fetching is unavailable, not the
primary source — a corpus is by construction limited and ageing, and reacting
to an ad that could never be yours teaches the tool the wrong thing.

Two rules protect the measurements:

- Stimuli fetched live enter the offer store as ordinary offers with status
  `new`, subject to the same dedup, lifecycle and purge rules. They are not a
  parallel universe of ads.
- When the corpus is used, stimuli are drawn **only from the elicitation
  split** (T9). `elicitation_eval_overlap == 0` is inherited and non-negotiable:
  an ad used to elicit preferences can never be one the ranking is later scored
  against, or the ranking gate measures memorisation.

### 2.4 Why Feedback (10) is not the same step as Reactions (5)

Same instrument, different position, different consequence. Reactions shows
stimuli the candidate has no stake in, to learn what they value. Feedback shows
offers they might actually apply to, and its output changes both the weights
*and* the offers' lifecycle status. One is elicitation; the other is a decision
point. A single step would need two stop rules and two gates.

---

<!-- required-item: connections -->
## 3. How the steps connect

### 3.1 Forward: sufficiency, not sequence for its own sake

Steps run in order on a first run, but what actually gates a later step is
whether the state it needs exists. Three sufficiency levels, recorded in
`session/state.json` and stamped onto anything derived:

| level | reached when | what it unlocks |
|-------|--------------|-----------------|
| **L0** | a handle is identified | reading and writing that candidate's tree, and nothing else |
| **L1** | constraints resolved (every field `stated`, `declined` or `unknown`) | sourcing, extraction, and a **provisional** ranking: hard filters plus default weights |
| **L2** | traits scored and weights fitted | a full ranking, with explanations in salary-equivalent terms |

A ranking records the level that produced it and is labelled with it wherever
it is shown. A provisional ranking that is not labelled provisional is a defect,
not a shortcut.

### 3.2 What each step must leave behind

Every step ends with something the candidate can see (brief §2.2) *and*
something the next step can read. A step that only fills internal state has no
visible output and will feel like an interrogation; a step whose visible output
is not also machine-readable state cannot be resumed or revised. Both columns
of the §2 table are requirements, not description.

### 3.3 The offered skip

The default path is the full first run, and the tool says plainly why: **the
more it knows, the better the results.** But at the end of every first-run step
it offers the alternative — *"we can stop here and go look at real jobs with
what I have; the list will be rougher and I'll tell you what would sharpen it."*

If the candidate takes it:

- the ranking produced is L1 and labelled provisional;
- the skipped steps are recorded as **pending**, not cancelled;
- the ranking is shown alongside a short statement of what completing each
  pending step would change — not a nag, a single line;
- returning to a pending step later is a normal forward move, not a repair.

The tool never elects the skip on the candidate's behalf, and never hides that
a shortcut was taken.

### 3.4 Backwards: revision propagates, it does not discard

Going back with new information must revise what later steps produced rather
than throw it away (brief §1.1). What happens depends on which of three classes
the downstream artefact belongs to.

| class | examples | on an upstream change |
|-------|----------|-----------------------|
| **Derived** | `constraints.json`, `traits.json`, `weights.json`, extractions, rankings | recomputed from the evidence log; never edited in place; recomputation is always safe because nothing was hand-authored into them |
| **Authored** | generated CVs and letters, interview preparation notes | marked **stale**, with the reason and the fields that changed; kept exactly as they are; regeneration is offered and never automatic |
| **Historical** | `evidence.jsonl` rows, `applications/`, `interviews/`, tombstones | immutable. Never revised, only appended to. What was sent was sent; what happened happened |

The distinction that matters is **authored**: a CV may already have been sent to
an employer. Silently regenerating it would leave the candidate unable to answer
a question about their own application. So it is versioned, the old version
survives, and the stale marker says what changed and why it might matter.

**The mechanism is a profile revision.** Because the profile is a pure function
of the append-only evidence log (T6), a revision needs no separate file:

```
profile_revision = { "rows": <count of evidence.jsonl>, "sha256": <hash of the file> }
```

Everything derived records the revision it was computed from. Anything whose
recorded revision is behind the current one is stale, by definition, and
staleness is computed rather than tracked. A ranking pinned to revision 412
shown while the profile is at 419 is displayed as out of date, with a one-click
recompute.

### 3.5 The three named re-entries

The brief names three events. Each has a defined entry step and a defined
propagation, and each is an ordinary forward move from that point:

| event | re-enters at | propagates to |
|-------|--------------|---------------|
| "I updated my CV" | 1 Intake | 2 (confirm changed facts) → 4 (rescore if new episodes) → 11 (generated CVs marked stale) |
| "I left my job" | 3 History | 2 (availability, pay floor) → 4 (rescore) → 6 (weights may have moved) → 9 (recompute) |
| "I got rejected, and here is why" | 10 Feedback or 12 Interview log | 6 (weights) → 9 (recompute) → the offer's lifecycle status |

`reentry_events` in `spec-v2-steps.json` carries the full list per step.

---

<!-- required-item: capture-scoring -->
## 4. Capture and scoring

Traits update continuously (brief §1.2), but the cost of inference cannot be
paid on every message. Two mechanisms, deliberately separated.

### 4.1 Capture — cheap, always on

Every step appends rows to `profile/evidence.jsonl`. A row is written for
anything the candidate says that bears on a dimension, an episode, a
constraint, or a preference. Capture performs no scoring and no inference beyond
what the step was already doing.

```jsonc
{
  "id": "ev-000412",
  "recorded_at": "2026-08-17T10:04:11Z",   // when we learned it
  "occurred_at": "2026-03-01",             // when it happened, if known; null if not
  "occurred_precision": "month",           // day | month | year | null
  "step": "history",
  "kind": "episode",                       // episode | statement | reaction | constraint | outcome | retraction
  "dimensions": ["team_autonomy"],
  "text": "…the candidate's own words…",
  "source": "conversation",                // conversation | cv_document | offer_reaction | interview
  "disclosure": "private"                  // private by default; never leaves without per-use approval
}
```

`occurred_at` is separate from `recorded_at` on purpose. It is what makes "two
years have passed since that job ended" computable, and §5 depends on it.

**Retraction.** The log is append-only, so "forget that" is a `retraction` row
naming the row it suppresses — never a deletion. Derived artefacts honour
retractions when rebuilt; the original row survives so a rebuild remains
deterministic and so an accidental retraction can itself be undone. A candidate
asking what is known about them gets the derived profile, and a candidate asking
for something to be forgotten gets it suppressed everywhere derived, in the same
turn.

### 4.2 Scoring — expensive, at defined points only

`traits.json`, `weights.json` and `constraints.json` are recomputed at exactly
three triggers, never per message:

1. **A step boundary** — any step ending recomputes what its evidence touched.
2. **An explicit request** — "what do you know about me now?"
3. **A batch threshold** — N new trait-bearing evidence rows since the last
   scoring run. N is set in the Traits step spec (S2).

Each derived file records `scored_at` and the `profile_revision` it was computed
from, so freshness is visible. Because the profile is a pure function of the
log, deferring scoring costs freshness and nothing else: **the log is never
behind, and no evidence is ever lost to a scoring run that did not happen.**

---

<!-- required-item: resumption -->
## 5. Freshness, proactive re-entry, and resumption

Three related things: what is recorded, how the tool notices the profile has
aged, and how a returning candidate lands in the right place without typing a
command.

### 5.1 Session state

`profiles/<handle>/session/state.json`, rewritten at every step boundary:

```jsonc
{
  "handle": "marcos",
  "current_step": "history",
  "position": { "covered": ["last_job", "reason_for_leaving"], "outstanding": ["earlier_roles"] },
  "last_activity": "2026-08-16T18:22:04Z",
  "pending_steps": ["traits", "reactions", "preferences"],   // skipped, not cancelled
  "open_questions": ["salary floor was declined — ask again if they raise money"],
  "sufficiency": "L1"
}
```

`position` is what makes an interrupted step resume at the right question rather
than at the top. It is written continuously during a step, not only at its end —
a session that dies mid-interview must not lose its place.

### 5.2 Proactive re-entry — the tool notices, the candidate does not have to

The owner's requirement, and the part that separates this from a form: **if
something could have changed, ask.** A candidate who returns after two years
saying "I lost my job" should not be handed a stale ranking. They should be
asked what happened — why the job ended, what they did there, what they
achieved, what went wrong, what they learned in those two years — because that
is both the most useful thing to know and the most human thing to say.

Three trigger kinds, evaluated at session start after identification:

| trigger | detected from | reopens |
|---------|---------------|---------|
| **Elapsed time** | `last_activity`, and `occurred_at` on the most recent role evidence | 3 History (what happened since), 2 Constraints (what changed), 4 Traits (rescore) |
| **Life event in the conversation** | the candidate says it: lost/left/started a job, moved, had a child, finished a course, changed field | the step in §3.5 for that event |
| **Gap** | a trait below sufficiency, a constraint still `unknown`, a pending step | the step that owns the gap |

Thresholds for "elapsed" belong to each step's spec (S2). The process-level rule
is that **a trigger produces an offer, never an action**: the tool says what it
noticed and what it would like to ask, and the candidate can decline. Declining
is recorded so it is not asked again next week.

What proactive re-entry must never become is an audit. "It has been eight
months, let's update your file" is a form. "You said you left in March — how did
that end up?" is a conversation, and it is the one that gets an answer.

### 5.3 Resumption — inferred, not commanded

Skills are not always invoked (brief §2.5). At the start of a session, after
identification and before anything else, the tool reads `state.json` and states
where the candidate is. Where to resume is decided by this order, highest first:

1. **An explicit request** — a command, or "let's do the interview again".
2. **A conversational cue** — "let's carry on" resumes `current_step` at
   `position`; a life event (§5.2) re-enters its own step.
3. **A recorded position** — an unfinished step is offered first.
4. **A freshness trigger** — the highest-value gap or the oldest stale artefact.
5. **The next step in sequence**, or the loop if the first run is complete.

Two rules constrain all five: the tool **says which step it is resuming and
why**, and it never resumes into a step silently. Being dropped back into a
half-finished interview with no explanation is indistinguishable from being
asked the same questions twice.

### 5.4 Manner and disclosure

These are protocol rules for every step, stated once here so S2 does not restate
them thirteen times.

- **Say why.** Each step opens with what it is for and what it will store — once
  per step, not per question.
- **Knowing them is how it helps them.** The tool says so, and means it: every
  question exists because an answer improves the offers they get. A question
  that cannot be justified that way should not be asked.
- **Nothing covert.** An evidence row exists only for something said in a step
  the candidate knew was recording. There is no silent capture.
- **A buddy, not a recruiter.** Directed, warm, interested in the person's
  working life rather than in filling a form. Negative episodes get a
  follow-up about what was learned, never a judgement (T27).
- **Always answerable.** "What do you know about me?" and "forget that" work at
  any point in any step, and are answered before the step continues.

---

<!-- required-item: artefact-tree -->
## 6. The per-user tree, and identification

Multi-user from day one (brief §1.3). A handful of people, file-based, not a
multi-tenant service.

```
profiles/<handle>/
  identity.json                 handle, display name, locale, created_at
  session/
    state.json                  current step, position, pending steps, sufficiency
  cv/
    source/                     originals as supplied (pdf, docx) — never modified
    master.json                 the CV on steroids: the store (S4)
    generated/<offer_id>/v<N>/  cv + letter produced for one offer, versioned
  profile/
    evidence.jsonl              append-only; written by every step; retractions included
    constraints.json            derived
    traits.json                 derived, with evidence row references
    weights.json                derived, salary-equivalent
    stories.jsonl               derived episodes, linked to dimensions
  offers/
    <offer_id>.json             normalised offer + lifecycle status + history
    tombstones.jsonl            purged ids, urls, hashes — dedup must not resurrect
  rankings/<timestamp>.json     pinned to a profile revision and a sufficiency level
  applications/<offer_id>/      what was sent, and when — immutable
  interviews/<offer_id>/        questions asked, outcome, lessons — immutable
```

`profiles/` is gitignored (T1) and stays so. Every derived file is regenerable
from `evidence.jsonl` plus the offer store; **nothing derived is ever edited in
place**, because an edit that is not an evidence row is lost at the next
rebuild and produces a profile that cannot be explained.

### 6.1 Identification precedes everything

**No path under `profiles/` is read or written before a handle is resolved.**
Resolution, in order:

1. the candidate names themselves, or a handle is supplied explicitly;
2. exactly one profile exists → the tool names it and asks for confirmation;
3. otherwise the tool asks who this is, listing the display names it has;
4. no match → offer to create a new profile, which is an explicit act.

Case 2 is a confirmation, never a default. Silently assuming the only profile is
how one person's evidence ends up in another person's history — and because the
log is append-only, that is a mess to unpick rather than a mistake to undo.
`cross_user_leaks == 0` (S3) measures exactly this: every store function takes
the handle and resolves paths beneath it, so a test can point one candidate's
operations at another's tree and prove they fail.

### 6.2 What may leave the machine

- `evidence.jsonl`, `master.json` and `stories.jsonl` are **never sent anywhere
  as-is**. Not to an employer, not to a model, not in a document.
- A story-bank episode reaches an employer-bound document only with **per-use
  approval**. Recounting a failure to the tool is not consent to send it to a
  company (inherited, v1 success criteria).
- Ad text may be sent to a model for extraction; candidate text sent to a model
  is minimised and each step's spec states exactly what it sends.
- **No autonomous outward action.** Nothing applies, emails, or contacts an
  employer without explicit per-item approval (inherited).

---

<!-- required-item: offer-lifecycle -->
## 7. The offer lifecycle

Ads go stale, and a tool that accumulates them forever becomes unusable
(brief §2.4).

### 7.1 Status

Seven statuses, one per offer, with `status_changed_at` and an append-only
`history` array on the offer record.

| status | meaning | terminal |
|--------|---------|----------|
| `new` | collected, not yet judged | no |
| `screened_out` | failed a hard constraint, or the candidate said no | no |
| `shortlisted` | the candidate wants this one | no |
| `applied` | documents were sent | no |
| `rejected` | closed unsuccessfully; `closed_reason` distinguishes employer rejection from candidate withdrawal | yes |
| `expired` | no longer live at source | yes |
| `archived` | hidden by the candidate, kept in full | yes |

Allowed transitions:

```
new         → screened_out | shortlisted | expired | archived
screened_out→ shortlisted | expired | archived          (a screen-out is reversible)
shortlisted → applied | screened_out | expired | archived
applied     → rejected | archived
rejected    → archived
expired     → archived
```

Anything else is a defect. Notably `applied` cannot go back to `new`: an
application happened, and the record of it is historical.

### 7.2 Retention

Kept **in full, indefinitely**, regardless of age:

- anything ever `shortlisted`, `applied` or `rejected`;
- anything with an `applications/` or `interviews/` record;
- anything `archived` (archiving is the candidate saying "keep this, hide it").

These are the ads that explain a candidate's own history. Deleting them would
make their story unreconstructable.

### 7.3 Purge

An offer is purge-eligible when **all** hold:

- status is `new`, `screened_out` or `expired`;
- it has never been `shortlisted` or `applied`, at any point in its history;
- `collected_at` is more than **60 days** ago;
- no `applications/` or `interviews/` record references it.

Purging **deletes the offer body and keeps a tombstone**. It is reported, not
silent: the candidate is told how many were retired and can look at the list
before it happens.

### 7.4 Tombstones

```jsonc
{
  "offer_id": "of-8823",
  "url": "https://…",
  "url_canonical": "…",           // normalised: no tracking params, no session ids
  "text_sha256": "…",             // over normalised ad text
  "first_seen": "2026-04-02",
  "purged_at": "2026-06-03",
  "last_status": "screened_out",
  "resightings": 3,
  "last_resighting": "2026-07-11"
}
```

A tombstone carries **no ad body** — that is the point of purging, and it is
what keeps a purge a privacy improvement rather than a bookkeeping trick.

On collection, an incoming ad matching a tombstone by `url_canonical` or by
`text_sha256` is **not re-added as `new`**. Its `resightings` counter increments
and it is dropped. Without this, the next collection run re-adds everything just
deleted and the candidate sees the same rejected ads forever.

**Revival is possible and explicit.** If the candidate pastes or asks for a
tombstoned ad, it is restored as `new`, the revival is recorded, and the
tombstone survives so the ad's history stays continuous. A rule with no exit is
how an accidental screen-out becomes permanent.

`resurrected_purged_offers == 0` (S5) counts purged offers that reappeared as
`new` without an explicit revival. Zero is the only acceptable value.

---

## 8. Where the gates come from

Every step in §2 names one gate metric. Ten reuse metrics that already exist in
`status/plan.md`; three are new and are named here for the first time:

| metric | step | owner |
|--------|------|-------|
| `intake_field_provenance` | 1 Intake | S4 — every field in `master.json` traces to a document span or a conversation turn |
| `constraint_field_resolution` | 2 Constraints | T24 — every constraint field is `stated`, `declined` or `unknown`, never blank |
| `trait_evidence_sufficiency` | 4 Traits | T28 — every trait carries either a score with ≥2 independent episodes, or `insufficient` |
| `interview_lesson_linkage` | 12 Interview log | S6 (to be seeded) — every interview produces ≥1 evidence row linked to a dimension or a story |

Every metric is currently `not_implemented` at the step level, which is a
truthful statement of a specification that has not yet been built against — and
`not_implemented` is a recorded value, not a blank. `spec-v2-steps.json` carries
the state per step, and S2 may not leave one empty.

---

## 9. What S2 inherits

S2 writes one specification per step, filling the template in
`status/spec-v2-brief.md` §4. From this document it inherits, and must not
re-decide:

- the **thirteen steps**, their boundaries, and their order;
- the **visible output** each step owes the candidate;
- the **gate metric** each step is measured by;
- the artefact classes (§3.4) — so "what a re-run preserves and what it
  replaces" is answered per output by which class it belongs to;
- the manner and disclosure rules (§5.4), which no step restates;
- the sufficiency levels (§3.1), which are what a step's preconditions refer to.

S2 must decide, per step: the conversation protocol, the coverage requirement,
the **stop rule** (coverage reached, candidate declines, or a hard cap — a step
with no cap runs until the candidate gives up), the elapsed-time thresholds for
proactive re-entry into that step, the batch threshold N for scoring, and
exactly what leaves the machine.

`step_count` is 13. S2's gate is `step_specs_complete_fraction`, whose divisor
is that number read from `spec-v2-steps.json` — never from counting the files
that happen to exist, because dividing by what was written makes any amount of
work look complete.

---

## 10. Open, and deliberately so

1. **Two episodes on two occasions** as the trait-scoring minimum (§2.2) is my
   number. If the owner wants three, or wants it per-trait, S2 is the place.
2. **Elapsed-time thresholds** for proactive re-entry (§5.2) are per step and
   belong to S2. "Two years" is the owner's example, not a configured value.
3. **Which sources** the Reactions step fetches stimuli from (§2.3) depends on
   the connectors T11/T12 deliver. The requirement — live, quick, multi-source,
   relevant — is settled; the source list is not.
4. **CV templates** remain out of v1 (brief §2.7). The store is designed to feed
   templates rather than one layout, which is all that is owed now.
