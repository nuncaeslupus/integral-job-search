# S4: The CV store — import, build-from-nothing, per-ad generation

## Acceptance gate

```gate
cv_generation_traceability == 1.0
evidence: status/evidence/S4.json
key: cv_generation_traceability
```

```bash
echo "no gate command defined for S4 — replace this line with the command that writes status/evidence/S4.json" >&2; exit 1
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

`cv_generation_traceability` = the fraction of claims in a generated CV that
trace to a specific entry in the store. It must be 1.0. A generated CV
containing anything not in the store is the tool inventing experience on a
candidate's behalf, which is the single worst thing this project could ship.

## Not now, but design for it

Templates: basic, always customisable, modular enough that a new one can be
assembled from chosen sections — possibly its own skill. The store's schema
should feed templates rather than one fixed layout.

## Tests

`test_every_generated_claim_traces_to_the_store`;
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
