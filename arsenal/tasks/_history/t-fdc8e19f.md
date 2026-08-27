---
id: t-fdc8e19f
title: "T86: eligibility — a scoped citizenship / right-to-work vocabulary, with unknown terms falling to FLAG"
priority: 5
deps: [t-e6f1dc24]
workspace: MATCH
tags: [v3, m5]
status: merged
---

Imported from issue #237

Carried over from [#235](https://github.com/nuncaeslupus/integral-job-search/pull/235) (T76). The owner cleared that PR to merge with this deferred; it must land **before T77/T78/T79 wire the gate into ranking**, because until then nothing consumes `eligibility` and the defect cannot reach a candidate.

## The defect

```text
candidate: citizenships=("DE",)     advert: "must hold German citizenship"     → FAIL
candidate: citizenships=("ES",)     advert: "must hold German citizenship"     → FAIL
```

The first is a **false FAIL** — the candidate qualifies. The second is correct. `_verdict_for_requirement` compares `_normalize`d strings for equality, so `de` ≠ `germancitizenship`, and the two cases are structurally identical to the code. A false FAIL is the invisible direction: an excluded job is one the candidate never sees.

The gate reads `offers_ranked_despite_a_stated_disqualification: 0` **because** no probe pairs a target with a differing vocabulary. Correct by coincidence, not construction.

## What this is not

Not a world gazetteer. The trap is thinking the fix requires every nationality on earth and giving up because it would be incomplete. Two things bound it:

- **The candidate's side is tiny.** One person holds a handful of citizenships and work authorisations. ISO 3166-1 alpha-2 plus bloc entries (`EU`, `EEA`, `UK`, `US`) covers it.
- **The advert side is bounded by the market, not the planet.** This is a Spain-focused search: the demonyms that actually appear are a few dozen country adjectives across ES/EN/CA, plus the bloc terms — `comunitario`, `UE`, `EEE`, Schengen, "right to work in the EU".

## What makes incompleteness safe

**A term outside the table resolves to FLAG, never FAIL.** That is what stops this being "too much and incomplete work": the gap degrades to *a human decides*, which is already the task's stated preference — prefer FLAG over a confident FAIL. Completeness becomes a quality dial, not a correctness precondition.

## Scope

- Citizenship and work authorisation: **yes**, a scoped table as above.
- **Clearances: no.** TS/SCI, SC, DV, `habilitación de seguridad` are national schemes with real level hierarchies, and clearance bars are rare in this market. Keep clearance at FLAG rather than model a taxonomy. #235 already folds the bare requirement noun (`"security"` in "must hold an active security clearance") to no-target, which routes it to FLAG.

## The rule the table must obey

Derive the vocabulary from **the languages and the spec**, never from corpus misses. This is D-2's failure in a new costume, and the same rule T15 states as "do not close it by adding `huye de` to `_NEGATORS`" — choosing vocabulary by reading an evaluation-split miss is fitting to the test set.

Given that, and per `CLAUDE.md`'s rule for gates that can pass while the code is wrong, the fixtures for this belong to **a session other than the implementer**, derived from the spec before the implementation is opened.

## What closes this

- A scoped alias table for citizenship and work authorisation, ES/EN/CA.
- `_verdict_for_requirement` returns FLAG when the advert's target is outside the table, FAIL only when the target resolves and the candidate demonstrably lacks it.
- Probes and tests for: `DE` vs "German citizenship" (PASS), `ES` vs "German citizenship" (FAIL), an unrecognised nationality (FLAG), `EU` vs "right to work in the EU" (PASS), and `ES` vs "comunitario" (PASS).
- `offers_ranked_despite_a_stated_disqualification_evaluated` rises by the number of accepted cases.

## Acceptance gate

```gate
false_disqualifications == 0
evidence: status/evidence/T86.json
key: false_disqualifications
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

`status-key` carries the weight here. The denominator matters as much as the
zero: before this task every probe paired a target with a candidate spelling it
the same way, so no probe could distinguish a qualifying candidate from a
disqualified one, and a zero over that set was correct by coincidence.
`measure_false_disqualifications` reports `unmeasured` rather than a clean `0`
whenever nothing is evaluated, which is precisely the state this gate was in
before it existed.

`test_the_false_disqualification_gate_fails_on_the_pre_fix_code_path` switches
the vocabulary off and asserts the same probes then report real violations —
8 of 13. A gate that cannot fail is not measuring anything.
