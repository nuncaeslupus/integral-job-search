---
id: lo-1af2
title: "T25: [LAPTOP] Broaden the corpus beyond remote programming — >=6 job families, >=15 ads each"
priority: 70
workspace: ONTOLOGY
tags: [laptop, m4]
requires: [surface:egress]
status: merged
pr: https://github.com/nuncaeslupus/job-search/pull/131
---

## Acceptance gate

```gate
corpus_job_family_count >= 6
evidence: status/evidence/T25.json
key: corpus_job_family_count
```

```bash
uv run --extra dev pytest tests/test_corpus_families.py -q
uv run --extra dev python -m integral.corpus
```

## What this is

v0's corpus is 100 remote programming ads, and v0's dimensions were written from
them. The model is meant to serve everyone, and the vocabulary of other job
families is not guessable — PR #8's review showed what happens when cues are
written from imagined phrasing rather than observed.

≥6 job families, ≥15 ads each, in the same three languages, with the same rules
as T4b: real ads, verbatim text, resolvable source URL, nothing synthetic or
translated. Families should be genuinely different in how they are advertised —
e.g. trades, hospitality, healthcare, administrative, retail, teaching — not six
flavours of office work, or the exercise proves nothing about breadth.

Add a `job_family` field to the raw ad schema (additive; existing ads become
`programming`).

## Tests

`test_corpus_covers_at_least_six_job_families` in `tests/test_corpus_families.py`
— no family below 15 ads; `test_every_ad_declares_a_job_family` — an ad without
one is refused at load, as with `source_url`.

## Laptop-only

Needs egress to job boards, which the cloud session's policy denies (403 at the
proxy). Tagged `laptop`; `release.sh` refuses `done` from a cloud session.

## Location

Service: **ONTOLOGY** · Size: L · Depends: —

`tools/collect_ads.py`, `corpus/raw/`. Design: `status/plan.md` (Scope extension §1)
