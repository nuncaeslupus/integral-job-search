# Session handover

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
