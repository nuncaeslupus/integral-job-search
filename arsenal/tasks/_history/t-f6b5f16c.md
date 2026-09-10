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

`employer_boards.measure_attribution` runs one sourcing round over
`ATTRIBUTION_BOARDS`. It is a closed product, not a list of cases:

- every declarable kind, meaning each `SourceKind` value plus undeclared;
- crossed with having an `{employer}` slot or not;
- crossed with how the one request ends: read, timed out, or refused with a 429.

That makes eighteen boards. A kind added to `SourceKind` joins the round by
itself. Each board's expected answer comes from the table and never from
`source_kind_of`:

- Every stored offer carries exactly its board's declared kind. The slot never
  decides it.
- The summary's employers line names exactly the declared employer boards that
  returned rows. A board refused on its first request is neither skipped nor an
  error, so `Run.employer_boards` reads `items > 0` rather than
  `reached_the_board` (#462 round 2, G3).
- The value is `-1` rather than a clean zero when any board that was read
  stored no offer. The test is parametrised over every such board (F2, G2).

It records `source_kind_defects` in T144's evidence, since T130 already reads
T126's file the same way. A control test patches `source_kind_of` and watches
the metric move.

Fourteen mutants are killed, each run in a fresh subprocess:

- the `build_offer` assignment, the outcome assignment, and the summary line;
- `source_kind_of` answering `"employer"` for every board;
- slot inference (F1);
- the `-1` guard dropped, weakened to "stored anything" (F2), or checking one
  board (G2);
- `reached_the_board` restored (G3), and the row filter dropped;
- `greenhouse_en`'s declaration dropped;
- any declaration read as `"employer"`, and any declared board named in the
  summary (G1);
- the declaration honoured only with a slot (G4).

**Not in this task:** passing `source_kind` to `dedup.select_survivor` or
`bulk_filter.reduce` in production. No caller does that yet, so T75's preference
still reaches nothing. The same goes for showing the kind per offer in step 9's
presentation.
