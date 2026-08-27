---
id: t-38baf6f5
title: "T88: Language parity — every supported language must be detected the same, for countries and for languages alike"
priority: 5
deps: [t-fdc8e19f]
workspace: MATCH
tags: [v3, m5]
---

# T88: Language parity — every supported language must be detected the same, for countries and for languages alike

## Acceptance gate

```gate
cross_language_verdict_disagreements == 0
evidence: status/evidence/T88.json
key: cross_language_verdict_disagreements
status-key: gate_status
```

```bash
uv run --extra dev pytest tests/test_eligibility.py -q
uv run --extra dev python -m integral.eligibility
```

`src/integral/eligibility.py` must write `status/evidence/T88.json`. It already
writes `T76.json`, `T77.json`, `T78.json` and `T86.json`; add this record beside
them rather than replacing one, so every gate keeps reading. **A gate must never
name a file no module produces.**

The `bash` block regenerates it; the `gate` block asserts the number in it.

## The requirement

**Every language this search supports behaves the same.** Not "English works and
the others are best-effort" — the same advert, stated in ES, EN or CA, reaches
the same verdict, and the same fact about the candidate is recognised however it
is spelled. That holds for what is being detected as much as for the language it
is written in: countries, blocs, and languages themselves.

The gate is that parity, measured directly: state each case in every supported
language, spell each candidate holding every supported way, and **the verdicts
must agree**. A disagreement is the violation. That is a stronger claim than "the
Spanish patterns exist", and it cannot be satisfied by adding one language's
patterns and leaving the next reader to check the rest.

## Why — three measured failures

Found by the independent adversarial fixture audit on T86 (#242, findings 5–7)
and by the language probe run alongside it. All are measured on
`arsenal/t-fdc8e19f`, not inferred.

### 1. A language is matched only by spelling — the largest hole

`language` was never added to `_TABLE_KINDS`, so `_verdict_for_requirement`
compares it with a bare `_normalize` equality against what the candidate holds.
No vocabulary, no folding, no codes:

| role requires | candidate holds | today | should be |
|---|---|---|---|
| `Spanish` | `("es",)` | **FAIL** | PASS |
| `español` | `("es",)` | **FAIL** | PASS |
| `castellano` | `("es",)` | **FAIL** | PASS |
| `es` | `("spanish",)` | **FAIL** | PASS |
| `català` | `("ca",)` | **FAIL** | PASS |
| `es` | `("es",)` | PASS | PASS |

Only byte-identical spellings pass. A profile stores codes and an advert writes
words, so in ordinary use **the two sides never agree** — and every disagreement
is a hard FAIL, which removes the offer from the ranking entirely. A candidate
who speaks Spanish is disqualified from Spanish-speaking roles. This is the same
defect T86 fixed for countries, one field over, and the fix is the same shape: a
scoped language vocabulary, `language` in `_TABLE_KINDS`, unresolved terms
resolving to FLAG rather than FAIL.

### 2. `_CITIZENSHIP_PATTERNS` / `_WORK_PERMIT_PATTERNS` are English-only

In a search aimed at the Spanish market, no ES or CA advert produces a
`Requirement` at all:

| advert text | today | should be |
|---|---|---|
| `Imprescindible tener permiso de trabajo en España.` | **PASS** | FLAG or FAIL |
| `Se requiere nacionalidad española.` | **PASS** | FLAG or FAIL |
| `Imprescindible ser ciudadano comunitario.` | **PASS** | FLAG or FAIL |
| `Cal tenir permís de treball a Espanya.` | **PASS** | FLAG or FAIL |

`PASS` means "the advert stated nothing", and the advert stated a bar. Fail-open
on the exact axis §5.4 exists for. It also means T86's ES/CA vocabulary is
exercised **only** through hybrid English text — which is what its probes use
(`"Applicants must be a comunitario citizen."`) — so that evidence record reads
as validation of a path no real advert can take.

A targetless English bar is missed the same way: `You must hold a valid work
permit.` and `A valid work permit is required.` match no pattern, so a stated bar
naming no country reads as silence — while the targetless branch of
`_verdict_for_requirement` exists precisely to score it.

### 3. A targetless pattern drags its own targeted PASS to FLAG

`German citizenship is required.` matches both the targeted and the targetless
citizenship pattern; worst-verdict-wins then takes the targetless FLAG over the
targeted PASS, so a German candidate is flagged by an advert they plainly clear.
`EU/EEA citizenship is required.` does the same. Minor and fail-closed, but it is
the same sentence read twice and answered twice.

## What it must not become

**Do not translate the English patterns literally.** `permiso de trabajo` is not
`work permit` word-for-word, and `imprescindible` carries the hardness `must`
carries in English. Write the patterns from adverts, not from a dictionary — the
corpus has real ones.

**Widening a pattern is how a false FAIL gets made.** Every new pattern is a new
way to state a bar *and* a new way to misread a sentence that states none. T86's
audit found four function words resolving to countries — `at` in "for **at**
least twelve months" disqualified a candidate over Austria — and the same class
reappears here one layer up, in three languages instead of one. Every pattern
added lands with at least one negative probe: a sentence it must **not** match.

**The language vocabulary is scoped, and unresolved is FLAG.** Same rule T86
settled for countries: a term outside the table resolves to `None`, and `None`
routes to FLAG, never FAIL. A gate that cannot recognise a language has not
learned the candidate lacks it.

**Do not fold `EU/EEA` in here.** `"EU/EEA citizenship"` normalises to `eueea`
and resolves to nothing, which is FLAG and therefore safe. Aliasing it belongs to
T86's table, not to these patterns — it may go in either, but say which.

**A zero-violation count over an empty input set is not a pass.** Record
`cross_language_verdict_disagreements_evaluated` — parity groups actually
compared — and write `gate_status: "unmeasured"` with the metric at `-1` when it
is `0`. Note that `measure_false_disqualifications` **skips any probe whose text
yields no requirement**, so a probe added for failure 2 would be silently dropped
from that denominator rather than counted: these cases need their own metric,
which is what this gate is.

## Tests — write these RED first

`test_a_language_is_recognised_under_every_supported_spelling` in
`tests/test_eligibility.py` — the table in failure 1, asserted.

`test_an_unknown_language_flags_rather_than_fails`.

`test_a_spanish_advert_stating_a_bar_is_not_read_as_silence`.

`test_a_catalan_advert_stating_a_bar_is_not_read_as_silence`.

`test_the_same_bar_in_three_languages_reaches_the_same_verdict` — parity itself,
which is the gate.

`test_a_targetless_english_work_permit_bar_is_found`.

`test_a_targeted_bar_is_not_dragged_to_flag_by_its_own_targetless_pattern`.

`test_every_new_pattern_has_a_sentence_it_must_not_match` — the negative control
for the widening above.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert
`cross_language_verdict_disagreements_evaluated` is written and non-zero.

## Location

Service: **MATCH** · Size: M

Spec: `status/spec-v3-silent-success.md` §5.1, §5.3, §5.4 · Plan: `status/plan.md`
(T88) · Methods: `docs/METHODS.md`

Source: the independent fixture audit `CLAUDE.md` requires for T86, run
2026-08-27 against `arsenal/t-fdc8e19f`. Findings 1–4 of that audit were fixed in
PR 242; findings 5–7 are failures 2 and 3 here. Failure 1 was measured in the
same session and is the largest of the three.
