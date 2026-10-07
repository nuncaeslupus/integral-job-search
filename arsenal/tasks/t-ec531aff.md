---
id: t-ec531aff
title: "T276: Deduplication does not fire: the same advert is stored four times from one board"
priority: 5
requires: [human:gate]
---

Imported from issue #551

Step 7 promises *"deduplication is by similarity, not by hash — the same job at two boards is rarely byte-identical."* Measured on a live round, it does not fire even on the easy case: the same board, the same employer, the same title.

## Measured 2026-09-22, 221 stored offers

| | groups | extra offers | groups inside one board |
|---|---|---|---|
| reachable (124) | 4 | 4 | 3 |
| foreign (97) | 10 | 17 | **10** |

**Every duplicate group in the foreign set is within a single board.** Worst cases, all greenhouse/anthropic:

```
Applied AI Architect, Partnerships   -> stored 4 times
Forward Deployed Engineer            -> stored 4 times
Applied AI Architect, Industries     -> stored 4 times
Applied AI Engineer, Enterprise      -> stored 2 times
```

So 41 "Anthropic vacancies" is not 41 vacancies. The candidate spotted it unaided: *"Algunas ofertas están duplicadas, incluso de la misma web"*.

These are near-certainly one posting listed under several offices, so the records differ in `location_raw` and in the URL's query — enough that a URL or text hash separates them, which is the mechanism the spec already says is not sufficient.

## Acceptance gate

```bash
uv run python -m integral.dedup
```

`stored_offers_sharing_title_company_and_source == 0` over the committed corpus, **plus** `distinct_vacancies_merged_wrongly == 0` over a fixture pair of genuinely different vacancies that share a title at one employer (two openings of the same role in different teams). A similarity threshold tuned only against the first number collapses real vacancies, which is the fail-open direction here — the candidate never sees the one that was swallowed.

Filed from a live candidate round, 2026-09-22.

## Acceptance gate

<!-- This task came from an issue, so its "gate" is prose. Write a real check
     below, then DELETE the `requires: [human:gate]` line in the front matter.
     Until that line is gone the selector will not offer this task, which is
     deliberate: a prose gate runs nothing, and a gate that runs nothing passes
     everything. -->

```bash
# arsenal:gate-placeholder — replace with the real check; it may land in this task's own PR
false
```
