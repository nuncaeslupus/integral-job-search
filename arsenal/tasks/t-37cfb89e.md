---
id: t-37cfb89e
title: "T72: Connector health — detect a silently rotted parser"
priority: 5
deps: []
workspace: SUPPLY
tags: [v3]
---

# T72: Connector health — detect a silently rotted parser

## Acceptance gate

```gate
silent_connector_failures == 0
evidence: status/evidence/T72.json
```

```bash
uv run --extra dev pytest tests/test_connector_health.py -q
uv run --extra dev python -m integral.connector_health
```

The `bash` block regenerates `status/evidence/T72.json`; the `gate` block asserts the
number in it.

## Why

Scrapers rot silently: when a portal changes its markup, a CSS-selector connector exits 0 with zero rows, or with null fields. `connector_coverage.py` asks whether a connector *exists* for a market; `liveness.py` asks whether one *offer* is alive. Nothing asks whether the connector still works — and `trabajos_es` is the only real board, so one restyle takes sourcing to zero with no signal at all.

Two stages, in order. **Free signals** over evidence already in hand, costing no request: `company` null on every row, undecoded entities (`&amp;`) in titles, `detail_url`s not pointing at the portal's own host, zero yield from a portal that has yielded before. Then **one bounded sentinel probe** using the example query recorded in the connector's own file — at most one retry.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

**The free pass runs first and must be able to reach a verdict alone.** A health check that always costs a request will be run rarely, which is the same as not having one.

The sentinel probe is capped at one retry. This is a health check, not a crawler.

## Tests — write these RED first

`test_a_connector_whose_selectors_no_longer_match_is_reported_broken` in `tests/test_connector_health.py` — mutate the recorded fixture's markup, assert `broken`.

`test_zero_yield_from_a_portal_that_never_yielded_is_not_breakage` — an empty market is not a rotted parser.

`test_a_healthy_connector_over_its_fixture_reads_ok`.

## Location

Service: **SUPPLY** · Size: M

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T72) ·
Methods: `docs/METHODS.md`
