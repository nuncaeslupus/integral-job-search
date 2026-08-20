---
id: lo-a95d
title: "S5: Offer lifecycle — status, purge rule, tombstones so dedup cannot resurrect, retention for what mattered"
priority: 68
deps: [lo-6928, lo-5c8c, lo-9e33]
workspace: SUPPLY
tags: [m2]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/23
---

## Acceptance gate

```gate
resurrected_purged_offers == 0
evidence: status/evidence/S5.json
key: resurrected_purged_offers
```

```bash
uv run --extra dev python -m jobsearch.lifecycle status/evidence/S5.json
```

## What this is

Ads go stale, and a tool that accumulates them forever becomes unusable
(brief §2.4). Four parts:

- **Status** per offer: new, screened out, shortlisted, applied, rejected,
  expired, archived.
- **Purge rule** for ads never shortlisted and past their useful life.
- **Tombstones** — a purged ad's id, URL and text hash survive its body, so
  re-collection and dedup cannot resurrect it. This is the gate.
- **Retention** — anything shortlisted, applied to, or interviewed for is kept
  in full, indefinitely. Those are the ads that explain a candidate's history.

## The gate

`resurrected_purged_offers` counts offers that were purged and later reappeared
as new. Zero. Without tombstones the next collection run re-adds everything just
deleted, and the candidate sees the same rejected ads forever — the specific
failure the owner called out.

## Tests

`test_a_purged_offer_does_not_return_on_recollection`;
`test_a_shortlisted_offer_is_never_purged`;
`test_a_tombstone_carries_no_ad_body` — retention and privacy both.

## Location

Service: **SUPPLY** · Size: M · Depends: S1

Source: `status/spec-v2-brief.md` §2.4
