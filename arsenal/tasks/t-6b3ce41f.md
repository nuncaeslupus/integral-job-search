---
id: t-6b3ce41f
title: "T106: Ship a US rule set, and make every tax figure name the authority it came from"
priority: 5
deps: []
# The task's own instruction is "prefer primary sources and nothing else: the
# IRS revenue procedure that sets the year's brackets and standard deduction,
# and the SSA announcement that sets the OASDI wage base and rates." Both are
# unreachable from a cloud session — measured 2026-09-04, `irs.gov` and
# `ssa.gov` each answer `CONNECT tunnel failed, response 403` to curl and
# `EGRESS_BLOCKED` to the fetch tool.
#
# That is not an inconvenience to work around, it is the task. Writing US
# figures from memory and citing a revenue procedure with a `read_on` date
# would fabricate exactly the provenance this task exists to create — an
# unauditable number wearing a citation is strictly worse than `ES.json`'s
# honest paragraph, because it looks checked. The same objection applies to
# backfilling ES and DE: a locator nobody fetched is invented.
#
# Same declaration and same reason as T25 (`lo-1af2`), which needs egress to
# job boards. `/continue EGRESS` on a surface that has it is how this is
# reached.
requires: [surface:egress]
workspace: BACKEND
tags: [m4]
---

## Acceptance gate

```gate
unsourced_tax_figures == 0
evidence: status/evidence/T106.json
key: unsourced_tax_figures
```

```bash
uv run --extra dev pytest tests/test_tax_provenance.py -q
uv run python -m integral.tax_provenance
```

## Why this exists

`taxes/` ships `ES.json` and `DE.json`. Both are `source: generated`,
`checked_on: null`, and both were "assembled from published public summaries"
— blog posts and aggregator sites, named in prose inside a single `notes`
string. `pay.py`'s own docstring is honest about it: *"No rule set shipped in
this repository is `verified` yet."*

Two things follow, and this task is both of them.

**1. There is no US rule set at all.** A candidate weighing a US offer against
a European one gets `load_or_generate_rules` inventing one at run time from
`default_generator`, which the module itself calls "stdlib arithmetic behind a
loudly-labelled placeholder". The comparison that misleads is exactly the one
T33 exists to stop.

**2. `notes` is prose, so nothing checks it.** `probe_pay` verifies the
*marking* — that a generated rule set cannot pass as verified — and that is a
real property, honestly measured. It does not, and cannot, check that any
figure in a shipped file traces to anything. `ES.json`'s 6.35% and
`DE.json`'s 19.3% are asserted by a paragraph. A rate that silently became
last year's, or a cap that was mistyped, would clear every gate in the repo.

## What "verify it" means here, and what it does not

The owner's instruction was *generate it and verify it*. That is **not** a
licence to write `source: verified` into the file. `probe_pay`'s shipped-file
loop refuses that outright, and it is right to:

> `verified` is a claim about a person having done the work, and nothing else
> may wear it.

That refusal stays. What this task adds is the layer underneath it, which is
missing: **per-figure provenance.** Every number in a rule set names the
authority it came from and the date that authority was read, so that when a
person does eventually sign one off, they are checking a citation rather than
re-deriving the whole file — and so that a wrong figure is a *findable* wrong
figure rather than a paragraph nobody can audit.

For the US, prefer primary sources and nothing else: the IRS revenue
procedure that sets the year's brackets and standard deduction, and the SSA
announcement that sets the OASDI wage base and rates. A blog restating them is
what `ES.json` already did and is what this task is correcting.

## Scope

- A `citations` structure on the rule-set schema — one entry per figure, each
  naming the figure it covers, the issuing authority, a locator, and the date
  it was read. `notes` stays for the simplifications; it stops being where the
  evidence lives.
- `taxes/US.json`, currency USD, `source: generated`, `checked_on: null`,
  fully cited. US federal income tax is filing-status dependent and the module
  models a single filer (`DE.json` already does this for Steuerklasse I) — say
  so in `notes` rather than averaging it away. State income tax is **out of
  scope**: `region` exists for it, and a US file with no region must not read
  as though it covered California. Name that in `OUT_OF_SCOPE_NOTE`'s reach or
  in `notes`, explicitly.
- Backfill citations for `ES.json` and `DE.json`. Where the only source is an
  aggregator blog, the honest entry says so — an entry marked as a secondary
  source is worth having; a missing entry is not.
- `integral.tax_provenance` writes `status/evidence/T106.json`:
  `unsourced_tax_figures`, `unsourced_tax_figures_evaluated` (the denominator:
  every figure across every shipped rule set), and `gate_status`.

## Denominators

A clean zero over an empty scan is the failure this repository keeps finding.
`unsourced_tax_figures == 0` is worthless if the walk found no figures, so the
denominator is counted and reported, and the module asserts a floor below
which it reports `unmeasured` rather than a pass — `naming.MINIMUM_SCANNED` is
the pattern, and T100 is the precedent for a floor rather than a count of the
day.

The bands are a list, so the count grows when a country is added: a floor, not
an equality.

## Tests

Write these RED before any production code:

- `test_every_shipped_rule_set_cites_every_figure` in
  `tests/test_tax_provenance.py` — the walk covers `taxes/*.json`, and a
  fixture rule set with an uncited rate is counted, not skipped.
- `test_an_empty_taxes_dir_reports_unmeasured` — the anti-vacuity case.
- `test_us_rules_load_and_produce_an_approximate_estimate` in
  `tests/test_pay.py` — `estimate_net_monthly(..., "US")` reads the committed
  file, and `.approximate` is still `True`, because `source` is still
  `generated`.
- `test_a_shipped_rule_set_still_may_not_claim_verified` — `probe_pay`'s
  existing refusal, re-asserted over the new file. Adding citations must not
  become a back door to the `verified` label.

## Location

Service: **BACKEND** · Size: M

Design: `status/plan.md` (T106) · Methods: `docs/METHODS.md#45-net-from-gross-pay-estimation`
