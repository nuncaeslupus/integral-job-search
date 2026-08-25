---
id: t-52bb1ec0
title: "T73: A rate-limited run is inconclusive, never broken"
priority: 10
deps: [t-37cfb89e]
workspace: SUPPLY
tags: [v3]
---

# T73: A rate-limited run is inconclusive, never broken

## Acceptance gate

```gate
rate_limited_runs_reported_as_broken == 0
evidence: status/evidence/T73.json
```

```bash
uv run --extra dev pytest tests/test_connector_health.py -q
uv run --extra dev python -m integral.connector_health
```

The `bash` block regenerates `status/evidence/T73.json`; the `gate` block asserts the
number in it.

## Why

The converse of T72, and it is not a rounding error. **A 429 or a block page is never evidence of breakage** — it is evidence we were not allowed to look. Reporting it as `broken` would retire a working connector on the strength of our own rate limiting, and the third verdict `inconclusive (rate-limited)` is what prevents that.

This is the same three-valued shape as `liveness`'s `unverified` and the gate layer's `unmeasured`: *I could not tell* is a distinct answer from *no*.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

Both directions must hold or the check becomes noise and gets ignored — a health check that cries wolf is switched off, and then the silent rot it existed to catch returns.

**Disabling is offered, never automatic**, and it flips one connector's `enabled` flag and nothing else.

## Tests — write these RED first

`test_a_429_is_inconclusive_not_broken` in `tests/test_connector_health.py`.

`test_a_block_page_is_inconclusive` — a challenge page is not a parse failure.

`test_disabling_a_connector_requires_confirmation` — and touches exactly one connector.

## Location

Service: **SUPPLY** · Size: S

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T73) ·
Methods: `docs/METHODS.md`
