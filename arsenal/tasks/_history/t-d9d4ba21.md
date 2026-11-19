---
id: t-d9d4ba21
title: "Read the advert page when the list row only carries a teaser"
label: "full advert text"
priority: 5
tags: [sourcing]
status: merged
---

A listing row that carries a teaser builds an offer by itself, so the advert's own page is never fetched and the stored `text` is the teaser alone. In `integral.sourcing` (the `if offer is None and connector.detail is not None` branch, about line 1806), the detail page is read only when the list row cannot complete an offer.

Measured on 2026-11-19, on a live sweep of `tecnoempleo_es`: the stored `text` was the list teaser ending in "..." (about 190 characters), and `location.raw` was the list's "100% remoto". The detail page held the full body (2 to 4 KB) on the connector's own `detail.fields.text` selector, which matched one node per page. So every downstream filter judged the teaser:
- `publisher_kind` returned `unknown` for an advert whose body says the work is a long-term project for a client, with a client interview.
- Seniority, the real work location and the pay band were invisible.
- An advert was presented to a candidate as remote and suitable when its body was senior and on-site in another city.

## Wanted

When a connector declares a `detail:` block, fetch the advert page for every new offer, not only for rows the list cannot complete. Detail fields win on overlap, as they already do. Keep `DETAIL_FETCH_CEILING` and robots per URL as they are. A row whose detail fetch fails or is refused keeps the list-only offer, and the run says how many offers carry list text only.

Tests, from the connector's own fixture (`connectors/tecnoempleo_es/fixture/`): an offer built from a list row with a teaser carries the detail page's `text` and `location_raw`; a refused or failed detail fetch still yields the list-only offer and is counted.

## Acceptance gate

```bash
uv run --extra dev pytest tests/test_sourcing.py -q
```
