---
id: t-f6b5f16c
title: "T172: an ATS-host result is stored and reported as a job-board result, though it came from the employer's own board"
priority: 10
deps: [t-ee67736b]
tags: [SOURCING]
workspace: SUPPLY
status: merged
---

## Acceptance gate

```gate
source_kind_defects == 0
evidence: status/evidence/T144.json
key: source_kind_defects
```

```bash
uv run --extra dev pytest tests/test_employer_boards.py -q
uv run --extra dev python -m integral.employer_boards
```

T144 (#445) added five ATS-host packages whose list `url_pattern` carries an
`{employer}` slot, so every request they make reads one named employer's own
board. Its task text also asked that *"a sourcing round says where each result
came from"*: an aggregator and the employer's own board are different facts,
and on the only complete run so far the second one decided the outcome. The
round-1 second reader on #445 (F14) found nothing declared it. These offers were
stored as `source: greenhouse.io` and nothing else, so they could not be told
apart from a job board's. The owner deferred it to this task.

**The kind is declared in `connector.yaml` as `source_kind: employer`, and
never inferred.** The first cut read it off the `{employer}` slot. The #462
second reader (F1) showed why that fails open: a job board's company page, such
as `indeed.com/cmp/{employer}/jobs`, takes the same slot and would have been
reported as the employer's own board. T75 already says the kind is "declared by
whoever assembles the batch — a connector's own metadata" and "never guessed
here from a URL". A hard-coded list of ATS hosts is the guess that sentence rules
out. The declaration is independent of the slot: a single employer's careers
page is that employer's own board and has no slot. The five T144 packages
declare it, and a test names them.

- **Stored offer.** `Offer.source_kind: SourceKind | None` sits beside `source`.
  It uses the existing T75 vocabulary, which moves from `dedup.py` to
  `offers.py` so the model can carry it. `build_offer` copies the connector's
  declaration into it. `None` means
  nothing declared it, never `"aggregator"`: calling every other board an
  aggregator is a claim nobody made. The field is additive and optional, and it
  is never backfilled.
- **Round summary.** `BoardOutcome.source_kind` holds the same value, and
  `Run.summary()` gets one line: *the employers' own boards, not a job board: …*.

`employer_boards.measure_attribution` runs four constructed boards through
`sourcing.source`, and each board's expected answer comes from its own table:

- a declared employer's board with the slot;
- a plain job board;
- a job board's company page that has the slot but declares nothing (F1);
- a declared employer's board whose every request fails, which must not be
  named in the summary (F3).

It reads the stored offers back from disk and checks the summary line exactly.
It records `source_kind_defects` in T144's evidence, since T130 already reads
T126's file the same way. The value is `-1` rather than a clean zero when any
board meant to store an offer stored none. That includes the employer board
alone (F2). A control test patches `source_kind_of` and watches the metric
move. It is mutation-checked. Each of these reverts turns it red:

- dropping the `build_offer` assignment
- dropping the `BoardOutcome` assignment
- dropping the summary line
- making `source_kind_of` answer `"employer"` for every board
- inferring the kind from the slot again (F1)
- dropping the `-1` guard, or weakening it to "stored anything" (F2)
- dropping `reached_the_board` from `Run.employer_boards` (F3)
- dropping `greenhouse_en`'s declaration

**Not in this task:** passing `source_kind` to `dedup.select_survivor` or
`bulk_filter.reduce` in production. No caller does that yet, so T75's preference
still reaches nothing. The same goes for showing the kind per offer in step 9's
presentation.
