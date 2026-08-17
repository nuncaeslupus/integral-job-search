# Brief for specification v2 — the whole process, then each step

**Status: input for the next session.** This is not the specification. It is
everything needed to write one: the owner's decisions, the requirements they
imply, a proposed step list to argue with, and the template each step's
specification must fill. The next session produces reviewable HTML spec
documents — first the whole process, then one per step.

Written 2026-08-16, after T2, T3, T4 and T23 landed.

---

## 1. Decisions taken (owner, 2026-08-16)

These close the three questions left open in `docs/product-shape.md`. They are
decisions, not proposals — the specification is written against them.

### 1.1 Several short conversations, one per step — with feedback loops back

Not one long interview. Each step is a **short, directed conversation with a
clear goal and an end**. A step that could run forever is a specification
failure, so every step needs a stop rule as much as it needs a gate.

The candidate can go **back** to an earlier step with new information at any
time, and doing so must not discard what later steps produced — it revises
them. "I updated my CV", "I left my job", "I got rejected and here is why" all
re-enter at an earlier step and propagate forward.

### 1.2 Traits update continuously

Traits accrue across every phase, not only in the trait interview. Scores update
as evidence arrives.

**Caveat the owner attached, and it is the right one:** if updating a trait
score needs LLM inference, that cost cannot be paid on every utterance. So the
specification must separate two things:

- **capture** — cheap, always on. Every phase appends evidence rows.
- **scoring** — potentially expensive. Runs at a defined point (step boundary,
  explicit request, or a batch threshold), never per message.

The profile is a pure function of the evidence log (T6), so deferring scoring
costs nothing but freshness, and the log is never behind.

### 1.3 Multi-user from day one

A directory tree per person. **The user is identified at the start of every
session** before anything is read or written — nothing may mix between people.
Expect a handful of users, not thousands: the design should be simple and
file-based, not a multi-tenant service.

Each person's tree holds: profile and traits, ranked offers, the CV and letter
generated for each position, and interview results — logged in a way that feeds
back into preparation for the next interview.

---

## 2. Requirements this adds

### 2.1 Every step specified professionally

Each step needs, written down: purpose, preconditions, inputs, the conversation
protocol, the stop rule, outputs, the measured gate, resume semantics, and what
happens when it is re-run. Steps must be runnable **in sequence or individually**.

### 2.2 The user must feel they are advancing

Each step ends with something concrete the candidate can see — a file, a list, a
draft, a number that moved. A step that only fills internal state has no visible
output and will feel like an interrogation.

### 2.3 Outputs are re-doable, not write-once

Every output can be updated or regenerated. The specification must say, per
output, what a re-run preserves and what it replaces. The CV case is the
motivating one: a candidate who updates their CV or leaves a job resumes the
process rather than starting it.

### 2.4 Ads have a lifecycle, including death

Old ads go stale. The specification needs:

- an explicit **status** per offer (new, screened out, shortlisted, applied,
  rejected, expired, archived);
- a **purge rule** for ads that were never shortlisted and are past their
  useful life;
- **tombstones** — a purged ad's id, URL and text hash are kept even when its
  body is not, so dedup and re-collection do not resurrect it;
- **retention** for ads that mattered: anything shortlisted, applied to, or
  interviewed for is kept in full, indefinitely.

### 2.5 Resumption is inferred, not commanded

Skills are not always invoked. The conversation itself indicates where the
candidate is: someone who stopped mid-interview yesterday should be able to say
"let's carry on" and land back at the right question. This requires per-user
session state on disk, and a rule for how the conversation reads it.

### 2.6 The CV is an input, a store, and an output

Three distinct things the current spec conflates:

1. **Input** — the candidate may supply a CV as PDF or DOCX, or may have none.
   If none, the tool helps produce a first version rather than demanding one.
2. **Store** — a "CV on steroids": everything the CV contains *plus* everything
   it omits. Episodes, failures and lessons, tools, numbers, certifications,
   languages, context of each role. Far more than hard skills, and never sent
   anywhere as-is.
3. **Output** — a CV generated **per ad**, drawn from the store and targeted at
   that ad's requirements, alongside a cover letter. So a CV is an output of the
   application step, not merely an input to onboarding.

### 2.7 CV templates (later, not v1)

Basic templates, always customisable, modular enough that a new one can be
assembled from the desired sections — possibly its own skill. Noted so the CV
store is designed to feed templates rather than one fixed layout.

---

## 3. Proposed step list — to be argued with, then specified

Twelve steps. Each is a short conversation or an automatic pass, with one goal.
Numbered as **steps** (the candidate's journey), distinct from the
specification's delivery **phases** (build order).

| step | name | goal in one sentence | visible output |
|------|------|----------------------|----------------|
| 0 | **Identify** | know whose tree we are in, and where they left off | greeting that names where they are |
| 1 | **Intake** | get the CV that exists, or build a first one | parsed CV in the store |
| 2 | **Constraints** | the facts that filter: place, permits, languages, hours, pay floor, mobility, cross-border | a constraints summary they can correct |
| 3 | **History** | the last job and the ones before: what they did, what went well, what did not, and why | story-bank episodes |
| 4 | **Traits** | how they work and what drives them, from behaviour rather than self-rating | a trait profile with the evidence behind each |
| 5 | **Preferences** | what they will trade for what, via forced choices | weights, in salary-equivalent terms |
| 6 | **Sourcing** | get offers in, deduped, with the stale ones retired | a list of live offers |
| 7 | **Understanding** | extract dimensions and evidence spans from each offer (automatic) | per-offer extraction |
| 8 | **Ranking** | order the live offers and explain each position | a ranked list with reasons |
| 9 | **Reaction** | capture what they think of the top offers and why | an updated ranking that visibly moved |
| 10 | **Application** | produce a targeted CV and letter for a chosen offer | the documents, per offer |
| 11 | **Interview log** | record what happened, and turn it into preparation for the next one | lessons attached to the profile |

Steps 0–5 are the first run. Steps 6–9 are the recurring loop. Steps 10–11 run
per opportunity. **Every step writes evidence**, so the profile deepens
throughout rather than only at the start (T28).

Open for the next session to settle: whether Constraints (2) and Intake (1)
merge, since a parsed CV answers several constraint questions already; and
whether Traits (4) is one step or is folded into History (3) with its own
coverage requirement.

---

## 4. The template every step specification must fill

```
### Step N — Name

**Purpose.** One sentence. What the candidate gets, not what the system does.

**Preconditions.** What must exist before this step can start, and what happens
when it does not (block, or run degraded and say so).

**Inputs.** Files and state read, with schemas.

**Protocol.** How the conversation goes: opening, required coverage, rules for
follow-ups, what to do with a negative episode, what is never asked.

**Stop rule.** How the step ends. Coverage reached, candidate declines, or a
hard cap. A step with no cap can run forever.

**Outputs.** Files written, with schemas, and what the candidate sees.

**Gate.** Metric, threshold, and the script that measures it. `not_implemented`
is a valid value while a step is unbuilt — a blank is not.

**Resume.** What is recorded so an interrupted step continues at the right
place, and how the conversation infers it without a command.

**Re-run.** What a second pass preserves and what it replaces.

**Privacy.** What is stored, what is derived, what may ever leave the machine.
```

---

## 5. Per-user tree (proposed)

```
profiles/<handle>/
  identity.json              handle, display name, locale, created
  session/state.json         current step, position within it, last activity
  cv/
    source/                  originals as supplied (pdf, docx)
    master.json              the CV on steroids — the store
    generated/<offer_id>/    cv + letter produced for one offer
  profile/
    evidence.jsonl           append-only, written by every step
    constraints.json         derived
    traits.json              derived, with evidence references
    weights.json             derived
    stories.jsonl            episodes
  offers/
    <offer_id>.json          normalised offer + lifecycle status
    tombstones.jsonl         purged ids, urls, hashes — dedup must not resurrect
  rankings/<timestamp>.json  pinned to a profile revision
  applications/<offer_id>/   what was sent, and when
  interviews/<offer_id>/     questions asked, outcome, lessons
```

`profiles/` is already gitignored (T1) and must stay so. Everything derived is
regenerable from `evidence.jsonl` and the offer store; nothing derived is edited
in place.

---

## 6. What the next session produces

1. **The whole-process specification** — the twelve steps (or however many
   survive the argument), how they connect, the artefact tree, the lifecycle
   rules, and the resumption model. Reviewable as HTML.
2. **One specification per step**, filling the §4 template. Also reviewable as
   HTML.
3. **Queue tasks** derived from those specifications, replacing or refining
   T24–T29 where they overlap.

Order matters: the whole process first, then each step. A step specified before
the process is settled will specify the wrong boundaries.

---

## 7. What is already settled and must not be re-litigated

The specification v2 inherits these; they are decided and implemented:

- **Dimension `side`** — matched / candidate fact / candidate trait (T23,
  merged). Traits carry no ad cues; facts filter against an ad-side requirement.
- **Unknown ≠ satisfied** — an unstated constraint neither passes nor vetoes,
  and surfaces as something still owed (T24).
- **Evidence is append-only, the profile is derived** (T6).
- **Gold provenance** — cue-derived examples are not evaluation data (D-2).
- **The corpus broadens before the model widens** (T25 before T26). Cues written
  from imagination look fine and match nothing.
- **Every gate is a measured number**, and a gate that could not run is not a
  pass.
