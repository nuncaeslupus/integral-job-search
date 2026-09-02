# Labelled corpus (T4 harness, T5 labels)

`ads.jsonl` — one labelled ad per line, sorted by id. Seeded from
`corpus/raw/ads.jsonl` by the harness; the raw file stays untouched.

| field | meaning |
|-------|---------|
| `id`, `language`, `text`, `source_url`, … | carried over verbatim from the raw ad |
| `split` | `elicitation` or `evaluation` — see below |
| `labels` | dimension values, each with the ad text that evidences it |

A label is `{dimension, value, spans, negated, labeller, round}`. `spans` are
half-open **character** ranges into `text` (`text[start:end]`), not byte
offsets: the corpus is full of accented Catalan and Spanish and of emoji in the
Manfred ads, and byte offsets would shift on every accent.

`negated` records that the evidence *denies* the dimension — "sense guàrdies",
"no on-call" — rather than the dimension being absent. That distinction is what
T16 measures as `extraction_negation_recall`, and a bare score cannot carry it.

**The store holds 39 human labels, on 4 ads** (50 spans; 22 confirmed, 10
written outright, 7 edited). It will not hold many more soon: the labelling
campaign was retired on 2026-08-19 in favour of the model reading each advert
and finding the dimensions on its own (T5, `lo-d2b2`). What is here accrued
from use and will keep accruing that way. Read **Why so few labels, and what
still needs them** at the end of this file before computing anything over
`labels`.

## Catalan ads are not all remote (D-1)

`corpus/raw/README.md`'s "Known divergence" section explains why: the 15
Catalan ads are Catalan IT ads at large, not filtered for remote work the way
the Spanish and English slices are — of the 15, only 2 actually offer
telework as part of the role; a further few mention `remot` only as remote IT
*support delivered to end users*, a duty rather than the role's own modality,
and at least one is explicitly on-site. When labelling `remote_arrangement`,
extract it from each ad's own text. Do not default a Catalan ad to remote
because the corpus overall skews that way, and do not default it to on-site
either — most Catalan ads say nothing about location at all.

## Splits

Each language is halved, evaluation taking the ceiling of an odd slice:
30/30 ES, 12/13 EN, 7/8 CA. (`round()` would hand the spare English ad to
elicitation under banker's rounding, and evaluation is the half carrying
`extraction_macro_f1` and `rank_spearman`.) The elicitation half feeds
reaction elicitation (T9); the evaluation half feeds `extraction_macro_f1` (T15)
and `rank_spearman` (T20). `elicitation_eval_overlap == 0` is the gate that
keeps the ranking measurement from scoring memorisation.

Assignment is stratified per language, not thresholded per ad. A per-ad hash
threshold is binomial, and the first cut of this corpus put **1 of 15** Catalan
ads in evaluation — which would have measured Catalan extraction on a single ad
while the aggregate 49/51 looked healthy.

Assignment is also **stable**: an ad already in the store keeps its split, and
only new ads are placed. An ad that migrated to the evaluation half after being
used to elicit preferences would put memorised ads into the ranking gate.

## Labelling

```bash
uv run python -m integral.harness init                    # seed / re-seed, keeping labels
uv run python -m integral.harness next --language ca      # next ad awaiting labels
uv run python -m integral.harness set <ad-id> <dimension> <value> --quote "<verbatim text>"
uv run python -m integral.harness status                  # counts, splits, agreement
uv run python -m integral.harness agreement               # self-agreement report
uv run python -m integral.harness gate                    # write status/evidence/T4.json
uv run python -m integral.harness labels                  # write status/evidence/T5.json
uv run python -m integral.harness                         # both, as `make evidence` runs it
```

`set` locates the span by searching for a quote copied out of the ad, and
refuses a quote that is absent or ambiguous. Offsets typed by hand are how a
corpus acquires spans that point at the wrong words while still validating.

## Fast path — the labelling page

Labelling dimension-first meant 22 cards beside each ad: 2,200 decisions offered
across the corpus to record the five or six per ad that are really there, and no
way to notice a dimension without already holding all 22 in mind.

`tools/labelling_page.py` inverts it. The ad arrives already marked — each span
highlighted, with a chip naming its dimension and proposed rung:

```bash
uv run python tools/labelling_page.py           # writes corpus/labelled/label.html
open corpus/labelled/label.html                 # file://, no server, no network
```

Read the ad once and react to what is marked:

| key | does |
|-----|------|
| `Enter` | confirm the focused mark |
| `Backspace` | delete it |
| `c` | change its dimension or rung |
| `j` / `k` | move between marks |
| `n` | next unresolved ad |
| `[` / `]` | previous / next ad |

Selecting text the marks missed opens a picker grouped into five titled
sections, with type-to-filter. Choosing a dimension offers its **named rungs**
with a line on what each looks like in an ad — no number is ever typed, and
every rung the page offers is one `import` accepts.

Export, then apply the whole batch at once:

```bash
uv run python -m integral.harness import t5-labels.json
```

### A proposal is not a label

A dashed mark is a *proposal* and is never exported. Only what you confirm or
change reaches the corpus, and `Label.source` records which:

| source | means |
|--------|-------|
| `confirmed` | you read a proposal and accepted it unchanged |
| `edited` | you changed its dimension, rung or span |
| `human` | you created it yourself; no proposal was involved |

Provenance is *derived* by comparing against the original proposal, not stored
as a flag the page could set wrongly.

### Where the marks come from, and why not from the cues

They come from `suggestions.json`, **not** from `Dimension.extraction.cues`.
`extraction_macro_f1` (T15) is measured against these labels, so confirming the
extractor's own regex output would make the gate score the extractor against
itself and pass regardless of merit — D-2. The page carries no cue data at all,
so this is closed by construction rather than by rule.

`integral.suggestions` measures what that rule cannot prove:

```bash
uv run python -m integral.suggestions        # writes status/evidence/T5-suggestions.json
```

`suggestion_cue_agreement` is the fraction of marks the cues would have produced
anyway; `cue_unreachable` is its complement, and is the quantity that matters —
those are the marks carrying phrasing no regex reaches.

### The control ads

About 15% of ads (stratified by language) ship with **no marks at all**, and the
page says so when you reach one. Label them as you read them. Without a blind
baseline, "the labeller agreed with 92% of proposals" cannot be told apart from
rubber-stamping. Do not skip them — they are what the rest of the run is
measured against.

### Coining a dimension mid-read

`+ new dimension` in the picker, when an ad says something none of the 22 can
hold. It appears in the export as a *proposal* together with the ad you coined
it at — every earlier ad was read without it existing, so those get swept for it
rather than assumed clean. `harness import` reports proposals and never writes
`dimensions/<id>.yaml`: changing the model's spine belongs in a reviewed diff,
not in an import that is also writing to the corpus.

### Quotes, not offsets

A mark crosses into the browser as a quote, and the page resolves it there. A
Python offset counts **code points**; a JavaScript offset counts **UTF-16 code
units**. These ads open with 📢 and contain 🫵🏾 (two surrogate pairs), so an
offset computed in Python and used in JS slides every later span leftwards —
observed citing "so. Manejarás \*\*cientos de miles de eventos por segun"
where the evidence was "Manejarás \*\*cientos de miles de eventos por
segundo\*\*". Plausible in the panel, wrong in the corpus. It is the same
failure this README rules out for byte offsets, one encoding layer up.

The page also widens an ambiguous quote itself on export, rather than asking you
to extend it until unique — the text determines that, not you.

## Why so few labels, and what still needs them

The corpus was pre-marked so that labelling would be confirm-and-move rather
than blind — 828 marks over 84 ads, in `suggestions.json`. After working
through part of it the owner decided the read was good enough to stop:

> *"The LLM must read the text and find those dimensions alone."*

That is a reasonable call about the product, and it has one consequence worth
stating plainly here, because the numbers in `status/evidence/` depend on it.

**A pre-mark is not a label, and cannot be promoted to one.** `Label.source`
has three members — `human`, `confirmed`, `edited` — and every one of them
means a person decided. There is deliberately no `suggested`. Anything computed
over `suggestions.json` is the model's read of the corpus, not a measurement of
the model against anything.

**So `extraction_macro_f1` has no denominator yet.** It was specified against a
hand-labelled corpus. Scoring extraction against the pre-marks instead would
score the same kind of reader against its own reading of the same adverts and
pass near 1.0 — which is exactly the failure D-2 (`lo-77a6`) was raised to catch,
one layer up from the cue-derived gold that first raised it. The answer is not
to lower the bar: T15 reports `n` beside the score, refuses to emit the score at
all while `n` is below the floor, and names the dimensions it could not measure.
Unmeasured is a third outcome, distinct from pass and from fail.

**Where labels can still come from, cheaply.** The 16 blind-control ads carry no
marks at all, so a label formed on one is an unprompted human read — the only
kind the corpus has. Reactions (step 5) and feedback (step 10) both put the
owner in front of real adverts in the normal course of using the tool, and both
already append to `evidence.jsonl`. Labels harvested there cost no separate
session. None of this is scheduled work; it is where to look when the gate needs
a denominator.

### What the round actually costs — measured 2026-08-24

`extraction_macro_f1`'s floor is **10 evaluation labels per dimension**, not ten
overall. There are **14**, spread one each across fourteen dimensions, so T56
(`lo-6f53`) is **236 labels short** of a denominator. Eleven ad-side dimensions
have none at all.

The live numbers are in `status/evidence/T15.json` —
`evaluation_labels_by_dimension`, `dimensions_below_floor`, `label_floor` — and
`make evidence` regenerates them. What follows is the part that is not in any
evidence file, and it is the part that decides how long the round takes.

**The pre-marking does not cover the corpus any more.** `suggestions.json` was
generated on 2026-08-19, over the 84 ads that were not in the blind-control
cohort. T25 then broadened the corpus to 208 ads across seven job families —
*after* that read. So:

| family | ads | pre-marked |
|---|---|---|
| programming | 100 | 84 |
| trades | 18 | **0** |
| healthcare | 18 | **0** |
| administrative | 18 | **0** |
| hospitality | 18 | **0** |
| teaching | 18 | **0** |
| retail | 18 | **0** |

Confirm-and-move is only available on programming. **The 108 ads in the six
broadened families would be labelled blind**, which is the slow path this
pre-marking exists to avoid — and they are the ads that matter most for the
question the corpus was broadened to answer.

`collaboration_mode` is the one dimension with no pre-mark even inside the 84.
That is not a broken cue set: its cues fire on 7 of the 208 ads, so it is simply
rare, and the 2026-08-19 reader never chose it. It will need labelling by hand
whatever else happens.

### One action serves both T56 and T57

**Regenerate `suggestions.json` over all 208 ads, with the reader allowed to name
what it cannot map.** That single pass:

- pre-marks the 108 ads that have no marks, turning the T56 round back into
  confirm-and-move instead of 108 blind reads;
- produces the top-level `unmapped` key that T57 (`lo-7c14`) is waiting for —
  `ontology_hit_rate` is `unmeasured` today precisely because no committed source
  declares it *could* have recorded an unmapped concept.

**The regenerated pass must be briefed differently from the last one.** The
2026-08-19 read worked "from each dimension's definition and its named rungs
only" — its own `note` says so. That is what makes its 828 mapped and 0 unmapped
a property of the briefing rather than of the ads, and it is exactly what T57
refuses to accept as a source. The new pass reads for meaning first and names
concepts freely; mapping to dimensions happens afterwards, and whatever fails to
map is the number T57 exists to report.

A pre-mark still is not a label. This shortens the round; it does not stand in
for the person at the end of it.

### What T59 costs — measured 2026-09-03

`extraction_negation_recall` (T59, `lo-4b17`) has its own denominator and its own
floor: **10 negated labels on the evaluation split**, counted overall rather than
per dimension. The store carries **9**. One label unblocks the number.

The live values are in `status/evidence/T16.json`. Two of them say what a bare
count cannot, and both should be read before the round is called done:

| key | today | why it matters |
|---|---|---|
| `negated_label_count_by_language` | `{en: 0, es: 9, ca: 0}` | The floor is a **total**. A tenth Spanish label makes the score "measured" with Catalan `no … pas` and every English negator never once scored. |
| `negation_recall_hits_by_mechanism` | `{scope: 3, denies: 3}` | Half the hits are `denies` cues — the negator is inside the cue's own pattern (`sin\s+viajes`). Only `scope` tests the backward-looking rule T16 built. |

So the cheap round is not "one more label". It is **one English and one Catalan
negated label**, on adverts whose denial the cue set does *not* already spell
out — a `negatable` cue with a negator in front of it, not a `denies` cue. That
is three labels, and it takes the measurement from Spanish-only to the parity
the repo requires everywhere else.

A pre-mark still is not a label here either. `negated` is a person's reading of
a denial, and `suggestions.json` cannot supply one.
