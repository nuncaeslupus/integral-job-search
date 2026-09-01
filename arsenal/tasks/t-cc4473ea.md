---
id: t-cc4473ea
title: "D-23: Gate accuracy over real adverts is unmeasured — no corpus labels exist"
priority: 5
deps: [t-e6f1dc24]
requires: [surface:human]
workspace: MATCH
tags: [v3, m5]
---

# D-23: Gate accuracy over real adverts is unmeasured — no corpus labels exist

## Where the labelled adverts may not come from

The live session of 2026-08-29/30 harvested roughly **2,755 adverts** across four
rounds, and landing them here would look like the cheapest possible unblock.

**They are the wrong sample, and the owner ruled so on 2026-09-01.** Those rows
are the shape of one person's queries, exclusions and language mix. An accuracy
figure computed over them describes the gate's behaviour for that person, and it
would be quoted as the gate's accuracy. This has to stay a generic tool.

The connector library, which did not exist when this divergence was filed, is the
replacement: a corpus drawn **by specification** — job families, languages,
regions — with no candidate in the loop, and redrawable, which a one-off harvest
never is. It can also be enriched for the four labels this task actually needs
(permit, citizenship, clearance, role-language) where a harvest contains whatever
it happens to contain. One measurement from the session says the enrichment is
worth doing: 117 of 213 USD adverts carrying a band were US/Canada-restricted.

The draw mechanism and the provenance rule are **T98**; this task consumes them
and labels. Neither may read a row whose provenance is a candidate session.

## Acceptance gate

```gate
unlabelled_gate_accuracy_claims == 0
evidence: status/evidence/D-23.json
key: unlabelled_gate_accuracy_claims
```

```bash
uv run --extra dev pytest tests/test_spec_consistency.py -q
uv run --extra dev python -m integral.spec_consistency
```

`src/integral/spec_consistency.py` must write `status/evidence/D-23.json`. It already writes `status/evidence/D3.json` for another task — add this record beside it rather than replacing it, so both gates keep reading. **A gate must never name a file no module produces** — the file not existing yet is the honest state of an unstarted task; the file existing but empty of this metric is not.

The `bash` block regenerates it; the `gate` block asserts the number in it.

**Wire the writer into `_main`, not only into the module.** Today
`spec_consistency._main` writes `D3.json` and `T61.json`; a `write_evidence` for
D-23 that `_main` does not call leaves the `bash` block above running a command
that never touches the file the `gate` block names — the acceptance would pass
against a stale or absent file, which is this increment's own failure class. `make
evidence` discovers modules by `^def _main` and runs each with no arguments, so a
record only reachable through a flag is a record the drift check never regenerates.

## Why

The eligibility and language gates (T76–T79) are gated on **mechanism** over hand-built fixtures and never on **accuracy** over real adverts. No corpus labels exist for permit, citizenship, clearance or role-language requirements, so a gate that fires wrongly on a Spanish advert passes every check in this increment.

Filed on the owner's decision, 2026-08-25, following the **D-12 precedent**: the mechanism ships now, the accuracy waits behind a corpus round. The current labelling round does not grow to absorb it.

This row's own gate is what keeps the gap honest: no document — specification, plan, docstring or skill file — may claim the gate is accurate on real adverts while that is unmeasured.

## What it must not become

**This task is blocked on human labelling** (`requires: [surface:human]`) and must not be picked up by an autonomous round. It is filed so the gap is named, not so it is worked.

Do not resolve it by weakening the claim in one document and leaving another. The check is over every document, which is why it lives in `spec_consistency`.

**A zero-violation count over an empty input set is not a pass.** The gate counts
violations, and nothing counted is also zero — so the evidence record must carry
`unlabelled_gate_accuracy_claims_evaluated` (documents scanned for an accuracy claim) and the gate is only meaningful while that count is
non-zero. This is the failure this whole increment is about, turned on its own gates:
a check that reports success over work it did not do. Assert the denominator.

## Tests — write these RED first

`test_no_document_claims_the_eligibility_gate_is_accurate_on_real_adverts` in `tests/test_spec_consistency.py`.

`test_the_gate_reports_its_accuracy_as_unmeasured`.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert `unlabelled_gate_accuracy_claims_evaluated` is written and non-zero.

## Location

Service: **MATCH** · Size: M

Spec: `status/spec-v3-silent-success.md` · Plan: `status/plan.md` (D-23) ·
Methods: `docs/METHODS.md`
