# S4: The CV store — import, build-from-nothing, per-ad generation

## Acceptance gate

```gate
intake_field_provenance == 1.0
evidence: status/evidence/S4.json
key: intake_field_provenance
```

```bash
uv run python -m jobsearch.cv_store --write-evidence status/evidence/S4.json
```

## What this is

The CV is three things the current specification conflates (brief §2.6):

1. **Input** — supplied as PDF or DOCX, or **not existing at all**, in which
   case the tool helps build a first version rather than demanding one.
2. **Store** — `cv/master.json`, the "CV on steroids": everything a CV contains
   plus everything it omits. Episodes, failures and their lessons, tools,
   numbers, certifications, languages, the context of each role. Never sent
   anywhere as-is.
3. **Output** — a CV generated **per ad**, targeted at that ad's requirements,
   with a cover letter beside it.

## The gate

`intake_field_provenance` = the fraction of fields in `master.json` that name
where they came from — a span in a supplied document, or a turn in the
conversation. It must be 1.0. A field with no provenance is a claim nobody can
check, and step 2 promotes claims to facts by asking about them, which it
cannot do for a claim whose origin is unknown.

**The generation gate moved with the generation work.**
`cv_generation_traceability == 1.0` is now T45's, measured over the claim
manifest of a generated document rather than over the store.

## Not now, but design for it

Templates: basic, always customisable, modular enough that a new one can be
assembled from chosen sections — possibly its own skill. The store's schema
should feed templates rather than one fixed layout.

## Tests

`test_every_master_field_names_its_source`;
`test_a_candidate_with_no_cv_can_still_reach_a_first_version`;
`test_the_store_is_never_sent_verbatim`.

## Location

Service: **PROFILE** · Size: L · Depends: S1

Source: `status/spec-v2-brief.md` §2.6, §2.7

---

## Scope change — v2 plan, 2026-08-18

**Narrowed.** S4 is the CV **store**: importing pdf/docx into
`cv/master.json`, building the same store by conversation with someone who has
no CV, and pinning the `master.json` contract — which nothing else pins. It owns
step 1's gate, `intake_field_provenance == 1.0`: every field names the document
span or the conversation turn it came from.

**Per-advert generation splits out as T45.** Its gate
(`cv_generation_traceability == 1.0`) is a different measurement on a different
artefact, and it depends on an offer and an extraction that step 1 has no
business knowing about.

**Intake never produces a document.** A candidate arriving with no CV does not
get a PDF generated for them; they get the same structured store that parsing a
real CV would have produced. `cv/source/*` is stored unmodified and never sent
anywhere. Personal details — date of birth, address, telephone — are **not**
collected here; they are collected at step 11, by T46, for the document that
requires them.
