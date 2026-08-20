# What this tool is based on

Every technique, instrument and formula the tool uses is registered here, with its source
and its limits. Nothing scores a person, ranks a job, or weights a trade-off without an
entry in this file.

**Standing rule.** If code computes a number that reaches the candidate, this document names
the method and states the formula. "We take a weighted mean of the dimension scores, weights
from the candidate's pairwise trade-offs" is the minimum; a worked example is better. A
number nobody can explain is a number nobody should act on — least of all one about a
person's own personality, produced by a tool they are trusting with a career decision.

Effect sizes below are quoted with their source. Where estimates conflict, both are given.

---

## 1. What the tool is actually predicting — and what it is not

This is the most important section, because it decides which research applies.

Almost all the literature cited here comes from **personnel selection**: how employers pick
people, validated against *job performance*. This tool is the inverse — candidate-side,
choosing between employers. Two consequences:

**We borrow elicitation techniques, not validity coefficients.** When Sackett et al. (2022)
report structured interviews at r ≈ .42, that is validity *for predicting job performance*.
We are not predicting job performance. What transfers is the finding that structured
behavioural questioning produces richer, more comparable, harder-to-fake data than
unstructured conversation — a claim about the *instrument*, which does transfer. The
coefficient does not, and must never be quoted in this project as if it did.

**The literature that does transfer directly is person–environment fit.** Kristof-Brown et
al. (2005), meta-analysing person–organisation fit, found:

| Outcome | ρ | k |
|---|---|---|
| Organisational commitment | .51 | 44 |
| Job satisfaction | .44 | 65 |
| Intent to quit | .35 | 43 |

An earlier meta-analysis (Verquer et al., 2003, 21 studies) reports more conservative
figures — ρ = .28 satisfaction, .31 commitment, −.21 intent to quit. Take the range, not the
best number.

Either way the shape is the same, and it is the justification for this entire project: **fit
predicts satisfaction, commitment and staying — and predicts performance only weakly.** So
the tool optimises for the thing fit actually predicts. It is not trying to find the job you
would be best at. It is trying to find the job you would still want in two years. Those are
different objectives and conflating them is the failure mode this section exists to prevent.

---

## 2. Techniques used

### 2.1 Structured behavioural elicitation

**What.** The onboarding interview and the pre-draft gap-fill both use predetermined,
job-relevant questions asked in a consistent order, with standardised probing and a
consistent extraction rubric.

**Why.** Validity increases monotonically with structure: each increment — fixed questions,
consistent order, restricted probing, a rating rubric — measurably improves predictive
accuracy and rater agreement. Past-behaviour questions ("describe a time when…") rest on the
premise that past behaviour predicts future behaviour, and outperform hypothetical framings.

**How we use it.** Questions are generated from the dimension model so every question maps to
at least one dimension ID (gate: `question_dimension_coverage == 1.0`). Free-text answers are
extracted against those same IDs. Standardised probing becomes: the follow-up is selected by
which dimension remains most uncertain, not by what seems interesting.

**Limits.** Structure was developed for comparability *across candidates*. We have one
candidate at a time, so the comparability benefit largely does not apply; we keep structure
for the other reason — it produces consistently extractable answers.

**Sources.** [Sackett et al. 2022, *J. Applied Psychology*](https://pubmed.ncbi.nlm.nih.gov/34968080/) ·
[structure–validity relationship](https://www.cambridge.org/core/journals/industrial-and-organizational-psychology/article/structured-interviews-moving-beyond-mean-validity/7CB1F7C86CB0D15328B3F07AD5F964E2) ·
[question-type comparison](https://www.sciencedirect.com/science/article/abs/pii/S0148296319301985) ·
[US OPM structured interview guidance](https://www.opm.gov/policy-data-oversight/assessment-and-selection/other-assessment-methods/structured-interviews/)

### 2.2 Story-bank composition — both kinds present, reported not floored

**What.** Once a story bank holds four or more episodes it should contain both
successes and failures. `story_failure_fraction` (failure episodes ÷ all
episodes) is computed and shown alongside the bank so a monotone one is
visible — it is reported, never gated on. A v1 draft floored it instead, at
`story_failure_fraction >= 0.33`; that floor is **superseded** (see Limits).

**Why.** Success stories are rehearsed and sanitised; they are the ones a candidate has
already told in interviews. Failure episodes carry more information per word about working
style, values and self-awareness, and they are the material a cover letter needs to be
specific rather than fluent-generic. That concern is real, which is why the fraction is
still worth reporting — a bank of nothing but rehearsed successes reveals less, and
something should say so.

**Limits.** The `>= 0.33` floor was a design judgement extrapolated from the
behavioural-interview premise, never a directly evidenced threshold — and it is now
superseded: `status/spec-v2-steps.md` step 3's revised History protocol takes a failure
episode when the candidate offers one "rather than digging for it," which a floor cannot
coexist with — an implementation would have to break the protocol or miss the gate. D-3
reconciles this entry and `status/specification.md`'s v1 success criteria with that
decision. Flagged in §5.

### 2.3 Discrete choice / conjoint preference elicitation

**What.** Preference weights come from forced choices between whole alternatives, not from
asking "how important is salary, 1–10."

**Why.** Discrete choice experiments recover *part-worth utilities* per attribute level, from
which attribute importance and willingness-to-pay follow. Because one attribute is money, every
other attribute can be expressed in salary-equivalent units. Published examples: workers forgo
on average €170/month to work at an innovation-focused company and €220/month for a CSR-focused
one. Attribute priorities differ systematically between people — one study found women
prioritising scheduling flexibility and employer reputation, men prioritising earnings and
permanent contracts — which is the point: the weights are per-candidate, not universal.

**How we use it.** Salary-equivalence is what makes trade-offs explainable. "This role pays
€200/month less but is worth €450/month more on your dimensions" is a sentence a person can
argue with. A raw composite score is not.

**Limits.** Stated preference, not revealed — people choose differently in hypotheticals than
in life. Mitigated by drawing choice sets from *real ads* (§2.4) rather than synthetic
attribute bundles. Market attributes also co-vary (salary with on-site, seniority with
autonomy), so some dimensions cannot be separated from real ads alone and may still need
synthetic pairs.

**Sources.** [Preferences for work arrangements: a DCE, PLOS One](https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0254483) ·
[Mission, prosocial attitudes and job preferences](https://www.sciencedirect.com/science/article/pii/S0927537121001226) ·
[Designing job ads to stimulate the decision to apply](https://www.tandfonline.com/doi/full/10.1080/09585192.2021.1891112)

### 2.4 Reaction elicitation on real ad text

**What.** Present real ads and ad excerpts — perks blocks, requirement blocks, how an
employer phrases an ask — and capture free-text reaction, comparison and sorting.

**Why.** People introspect poorly in the abstract and react well to concrete stimuli. It also
does two jobs the abstract questionnaire cannot: reactions arrive in the *wild vocabulary of
real ads*, surfacing dimensions the model is missing, and they supply preference data on day
one, before any application outcome exists.

**Limits.** Reactions are to *ad text*, which is marketing. A warm reaction to a well-written
ad is evidence about the writing as much as the workplace. Enrichment from outside the ad
(§2.6) is the counterweight.

**Provenance.** Proposed by the repository owner in spec review, 2026-08-15
(`status/reviews/spec-notes-2026-08-15.md`).

### 2.5 The ranked output as an automated realistic job preview

**What.** Ranking surfaces the unflattering dimensions of a job alongside the attractive ones.

**Why.** Realistic Job Previews — telling candidates the bad parts before they join — are one
of the better-evidenced interventions in the field. Premack and Wanous (1985), meta-analysing
21 studies, found a mean **36% reduction in voluntary turnover**; Phillips (1998), across 40
studies, found reduced turnover and reduced attrition during recruitment. The two mechanisms
identified are **self-selection** and **adjustment of expectations** — and self-selection is
precisely what a candidate-side ranking tool does.

This is the strongest theoretical grounding the project has: the literature says that showing
people what a job is really like makes them leave less. That is the product.

**Limits.** RJP research studies *employer-provided* previews of a job the candidate is
already close to taking. We are inferring the preview from public text, at a distance, before
contact. The mechanism should transfer; the effect size should not be assumed to.

**Sources.** [Premack & Wanous 1985 / Phillips 1998 summary](https://www.qic-wd.org/umbrella-summary/realistic-job-previews) ·
[Phillips 1998 meta-analysis, *AMJ*](https://journals.aom.org/doi/abs/10.5465/256964?journalCode=amj) ·
[mechanisms linking RJPs with turnover](https://stevenmbrownportfolio.weebly.com/uploads/1/7/4/6/17469871/earnest_et_al._2011_rjp.pdf)

### 2.6 Ad wording as signal

**What.** Register, length, jargon density, whether salary is stated, whether the employer
describes the team or only the requirements, and explicit inclusivity signals ("if you don't
match everything, apply anyway") are extracted as features in their own right.

**Why.** There is direct evidence that ad wording changes who applies. Gaucher, Friesen and
Kay (2011) showed that masculine-coded wording ("competitive", "dominant", "leader") made
roles less appealing to women and lowered their sense of belonging, with no comparable effect
on men; the finding has since been replicated and extended in a start-up context (Seong,
2024). If wording measurably changes applicant behaviour, wording carries information about
the workplace and is legitimate to extract.

**Limits.** The evidence is that wording affects *applicant perception*. It does **not**
establish that masculine-coded ads describe worse or more male-dominated workplaces. Treat
wording features as weak priors requiring corroboration, never as conclusions. This is the
part of the system most at risk of drifting into astrology, which is why every wording
feature must be calibrated against the labelled corpus before it is allowed to affect a rank.

**Sources.** [Gaucher, Friesen & Kay 2011 (PDF)](https://ideas.wharton.upenn.edu/wp-content/uploads/2018/07/Gaucher-Friesen-Kay-2011.pdf) ·
[Seong 2024 replication, *Strategic Entrepreneurship Journal*](https://sms.onlinelibrary.wiley.com/doi/10.1002/sej.1489)

### 2.7 CV and cover letter targeting

**What.** Documents are generated against the extracted requirements of one posting, from
approved story-bank episodes.

**Why.** As of 2026 the screening stack is two layers: the classic parser and keyword match
still runs first, and an LLM layer increasingly summarises and ranks whatever survives it.
Consequences for drafting: exact-term matching and clean, parseable formatting still matter
for layer one, while layer two rewards material that supports *why* someone fits — which is
what episodes provide and a keyword list does not. Modern NLP handles synonyms and
transferable skills better than older parsers, so synonym-stuffing is both less necessary and
more detectable.

**Limits.** This is the fastest-moving area in the document and the one most likely to be
stale. Vendor and SEO sources dominate the search results and have an obvious interest in
overstating both the threat and their remedy. **Re-verify before Phase 7 and treat the
current entry as provisional.** The honesty rule stands regardless of screening mechanics: a
keyword the profile does not support is a gap, never something to insert.

**Sources.** [AI resume screening 2026](https://atsverification.com/blog/ai-resume-screening-2026/) ·
[How AI screens resumes in 2026](https://happypeopleai.com/blog/how-ai-screens-your-resume-in-2026-and-how-to-beat-ats-filters)
— both commercial; low confidence, flagged in §5.

### 2.8 Cross-source near-duplicate detection

**What.** The same advert reposted across sources — reworded, retitled, or with a source's own
summary or footer stitched on — is found by shingled Jaccard similarity over normalised ad
text, not by hashing (T13).

**Why.** Process spec §7.4 fixes `text_sha256` as a hash over normalised text, which "catches
re-collection of the same listing and nothing else": two portals carrying the same role rarely
carry byte-identical text, so cross-posted duplicates need a *similarity* judgement, not an
equality check. Word-shingle Jaccard (the technique behind Broder's near-duplicate web-page
detection) was chosen over `difflib.SequenceMatcher` because shingle-set overlap is insensitive
to *where* in the text an edit happened — a retitled opening line or an appended footer only
invalidates the shingles that cross that boundary — while `SequenceMatcher`'s
longest-common-subsequence approach is sensitive to exactly that kind of local rearrangement,
and quadratic in text length besides. Standard library only: no new dependency.

**How we use it.** Text is lowercased and word-tokenised into a comparison key that is never
written back to the stored offer (`Offer.text` stays byte-for-byte verbatim, per T11 — T15's
extraction evidence spans are offsets into it). The key is split into overlapping 8-word
shingles and compared by `|intersection| / |union|`. Shingles common to more than half of a
reference population are excluded from every pair's score before it is computed — same-source
template text (a cookie notice, an equal-opportunity statement) recurs across most of an
arbitrary batch, while genuine duplicate content is specific to one crosspost cluster, so a
bare-majority frequency threshold separates the two without needing a template denylist. See
§4.6 for the formula and the threshold's calibration.

**Two passes, not one — the majority-cluster fix.** That reference population is *cluster
representatives*, not raw offers, and it took a review finding to establish why raw offers is
wrong: a frequency threshold cannot, on its own, distinguish shared template text from shared
*duplicate* content, because both recur across a batch by construction. Counting frequency over
raw offers means a popular role's own crossposts inflate their own content's frequency exactly
the way boilerplate does — three or more copies of one ad in a batch of five puts their shared
genuine body over the 50% line, and the filter erases the very content it exists to match on. A
popular role is *more* likely to dominate a small batch, not less, so this was the exact case
the feature exists for, not an edge case, and the gate's precision-only metric could not see it
(recall is not measured — see below). The fix runs the comparison in two passes: pass one scores
every pair on raw, unfiltered shingles against a stricter cutoff
(`integral.dedup._RAW_CLUSTER_THRESHOLD`, calibrated so shared-template overlap alone never
crosses it) purely to find which offers are copies of the same ad, and collapses each such
cluster to one representative (the union of its members' shingle sets). Pass two counts
boilerplate frequency over those representatives — so three copies of one ad contribute one
entry to the corpus, the same as a genuinely unique ad — and re-scores every pair with that
filter. See `integral.dedup._cluster_representatives` and
`tests/test_dedup.py::test_majority_duplicate_cluster_is_not_erased_as_boilerplate`.

**Limits.** The 0.25 similarity threshold and the 8-word shingle width are calibrated against a
seven-offer, twenty-one-pair seeded fixture (`integral.dedup._fixture_batch`), not a broad
corpus — flagged in §5. Boilerplate filtering needs at least three items in its reference
population to define "common" against; a bare pair falls back to unfiltered similarity, so a
two-offer comparison sharing a long boilerplate block is not protected by this mechanism
(`integral.dedup.similarity` vs. `integral.dedup.find_duplicates`, whose docstrings say so).
The gate measures precision, never recall — see the module docstring's asymmetry argument,
echoed in §4.4's `dedup_precision` row: a false merge silently drops a role from the candidate's
list with nothing to tell them it happened, while a missed duplicate is only noise. Because a
missed-duplicate defect (the majority-cluster case above) is structurally invisible to a
precision-only gate, `integral.dedup.probe_dedup` also runs a dedicated recall probe over a
second, majority-cluster fixture (`integral.dedup._majority_cluster_fixture`, at least three
near-identical copies) and records `majority_cluster_recall` / `majority_cluster_missed`
alongside `dedup_precision` in the same evidence file — a measurement, not a prose note, so the
defect coming back would be caught. `dedup_precision` remains the sole declared gate; the recall
probe does not change what "pass" means.

**Sources.** Broder, A. (1997), *On the resemblance and containment of documents* — the
w-shingling technique for near-duplicate detection this module's shingle width follows.

---

## 3. Techniques deliberately NOT used

**Type indicators (MBTI, DISC, and similar four-letter systems).** Excluded.

The theory predicts bimodal score distributions — people clustering at the ends of each
dichotomy — and they do not appear, even after the instrument was rescored with item response
theory to discourage midpoints. Test-retest evidence is contested: the publisher reports
coefficients of .81–.86 over 6–15 weeks, while independent critics report that between 39%
and 76% of respondents receive a *different type* on retest within five weeks. And the
instrument does not consistently predict job performance, career success or satisfaction —
the things we care about.

In fairness, it is not measuring nothing: MBTI Extraversion correlates about .74 with Big
Five Extraversion. It measures real variation, imprecisely, then discards most of it by
forcing a cut point.

**We go further and mostly avoid trait inference altogether**, including well-validated
instruments. The construct we need — "do you want an office with parties and open-plan
desks?" — is directly askable, and the direct answer beats anything inferred from a trait
score via a mapping we would have to invent. Traits earn their place only where they predict
something a direct question cannot reach, chiefly where a candidate's stated preference and
their own history disagree.

**Sources.** [Stein & Swan, evaluating MBTI theory (PDF)](https://swanpsych.com/publications/SteinSwanMBTITheory_2019.pdf) ·
[publisher's reliability and validity page](https://www.myersbriggs.org/research-and-library/validity-reliability/)

**Autonomous outward action.** No code path submits an application, sends an email or
contacts an employer without per-item human approval. Not a research finding — a design
boundary. Likewise the tool stays candidate-side; the same machinery pointed at candidates on
an employer's behalf is regulated activity under the EU AI Act's employment provisions.

---

## 4. Formula register

Every computed number that reaches the candidate appears here.

### 4.1 Dimension score — weighted mean

A dimension's score for an offer is the **weighted arithmetic mean** of its evidence items,
weighted by extraction confidence:

```
score(d) = Σ(confidence_i × value_i) / Σ(confidence_i)
```

Evidence with confidence below the floor is dropped, not down-weighted, so a pile of weak
signals cannot manufacture a strong score. If no evidence survives, the dimension is
**unknown** — distinct from neutral, and displayed as such. "We don't know" and "it's average"
are different claims and must never be collapsed.

### 4.2 Preference weights — part-worth utilities

Per-candidate weights are estimated from forced choices (§2.3). Each dimension level gets a
part-worth utility; the weight of a dimension is the spread of its part-worths across levels.
Dividing by the salary attribute's part-worth converts any dimension to **salary-equivalent
units**, which is what explanations quote.

### 4.3 Offer comparison — Pareto dominance, then salary-equivalent total

Offer A **dominates** B when A is at least as good on every dimension and strictly better on
at least one. Dominated offers are collapsed. The remaining **non-dominated set** (the Pareto
frontier) is what gets shown, because within it there is no objectively correct order — only
trade-offs, which are the candidate's to make.

Ordering *within* the frontier, and the named facet lists, use the salary-equivalent total:

```
total(offer) = salary + Σ_d weight(d) × score(d)
```

This single number is deliberately never shown alone. It orders a list; the explanation
carries the reasoning.

### 4.4 Gate metrics

| Metric | Formula | Used for |
|---|---|---|
| `extraction_macro_f1` | unweighted mean of per-dimension F1 = 2PR/(P+R) | Extraction gate. Macro, not micro, so common dimensions cannot mask rare ones |
| `rank_spearman` | Spearman ρ between system order and the candidate's blind manual order | Ranking gate |
| `dedup_precision` | TP / (TP + FP) on seeded cross-posted duplicates | Dedup gate |
| `ontology_hit_rate` | extracted concepts mapping to a known dimension ÷ all extracted concepts | Extraction coverage **and** staleness signal |
| `story_failure_fraction` | failure episodes ÷ all episodes | Story-bank composition |
| `elicitation_eval_overlap` | \|elicitation ads ∩ evaluation ads\| | Must be 0; see below |

`elicitation_eval_overlap` is not a quality metric but a **validity guard**. If the ads used
to elicit preferences are also used to measure `rank_spearman`, the ranking gate measures
memorisation, passes, and tells us nothing. It must be exactly zero.

### 4.5 Net-from-gross pay estimation

Comparing a Spanish offer and a German one on gross salary is exactly the comparison that
misleads — a candidate needs a rough **monthly net**, in their own currency, for every offer
(T33). Given a country's (or region's) rule set — progressive income-tax bands, a flat
capped social security rate, and an "obvious" flat personal allowance — the estimate is:

```
taxable        = max(gross_annual - allowance, 0)
income_tax     = Σ over ordered bands of (band's share of taxable) × band.rate
social_security = min(gross_annual, cap) × social_security_rate
net_annual     = gross_annual - income_tax - social_security
net_monthly    = net_annual / 12
```

`income_tax` is the ordinary **marginal-band** calculation — each band taxes only the slice
of `taxable` that falls inside it, not the whole amount at that band's rate. `social_security`
is a single flat rate against gross, capped where the rule set says a country caps
contributions. `net_monthly` always assumes 12 equal payments — countries that pay salary in
13 or 14 instalments (Spain routinely does) are simplified to that convention, and each
committed rule set's `notes` says so explicitly.

**Two rule sources, and the honesty rule that governs them.** Rules are either **committed**
(`taxes/<COUNTRY>.json`, checked by a person against a real tax code, `source: verified`,
carrying `checked_on`) or **generated** when a country is absent (worked out on the spot,
written to disk, and used — `source: generated`, carrying `generated_on` and `generated_by`
instead of `checked_on`). **No rule set shipped in this repository is `verified` yet** —
`taxes/ES.json` and `taxes/DE.json` were assembled from published secondary summaries, not
checked by a person against the tax code, so both are marked `generated` and every figure
drawn from them reads as approximate. `verified` is a claim about a person having done that
work; `pay.probe_pay` checks the shipped files so nothing can wear the label without it.
A search must never stop for want of a country's tax rules, so
generation always succeeds; but every figure it produces is displayed as **approximate and
generated**, never like a checked rule — `pay.TaxRules._marking_matches_source` makes the two
sources mutually exclusive by construction, and `pay.NetEstimate.label()` carries the mark
through to the number itself. A committed rule set also **goes stale**: rates change every
year, and one nobody has checked in over `pay.STALE_AFTER_DAYS` days is flagged rather than
shown next to a freshly-checked one with no visible difference. No model is called to produce
a generated rule set here — `pay.default_generator` is a loudly-labelled, stdlib-only
placeholder behind the same `pay.RuleGenerator` seam a real generator would use.

**Out of scope, and said so on every estimate** (`pay.OUT_OF_SCOPE_NOTE`): dependants, joint
assessment, regional variation below the level a rule set models, and pension arrangements.
None of these are modelled; the estimate states that it ignores them rather than implying a
precision the calculation does not have.

### 4.6 Near-duplicate detection — shingled Jaccard similarity

Two ads' normalised texts are each split into overlapping 8-word shingles (§2.8); similarity is
plain Jaccard over the two shingle sets, after a two-pass boilerplate filter removes shingles
common to more than half a reference population of cluster representatives (§2.8's
"majority-cluster fix" — not the raw batch; see below for why):

```
shingles(text)             = { word[i:i+8] for i in range(len(words) - 7) }   # 8-word windows

# pass 1 — cluster offers into copies of the same ad, on RAW (unfiltered) shingles
cluster_threshold          = 0.30                                    # integral.dedup._RAW_CLUSTER_THRESHOLD
same_ad(a, b)               = jaccard(shingles(a), shingles(b)) > cluster_threshold
clusters(batch)             = connected components of `batch` under `same_ad` (union-find)
representative(cluster)     = ⋃ { shingles(o) : o in cluster }       # one entry per cluster, not per offer

# pass 2 — boilerplate frequency over representatives, then the final score
boilerplate(batch)          = { s : |{ r in representatives(batch) : s in r }| > 0.5 × |representatives(batch)| }
similarity(a, b, batch)     = |shingles(a)\boilerplate − shingles(b)\boilerplate|
                               ────────────────────────────────────────────────
                               |shingles(a)\boilerplate ∪ shingles(b)\boilerplate|
```

Two offers are reported as the same ad when `similarity > 0.25`
(`integral.dedup.SIMILARITY_THRESHOLD`). That value is not assumed; it is the point roughly
midway between the lowest score any seeded duplicate pair reached (0.489, after boilerplate
filtering) and the highest score any seeded non-duplicate pair reached (0.0) in the calibration
fixture referenced in §2.8 — comfortable margin on both sides of the observed gap, rather than a
value fit to the exact boundary. Fixing the majority-cluster defect (§2.8) did not move this
threshold or either observed score: `_fixture_batch`'s own largest crosspost cluster is 3 of 7
offers (43%), under the 50% boilerplate line even under the single-pass filter this replaced, so
the fix changes nothing on that fixture — it is recorded here as a fact that was checked, not
assumed. `cluster_threshold = 0.30` (pass 1) is calibrated separately, deliberately stricter than
`0.25`: pass 1 has no boilerplate filter yet to protect it, and two unrelated ads sharing only a
long template footer can score up to 0.268 on raw Jaccard alone in the calibration fixture, so
0.30 sits above every such footer-only confounder and below the weakest genuine crosspost's raw
score (0.331). Boilerplate filtering itself needs at least three items in its reference
population to define "common" against (with two, any shingle either shares is, trivially, in
"all of them"); below that population no filtering is applied and the two shingle sets are
compared as they stand.

---

## 5. Evidence gaps

Recorded so they are not mistaken for settled.

1. **ATS and LLM screening behaviour (§2.7)** — sourced from commercial vendor and SEO pages,
   which have an interest in the answer. No peer-reviewed source located. Fastest-moving area
   here. **Re-verify before Phase 7.**
2. **The 0.33 failure-episode floor (§2.2)** — was a design judgement, not an evidenced
   threshold. Now superseded (D-3): `story_failure_fraction` is reported, not floored. The
   open question this leaves is which episodes drafts actually use, not what the floor
   should have been.
3. **RJP effect size at a distance (§2.5)** — the mechanism should transfer from
   employer-provided previews to inferred ones; the magnitude should not be assumed to.
4. **Wording features (§2.6)** — evidence covers effects on applicant perception, not on what
   workplaces are like. Every wording feature needs corpus calibration before it moves a rank.
5. **Fit effect sizes (§1)** — Kristof-Brown et al. (2005) and Verquer et al. (2003) differ
   substantially. Neither has been read in full; both are quoted from meta-analytic summaries.
6. **Spanish, Catalan and EU-market specifics** — every source here is anglophone. Salary
   disclosure norms, ad conventions and screening practice differ. Not yet researched.
7. **Shipped tax rule sets (§4.5)** — `taxes/ES.json` and `taxes/DE.json` are stepped,
   flat-allowance approximations of each country's real progressive tax code, assembled from
   public secondary sources rather than the primary tax authority text, and dated 2026-08-18.
   Neither models regions, multi-payment conventions beyond the 12-payment default, or any
   deduction beyond a single flat allowance. **Nobody has checked either against the tax code,
   so both are marked `generated`** and every figure from them is shown as approximate; that is
   the honest state, not a temporary one. Promoting either to `verified` is a task for a person
   with the tax code in front of them — see each file's `notes` for what was simplified and why.
8. **Dedup similarity threshold (§2.8, §4.6)** — 0.25, the 8-word shingle width, and the 0.5
   boilerplate-frequency cutoff are all calibrated against one seven-offer seeded fixture, not
   real cross-posted ad pairs collected at scale. They separate that fixture's cases with
   margin, but the margin's size on a real, larger corpus is unmeasured. **Re-calibrate once
   T12's live connector supplies real cross-posted pairs**, and widen the fixture itself.
9. **The Catalan corpus slice is IT-at-large, not remote-programming (D-1)** — natively-Catalan
   remote-programming job ads are too thin a market to fill a 15-ad slice: a full keyword sweep
   of Feina Activa, the only board publishing ads written in Catalan rather than translated into
   it, returns under ten. `corpus/raw/ads.jsonl`'s 15 Catalan ads are Catalan IT ads at large
   (developer, sysadmin, data, cybersecurity, TIC consulting) instead, with the remote dimension
   **mixed in rather than filtered for** — only 2 of the 15 actually offer telework as part of
   the role; ES and EN stay remote-filtered at source. Labelling (T5) must extract
   `remote_arrangement` per Catalan ad from its own text, never assume the slice is remote
   because ES/EN are. See `corpus/raw/README.md` ("Known divergence") and
   `integral.corpus_scope`, which checks `status/plan.md`, the README and
   `tests/test_corpus_raw.py::TARGET_MIX` against each other mechanically.

---

## 6. Changelog

| Date | Change |
|---|---|
| 2026-08-18 | §5 added: the Catalan corpus slice is documented as IT-at-large rather than remote-programming (D-1); `status/plan.md`'s T4b row and `corpus/raw/README.md` restated to match, and `integral.corpus_scope` checks the two against `tests/test_corpus_raw.py::TARGET_MIX` mechanically. |
| 2026-08-18 | §2.8/§4.6 updated: near-duplicate detection reworked to two passes — boilerplate frequency is now counted over crosspost-cluster representatives, not raw offers, fixing a majority-duplicate-cluster blind spot a precision-only gate could not see (T13 review finding). `SIMILARITY_THRESHOLD` unchanged; new `_RAW_CLUSTER_THRESHOLD = 0.30` calibrated for pass 1. |
| 2026-08-18 | §2.8/§4.6 added: cross-source near-duplicate detection by shingled Jaccard similarity, and its threshold's calibration (T13). |
| 2026-08-18 | §4.5 added: net-from-gross pay estimation, and its committed/generated rule-source split (T33). |
| 2026-08-15 | Created. Sections 1–5 from the pre-`ONTOLOGY` research pass. |
