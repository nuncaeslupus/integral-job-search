---
id: t-bf1b62e6
title: "T224: One advert is stored once per search: 139 canonical URLs are stored more than once, so a ruled-out advert comes back under a new id"
label: "T224: One advert is stored"
priority: 5
status: merged
---

Filed from a candidate session (test-mode 658fcce2).

Measured 2026-10-02 on one candidate's store: 2,840 readable offers, **139 canonical URLs stored more than once, 378 extra copies** — jobfluent 64, ashby 36, tecnoempleo 14, greenhouse 10, weworkremotely 7, workingnomads 6, talent 1, foorilla 1. The offer id is a hash of the text, and a list row's text changes between searches; JobFluent's URL also carries the search (`?q=AI+engineer&result=21`). So dedup, tombstones and a rule-out recorded against one id all miss the copy. The candidate was shown two adverts he had discarded the day before.

Key storage and tombstones on the canonical URL (query string dropped where the connector declares it is not identity), and pin it per connector rather than for JobFluent alone.

Not every query string is disposable: talent.com's advert URL is `/view?id=<n>`, and the `id` is the
identity — 183 canonical talent URLs are 183 distinct adverts. `lifecycle.canonicalize_url` already
keeps it; a per-connector rule must not drop it.


## Acceptance gate

```bash
uv run pytest tests/test_advert_identity.py -q
```

