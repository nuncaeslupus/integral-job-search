# Session handover — 2026-08-23 (third session of the day)

## What is open

| PR | Task | Gate | State |
|---|---|---|---|
| [#131](https://github.com/nuncaeslupus/job-search/pull/131) | T25 corpus job families | `corpus_job_family_count == 7` (floor 6) | open, awaiting review |
| [#133](https://github.com/nuncaeslupus/job-search/pull/133) | T12 live portal connector | `connector_fixture_parse_f1 == 1.0` (floor 0.95) | open, awaiting review |

`merge-policy` is `after-review`, so neither was self-merged. Both pass
`make host-gate` locally; CI is red on both for the known runner-minutes reason
(`runner_id: 0`, 2–4 second jobs). Issues 50 and 51 close on merge via `Closes #`.

Board: 95 tasks — 0 open, 2 claimed (the two above), 1 done, 1 cancelled, 14 blocked,
77 merged. **The queue has nothing unblocked left**: every remaining task depends on
T25 or T12 merging, or on T5/T20 which are `[HUMAN]`.

PR #132 ("one priority scale on the board") is not from this session.

## The thing worth carrying forward

**Check robots.txt before choosing a board, not after building against it.**

T12 was most of the way to a connector on tecnoempleo.com before its robots.txt was
read. It names `ClaudeBot`, `Claude`, `anthropic-ai`, `Claude-Web`, `Claude-SearchBot`
and `AnthropicBot`, each with `Disallow: /`. The recordings were deleted and the board
switched. `remoteok.com` blanket-blocks `ClaudeBot` too.

This is not a T12 detail. **`tools/collect_ads.py` still has `from_tecnoempleo` and
`from_remoteok` adapters, and 53 of the corpus's committed ads came from tecnoempleo**
(T4b, long before this session). Nothing was changed about that here — removing 53 ads
and a source adapter is the repo owner's call, not a worker's. It needs a decision:

1. leave it (the ads are already collected; the block post-dates the collection), or
2. drop both adapters and re-collect those 53 from permitted boards, or
3. keep the adapters but stop running them.

Whichever way, `connectors/trabajos_es/meta.yaml` shows the shape of the check that
would have caught it: `policy.robots_txt: respected` is a field a package must assert,
so it forces the question at authoring time.

The other reason the board changed is worth knowing before the next connector:
**weworkremotely, remotive, getmanfred, feinaactiva and EURES all permit us, and all
serve their listings from JSON APIs or JavaScript applications.** `integral.connectors`
matches CSS selectors against served markup, so on those boards there is nothing on the
page to find. Server-rendered HTML is now a scarcer precondition than permission is.

## Two patterns that held up again

Both PRs ran a **mutation pass before opening**, per the last session's recommendation.
It paid for itself twice, and one round found what review would have:

- T25's gate looked green while `retail` had 11 ads against a floor of 15, because
  Catalan titles are written `Venedor/a` and a pattern needing a following word never
  fired on the gender suffix.
- T12's first precision test could not distinguish `false_positive = 0` from the real
  thing, because it only tested a case where hits were already zero. Rewritten with one
  right cell and one wrong one.

**The independent-witness pattern generalises.** T12's expected offers are written by a
different parser (lxml + full CSS) from the one under test (hand-rolled, no
combinators), and are committed as frozen data the gate never regenerates. If the gate
re-ran the annotator, both sides would be recomputed from the fixture in one breath and
agree with themselves whatever either did — the same failure T46's harness had.

## Stated ceilings, deliberately not built

- **T12 reads one listing page.** trabajos.com pages by offset (`&DESDE=41`, 40 at a
  time) and `Pagination` only emits consecutive integers, so a stride of 40 is not
  expressible in the schema. Declared `mode: none` rather than encoding a lie. A `step:`
  field on `Pagination` is the upgrade path — **worth a task, not seeded**.
- **T25's six new families are ca/es only.** "The same three languages" was read as a
  whitelist on what may enter the corpus, not a per-family quota: they are on-site roles
  in Catalonia and no English-language board advertises Catalan hospitality work.
- **T25's new families are unlabelled.** The labelled store is still T5's 100
  programming ads; T26 sequences widening it. `test_corpus_raw.py`'s language mix and
  `test_corpus.py`'s roundtrip count were scoped to the `programming` slice for that
  reason — scoped, not weakened, and D-1's anchors are untouched.

## Board hygiene, unactioned on purpose

`query_status.py` still flags `mixed-priority-convention`: 2 tasks carry priority 70/60
on a board whose size scale is 10/5/1. Changing them changes what runs next, which is
the owner's call. PR #132 may already address it.
