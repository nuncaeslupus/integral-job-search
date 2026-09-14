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

`employer_boards.attribution_round` runs one sourcing round over
`ATTRIBUTION_BOARDS`. It is a closed product, not a list of cases. Two axes
decide what a board's results are — what it declares, and what comes back:

- every declarable kind: each `SourceKind` value, plus undeclared;
- crossed with one request, or two so a board can fail part-way (an
  `{employer}` slot with two employers);
- crossed with every way a request can answer: a new offer, an advert already
  in the store, no rows, a row that builds no offer, a timeout, a 429.

That is 126 boards, and a kind or an answer added anywhere joins the round by
itself. `attribution_expectations` derives each board's answer from the table
before anything runs, so no expectation comes from `source_kind_of`:

- Every stored offer carries exactly its board's declared kind.
- The summary's employers line names exactly the declared employer boards one
  of whose rows became an offer. `Run.employer_boards` therefore reads
  `items > dropped`. T144 asks where each **result** came from: a board that
  answered with no rows, or with rows that build no offer, produced none —
  while one refused after reading some did, and so did one whose offer was a
  re-sighting, where `added` is 0 (#462 rounds 2 and 3, G3 and H1/H2).
- `-1`, never a clean zero, when a board that should have stored an offer
  stored none. `attribution_verdict` is split from the round so that rule is
  checked for **every** such board without re-running it (F2, G2, H3).

It records `source_kind_defects` in T144's evidence, since T130 already reads
T126's file the same way. A control test patches `source_kind_of` and watches
the metric move.

The closure test writes the six answers out on the spec's side rather than
reading `ATTRIBUTION_RESPONSES`. Deriving the expectation from the module's own
tuple would be a bound derived from the thing it bounds — deleting an answer
would satisfy it, and deleting `badrow` or `known` brings the `items > 0` and
`added > 0` mutants back to life (#462 round 4, J1).

Twenty-one mutants are killed, each in a fresh subprocess. Among them: the
declaration read off the slot (F1); any declaration read as `"employer"`, and
any declared board named (G1); the declaration honoured only with a slot (G4);
and every near-miss of the naming rule — `reached_the_board` (G3),
`reached_the_board and not refused`, `status == 200`, `items > 0` and
`added > 0` (H1/H2). So is a `-1` guard that goes quiet on an empty round (H3),
and the one check whose population never arrives is pinned by a synthetic
verdict rather than left unreachable.

**Not in this task**, and filed instead: a board with no `{employer}` slot
reads one page per round, so no board in the table can read rows and *then*
fail. `items > dropped and error is None` therefore survives, which is wrong
for a multi-page employer careers page and fails closed (#462 round 4, J2).
Closing it needs a per-board page count, which `sourcing.source` takes per
round.

**Not in this task:** passing `source_kind` to `dedup.select_survivor` or
`bulk_filter.reduce` in production. No caller does that yet, so T75's preference
still reaches nothing. The same goes for showing the kind per offer in step 9's
presentation.
