# Session handover

**2026-09-05 into 2026-09-06.** Board: **173 tasks** — 25 open, 145 merged,
2 cancelled, 1 done. `origin/main` at `79a1f23`. Five PRs merged (#349, #350,
#353, #354, #357, #359); #343 and #345 closed by them, #344 closed
not-planned by the owner's decision.

The session set out to make a live Spanish candidate session possible. It
ended having found that the thing blocking every remaining connector is not a
connector problem at all.

## 1. The connector gap is a language gap — #358

This is the finding that reframes the rest, and it corrects work done earlier
in the same session.

`connectors/wanted.yaml` was written ranking fourteen boards by country
coverage. Twelve were then surveyed end to end — robots checked with the
repo's own matcher, then an anonymous GET for readability. `net-empregos.com`
cleared robots, mapped every field, decoded 121 KB of ISO-8859-1 cleanly
once T128 landed, and the package still would not load:

```
ConnectorError: locale: Input should be 'en', 'es' or 'ca'
```

**Not one of the fourteen can be connected.** Not for robots, not for markup,
not for either engine gap filed this session — because the language does not
exist in the type.

What a language pack costs, measured on `79a1f23`:

| | count |
|---|---|
| declarations of the language set | **3** — `corpus.LANGUAGES:19`, `dimensions.Language:45`, `identity.Language:78` |
| dimension files carrying cues | 37 of 41 |
| cue phrases per language | en 105, es 110, ca 109 |
| catalogue entries needing a translation | 24, each carrying `of` — the sha256 of the English it came from |
| corpus ads in the new language | **0** (today: ca 90, es 93, en 25) |

The bootstrap problem is worth naming before anyone starts: a language needs a
corpus, and the corpus is drawn through connectors for that language, of which
there are none. That circularity is the actual work, not the 41 files.

**A trap directly in that path.** Only two of the three declarations are tied
together — `test_dimension_model.py:243` asserts
`set(get_args(Language)) == set(LANGUAGES)`. `identity.Language` is spelled
independently and nothing compares it to either. It validates
`Identity.language`, the field in every candidate's `identity.json`. Adding a
language to the other two would leave identity refusing it, and no test says so.

Both yaml files now open with a `READ THIS FIRST` block saying the ranking
measures the wrong thing.

## 2. The rot check was comparing a page with itself — #353 (T127)

`assess_package` compares a connector's fixture against its probe. That is
meaningful only if the two carry different offers. **2 of 18 packages had
probes that were re-captures of the fixture** — `ticjob_es` and
`getmanfred_es` — so the check ran, passed, and measured nothing.

One of the two was byte-*different* from its fixture while carrying the same
three offers, so no byte comparison could ever have caught it. The metric is
now reference overlap, and it refuses a zero denominator: a side that parses
to nothing reports `parsed no offers`, never 100% overlap.

`getmanfred_es/meta.yaml` had carried an argument that the near-equality was
"a fact about the three offers kept, not about the capture" and "the healthy
reading rather than a weak one". That was wrong and is retracted in the file.

Both probes re-captured live 2026-09-06; 0 of 3 overlap each.

## 3. Connectors can declare a charset — #359 (T128)

Every fetch assumed UTF-8. `decode_body` now honours a declared charset, with
a BOM winning over the declaration, and **decodes strictly** — never
`errors="replace"`, which would turn an encoding bug into plausible mojibake
that no gate can see.

`iso-8859-1` and `us-ascii` map to **cp1252**, per WHATWG Encoding §4.2: they
are labels *of* windows-1252, not Latin-1. The difference is bytes 0x80–0x9F.

Two things about how it was verified, because neither is the usual claim:

- CLAUDE.md requires a **second session** to write fixtures for anything
  comparing two encodings of the same thing. None was available. The 13-case
  table was derived from the standards text before any code, each contract
  citing its clause — which breaks the circularity but **is not the second
  reader**. Said on the PR and in the merge commit rather than claimed as
  compliant.
- Mutation round 1 scored **5 of 7**. Deleting the `REPLACEMENT_LABELS` guard
  left the gate green: those labels were still refused, via the unknown-label
  path. The contract asked "did it raise" and got a yes over a deleted check.
  It now reads the refusal's *reason*. 7 of 7 after.

## 4. The corpus cannot be excerpted — #344, closed not-planned

`tools/excerpt_corpus.py` was written, run, and **deliberately not committed**.
Four independent mechanisms anchor a corpus row to its exact bytes: offsets in
`corpus/labelled`, verbatim gold spans in `dimensions/*.yaml`, raw/labelled
body equality that nothing gates, and "some advert must exercise each recovery
route". Cutting it moved **six** measurements, **five of them silently**.

Owner's decision: keep it whole and publish it — 208 ads, 485,074 chars, with
`source_url` on every row. A copy of the discarded tool is in the session
scratchpad only.

## 5. Corrections to this repo's own record

- **CLAUDE.md's "Known environment state" was stale** (#354). Re-measured
  2026-09-05 22:31 UTC: five runs, 3–6 seconds each, every job failed. Actions
  has no minutes. The section keeps the clock test, points at
  `tools/verified_gate.sh`, and now records that it has been wrong twice — which
  is the section's own point about snapshots.
- `cv-library.co.uk` answered 200 and then 403 four minutes later to an
  identical request. Recorded in `ruled-out.yaml` as an inconsistency, not as
  either verdict.
- 18 stale worktrees and 65 claim refs cleared. Only the main checkout remains.

## 6. Standing authority granted this session

The owner granted **standing merge authority**: any PR green on
`tools/verified_gate.sh` may be merged, with the verdict block on the PR and
the four results quoted in the merge commit. He was offered an "except risky
diffs" carve-out and **explicitly declined it**. Do not re-ask.

## 7. Open

| | |
|---|---|
| **#358** | the language gap — highest value, upstream of every remaining connector, and needs an owner decision on which language and how to bootstrap its corpus |
| **#356** | a selector cannot take part of a text node — real, but no longer the binding constraint for DE |
| **#352** | CI path guard for contribution PRs — blocked on the repo being public |
| — | `T89.ledger_entries_scanned` is committed as an exact value and grows with every ledger row; it wants T100's floor treatment |
| — | **Ivan's live Spanish candidate session, still unstarted.** T124 gave step 7 its aim and T126 gave it a real fetcher, so it is now genuinely possible for the first time. |
