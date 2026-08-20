# Specification v2 — the whole process

**Version**: 2.1 — revised 2026-08-17 after the owner's review round
**Author**: nuncaeslupus
**Supersedes**: the step table in `docs/product-shape.md`
**Source**: `status/spec-v2-brief.md` (owner's decisions), owner's answers of
2026-08-17, and the sixteen review annotations in `docs/spec-v2/notes.json`
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

Three more were settled in the review round of 2026-08-17:

| # | Question | Decision |
|---|----------|----------|
| 6 | How is a candidate identified? | **A short handle they choose**, confirmed by display name at every later session. Not a legal name — the first thing the tool asks should be answerable the way a person introduces themselves. §6.1. |
| 7 | May a session delete another profile's data? | **Yes, after confirming the target by name.** Whoever is at the keyboard can delete the folder anyway; the tool adds a named confirmation rather than a refusal. §4.3. |
| 8 | Which steps are required? | **Identify, Constraints, Sourcing, Understanding, Ranking.** Every other step is offered, improves the result, and may be declined or deferred without blocking. §2.5. |

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

| step | name | req | goal | visible output | gate metric |
|------|------|-----|------|----------------|-------------|
| 0 | **Identify** | ● | know whose tree we are in, and where they left off | a greeting naming them, their last activity, and where they stopped | `cross_user_leaks == 0` |
| 1 | **Intake** | ○ | the CV that exists, or the same store built with someone who has none | a readable profile of their working life, every fact showing where it came from | `intake_field_provenance == 1.0` |
| 2 | **Constraints** | ● | the facts that filter, confirmed rather than re-asked | a constraints summary they correct in place | `constraint_field_resolution == 1.0` |
| 3 | **History** | ○ | the last job and the ones before: what they did, what went wrong, why they left | a story bank of episodes | `story_dimension_linkage == 1.0` |
| 4 | **Traits** | ○ | score what the evidence supports, ask only about what it does not | how they work, with the episodes behind each line | `trait_evidence_sufficiency == 1.0` |
| 5 | **Reactions** | ○ | real ads and ad fragments, and what the candidate makes of them | their own words against each stimulus | `elicitation_eval_overlap == 0` |
| 6 | **Preferences** | ○ | reactions and forced choices become weights | what each dimension is worth per month, in their currency | `weight_salary_equivalent_roundtrip_error <= 0.01` |
| 7 | **Sourcing** | ● | offers in, deduped, stale ones retired | what arrived, what duplicated, what expired | `offer_schema_violations == 0` |
| 8 | **Understanding** | ● | extract dimensions and evidence spans (automatic) | per offer, what the ad was found to say | `extraction_macro_f1 >= 0.75` |
| 9 | **Ranking** | ● | order the live offers and explain every position, legibly | a ranked list citing the ad's own words | `explained_fraction == 1.0` |
| 10 | **Feedback** | ○ | what they think of the offers in front of them | a re-ordered list, and why it moved | `feedback_traceability == 1.0` |
| 11 | **Application** | ○ | a CV and letter targeted at one offer | the documents, versioned per offer | `cv_generation_traceability == 1.0` |
| 12 | **Interview** | ○ | prepare for the interview, then record what actually happened | what to rehearse beforehand; afterwards, the lessons | `interview_lesson_linkage == 1.0` |

● required · ○ offered — see §2.5.

Steps **0–6** are the first run. Steps **7–10** are the loop the candidate
lives in afterwards. Steps **11–12** run per opportunity, any number of times,
in parallel across offers.

Every step writes evidence (T28). The profile therefore deepens throughout,
rather than only during onboarding.

Two things the table now says that the first version got wrong:

- **Step 6 is in the candidate's currency, not euros.** Currency is a profile
  field set from residence during Intake and overridable. Every
  salary-equivalent figure anywhere in the system is in it.
- **Step 12 is preparation first and a log second.** Its value is what the
  candidate rehearses *before* walking in; the record of what happened is how
  the next preparation gets better. Naming it "Interview log" described the
  file rather than the step.

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

**Intake never produces a document.** A candidate who arrives with no CV does
not get a PDF generated for them; they get the same structured store that
parsing a real CV would have produced, built by conversation instead. Document
generation happens once, at step 11, targeted at one advert. A CV written before
there is an advert to write it for is a worse CV than the one that step produces.

**Residence is Intake's job, and it is not a formality.** Where someone lives
decides their currency, their work authorisation, which borders they could
commute across, and how they would be taxed by an employer in another country.
Every one of those constrains the search, so the fact has to be established
early rather than inferred from a postcode on a document.

### 2.2 What a trait is, and why it gets its own step

**A trait is how someone works and what drives them.** How much autonomy they
need. How social they want the place to be. Whether they are pulled by learning
or by stability. How much process and ceremony they can stand before it grates.
Not skills, and not facts.

The distinction is structural, not a matter of taste (T23). A **fact** —
languages, location, salary floor — is compared against something the advert
*states*, so an ad can satisfy or violate it. A **trait** has no ad-side wording
to compare against: no job advert says "we want someone whose ambition is 0.7".
Traits therefore cannot be extracted from anything. They can only be inferred
from how a person talks about the work they have done — which is exactly what
the History step produces.

So the step is not an interrogation about personality. It is:

1. the defined point where **scoring runs** over everything already said —
   History's stories evidence most of these without anyone being asked directly;
2. a short conversation about the **few traits nothing yet supports**.

With a good History behind it, most of the work is already done and the step is
brief. Folded into History, it would have no stop rule other than "keep telling
stories until coverage" — the interrogation this design exists to avoid.

**The floor.** A trait is scored from at least two independent episodes recorded
on at least two separate occasions. One anecdote is a stereotype, and a profile
that is confidently wrong about someone is what makes them distrust everything
else the tool says.

**What the floor does is ask, not refuse.** Below it the trait reads
`insufficient` internally and the step looks for one more episode — in the
ordinary way, by asking about another job or another moment, never by announcing
a quota. Whether something sounds like a stereotype is a judgement made in the
conversation and acted on by asking a better question. It is never voiced. "Is
there another case like that, or are you a stereotype?" is not a question anyone
should ever be asked.

**What the candidate sees is not the word "traits".** Internally the term
matches the dimension model and stays. On screen this step is about *how you
work*, and it shows the episodes behind each line so the person can disagree
with it.

> **Owner decision if this is wrong.** Two episodes on two occasions is my
> number, not the owner's. It is the one threshold in this document that was not
> given to me.

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

**Stimuli are never invented.** Fetched live by preference, drawn from the
elicitation split of the corpus otherwise — but written by no one. An imagined
advert reads plausibly and represents nothing, which is precisely the failure
that put eight wrong cues into the dimension model with gold examples
demonstrating their own error (PR #8). A reaction to a fabricated advert teaches
the tool about the fabrication.

### 2.5 Required and offered steps

Five steps are required, because without them there is nothing to show: **0
Identify**, **2 Constraints**, **7 Sourcing**, **8 Understanding**, **9
Ranking**. Know who this is, know what vetoes a job, fetch, read, order.

The other eight are **offered**. Each improves the result and each may be
declined or deferred without blocking anything downstream. A candidate who
answers nothing but the constraints still gets a ranked list — a rougher one,
and labelled as such (§3.1).

This is not a licence to under-ask. It is what makes the non-insistence rule
(§5.4) safe to obey: when someone does not want to answer, there is always a
path forward that does not require them to.

**The claim has to hold in the graph, not only here.** Every input a required
step reads must be produced by another required step or marked optional (§3.1),
or "declining an offered step blocks nothing" is false the first time someone
declines Intake. The trace is 0 → 2 → 7 → 8 → 9.

### 2.6 Three steps the table under-describes

**Sourcing (7) is a research problem, not a fetch.** Where the offers come from
determines everything downstream, and the obvious portals are the worst of the
available sources. The step must reach specialised boards for the candidate's
field, and it must establish — at the moment it becomes relevant, not as an
opening questionnaire — how far the search can travel: remote, cross-border
commuting, relocation, working for an employer in another country while living
here. That last one is often where the money is, and it carries the questions
nobody enjoys: how would they be paid, employed or contracting, and taxed where.
Those answers change which offers are even legal to take, so they belong to
Sourcing's inputs rather than to a footnote at the application stage.

**Understanding (8) needs a rule for the ads that say nothing.** Plenty of
adverts are four lines and a salary band. When extraction yields few dimensions
the step does not simply record a sparse result: it may look outside the advert
— what the company does, how it is spoken about, what former employees say —
and add what it finds. **Anything sourced that way is marked as not from the
ad.** It never appears as a verbatim evidence span, because `explained_fraction`
means the ad's own words, and an explanation citing a review site as though the
employer had written it is a lie about provenance.

**Ranking (9) is half presentation.** An ordering nobody can read is not a
result. What the candidate sees — how many, in what order, how much of the
reasoning at once, what is offered next — is as much a part of the step's
specification as the arithmetic, and S2 specifies it rather than leaving it to
whatever the model does that day.

---

<!-- required-item: connections -->
## 3. How the steps connect

### 3.1 Forward: a dependency graph, not a queue

Steps run in order on a first run, but the order is a default, not the
mechanism. **Each step declares what it reads and what it produces**, and the
graph of those declarations is what decides whether a step can run:

```
0  identify      → handle, session state       [reads: —]
1  intake        → cv/master.json, claimed facts [reads: handle]
2  constraints   → constraints.json, currency, locale [reads: claimed facts?]
3  history       → stories.jsonl, trait evidence [reads: cv/master.json?]
4  traits        → traits.json                  [reads: trait evidence]
5  reactions     → reaction evidence            [reads: constraints.json]
6  preferences   → weights.json                 [reads: reaction evidence]
7  sourcing      → offers/*.json                [reads: constraints.json]
8  understanding → extractions                  [reads: offers/*.json, dimension model]
9  ranking       → rankings/<ts>.json           [reads: extractions, constraints.json, weights.json?]
10 feedback      → reaction + outcome evidence  [reads: a ranking]
11 application   → cv + letter per offer        [reads: cv/master.json, one offer]
12 interview     → preparation, then lessons    [reads: stories.jsonl, one offer]
```

**A `?` marks an optional input**, and those marks are what make §2.5 true rather
than merely stated. Every required step must be runnable from the outputs of
required steps alone, or "any offered step may be declined" is a promise the
graph breaks:

- **Constraints reads `claimed facts?`.** Intake is offered, so a candidate with
  no CV — or one who would rather just talk — arrives at Constraints with
  nothing pre-filled. The step then asks from scratch instead of confirming.
  What it must never do is treat an absent claim as a confirmed fact: unstated
  stays `unknown`, which neither passes nor vetoes.
- **History reads `cv/master.json?`** for the same reason — a CV makes the
  conversation better, and its absence makes it longer, not impossible.
- **Ranking reads `weights.json?`** — without weights it ranks on hard filters
  and defaults, and says so (L1, §3.1).

Trace the required steps alone — 0 → 2 → 7 → 8 → 9 — and every input is either
external or produced by another required step. That is the property that has to
hold, and it is worth re-checking whenever a step's inputs change.

Two more things follow, and both are the point of writing it this way.

**The order can bend.** A conversation that wanders into last year's redundancy
is doing step 3's work; the tool follows it rather than steering back, because
the graph says History's inputs are satisfied and its outputs are what just
arrived. What must never bend is a step running without its inputs.

**What is still owed is computable.** At any moment the tool can say which
outputs are missing and which step would produce them — that is what makes
"where were we?" answerable, and it is what keeps a long conversation from
losing the thread.

Three **sufficiency levels** are named milestones over that graph, recorded in
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

**The boundary is said out loud, and it is warm.** A step ends by naming what
was gained and offering the next thing — *"Good, I have your preferences now.
Want to go and look at some jobs?"* Two things are wrong with ending silently:
the candidate cannot tell that anything happened, and they are given no moment
at which stopping is a normal choice rather than an abandonment.

**That moment is made by pausing to ask, not by naming the exit.** Leaving is
always allowed and never the suggestion: the exit is offered when the session
has actually run long or the candidate sounds tired, never as the standard close
of a step. Offering it every time asks someone who has answered four steps four
separate times whether they would rather leave, which reads as the tool losing
interest. This is `status/spec-v2-steps.md`'s "Invite forward, do not offer an
exit", stated here so the two documents cannot be read as disagreeing.

**Two different things get called stopping, and only one of them is the exit.**
The *exit* ends the sitting: the candidate goes, and comes back another day.
§3.3's *offered skip* — *"we can stop here and go look at real jobs with what I
have"* — ends the **first-run climb**, not the session, and sends them forward
to a provisional ranking: sooner, and rougher. The rule above governs the exit
alone and never suppresses the skip, which §3.3 requires at the end of every
first-run step. Reading the two as one rule would delete a documented path
through the process.

**Gates are never mentioned.** `constraint_field_resolution` is how the
engineers know the step is done. What the candidate hears is that we have what
we need. A number quoted at a person turns a conversation into an assessment.

### 3.3 The offered skip

The default path is the full first run, and the tool says plainly why: **the
more it knows, the better the results.** But at the end of every first-run step
it offers the alternative — *"we can stop here and go look at real jobs with
what I have; the list will be rougher and I'll tell you what would sharpen it."*

**This is a move forward, not the exit of §3.2**, and the "invite forward, do
not offer an exit" rule has no bearing on it: the skip is required here at every
first-run step, while the exit is offered only when the session has actually run
long. What the candidate is offered is an earlier ranking, never the door.

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
| "I got rejected, and here is why" | 10 Feedback or 12 Interview | 6 (weights) → 9 (recompute) → the offer's lifecycle status |

`reentry_events` in `spec-v2-steps.json` carries the full list per step.

**These three are examples, not the set.** "I moved", "I finished the course",
"I've started thinking about the public sector instead", "I had a child" — each
one changes something, and the tool's job is to work out *what* it changed and
which steps therefore have stale inputs. The graph in §3.1 is what makes that a
computation rather than a guess: name the outputs the news invalidates, and the
steps that read them are the ones to revisit.

**A change of mind is a legitimate input.** Someone who came in looking for
private-sector work and leaves wanting a public-sector post has not wasted the
process; they have used it. What they are looking for may be stated outright or
inferred from a run of answers, and either way it is evidence like any other —
recorded, revisable, never assumed permanent.

**Some propagation is advice, not recomputation.** If the path they now want
needs a qualification they do not have, the honest response is to say so with a
number attached — *"that route would mean about six months of study first; is
that something you'd take on?"* — and let them decide. See §8.

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

### 4.3 Deletion — of a fact, and of a person

Retraction handles one fact. **Deleting a person is a different operation and
must exist**: "delete everything you have about me" removes
`profiles/<handle>/` entirely — evidence log, stories, CV store, offers,
rankings, applications, interviews. Nothing is retained, including tombstones,
which are per-profile.

Deletion is confirmed once, by naming what goes, and it is not reversible. That
is the point of it.

**Deleting another profile is permitted, after confirming the target by name.**
Anyone who can run the tool can delete the directory with a file manager, so a
refusal would protect nothing and would merely make the tool useless to a
household that shares a laptop. What the tool adds is that the target is stated
before it happens — *"this will permanently delete everything for Ana: profile,
stories, offers, applications. Confirm by typing her name."* An instruction that
does not name a profile deletes nothing.

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

**`last_activity` is rewritten at every step boundary, and this is a line every
step specification repeats.** Stated once as a general principle it will be
forgotten by whichever step spec is written last; stated per step it is a thing
that either is in the document or is not. The same holds for the writing rule
behind it: **state is written when something new is known, not at the end.** A
session that closes and never returns must leave behind everything that was
learned before it closed — the files are the memory, and a memory written only
at the end is not one.

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

**The non-insistence rule comes first, because it overrides the others.**

> When cooperation drops, stop asking. A subject declined once is not raised
> again in that step; a subject declined twice is not raised again at all unless
> the candidate reopens it. **It is better to find a worse job than to make
> someone feel bad about the questions.** Coverage is a target, never a
> requirement to be extracted from a person — and §2.5 guarantees there is
> always a path forward without the answer.

The rest:

- **Say why.** Each step opens with what it is for and what it will store — once
  per step, not per question.
- **Knowing them is how it helps them.** The tool says so, and means it: every
  question exists because an answer improves the offers they get. A question
  that cannot be justified that way should not be asked.
- **A friend, not an assessor.** The candidate's advocate — their lawyer, not
  the prosecution. Sincerity produces a better search, and it is only offered to
  someone who does not feel judged. Negative episodes get a follow-up about what
  was learned, never a verdict (T27).
- **Ask warmly and concretely.** "How's your English?" rather than "Which
  languages do you speak, and at what level?" — the first gets an honest answer
  and the second gets a form filled in. Vary the phrasing; a question asked the
  same way twice reads as a script.
- **Their language.** The conversation happens in whatever language the
  candidate uses. Evidence keeps their own words, verbatim, in that language.
- **Nothing covert.** An evidence row exists only for something said in a step
  the candidate knew was recording. There is no silent capture.
- **Always answerable.** "What do you know about me?", "forget that", and
  "delete everything" work at any point in any step, and are answered before the
  step continues.

---

<!-- required-item: artefact-tree -->
## 6. The per-user tree, and identification

Multi-user from day one (brief §1.3). A handful of people, file-based, not a
multi-tenant service.

The tree's root is **`$INTEGRAL_HOME/profiles/`**, not a directory inside the
clone — `$INTEGRAL_HOME` defaults to `~/.integral-job-search/` and respects
`$XDG_DATA_HOME` where it is set (`docs/distribution.md` §2, made mechanical by
T51 in `jobsearch.state_home`). The resolver **refuses** to return any path
inside a git work tree, with `--dev` / `INTEGRAL_DEV=1` as the single explicit
escape for work on the tool itself.

```
$INTEGRAL_HOME/profiles/<handle>/
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

`profiles/` is gitignored (T1) and stays so — the cheap belt behind the
resolver's braces, since a tree resolved outside every work tree is not there
to stage. Every derived file is regenerable
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

**The key is a handle the candidate chooses, not a legal name.** On a first run
the tool asks what to call them, and derives a directory-safe handle from the
answer; `identity.json` keeps the display name they gave, their language and
their locale. Later sessions greet by display name and ask for confirmation.

A full name is not required and is not asked for as an opening. The first thing
the tool says should be answerable the way a person introduces themselves, and
"what is your full legal name and profession" is a form. If two profiles would
collide on one handle, the tool asks for something to tell them apart rather
than inventing a suffix.

**The candidate must be identified before the tool answers anything at all.**
Not merely before writing — before reading. A session that begins by answering a
question about "my CV" has already guessed whose CV it is. The opening move is
always to establish who this is, and it is a short, friendly one.

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

**If sending is ever built, the gate is a summary of everything that would go.**
Not "shall I apply?" but the actual payload — which documents, which claims,
which contact details, to whom — approved once per application, never as a
standing permission.

**The default is to stop one step short of sending**, and that is not a
limitation. Prepare the text to paste into the employer's form, produce the
files to attach, write the email and leave it in drafts. The candidate presses
send. That keeps the last decision with the person whose name is on the
application, and it costs them a few seconds.

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

**What the employer said back is part of that history.** A rejection, a silence
that ran past a stated date, an invitation, an offer, the reason given —
recorded against the application and kept with it. Half of what an application
teaches is in the reply, and it is also the evidence that feeds the next
ranking's weights (step 10).

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

**`text_sha256` is over normalised text, and the normalisation is part of the
contract**, because a hash is only useful if the same advert hashes the same way
every time it is seen. The rule: strip the source's chrome (navigation, cookie
banners, "similar jobs", the application form), strip volatile stamps ("posted 3
days ago", view counts, expiry countdowns), strip tracking parameters from any
embedded URL, collapse whitespace, lowercase, then hash the remainder. It is
declared once and versioned — changing it invalidates every existing tombstone,
so the version travels with the hash.

**And it must be said plainly what this does not catch.** Two portals carrying
the same job rarely carry byte-identical text: one truncates, one adds its own
summary, one translates the title. Those hash differently and the tombstone will
miss them. Exact-hash matching catches re-collection of *the same listing*;
cross-posted near-duplicates are a similarity problem and remain T13's
(`dedup_precision >= 0.95`). A tombstone consults both, and the honest summary
is that the hash is the cheap half.

**Which URL is canonical.** Sources are normalised — tracking parameters and
session ids removed — and when one role is found at several, a single offer is
kept carrying all of them. The employer's own posting is preferred as canonical
when it is among them: a company careers page outlives an aggregator's listing,
and an ad that expires at one source is not an ad that no longer exists.

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

## 8. What the tool owes beyond matching

A ranked list is the mechanism, not the job. The job is that someone ends up in
better work than they would have found alone, and three of the ways that happens
are not matching at all.

**Widen the field.** Someone arrives with a job title in mind — the one they
last held. The profile that accumulates over the first run frequently implies
others they never considered, in adjacent fields or built on a part of their
experience they think of as incidental. Naming those is one of the most valuable
things the tool can do, and it costs a sentence: *"given what you've said about
X, there's a whole kind of role you haven't mentioned — want to see some?"* An
offered widening, never a substitution for what they asked for.

**Be honest in both directions.** Someone who is sure they are ready for
something they are not should be told, kindly and specifically — what is
missing, and what would close it. Someone convinced they are not good enough for
a job they would plainly get should be told that too, and encouraged to apply.
The second is more common than the first and does more damage: people rule
themselves out of work they could do, and a tool that quietly ranks around that
belief has confirmed it. Both are said with the evidence attached, from the
profile and from what the adverts actually ask for.

**Say what it would take.** When a role is out of reach today but reachable, the
useful answer is the route — the certificate, the six months, the one project
that would change the reading — offered as a question rather than a homework
assignment. *"That path needs about six months of study first. Is that something
you'd take on?"*

Realistic but positive is the standard: never flattery, never discouragement,
always the reason and the evidence. This is process-level because every step can
do it, and because a tool that only ever ranks will never do it at all.

---

## 9. Where the gates come from

Every step in §2 names one gate metric. Ten reuse metrics that already exist in
`status/plan.md`; three are new and are named here for the first time:

| metric | step | owner |
|--------|------|-------|
| `intake_field_provenance` | 1 Intake | S4 — every field in `master.json` traces to a document span or a conversation turn |
| `constraint_field_resolution` | 2 Constraints | T41 — every constraint field is `stated`, `declined` or `unknown`, never blank (the field set itself is pinned by T24) |
| `trait_evidence_sufficiency` | 4 Traits | T49 — every trait carries either a score with ≥2 independent episodes, or `insufficient` |
| `interview_lesson_linkage` | 12 Interview log | S6 (to be seeded) — every interview produces ≥1 evidence row linked to a dimension or a story |

Every metric is currently `not_implemented` at the step level, which is a
truthful statement of a specification that has not yet been built against — and
`not_implemented` is a recorded value, not a blank. `spec-v2-steps.json` carries
the state per step, and S2 may not leave one empty.

---

## 10. What S2 inherits

S2 writes one specification per step, filling the template in
`status/spec-v2-brief.md` §4. From this document it inherits, and must not
re-decide:

- the **thirteen steps**, their boundaries, and their order;
- which five are **required** and which eight are offered (§2.5);
- the **visible output** each step owes the candidate;
- the **gate metric** each step is measured by;
- the **inputs and outputs** each step declares (§3.1) — a step's preconditions
  are its inputs, not a position in a queue;
- the artefact classes (§3.4) — so "what a re-run preserves and what it
  replaces" is answered per output by which class it belongs to;
- the manner and disclosure rules (§5.4), which no step restates — above all
  the **non-insistence rule**, which overrides every coverage target.

S2 must decide, per step: the conversation protocol, the coverage requirement,
the **stop rule** (coverage reached, candidate declines, or a hard cap — a step
with no cap runs until the candidate gives up), the elapsed-time thresholds for
proactive re-entry into that step, the batch threshold N for scoring, and
exactly what leaves the machine.

Three lines every step specification repeats verbatim, because a rule stated
only in this document is a rule the last step spec written will not have:

1. **`last_activity` is rewritten when this step ends** (§5.1).
2. **What this step says out loud at its boundary** — what was gained, what is
   next, and that stopping here is fine (§3.2).
3. **What this step does when the candidate declines** — which is never to ask
   again in the same breath (§5.4).

`step_count` is 13. S2's gate is `step_specs_complete_fraction`, whose divisor
is that number read from `spec-v2-steps.json` — never from counting the files
that happen to exist, because dividing by what was written makes any amount of
work look complete.

---

## 11. Open, and deliberately so

1. **Two episodes on two occasions** as the trait-scoring minimum (§2.2) is my
   number. If the owner wants three, or wants it per-trait, S2 is the place.
2. **Elapsed-time thresholds** for proactive re-entry (§5.2) are per step and
   belong to S2. "Two years" is the owner's example, not a configured value.
3. **Which sources** the Reactions step fetches stimuli from (§2.3) depends on
   the connectors T11/T12 deliver. The requirement — live, quick, multi-source,
   relevant — is settled; the source list is not.
4. **CV templates** remain out of v1 (brief §2.7). The store is designed to feed
   templates rather than one layout, which is all that is owed now.
5. ~~**How this is distributed** is undecided~~ — **settled 2026-08-18, and
   recorded in `docs/distribution.md`.** The tool is installed by cloning the
   repository, and the per-user tree of §6 resolves from `$INTEGRAL_HOME`
   (default `~/.integral-job-search/`) rather than from a path inside the
   clone — a resolver that refuses any location inside a git work tree, so
   "candidate data never reaches a repository" is a property of the code and not
   of a `.gitignore` line. As anticipated here, the tree in §6 did not depend on
   the answer: nothing in it changes, only where its root resolves from.
   Job-site connectors live in a separate repository and enter as a dependency;
   contributing one is offered, disclosed in full, and may be declined without
   consequence (§5.4's non-insistence rule, applied to contribution).
6. **Which sources Sourcing uses** (§2.6) is the same shape of question as (3):
   the requirement — specialised boards, cross-border reach, the payment and tax
   questions asked at the right moment — is settled, and the list of connectors
   arrives with T11/T12.
