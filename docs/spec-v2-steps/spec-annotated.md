# Job Search — Specification v2 — Specification (annotated edition)

> Generated 2026-08-17. This is the specification with a **note slot** after every section. Read it in any Markdown app. To annotate, replace the `_(your notes…)_` placeholder under any section. When done, send the file back — notes are acted on.

---

# Spec V2 Steps

## Preamble & scope

**Version**: 1.0 — written 2026-08-17
**Author**: nuncaeslupus
**Requires**: `status/spec-v2-process.md` v2.1 — the process this specifies steps within
**Companion**: `status/spec-v2-steps.json` — the settled step list; `step_count` is this
document's divisor

Thirteen steps, each filling the template in `status/spec-v2-brief.md` §4 plus the
two fields `spec-v2-process.md` §10 requires every step to carry. Nothing here
re-decides the process: the step boundaries, the required/offered split, the
inputs and outputs, the artefact classes and the manner rules are all inherited.

> **✎ Notes** · `SPEC · intro`
> _(your notes here — replace this line)_

## How to read a step

Twelve fields, in this order, every time:

| field | what it answers |
|-------|-----------------|
| **Purpose** | what the candidate gets — not what the system does |
| **Preconditions** | what must exist, and what happens when it does not |
| **Inputs** | files and state read, and which are optional |
| **Protocol** | how the conversation goes: opening, coverage, follow-ups, what is never asked |
| **Stop rule** | how the step ends — coverage, decline, or a hard cap |
| **When declined** | the non-insistence rule (§5.4) for this step specifically |
| **Outputs** | files written, and what the candidate sees |
| **Boundary** | what is said out loud when the step ends, and the `last_activity` write |
| **Gate** | metric, threshold, and what measures it |
| **Resume** | what is recorded so an interruption continues in the right place |
| **Re-run** | what a second pass preserves and what it replaces |
| **Privacy** | what is stored, what is derived, what may ever leave the machine |

**Every hard cap in this document is a first setting, not a finding.** Caps exist
because a step with no cap runs until the candidate gives up; the specific
numbers are the least evidenced thing here and should be revised against real
sessions rather than defended.

Two rules apply to every step and are not repeated in each:

- **Non-insistence overrides coverage.** A subject declined once is not raised
  again in that step; declined twice, not raised again at all unless the
  candidate reopens it. Better a worse job than a person who felt interrogated.
- **Gates are never mentioned.** The metrics below are how the build knows a step
  works. The candidate hears what was learned and what is next.

> **✎ Notes** · `SPEC › How to read a step`
> _(your notes here — replace this line)_

## Step 0 — Identify

**Purpose.** The candidate is greeted by name, told when they were last here and
where they stopped, and can carry on without explaining themselves.

**Preconditions.** None — this is the step that has no preconditions, because
everything else has this one. The tool may not read or write anything under
`profiles/` before it completes, including on a question that seems to need no
identity ("what does this ad look like?"). Answering first and identifying
afterwards has already guessed whose data to use.

**Inputs.** `profiles/*/identity.json` — display names only, to offer a list. No
other file in any profile is opened until a handle resolves.

**Protocol.** Open by asking who this is, in one short friendly line. Resolve in
the §6.1 order: an explicit handle or name; exactly one profile exists, in which
case name it and ask for confirmation; otherwise ask, listing display names; no
match, offer to create a profile. On a first run, ask what to call them and
derive a directory-safe handle from the answer — a nickname is fine, a legal
name is not required and is not asked for. Record the language they wrote in;
the rest of the process happens in it. Never guess from one profile existing,
and never invent a suffix to resolve a collision — ask for something that tells
the two apart.

**Stop rule.** A handle is resolved and confirmed, or a new profile is created.
Hard cap: three attempts, after which the tool says it cannot tell who this is
and stops rather than guessing.

**When declined.** A candidate who will not identify themselves cannot be
served, and this is the one place where that is true — say so plainly and
without pressure, and offer to answer general questions that touch no stored
data. No evidence row is written for an unidentified session.

**Outputs.** `identity.json` (handle, display name, language, locale, created_at)
on a first run; `session/state.json` touched on every run. The candidate sees a
greeting naming them, the date of their last activity, and the step they stopped
in.

**Boundary.** *"Hello again, Marcos — last time we were partway through your work
history, about three weeks ago. Pick up there, or something else?"* Writes
`last_activity` immediately, before any other step begins, so a session that
dies in the next minute still records that someone was here.

**Gate.** `cross_user_leaks == 0` — every store operation resolves paths beneath
the identified handle, proven by pointing one profile's operations at another's
tree and requiring them to fail. Owner: S3. State: `not_implemented`.

**Resume.** This step has no interior to resume; it is the thing that makes
resuming possible. What it reads back is `session/state.json`: `current_step`,
`position`, `pending_steps`, `open_questions`, `sufficiency`.

**Re-run.** Every session. Preserves everything; replaces nothing except
`last_activity`. Re-running with a *different* handle is a profile switch, never
a merge — no state crosses.

**Privacy.** Display names are the only cross-profile data any session reads,
and only to offer a choice. Nothing here leaves the machine.

> **✎ Notes** · `SPEC › Step 0 — Identify`
> _(your notes here — replace this line)_

## Step 1 — Intake

**Purpose.** The candidate sees their working life written down — from the CV
they already have, or built with them if they have none — and can correct it.

**Preconditions.** A resolved handle (step 0). Nothing else: this step is where
someone with no document, no recent CV, and no idea where to start is expected
to arrive, and it must work for them without apology.

**Inputs.** `cv/source/*` if the candidate supplies a PDF or DOCX;
`cv/master.json` if a previous run built one. Both optional.

**Protocol.** Say what this is for — that everything captured here makes the
search better, that it stays on this machine, and that the tool is on their side
rather than assessing them. Then take whatever exists: a document to parse, or a
conversation. Parsing writes **claims with provenance**, never established
facts: "Barcelona" from a CV header is what the document says, not where they
live. With no document, work backwards from the last job through the ones before,
asking for what a CV would carry — dates, employers, what the work actually
involved — and stop when the shape of a career is there, not when a form is
full. Establish **where they live**, because it decides currency, work
authorisation, which borders are commutable and how a foreign employer would tax
them. Never ask for a legal name, an address, an identity number, a date of
birth, or a photograph: none of them improve a search, and a tool that collects
them looks like every recruiter the candidate is tired of.

**Stop rule.** Every role in the supplied document is represented, or — with no
document — the current or last role plus at least two earlier ones, or the
candidate says that is enough. Hard cap: 25 questions.

**When declined.** Intake is offered, and declining it is ordinary: skip to
Constraints, which then asks from scratch instead of confirming (§3.1). Say what
is lost in one line — the search will lean more on questions later — and never
repeat it.

**Outputs.** `cv/master.json`, the store: roles with dates and context, tools,
certifications, languages, and every claim's provenance. `profile/evidence.jsonl`
rows for everything said. The candidate sees a readable summary of their own
working life, with anything uncertain marked as uncertain. **No document is
produced here** — no PDF, no DOCX. A CV written before there is an advert to
write it for is a worse CV than step 11 produces.

**Boundary.** *"That's your history down — twelve years, four roles, and the
Catalan I nearly missed. Want to keep going to what would rule a job out, or
leave it here?"* Writes `last_activity`.

**Gate.** `intake_field_provenance == 1.0` — every field in `master.json` names
where it came from: a document span, or the turn in which it was said. A field
with no provenance is a field the tool invented. Owner: S4. State:
`not_implemented`.

**Resume.** `position` records which roles are covered and which the candidate
mentioned but has not described. An interrupted Intake resumes at the next
undescribed role, named: *"you'd mentioned the years at the hospital — want to
pick that up?"*

**Re-run.** Preserves every existing entry and its evidence; replaces nothing.
A newer CV **adds** claims and marks superseded ones rather than overwriting, so
a role removed from a candidate's public CV survives in the store — the store is
the CV plus everything it omits, and omission is often the point. Marks generated
CVs (step 11) stale.

**Privacy.** `cv/source/*` is stored unmodified and never sent anywhere.
`master.json` is never transmitted as-is, to a model or an employer. Parsing a
document may use a local extractor; if a model is used, it sees the document text
and nothing from any other profile.

> **✎ Notes** · `SPEC › Step 1 — Intake`
> _(your notes here — replace this line)_

## Step 2 — Constraints

**Purpose.** The candidate settles what would rule a job out — and sees it as a
short list they can correct, not a form they filled in.

**Preconditions.** A resolved handle. Runs whether or not Intake did; this is
required and Intake is not, so it cannot depend on Intake's output existing
(§2.5).

**Inputs.** `cv/master.json` and its claims — **optional**. `constraints.json`
from a previous run, optional.

**Protocol.** With claims available, open by showing what was inferred and ask
for corrections; with none, ask directly. Cover residence and the currency that
follows from it, work authorisation per country, languages and the level of
each, hours and availability, pay floor, mobility (remote, commute, relocation,
cross-border), and notice period. Ask warmly and one thing at a time: *"how's
your English?"* rather than a language table. **Ask about the things that quietly
rule out whole employers** — the work someone will not do, and who they will not
do it for — and get there naturally rather than by questionnaire: a person who
cares about poverty may not want a bank, a vegetarian may not want an abattoir's
logistics contract, and neither will volunteer it unprompted. An unconfirmed
claim stays `unknown`; **unknown neither passes nor vetoes** and surfaces later
as something still owed.

**Stop rule.** Every constraint field is `stated`, `declined` or `unknown` —
never blank. Hard cap: 20 questions, after which whatever is unresolved stays
`unknown` and the step ends.

**When declined.** A declined field records `declined`, which is distinct from
`unknown`: it means do not ask again. The step continues to the next field. A
candidate who declines everything still leaves with a valid constraints file in
which nothing filters, and the ranking that follows says so.

**Outputs.** `profile/constraints.json` (derived), evidence rows for each
answer. The candidate sees a summary they can correct in place, with unknowns
listed as unknowns rather than hidden.

**Boundary.** *"Right — remote or Barcelona, nothing under €45k, and you'd rather
not do defence work. That's enough to start looking. Shall I?"* Writes
`last_activity`.

**Gate.** `constraint_field_resolution == 1.0` — every field carries one of the
three states. A blank field is indistinguishable from a question nobody asked.
Owner: T24. State: `not_implemented`.

**Resume.** `position` lists fields covered and outstanding. Resumes at the first
outstanding field, naming what is left: *"three things left — hours, notice, and
whether you'd move."*

**Re-run.** Recomputed from evidence, so a re-run replaces `constraints.json`
entirely and preserves every answer that produced it. A changed constraint marks
rankings stale and may retire offers that no longer pass (step 7). `declined`
survives a re-run — declining is an answer.

**Privacy.** Constraints are derived and local. Only the filters needed to
search are ever expressed outward, and never as a profile: a query for remote
roles in a salary band carries no statement about the person.

> **✎ Notes** · `SPEC › Step 2 — Constraints`
> _(your notes here — replace this line)_

## Step 3 — History

**Purpose.** The candidate tells the story of the work they have done — including
what went wrong — and ends with a story bank they own and can see.

**Preconditions.** A resolved handle. Better with Intake behind it, and does not
require it: with no CV the step asks about roles as it goes.

**Inputs.** `cv/master.json` — **optional**, used to ask about specific roles
rather than in general. `profile/stories.jsonl` from previous runs.

**Protocol.** This is the step most likely to feel like an interrogation and the
one that must not. Ask about one role at a time, starting with the most recent.
For each: what the work actually was, what went well, what went badly, and why
it ended. Follow the candidate rather than the checklist — someone who starts
talking about the manager who left is giving you the episode; take it. Ask about
the things a CV never holds: what they are proud of, what they would do
differently, how they like to work, what they do outside work, the small
insistences that make a job bearable or not. **Every negative episode gets a
follow-up about what was learned, never a judgement** (T27), and a candidate who
does not want to discuss a departure is not pressed on it — the fact that a job
ended badly is already useful without the details. Never ask why a gap exists in
a tone that requires an excuse; ask what they were doing then.

**Stop rule.** The current or last role plus two earlier ones have an episode
each, or the candidate says that is enough. Hard cap: 12 episodes or 40
questions, whichever first.

**When declined.** History is offered. A candidate who does not want to tell
stories keeps a working profile — traits will read `insufficient` and the
ranking leans on constraints and stated preferences, which is worse but not
broken. Say that once, in a sentence, and drop it.

**Outputs.** `profile/stories.jsonl` (derived episodes, each linked to what it
evidences), evidence rows including trait evidence. The candidate sees their own
episodes written back, in their words.

**Boundary.** *"That's a good bank — nine episodes, and the one about the failed
migration will be worth having when someone asks about pressure. Enough for
today?"* Writes `last_activity`.

**Gate.** `story_dimension_linkage == 1.0` — every episode links to at least one
dimension id, so the bank is queryable rather than a pile of prose. Paired with
`story_failure_fraction >= 0.33`: success stories are rehearsed and reveal less.
Owner: T8. State: `not_implemented`.

**Resume.** `position` records roles covered, roles mentioned but not explored,
and any thread the candidate left open. Resumes by naming the thread rather than
restarting the role.

**Re-run.** Append-only in effect: new episodes are added, existing ones are
never rewritten. A re-entry after "I left my job" starts with the role that
ended and works forward. Marks `traits.json` stale.

**Privacy.** Episodes default to `disclosure: private`. **Recounting a failure to
the tool is not consent to send it to a company**: no episode reaches an
employer-bound document without per-use approval (step 11). If a model is used to
extract dimensions from an answer, it sees that answer, not the bank.

> **✎ Notes** · `SPEC › Step 3 — History`
> _(your notes here — replace this line)_

## Step 4 — Traits

**Purpose.** The candidate sees how they work — described from what they have
said rather than from a personality quiz — with the episodes behind each line.

**Preconditions.** Trait evidence exists, which History normally supplies. With
no evidence at all the step says so and offers to go to History instead of
asking a person to rate themselves out of ten.

**Inputs.** `profile/evidence.jsonl` rows bearing on trait dimensions;
`profile/stories.jsonl`; `traits.json` from a previous scoring run.

**Protocol.** Score first, ask second — most of the work is already done and the
candidate should see that before being asked anything. Present the scored traits
with their evidence, invite disagreement, and then ask about the traits still
below the floor: **two independent episodes recorded on two separate occasions**.
Ask for those by asking for another situation, never by announcing a quota.
Whether an inference sounds like a stereotype is a judgement made silently and
acted on by asking a better question; it is never voiced. A candidate who
disagrees with a score is right by default — record the disagreement as evidence
and rescore, because a profile they do not recognise is worse than no profile.

**Stop rule.** Every trait is either scored or explicitly `insufficient` with its
count, and the candidate has seen the profile. Hard cap: 10 questions.

**When declined.** Traits is offered, and it is the step people are most likely
to find odd. Declining leaves every trait `insufficient`, which the ranking
handles by not weighting them — never by assuming an average, which would be an
invented person.

**Outputs.** `profile/traits.json` (derived; per trait a score with evidence row
ids, or `insufficient` with a count). The candidate sees a description of how
they work, each line traceable to something they said.

**Boundary.** *"That's what I've got: you like a lot of autonomy, you're happier
fixing than launching, and I don't have enough yet on how you take pressure.
Leave it there?"* Writes `last_activity`.

**Gate.** `trait_evidence_sufficiency == 1.0` — every trait carries either a
score backed by ≥2 independent episodes or `insufficient` with its count. A
scored trait below the floor is a stereotype presented as a finding. Owner: T28.
State: `not_implemented`.

**Resume.** Scoring is idempotent, so an interruption re-runs it. `position`
records which insufficient traits were already asked about, so a resumed step
does not re-ask.

**Re-run.** Always recomputed from the evidence log — `traits.json` is derived
and never edited. A re-run replaces every score and preserves every episode.
Scoring is also triggered outside this step: at any step boundary, on request,
or when the batch threshold of **20** new trait-bearing evidence rows is reached
(§4.2).

**Privacy.** Trait scores are the most inferential thing the tool holds and the
least appropriate to share. They never appear in a generated CV or letter, and
never leave the machine. If scoring uses a model, it sees episode text without
the candidate's identity attached.

> **✎ Notes** · `SPEC › Step 4 — Traits`
> _(your notes here — replace this line)_

## Step 5 — Reactions

**Purpose.** The candidate reads real adverts and says what they make of them —
and discovers what they actually care about, including things they would not
have thought to state.

**Preconditions.** `constraints.json` exists, because stimuli must be adverts
that could plausibly be theirs. Without constraints the step does not run: a
reaction to an irrelevant advert teaches the tool the wrong thing.

**Inputs.** `profile/constraints.json`. Stimuli — **fetched live** from multiple
sources by preference; the corpus **elicitation split** as fallback when
fetching is unavailable.

**Protocol.** Show adverts and fragments of adverts, and ask open questions
rather than ratings: what puts you off here, what would you want to know,
which of these two would you rather work at and why. Mix whole adverts with
fragments, because the interesting reactions are often to one part — the perks
list, the way requirements are phrased, the "if you don't meet everything, apply
anyway" line, the tone of the section about the team. Vary the question; the
same prompt fifteen times reads as a form. Capture their words verbatim and
extract afterwards — never ask them to categorise their own reaction. **Stimuli
are never invented.** An imagined advert reads plausibly and represents nothing,
which is how eight wrong cues once entered the dimension model with gold
examples demonstrating their own error.

**Stop rule.** Fifteen stimuli reacted to, or the candidate stops. Hard cap: 25
stimuli — past that, reactions get shorter and less useful, which is a worse
outcome than fewer of them.

**When declined.** Offered. Declining means weights are fitted from forced
choices alone (step 6) or not at all, and the ranking says it is working from
less. This is also the step to stop early without comment: someone giving
one-word answers has finished whether or not the count says so.

**Outputs.** Evidence rows of kind `reaction`, each tied to the offer id of its
stimulus; fetched stimuli enter `offers/` as ordinary offers with status `new`.
The candidate sees the first read of what their reactions imply — the earliest
point at which the tool tells them something about themselves.

**Boundary.** *"That's telling. You didn't mention money once, and you flinched
at every mention of 'fast-paced'. Want to turn that into weights, or pause?"*
Writes `last_activity`.

**Gate.** `elicitation_eval_overlap == 0` — no advert used to elicit preferences
is ever one the ranking is later scored against. Without it, `rank_spearman`
measures memorisation and would pass while the system is worthless. Owner: T9.
State: `not_implemented`.

**Resume.** `position` records which stimuli have been shown and which are
pending, so a resumed step does not repeat an advert — reacting twice to the
same text produces agreement with oneself, not evidence.

**Re-run.** Additive. Old reactions are never discarded; a re-run draws new
stimuli, excluding everything already shown. Marks `weights.json` stale.

**Privacy.** Reactions are strong evidence about a person's values and stay
local. Fetching stimuli sends a search shaped by constraints — a role, a
location, a salary band — and never a profile, an episode, or a trait.

> **✎ Notes** · `SPEC › Step 5 — Reactions`
> _(your notes here — replace this line)_

## Step 6 — Preferences

**Purpose.** The candidate sees what each thing is worth to them per month, in
their own currency, as a list they can argue with.

**Preconditions.** Reaction evidence, or enough constraint and history evidence
to seed the choices. With neither, the step explains that it would be guessing
and offers Reactions instead.

**Inputs.** Reaction evidence rows; `profile/constraints.json` for the currency
and the pay floor; `weights.json` from a previous fit.

**Protocol.** Forced pairwise choices between two realistic packages that differ
on a few dimensions — never sliders, never "rate how important autonomy is out
of ten", both of which measure what someone believes about themselves. Draw the
pairs from what reactions suggested is contested. Show the trade in their own
currency. When a choice contradicts a stated preference, do not correct them:
record both and let the fit reconcile it, because what people choose is better
evidence than what they say they value. Present the fitted weights as a claim
they can reject.

**Stop rule.** Enough choices for the part-worths to be identifiable, or the
candidate stops. Hard cap: 20 choices.

**When declined.** Offered. Without weights the ranking is L1: hard filters and
defaults, explicitly labelled provisional (§3.1). That is a real result, and
saying so is more honest than implying the list is worthless.

**Outputs.** `profile/weights.json` (derived; part-worths in salary-equivalent
terms, in the candidate's currency). The candidate sees an ordered list of what
each dimension is worth per month.

**Boundary.** *"So a shorter commute is worth about €200 a month to you, and
remote about €600. Does that sound like you? We can look at real jobs now."*
Writes `last_activity`.

**Gate.** `weight_salary_equivalent_roundtrip_error <= 0.01` — converting a
dimension to currency and back recovers the part-worth within 1%, so the number
the candidate is shown is the number the ranking uses. Owner: T10. State:
`not_implemented`.

**Resume.** `position` records choices made and the pairs still queued. Resumes
mid-sequence; a partial fit is usable and is marked as partial.

**Re-run.** Recomputed from all reaction and choice evidence, so a re-run
replaces `weights.json` and preserves every choice behind it. Triggered by new
reactions, by a recorded rejection reason (step 10), and on request. Marks
rankings stale.

**Privacy.** Weights are derived, local, and never transmitted. A salary
expectation may be shared with an employer only through step 11, and only with
per-item approval.

> **✎ Notes** · `SPEC › Step 6 — Preferences`
> _(your notes here — replace this line)_

## Step 7 — Sourcing

**Purpose.** The candidate gets live offers worth looking at, with the stale ones
retired and nothing they have already rejected coming back.

**Preconditions.** `constraints.json`, which decides where and what to search
for. Required step; runs on a schedule, on request, or when constraints change.

**Inputs.** `profile/constraints.json`; `offers/*.json` and
`offers/tombstones.jsonl` for dedup; connector configuration.

**Protocol.** Mostly automatic, with one conversational duty: **establish how far
the search can travel, at the moment it becomes relevant.** Remote, commuting
distance, relocation, and — the one worth real care — working for an employer in
another country while living here. That last is often where the money is and it
carries the questions nobody enjoys: employed or contracting, paid where, taxed
where. Those answers change which offers are legal to take, so they belong here
rather than as a surprise at the application stage. Reach beyond the obvious
portals to boards specialised in the candidate's field; the general aggregators
are the worst of the available sources and the easiest to over-rely on.

**Stop rule.** All configured sources have been polled and results normalised.
Hard cap: a per-run offer ceiling, so one badly-scoped query cannot deliver
four hundred adverts nobody will read.

**When declined.** Not applicable to the fetch, which is required. The
conversational part is declinable per question: an unanswered mobility question
leaves the reach at its current setting and searches accordingly.

**Outputs.** `offers/<offer_id>.json` (normalised, status `new`), tombstone
updates, expiry marks on offers no longer live at source. The candidate sees a
count: what arrived, what duplicated, what expired, what was retired.

**Boundary.** *"Fourteen new, six duplicates, and four have closed since last
week. Want to see the new ones ranked?"* Writes `last_activity`.

**Gate.** `offer_schema_violations == 0`, with `dedup_precision >= 0.95` (T13)
alongside. Owner: T11. State: `not_implemented`.

**Resume.** Per-source progress is recorded, so an interrupted run resumes at the
unpolled source rather than re-fetching everything and re-tripping rate limits.

**Re-run.** Every run is additive and idempotent: an advert already stored is
updated, not duplicated, and an advert matching a tombstone by canonical URL or
normalised text hash is **not re-added as new** (§7.4). Purge runs here: offers
never shortlisted and older than 60 days lose their body and keep their
tombstone, reported rather than done silently.

**Privacy.** Queries carry constraints only — a role, a place, a band. No
profile, episode, trait or CV content is ever sent to a job source. Adverts are
public text and are stored in full.

> **✎ Notes** · `SPEC › Step 7 — Sourcing`
> _(your notes here — replace this line)_

## Step 8 — Understanding

**Purpose.** Automatic. The candidate gets offers described in the same
vocabulary as their profile, with the ad's own words as evidence.

**Preconditions.** New or changed offers to read, and a dimension model that
loads and validates. A model that fails validation stops this step rather than
extracting against a broken vocabulary — a bad extraction is worse than none,
because it looks like a result.

**Inputs.** `offers/*.json`; `dimensions/*.yaml`; previous extractions, so
unchanged offers are not re-extracted.

**Protocol.** No conversation. Prefilter for recall, then extract dimension
values with verbatim evidence spans, handling negation as inversion rather than
absence — "no on-call" is evidence *against*, not missing evidence. Record
`unmapped_concepts` rather than discarding what the model has no dimension for;
that count is the staleness signal for the model itself. **When an advert yields
very little** — four lines and a salary band is common — the step may look
outside it: what the company does, how it is spoken about, what former employees
say. **Anything found that way is marked as not from the advert**, and never
appears as a verbatim evidence span: `explained_fraction` means the employer's
own words, and citing a review site as though the employer wrote it is a lie
about provenance.

**Stop rule.** Every new or changed offer has an extraction. Hard cap: a
per-run extraction budget, since this is the step that costs model calls.

**When declined.** Not applicable — nothing is asked. A candidate may skip
outside-information lookups as a standing preference, recorded in
`constraints.json`.

**Outputs.** `extractions/<offer_id>.json` — per dimension a score, evidence
spans, and a provenance marker distinguishing the advert from outside sources.
The candidate sees, per offer, what it was found to say — and what it did not
say, which is not the same as saying no.

**Boundary.** Usually silent, folded into step 9's presentation. When run alone:
*"Read the fourteen new ones. Three don't say anything about how they work,
which is itself worth knowing."* Writes `last_activity`.

**Gate.** `extraction_macro_f1 >= 0.75` on the evaluation split, with
`extraction_negation_recall >= 0.80` and `ontology_hit_rate >= 0.85`. Owner:
T15, T16, T17. State: `not_implemented`.

**Resume.** Extraction is per offer and idempotent, so an interrupted run
resumes at the first offer without a current extraction.

**Re-run.** Replaces the extraction for any offer whose text changed or whose
extraction predates the current dimension model version. Preserves extractions
still current — re-extracting unchanged adverts spends money to reproduce a
result.

**Privacy.** Advert text goes to the extraction model. **Nothing from the
candidate's profile is sent with it** — extraction reads the advert, and
matching happens locally afterwards. That separation is what keeps the profile
from leaving the machine one advert at a time.

> **✎ Notes** · `SPEC › Step 8 — Understanding`
> _(your notes here — replace this line)_

## Step 9 — Ranking

**Purpose.** The candidate sees the live offers in order, each with the reason it
sits where it does, in words from the advert and numbers in their currency.

**Preconditions.** Extractions for the live offers, and `constraints.json`.
Weights are optional: without them the ranking is L1 and says so.

**Inputs.** `extractions/*`; `profile/constraints.json`;
`profile/weights.json` — **optional**; `profile/traits.json` where a dimension
is trait-side.

**Protocol.** No questions; this step presents. **Presentation is half the
specification**, not a rendering detail. Show a handful at a time, not forty.
Lead with the offer and the one thing that most moved it, not with a score.
Make the reason concrete: the sentence in the advert, and what it is worth per
month. Show what is *unknown* about an offer as unknown rather than as neutral —
an advert silent on hours is not an advert promising good ones. Say when the
ranking is provisional and what would sharpen it, in one line, once. Where an
offer is out of reach today but reachable, say what it would take and ask
whether that is of interest rather than assigning homework.

**Stop rule.** A ranking is produced and presented. Hard cap: the number shown
at once, so the list stays readable; the rest are available on request.

**When declined.** A candidate can ask not to see rankings for now; the run
still computes and stores one, so it is there when they come back.

**Outputs.** `rankings/<timestamp>.json`, pinned to the `profile_revision` and
the sufficiency level that produced it. The candidate sees the ordered list with
its reasons.

**Boundary.** *"Here are the top five. The Girona one is first mostly because
they say 'we don't do on-call' outright, which is worth about €400 a month to
you. Want to react to any of these?"* Writes `last_activity`.

**Gate.** `explained_fraction == 1.0` — every ranked offer cites at least one
verbatim span per contributing dimension. Calibrated by `rank_spearman >= 0.60`
against a blind manual ranking (T20). Owner: T18, T19. State: `not_implemented`.

**Resume.** Rankings are computed, not conversational. A ranking whose pinned
revision is behind the current one is shown as out of date with a one-click
recompute.

**Re-run.** Produces a new timestamped ranking and preserves every earlier one —
they are the record of how the candidate's ordering changed as the profile
deepened, which is the evidence that any of this worked.

**Privacy.** Entirely local: extractions and profile are both on the machine and
the ordering is arithmetic. Nothing about the ranking is transmitted anywhere.

> **✎ Notes** · `SPEC › Step 9 — Ranking`
> _(your notes here — replace this line)_

## Step 10 — Feedback

**Purpose.** The candidate says what they think of the offers in front of them,
and watches the list move because of it.

**Preconditions.** A ranking has been presented. Nothing else — this step exists
to catch what someone says while looking at real jobs, which is the most
informative moment in the whole process and the easiest to waste.

**Inputs.** The current `rankings/<timestamp>.json` and the offers it names, with
their extractions so a reaction can be attributed to what the advert actually
said; `profile/weights.json`, which this step's output revises.

**Protocol.** Follow, do not survey. Most feedback arrives unprompted — "not
another agency", "this one's interesting but the commute" — and the step's main
job is to be listening when it does. When prompting, prompt once and lightly:
*"anything here you'd rule out straight away?"* Never work down the list asking
for an opinion on each. Capture their words, extract afterwards, and **show the
consequence immediately**: which offer moved, and which sentence of theirs
caused it. That is the moment the tool stops feeling like a search box. Record
offer status changes as they fall out of the conversation — ruled out is
`screened_out`, interested is `shortlisted` — and never infer a status from
silence.

**Stop rule.** The candidate stops talking about the offers, or every offer they
raised has a recorded reaction. Hard cap: no prompt is issued more than twice in
a session.

**When declined.** Offered, and the most declinable step in the process —
someone who wants to read a list without being asked about it should be able to.
Decline is recorded so the prompt does not return next session. Unprompted
feedback is still captured, because that is them volunteering it.

**Outputs.** Evidence rows of kind `reaction` and `outcome`; offer status
changes with `status_changed_at`; a recomputed ranking. The candidate sees the
re-ordered list and a plain statement of what changed and why.

**Boundary.** *"Noted — agencies out. That dropped three of them and pushed the
Girona role to the top. Anything else, or leave it?"* Writes `last_activity`.

**Gate.** `feedback_traceability == 1.0` — every derived value names the evidence
rows that produced it, so "the ranking changed because you said X" is checkable
rather than a story. Owner: T21. State: `not_implemented`.

**Resume.** Feedback is naturally interruptible: rows are appended as they
arrive, so there is nothing partial to resume. `open_questions` carries anything
they raised that has not been followed up.

**Re-run.** Every ranking presentation is an opportunity for it. Additive:
reactions accumulate, statuses change forward through the transition table
(§7.1), and a rejection reason recorded here triggers a weight refit.

**Privacy.** Reactions are local. A rejection reason given to an employer is
different from one given here, and this step captures the second — the candid
version, which is exactly why it never leaves.

> **✎ Notes** · `SPEC › Step 10 — Feedback`
> _(your notes here — replace this line)_

## Step 11 — Application

**Purpose.** The candidate gets a CV and a covering letter written for one
specific advert, drawn only from things they actually said.

**Preconditions.** An offer with status `shortlisted`, and `cv/master.json` with
enough in it to draw on. With a thin store the step says what is missing and
offers Intake or History rather than producing a document padded with invention.

**Inputs.** `cv/master.json`; the offer and its extraction;
`profile/stories.jsonl` for episodes the letter might use; previous versions in
`cv/generated/<offer_id>/`.

**Protocol.** Select from the store against what the advert asks for, draft, and
show the candidate what was chosen and what was left out — the omissions are as
much a decision as the inclusions. **Every claim traces to a store entry**;
nothing is written that the candidate did not say. Where the advert asks for
something they lack, say so and offer the options honestly: apply anyway and
address it, or leave this one. **Any story-bank episode proposed for the letter
needs per-use approval** — recounting a failure to the tool was never consent to
send it to a company. The tool stops one step short of sending: the documents,
the text to paste into the employer's form, or an email left in drafts. The
candidate presses send.

**Stop rule.** A CV and a letter exist for this offer and the candidate has
approved them, or has parked them. Hard cap: three regeneration rounds per
offer, after which the useful move is to talk about what is wrong rather than
generate a fourth.

**When declined.** Offered per offer. Declining generates nothing and leaves the
offer `shortlisted`. A candidate who wants to write their own letter and only
use the CV gets exactly that.

**Outputs.** `cv/generated/<offer_id>/v<N>/` — CV and letter, **versioned**, plus
a manifest of which store entries each claim came from. On send,
`applications/<offer_id>/` records what went and when, and is immutable
thereafter. Offer status moves to `applied`.

**Boundary.** *"That's the CV and letter for the Girona role. I've led with the
migration work and left out the teaching — say if that's wrong. Ready to send,
or sit on it?"* Writes `last_activity`.

**Gate.** `cv_generation_traceability == 1.0` — the fraction of claims in a
generated document tracing to a specific store entry. Anything less is the tool
inventing experience on a candidate's behalf, which is the single worst thing
this project could ship. Owner: S4. State: `not_implemented`.

**Resume.** A draft in progress is saved as an unapproved version, so an
interrupted session resumes at review rather than regenerating.

**Re-run.** **Never overwrites.** A regeneration writes `v<N+1>` and preserves
every earlier version, because an earlier one may already be with an employer
and a candidate must be able to answer a question about their own application.
An updated CV store marks existing versions stale with the reason; regeneration
is offered, never automatic.

**Privacy.** This is the only step that produces something intended to leave the
machine, and everything in it is per-item approved. The store is never sent
as-is. If a model drafts, it receives the advert and **the selected entries
only** — not the store, not the trait profile, not the episodes that were not
chosen.

> **✎ Notes** · `SPEC › Step 11 — Application`
> _(your notes here — replace this line)_

## Step 12 — Interview

**Purpose.** The candidate walks in prepared, and afterwards turns what happened
into better preparation for the next one.

**Preconditions.** An offer with status `applied` and an interview arranged, for
the preparation half; a completed interview for the recording half. Either half
runs without the other — someone who arrives having already interviewed can
still log it.

**Inputs.** The offer and its extraction; `cv/generated/<offer_id>/`, so
preparation matches what was actually sent; `profile/stories.jsonl`;
`interviews/*` from earlier interviews, including for other offers.

**Protocol.** *Before:* work out what this employer is likely to press on — from
the advert's emphases, from what the application claimed, from what previous
interviews asked — and rehearse the episodes that answer it, using the bank
rather than inventing. Name the weak points honestly and prepare an answer for
each; a candidate ambushed by an obvious question was failed by the preparation,
not by themselves. *After:* record what was actually asked, what went well, what
they wish they had said, and the outcome when it comes. Ask about it gently and
soon, and not at all if they clearly do not want to relive it — a bad interview
is a bad day, and the lesson can wait until the next preparation.

**Stop rule.** *Before:* the likely questions have an answer each, or the
candidate says they are ready. Hard cap: 10 rehearsed questions. *After:* the
questions asked and the outcome are recorded, or the candidate stops.

**When declined.** Both halves are offered. Declining preparation is common and
fine. Declining to log an interview loses the lesson and nothing else; ask once,
later, and never twice.

**Outputs.** `interviews/<offer_id>/` — preparation notes, questions asked,
outcome, lessons — **immutable**, and exempt from purge regardless of the
offer's status. Evidence rows linking each lesson to a dimension or an episode.
The candidate sees, beforehand, what to rehearse; afterwards, what to carry into
the next one.

**Boundary.** *"Logged. They pushed hard on on-call and you didn't have much —
worth building that into a story before the next one. How did it feel?"* Writes
`last_activity`.

**Gate.** `interview_lesson_linkage == 1.0` — every logged interview produces at
least one evidence row linked to a dimension or a story-bank episode. An
interview that produces only prose is a diary entry; the point is that the next
one goes better. Owner: S6. State: `not_implemented`.

**Resume.** Preparation records which questions have been rehearsed. The
recording half resumes at the first unanswered part — questions, then outcome,
then lessons — and the outcome commonly arrives days later, in a different
session, which the step expects rather than treats as an interruption.

**Re-run.** Preparation may run any number of times before the interview and
replaces its notes each time. The record of what happened is historical: never
revised, only appended to. A later interview for the same offer is a new record,
not an edit of the old one.

**Privacy.** Interview records are among the most sensitive things stored —
what someone was asked, what they fumbled, why they were turned down — and they
never leave the machine. Nothing here reaches a future employer-bound document
without per-use approval, and a rejection reason is never quoted back to any
employer.

> **✎ Notes** · `SPEC › Step 12 — Interview`
> _(your notes here — replace this line)_

