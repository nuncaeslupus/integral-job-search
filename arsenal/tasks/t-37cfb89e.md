---
id: t-37cfb89e
title: "T72: Connector health — detect a silently rotted parser"
priority: 5
deps: []
workspace: SUPPLY
tags: [v3, m5]
---

# T72: Connector health — detect a silently rotted parser

## Acceptance gate

```gate
silent_connector_failures == 0
evidence: status/evidence/T72.json
key: silent_connector_failures
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_connector_health.py -q
uv run --extra dev python -m integral.connector_health
```

`src/integral/connector_health.py` must write `status/evidence/T72.json`. This is a new module, so it owns this record outright. **A gate must never name a file no module produces** — the file not existing yet is the honest state of an unstarted task; the file existing but empty of this metric is not.

The `bash` block regenerates it; the `gate` block asserts the number in it.

## Why

Scrapers rot silently: when a portal changes its markup, a CSS-selector connector exits 0 with zero rows, or with null fields. `connector_coverage.py` asks whether a connector *exists* for a market; `liveness.py` asks whether one *offer* is alive. Nothing asks whether the connector still works — and `trabajos_es` is the only real board, so one restyle takes sourcing to zero with no signal at all.

Two stages, in order. **Free signals** over evidence already in hand, costing no request: `company` null on every row, undecoded entities (`&amp;`) in titles, `detail_url`s not pointing at the portal's own host, zero yield from a portal that has yielded before. Then **one bounded sentinel probe** using the example query recorded in the connector's own file — at most one retry.

Adapted from `MadsLorentzen/ai-job-search` (MIT, © 2026 Mads Lorentzen). **T83 records the attribution** — do not add a credit line here; it belongs in `README.md` and `docs/METHODS.md`, in one place, once.

## What it must not become

**The free pass runs first and must be able to reach a verdict alone.** A health check that always costs a request will be run rarely, which is the same as not having one.

The sentinel probe is capped at one retry. This is a health check, not a crawler.

**A zero-violation count over an empty input set is not a pass.** The gate counts
violations, and nothing counted is also zero — so the evidence record must carry
`silent_connector_failures_evaluated` (connectors checked) and the gate is only meaningful while that count is
non-zero. This is the failure this whole increment is about, turned on its own gates:
a check that reports success over work it did not do. Assert the denominator.

## Tests — write these RED first

`test_a_connector_whose_selectors_no_longer_match_is_reported_broken` in `tests/test_connector_health.py` — mutate the recorded fixture's markup, assert `broken`.

`test_zero_yield_from_a_portal_that_never_yielded_is_not_breakage` — an empty market is not a rotted parser.

`test_a_healthy_connector_over_its_fixture_reads_ok`.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert `silent_connector_failures_evaluated` is written and non-zero.

## Location

Service: **SUPPLY** · Size: M

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (T72) ·
Methods: `docs/METHODS.md`

## Why this is still open — 2026-08-26

The module landed; the *measurement* did not. `default_fetch` read the same
`fixture/list.html` that `assess` uses as `baseline_html`, so the production
path compared a string with itself: the regression branch was unreachable,
`silent_connector_failures` could only ever be 0, and the evidence recorded
`"gate_status": "measured"` on a check whose whole purpose is detecting
parser rot.

The probe now reads `probe/list.html` — a separately captured current read,
written by the permitted `[LAPTOP]` process — and there is none in this
repository, so `gate_status` is `unmeasured` and `gate_evidence.py` exits 3.
Not a pass and not a fail.

**What finishes this task:** capture `connectors/trabajos_es/probe/list.html`
on the laptop, where egress is permitted (the same surface T12 needs), and
re-run `python -m integral.connector_health`. Nothing in the module changes.
Until then `connector_runs_probed` is 0 and the number is a lower bound over
the free signals alone.

## A zero count must prove the mechanism ran — 2026-08-26

This gate asserts a **violation count of zero**, and an empty input set produces
zero too. As written it could pass without evaluating a single offer, verdict,
ranked result, document, keyword, application or technique — which is *precisely*
the failure class this increment exists to catch, reproduced inside its own
acceptance criteria.

The gate block therefore carries `status-key: gate_status`, and the producing
module must honour it:

* record **``connector_runs_evaluated``** — how many inputs were actually evaluated — in the evidence
  file, beside the violation count, and **``connector_runs_probed``** beside it;
* write **`gate_status: "measured"`** only when `connector_runs_evaluated` is
  non-zero **and every evaluated connector was probed**; write
  **`"unmeasured"`** otherwise — which covers both an empty input set and a
  probe that is missing or incomplete.

  The probe coverage half is not a refinement of the emptiness rule, it is the
  same rule one level down: a connector evaluated without a current read had its
  rot stage skipped, so counting it as measured claims a check that did not run.

* a violation the free signals **did** find is a measured failure and outranks
  any missing probe. `_main` therefore reports it before it considers
  `unmeasured`, because `make evidence` accepts exit 3 and walks past it — so
  reporting a real finding as "cannot be scored yet" is how this module would
  fail silently at the one job it exists to do.

`gate_evidence.py` reads `status-key` before it reads the metric and exits **3** on
`unmeasured` — "the check ran, and what it found is that this cannot be scored
yet". Not a pass and not a fail. That is the same mechanism `lo-6f53` uses for
`extraction_macro_f1`, so this is existing machinery rather than a new rule.

Exit 3 covers **two** runs, and only the first is an empty input set:

* nothing was evaluated at all;
* something was evaluated but its **rot stage did not run**, because no current
  read was captured for it. Such a connector is not idle — its baseline was
  parsed and its free signals were checked in full — so "a run that processed
  nothing" describes only half of what reaches this exit, and describing it that
  way was how the incomplete-coverage case looked like a non-case.

Neither of those is a run that found something. A violation the free signals did
find never reaches exit 3 at all; it is reported first, as a measured failure.

**A second assertion in the gate block would not have worked**: line 1 of a `gate`
fence *is* the gate, one metric per block. Making the emptiness visible through the
status key is what makes the invariant executable rather than prose.
