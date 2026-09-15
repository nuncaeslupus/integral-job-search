---
id: t-fef784bb
title: "T174: a refusal on an advert page is followed by 39 more advert requests, and a refused board is listed as reached"
priority: 10
tags: [BACKEND]
workspace: BACKEND
status: merged
---

## Acceptance gate

```gate
advert_requests_after_a_refusal == 0
evidence: status/evidence/T126.json
key: advert_requests_after_a_refusal
```

```bash
uv run --extra dev pytest tests/test_sourcing.py tests/test_employer_boards.py -q
uv run --extra dev python -m integral.sourcing
```

## The defects

Two findings from the round-3 second-reader report on #445 (T144), both present
on `main` at 69aae26 and deferred there. Must land before T167 (#458) makes
GLOBAL / ATS-host packages selectable.

**R3-3 (fail-open, politeness).** `sourcing._one_board` stopped on a refusal
(`connector_health.BLOCKED_STATUSES` = 403/429/503, via `rate_limited`) for
**list** responses only. `_detail_record` returned `None` on any non-200 advert
page, so a 429 on the first advert was followed by up to
`DETAIL_FETCH_CEILING - 1` (39) more requests to the host that refused, and the
rows were reported as "not offers — no 'text' field", a connector defect,
rather than as the board saying stop. Measured on `main`'s fixtures:
getmanfred_es asked 3 advert pages, trabajos_es 12, after the first 429.
A list refusal was also per board-and-phrase only: a steerable board was asked
again for every remaining phrase after it had answered 429.

**R3-4 (reporting).** `BoardOutcome.reached_the_board` was
`skipped is None and error is None`, so a refused board was still listed under
"searched for your terms" / "returned their whole list" in `Run.summary()`.

## The fix

* A refusal (list or advert page) records the host's origin in one
  run-scoped `refused_origins` map that `source` shares across every board and
  phrase. No further request — list or advert — goes to that origin this run.
* `_detail_record` returns the refusal apart from a plain failure: a 404 is one
  missing advert, a 429 is the host saying stop.
* Rows left unread because the host refused are not counted as `dropped`; the
  outcome carries `refused`, and the summary's REFUSED line says how many
  offers were added before it (partial).
* `reached_the_board` also requires `refused is None`. Its consumers on `main`
  are `Run.steered` and `Run.unsteered` only (`search_terms` reads the fetch
  log, not outcomes).

## What the metrics count

In `status/evidence/T126.json`, from `measure_fixture`'s second constructed run
over the same six ES captures with every advert page answering 429:

* `advert_requests_after_a_refusal` — advert requests made to an origin that
  had already been asked one: 0 (13 with the fix reverted).
* `refused_boards_listed_as_reached` — boards that made an advert request
  (every one of which was refused) and are also in `steered` / `unsteered`: 0
  (2 with R3-4 reverted). Its population is deliberately not `Run.refused`,
  which is the fix's own output: a fix that stopped the requests but never
  recorded the refusal would read a vacuous zero there.
* `boards_with_a_second_advert_to_refuse` — the population, independent of the
  fix: boards whose list needed more than one advert page. A zero makes the run
  `unmeasured`.

The fixture run has one phrase, so the cross-phrase half is pinned by tests
only: `test_a_host_that_refused_is_not_asked_again_by_the_next_phrase` (over
both shapes a fetcher gives a 429 — a body, and T144's `error`-carrying
response) and `test_a_refused_advert_page_stops_the_next_phrases_list_too`.
The ATS shape — lists on one host, advert bodies on another, as Lever's
api.lever.co / jobs.lever.co — is pinned by
`test_a_refused_advert_host_is_asked_once_across_employers` in
`tests/test_employer_boards.py`: the second employer's list is still read (a
different origin), its adverts are not.

Rebased onto T144 (#445), which merged while this was in flight: its `ended()`
closure carries `refused` for the break path, and its errored-list refusal
(`blocked`) records the origin like the parsed-list one.

## Second-reader round 1 (#466): three blocking findings, all accepted

* **F1 (fail-open).** `_origin` was `scheme://netloc`, so
  `https://www.usajobs.gov` and `https://www.usajobs.gov:443` were two origins
  — and `usajobs_en` lists on the first spelling and links its adverts as the
  second. A refusal on one left the other free to be asked. `_origin` now
  returns RFC 6454's (scheme, host, port) with the default port filled in;
  `test_one_host_is_one_origin_however_its_links_spell_it` pins it, including
  the controls that a different port, scheme or host stay different origins.
* **F2 (the gate measured a proxy).** `advert_requests_after_a_refusal`
  counted origins with the very function it was checking, so `_origin`
  returning the whole URL — R3-3 fully back — still read 0 and `measured`. It
  now counts by `urlsplit(...).hostname`, independent of `_origin`: that
  mutation reads 13.
* **F3 (pinning gap).** A refused advert page arriving as
  `Response(429, "", error=...)` was handled correctly and tested nowhere;
  moving the `error` check ahead of the refusal check in `_detail_record`
  restored the defect with every test green. The advert test is now
  parametrised over both shapes.

Non-blocking and deliberately left: a **challenge page at 200** on an advert
page is not a refusal (the list rule reads body markers only when nothing
parsed; the advert rule reads the status alone, as R3-3 asked — and round 2
adds that reusing `BLOCK_PAGE_MARKERS` on an advert body would be fail-closed,
since `rate_limited`'s own docstring says "captcha" and "access denied" occur
in real adverts), and `Run.searched` still lists a phrase whose boards were
never asked because their host had already refused (#458 carries the filter
that fixes it, and whichever PR lands second should pin the refusal case).

**Rows left unread by a refusal are counted nowhere in full.** Round 2
measured 15 unread against a `detail_needed - detail_fetched` of 13: the two
rows whose own fetch drew the 429 are inside `detail_fetched`, so the
difference undercounts by one per refusing board. Nothing in this PR depends
on it; #458's row-accounting identity will, and this is the number it must
not assume.

Mutation round after the fixes: **13 mutants**, all killed by the scoped tests
— M1-M9 and M4b over the original fix (ten), F1-F3 over the round-1 remedies
(three). The metric kills M1, M2, M3, M7, M8, M9 and F2.

## Second-reader round 2 (#466): CLEAR, five non-blocking findings

All five are addressed rather than waved through:

* **N1** — the round-1 reporting fix (a board keeps its own refusal reason)
  had no fixture: reverting it left 92/92 green. Pinned by
  `test_a_board_refused_on_its_own_advert_keeps_that_reason` in
  `tests/test_employer_boards.py`, on a board serving adverts from its own
  host, and by the two-page arm of
  `test_a_refused_advert_page_stops_the_next_phrases_list_too`. Round 3
  dropped that arm on the claim that `getmanfred_es` is one page per run;
  round 4 (#466 N7) showed the claim is false — `mode: none` clamps only when
  `page_count is None`, so `page_count=2` really does make a second request —
  and the arm is restored. The first assertion written for it did **not** kill
  the mutant: the
  carry-over wording quotes the reason it carries, so asserting that reason's
  text passed either way. The discriminator is the absence of the carry-over,
  and round 3 (#466 N6) caught the same mistake a second time, in the prose
  that credited the wrong test.
* **N2** — `_origin`'s `except ValueError` branch was dead to the suite and was
  the one part that did not case-fold. It folds now, and both properties are
  pinned in `test_one_host_is_one_origin_however_its_links_spell_it`.
* **N3** — `boards_with_a_second_advert_to_refuse` counted `detail_needed > 1`
  rather than adverts the budget could ask for, so `DETAIL_FETCH_CEILING = 1`
  left the population at 2 and the gate `measured` over a metric that can
  observe nothing. It is `min(detail_needed, DETAIL_FETCH_CEILING) > 1` now,
  pinned by `test_the_population_counts_adverts_the_budget_could_ask_for`.
* **N4, N5** — two prose claims in this file were wrong (a mutant count that
  enumerated twelve, and the unread-row accounting above). Corrected here.

Round 2 also recorded that three single-line mutants still read 0/0
`measured` — reverting `_origin`, checking `error` before the refusal, and
neutering the list pre-check — each killed by a test but not by the evidence.
That is the honest reach of the key rather than a claim it catches everything.
