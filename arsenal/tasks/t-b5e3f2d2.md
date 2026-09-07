---
id: t-b5e3f2d2
title: "T146: The claim manifest traces assertions \u2014 a denial and a count go untraced"
priority: 5
tags: [PROFILE]
workspace: PROFILE
issue: 391
---

## Acceptance gate

```gate
untraced_claim_defects == 0
evidence: status/evidence/T146.json
key: untraced_claim_defects
```

```bash
uv run --extra dev pytest tests/test_claim_trace.py -q
uv run --extra dev python -m integral.claim_trace
```

T45 requires every claim in a generated document to trace to a store entry, and
`cv_generation_traceability == 1.0` says it does. The first live run shipped two
claims that traced to nothing, and the number was green for both.

**A denial.** The letter said *"I have not used observability tools"*. It was
false: the candidate had used Honeycomb at Flanks for years and understands
queries and traces. Nothing in the store said he had not — nothing needed to,
because a manifest that traces assertions has no row to demand for an absence.
This is the worst class of error the tool can make. It is an invented fact about
the candidate, in the direction of making him smaller, sent to an employer over
his name. It reached the PDF and was caught only because he read it.

**A count.** *"~1,600 commits across seven repositories, six published"* was
true when written and stale within the same session as the project list grew.
The candidate: *"ha quedado obsoleto con nuestra lista. Mejor no poner un
número."*

Both holes have the same shape — a claim whose truth-maker is not an entry the
manifest can point at — so both close the same way:

- **A denial needs a backing row exactly as an assertion does.** "The candidate
  has not done X" is a claim about the candidate. Where the store is silent, the
  honest sentence is about the store, not about the person.
- **A number in a document is computed or it is not written.** A count typed
  into prose has no source of truth and begins ageing the moment it is typed.

The measurement extends T45's: run the generator over the labelled corpus as it
already does, and add a case per hole. A denial with no backing row must be
refused; a hand-typed count must be refused; and **a denial that does have a
backing row must pass**, so the check is not satisfiable by banning the word
"not" — which would pass this gate while destroying the honest-gap paragraph
that is one of the letter's better features.
