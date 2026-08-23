# Raw ad corpus (T4b, T25)

`ads.jsonl` — 208 real job ads across seven job families, one JSON object per line,
sorted by `id`:

| field | meaning |
|-------|---------|
| `id` | `<source>-<native id>` |
| `source` | board it came from |
| `source_url` | resolvable URL of the live ad |
| `fetched_at` | ISO-8601 UTC fetch timestamp |
| `language` | `es` / `en` / `ca`, detected with `py3langid` over the ad text |
| `title`, `company` | as published |
| `job_family` | the family the ad advertises for; `programming` is T4b's slice, the rest are T25's |
| `text` | the ad body, verbatim apart from HTML→text and whitespace collapsing |

**No labels.** Labelling is T5, and it covers the `programming` 100 only — the six
families T25 added are unlabelled raw text, which T26 sequences.

## Provenance

### The `programming` slice (T4b, 100 ads)

| source | language | n | remote filter |
|--------|----------|---|---------------|
| tecnoempleo | es | 53 | board's own `teletrabajo` listing |
| manfred | es 7, en 2 | 9 | `remotePercentage == 100` |
| weworkremotely | en | 20 | remote-only board |
| remotive | en | 3 | remote-only board |
| feinaactiva | ca | 15 | none — see below |

### The other families (T25, 108 ads)

All from Feina Activa, which is the one board in reach that advertises **every** job
family natively in the corpus's own languages. The remote boards were not used here:
their non-tech categories are customer support, sales, marketing and design — more
flavours of office work, which would have proved nothing about breadth.

| family | language | n |
|--------|----------|---|
| administrative | ca 11, es 7 | 18 |
| healthcare | ca 17, es 1 | 18 |
| hospitality | ca 12, es 6 | 18 |
| retail | ca 12, es 6 | 18 |
| teaching | ca 16, es 2 | 18 |
| trades | ca 7, es 11 | 18 |

No English: these are on-site roles in Catalonia, advertised in Catalan and Spanish.
T25 asked for the same three languages as T4b, which is a whitelist on what may enter
the corpus (`detect_language` admits nothing else) — not a per-family quota, and there
is no English-language board advertising Catalan hospitality work to collect from.

**How an ad gets its family.** `integral.corpus.classify_family` matches the ad's title
against one regex per family: exactly one match assigns the family, none or two drops
the ad. It lives in `integral.corpus`, not in the collector, so it needs no scraping
stack — T25's gate runs on a machine with no egress. Two exclusions matter:

* **Recruitment bulletins are not job adverts.** Feina Activa also carries the public
  employment service's hiring announcements ("Borsa de treball de places de …",
  "Convocatòria …", CIDO notices). They are near-identical administrative boilerplate;
  12 of the first teaching sweep's 18 were one of these. `FAMILY_NOT_RE` drops them.
* **A title naming two families is dropped, not guessed.** School-canteen posts really
  are advertised as "Cuiner/a i monitor/a de menjador" — hospitality and teaching at
  once. Guessing would teach the wrong vocabulary for both.

(Two Manfred ads are written in English despite the board being Spanish; they are
counted as `en` because the corpus language is a property of the text, not the board.)

Every ad was fetched from a live board. Nothing is synthetic, translated or
paraphrased (`status/specification.md` risk register: a corpus of invented ads
makes every numeric gate pass while measuring nothing).

## Known divergence — the Catalan slice is Catalan IT ads, not remote programming

*This section is about the **`programming`** slice's Catalan 15 and nothing else.*
*T25's six families are a separate slice with its own account above; their Catalan*
*ads are on-site work in Catalonia and were never remote-filtered to begin with.*

**This is a decision (D-1), not an oversight.** T4b originally asked for
**remote programming** ads in all three languages. Natively-Catalan *remote
programming* ads barely exist: a full keyword sweep of Feina Activa (the one
board whose ads are written in Catalan rather than translated into it, ~5 500
live offers) returns under ten — a fact about the Catalan-language job market,
not a collection shortfall, and no amount of harvesting effort changes it. The
available shortcut — teletreballa.com republishes Feina Activa ads
machine-translated into Catalan, which would have made the count trivially —
was rejected on principle and stays rejected: those are not verbatim originals,
and the spec's risk register forbids padding the corpus with text that is not
the real ad. Shrinking the Catalan target and growing the Spanish one was
considered and rejected too: the Catalan slice's job is Catalan job-ad
*vocabulary* for the ontology, and that job does not require the ads to be
remote — a Catalan sysadmin ad teaches the same vocabulary as a Catalan
remote-developer ad.

So: **the Catalan 15 are Catalan IT ads at large** (developer, sysadmin, data,
cybersecurity, TIC consulting), stated honestly as such, with the remote
dimension mixed in rather than filtered for — unlike ES and EN, which are
remote-filtered at source. Measured against the actual text (not assumed):
6 of the 15 contain the string `teletreball`/`remot`, but close reading narrows
that to 2 ads that actually offer telework as part of the role
(`feinaactiva-FA92317375`: "Possibilitat de 95% teletreball"; `feinaactiva-FA92317378`:
"Més del 50% de la jornada de teletreball"). The other 4 hits use `remot` to
describe **remote IT support delivered to end users** — a duty, not the
position's own arrangement — and one of those four
(`feinaactiva-FA92318000`) is explicitly on-site ("LLOC DE TREBALL PRESENCIAL A
VIC"). The remaining 9 Catalan ads say nothing about work location at all.

`status/plan.md` (T4b row), `tests/test_corpus_raw.py` (`TARGET_MIX`, via
`integral.corpus_scope` — measured over the `programming` slice, which is the slice
`TARGET_MIX` describes) and this section are checked against each other
mechanically by `integral.corpus_scope` — `corpus_language_slice_mismatch == 0`
fails if any of the three stops agreeing with the other two, rather than
trusting three hand-edited documents to stay in sync. **Labelling (T5) must
extract `remote_arrangement` from each Catalan ad's own text — never assume a
Catalan ad is remote because the corpus overall skews that way, and never
assume it is on-site either; both directions are represented.**

## Reproducing / extending

Reading the corpus needs nothing but the stdlib:

```python
from integral.corpus import load_ads, job_family_counts, language_counts

ads = load_ads()  # raises on any entry without a resolvable source_url or a job_family
job_family_counts(ads)  # {'administrative': 18, ..., 'programming': 100, ...}
```

Collecting more needs the scraping stack and egress to the boards:

```bash
uv run --extra collect python tools/collect_ads.py \
    --target-es 60 --target-en 25 --target-ca 15 --target-family 18
uv run python -m integral.corpus     # recount → status/evidence/T4b.json and T25.json
make test
```

Re-running the collector merges by `id` into the existing file and tops up whichever
language or family is short, so collection can happen over several sittings. It skips
ids it already holds before fetching their detail pages, so a top-up run reaches ads it
has not seen rather than re-walking the ones it has. Requires egress to the job boards —
cloud sessions are blocked at the proxy, hence the `laptop` tag.

Reading the corpus still needs nothing but the stdlib, deliberately: `integral.corpus`
imports no part of the scraping stack, so T4b's and T25's gates run wherever the repo
does.
