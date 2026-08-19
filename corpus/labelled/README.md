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

**The store is currently unlabelled.** Labelling is T5, by hand.

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
uv run python -m jobsearch.harness init                    # seed / re-seed, keeping labels
uv run python -m jobsearch.harness next --language ca      # next ad awaiting labels
uv run python -m jobsearch.harness set <ad-id> <dimension> <value> --quote "<verbatim text>"
uv run python -m jobsearch.harness status                  # counts, splits, agreement
uv run python -m jobsearch.harness agreement               # self-agreement report
uv run python -m jobsearch.harness gate                    # write status/evidence/T4.json
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
uv run python -m jobsearch.harness import t5-labels.json
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

`jobsearch.suggestions` measures what that rule cannot prove:

```bash
uv run python -m jobsearch.suggestions        # writes status/evidence/T5-suggestions.json
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
