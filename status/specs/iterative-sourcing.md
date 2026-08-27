# Iterative sourcing: the search is the conversation

Feature spec, 2026-08-24. Amends the process spec. Sections 1–4 (`specify`); 5–6 are
`design`'s to append. Companion to `preference-directed-sourcing.md` (#154), which this
supersedes in scope: that spec proposes a second directed *pass*, this one makes the pass
a *cycle* and gives the tool a voice in steering it.

---

## 1. Problem statement

The process graph is already a loop and says so. `integral.step_graph`: *"No acyclicity
check, deliberately. Feedback (10) produces reaction evidence that Preferences (6) reads,
whose weights Ranking (9) reads, whose ranking Feedback reads — the loop is the product,
not a defect in the graph."*

**Sourcing is outside that loop.** §3.1's graph declares:

```
7  sourcing      → offers/*.json                [reads: constraints.json]
```

Step 7 reads the constraints and nothing else. Constraints are settled at step 2, before
the candidate has seen a single advert. So the offer set is fixed by the least-informed
moment in the process, and everything learned afterwards — fitted weights, reactions,
feedback, outcomes, the whole point of steps 5, 6 and 10 — can re-rank and re-weight that
fixed set forever without ever being able to go and look somewhere else.

The first blind sitting measured the cost: of twenty adverts, one was worth applying to.
The ranking ordered exactly the list it was handed. **No amount of re-ranking reaches
that**, because the list is the input to ranking, not its output.

Two mechanisms are missing, not one:

* **The tool cannot notice it is stuck.** §5.2's freshness triggers (T36) already license
  re-entering a finished step, and already require it to *say why* — but they fire on
  **staleness**, elapsed time since something was recorded. "This search keeps returning
  offers you reject for the same reason" is not staleness. Nothing computes it.
* **The tool cannot propose a change of scope.** A search that is too narrow and one that
  is too broad fail differently and are fixed in opposite directions, and choosing between
  them is a judgement about the candidate's situation — exactly the judgement a
  conversation is for. Today step 7 has no way to say anything at all.

This is what a person does when they job-hunt: search, read some, notice the results have
gone stale or gone wrong, change what they are searching for, go again. The product
already promises the candidate a conversation. It does not currently have one about the
only decision that determines what they get to choose between.

### Success criteria (measurable)

| Metric | Threshold | Why this number |
|---|---|---|
| `sourcing_inputs_excluding_learned_evidence` | `== 0` | Step 7's declared inputs include the weights and the reaction/outcome evidence, in **both** §3.1's prose and `spec-v2-steps.json`. `step_graph.drift_violations` already fails when the two disagree, so this cannot be half-done. |
| `narrowings_without_a_recorded_decision` | `== 0` | A cycle may narrow onto one employer, one country, one stack — **when the candidate chose it**. The failure is the algorithm quietly shrinking the world while nobody notices. Consent is the discriminator, so consent is what is counted. |
| `scope_proposals_offering_only_narrowing` | `== 0` | The guide must be able to say *"we are too focused, shall we widen?"*. A tool that only ever proposes narrowing is a machine for confirming whatever the candidate said first. |
| `stuck_cycles_without_a_proposal` | `== 0` | When a cycle meets the exhaustion condition, the tool proposes a change of scope rather than running the same search again. |
| `exhaustion_triggers_without_a_reason` | `== 0` | Mirrors what §5.2 already demands of freshness triggers: a trigger that fires without saying why is indistinguishable from a bug. |
| `cycle_rejection_rate` | strictly decreasing across a candidate's cycles, or the cycle proposes a scope change | Each search must be better than the last. Where it is not, that *is* the exhaustion condition — so this metric and the trigger are the same measurement read twice. |

All within-subject. There is no central store, no cross-candidate comparison, and neither
is sought.

### The amendment this implies to `status/specification.md` §1

§1 currently argues the differentiator is that the candidate's non-skill dimensions survive
the trip from questionnaire to ranked list. That stays true and stays the mechanism. What
it omits is where the mechanism pays off: **the dimensions are what make an iterative
search steerable at all.** Knowing that this candidate weights remote arrangement above pay
is what turns "search again" from a coin toss into a direction.

So §1 gains a sentence, and does not lose one. Search is the point of application; the
dimension model is the mechanism. Replacing the model with search would describe a tool
that already exists and that §1 exists to distinguish this one from.

---

## 2. Systems & Impact

### Dependency map

| System | Role | Needs change? |
|---|---|---|
| `status/spec-v2-process.md` §3.1 | The prose step graph; step 7's `reads` list | **Yes** — the edit at the centre of this spec |
| `status/spec-v2-steps.json` | The machine-readable graph | **Yes** — in the same commit, or `drift_violations` fails |
| `integral.step_graph` | `closure_violations`, `unproduced_inputs`, `drift_violations` | Validation — the gates that keep the two in step |
| `integral.spec_consistency` (D-3) | Three documents agreeing on what the product is | **Yes** — §1's amendment must reach every document that states it |
| `status/specification.md` §1 | The product's argument | **Yes** — one sentence |
| `integral.step_runtime` | `offered`, `is_finished`, `decide_resumption` | **Yes** — a finished step 7 must become offerable again on exhaustion |
| `integral.freshness` (T36) | Re-entry triggers, each carrying its reason | **Yes** — a new trigger kind: exhaustion, not staleness |
| `integral.sourcing_strategy` (#154, unbuilt) | The directed pass | **Yes** — becomes a cycle rather than a second pass |
| `step-07-sourcing`, `step-10-feedback` skills | What the tool actually says | **Yes** — the strategy conversation lives here |
| Profile evidence log | Where the decision and its reason are recorded | Read/write — a scope decision is candidate evidence like any other |
| `integral.dedup`, `robots`, `lifecycle` | Repeat cycles re-fetch | Validation only |

### Impact assessment

| Dimension | Severity | Notes |
|---|---|---|
| Data | **Medium** | Scope decisions and exhaustion triggers are new evidence rows. Nothing is schema-breaking; the log already carries `about` and a reason. |
| API | **Medium** | Step 7's declared inputs change, which is a graph change two gates check. No runtime contract breaks. |
| Performance | **Medium** | Cycles multiply fetches. `robots` and rate limits are unchanged, so the ceiling is courtesy. |
| User | **High** — intended | The candidate is asked to steer. Done well this is the product; done badly it is an interrogation, and the difference is how often the tool speaks and how good its proposals are. |
| Operational | Low | Runs in the candidate's own session. |
| **Anchoring** | **High** | New, and specific to this change. A conversational guide is the most anchoring surface this product has — more than a ranking, far more than a card. `blind_ranking_leaks`, D-2 and the elicitation/evaluation split all exist because anchoring is this system's characteristic failure, and every one of them guards a weaker surface than a question like *"shall we focus on US companies?"*. The symmetry gate (`scope_proposals_offering_only_narrowing == 0`) is the countermeasure, and it is not optional. |
| Risk if nothing changes | **High** | The measured result stands: one in twenty. Every downstream improvement polishes the ordering of a list that does not contain the job. |

---

## 3. Options

### Option 1 — Widen step 7's inputs, and nothing else

Add the fitted weights and the reaction/outcome evidence to step 7's `reads` in both the
prose graph and the JSON. The loop closes; nothing else changes.

- **Scope**: two documents, both gates.
- **Effort**: Small.
- **Trade-offs**: Honest and tiny, and it makes every later option legal. But it only makes
  re-sourcing *expressible* — nothing decides when to re-source or how to change the scope,
  so in practice step 7 runs once anyway and the graph merely stops lying about why.
- **Compatibility**: Backwards compatible.

### Option 2 — The loop plus the strategy conversation *(recommended)*

Option 1, plus the machinery that uses it: an **exhaustion measurement** (a cycle whose
rejection rate did not improve, or whose rejections concentrate on one reason), a **scope
proposal** the tool makes in conversation — symmetric, able to widen or narrow, with the
reason stated — and a **recorded decision** that licenses the narrowing.

- **Scope**: Option 1, plus `integral.freshness` (new trigger kind), `step_runtime`,
  `integral.sourcing_strategy`, the two step skills, evidence rows for decisions.
- **Effort**: Medium.
- **Trade-offs**: This is the feature as described. It stops short of one thing the
  candidate asked for — re-entering steps 3 and 4 to gather more about them — see Option 3
  for why that is sequenced rather than dropped.
- **Compatibility**: Backwards compatible; a candidate who never hits exhaustion sees no
  change at all.

### Option 3 — Option 2, plus re-entry into profile steps

When the search is exhausted *and* the profile evidence behind the deciding dimensions is
thin, the tool offers to go back — more history, an unexpected skill, an aspect of the
candidate's life nobody asked about — and uses what it learns to search differently.

- **Scope**: Option 2, plus `offered()`/`decide_resumption` and the profile-step skills.
- **Effort**: Large.
- **Trade-offs**: The most powerful version and the most annoying failure mode in the whole
  product. Being sent back through questions you already answered, because a search did not
  work, is the experience that makes people close a tool. It needs the exhaustion signal to
  exist and to be *trusted* first — otherwise the tool interrogates the candidate every
  time a search is merely unlucky.
- **Compatibility**: Backwards compatible.

### Comparison

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Effort | Small | Medium | Large |
| Closes the graph loop | Yes | Yes | Yes |
| Decides when to re-search | No | Yes | Yes |
| Tool can propose scope changes | No | Yes | Yes |
| Can gather new profile evidence | No | No | Yes |
| Worst failure mode | Graph says a thing nobody does | A badly-timed question | Interrogation |

---

## 4. Recommendation

**Option 2 now; Option 3 as its own task immediately after, gated on the exhaustion signal
having been observed to be right.** *Confirmed in review (2026-08-24): 2, then 3.*

Option 1 alone is not worth shipping by itself: a graph edge nobody traverses is
documentation, not a feature. Option 2 is the thing the candidate described — the tool
noticing, proposing, and the candidate deciding — and its consent rule resolves what would
otherwise be a contradiction in the design. An earlier review note said a cycle must never
collapse onto one employer; a later one said collapsing onto one employer is *good* when
the conversation went there. Both are right, and the difference between them is entirely
whether the candidate chose it. So the gate counts recorded decisions, not employer share.

Option 3 is sequenced rather than dropped because its failure mode is asymmetric: a missed
opportunity to ask costs one cycle, and an unwanted interrogation costs the candidate's
willingness to keep using the tool. The exhaustion measurement has to earn trust before it
is allowed to send someone back through step 3.

### Immediate next action

Run `design` over this spec to produce sections 5–6 and the task split. The first task is
the graph amendment (Option 1's content) — it is small, it is gated twice over by
`drift_violations` and D-3, and every other task depends on step 7 being allowed to read
what the candidate has taught the system.

### Open questions

1. **What exactly is exhaustion?** **Settled in review: the third — "we are finding the
   same jobs again".** A cycle whose offers largely dedupe against ones already seen, or
   that returns nothing of interest. It needs no preference model, no fitted weights and no
   rejection history, so it works on a candidate's first afternoon as well as their tenth,
   and `integral.dedup` already computes the hard part. The rejection-rate and
   single-reason variants remain available as refinements once there is a cycle to
   calibrate them against.
2. **How often may the tool speak?** **Partly settled: observe it, and start from common
   sense.** A proposal is licensed by a trigger, so the question is the trigger's
   sensitivity, and the honest answer is that it cannot be tuned before there is a cycle to
   watch. The design should make the threshold a named constant carrying its reasoning
   rather than a tuned number pretending to be evidence — the shape `weights.MAX_CHOICES`
   and `harness.EVALUATION_SHARE` already use.
3. **Does a scope decision expire?** **Settled in review: not on a clock — it is
   re-surfaced.** When the candidate returns they are shown a summary of what the system
   holds about them, scope decisions included, and can correct it. Better than an expiry,
   because a decision does not become wrong after N days — it becomes wrong when the
   candidate's situation changes, and only they know when that was. Step 0 already opens
   with *"last time we were partway through your work history"*; this extends that opening
   from position to substance. It also makes the standing scope visible, which the consent
   gate needs: consent nobody can review is not consent.
4. **What does the tool do with a refused proposal?** **Settled in review: record it, and
   re-asking later is allowed.** A refusal is evidence about the candidate and is not
   permanent — circumstances change and so does the offer pool. What it must not become is
   the same question next cycle in different words, so the design owes a rule for *when* a
   refused proposal may return: a changed trigger, new evidence, or a new session, never
   simply the next cycle.
5. **Does an exhausted search ever mean "there is no job for you right now"?**
   **Settled in review: yes, and the tool must be able to say it.** Every option above
   otherwise assumes a better search exists, and a tool that cannot report an empty market
   will manufacture a scope change instead — proposing a widening it does not believe in,
   which is worse than silence because the candidate acts on it. This needs a gate of its
   own, because "no result" is the outcome a tool is most tempted to dress up:
   `exhausted_searches_reported_as_a_scope_change == 0`. It also needs a shape — what the
   tool says, what it offers next, and how it distinguishes "the market has nothing this
   month" from "we have looked in the wrong place" — opposite diagnoses with opposite
   remedies.

   **Settled in review: the conversation says so, and the signal is exhaustion that
   survives steering.** One stale cycle means look elsewhere. Repeated cycles returning the
   same or similar adverts *after the scope has been both broadened and narrowed* mean the
   market is the problem rather than the search — the distinction above, reached by having
   tried the remedy for the other diagnosis and watched it fail. The candidate's own words
   for what the tool should then say:

   > "It looks it's not a good day to find jobs. Do you want to leave it for today and try
   > again tomorrow or next week?"

   Note what that offers: a **time**, not a compromise. The alternative — proposing to
   relax a hard constraint because nothing was found — asks the candidate to want a
   different job than the one they want, and it is the move a tool reaches for when it
   cannot admit an empty result.

---

## 5. Contracts

Option 2, made concrete. Every shape below is additive: a candidate who never reaches
exhaustion sees none of it, and no existing row, file or gate changes meaning.

### 5.1 The graph edge — step 7's inputs

The one edit Option 1 contains, in **both** documents or neither. `step_graph.drift_violations`
fails when the prose and the JSON disagree, so this is a single commit by construction.

`status/spec-v2-process.md` §3.1:

```
7  sourcing      → offers/*.json   [reads: constraints.json, weights.json,
                                            evidence.jsonl(reaction, outcome)]
```

`status/spec-v2-steps.json`, step `sourcing`:

```json
"reads": [
  {"artefact": "constraints", "optional": false},
  {"artefact": "weights", "optional": true},
  {"artefact": "reaction_evidence", "optional": true},
  {"artefact": "outcome_evidence", "optional": true}
]
```

**All three new inputs are `optional: true`, and that is load-bearing.** Step 7 must stay
runnable on a candidate's first afternoon, before any weight is fitted or any reaction
recorded — `missing_inputs` treats a required artefact as blocking, and a first-cycle
sourcing step that reports itself blocked on evidence that cannot exist yet would make the
loop a precondition for entering the loop.

### 5.2 Exhaustion — the measurement

Settled in review as the dedup form: *"we are finding the same jobs again."* No preference
model, no fitted weights, no rejection history, so it works on cycle two.

```python
class Exhaustion(Strict):
    """Why a sourcing cycle is judged to have stopped finding anything new."""

    cycle: int  # 1-based, within this candidate
    offers_returned: int
    offers_already_seen: int  # dedupe against every offer in the candidate's tree,
    # including purged tombstones — a purged ad the search
    # keeps re-finding is the definition of stuck
    repeat_share: float  # offers_already_seen / offers_returned, 0.0 when none
    exhausted: bool
    reason: str  # never empty when `exhausted` — §5.2's rule, applied here
```

`repeat_share == 0.0` when `offers_returned == 0`: a cycle that returned nothing is
exhausted for a different reason, carried in `reason`, and must not read as "nothing was
repeated, so all is well."

**The threshold is a named constant carrying its reasoning**, per open question 2 — the
shape `weights.MAX_CHOICES` and `harness.EVALUATION_SHARE` already use:

```python
#: A cycle is exhausted when this share of what it returned was already seen. Chosen by
#: common sense and not by evidence: there is no cycle to tune against yet, and a tuned
#: number pretending to be evidence is worse than an honest guess that says so. Revisit
#: once a real candidate has run four or more cycles.
EXHAUSTION_REPEAT_SHARE = 0.8
```

### 5.3 The trigger — exhaustion is not staleness

`integral.freshness` (T36) already re-opens a finished step and already requires a reason.
This adds a **kind**, and changes nothing about the existing one.

| kind | fires on | reason names |
|---|---|---|
| `stale` (existing) | elapsed time since something was recorded | what went stale, and when |
| `exhausted` (new) | `Exhaustion.exhausted` | the repeat share, the cycle number, and what was repeated |

A trigger with an empty `reason` is a violation of `exhaustion_triggers_without_a_reason`,
not a trigger. This mirrors what §5.2 of the process spec already demands of staleness, and
is the same rule rather than a second one.

### 5.4 The scope proposal — symmetric by construction

```python
class ScopeProposal(Strict):
    direction: Literal["widen", "narrow"]
    facet: str  # what would change: employer, country, stack, seniority, pay floor
    reason: str  # why, in the candidate's terms, citing what was observed
    alternatives: list[ScopeProposal]  # never empty, and never all one direction
```

**`alternatives` must contain at least one proposal of the opposite `direction`.** That is
the whole of `scope_proposals_offering_only_narrowing == 0`, enforced in the type rather
than in the skill's prose, because prose is what drifts. A tool that can only ever propose
narrowing is a machine for confirming whatever the candidate said first — and this is the
most anchoring surface the product has, more than a ranking and far more than a card.

### 5.5 Consent — a narrowing needs a recorded decision

A scope change is candidate evidence like any other and lands in `evidence.jsonl`:

```json
{"kind": "scope_decision", "step": "sourcing", "about": "employer:acme",
 "decision": "narrow", "accepted": true, "cycle": 3,
 "reason": "the candidate asked to focus here after reading two of their adverts",
 "proposed_alternatives": ["widen:country", "widen:seniority"]}
```

`accepted: false` records a **refusal**, which is evidence and is not permanent. The rule
open question 4 asks for:

> A refused proposal may be made again when the **trigger changed**, when **new evidence**
> about the candidate arrived, or in a **new session**. Never simply on the next cycle.

Re-asking the same question next cycle in different words is the failure this rule exists
to name, and it is checkable: a proposal whose `facet` and `direction` match a refusal in
the same session, with no intervening evidence row and the same trigger, is a violation.

**The gate counts recorded decisions, not employer share.** An earlier review note said a
cycle must never collapse onto one employer; a later one said collapsing onto one employer
is good when the conversation went there. Both are right, and the discriminator is entirely
whether the candidate chose it.

### 5.6 The empty market — a time, not a compromise

The outcome a tool is most tempted to dress up. Reported **only** when exhaustion survives
steering in **both** directions:

```python
def market_is_empty(cycles: list[Cycle]) -> bool:
    """Exhaustion that survived both a broadening and a narrowing.

    One stale cycle means look elsewhere. Repeated cycles returning the same adverts
    *after the scope was widened and narrowed* mean the market is the problem rather
    than the search — a diagnosis reached by having tried the remedy for the other one
    and watched it fail.
    """
```

What the tool then offers is **a time**:

> "It looks like it's not a good day to find jobs. Do you want to leave it for today and
> try again tomorrow or next week?"

What it must never offer is a relaxed hard constraint. That asks the candidate to want a
different job than the one they want, and it is precisely the move a tool reaches for when
it cannot admit an empty result — which is why
`exhausted_searches_reported_as_a_scope_change == 0` is its own gate rather than a note.

### 5.7 Standing scope, re-surfaced

Scope decisions do not expire on a clock. When the candidate returns they are shown what
the system holds about them, scope decisions included, and can correct any of it. Step 0
already opens with *"last time we were partway through your work history"*; this extends
that opening from **position** to **substance**.

This is not a courtesy. **Consent nobody can review is not consent**, so the re-surfacing
is what makes §5.5's gate mean anything a month later.

### 5.8 What is NOT changing

- **`integral.dedup`, `robots`, `lifecycle`** — repeat cycles re-fetch through the existing
  paths, at the existing rate limits. The ceiling on cycles is courtesy, and it stays.
- **The ranking, the extractor, the dimension model.** This spec changes what is *in* the
  list, never how a list is ordered.
- **Step 2's constraints.** A scope decision is not a constraint edit. Hard constraints stay
  where the candidate put them; scope is the search's aim within them.
- **Cross-candidate anything.** Every metric is within-subject. There is no central store
  and none is sought.

---

## 6. Risks

| # | What could go wrong | L | I | Mitigation | Rollback |
|---|---|---|---|---|---|
| IS-1 | **The tool anchors the candidate.** A question like *"shall we focus on US companies?"* plants the idea it pretends to ask about — and a conversational guide is the most anchoring surface this product has | H | H | `ScopeProposal.alternatives` is typed to require the opposite direction, so a one-way proposal cannot be constructed; `scope_proposals_offering_only_narrowing == 0` measures it over what was actually offered, not over intent | The proposal surface is behind the exhaustion trigger — disabling the trigger returns step 7 to a single pass with no conversation at all |
| IS-2 | **Exhaustion fires when the search was merely unlucky**, and the candidate is asked to re-steer a search that would have worked | M | M | The threshold is a named constant carrying its reasoning rather than a tuned number; the trigger is licensed by repeat share over the candidate's whole tree, which needs two cycles to fire at all | Raise `EXHAUSTION_REPEAT_SHARE`; it is one constant and its docstring says it expects revision |
| IS-3 | **Interrogation.** Option 3 sends the candidate back through questions they already answered because a search did not work — the experience that makes people close a tool | M | H | Option 3 is sequenced after Option 2 and gated on the exhaustion signal having been *observed* to be right, not merely built; its own gate counts unrequested re-entries | Option 3 is a separate task and a separate merge; not shipping it leaves Option 2 whole |
| IS-4 | **Consent becomes theatre** — the decision is recorded, the candidate never sees it again, and the search quietly narrows for a month | M | H | §5.7 re-surfaces standing scope on return, and the gate for it is that a decision the candidate cannot review does not count | Scope decisions are evidence rows; suppressing them returns sourcing to constraints-only |
| IS-5 | **Cycles multiply fetches** past what a source will tolerate | M | M | `robots` and the rate limits are unchanged and un-bypassed; exhaustion *reduces* fetching by stopping a search that repeats itself | Cap cycles per session; the cap is a constant like IS-2's |
| IS-6 | **The empty-market answer is used as a euphemism** — the tool says "try tomorrow" when it should say "we looked in the wrong place" | M | M | `market_is_empty` requires exhaustion to have survived steering in *both* directions, so it cannot be reached without having tried the other diagnosis first | The report is a leaf of the proposal path; removing it returns the tool to proposing a scope change, which is the current behaviour |
| IS-7 | **The graph edit lands without the machinery**, and step 7 declares inputs nobody reads | M | L | T60 is deliberately first and deliberately small, and every later task depends on it; a graph edge nobody traverses is documentation, which the spec says outright is not worth shipping alone | Revert two documents in one commit; `drift_violations` keeps them in step either way |
