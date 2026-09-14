# Session handover

## 000. T169 and T170 seeded (#457): the two engine gaps #445's second reader found

Seeding only. Nothing is built. Both tasks depend on T144 (merged) and are
unblocked. The owner approved the design on 2026-09-10, and it is written into
each task file.

- **T169** ([#453](https://github.com/nuncaeslupus/integral-job-search/issues/453),
  F5): a field cannot say its value is markup. **13 of 75** fixture offers on
  `main` carry HTML in `text`:
  - greenhouse holds escaped HTML, two layers deep;
  - workable, rippling, himalayas and workingnomads hold raw HTML;
  - weworkremotely does too, on its list page;
  - getmanfred holds Markdown with an inline `<u>`.

  The fix is two closed `take:` members, `html_text` and `escaped_html_text`,
  both reusing `Node.text_content`, plus an optional `{path, take}` form for
  JSON fields. The owner chose to put every connector in scope, not only
  greenhouse.
- **T170** ([#454](https://github.com/nuncaeslupus/integral-job-search/issues/454),
  F13): **the pay floor applies to no salary a connector states.** Lever sends
  `per-year-salary`, himalayas `annual`, and justjoin and jobfluent `MONTH`/`YEAR`.
  `bulk_filter` compares those against the floor's `year`/`month` by equality.
  The fix:
  - `Salary.period` becomes a closed `Literal`;
  - one table in `build_offer` maps each board's words onto it;
  - a period that cannot be represented (`one-time`) states no salary.

  The last point was the owner's choice.
- **Both contract tables are written by a second session**, from the WHATWG
  spec for T169 and from each board's own docs for T170, before the
  implementation is read.
- **Still open: T166 is used twice**, for #446 and #451. One of them needs
  renumbering.

## 00. T171 opened (#461): a steerable connector's query must be in its capture

- **T171** ([#456](https://github.com/nuncaeslupus/integral-job-search/issues/456),
  PR [#461](https://github.com/nuncaeslupus/integral-job-search/pull/461)) adds
  `integral.query_capture`. For every package with `{query}` in `url_pattern`,
  the probe URL must be a URL the pattern issues, with `{query}` filled.
  `jobfluent_es`'s probe was re-recorded `live` from `?q=python&page=2`, and a
  nonsense `q` gives 0 rows, not a fallback list. Merged with `main` at
  `69aae26`. Waiting for a second reader and CI.
- **It will name two open PRs' packages as they are pushed today.** `trabajos_es`
  on #447 (probe still `atencion_al_cliente`, no `CADENA=`) and `infojobs_es`
  on #455 (`…/{query}/barcelona` over a probe with no query segment). Each needs
  a probe recorded from a real search before it merges after #461.
- **Census collision to watch:** #461 and #445 both change
  `floor_sweep.MINIMUM_FLOORS_SWEPT` from 74 to 75, in byte-identical text. Git
  will merge them silently, and the merged tree counts 76. Whichever merges
  second regenerates it and raises the floor; don't pick a side.

## 0. A concurrent session, same evening: T168 merged (#452)

**`origin/main` is now at `fff210d` (#452), not the #444 repair the next
section describes.** `make host-gate` was re-run against `main` after the merge:
PASS, 3549 passed, no drift.

- **T168** ([#450](https://github.com/nuncaeslupus/integral-job-search/issues/450)):
  `lifecycle.collect_offer` only consulted tombstones, so re-collecting a stored
  offer rewrote its lifecycle as a fresh `new` and counted as added. A
  shortlist was lost on every sourcing run, and `BoardOutcome.added` counted
  re-sightings. Fixed in `collect_offer`: an offer whose **lifecycle record**
  exists is left alone. S5 records `live_offers_reset_by_recollection`.
  Two second-reader rounds, both CLEAR; round one's three findings were
  accepted and pinned before merge.
- **The T-number collided three ways.** Three sessions each minted **T166**
  within half an hour: #446/#447 (first, kept it), #450 (renumbered to T168),
  and **#451 (InfoJobs), still titled T166 — its session must renumber it**.
  `plan_v2` catches a duplicate row only once both land on `main`, so the
  collision is invisible from inside any one branch. Check open PRs' plan rows,
  not only `main`, before minting a label.
- **The auto-mode classifier blocks a bare merge.** Merging needed the owner's
  explicit "merge when green and no comments" in chat.

**2026-09-10, evening.** One task seeded, solved and opened: **T166**
([#446](https://github.com/nuncaeslupus/integral-job-search/issues/446), PR
[#447](https://github.com/nuncaeslupus/integral-job-search/pull/447)). Nothing
merged this session. `origin/main` is still at the #444 repair.

## 1. Why T166 exists: the gap was sector, not language

A live candidate session sourced for a pharmacy technician / dermoconsejera in
Barcelona. **None of 81 offers** from the six ES boards was a pharmacy job. The
ES shelf is tech boards plus `trabajos_es`, and that one pointed at the fixed
`atencion_al_cliente` category, so every candidate got the same forty
customer-service adverts. A non-tech candidate could not be served.

**#447 steers it** through the board's own `?CADENA={query}`. `técnico
farmacia` returns 40 rows, 21 of them pharmacy, lab or cosmetics titles, and 11
in Barcelona. A nonsense word returns 0 rows, not a fallback list. The pin is
the test naming the steered ES set, which is mutation-checked. The count
`boards_steered >= 3` alone would not catch a revert once another steerable
board lands.

## 2. Three readable pharmacy boards, each blocked on the engine

Surveyed with `connector-new` and recorded in `connectors/ruled-out.yaml`, with a
retest per entry:

| board | why it matters | engine change it needs |
|---|---|---|
| farmatalent.com | pharmacy-office jobs only, Barcelona filter | a field that reads the **item's own** attribute (the href is on the card's `<a>`) |
| infoempleo.com | general board, all sectors, steerable | a **no-results marker**: a miss prints ten fallback adverts in the same `li` |
| pmfarma.com | pharma-industry and dermoconsejera roles, public JSON | a mapped `url` must **outrank the detail fetch URL** in `build_offer` |

My recommendation is infoempleo's gap first. It is the only one bringing a
general, steerable board, so it serves every non-tech candidate. Farmatalent
fits a pharmacy candidate best, but it has no search. With no sector routing,
every ES candidate would get about 12 pharmacy adverts per run. **None of these
three should start before #445 (T144) merges**: all touch `connectors.py` or
`sourcing.py`, where T144 is changing the list format.

Out, and why: the COFB board needs a member login and robots-refuses
`/group/guest/`; the CGCOF portal is admin-ajax and lists no Barcelona;
es.jooble.org and es.indeed.com answer 403; opcionempleo.com serves a challenge
page, not bypassed; and the robots.txt of jobatus.es and laboris.net cannot be
read.

**After #445 lands**, check whether pharmacy employers post on an ATS host T144
reads: online pharmacies, chains and hospital groups. That route may be cheaper
than any of the three engine changes.

## 3. Standing answers, still true

- `review_reader check` reads **exit 2** on this surface and always will:
  every session authenticates as `nuncaeslupus`, the PRs' own author. The
  owner's answer is to merge on the second reader's verdict and record the check
  as unsatisfiable rather than imply it passed. Do not re-ask it.
- **Re-run `make host-gate` against `main` after any batch of merges.** The
  #434/#436 collision was visible in neither diff.
- **`gh pr edit` fails** here on a Projects-classic GraphQL deprecation. Edit
  a PR body with `gh api -X PATCH repos/<owner>/<repo>/pulls/<n> -F body=@file`.

## 4. Pick up here

1. **#447**: a second reader (Opus) was dispatched on head `a0614487`. If its
   report is CLEAR, merge. The `verified_gate.sh` PASS block and green CI are on
   that same head. If it is BLOCK, fix and re-read.
2. **#445** (T144) is open in another session. When it and #447 both merge,
   whichever lands second regenerates evidence (`T89.ledger_entries_scanned`
   and `T126` are the likely collisions) rather than picking a side.
3. File the three engine gaps in §2 as tasks once #445 is in.
4. Still open and unclaimed from the previous handover: **#437**,
   **#439/#440/#441**, **#420**, **#427**, **#426**, **#314**. **#412** still
   needs egress.
