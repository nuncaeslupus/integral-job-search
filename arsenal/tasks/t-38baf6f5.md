---
id: t-38baf6f5
title: "T88: The requirement patterns are English-only — a Spanish or Catalan advert states no bar at all"
priority: 5
deps: [t-fdc8e19f]
workspace: MATCH
tags: [v3, m5]
---

# T88: The requirement patterns are English-only — a Spanish or Catalan advert states no bar at all

## Acceptance gate

```gate
bars_read_as_silence == 0
evidence: status/evidence/T88.json
key: bars_read_as_silence
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

## Why

Found by the independent adversarial fixture audit on T86 (#242), findings 5–7.
They are extraction gaps, not vocabulary gaps, which is why they were split out
of that PR rather than folded into it.

**`_CITIZENSHIP_PATTERNS` and `_WORK_PERMIT_PATTERNS` are English-only.** In a
search aimed at the Spanish market, no ES or CA advert can produce a
`Requirement` at all:

| advert text | today | should be |
|---|---|---|
| `Imprescindible tener permiso de trabajo en España.` | **PASS** | FLAG or FAIL |
| `Se requiere nacionalidad española.` | **PASS** | FLAG or FAIL |
| `Imprescindible ser ciudadano comunitario.` | **PASS** | FLAG or FAIL |
| `Cal tenir permís de treball a Espanya.` | **PASS** | FLAG or FAIL |

`PASS` here means "the advert stated nothing", and the advert stated a bar. That
is fail-open on the exact axis §5.4 exists for. It also means T86's ES/CA
vocabulary — the whole point of that task — is reachable **only** through hybrid
English text, which is what its probes use (`"Applicants must be a comunitario
citizen."`). The T86 evidence record therefore reads as validation of a path no
real advert can take, and that is worth naming rather than leaving for a reader
to discover.

**A targetless bar in English is missed too** (audit finding 7). `You must hold a
valid work permit.` and `A valid work permit is required.` match no pattern, so a
stated bar naming no country reads as silence — while the targetless branch of
`_verdict_for_requirement` exists precisely to score that case.

**Overlapping patterns drag a correct PASS to FLAG** (audit finding 5, minor,
fail-closed). `German citizenship is required.` matches both the targeted and the
targetless citizenship pattern; worst-verdict-wins then takes the targetless
FLAG over the targeted PASS, so a German candidate is flagged by an advert they
plainly clear. `EU/EEA citizenship is required.` does the same.

## What it must not become

**Do not translate the English patterns literally.** `permiso de trabajo` is not
`work permit` word-for-word, and `imprescindible` carries the hardness that
`must` carries in English. Write the patterns from adverts, not from a
dictionary — the corpus has real ones.

**Widening a pattern is how a false FAIL gets made.** Every new pattern is a new
way to state a bar *and* a new way to misread a sentence that states none. T86's
audit found four function words resolving to countries; the same class reappears
here one layer up. Every pattern added must land with at least one negative probe
— a sentence it must **not** match.

**Do not fold `EU/EEA` in here.** `"EU/EEA citizenship"` normalises to `eueea`
and resolves to nothing, which is FLAG and therefore safe. Aliasing it is T86's
table, not this task's patterns, and it can go in either — but say which.

**A zero-violation count over an empty input set is not a pass.** Record
`bars_read_as_silence_evaluated` — non-English and targetless probes actually
run — and write `gate_status: "unmeasured"` with the metric at `-1` when it is
`0`. Note that `measure_false_disqualifications` **skips any probe whose text
yields no requirement**, so a probe added for this failure would be silently
dropped from that denominator rather than counted: these cases need their own
metric, which is what this gate is.

## Tests — write these RED first

`test_a_spanish_advert_stating_a_bar_is_not_read_as_silence` in
`tests/test_eligibility.py`.

`test_a_catalan_advert_stating_a_bar_is_not_read_as_silence`.

`test_a_targetless_english_work_permit_bar_is_found`.

`test_a_targeted_bar_is_not_dragged_to_flag_by_its_own_targetless_pattern`.

`test_every_new_pattern_has_a_sentence_it_must_not_match` — the negative control
for the widening above.

`test_the_gate_does_not_pass_on_an_empty_input_set` — assert
`bars_read_as_silence_evaluated` is written and non-zero.

## Location

Service: **MATCH** · Size: M

Spec: `status/spec-v3-silent-success.md` §5.1, §5.4 · Plan: `status/plan.md` (T88)
· Methods: `docs/METHODS.md`

Source: the independent fixture audit required by `CLAUDE.md` for T86, run
2026-08-27 against `arsenal/t-fdc8e19f`. Findings 1–4 of that audit were fixed in
#242; 5–7 are these.
