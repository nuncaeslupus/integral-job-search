# Raw ad corpus (T4b)

`ads.jsonl` — 100 real job ads, one JSON object per line, sorted by `id`:

| field | meaning |
|-------|---------|
| `id` | `<source>-<native id>` |
| `source` | board it came from |
| `source_url` | resolvable URL of the live ad |
| `fetched_at` | ISO-8601 UTC fetch timestamp |
| `language` | `es` / `en` / `ca`, detected with `py3langid` over the ad text |
| `title`, `company` | as published |
| `text` | the ad body, verbatim apart from HTML→text and whitespace collapsing |

**No labels.** Labelling is T5.

## Provenance

| source | language | n | remote filter |
|--------|----------|---|---------------|
| tecnoempleo | es | 53 | board's own `teletrabajo` listing |
| manfred | es 7, en 2 | 9 | `remotePercentage == 100` |
| weworkremotely | en | 20 | remote-only board |
| remotive | en | 3 | remote-only board |
| feinaactiva | ca | 15 | none — see below |

(Two Manfred ads are written in English despite the board being Spanish; they are
counted as `en` because the corpus language is a property of the text, not the board.)

Every ad was fetched from a live board. Nothing is synthetic, translated or
paraphrased (`status/specification.md` risk register: a corpus of invented ads
makes every numeric gate pass while measuring nothing).

## Known divergence — the Catalan slice

T4b asks for **remote programming** ads in all three languages. Natively-Catalan
*remote programming* ads barely exist: a full sweep of Feina Activa (the one
board whose ads are written in Catalan rather than translated into it, ~5 500
live offers) yields fewer than ten, and most Catalan employers post in Spanish
or English. Rather than pad the slice with machine-translated text — teletreballa.com
republishes Feina Activa ads in translated Catalan, which would have made the count
trivially — the Catalan 15 are **IT roles at large** (developer, sysadmin, data,
cybersecurity, TIC consulting), 5 of which mention teletreball/remote work.

The Catalan slice therefore covers Catalan job-ad *vocabulary*, which is what the
ontology needs, but is not a like-for-like remote-programming sample. Tracked as a
queue task; labelling (T5) should treat the remote dimension on these as genuinely
mixed rather than assumed-remote.

## Reproducing / extending

Reading the corpus needs nothing but the stdlib:

```python
from jobsearch.corpus import load_ads, language_counts
ads = load_ads()  # raises on any entry without a resolvable source_url
```

Collecting more needs the scraping stack and egress to the boards:

```bash
uv run --extra collect python tools/collect_ads.py --target-es 60 --target-en 25 --target-ca 15
uv run python -m jobsearch.corpus status/evidence/T4b.json   # recount → evidence
make test
```

Re-running the collector merges by `id` into the existing file and tops up whichever language
is short, so collection can happen over several sittings. Requires egress to the
job boards — cloud sessions are blocked at the proxy, hence the `laptop` tag.
