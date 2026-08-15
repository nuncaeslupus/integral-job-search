# D-1: Catalan corpus slice covers IT roles at large, not remote programming as T4b specifies

## What the spec requires

`status/plan.md` T4b and `status/specification.md` §"corpus_size >= 100": ≥100 raw
ads for **remote programming roles**, ≈60 ES / 25 EN / 15 CA.

## What the code does

`corpus/raw/ads.jsonl` holds 100 ads with the target language mix, but the 15
Catalan ads are IT roles at large — developer, sysadmin, data, cybersecurity, TIC
consulting — and only 5 of them mention teletreball/remote. The ES and EN slices
are remote-filtered at source and match the spec.

Cause: natively-Catalan remote-programming ads barely exist. A full keyword sweep of
Feina Activa — the one board publishing ads written in Catalan rather than
translated into it — returns under ten. The available shortcut (teletreballa.com
republishes Feina Activa ads machine-translated into Catalan) was rejected: those
are not verbatim originals, and the spec's risk register forbids padding the corpus
with text that is not the real ad.

## Fix location

Decide one of:

1. **Accept and amend the spec** — restate T4b's Catalan slice as "Catalan IT ads"
   and note in `docs/METHODS.md` that the remote dimension is mixed there. Cheapest,
   and the Catalan slice still does its real job (Catalan job-ad vocabulary for the
   ontology).
2. **Re-scope the language mix** — shift the Catalan target down (e.g. 8) and the
   Spanish target up, keeping every slice strictly remote-programming.
3. **Find another native-Catalan source** — university and public-sector boards
   (UOC, UPC, CTTI, Consorci AOC, DIBA) publish in Catalan; harvest and top up.

Whichever is chosen, update `tests/test_corpus_raw.py::TARGET_MIX`,
`corpus/raw/README.md` ("Known divergence"), and the T4b row in `status/plan.md`.

## Blocks

T5 (`lo-d2b2`) labelling should not assume the Catalan ads are remote.
