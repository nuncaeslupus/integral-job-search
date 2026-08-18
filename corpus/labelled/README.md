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

Typing a quote correctly, in Catalan or Spanish, in a terminal, 300+ times
(100 ads × up to 22 dimensions) is the actual bottleneck `set` alone leaves
open — a mistyped accent is rejected outright by the same verbatim check that
protects the corpus. `tools/labelling_page.py` and `harness import` remove
the typing without touching the judgement:

```bash
uv run python tools/labelling_page.py           # writes corpus/labelled/label.html
open corpus/labelled/label.html                 # or: xdg-open / double-click — file://, no server
```

Work through the ads in the page: select the words in the ad that evidence a
dimension with the mouse — the page reads the browser's own selection back as
the quote, so it is always an exact substring of the ad and can never fail
`set`'s verbatim check — enter a value, and tick **negated** when the ad
*denies* the dimension ("sense guàrdies", "no on-call") rather than being
silent about it. Progress accumulates in the browser's `localStorage`, so
closing the tab does not lose it; a visible JSON blob on the page is the
running export.

When ready — after one ad or after all 100 — copy that blob to a file and
apply it in one atomic batch instead of one `set` call per label:

```bash
uv run python -m jobsearch.harness import labels.json
# or, piping the clipboard straight through:
pbpaste | uv run python -m jobsearch.harness import -
```

`import` is exactly as strict as `set` — the same verbatim-quote search, the
same refusal of an absent or ambiguous quote — run over the whole batch before
anything is written: one bad row refuses the entire file rather than
half-applying it. Re-importing the same export (or a superset of it, after
labelling more ads) is safe; it overwrites in place rather than duplicating.

The page also shades where a dimension's extraction regex matches the ad
text, purely so the eye lands on the right paragraph — it never sets a value,
never picks a dimension, and never fills a quote. v0's gold examples are
already known to be cue-derived rather than independent (D-2,
`status/plan.md`), and `extraction_macro_f1` is measured against this
corpus — a page that pre-filled from its own cues would let that gate check
the extractor against itself. The page says so in its own UI, above the ad,
every time it is opened.

## Self-agreement

The labelling protocol calls for re-labelling a subset at least two weeks later
and reporting self-agreement (`status/specification.md`, open questions). Pass
`--round 2` on the second pass; `agreement` reports **Cohen's kappa** over the
sign of each value (negative / absent / positive).

Only ads actually revisited are compared. Within those, a dimension labelled in
one round and not the other counts as a **disagreement** — present versus absent
— rather than being skipped: comparing only the dimensions both rounds share
would discard exactly the cases where the two passes differed most, so agreement
would rise the more the labeller changed their mind.

Kappa rather than raw agreement, because most dimensions are absent on most ads:
two passes that both score everything zero agree 100% of the time and have
established nothing. In that degenerate case kappa is 0/0, and the report says
`kappa: null` with the reason rather than claiming perfect agreement.

## Gate

`corpus_harness_roundtrip_loss == 0` — write the store, read it back, and
compare text, splits, and every span **by the text it extracts**, not merely by
its integers. An offset that survives as a number but covers different
characters is the failure this exists to catch.

Because the store is unlabelled until T5, the gate also measures a copy carrying
one probe label per ad, with offsets taken from a real cue match in real ad
text. Without it the roundtrip would preserve offsets vacuously, having none to
preserve.
