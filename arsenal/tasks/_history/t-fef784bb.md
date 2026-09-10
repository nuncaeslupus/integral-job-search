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
