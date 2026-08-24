# Preference-directed sourcing — Specification (annotated edition)

> Generated 2026-08-24. This is the document with a **note slot** after every section. Read it in any Markdown app. To annotate, replace the `_(your notes…)_` placeholder under any section. When done, send the file back — notes are acted on.

---

# Preference Directed Sourcing

## Preamble & scope

Feature spec, 2026-08-24. Issue #154. Sections 1–4 (`specify`); 5–6 are `design`'s to append.

This is a **feature spec**, kept beside the project spec rather than inside it:
`status/specification.md` §1–4 state the problem the *product* solves, and
overwriting them with one feature's problem statement would delete that argument.

> **✎ Notes** · `SPEC · intro`
> _(your notes here — replace this line)_

## §1 Problem statement

Sourcing decides **where to look** from the candidate's constraints — country, field,
reach — and then queries with skills keywords. Everything after that filters and ranks
what came back. Nothing in the system ever revises where it looked based on what the
candidate turned out to value.

The first blind sitting made the cost visible. Presented with twenty held-out adverts from
the corpus, the candidate placed **one** in "would apply", one in "maybe", and eighteen in
"not for me" — nine of those rejected for a technology they have never written. The
ranking did not misbehave; it ordered exactly the list it was handed, and the list was
mostly not this candidate's job. **This is a supply failure presenting as a ranking
result**, and no improvement to the dimension model, the extractor or the ranker can
reach it: all three operate downstream of the decision that produced the list.

The signal to fix it already exists and is discarded. An advert rejected for a reason
*orthogonal* to what made it attractive — right remote policy, wrong stack — is evidence
about its **employer**, not a dead end. Today that advert is scored, ranked last, and
forgotten.

> **✎ Notes** · `SPEC §1`
> _(your notes here — replace this line)_

### Success criteria (measurable)

| Metric | Threshold | Why this number |
|---|---|---|
| `directed_rejection_rate` | `< first_pass_rejection_rate` for the same candidate | The strategy must beat the baseline it supplements. A directed search returning more of what the candidate rejects is worse than not running it. |
| `directed_offers_without_an_attractor` | `== 0` | Every offer a directed search returns names the attractor that caused the search. An offer nobody can trace back to a stated preference is an unexplained recommendation. |
| `directed_offers_without_a_shown_reason` | `== 0` | The attractor is **shown**, not merely stored: *"good remote policy · pay above your floor · a stack you know"*. T19 already requires an explanation to cite the advert; this extends it to why the offer was *sought*. |
| `shown_reasons_omitting_what_is_missing` | `== 0` | The same card states what the offer **lacks** — *"no health cover · no half-day Fridays"*. A card that lists only the good is an advertisement, not an explanation, and the candidate cannot weigh what they are not shown. |
| `strategy_fires_without_attractors` | `== 0` | The fire rule must decline when nothing is worth steering toward — the bakery case below. Firing on an empty attractor set spends requests to reproduce the generic search. |
| `unverified_company_claims` | `== 0` | An employer proposed from model knowledge is never shown until a real page has been fetched and found to carry a matching opening. |
| `undisclosed_directed_sourcing` | `== 0` | Extends D-16's rule: the candidate is told *why* these offers are in front of them, as they are already told when a result came from web search rather than a board. |
| `robots_violations` | `== 0` | Existing gate (`integral.robots`). Directed search multiplies requests; it may not multiply violations. |

`first_pass_rejection_rate` is measured on the same candidate in the same cycle, so the
comparison is within-subject. Cross-candidate comparison is not available and is not
sought — there is no central store and there should not be one.

> **✎ Notes** · `SPEC › Success criteria (measurable)`
> _(your notes here — replace this line)_

## §2 Systems & Impact



> **✎ Notes** · `SPEC §2`
> _(your notes here — replace this line)_

### Dependency map

| System | Role | Needs change? |
|---|---|---|
| Step 7 `sourcing` | Where the strategy runs | **Yes** — a second, directed pass after the generic one |
| `integral.connectors` | Board contract: `site + locale + list + detail` | **No** — see below |
| `SEARCH_SOURCE` (`connectors.py:134`) | Reserved `"web_search"` source for offers no connector produced | **No** — reused as-is |
| `integral.weights` | Fitted part-worths; which dimensions the candidate values | Read only |
| `integral.calibration` | Signed notes (`liked` / `disliked`) from the blind sitting | Read only |
| Step 5 `reactions`, step 10 `feedback` | The live-session equivalents of signed notes | Read only |
| `integral.rank`, `integral.explain` | Per-dimension contributions — how an attractor is derived | Read only |
| `integral.dedup` | Second-pass offers must dedupe against the first pass | Validation only |
| `integral.robots`, `freshness`, `lifecycle` | Courtesy, staleness, offer states | Validation only |
| `Offer.company` | Employer identity, `str | None` | Validation only — nullable, so the company axis is unavailable on offers that lack it |

> **✎ Notes** · `SPEC › Dependency map`
> _(your notes here — replace this line)_

### Two facts that shape every option

**Connectors cannot be parameterised.** A `Connector` names a site, a locale, a `ListPage`
and an optional `DetailPage`. `Pagination.mode` (`query_param` / `path_segment`) describes
**how a listing continues past its first page** — not how to search it. There is no
query-axis mechanism to extend, so any option that says "search board X by company" is
proposing a change to the connector contract, and that is a larger piece of work than the
strategy itself.

**Web search is already a disclosed offer source.** `SEARCH_SOURCE = "web_search"` is
reserved, and a connector is *refused* if it tries to claim that name — so `Offer.source`
can never be ambiguous about whether a board was actually searched. D-16 (merged,
`undisclosed_connectorless_sourcing == 0`) established that step 7 already presents
web-search results and must say so. Directed search therefore has a home that exists,
is honest by construction, and needs no connector work.

> **✎ Notes** · `SPEC › Two facts that shape every option`
> _(your notes here — replace this line)_

### Impact assessment

| Dimension | Severity | Notes |
|---|---|---|
| Data | **Medium** | New offers through the existing `Offer` contract; no schema change. But everything this feature learns about the candidate — which attractors fired, which reasons they gave, which directed results they then rejected — is **written to the profile as evidence**, the same as every other step's output. A preference discovered by a search strategy and kept only inside that strategy is a preference the next step cannot use, and the whole premise of the product is one shared vocabulary across stages. |
| API | Low | No public contract changes. Step 7's outputs gain a provenance field. |
| Performance | **Medium** | A second pass multiplies requests per cycle. Rate limits and `robots` apply unchanged, so the cap is courtesy, not latency. |
| User | **High** — intended | The candidate sees a different list. That is the point, and it is also the risk: a bad strategy degrades the product's core output. |
| Operational | Low | No deployment coordination; this runs in the candidate's own session. |
| Risk if nothing changes | **High** | The observed result stands: a candidate is shown a list that is mostly not their job, and every downstream improvement polishes the ordering of the wrong set. |

> **✎ Notes** · `SPEC › Impact assessment`
> _(your notes here — replace this line)_

## §3 Options



> **✎ Notes** · `SPEC §3`
> _(your notes here — replace this line)_

### Option 1 — Employer re-query from offers already seen

Take the employers of offers that scored well on high-weight dimensions but were rejected
for an orthogonal reason, and look for their **other** openings. The candidate set is
entirely derived from adverts the candidate has already been shown and reacted to.

- **Scope**: step 7, a new `integral.sourcing_strategy`, reads `weights.json` and the
  signed notes; emits queries through the existing web-search path.
- **Effort**: Small.
- **Trade-offs**: Invents nothing — every employer is one the candidate saw. Cannot reach
  an employer that never appeared in a first pass, so it deepens rather than widens.
- **Compatibility**: Fully backwards compatible.
- **Dependencies**: Fitted weights; at least one completed reaction or feedback round.

> **✎ Notes** · `SPEC › Option 1 — Employer re-query from offers already seen`
> _(your notes here — replace this line)_

### Option 2 — Attribute-directed search

Derive search *attributes* from the high-weight dimensions and query on those instead of
on employers: if remote policy dominates, search remote-first job boards, remote-friendly
countries, company sizes and stages that correlate with the dimension.

- **Scope**: as Option 1, plus a mapping from dimension to searchable attribute, plus a
  per-source statement of which attributes it can express.
- **Effort**: Medium.
- **Trade-offs**: Widens the pool rather than deepening it, so it can reach employers the
  candidate has never seen — the actual complaint. But the dimension→attribute mapping is
  editorial: "remote policy correlates with company stage" is a claim, and a wrong one
  sends every subsequent search in a wrong direction. It also cannot be verified per
  candidate without more data than one person generates.
- **Compatibility**: Backwards compatible.
- **Dependencies**: Option 1's machinery.

> **✎ Notes** · `SPEC › Option 2 — Attribute-directed search`
> _(your notes here — replace this line)_

### Option 3 — Model-proposed employers, verified before display

Use the assistant's own knowledge of employers to propose candidates for a valued
dimension — "these companies are known for four-day weeks" — then **fetch and confirm**
before anything reaches the candidate.

- **Scope**: Option 1, plus a proposal step and a mandatory verification step.
- **Effort**: Medium.
- **Trade-offs**: The only option that can reach an employer neither the candidate nor any
  board surfaced, and the candidate reports this working in practice (PostHog, Canonical,
  via `ai-job-search`) — though **how that list was arrived at was never recorded**, which
  is most of what makes it hard. Against it: model knowledge is unverifiable, has a
  training cut-off, and fabricates confidently. A hallucinated employer with a plausible
  name is indistinguishable from a real one until fetched. Verification is therefore not a
  safeguard bolted on, it is the feature: `unverified_company_claims == 0` means nothing
  is shown that a fetch did not confirm.
- **Compatibility**: Backwards compatible.
- **Dependencies**: Option 1; `robots` compliance on employer career pages.

> **✎ Notes** · `SPEC › Option 3 — Model-proposed employers, verified before display`
> _(your notes here — replace this line)_

### Comparison

| | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Effort | Small | Medium | Medium |
| Reaches unseen employers | No | Yes | Yes |
| Can fabricate | No | No | **Yes, without verification** |
| Editorial judgement required | None | Dimension→attribute mapping | Which employers, from memory |
| Fires on the bakery case | No (correctly) | Possibly, wrongly | Possibly, wrongly |
| Needs connector changes | No | No | No |

> **✎ Notes** · `SPEC › Comparison`
> _(your notes here — replace this line)_

## §4 Recommendation

**Option 1 first, then Option 3 behind its verification gate. Option 2 last, or never.**
*Confirmed in review (2026-08-24): options 1 and 3, not 2.*

Option 1 is the whole idea in its cheapest honest form. Its candidate set is derived
entirely from what the candidate has already seen and judged, so it cannot invent an
employer, cannot import an editorial claim, and needs no new source of truth. It is also
the version that answers the bakery case *by construction* rather than by detection: if a
first pass over local bakery adverts turns up no employer scoring well on anything the
candidate values, the attractor set is empty and the strategy declines to fire. The tool
never has to know it is looking at bakeries — it has to notice it has nothing to chase,
and that is a measurement, not an inference.

Option 3 second, because it is the one that reaches genuinely new employers and the
candidate has seen it work. It ships only with `unverified_company_claims == 0` enforced,
and that gate must be built with the feature rather than after it.

Option 2 last. Its dimension→attribute mapping is a set of claims about the labour market
that this system has no way to verify from one candidate's data, and a wrong mapping is
invisible: it produces a plausible list that is systematically off, which is worse than
producing nothing.

> **✎ Notes** · `SPEC §4`
> _(your notes here — replace this line)_

### Immediate next action

Run `design` over this spec to produce sections 5–6 and the task split. The first task is
`integral.sourcing_strategy` with the attractor definition and the fire rule, gated on
`strategy_fires_without_attractors == 0` — the property that makes every later option safe.

> **✎ Notes** · `SPEC › Immediate next action`
> _(your notes here — replace this line)_

### Open questions

1. **Where do signed notes come from in a live run?** **Settled in review: the candidate
   is shown adverts and judges them as a normal step, and that judgement drives the next
   search.** The loop is the feature, not a preliminary to it. Step 5 (`reactions`) and
   step 10 (`feedback`) are where it happens; the open work is checking whether their
   evidence carries the *sign* that `liked` / `disliked` carries, and adding it if not.
   That check is a prerequisite task, not part of this one.
2. **What is an attractor, formally?** **Settled in review: the signal is symmetric.**
   A *good thing in a rejected advert* says where to search next; a *bad thing in an
   accepted advert* says what to stop returning, and is equally informative. So the unit
   is not "attractor" but a **signed observation**: `(dimension, sign, offer, employer)`,
   harvested from every judged advert regardless of whether the advert was accepted.
   Restricting it to rejections would discard half the signal — an offer the candidate
   took *despite* a hybrid arrangement states the price of hybrid better than any offer
   they refused. Remaining question is the threshold: how far above the candidate's rung,
   and how high in the weight ranking, before an observation is worth acting on.
3. **How many directed queries per cycle?** **Settled in review: a directed pass focuses
   the search, it never replaces it.** The output of a cycle is a blend — generic results
   plus emphasis on the employers and attributes the candidate's judgements favour — not a
   list drawn from one employer. Two properties follow and both need gates: each cycle
   must be *better than the previous one* by the same within-subject measure
   (`directed_rejection_rate`), and no single employer may dominate a cycle's results.
   The cap is therefore a share of the cycle, not a count of queries.
4. **Does a directed offer re-enter ranking normally, or is it flagged?** **Settled in
   review: flag it, even where the flag is not used.** The anchoring worry does not apply
   here — `blind_ranking_leaks` governs T20's *blind* sitting, where the whole point is
   that the candidate sees no system opinion. The live ranking is the opposite case: T19
   already requires every position to be explained from the advert, so saying *why this
   offer was sought* is continuous with what the product already promises, not a leak.
   The flag is carried whether or not a given surface renders it.

> **✎ Notes** · `SPEC › Open questions`
> _(your notes here — replace this line)_

