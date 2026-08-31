# Session handover — 2026-08-30 ~23:55 UTC, interactive, laptop

Board: **116 gates on `main`** (`eb4e9a0`). `make host-gate` exit 0: ruff clean,
strict mypy over 172 files, 1878 tests, `evidence: no drift`,
`verify-gates: 116 terminal task(s); 116 gate(s) asserted, 0 carry no fenced
gate block`.

This was a **live candidate session** — a real person, in Spanish, looking for
Python work in Barcelona — with the owner stepping out of character to direct
connector work. Everything below came out of that: the library grew because the
search kept failing for reasons the candidate could name.

## What landed

**[#259](https://github.com/nuncaeslupus/integral-job-search/pull/259) —
connectors can read JSON, and eleven new packages.** Merged.

`integral.connectors` gained a `from_json` block, alternative to `item`/`fields`
and never alongside it: an optional `embedded_in` selector naming the element
whose text is the document (omit it and the response body *is* JSON), a `match`
that picks the right document when a page serves several, `items` for the list
page's array, and one dotted path per field. The path grammar is as small as
the selector grammar — dotted keys, no indices, no wildcards, no filters, plus
the literal `$` for a document that is itself the array. `json.loads` is the
only parser and nothing is evaluated.

The reason it was worth building is `Salary`. `build_offer` turns any salary key
into `Salary(stated=True)`, and **six** HTML connectors here leave salary
deliberately unmapped because their board prints it as one unsplittable string.
A JSON number needs no splitting. `dig` is written to match: a path landing on
an object or an array counts as *no value*, never `str({...})`.

Eleven packages shipped with it: `arbeitnow_en`, `builtin_en`, `infojobs_es`,
`jobfluent_es`, `jobsacuk_en`, `pythonorg_en`, `remotive_en`, `tecnoempleo_es`,
`ticjob_es`, `wellfound_en`, `weworkremotely_en`. The library was two packages
before today.

Two smaller changes rode along, both forced by the above:

- `connector_health.free_signals` now asks whether a field the connector
  **declared** came back empty. justjoin.it's listing is an index of URLs, so
  "company is null on every row" marked it broken on the day it was written.
- T55's old-name sweep exempts `connectors/*/fixture/` and `connectors/*/probe/`.
  Remotive serves a stylesheet and a blog tag whose own URLs happen to contain
  this repository's former name; editing a capture so it stops saying so would
  falsify what the fixture proves. (Quoting those two URLs here would trip the
  same sweep on this file, which is the exemption's argument in miniature.)

## What is open

**[#260](https://github.com/nuncaeslupus/integral-job-search/pull/260) — four
JSON-reading packages. Draft, and the draft is the point.**

`himalayas_en`, `justjoin_en`, `nofluffjobs_en`, `workingnomads_en`. All four
pass `check_package` with no violations. They are not merged because
`connector_health`'s gate reads `measured` only when **every** connector has a
probe, and a probe is the *second* capture of the same query taken on a **later
day**. A package written today cannot carry one, so merging it parks T72's gate
and `verify_gates` then reports T72 as a merged task that cannot show its
measurement.

**To finish it: capture the four probes, `make evidence`, mark ready.** Nothing
else about the branch should need to change.

### Owed first — an independent adversarial pass on `dig` / `compile_path`

CLAUDE.md requires fixtures for a correctness-critical gate to be written by a
session **other than the implementer**, and a JSON path resolver is exactly the
parser family that rule names. #259 was safe to merge without it because no
connector on that branch used `from_json`. **The four on #260 do**, so the audit
blocks that branch, not the engine.

The argument for it was already made once, on #259: review found that
`_json_documents` read embedded documents through `Node.text_content()`, which
collapses runs of whitespace *inside* JSON string values — silently reflowing
every advert body the route parsed, and shifting every extraction offset past
the first collapsed run. `Node.raw_text()` fixes it. That was a fail-open bug
behind a green gate, found by a second reader, which is the whole thesis.

Whoever does it should read schema.org's `JobPosting` and the module docstring
**first**, derive cases from that text before opening the implementation, and
weight fail-open over fail-closed.

## What the candidate session learned, since it drove all of the above

Ivan Marcos — Barcelona, Python, laid off from Flanks in May. Constraints
recorded across `ev-000003`…`ev-000050`. Four searches ran, each narrowed by
what the previous one surfaced:

1. **Spain, 535 adverts.** 78 survivors. Only 2 published a salary.
2. **Foreign boards, 875.** 29 survivors, 15 opened, **1** reachable. Of the 15,
   four said contractor/B2B outright and one said full-time — the pay premium
   abroad is mostly denominated in *autónomo*, which he refuses.
3. **"Agentic Python", 1005.** He named the shape himself, and added the rule
   that governs everything after: **an advert with no salary, and no cheap way
   to approximate one, is not shown.** It removed 13 of 17 survivors.
4. **JSON sources + US, 2755.** 28 survivors, 9 priced.

Measured, not asserted, over everything harvested: **USD adverts carrying a
band, median $125,000–$160,000, and 117 of 213 are US/Canada-restricted.**
EUR: 4 adverts, median €61,654–€94,205. He was right that the US pays more, and
the constraint that bites is payroll, not pay.

Two filter defects found by reading results rather than code: a gambling veto
that misses slot-machine firms because their adverts never say "casino", and a
`deel` entry in the cárnica name list that was filtering out **Deel's own**
Analytics Engineer post — a payroll platform is not a body shop, and that post
is one of very few foreign roles saying *Spain*, *Full-time* and a figure.

## Ready for the next session

`arsenal/tasks/` untouched; no task was claimed and none released. The
connector work above was not a queued task and did not pretend to be one — if it
should become one, seed it from #260 rather than from this file.
